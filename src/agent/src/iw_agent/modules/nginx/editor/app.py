"""The editor session: state, key handling, and the terminal loop.

:class:`EditorSession` holds everything and reacts to key events without
touching a terminal, so the whole interaction can be driven from tests.
:func:`run_editor` is the thin shell that owns raw mode, the redraw, and the
one thing the session cannot do synchronously: saving.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from iw_agent.cli.tui.keys import Key, ctrl, decode
from iw_agent.cli.tui.screen import Screen
from iw_agent.cli.tui.terminal import Terminal, supports_fullscreen
from iw_agent.cli.tui.widgets import (
    CANCEL,
    PENDING,
    Confirm,
    LineEditor,
    Picker,
    PickerItem,
    Viewer,
)
from iw_agent.modules.nginx.confparse import Block, Directive
from iw_agent.modules.nginx.editor import view
from iw_agent.modules.nginx.editor.catalog import options_for_insert, render_template
from iw_agent.modules.nginx.editor.document import EditBuffer, EditRejected, node_at
from iw_agent.modules.nginx.editor import panel
from iw_agent.modules.nginx.editor.forms import form_for
from iw_agent.modules.nginx.editor.rows import (
    RowKind,
    build_rows,
    first_selectable,
    line_count,
    move,
    reanchor_by_path,
)
from iw_agent.modules.nginx.validation import NginxValidationError

QUIT_KEYS = {"q", ctrl("c")}


class EditorUnavailable(Exception):
    """Raised when this terminal cannot host a full-screen editor."""


@dataclass
class _Modal:
    widget: object
    on_done: object
    title: str = ""


@dataclass
class EditorSession:
    buffer: EditBuffer
    title: str
    read_only: bool = False
    dry_run: bool = False
    site_enabled: bool = True
    folded: set = field(default_factory=set)
    cursor: int = 0
    top: int = 0
    status: str = ""
    running: bool = True
    rows: list = field(default_factory=list)
    modal: _Modal | None = None
    save_requested: bool = False
    pending_action: tuple | None = None
    action_params: dict = field(default_factory=dict)
    search_matches: list[int] = field(default_factory=list)
    search_index: int = 0
    search_label: str = ""

    def __post_init__(self) -> None:
        self.rebuild()
        self.cursor = first_selectable(self.rows)

    # -- state -------------------------------------------------------------

    @property
    def document(self):
        return self.buffer.document

    @property
    def path(self) -> str:
        return self.buffer.path

    def rebuild(self, *, focus_path=None) -> None:
        self.rows = build_rows(self.document, frozenset(self.folded))
        if focus_path is not None:
            self.cursor = reanchor_by_path(self.rows, focus_path, self.cursor)

    @property
    def current(self):
        if not self.rows:
            return None
        return self.rows[min(self.cursor, len(self.rows) - 1)]

    def frame(self, height: int) -> view.Frame:
        self.top = view.clamp_scroll(
            self.top, self.cursor, view.body_height(height), len(self.rows),
        )
        return view.Frame(
            title=self.title,
            path=self.path,
            rows=self.rows,
            cursor=self.cursor,
            top=self.top,
            status=self.status,
            read_only=self.read_only,
            dry_run=self.dry_run,
            site_enabled=self.site_enabled,
            search_label=self.search_label,
            dirty_count=self.buffer.changed_lines(),
            modal=self._modal_view(),
        )

    def _modal_view(self):
        if self.modal is None:
            return None
        return view.Modal(title=self.modal.title, widget=self.modal.widget)

    # -- input -------------------------------------------------------------

    def handle(self, event, *, height: int = 24) -> None:
        if self.modal is not None:
            self._handle_modal(event)
            return

        self.status = ""
        page = max(1, view.body_height(height) - 2)

        if event in QUIT_KEYS:
            self._quit()
        elif event in (Key.DOWN, "j"):
            self.cursor = move(self.rows, self.cursor, 1)
        elif event in (Key.UP, "k"):
            self.cursor = move(self.rows, self.cursor, -1)
        elif event is Key.PAGE_DOWN:
            self.cursor = move(self.rows, self.cursor, page)
        elif event is Key.PAGE_UP:
            self.cursor = move(self.rows, self.cursor, -page)
        elif event in (Key.HOME, "g"):
            self.cursor = first_selectable(self.rows)
        elif event in (Key.END, "G"):
            self.cursor = move(self.rows, self.cursor, len(self.rows))
        elif event in (Key.RIGHT, "l"):
            self._expand()
        elif event in (Key.LEFT, "h"):
            self._collapse()
        elif event is Key.ENTER:
            self._activate()
        elif event == "e":
            self._raw_edit()
        elif event in ("a", "A"):
            self._add(first_child=(event == "A"))
        elif event == "d":
            self._delete()
        elif event in ("u", ctrl("z")):
            self._undo()
        elif event == ctrl("r"):
            self._redo()
        elif event == "s":
            self._save()
        elif event == "x":
            self._open_actions()
        elif event == "o":
            self._toggle_site()
        elif event == "/":
            self._start_search()
        elif event == "n":
            self._next_search(reverse=False)
        elif event == "N":
            self._next_search(reverse=True)
        elif event == "?":
            self._open_help()

    def _handle_modal(self, event) -> None:
        modal = self.modal
        result = modal.widget.handle(event)
        if result is PENDING:
            return
        self.modal = None
        if result is CANCEL:
            self.status = "cancelled"
            return
        modal.on_done(result)

    # -- navigation --------------------------------------------------------

    def _expand(self) -> None:
        row = self.current
        if row is None or not isinstance(row.node, Block):
            return
        if id(row.node) in self.folded:
            self.folded.discard(id(row.node))
            self.rebuild(focus_path=row.path)
            return
        self.cursor = move(self.rows, self.cursor, 1)

    def _collapse(self) -> None:
        row = self.current
        if row is None:
            return
        if isinstance(row.node, Block) and id(row.node) not in self.folded:
            self.folded.add(id(row.node))
            self.rebuild(focus_path=row.path)
            return
        if len(row.path) > 1:
            self.cursor = reanchor_by_path(self.rows, row.path[:-1], self.cursor)

    # -- editing -----------------------------------------------------------

    def _guard(self) -> bool:
        if self.read_only:
            self.status = "read-only — rerun with sudo to edit"
            return False
        return True

    def _activate(self) -> None:
        row = self.current
        if row is None:
            return
        if row.kind is RowKind.ADD_SLOT:
            if self._guard():
                self._open_picker(row.insert_parent, row.insert_index, row.path)
            return

        node = row.node
        if isinstance(node, Block):
            form = form_for(node.name, block=True)
            if form is None:
                self._collapse() if id(node) not in self.folded else self._expand()
                return
            if not self._guard():
                return
            self._open_value_form(row, form, " ".join(node.args))
            return

        if isinstance(node, Directive):
            form = form_for(node.name)
            if form is not None:
                if not self._guard():
                    return
                self._open_value_form(row, form, " ".join(node.args))
                return

        self._raw_edit()

    def _open_value_form(self, row, form, value: str) -> None:
        path = row.path
        editor = LineEditor(value, title=form.label, hint=form.help or form.placeholder)

        def commit(text: str) -> None:
            try:
                args = form.parse(text)
                self.buffer.set_args(path, args)
            except (NginxValidationError, EditRejected) as exc:
                self.status = _reason(exc)
                return
            self.rebuild(focus_path=path)
            self.status = f"{form.label} updated"

        self.modal = _Modal(editor, commit, title=form.label)

    def _raw_edit(self) -> None:
        row = self.current
        if row is None or row.node is None or not self._guard():
            return
        if isinstance(row.node, Block):
            self.status = "edit the lines inside the block, or its header value"
            return
        if line_count(row.node) != 1:
            self.status = "this spans several lines — delete it and add it again"
            return

        path = row.path
        editor = LineEditor(row.text, title="raw line", hint="checked by re-parsing")

        def commit(text: str) -> None:
            try:
                self.buffer.replace_lines(path, text)
            except EditRejected as exc:
                self.status = _reason(exc)
                return
            self.rebuild(focus_path=path)
            self.status = "line updated"

        self.modal = _Modal(editor, commit, title="raw line")

    def _add(self, *, first_child: bool) -> None:
        row = self.current
        if row is None or not self._guard():
            return

        if row.kind is RowKind.ADD_SLOT:
            self._open_picker(row.insert_parent, row.insert_index, row.path)
            return

        if first_child and isinstance(row.node, Block):
            self._open_picker(row.node, 0, row.path)
            return

        parent_path = row.path[:-1]
        parent = node_at(self.document, parent_path) if parent_path else self.document
        self._open_picker(parent, row.path[-1] + 1, parent_path)

    def _open_picker(self, parent, index: int, parent_path) -> None:
        options = options_for_insert(parent, index)
        context = "file" if parent is self.document else getattr(parent, "name", "") or "block"
        picker = Picker(
            [PickerItem(option.label, option.hint, option) for option in options],
            title=f"add to {context}",
        )

        def commit(item) -> None:
            option = item.value
            text = render_template(
                option,
                self.buffer.indent_for(parent_path),
                self.buffer.indent_unit(),
            )
            try:
                new_path = self.buffer.insert_lines(parent_path, index, text)
            except EditRejected as exc:
                self.status = _reason(exc)
                return
            self.rebuild(focus_path=new_path)
            self.status = f"added {option.label}"

        self.modal = _Modal(picker, commit, title=picker.title)

    def _delete(self) -> None:
        row = self.current
        if row is None or row.node is None or not self._guard():
            return
        if row.kind is RowKind.ADD_SLOT:
            return

        path = row.path
        lines = line_count(row.node)
        detail = f"{lines} lines" if lines > 1 else row.text.strip()
        confirm = Confirm(
            f"Delete {detail}?",
            require_word="YES" if lines > 3 else "",
        )

        def commit(answer) -> None:
            if not answer:
                self.status = "kept"
                return
            try:
                self.buffer.delete(path)
            except EditRejected as exc:
                self.status = _reason(exc)
                return
            self.rebuild(focus_path=path)
            self.status = "deleted"

        self.modal = _Modal(confirm, commit, title="delete")

    def _undo(self) -> None:
        if self.buffer.undo():
            self.rebuild()
            self.cursor = min(self.cursor, max(0, len(self.rows) - 1))
            self.status = "undone"
        else:
            self.status = "nothing to undo"

    def _redo(self) -> None:
        if self.buffer.redo():
            self.rebuild()
            self.cursor = min(self.cursor, max(0, len(self.rows) - 1))
            self.status = "redone"
        else:
            self.status = "nothing to redo"

    def _save(self) -> None:
        if not self.buffer.dirty:
            self.status = "no changes to save"
            return
        if not self.dry_run and not self._guard():
            return
        self.save_requested = True

    def _start_search(self) -> None:
        editor = LineEditor(
            self.search_label,
            title="search",
            hint="plain text or regex",
        )

        def commit(text: str) -> None:
            self._apply_search(text)

        self.modal = _Modal(editor, commit, title="search")

    def _apply_search(self, pattern: str) -> None:
        query = pattern.strip()
        if not query:
            self.search_matches = []
            self.search_index = 0
            self.search_label = ""
            self.status = "search cleared"
            return
        try:
            matcher = re.compile(query, re.IGNORECASE)
        except re.error as exc:
            self.status = f"invalid pattern: {exc}"
            return

        matches = [
            index
            for index, row in enumerate(self.rows)
            if row.selectable and matcher.search(row.text)
        ]
        if not matches:
            self.search_label = query
            self.search_matches = []
            self.status = f"no match for {query!r}"
            return

        self.search_matches = matches
        self.search_index = 0
        self.search_label = query
        self.cursor = matches[0]
        self.status = f"match 1/{len(matches)}"

    def _next_search(self, *, reverse: bool) -> None:
        if not self.search_matches:
            self.status = "no active search — press /"
            return
        step = -1 if reverse else 1
        self.search_index = (self.search_index + step) % len(self.search_matches)
        self.cursor = self.search_matches[self.search_index]
        self.status = f"match {self.search_index + 1}/{len(self.search_matches)}"

    def _open_help(self) -> None:
        viewer = Viewer(view.HELP_LINES, title="help")
        self.modal = _Modal(viewer, lambda _result: None, title="help")

    # -- actions panel -----------------------------------------------------

    def _toggle_site(self) -> None:
        if self.read_only and not self.dry_run:
            self.status = "read-only — rerun with sudo"
            return
        action_id = "disable_site" if self.site_enabled else "enable_site"
        action = panel.action_for(action_id)
        if action is None:
            return
        if action.destructive:
            self._confirm_then_run(action)
            return
        self.pending_action = (action, {})

    def _open_actions(self) -> None:
        actions = panel.available(dirty=self.buffer.dirty, site_enabled=self.site_enabled)
        picker = Picker(
            [PickerItem(a.label, a.hint, a) for a in actions],
            title="actions",
        )

        def commit(item) -> None:
            self._start_action(item.value)

        self.modal = _Modal(picker, commit, title="actions")

    def _start_action(self, action) -> None:
        if action.local:
            self._local_action(action)
            return
        if self.read_only and action.action_id != "test_config":
            self.status = "read-only — rerun with sudo"
            return
        if action.needs_email:
            self._ask_email(action)
            return
        if action.destructive:
            self._confirm_then_run(action)
            return
        self.pending_action = (action, {})

    def _ask_email(self, action) -> None:
        editor = LineEditor(
            "",
            title=action.label,
            hint="contact email for Let's Encrypt",
        )

        def commit(text: str) -> None:
            if not text.strip():
                self.status = "an email is required"
                return
            self.pending_action = (action, {"email": text.strip()})

        self.modal = _Modal(editor, commit, title=action.label)

    def _confirm_then_run(self, action) -> None:
        confirm = Confirm(f"{action.label}?", detail=action.hint)

        def commit(answer) -> None:
            if answer:
                self.pending_action = (action, {})
            else:
                self.status = "cancelled"

        self.modal = _Modal(confirm, commit, title=action.label)

    def _local_action(self, action) -> None:
        if action.key == "diff":
            self.modal = _Modal(
                Viewer(self.buffer.diff().splitlines(), title="unsaved changes"),
                lambda _result: None,
                title="unsaved changes",
            )
        elif action.key == "revert":
            confirm = Confirm(
                f"Discard {self.buffer.changed_lines()} changed lines?",
            )

            def commit(answer) -> None:
                if not answer:
                    self.status = "kept"
                    return
                while self.buffer.can_undo():
                    self.buffer.undo()
                self.rebuild()
                self.cursor = min(self.cursor, max(0, len(self.rows) - 1))
                self.status = "reverted to the file on disk"

            self.modal = _Modal(confirm, commit, title="discard changes")
        elif action.key == "reread":
            self.reload_from_disk()

    def reload_from_disk(self) -> None:
        text = Path(self.path).read_text(encoding="utf-8", errors="replace")
        if text == self.buffer.text:
            self.status = "already up to date"
            return
        self.buffer = EditBuffer(text, self.path)
        self.folded.clear()
        self.rebuild()
        self.cursor = first_selectable(self.rows)
        self.status = "reloaded from disk"

    def _quit(self) -> None:
        if not self.buffer.dirty:
            self.running = False
            return

        confirm = Confirm(f"Discard {self.buffer.changed_lines()} changed lines?")

        def commit(answer) -> None:
            if answer:
                self.running = False
            else:
                self.status = "still here"

        self.modal = _Modal(confirm, commit, title="unsaved changes")


def _reason(exc: Exception) -> str:
    text = str(exc)
    return text.split("] ", 1)[-1] if "] " in text else text


# -- entry -----------------------------------------------------------------


def load_session(
    config_path: str,
    *,
    title: str = "",
    read_only: bool = False,
    dry_run: bool = False,
    site_enabled: bool = True,
    action_params: dict | None = None,
) -> EditorSession:
    text = Path(config_path).read_text(encoding="utf-8", errors="replace")
    return EditorSession(
        buffer=EditBuffer(text, config_path),
        title=title or Path(config_path).name,
        read_only=read_only,
        dry_run=dry_run,
        site_enabled=site_enabled,
        action_params=action_params or {},
    )


async def _perform_save(session: EditorSession) -> None:
    from iw_agent.modules.nginx.editor.actions import save_config

    session.save_requested = False
    session.status = "saving…"
    result = await save_config(
        config_path=session.path,
        content=session.buffer.text,
        expected_sha256=session.buffer.base_sha256,
        params=session.action_params,
        dry_run=session.dry_run,
    )
    session.status = result.message.replace("\n", " · ")
    if result.ok and not session.dry_run:
        session.buffer.mark_saved()


async def _perform_action(session: EditorSession) -> None:
    from iw_agent.modules.nginx.editor.actions import run_named_action

    action, extra = session.pending_action
    session.pending_action = None
    session.status = f"{action.label}…"
    result = await run_named_action(
        action_id=action.action_id,
        config_path=session.path,
        params={**session.action_params, **extra},
        dry_run=session.dry_run,
    )
    session.status = result.message.replace("\n", " · ")
    if result.ok and action.action_id == "enable_site":
        session.site_enabled = True
    elif result.ok and action.action_id == "disable_site":
        session.site_enabled = False
    if result.ok and action.action_id in {"secure_site", "attach_ssl"}:
        # certbot rewrites the file underneath us
        session.reload_from_disk()


async def run_editor(session: EditorSession, *, terminal: Terminal | None = None) -> None:
    if terminal is None and not supports_fullscreen():
        raise EditorUnavailable(
            "the editor needs an interactive terminal — try `iw nginx` for the read-only view",
        )

    owned = terminal is None
    term = terminal or Terminal()
    context = term if owned else _NullContext(term)

    with context:
        width, height = term.size()
        screen = Screen(term.write, width=width, height=height)
        pending = b""

        while session.running:
            new_width, new_height = term.size()
            if (new_width, new_height) != (screen.width, screen.height):
                screen.resize(new_width, new_height)
            view.render(screen, session.frame(screen.height))
            screen.flush()

            try:
                chunk = term.read()
            except KeyboardInterrupt:
                break
            if not chunk:
                continue

            pending += chunk
            events, pending = decode(pending)
            if pending == b"\x1b":
                # a lone ESC is ambiguous: give the rest of a sequence one
                # short beat to arrive before calling it an Escape keypress
                tail = term.wait_for_escape_tail()
                if tail:
                    pending += tail
                    more, pending = decode(pending)
                    events += more
                else:
                    events.append(Key.ESCAPE)
                    pending = b""
            # anything else left over is an incomplete sequence — the next
            # read completes it, so it must not be flushed here

            for event in events:
                session.handle(event, height=screen.height)
                if not session.running:
                    break

            if session.save_requested:
                await _perform_save(session)
            if session.pending_action is not None:
                await _perform_action(session)


class _NullContext:
    def __init__(self, value):
        self._value = value

    def __enter__(self):
        return self._value

    def __exit__(self, *_exc):
        return None

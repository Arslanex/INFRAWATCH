"""Safe whole-file writes for nginx configs.

The existing patchers write with ``path.write_text``, which truncates in
place: a crash mid-write leaves a root-owned nginx config half written. They
also run ``nginx -t`` only *after* the write, with no way back — ``.iw.bak`` is
guarded by ``if not exists`` so it holds the first-ever original, not the
previous revision.

This module provides the pieces a structural editor needs to write a whole
file safely, and keeps them independent of the executor so they can be tested
without an action pipeline.
"""
from __future__ import annotations

import difflib
import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

# first-ever snapshot; other actions already rely on this name and semantic
PRISTINE_SUFFIX = ".iw.bak"
# overwritten on every write — this is what a rollback restores from
ROLLBACK_SUFFIX = ".iw.prev"

MAX_CONFIG_BYTES = 1024 * 1024


class ConfigConflictError(Exception):
    """The file on disk is not the revision the caller started from."""


@dataclass(frozen=True)
class WriteOutcome:
    changed: bool
    message: str
    rollback_path: str | None = None
    diff: str = ""


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def unified_diff(before: str, after: str, path: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a{path}",
            tofile=f"b{path}",
            n=3,
        )
    )


def diff_stat(before: str, after: str) -> tuple[int, int]:
    """(added, removed) line counts, for the audit message."""
    added = removed = 0
    for line in difflib.ndiff(before.splitlines(), after.splitlines()):
        if line.startswith("+ "):
            added += 1
        elif line.startswith("- "):
            removed += 1
    return added, removed


def atomic_write(path: Path, text: str) -> None:
    """Replace ``path`` in one step, preserving ownership and permissions.

    The temporary file is created in the same directory so ``os.replace`` stays
    on one filesystem and is therefore atomic.
    """
    directory = path.parent
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(directory),
        prefix=f".{path.name}.",
        suffix=".iw-tmp",
        delete=False,
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        _copy_file_identity(path, temp_path)
        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def _copy_file_identity(source: Path, target: Path) -> None:
    """Carry mode and ownership from an existing file onto its replacement."""
    try:
        stat = source.stat()
    except FileNotFoundError:
        return
    try:
        os.chmod(target, stat.st_mode & 0o7777)
    except OSError:
        pass
    try:
        os.chown(target, stat.st_uid, stat.st_gid)
    except (OSError, AttributeError):
        # not root, or a platform without chown — mode still carried over
        pass


def take_backups(path: Path) -> Path:
    """Snapshot before a write. Returns the path a rollback should restore."""
    pristine = Path(f"{path}{PRISTINE_SUFFIX}")
    if not pristine.exists():
        shutil.copy2(path, pristine)
    rollback = Path(f"{path}{ROLLBACK_SUFFIX}")
    shutil.copy2(path, rollback)
    return rollback


def restore(path: Path, rollback_path: Path) -> None:
    atomic_write(path, rollback_path.read_text(encoding="utf-8", errors="replace"))


def guard_content(content: str) -> None:
    if not content.strip():
        raise ValueError("config is empty")
    if len(content.encode("utf-8")) > MAX_CONFIG_BYTES:
        raise ValueError(f"config is larger than {MAX_CONFIG_BYTES} bytes")


def guard_revision(path: Path, expected_sha256: str | None) -> str:
    """Optimistic lock: refuse to write over someone else's change."""
    current = path.read_text(encoding="utf-8", errors="replace")
    if expected_sha256 and sha256_text(current) != expected_sha256:
        raise ConfigConflictError(
            f"{path} changed on disk since it was opened — reload before saving",
        )
    return current

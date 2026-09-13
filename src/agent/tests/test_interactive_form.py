"""Form prompts retry instead of aborting on bad input."""
import pytest

from iw_agent.cli.interactive.form import prompt_text


def test_prompt_text_retries_on_validation_error(monkeypatch):
    answers = iter(["bad", "app.example.com"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    value = prompt_text("Domain", validator=lambda raw: "nope" if raw == "bad" else None)

    assert value == "app.example.com"


def test_prompt_text_returns_none_on_quit(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt="": "q")

    assert prompt_text("Domain") is None

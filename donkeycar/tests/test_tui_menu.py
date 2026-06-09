import pytest

from donkeycar.management import tui


def test_main_menu_exit_confirmation_defaults_to_yes(monkeypatch):
    defaults = []

    monkeypatch.setattr(tui.console, "clear", lambda: None)
    monkeypatch.setattr(tui.console, "print", lambda *args, **kwargs: None)
    monkeypatch.setattr(tui.Prompt, "ask", lambda *args, **kwargs: "0")

    def confirm_exit(*args, **kwargs):
        defaults.append(kwargs.get("default"))
        return True

    monkeypatch.setattr(tui.Confirm, "ask", confirm_exit)

    with pytest.raises(SystemExit):
        tui.MenuSystem().show_main_menu()

    assert defaults == [True]


def test_main_menu_sixth_item_is_drive_page():
    command = tui.MenuSystem().flat_commands[5]

    assert command.name == "drive"
    assert "Web Console" in command.description

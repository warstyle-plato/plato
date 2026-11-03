from types import SimpleNamespace

from mpt_bot_menu import _MENU_TEXT, install


class DummyCore:
    TELEGRAM_BOT_COMMANDS = [{"command": "vritep", "description": "ВРИ и ТЭП"}]

    @staticmethod
    def _telegram_web_app_url(chat_id, cad):
        return f"https://example.test/app?session=chat-{chat_id}"


def _base():
    base = SimpleNamespace()
    base.core = DummyCore()
    base._help_markup = lambda chat_id: {
        "inline_keyboard": [
            [{"text": "Посчитать ВРИ и ТЭП", "callback_data": "vritep_start"}],
            [{"text": "Спросить Платона", "callback_data": "ask_platon"}],
        ]
    }
    return base


def test_help_menu_gets_separate_mpt_webapp_entry():
    base = _base()
    install(base)
    markup = base._help_markup(123)
    buttons = [button for row in markup["inline_keyboard"] for button in row]
    mpt = [button for button in buttons if button.get("text") == _MENU_TEXT]
    assert len(mpt) == 1
    assert "session=chat-123" in mpt[0]["web_app"]["url"]
    assert "section=mpt" in mpt[0]["web_app"]["url"]


def test_slash_command_is_registered_once():
    base = _base()
    install(base)
    commands = base.core.TELEGRAM_BOT_COMMANDS
    assert [item["command"] for item in commands].count("mpt") == 1
    install(base)
    assert [item["command"] for item in commands].count("mpt") == 1


def test_temporary_inline_keyboard_is_not_modified():
    base = _base()
    install(base)
    temporary = {"inline_keyboard": [[{"text": "Да", "callback_data": "yes"}]]}
    # Exercise the installed logic through a temporary original menu.
    base2 = _base()
    base2._help_markup = lambda chat_id: temporary
    install(base2)
    assert base2._help_markup(1) is temporary

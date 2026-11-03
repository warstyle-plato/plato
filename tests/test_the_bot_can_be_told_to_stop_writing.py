"""«Бот пишет в чат ерунду. Как сделать, чтобы не писал» (владелец, 14.09.2026).

Ответа не было. Бот пишет сам, без вопроса, по четырём поводам — новинки
каталога КРТ, изменения нормативной базы, новые регистрации и ежедневная
сводка, — и выключателя не имел ни один: `/krt выкл` отвечало «подписка
выключена» и владельца не трогало вовсе (рассылка шла ему по признаку
владельца, мимо подписки), а у остальных трёх подписки не было в принципе.

Здесь проверяется то, что видно человеку: сказал «выключить» — перестало
приходить, и список состояний говорит то же самое, что делает рассылка. Вторая
половина не украшение: правило и подпись жили порознь, и первая же проба
показала «включено» у выключенной рассылки при верно молчащей рассылке.

Запуск: python3 -m pytest tests/test_the_bot_can_be_told_to_stop_writing.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OWNER = 777
GUEST = 555


@pytest.fixture()
def bot(tmp_path, monkeypatch):
    """Бот на одном хосте: ядро рядом, ходить за настройкой некуда."""
    import main as wrapper

    core = wrapper.core
    monkeypatch.setattr(core, "_PROJECTS_DIR", tmp_path / "projects")
    core._PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(core, "_projects_remote_url", lambda path: "")
    monkeypatch.setattr(core, "usage_admin_ids", lambda: {OWNER})
    monkeypatch.setattr(core, "_telegram_token", lambda: "t")
    monkeypatch.setattr(core, "_telegram_webhook_enabled", lambda: True)
    sent: list[tuple[int, str]] = []
    monkeypatch.setattr(wrapper, "_send_message",
                        lambda chat, text, **kw: sent.append((int(chat), text)))
    monkeypatch.setattr(core, "_telegram_send_message",
                        lambda chat, text, **kw: sent.append((int(chat), text)))
    wrapper.sent = sent  # type: ignore[attr-defined]
    return wrapper


def targets(wrapper, channel: str) -> list[int]:
    return wrapper._notification_targets(
        channel, subscribers=wrapper.core.krt_recipients())


def test_every_unprompted_channel_reaches_the_owner_until_he_says_otherwise(bot) -> None:
    """Умолчание не трогаем: молчащий по умолчанию бот — другая поломка."""
    for channel in bot.core.NOTIFICATION_CHANNEL_KEYS:
        assert targets(bot, channel) == [OWNER], channel


def test_one_word_silences_all_four(bot) -> None:
    """«Как сделать, чтобы не писал» обязано отвечаться одним словом."""
    bot._notify_command(OWNER, "/notify выкл")
    for channel in bot.core.NOTIFICATION_CHANNEL_KEYS:
        assert targets(bot, channel) == [], channel


def test_a_named_channel_goes_silent_alone(bot) -> None:
    bot._notify_command(OWNER, "/notify выкл нормативы")
    assert targets(bot, "normatives") == []
    assert targets(bot, "digest") == [OWNER], \
        "выключили одну рассылку — остальные обязаны остаться"


def test_an_unknown_name_refuses_instead_of_silencing_everything(bot) -> None:
    """Молча расширенная команда хуже непонятой."""
    bot._notify_command(OWNER, "/notify выкл чепуха")
    assert "Нет такой рассылки" in bot.sent[-1][1]
    for channel in bot.core.NOTIFICATION_CHANNEL_KEYS:
        assert targets(bot, channel) == [OWNER], channel


def test_the_listing_says_what_the_delivery_does(bot) -> None:
    """Подпись состояния и правило рассылки — один ответ, а не два.

    Проба поймала ровно это: правило молчало верно, а список рядом печатал
    «включено» у всех четырёх — булев флаг подавался туда, где ждут состояние
    чата целиком, и читался как «человек ничего не говорил».
    """
    bot._notify_command(OWNER, "/notify выкл крт")
    lines = bot._notification_lines(OWNER)
    said = dict(zip(bot.core.NOTIFICATION_CHANNEL_KEYS, lines))
    for channel, line in said.items():
        goes = OWNER in targets(bot, channel)
        assert ("— включено" in line) == goes, (channel, line, goes)


def test_the_owner_is_no_longer_told_a_lie_by_the_krt_switch(bot) -> None:
    """`/krt выкл` отвечало «выключено» и не выключало ничего."""
    bot._krt_command(OWNER, "/krt выкл")
    assert "выключена" in bot.sent[-1][1]
    assert targets(bot, "krt") == [], \
        "ответ бота обязан совпасть с тем, что он делает"


def test_silencing_one_chat_does_not_silence_another(bot) -> None:
    bot._krt_subscription(GUEST, True)
    assert GUEST in targets(bot, "krt")
    bot._notify_command(OWNER, "/notify выкл")
    assert targets(bot, "krt") == [GUEST]


def test_a_missing_key_is_not_a_refusal(bot) -> None:
    """Отсутствующий ключ — «человек не говорил», а не «выключено».

    Подписчик из прежнего файла не теряет подписку от того, что настройку
    завели позже: иначе первая же выкатка молча отписала бы всех.
    """
    core = bot.core
    core._krt_subscribers_path().parent.mkdir(parents=True, exist_ok=True)
    core._krt_subscribers_path().write_text('{"chat_ids": [555]}', encoding="utf-8")
    assert core.chat_notification_overrides() == {}
    assert GUEST in targets(bot, "krt")


def test_a_switched_off_channel_says_so_instead_of_looking_empty(bot, monkeypatch) -> None:
    """Выключено получателями — это ответ, а не «изменений нет».

    Без этой строки молчание по просьбе человека и поломка доставки выглядят
    со стороны одинаково — ровно то, ради чего заведён счётчик молчания.
    """
    monkeypatch.setattr(bot.core.app.state, "normatives_announcements_take",
                        lambda: [{"short_name": "945-ПП", "result": "changed"}],
                        raising=False)
    bot._notify_command(OWNER, "/notify выкл нормативы")
    bot._deliver_normatives_announcements()
    state = bot.normatives_delivery_state()
    assert state["stopped_by"] == "выключено получателями"
    assert state["taken"] == 1 and state["sent"] == 0


def test_the_channels_are_declared_once(bot) -> None:
    """Второй список каналов разошёлся бы с первым молча."""
    keys = set(bot.core.NOTIFICATION_CHANNEL_KEYS)
    assert set(bot._NOTIFY_WORDS) == keys, \
        "слова команды обязаны покрывать ровно объявленные движком каналы"
    assert len(bot.core.NOTIFICATION_CHANNELS) == len(keys)


def test_a_flag_in_place_of_the_chat_state_is_refused(bot) -> None:
    """Сторож на ту самую ошибку: булево вместо состояния чата.

    Оно читалось как «ничего не сказано» — то есть тихо возвращало умолчание
    там, где человек уже высказался.
    """
    with pytest.raises(TypeError):
        bot.core.notification_enabled("krt", owner=True, override=False)


def test_the_catalogue_delivery_itself_goes_quiet(bot, monkeypatch) -> None:
    """Проверять надо ту дверь, в которую ходят.

    Прежняя редакция этих проверок спрашивала правило, а не доставку: подмена
    фильтра обратно на «подписчики плюс владельцы» не уронила ни одной из
    одиннадцати. Жалоба человека — «бот пишет», значит и мерить надо отправку.
    """
    monkeypatch.setattr(bot.core.app.state, "krt_announcements_take",
                        lambda: [{"kind": "site", "slug": "x", "title": "Площадка"}],
                        raising=False)
    bot._notify_command(OWNER, "/notify выкл крт")
    bot.sent.clear()
    bot._deliver_krt_announcements()
    assert bot.sent == [], "выключено — значит ни одного сообщения"
    assert bot.krt_delivery_state()["stopped_by"] == "выключено получателями"


def test_the_catalogue_delivery_still_reaches_a_subscriber(bot, monkeypatch) -> None:
    """Предохранитель: выключенная у одного рассылка обязана дойти до другого,
    иначе проверка выше зелена и на боте, который молчит всегда."""
    monkeypatch.setattr(bot.core.app.state, "krt_announcements_take",
                        lambda: [{"kind": "site", "slug": "x", "title": "Площадка"}],
                        raising=False)
    bot._krt_subscription(GUEST, True)
    bot._notify_command(OWNER, "/notify выкл крт")
    bot.sent.clear()
    bot._deliver_krt_announcements()
    assert [chat for chat, _text in bot.sent] == [GUEST]

"""Бот в групповом чате не пишет ничего и никогда.

Владелец снял privacy mode 13.09.2026, чтобы бот читал ежедневную численность
из рабочей группы. До первой правки бот отвечал «DevelopAid работает в личном
чате с ботом» на КАЖДОЕ сообщение из группы: пока privacy был включён, он
видел только команды, и это почти не замечалось, а со снятым — четырнадцать
человек получили бы поток.

Первая правка оставила ответы на адресованное — разобравшуюся сводку и
`/site`. Владелец снял и их: «И он не будет туда ничего сам писать? В чат
ничего не надо» (13.09.2026). Значит утверждение здесь теперь одно и жёсткое:
в групповой чат не уходит НИ ОДНОГО сообщения, что бы там ни написали.

Молчание при этом не может быть единственным ответом — иначе «привязалось» и
«команда не сработала» выглядят одинаково. Прочитанное видно в двух местах, и
оба проверяются ниже: личка того, кто написал команду, и счётчик `/status`.
"""

import main_legacy as core


def _chat(chat_id=-100500, title="Гродненская — реализация"):
    return {"id": chat_id, "type": "supergroup", "title": title}


AUTHOR = 4242


def _message(text, chat=None, date=1757721600, author=AUTHOR):
    return {"chat": chat or _chat(), "from": {"id": author}, "text": text, "date": date}


REPORT = """Добрый день.
1. Первый : Итр- 1чел., Рабочие - 6 чел.
2. Второй:ИТР- 11чел.;
Рабочие - 50чел.;
По работам:
1. Второй:
Корпус 2
Разборка опалубки.
"""


class _Bot:
    """Перехват отправленного: КУДА бот написал и что именно."""

    def __init__(self, monkeypatch, tmp_path, bound=""):
        self.said: list[tuple[int, str]] = []
        monkeypatch.setattr(core, "_telegram_send_message",
                            lambda chat_id, text, **kw: self.said.append((int(chat_id), text)))
        monkeypatch.setattr(core, "_telegram_token", lambda: "test-token")
        monkeypatch.setattr(core, "_PROJECTS_DIR", tmp_path / "projects")
        monkeypatch.setattr(core, "_core_api_url", lambda path: "")
        core.app.state.telegram_group_seen = {}
        self.bound = bound
        if bound:
            core._site_chat_bind(_chat()["id"], bound)

    def to_group(self, chat_id=-100500):
        return [text for where, text in self.said if where == chat_id]

    def to_author(self, user_id=AUTHOR):
        return [text for where, text in self.said if where == user_id]

    @property
    def outcome(self):
        return core.app.state.telegram_group_seen[str(_chat()["id"])].get("outcome", "")


def test_nothing_is_ever_written_into_the_group(monkeypatch, tmp_path):
    """Главное утверждение: в группу не уходит ни одного сообщения.

    Проверяется на всех четырёх поводах разом — рабочая переписка, команда
    привязки, разобравшаяся сводка и сводка в непривязанном чате. Прежде на
    трёх из четырёх бот отвечал; порознь это выглядело осмысленно, а вместе —
    как бот, вклинивающийся в чат стройки.
    """
    bot = _Bot(monkeypatch, tmp_path, bound="Гродненская")

    # Через настоящий вход бота, а не через помощника: сплошной ответ стоял
    # именно в `_telegram_handle_message`, и проверка мимо него зеленела бы на
    # том самом коде, который шумит.
    for line in ("Привет, когда бетон?", "Завтра кран приедет", "/help", "ок",
                 "/site", "/site Нагатино", REPORT):
        core._telegram_handle_message(_message(line))

    assert bot.to_group() == [], bot.to_group()


def test_an_unbound_chat_stays_silent_too(monkeypatch, tmp_path):
    """Непривязанный чат — тоже тишина: там о нашей привязке не знают."""
    bot = _Bot(monkeypatch, tmp_path)

    core._telegram_handle_message(_message(REPORT))

    assert bot.to_group() == [], bot.to_group()
    # И это не потеря: наш пробел назван в счётчике, а не выброшен молча.
    assert "не привязан" in bot.outcome, bot.outcome


def test_the_binding_is_confirmed_to_the_author_in_private(monkeypatch, tmp_path):
    """Ответ на команду уходит в личку тому, кто её набрал.

    Молчание в ответ на `/site` неотличимо от сломанной команды, а человек
    только что сам её написал — значит ответ ему не «сообщение в чат», а
    ответ на его действие. Группа при этом не видит ничего.
    """
    bot = _Bot(monkeypatch, tmp_path)

    core._telegram_handle_message(_message("/site"))

    assert bot.to_group() == []
    assert len(bot.to_author()) == 1, bot.said
    assert "Гродненская — реализация" in bot.to_author()[0]
    assert core._site_chat_project(_chat()["id"]) == "Гродненская — реализация"

    core._telegram_handle_message(_message("/site Нагатино"))
    assert core._site_chat_project(_chat()["id"]) == "Нагатино"
    assert bot.to_group() == []


def test_the_report_numbers_land_in_the_counter(monkeypatch, tmp_path):
    """Сводка сохраняется, а числа видны в `/status` — «принято» без них ничего
    не значит, и теперь это единственное место, где их вообще видно."""
    bot = _Bot(monkeypatch, tmp_path, bound="Гродненская")

    core._telegram_handle_message(_message(REPORT))

    assert bot.to_group() == []
    outcome = bot.outcome
    assert "подрядчиков 2" in outcome.lower(), outcome
    assert "ИТР 12" in outcome, outcome
    assert "рабочих 56" in outcome, outcome
    assert "Гродненская" in outcome, outcome
    # Дата берётся у сообщения и в московской зоне: день стройки ставит город,
    # а не часы читателя.
    assert "-09-13" in outcome, outcome

    line = core._telegram_group_seen_line()
    assert "Гродненская" in line and "ИТР 12" in line, line


def test_the_bot_counts_what_it_saw_in_groups(monkeypatch, tmp_path):
    """Счётчик увиденного: без него молчание нечем объяснить.

    «Privacy не сняли», «бота не переподключили» и «мост не дописан» снаружи
    выглядят одинаково — бот молчит. А с решением «в чат ничего не надо» так
    же выглядит и ИСПРАВНАЯ работа, поэтому счётчик тут единственный ответ.
    """
    _Bot(monkeypatch, tmp_path, bound="Гродненская")

    core._telegram_group_message(_chat(), _message("просто сообщение"))
    core._telegram_group_message(_chat(), _message("и ещё одно"))

    seen = core.app.state.telegram_group_seen[str(_chat()["id"])]
    assert seen["count"] == 2
    assert seen["title"] == "Гродненская — реализация"
    assert seen["last"]

    # Пустой счётчик — это ответ, а не прочерк, и он называет обе причины.
    core.app.state.telegram_group_seen = {}
    empty = core._telegram_group_seen_line()
    assert "ни одного" in empty and "privacy" in empty.lower(), empty


def test_the_project_name_never_becomes_a_path(monkeypatch, tmp_path):
    """Имя проекта становится именем каталога — значит оно проверяется на границе.

    Внутри монитора имя чистится, но чистка — это молчаливая правка чужого
    значения: «Гродненская/../x» превратилась бы в другое имя, и отчёт лёг бы
    не туда, где его ищут. Поэтому граница отказывает, а не исправляет, и
    отказ назван — в личке автора, не в чате.
    """
    bot = _Bot(monkeypatch, tmp_path)

    for bad in ("../../etc/passwd", "a/b", "..", "Гродненская/../x", "x" * 70):
        assert core._site_project_name(bad) == "", bad
    for good in ("Гродненская — реализация", "Нагатино", "ЖК «Тест» №2"):
        assert core._site_project_name(good) == good

    core._telegram_handle_message(_message("/site ../../etc/passwd"))
    assert core._site_chat_project(_chat()["id"]) == ""
    assert bot.to_group() == []
    assert bot.to_author(), bot.said
    assert "не годится" in bot.to_author()[-1] or "не удалась" in bot.to_author()[-1]


def test_a_bad_name_left_in_the_registry_is_not_trusted(monkeypatch, tmp_path):
    """Запись могла лечь до появления проверки — читаем реестр тоже через неё."""
    _Bot(monkeypatch, tmp_path)
    path = core._site_chats_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"chats": {"-100500": "../../etc"}}', encoding="utf-8")

    assert core._site_chat_project(-100500) == ""

"""Бот в групповом чате молчит, пока это не сводка с площадки.

Владелец снял privacy mode 13.09.2026, чтобы бот читал ежедневную численность
из рабочей группы. До этой правки бот отвечал «DevelopAid работает в личном
чате с ботом» на КАЖДОЕ сообщение из группы: пока privacy был включён, он
видел только команды, и это почти не замечалось, а со снятым — четырнадцать
человек получили бы поток.

Утверждение здесь одно и в две стороны: на рабочую переписку ответа нет
вовсе, на сводку есть — с числами, чтобы «принято» не было неотличимо от
«проглотил и потерял».
"""

import main_legacy as core


def _chat(chat_id=-100500, title="Гродненская — реализация"):
    return {"id": chat_id, "type": "supergroup", "title": title}


def _message(text, chat=None, date=1757721600):
    return {"chat": chat or _chat(), "from": {"id": 42}, "text": text, "date": date}


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
    """Перехват отправленного: что бот сказал в чат, и сказал ли вообще."""

    def __init__(self, monkeypatch, tmp_path, bound=""):
        self.said: list[str] = []
        self.stored: list[dict] = []
        monkeypatch.setattr(core, "_telegram_send_message",
                            lambda chat_id, text, **kw: self.said.append(text))
        monkeypatch.setattr(core, "_telegram_token", lambda: "test-token")
        monkeypatch.setattr(core, "_PROJECTS_DIR", tmp_path / "projects")
        monkeypatch.setattr(core, "_core_api_url", lambda path: "")
        self.bound = bound
        if bound:
            core._site_chat_bind(_chat()["id"], bound)


def test_ordinary_chatter_gets_no_answer(monkeypatch, tmp_path):
    """Рабочая переписка — тишина, а не «я вас не понял»."""
    bot = _Bot(monkeypatch, tmp_path, bound="Гродненская")

    # Через настоящий вход бота, а не через помощника: сплошной ответ стоял
    # именно в `_telegram_handle_message`, и проверка мимо него зеленела бы на
    # том самом коде, который шумит.
    for line in ("Привет, когда бетон?", "Завтра кран приедет", "/help", "ок"):
        core._telegram_handle_message(_message(line))

    assert bot.said == [], bot.said


def test_the_daily_report_is_stored_and_answered_with_numbers(monkeypatch, tmp_path):
    """Сводка сохраняется, а ответ несёт числа: «принято» без них ничего не значит."""
    bot = _Bot(monkeypatch, tmp_path, bound="Гродненская")

    core._telegram_group_message(_chat(), _message(REPORT))

    assert len(bot.said) == 1, bot.said
    answer = bot.said[0]
    assert "Подрядчиков 2" in answer
    assert "ИТР 12" in answer
    assert "рабочих 56" in answer
    assert "Гродненская" in answer
    # Дата берётся у сообщения и в московской зоне: день стройки ставит город,
    # а не часы читателя.
    assert "2025-09-13" in answer or "2026-09-13" in answer or "-09-13" in answer


def test_an_unbound_chat_is_told_how_to_bind(monkeypatch, tmp_path):
    """«Чат не привязан» — ответ, а не молчание: иначе сводка падает в никуда."""
    bot = _Bot(monkeypatch, tmp_path)

    core._telegram_group_message(_chat(), _message(REPORT))

    assert len(bot.said) == 1, bot.said
    assert "/site" in bot.said[0]


def test_site_command_binds_the_chat_to_the_group_title(monkeypatch, tmp_path):
    """Без имени в команде проект берётся из названия группы."""
    bot = _Bot(monkeypatch, tmp_path)

    core._telegram_group_message(_chat(), _message("/site"))

    assert core._site_chat_project(_chat()["id"]) == "Гродненская — реализация"
    assert "Гродненская — реализация" in bot.said[0]

    core._telegram_group_message(_chat(), _message("/site Нагатино"))
    assert core._site_chat_project(_chat()["id"]) == "Нагатино"


def test_the_bot_counts_what_it_saw_in_groups(monkeypatch, tmp_path):
    """Счётчик увиденного: без него молчание нечем объяснить.

    «Privacy не сняли», «бота не переподключили» и «мост не дописан» снаружи
    выглядят одинаково — бот молчит. Счётчик отвечает, дошло ли хоть одно
    сообщение и из какого чата.
    """
    _Bot(monkeypatch, tmp_path, bound="Гродненская")
    core.app.state.telegram_group_seen = {}

    core._telegram_group_message(_chat(), _message("просто сообщение"))
    core._telegram_group_message(_chat(), _message("и ещё одно"))

    seen = core.app.state.telegram_group_seen[str(_chat()["id"])]
    assert seen["count"] == 2
    assert seen["title"] == "Гродненская — реализация"
    assert seen["last"]


def test_the_project_name_never_becomes_a_path(monkeypatch, tmp_path):
    """Имя проекта становится именем каталога — значит оно проверяется на границе.

    Внутри монитора имя чистится, но чистка — это молчаливая правка чужого
    значения: «Гродненская/../x» превратилась бы в другое имя, и отчёт лёг бы
    не туда, где его ищут. Поэтому граница отказывает, а не исправляет, и
    отказ назван.
    """
    bot = _Bot(monkeypatch, tmp_path)

    for bad in ("../../etc/passwd", "a/b", "..", "Гродненская/../x", "x" * 70):
        assert core._site_project_name(bad) == "", bad
    for good in ("Гродненская — реализация", "Нагатино", "ЖК «Тест» №2"):
        assert core._site_project_name(good) == good

    core._telegram_group_message(_chat(), _message("/site ../../etc/passwd"))
    assert core._site_chat_project(_chat()["id"]) == ""
    assert "не годится" in bot.said[-1] or "Привязка не удалась" in bot.said[-1]


def test_a_bad_name_left_in_the_registry_is_not_trusted(monkeypatch, tmp_path):
    """Запись могла лечь до появления проверки — читаем реестр тоже через неё."""
    _Bot(monkeypatch, tmp_path)
    path = core._site_chats_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"chats": {"-100500": "../../etc"}}', encoding="utf-8")

    assert core._site_chat_project(-100500) == ""

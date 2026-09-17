"""Общая подготовка тестов.

Контекст Платона Сергеевича дублируется на диск, чтобы переживать переход между
воркерами. В тестах это состояние обязано быть временным: иначе один тест
оставляет проект в рабочем каталоге, а следующий, проверяющий поведение «проекта
нет», находит чужой и падает. Заодно репозиторий не засоряется.

То же и с `DATA_DIR`: под ним лежат каталог КРТ, рейтинг площадок и отметка
«когда впервые увидели». Изоляция обязана покрывать ВСЁ дисковое состояние, а
не перечисленное по памяти: поле, о котором забыли, ловится потом странным
падением соседа — и ловится не сразу, потому что зависит от порядка.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Недельный прогон каталога КРТ стартует нитью при установке модуля торгов и
# считает ВЕСЬ каталог, когда наступает его календарная точка. В тестах этой
# нити быть не должно: 02.09.2026 она проснулась внутри прогона на GitHub с
# рынком-заглушкой из соседнего теста, сходила в сеть за 263 площадками и
# залила хвост лога 134 трассировками «'object' has no attribute
# 'build_report'» — строку «N passed» под ними пришлось искать скриптом.
# Выключатель у нити есть; здесь он взводится до импорта приложения.
os.environ.setdefault("AUCTION_KRT_WEEKLY", "0")
# Сторож каталога — вторая такая нить: он ходит к городу за новостями своим
# сроком и в тестах ему делать нечего ровно по той же причине. Фоновая работа
# приложения — не часть теста, и выключатель взводится здесь же, до импорта.
os.environ.setdefault("AUCTION_KRT_WATCH", "0")
# Сохранённые значения книги: их считает наш вычислитель, и счёт всей книги
# стоит около четырнадцати секунд. Книгу собирают 62 файла набора, и на каждой
# сборке прогон подорожал бы получасом — при потолке доли в восемьдесят минут
# это уже не «дороже», а «не доходит». Проход держит своя проверка, и она же
# включает его обратно; выгрузке он нужен всегда и там включён по умолчанию.
os.environ.setdefault("DEVELOPAID_WORKBOOK_CACHE", "0")
# Сторож нормативной базы — та же история: он ходит к правовым порталам по
# расписанию, и в прогоне это сеть, чужие ответы и мусор в логе.
os.environ.setdefault("NORMATIVES_WATCH", "0")
# Служебная страница участков КРТ Нагатино дочитывает контуры в ЕГРН фоном,
# как только её открыли. Открывает её в прогоне проверка подвала — обходом
# ВСЕХ страниц приложения, — и тридцать девять запросов в НСПД из теста это та
# же фоновая работа приложения, которой в прогоне быть не должно.
os.environ.setdefault("NAGATINO_EGRN_READ", "0")

import main as _wrapper  # noqa: E402
import main_legacy as _engine  # noqa: E402

# Обёртка грузит движок отдельным модулем (`developaid_core`), а тесты
# импортируют `main_legacy` напрямую: это два разных объекта с двумя разными
# наборами путей. Изолировать надо оба — иначе половина тестов пишет во
# временный каталог, а половина в рабочий, и найти это можно только по
# странному падению соседа.
_MODULES = (_wrapper.core, _engine) if _wrapper.core is not _engine else (_engine,)


@pytest.fixture(autouse=True)
def empty_glavapu_tep_cache():
    """ТЭП участка кэшируется на шесть часов — в жизни это ускорение, в тестах
    чужой ответ: один тест кладёт результат по номеру, следующий проверяет
    поведение при сбое и получает вчерашний успех."""
    _wrapper.core._GLAVAPU_TEP_CACHE.clear()
    # Предохранитель после сбоя держит браузер закрытым пять минут — в жизни
    # это спасает от полутора минут ожидания на каждом расчёте, в тестах
    # сбой одного проверяющего сценария молча отключал бы браузер соседям.
    _wrapper.core._GLAVAPU_HEADLESS_BLOCKED_UNTIL["at"] = 0.0
    yield
    _wrapper.core._GLAVAPU_TEP_CACHE.clear()
    _wrapper.core._GLAVAPU_HEADLESS_BLOCKED_UNTIL["at"] = 0.0


@pytest.fixture(autouse=True)
def isolated_platon_state(tmp_path, monkeypatch):
    monkeypatch.setattr(_wrapper, "_STATE_DIR", tmp_path / "platon_state")
    # Кэш ответов агента и стадии запросов тоже живут на диске — иначе ответ,
    # положенный одним тестом, приходит другому вместо похода в модель, и тест
    # «свободный вопрос доходит до модели» падает через раз.
    monkeypatch.setattr(_wrapper.core, "_PLATO_STAGE_DIR", tmp_path / "agent_state")
    # Журнал обращений тоже на диске: без изоляции тесты писали бы в рабочий
    # каталог, а свод одного теста считал бы события соседнего.
    for module in _MODULES:
        monkeypatch.setattr(module, "_USAGE_DIR", tmp_path / "usage")
        # Анкеты и реестр людей лежат рядом с проектами и живут вечно — тем
        # более им нужна изоляция: без неё свод читал анкеты, записанные
        # соседним тестом и оставшиеся в рабочем каталоге (падение
        # test_the_free_texts_are_not_folded, 23.08.2026 — вместо «адрес
        # ищется, а ТЭП нет» приходило «ок» с диска).
        monkeypatch.setattr(module, "_PROJECTS_DIR", tmp_path / "projects")
        module._USAGE_SWEPT.clear()
    # Каталог КРТ, рейтинг, `first_seen` и отчёты площадок живут под `DATA_DIR`,
    # и он в эту изоляцию не входил: тесты писали в рабочий `data/`
    # репозитория, а тест «первый снимок никого не делает новым» находил там
    # снимок, оставленный соседом. В прогоне 0.20.91 он проходил, в 0.20.92
    # падал — код между ними не менялся, менялось лежащее на диске. Проверка,
    # зависящая от оставленного файла, врёт в обе стороны, и зелёный прогон
    # здесь не значит ничего: на CI контейнер чистый, и там этого не видно.
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    # Снимки монитора живут своим каталогом (`DEVELOPAID_MONITOR_DIR`, иначе
    # `data/monitor` рядом с кодом), и в изоляцию он не входил: ежедневный
    # отчёт из теста ложился в рабочий каталог репозитория, а `git add -A`
    # готов был увезти его в публичный git вместе с именами подрядчиков живого
    # объекта. Путь берётся у самого модуля, а не собирается второй раз.
    try:
        import developaid_monitor as _monitor

        monkeypatch.setattr(_monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    except Exception:  # модуль монитора может быть не установлен
        pass
    for name in ("_PLATON_CONTEXT_BY_SESSION", "_PLATON_LAST_SESSION",
                 "_PLATON_TEP_CONTEXT", "_PLATON_MODE", "_PLATON_HISTORY",
                 "_PLATON_PENDING", "_PLATON_LAST_URL"):
        monkeypatch.setattr(_wrapper, name, {})
    yield


def live_threads() -> list[str]:
    """Недемонические нити, кроме главной. Демоны процесс не держат."""
    import threading

    return sorted(one.name for one in threading.enumerate()
                  if one is not threading.main_thread() and not one.daemon
                  and one.is_alive())


def live_children() -> list[str]:
    """Живые дочерние процессы — «pid команда». Без зависимостей, через /proc.

    Нитей сторож не нашёл (прогон 16.09.2026 промолчал во всех четырёх долях),
    а доля всё равно молчала одиннадцать с половиной минут после итога. Значит
    держит не нить: незакрытый ребёнок наследует стандартный вывод шага, раннер
    ждёт закрытия трубы и в самом конце сам пишет «Cleaning up orphan
    processes». Нить такого не покажет — у неё нет своего процесса.
    """
    import os

    mine = os.getpid()
    out: list[str] = []
    try:
        names = sorted(int(one) for one in os.listdir("/proc") if one.isdigit())
    except OSError:
        return out
    for pid in names:
        if pid == mine:
            continue
        try:
            with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as fh:
                stat = fh.read()
            # Имя процесса в скобках и может содержать сами скобки и пробелы,
            # поэтому родителя берут ПОСЛЕ закрывающей скобки, а не по индексу
            # в разбитой пробелами строке.
            tail = stat[stat.rindex(")") + 1:].split()
            if int(tail[1]) != mine:
                continue
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                cmd = fh.read().replace(b"\x00", b" ").decode("utf-8", "replace")
        except (OSError, ValueError, IndexError):
            continue
        out.append(f"{pid} {(cmd.strip() or '?')[:120]}")
    return out


def pipe_holders() -> tuple[list[str], int]:
    """Кто ещё держит трубу нашего вывода, и сколько процессов не прочитано.

    Раннер ждёт закрытия ТРУБЫ шага, а не завершения дерева процессов. Счёт по
    родителю (`live_children`) ловит только прямых детей: внук и
    переподчинённая сирота (PPID уехал на init) держат трубу точно так же, а по
    родителю их не видно вовсе.

    Замер 16.09.2026, доля 3: шаг «Доля набора» кончился 01:18:01 при итоге
    pytest 01:07:39 — разрыв десять минут двадцать одна секунда, — послешаговые
    шаги заняли НОЛЬ секунд, а сторож нитей и детей промолчал. Значит держит ни
    раннер, ни нить, ни прямой ребёнок, а тот, кого счёт по родителю не видит.

    Свои предки исключены намеренно: родитель шага (`run_tests.sh`, оболочка
    раннера) держит тот же вывод по построению, и названный, он кричал бы зря
    в каждой доле. Читающий конец не в счёт по той же причине — ждут закрытия
    ПИШУЩЕГО, а направление называет `fdinfo`, а не сама ссылка.
    """
    import os

    mine = os.getpid()
    try:
        target = os.readlink(f"/proc/{mine}/fd/1")
    except OSError:
        return [], 0
    if not target.startswith("pipe:"):
        # Вывод шага не труба (файл, терминал) — закрытия трубы никто не ждёт,
        # и говорить тут не о чем.
        return [], 0

    forebears = {mine}
    pid = mine
    while pid > 1:
        try:
            with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as fh:
                stat = fh.read()
            pid = int(stat[stat.rindex(")") + 1:].split()[1])
        except (OSError, ValueError, IndexError):
            break
        forebears.add(pid)

    out: list[str] = []
    unseen = 0
    try:
        names = sorted(int(one) for one in os.listdir("/proc") if one.isdigit())
    except OSError:
        return out, unseen
    for pid in names:
        if pid in forebears:
            continue
        try:
            handles = os.listdir(f"/proc/{pid}/fd")
        except FileNotFoundError:
            continue  # процесс кончился между обходом и чтением
        except OSError:
            unseen += 1
            continue
        for handle in handles:
            try:
                if os.readlink(f"/proc/{pid}/fd/{handle}") != target:
                    continue
            except OSError:
                continue
            if not _writes(pid, handle):
                continue
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as fh:
                    cmd = fh.read().replace(b"\x00", b" ").decode("utf-8", "replace")
            except OSError:
                cmd = ""
            out.append(f"{pid} {(cmd.strip() or '?')[:120]}")
            break
    return out, unseen


def _writes(pid: int, handle: str) -> bool:
    """Пишущий ли это конец трубы. Непрочитанное направление считаем пишущим.

    Перекос намеренный: лишний названный держатель разбирается за минуту, а
    пропущенный возвращает нас к молчанию, из которого сторож и написан.
    """
    try:
        with open(f"/proc/{pid}/fdinfo/{handle}", encoding="utf-8",
                  errors="replace") as fh:
            for line in fh:
                if line.startswith("flags:"):
                    return int(line.split()[1], 8) & 3 in (1, 2)
    except (OSError, ValueError, IndexError):
        return True
    return True


def hanging_report(names: list[str], children: list[str] | None = None,
                   pipes: tuple[list[str], int] | None = None) -> str:
    """Что сказать про оставшееся живым. Пусто — значит говорить нечего.

    Молчание здесь ответ: пока непрозрачных нитей и детей нет, в конце доли не
    печатается ничего, иначе там стояла бы приписка, которую перестают читать.

    Нити, дети и держатели трубы названы ПОРОЗНЬ: «нить не закрыли», «ребёнок
    держит трубу шага» и «внук или сирота держит её мимо родителя» — разные
    поломки и чинятся по-разному, а одно число их бы скрыло.
    """
    kids = list(children or [])
    holders, unseen = pipes or ([], 0)
    if not names and not kids and not holders:
        return ""
    said = []
    if names:
        said.append(f"После итога живы недемонические нити ({len(names)}): "
                    + ", ".join(names))
    if kids:
        said.append(f"После итога живы дочерние процессы ({len(kids)}): "
                    + "; ".join(kids))
    if holders:
        said.append(f"Трубу нашего вывода держат чужие процессы ({len(holders)}): "
                    + "; ".join(holders))
    said.append("Это держит шаг: раннер ждёт закрытия его вывода, а в логе "
                "выглядит как медленная доля. Стеки ниже — чтобы не гадать, "
                "чего мы ждём.")
    if unseen:
        # Говорится только рядом с находкой: в здоровой доле чужие процессы
        # нечитаемы всегда, и постоянная приписка перестала бы читаться.
        said.append(f"Заглянуть не удалось в {unseen} процессов — держатель "
                    "мог остаться среди них.")
    return "\n".join(said)


def pytest_sessionfinish(session, exitstatus):
    """Кто остался жив после итога — говорится вслух, а не молча ждётся.

    Пять прогонов подряд Доля 3 кончала работу через десять–тринадцать минут
    ПОСЛЕ того, как pytest напечатал итог (замер 15.09.2026: итог 11:08, конец
    24:44, у остальных долей разрыв 34–46 секунд). Снаружи это неотличимо от
    медленной доли, а цена — треть потолка, который считается от худшей доли.

    Замер в песочнице причину НЕ показал: и подозреваемый файл в одиночку
    (12,54 с при реальных 13,76), и вся третья доля целиком (592,54 с при
    реальных 594,76) выходят с разрывом в секунду-две. Значит ждать надо там,
    где это происходит, — и единственный способ узнать, чего мы ждём, назвать
    оставшиеся нити прямо в логе доли.
    """
    said = hanging_report(live_threads(), live_children(), pipe_holders())
    if not said:
        return
    import faulthandler
    import sys

    print("\n" + said)
    faulthandler.dump_traceback(file=sys.stdout, all_threads=True)

"""Где взять браузер для проверок, которые решает браузер.

Геометрия, `let`-состояние страницы, порядок объявлений, дубль картинок — всё
это в исходнике выглядит одинаково у верного кода и у сломанного, и проверяет
это настоящий Chromium. Такие проверки есть, и на CI они не шли **ни разу**:
`tests-on-pr.yml` ставит зависимости и не ставит браузер, а тесты искали его по
зашитому пути и на его отсутствии делали `pytest.skip`. Снаружи «прошло» и «не
запускалось» выглядят одинаково — то самое «молчащая проверка неотличима от
отсутствующей».

Ответов на «где chromium» в наборе было СЕМЬ форм в двадцати двух местах, и все
они расходились. Одни держали НОМЕР СБОРКИ — величину playwright, которая
меняется с каждым его обновлением: в песочнице сейчас 1194, в образе прода уже
1234. Другие номер переживали, но держали каталог `/opt/pw-browsers`, а в образе
браузер лежит под `~/.cache/ms-playwright`. И все семь держали имя папки
`chrome-linux`, которое у свежего playwright уже `chrome-linux64`.

Своей восьмой копии здесь нет: у сервиса такой путь **уже есть** —
`browser_launch.executable_paths()`. Он ищет по имени файла, а не по пути
(`chromium-*/*/chrome`), то есть переживает и переименование папки; знает все
каталоги, где playwright держит браузеры; проверяет исполняемость. Написан он
был по настоящей поломке прода 20.08.2026, и повторять его хуже — значит
завести число, за которое никто не отвечает.

И главное, без чего первое не стоит ничего: **отсутствие браузера там, где он
обязан быть, — это падение, а не пропуск.** На CI и в образе он ставится,
значит его отсутствие означает сломанную установку, а пропуск об этом
промолчит и вернёт нас ровно туда, откуда пришли. Решает `REQUIRE_BROWSER`: она
взводится рядом с шагом установки в самом workflow, чтобы установка и
требование стояли в одном месте и не разошлись.

Запуск проверок этого файла:
python3 -m pytest tests/test_the_browser_is_found_not_remembered.py -q
"""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import browser_launch  # noqa: E402


def chromium_path() -> Path | None:
    """Полный Chromium этой машины — или `None`, если его тут нет.

    Берётся первый `chrome` из перебора сервиса: у него полный браузер идёт
    раньше headless shell, а запускать проверки страницы надо именно полным —
    у shell нет ни окна, ни его геометрии, а геометрия здесь и есть предмет.
    """
    for path in browser_launch.executable_paths():
        if os.path.basename(path) == "chrome":
            return Path(path)
    return None


def browser_required() -> bool:
    """Обязан ли браузер быть на этой машине.

    Взводится в workflow рядом с установкой браузера. Пусто — машина человека
    или песочница, и пропуск там честен; взведено — установка обязана была
    сработать, и её несрабатывание должно быть видно красным.
    """
    said = (os.environ.get("REQUIRE_BROWSER") or "").strip().lower()
    return said not in ("", "0", "false", "no")


def _where_we_looked() -> str:
    """Что лежит в каталогах браузеров — словами.

    Пустой перебор и пустой образ выглядят одинаково («не нашли»), а причины у
    них разные: в первом случае промахнулись шаблоном, во втором установка не
    сработала. Сервис умеет отвечать на это (`cache_contents`), и отказ здесь
    говорит его ответом, а не своим пересказом.
    """
    try:
        contents = browser_launch.cache_contents()
    except Exception as exc:  # noqa: BLE001
        return f"перечислить каталоги не удалось: {exc}"
    return "; ".join(f"{root}: {', '.join(items) or 'пусто'}"
                     for root, items in contents.items())


def chromium_or_skip() -> Path:
    """Путь к chromium, либо пропуск с причиной, либо падение — смотря где мы.

    Зовётся из тела теста: `pytest.skip` и `pytest.fail` работают только оттуда.
    """
    import pytest

    try:
        import playwright.sync_api  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        if browser_required():
            pytest.fail("браузер объявлен обязательным (REQUIRE_BROWSER), "
                        f"а пакет playwright не импортируется: {exc}")
        pytest.skip(f"playwright недоступен — {exc}")
    chrome = chromium_path()
    if chrome is None:
        if browser_required():
            pytest.fail(
                "браузер объявлен обязательным (REQUIRE_BROWSER), а полного "
                "chromium не нашлось. Значит `playwright install chromium` не "
                "сработала — и молчаливый пропуск здесь вернул бы набор в "
                "состояние, когда браузерные проверки не шли вовсе. "
                f"В каталогах браузеров лежит: {_where_we_looked()}")
        pytest.skip(f"chromium не найден. В каталогах браузеров: {_where_we_looked()}")
    return chrome


@contextlib.contextmanager
def serve(app, port: int):
    """Поднять приложение на 127.0.0.1:port и отдать адрес его корня.

    Страницу проверяют на том адресе, по которому её открывает человек.
    Открытая с диска (`file://`), она живёт в другом мире: её собственные
    запросы к `/tep/...` становятся `file:///tep/...`, и держались они на том,
    что Chromium такой запрос вообще выпускает, а playwright его перехватывает.
    В сборке 1194 это работало, в 151.0.7922.34 (playwright 1234) перестало —
    и две проверки покраснели на верном коде при первом же прогоне с браузером
    на CI. Схемы `file://` у продукта нет нигде: он отвечает по http, и
    проверять надо то, что видно.

    Пятнадцать проверок поднимают сервер своей копией этих строк — они
    остаются, пока их не свели сюда одной правкой; новой копии заводить незачем.
    """
    import threading
    import time

    import uvicorn

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(400):
        if server.started:
            break
        time.sleep(0.05)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=10)
        raise RuntimeError(f"сервер проверок не поднялся на порту {port}")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)

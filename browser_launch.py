"""Запуск Chromium — один на все места, где он нужен.

Playwright с некоторых версий при `headless=True` запускает не полный
Chromium, а отдельную сборку `chromium_headless_shell`, и качается она
отдельным пакетом. В образе стоит `playwright install chromium`; если слой с
браузером собран более старым Playwright, чем библиотека в том же образе,
шелла в кэше нет, и запуск падает на «Executable doesn't exist … Looks like
Playwright was just installed or updated».

Отказ выходит наружу по-разному в зависимости от того, кто запускал: печать
PDF молча откатывалась к диалогу браузера, а расчёт ГлавАПУ — к серверным
формулам. То есть одна и та же поломка образа читалась как две разные, и обе
выглядели как «просто так работает».

Поэтому запуск здесь один и с отступлением: сначала как просит Playwright,
потом полным Chromium (`channel="chromium"` — это ровно «не бери шелл»), потом
по найденному в кэше исполняемому файлу. Что сработало — записывается, чтобы
диагностика отвечала фактом, а не догадкой.
"""

from __future__ import annotations

import glob
import os
from typing import Any

# Чем закончилась последняя попытка запуска. Читается диагностикой; хранить
# состояние здесь можно, потому что модуль один на процесс.
LAST_LAUNCH: dict[str, Any] = {"how": "", "error": "", "tried": []}

_CACHE_DIRS = (
    os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "",
    "/root/.cache/ms-playwright",
    os.path.expanduser("~/.cache/ms-playwright"),
    "/ms-playwright",
)
# Полный Chromium предпочтительнее шелла: он и есть то, чего может не хватать.
_BINARIES = (
    "chromium-*/chrome-linux/chrome",
    "chromium_headless_shell-*/chrome-linux/chrome-headless-shell",
)


def executable_paths() -> list[str]:
    """Что из браузеров реально лежит в кэше — по возрастанию предпочтения."""
    found: list[str] = []
    for root in _CACHE_DIRS:
        if not root:
            continue
        for pattern in _BINARIES:
            found.extend(sorted(glob.glob(os.path.join(root, pattern))))
    return [path for path in found if os.path.exists(path)]


def launch(playwright: Any, *, args: list[str] | None = None, **extra: Any) -> Any:
    """Поднять Chromium, отступая по способам, пока какой-нибудь не сработает.

    Возвращает браузер. Не поднялся ни один способ — поднимается последняя
    ошибка: пустого браузера не бывает, а притворяться, что он есть, значит
    отложить ту же поломку на шаг дальше.
    """
    common: dict[str, Any] = {"headless": True, "args": list(args or []), **extra}
    forced = os.environ.get("CHROMIUM_EXECUTABLE_PATH") or ""

    attempts: list[tuple[str, dict[str, Any]]] = []
    if forced:
        attempts.append(("указанный путь", {**common, "executable_path": forced}))
    attempts.append(("как просит playwright", dict(common)))
    # channel="chromium" — это ровно «не бери headless shell, бери полный».
    attempts.append(("полный chromium", {**common, "channel": "chromium"}))
    for path in executable_paths():
        attempts.append((f"файл {os.path.basename(path)}",
                         {**common, "executable_path": path}))

    LAST_LAUNCH["tried"] = []
    problem: Exception | None = None
    for how, options in attempts:
        try:
            browser = playwright.chromium.launch(**options)
        except Exception as exc:  # noqa: BLE001 — причина нужна целиком
            LAST_LAUNCH["tried"].append(f"{how}: {type(exc).__name__}")
            problem = exc
            continue
        LAST_LAUNCH["how"] = how
        LAST_LAUNCH["error"] = ""
        return browser
    LAST_LAUNCH["how"] = ""
    LAST_LAUNCH["error"] = str(problem or "браузер не запустился")
    raise problem or RuntimeError("Chromium не запустился ни одним способом")


def diagnostics() -> dict[str, Any]:
    """Состояние браузера в образе — фактом, а не догадкой.

    «Chromium в образе есть» проверялось глазами при сборке и оказывалось
    неверным на проде: сборка браузера и версия библиотеки разъезжались, и
    узнавали об этом по тому, что печать выдавала прежний файл, а ТЭП —
    формулы.
    """
    found = executable_paths()
    return {
        "browsers": [os.path.basename(os.path.dirname(os.path.dirname(path)))
                     for path in found],
        "paths": found,
        "last_launch": LAST_LAUNCH.get("how") or None,
        "last_error": LAST_LAUNCH.get("error") or None,
        "tried": LAST_LAUNCH.get("tried") or [],
    }

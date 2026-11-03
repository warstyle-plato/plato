"""У склада на диске есть строка в .gitignore — спрашиваем git, а не память.

Набор тестов пишет в НАСТОЯЩИЙ каталог данных, и склад без строки в
`.gitignore` оседает в рабочем дереве репозитория: ровно так три файла с
тестовым слагом уехали коммитом 83c4139 и с тех пор грязнили дерево на каждом
прогоне. Хуже другое — однажды прогон затрёт живое.

Склад выписок (`egrn_store`) завёлся 13.09.2026 без такой строки, и заметить
это было нечем: пока проверки ходят с `DATA_DIR` во временный каталог,
рабочее дерево остаётся чистым — до первого разбора лота на машине.

Каталог склада объявляет сам склад (`DIRNAME`), и его же спрашивают у git:
список «какие у нас склады» рядом с кодом разошёлся бы с кодом молча.

Запуск: python3 -m pytest tests/test_a_store_is_ignored_by_git.py -q
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402
from auction_search import egrn_store, lot_documents  # noqa: E402

# Склады рынка: модуль и каталог данных, в котором он живёт. Ключ — то, как
# каталог собирает маршрут (`_market_dir`), а не как он записан здесь.
MARKET = Path("data") / "market"


def _relative(place: Path) -> Path:
    """Каталог движка — относительно корня репозитория.

    Спрашивается у самого движка (`_PROJECTS_DIR` и его сосед), а не пишется
    здесь строкой: переедет каталог — переедет и проверка. Путь может быть
    уведён переменной окружения наружу репозитория; тогда рабочему дереву он
    не грозит и проверять нечего.
    """
    try:
        return Path(place).resolve().relative_to(ROOT)
    except ValueError:
        return Path()


STORES = {
    "egrn_store": MARKET / egrn_store.DIRNAME,
    "lot_documents": MARKET / lot_documents.DIRNAME,
    # Данные людей: сохранённые финансовые модели и знакомство (имя, компания).
    # Репозиторий публичный, и строки у них не было до 15.09.2026 — в коммит
    # едва не уехал проект, записанный пробой.
    "projects": _relative(core._PROJECTS_DIR),
    "profiles": _relative(core._PROJECTS_DIR.parent / "profiles"),
}


def ignored(path: Path) -> bool:
    done = subprocess.run(["git", "check-ignore", "-q", str(path)],
                          cwd=ROOT, capture_output=True)
    return done.returncode == 0


def test_git_answers_at_all() -> None:
    """Предохранитель: без него «спрятан» отвечало бы «да» обо всём.

    Путь, которого в `.gitignore` нет, git спрятанным называть не должен —
    иначе проверка ниже зелена при любом содержимом файла.
    """
    assert not ignored(Path("auction_search") / "lot_documents.py")


def test_every_store_directory_is_named() -> None:
    """Предохранитель: склад, уведённый наружу репозитория, даёт пустой путь —
    и `Path()/"probe.json"` спрятанным не окажется никогда, то есть проверка
    ниже красна не по делу. Здесь каталоги движка лежат внутри дерева."""
    assert all(str(place) not in ("", ".") for place in STORES.values()), \
        f"склад без каталога: {[n for n, v in STORES.items() if str(v) in ('', '.')]}"


def test_every_store_directory_is_hidden_from_git() -> None:
    exposed = [name for name, place in STORES.items()
               if not ignored(place / "probe.json")]
    assert not exposed, (
        "склад пишет в рабочее дерево репозитория: " + ", ".join(exposed))

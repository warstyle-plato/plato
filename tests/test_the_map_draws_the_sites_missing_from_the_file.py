"""Карта Москвы рисует и те площадки, которых нет в файле карты реестра.

«На карте Москвы этот КРТ так и не появился» (владелец, 04.09.2026) — про
Варшавское ш., вл. 37: файл `map2025.json` держит 263 записи, а в каталоге 282
строки, и у 35 из них записи в файле нет вовсе. На общей карте их не было ни
под каким увеличением, и это читалось как «площадки нет», хотя у нас есть чем
её нарисовать: проект решения перечисляет участки, а ЕГРН отдаёт контур
каждого.

Два правила, ради которых тест написан.
1. **Чем нарисовано — часть ответа.** Официальный полигон реестра и наш свод по
   перечню документа рисуются по-разному и называются раздельно; одинаковые,
   они читались бы как один источник.
2. **Карта не ходит в ЕГРН в момент отрисовки.** У одной площадки в перечне
   бывает шесть десятков номеров; тридцать пять таких площадок — это минуты
   ожидания. Берётся прочитанное, недостающее дочитывается фоном и называется
   числом: молча пропущенная площадка снова читается как её отсутствие.

Запуск: python3 -m pytest tests/test_the_map_draws_the_sites_missing_from_the_file.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import ui  # noqa: E402
from market_search.krt_registry import KrtRegistry  # noqa: E402

API = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")

IN_FILE = {"slug": "in-file", "name": "Есть в файле карты", "rings_merc": [[[0, 0], [1, 0], [1, 1]]]}
MISSING = {"slug": "varshavskoe-37", "name": "Варшавское шоссе, вл. 37, Нагатинская ул., влд. 3А/6",
           "okrug": "ЮАО", "status": "Планируемый", "area_ha": 14.62}


def _registry(tmp_path) -> KrtRegistry:
    registry = KrtRegistry(tmp_path)
    return registry


def test_the_missing_site_is_found(tmp_path) -> None:
    """Площадка каталога, которой нет в файле карты, названа."""
    registry = _registry(tmp_path)
    registry.map_dataset = lambda **_: {"sites": [dict(IN_FILE)]}  # type: ignore[assignment]
    missing = registry.map_missing([dict(IN_FILE), dict(MISSING)])
    assert [row["slug"] for row in missing] == ["varshavskoe-37"]


def test_only_the_read_outlines_are_taken(tmp_path) -> None:
    """Кэш читается, наружу не ходим: у карты нет минут на ЕГРН."""
    registry = _registry(tmp_path)
    assert registry.decision_outlines_known(["varshavskoe-37"]) == {}
    path = registry.outline_dir / "varshavskoe-37.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, "slug": "varshavskoe-37",
                                "rings_merc": [[[10, 10], [11, 10], [11, 11]]],
                                "centre_merc": [10.5, 10.5]}), encoding="utf-8")
    known = registry.decision_outlines_known(["varshavskoe-37"])
    assert known["varshavskoe-37"]["rings_merc"]
    # Пустой контур — не контур: рисовать нечего, и в ответ он не идёт.
    path.write_text(json.dumps({"schema_version": 1, "rings_merc": []}), encoding="utf-8")
    assert registry.decision_outlines_known(["varshavskoe-37"]) == {}


def test_the_route_marks_the_source_and_counts_the_rest() -> None:
    start = API.index('    @app.get("/auctions/krt/map")')
    body = API[start:API.index('    @app.get("/auctions/krt/api-probe")', start)]
    assert '"source": "decision"' in body, "контур по документу неотличим от официального"
    assert "by_document_pending" in body, "недочитанные площадки не названы числом"
    assert "decision_outlines_known" in body, "карта пошла в ЕГРН в момент отрисовки"
    assert "fill_decision_outlines_in_background" in body, "недостающее не дочитывается вовсе"


def test_the_page_draws_them_apart_and_says_so() -> None:
    page = ui.auctions_page()
    assert "stroke-dasharray" in page, "контур по документу нарисован как официальный"
    assert "состав территории" in page and "по документу" in page, \
        "подпись не говорит, чем нарисован пунктир"

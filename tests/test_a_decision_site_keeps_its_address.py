"""Площадка-решение несёт признак адреса — им её маршруты и гейтят.

«Почему в торгах лот по этой КРТ есть … а тут вот так» (владелец, 07.09.2026,
Рубцовская наб., влд. 3): карточка писала «Карта не построена: у
площадки-решения нет адреса — заголовок документа называет район или границы».
Заголовок при этом адрес называет, и реестр его разобрал: `/auctions/krt`
отдаёт эту строку с `address_known: true`, и таких 244 из 247.

Отказ приходил из ДРУГОЙ сборки той же строки. `/point` спрашивает площадку
сперва у `krt_registry.find`, и для `decision:*` та собирает свою запись —
с адресом в `name`, но БЕЗ `address_known`. Гейт маршрута читает именно это
поле, отсутствующее читается как «адреса нет», и до второй сборки
(`_krt_decision_rows_built`, где поле есть) дело не доходит вовсе: `find`
отвечает первой. Замер прода: карта отказывала у всех шести проверенных
слагов подряд, то есть у всех 247 площадок-решений — и надпись винила
документ города за наш пропущенный ключ.

Закреплено:
- запись `find_decision` несёт `address_known` — она и возвращается только
  тогда, когда адрес есть (`if not address: return None`);
- гейт маршрутов на этой записи ПРОХОДИТ — проверяется тем же выражением,
  что стоит в `api.py`, а не пересказом;
- обе сборки одной строки согласны по полям, на которые смотрят маршруты.

Запуск: python3 -m pytest tests/test_a_decision_site_keeps_its_address.py -q
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import krt_registry as registry_module  # noqa: E402

DOCUMENT_ID = "333331220"
ADDRESS = "Рубцовская наб., влд. 3"
TITLE = ("Проект решения о комплексном развитии территорий нежилой застройки "
         "города Москвы, расположенных по адресу: г. Москва, "
         "Рубцовская наб., влд. 3 (ЦАО)")


def _registry(tmp_path: Path, *, address: str = ADDRESS):
    site = {
        "id": DOCUMENT_ID, "title": TITLE, "address": address, "okrug": "ЦАО",
        "kind": "нежилой застройки", "department": "ДГП",
        "url": f"https://www.mos.ru/dgp/documents/view/{DOCUMENT_ID}/",
        "published_at": 1764601200,
    }
    store = registry_module.KrtRegistry(tmp_path)
    store.decisions_path.parent.mkdir(parents=True, exist_ok=True)
    store.decisions_path.write_text(json.dumps(
        {"all": [site], "retrieved_at": int(time.time()), "complete": True},
        ensure_ascii=False), encoding="utf-8")
    return store, site


def _route_gate_passes(project: dict) -> bool:
    """То же условие, что стоит в `/point`, `/handoff` и соседних маршрутах.

    Пересказ гейта своими словами проверял бы пересказ: условие переписано
    отсюда буква в букву, и меняя его в маршруте, меняют и здесь.
    """
    address = str(project.get("address") or project.get("name") or "").strip()
    return bool(project.get("address_known")) and bool(address)


def test_the_record_carries_the_address_flag(tmp_path: Path) -> None:
    store, _ = _registry(tmp_path)
    project = store.find_decision(DOCUMENT_ID)
    assert project is not None, "площадка-решение не найдена по номеру документа"
    assert project["name"] == ADDRESS
    assert project["address_known"] is True, (
        "запись без признака адреса — маршрут прочитает её как «адреса нет»")


def test_the_route_gate_accepts_the_record(tmp_path: Path) -> None:
    store, _ = _registry(tmp_path)
    project = store.find_decision(DOCUMENT_ID)
    assert _route_gate_passes(project), (
        "гейт маршрута отказывает записи с разобранным адресом — "
        "ровно то, из-за чего карта не строилась ни у одной площадки-решения")


def test_a_title_without_an_address_gives_no_record(tmp_path: Path) -> None:
    """Обратная сторона: без адреса записи нет вовсе, и отказ честен."""
    store, _ = _registry(tmp_path, address="")
    assert store.find_decision(DOCUMENT_ID) is None


def test_both_builders_of_the_row_agree(tmp_path: Path) -> None:
    """Две сборки одной строки расходятся молча — эта их и сверяет."""
    from auction_search.api import krt_decision_rows

    store, site = _registry(tmp_path)
    by_find = store.find_decision(DOCUMENT_ID)
    built = [row for row in krt_decision_rows({"decisions": [site]})
             if row.get("slug") == "decision:" + DOCUMENT_ID]
    assert built, "сборщик списка не дал строки для этого решения"
    for key in ("slug", "name", "no_card", "address_known"):
        assert by_find.get(key) == built[0].get(key), (
            f"поле {key} у двух сборок одной строки разное: "
            f"{by_find.get(key)!r} против {built[0].get(key)!r}")

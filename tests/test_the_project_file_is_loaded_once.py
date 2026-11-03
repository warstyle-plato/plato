"""Файл проекта грузится один раз, а не при каждом открытии кабинета.

Источников на один проект несколько, и приходят они порознь: выгрузка ЦФ
несёт контрактацию, проводки 1С и оба плана, книга финмодели — квартирографию
(владелец, 26.08.2026: «можно его подгружать будет просто потом
дополнительно?»). Просить оба файла при каждом открытии значит однажды
получить два файла разных дат и показать их как один проект.

Хранится РАЗОБРАННОЕ, а не сам файл: выгрузка — это десятки мегабайт, а её
свод — сотни килобайт, и диск у нас уже кончался молча.
"""
from __future__ import annotations

from pathlib import Path

from market_search import sales_store


def test_the_second_file_does_not_erase_the_first(tmp_path: Path) -> None:
    sales_store.save(tmp_path, "Проект", {"contracting": {"rows": [1]}}, "цф.xlsb")
    sales_store.save(tmp_path, "Проект", {"pool": {"bands": [2]}}, "книга.xlsx")
    kept = sales_store.load(tmp_path, "Проект")
    assert kept["sources"]["contracting"]["data"] == {"rows": [1]}
    assert kept["sources"]["pool"]["data"] == {"bands": [2]}
    assert kept["sources"]["contracting"]["file"] == "цф.xlsb"


def test_a_source_that_did_not_parse_does_not_overwrite(tmp_path: Path) -> None:
    """Пустой разбор — это «в этом файле такого листа нет», а не «стало пусто»."""
    sales_store.save(tmp_path, "Проект", {"pool": {"bands": [2]}}, "книга.xlsx")
    sales_store.save(tmp_path, "Проект", {"pool": None, "contracting": {"rows": []}}, "цф.xlsb")
    kept = sales_store.load(tmp_path, "Проект")
    assert kept["sources"]["pool"]["data"] == {"bands": [2]}


def test_each_source_carries_its_own_date(tmp_path: Path) -> None:
    """Два файла разных дат, показанные как один проект, — худший исход."""
    sales_store.save(tmp_path, "Проект", {"contracting": {"rows": []}}, "цф.xlsb")
    kept = sales_store.projects(tmp_path)
    assert kept and kept[0]["project"] == "Проект"
    assert kept[0]["sources"][0]["at"], "когда принесён — часть ответа"
    assert kept[0]["sources"][0]["name"] == sales_store.KINDS["contracting"]


def test_a_broken_file_is_nothing_to_show_not_no_sales(tmp_path: Path) -> None:
    place = tmp_path / "cabinet" / f"{sales_store.slug('Проект')}.json"
    place.parent.mkdir(parents=True)
    place.write_text("{не json", encoding="utf-8")
    kept = sales_store.load(tmp_path, "Проект")
    assert kept["sources"] == {} and kept.get("broken")


def test_the_store_holds_no_names_of_buyers() -> None:
    """Имена покупателей наружу не идут — ни на экран, ни на диск."""
    source = (Path(__file__).resolve().parent.parent / "market_search" / "contracting.py").read_text()
    body = source[source.index("def read_contracts("):source.index("def read_ledger(")]
    assert '"buyer"' not in body.split("out.append")[1], "имя покупателя в записи не сохраняется"
    assert "company_buyer" in body, "остаётся только признак юрлица"


def test_the_summary_is_assembled_by_one_function() -> None:
    """Два сборщика на один проект однажды разойдутся, и обе картинки будут верны."""
    api = (Path(__file__).resolve().parent.parent / "market_search" / "api.py").read_text()
    assert api.count("def _sales_view(") == 1
    # И загрузка файла, и открытие кабинета зовут её же.
    upload = api[api.index("async def cabinet_contracting("):api.index("@app.get(\"/cabinet/sales/summary\")")]
    opened = api[api.index("async def cabinet_sales("):api.index("@app.post(\"/market/report\")")]
    assert "_sales_view(" in upload and "_sales_view(" in opened


def test_the_screen_asks_the_store_before_asking_for_a_file() -> None:
    page = (Path(__file__).resolve().parent.parent / "market_search" / "cabinet.py").read_text()
    assert "async function loadStoredSales(" in page
    assert "loadStoredSales();" in page, "склад спрашивается при открытии"
    # Пустой склад — это «ещё не грузили», а не «продаж нет».
    assert "ещё не загружены" in page

"""Прямой путь идёт первым, а отказ превзойдённого транспорта — не ошибка.

Замер прода 13.09.2026 по одиннадцати КРТ с живым лотом: `transport` равен
`official_host` у всех десяти прочитанных, а отказ читалки (HTTP 451 от
r.jina.ai) записан в `errors` у тех же десяти — включая четыре, где перечень
участков прочитан целиком (60, 54, 55 и 27 номеров). То есть отказ читалки не
был причиной НИЧЕГО: запасной путь срабатывал.

Стоило это неверного диагноза, объявленного владельцу: шесть площадок без
перечня участков были названы молчащими из-за читалки, тогда как у них решения
не нашёл поиск mos.ru (ошибок `mos_search_*` — ноль). Отсюда правило: у
записанного отказа спрашивают, не удался ли запасной путь. Ошибка в списке
ошибок — ещё не причина, пока не посмотрел, чем кончилось значение.

Цена была не только в чтении. `errors` обрезается до трёх и отвечает на «почему
величины НЕ получилось», а отказ читалки стоял в нём первым и всегда — то есть
вытеснял оттуда настоящие причины (`mos_decision_pdf`,
`mos_document_attachments`, `mos_document_detail`).

Порядок при этом перевёрнут относительно действительности: общие корни
(`trusted_roots`) заведены для api.krt.mos.ru в 0.23.30, и прямое чтение
работает. Читатель каталога тем же порядком уже ходит — правило закрыли в одном
месте и не закрыли в соседнем.

Схема кэша НЕ поднята намеренно: правка не меняет ни одной величины, только то,
в каком списке лежит отказ транспорта, а срок хранения ответа сутки — хранимые
ответы устареют сами. Поднятая схема заказала бы перечитывание всех площадок
каталога ради поля, за которым не стоит ни одного числа.

Запуск: python3 -m pytest tests/test_a_superseded_transport_is_not_an_error.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search.krt_registry import (  # noqa: E402
    CACHE_SCHEMA_VERSION, JINA_PREFIX, KrtRegistry,
)

CARD = """
# Описание объекта
Площадь, га: 10.24
Округ: СЗАО
Район: Строгино
Общий объем застройки: 323 796
"""

PROJECT = {
    "slug": "mira",
    "name": "Мира пр-кт, вл. 122",
    "status": "Планируемый",
    "url": "https://api.krt.mos.ru/projects/mira",
    "housing_gfa_sqm": 10_000,
}


def _registry(tmp_path: Path, fetch) -> KrtRegistry:
    registry = KrtRegistry(tmp_path, fetch=fetch)
    registry.path.parent.mkdir(parents=True, exist_ok=True)
    registry.path.write_text(
        json.dumps({"schema_version": CACHE_SCHEMA_VERSION, "complete": True,
                    "projects": [PROJECT]}),
        encoding="utf-8",
    )
    return registry


def _page_reads(calls: list[str]) -> list[str]:
    """Только чтения страницы площадки: у каталога свой запасной путь."""
    return [url for url in calls
            if url in (PROJECT["url"], JINA_PREFIX + PROJECT["url"])]


def _reader(calls: list[str], *, renderer_fails: bool = True, host_fails: bool = False):
    """Читалка отказывает, прямой путь отвечает — как на живом проде."""

    def fetch(url: str) -> bytes:
        calls.append(url)
        if url.startswith(JINA_PREFIX):
            if renderer_fails:
                raise OSError("HTTP Error 451: Unavailable For Legal Reasons")
            return CARD.encode()
        if url == PROJECT["url"]:
            if host_fails:
                raise OSError("chain rejected")
            return CARD.encode()
        # Поиск решения на mos.ru: отвечает и не находит ничего — это молчание
        # источника, а не наш пробел, и в errors ему не место.
        return json.dumps({"results": []}).encode()

    return fetch


def test_the_official_host_is_asked_before_the_renderer(tmp_path: Path) -> None:
    calls: list[str] = []
    answer = _registry(tmp_path, _reader(calls)).requirements("mira")
    assert answer is not None
    page_reads = _page_reads(calls)
    assert page_reads, f"страницу площадки не читали вовсе: {calls}"
    assert page_reads[0] == PROJECT["url"], (
        "первым спрошен не прямой путь, а "
        f"{page_reads[0]} — порядок транспортов перевёрнут"
    )


def test_the_renderer_is_not_asked_when_the_direct_path_answers(tmp_path: Path) -> None:
    """Заведомо неудачный запрос на каждое чтение — плата, которой быть не должно."""
    calls: list[str] = []
    _registry(tmp_path, _reader(calls)).requirements("mira")
    assert not [url for url in _page_reads(calls) if url.startswith(JINA_PREFIX)], (
        f"читалку спросили при отвечающем прямом пути: {calls}"
    )


def test_a_superseded_refusal_is_named_but_is_not_an_error(tmp_path: Path) -> None:
    """Читалка отказала, значение получено — отказ назван, но причиной не стоит."""
    calls: list[str] = []
    answer = _registry(
        tmp_path, _reader(calls, renderer_fails=False, host_fails=True)
    ).requirements("mira")
    assert answer is not None
    assert answer["transport"] == "read_only_renderer", answer["transport"]
    attempts = answer.get("transport_attempts") or []
    assert any("official_host" in str(item) for item in attempts), (
        f"отказ прямого пути пропал молча: {attempts}"
    )
    assert not [e for e in (answer.get("errors") or [])
                if "official_host" in str(e) or "read_only_renderer" in str(e)], (
        f"превзойдённый транспорт записан ошибкой: {answer.get('errors')}"
    )


def test_errors_keep_their_room_for_real_causes(tmp_path: Path) -> None:
    """errors отвечает на «почему величины НЕ получилось» — и только на это."""
    calls: list[str] = []
    answer = _registry(tmp_path, _reader(calls)).requirements("mira")
    assert answer is not None
    assert answer.get("errors") == [], (
        "при сработавшем прямом пути и молчащем поиске mos.ru ошибок быть не "
        f"должно, а стоят: {answer.get('errors')}"
    )
    # Предохранитель: молчание поиска решения названо своим словом, а не пустотой.
    assert answer.get("decision_available") is False
    assert "mos.ru" in str(answer.get("warning") or "")


def test_the_measurement_would_catch_the_old_order(tmp_path: Path) -> None:
    """Предохранитель: на прежнем порядке проверки выше обязаны падать.

    Прежний порядок — читалка первой. Подделываем его тем, что прямой путь
    отвечает, а читалка тоже: если бы порядок остался прежним, первым
    прочитанным оказался бы адрес читалки. Проверка держит утверждение, а не
    форму записи кода: сравнивается ПОРЯДОК запросов, который виден только
    запуском.
    """
    calls: list[str] = []
    _registry(tmp_path, _reader(calls, renderer_fails=False)).requirements("mira")
    page_reads = _page_reads(calls)
    assert page_reads[0] == PROJECT["url"], page_reads
    assert len(page_reads) == 1, (
        f"при отвечающем прямом пути прочитано больше одного адреса: {page_reads}"
    )


def test_when_nothing_was_read_the_transport_says_so(tmp_path: Path) -> None:
    """Оба транспорта отказали — поле «чем прочитано» не называет удачное чтение.

    Начальным значением стоял `official_host`, и ответ утверждал чтение
    официальным хостом там, где не прочитано ничего. Та же семья, что «ноль
    вместо числа и ноль как значение выглядят одинаково»: ответ поля неотличим
    от настоящего, а обе попытки при этом названы своим списком.
    """
    calls: list[str] = []
    answer = _registry(
        tmp_path, _reader(calls, renderer_fails=True, host_fails=True)
    ).requirements("mira")
    assert answer is not None
    assert not answer.get("transport"), (
        f"поле назвало транспорт при пустом чтении: {answer.get('transport')!r}"
    )
    attempts = [str(item) for item in (answer.get("transport_attempts") or [])]
    assert len(attempts) == 2, f"названы не обе попытки: {attempts}"
    assert any("official_host" in item for item in attempts), attempts
    assert any("read_only_renderer" in item for item in attempts), attempts

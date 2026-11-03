"""Починка читателя доезжает до УЖЕ прочитанного лота, а не только до нового.

14.09.2026 это стоило видимого результата выпуска. Краткая форма выписки
(«об основных характеристиках и зарегистрированных правах») уже читалась на
проде, а на 1-й Горловской, вл. 4 по-прежнему стояло «выписки на объект нет» у
всех 19 участков: свод территории считается из РАЗОБРАННОГО на диске, разобрано
оно прежним читателем, а проход за извещениями прочитанное больше не
спрашивает — «разобранный не спрашивается больше никогда». Собственники (ООО
«СОКОЛ», физическое лицо) появились только после того, как лот перечитали
рукой. На экране НАШ пробел читался как молчание документа.

Правило то же, что у привязки публикаций (`ANCHOR_RULES_VERSION`) и у диагноза
съехавшей карточки каталога: хранимая производная расходится с правилом молча.

Проверок четыре, и каждая держит своё утверждение:

- запись несёт версию правил, которыми прочитана;
- склад отличает разобранное прежними правилами от свежего, и запись без поля
  считается первой версией, а не «неизвестно»;
- перечитывание спрашивается один раз на смену правил: перечитали и что-то
  осталось прежним — это ответ ДОКУМЕНТОВ, и вторым заходом он не лечится;
- проход за извещениями спрашивает устаревший лот заново и называет число.

Живые выписки квартала 77:05:0004001 — из `reference_data/krt/egrn`. Своя
подделка подтвердила бы только саму себя.

Запуск: python3 -m pytest tests/test_a_stale_parse_is_read_again.py -q
"""

from __future__ import annotations

import io
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import egrn_archive, egrn_store  # noqa: E402

EXTRACTS = ROOT / "reference_data" / "krt" / "egrn"
LAND = "77:05:0004001:15"
OWNED = "77:05:0004001:1038"


def live(number: str) -> bytes:
    return (EXTRACTS / f"{number.replace(':', '_')}.xml").read_bytes()


def as_short_form(raw: bytes) -> bytes:
    """Та же живая выписка, объявленная краткой формой: меняется ровно корень."""
    short = re.sub(r"extract_about_property_(land|build)",
                   r"extract_base_params_\1", raw.decode("utf-8"))
    assert "extract_base_params_" in short
    return short.encode("utf-8")


def zipped(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_a_record_carries_the_reader_version_it_was_read_by():
    """Чем прочитана запись — часть записи, иначе склад не узнает об устаревании."""
    found = egrn_archive.read(zipped({
        "участок.xml": live(LAND),
        "здание.xml": as_short_form(live(OWNED)),
    }), name="Выписки ЕГРН.zip")

    assert found["read"] == 2, found["unread"]
    # Версия стоит у КАЖДОЙ записи, а не только у разбора целиком: склад сводит
    # записи по кадастровому номеру из разных архивов, и версия разбора целиком
    # сказала бы о свежести чужой записи.
    assert {record["reader_version"] for record in found["records"]} == {
        egrn_archive.READER_VERSION}
    assert found["reader_version"] == egrn_archive.READER_VERSION


def test_the_store_tells_how_many_records_are_behind_the_reader(tmp_path: Path):
    """Запись без версии — первой версии, а не «неизвестно»: байты есть всегда."""
    found = egrn_archive.read(zipped({"участок.xml": live(LAND)}), name="зип")
    egrn_store.save(tmp_path, "лот/1", found, "Выписки ЕГРН.zip")

    kept = egrn_store.load(tmp_path, "лот/1")
    assert egrn_store.stale(kept)["behind"] == 0

    # Так выглядит склад, записанный ДО того, как версию завели.
    for record in kept["records"]:
        record.pop("reader_version", None)
    behind = egrn_store.stale(kept)
    assert behind["behind"] == len(kept["records"]) >= 1
    assert behind["versions"] == {str(egrn_archive.READER_VERSION_BEFORE):
                                  len(kept["records"])}


def test_a_lot_is_asked_again_once_per_change_of_the_rules(tmp_path: Path):
    """Три ответа, и слить их нельзя: свежий разбор, перечитанный, не отданный.

    Без отметки перечитывания устаревший лот спрашивался бы КАЖДЫЙ круг
    сторожа: `krt_territory.notice_due` при прочитанном составе молчит навсегда,
    и цена была бы по карточке лота на круг за ответ, который не изменится.
    """
    found = egrn_archive.read(zipped({"участок.xml": live(LAND)}), name="зип")
    egrn_store.save(tmp_path, "лот/1", found, "Выписки ЕГРН.zip")
    place = tmp_path / egrn_store.DIRNAME / f"{egrn_store.slug('лот/1')}.json"
    kept = json.loads(place.read_text(encoding="utf-8"))
    for record in kept["records"]:
        record.pop("reader_version", None)
    place.write_text(json.dumps(kept, ensure_ascii=False), encoding="utf-8")

    kept = egrn_store.load(tmp_path, "лот/1")
    assert egrn_store.reread_due(kept, now=1_000.0) is True

    # Перечитали, и часть записей осталась прежней — это ответ ДОКУМЕНТОВ
    # (машинной выписки на объект в лоте нет вовсе), вторым заходом он не
    # лечится, и спрашивать снова незачем.
    egrn_store.remember_reread(tmp_path, "лот/1",
                               version=egrn_archive.READER_VERSION,
                               ok=True, now=1_000.0)
    assert egrn_store.reread_due(egrn_store.load(tmp_path, "лот/1"),
                                 now=1_000_000.0) is False

    # А перечитать НЕ ДАЛИ — это ответ площадки, и у него свой короткий срок:
    # Росэлторг отдаёт карточку через раз.
    egrn_store.remember_reread(tmp_path, "лот/1",
                               version=egrn_archive.READER_VERSION,
                               ok=False, why="HTTP 502", now=1_000.0)
    kept = egrn_store.load(tmp_path, "лот/1")
    assert egrn_store.reread_due(kept, now=1_100.0) is False
    assert egrn_store.reread_due(kept, now=1_000.0 + 1_800.0) is True


def test_the_run_asks_again_when_the_reader_rules_changed(tmp_path, monkeypatch):
    """Проход спрашивает устаревший лот заново и называет число.

    Держится здесь то, что видно снаружи: лот с прочитанным составом второй раз
    не спрашивается, а тот же лот с разбором прежних правил — спрашивается, и
    ровно один раз на смену правил.
    """
    from auction_search import krt_pipeline  # локально: ставит маршруты
    import tests.test_the_notice_is_taken_by_the_run as run  # noqa: PLC0415

    monkeypatch.setattr(krt_pipeline, "download_document", run._platform())
    first = krt_pipeline.read_notices(run.BY_SITE, fetch_lot=run._fetcher([]),
                                      store_dir=tmp_path)
    assert (first["read"], first["stale"]) == (1, 0), first

    # Прочитанный состав второй раз не спрашивается — правило на месте.
    again = krt_pipeline.read_notices(
        run.BY_SITE,
        fetch_lot=lambda url: (_ for _ in ()).throw(
            AssertionError("площадку спросили о прочитанном составе")),
        store_dir=tmp_path)
    assert (again["already"], again["asked"]) == (1, 0), again

    # А теперь на складе лежат записи ПРЕЖНЕГО читателя — так выглядел прод
    # 14.09.2026 на 1-й Горловской.
    found = egrn_archive.read(zipped({"участок.xml": live(LAND)}), name="зип")
    for record in found["records"]:
        record.pop("reader_version", None)
    egrn_store.save(tmp_path, run.KEY, found, "Выписки ЕГРН.zip")
    behind = egrn_store.stale(egrn_store.load(tmp_path, run.KEY))
    assert behind["behind"] >= 1, behind

    calls: list[str] = []
    stale_run = krt_pipeline.read_notices(run.BY_SITE,
                                          fetch_lot=run._fetcher(calls),
                                          store_dir=tmp_path)
    assert calls == [run.LOT_URL], "устаревший разбор не перечитан"
    assert stale_run["stale"] == 1, stale_run
    assert stale_run["reader_version"] == egrn_archive.READER_VERSION

    # И ровно один раз: перечитали — дальше это ответ документов, а не наш
    # пробел, и спрашивать снова незачем.
    quiet = krt_pipeline.read_notices(
        run.BY_SITE,
        fetch_lot=lambda url: (_ for _ in ()).throw(
            AssertionError("устаревший лот спрошен второй раз")),
        store_dir=tmp_path)
    assert (quiet["already"], quiet["stale"]) == (1, 0), quiet

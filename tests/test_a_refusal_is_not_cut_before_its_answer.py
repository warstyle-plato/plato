"""Обрезка отказа по длине не съедает его ответ.

Предел стоял числом 200 в двух местах и был заведён РАНЬШЕ диагнозов: у отказа
тогда было пять слов. Диагнозы пришли позже и оба длиннее — печатная форма
кладёт вид, чем прочитано, знаков, подписи и форму клетки номера, машинный
разбор до тридцати путей элементов. Замер прода 15.09.2026 (0.23.82, оба
Прожектора): диагноз вышел 288 знаков, склад записал 200, и на экране стояло
«…, holder_text, lands_text, name» — конца, ради которого диагноз написан, не
было вовсе, а с виду это чужое сообщение, кончившееся на полуслове.

Здесь три утверждения, и они разные: решающее стоит раньше расширяемого
перечисления (обрезанный диагноз теряет хвост списка, а не ответ), предел
объявлен один раз на весь склад, и сработавшая обрезка называется вслух.
"""

from __future__ import annotations

import io
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import egrn_archive, egrn_print_form, egrn_store  # noqa: E402
from tests import egrn_fixtures  # noqa: E402

# Клетка номера, в которой стоит не один номер: ровно такой случай и молчал на
# проде. Значение здесь наше, а в отказ уходит его форма.
GLUED = "77:05:0012007:2054 21.06.2024 77:05:0012007:2055"


def broken_form(cell: str = GLUED) -> str:
    return re.sub(r"(Кадастровый номер:\s*\n)[^\n]+", r"\g<1>" + cell,
                  egrn_fixtures.LIVE, count=1)


def zipped(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in entries.items():
            archive.writestr(name, body)
    return buffer.getvalue()


def test_the_decisive_part_stands_before_the_list_of_labels():
    """Форма клетки — раньше перечисления подписей."""
    try:
        egrn_print_form.read_text(broken_form())
    except ValueError as exc:
        said = str(exc)
    else:
        raise AssertionError("склеенная клетка обязана быть отказом")

    shape_at = said.index("форма «")
    labels_at = said.index("подписей со значением")
    assert shape_at < labels_at, said
    # И «знаков», и «вид» — тоже раньше списка: список последний.
    assert said.index("вид ") < labels_at, said


def test_the_diagnosis_reaches_the_store_whole():
    """Отказ печатной формы доезжает до склада целиком, а не до 200 знаков."""
    data = zipped({"Выписка ЕГРН для здания.pdf":
                   egrn_fixtures.print_form_pdf(broken_form())})
    result = egrn_archive.read(data)

    assert result["records"] == []
    reason = result["unread"][0]["reason"]
    assert len(reason) > 200, reason
    assert f"форма «{egrn_print_form._shape(GLUED)}»" in reason, reason
    assert "обрезано" not in reason, reason


def test_a_cut_names_how_many_characters_there_were():
    """Обрезка называется вслух: молча обрезанный отказ читается как чужой."""
    long = "причина " * 200
    said = egrn_archive.cut_reason(long)

    assert said.endswith(f"… (обрезано с {len(long)} знаков)"), said[-60:]
    assert len(said) < len(long)
    # Короткий отказ не тронут и приписки не получает.
    assert egrn_archive.cut_reason("не XML выписки") == "не XML выписки"


def test_the_limit_fits_the_diagnosis_by_construction():
    """Предел посчитан под ограниченный диагноз, а не назначен на глаз.

    Форма клетки режется по 60 знаков, перечисление подписей — по восьми:
    длина диагноза ограничена по построению, и предел обязан её вмещать.
    Проверяется худшим случаем, а не тем, что вышло на живой выписке.
    """
    worst = broken_form("9" * 400)
    try:
        egrn_print_form.read_text(worst)
    except ValueError as exc:
        said = str(exc)
    else:
        raise AssertionError("клетка из четырёхсот цифр — отказ")

    assert len(said) <= egrn_archive.REASON_LIMIT, len(said)
    assert egrn_archive.cut_reason(said) == said


def test_the_limit_is_declared_once():
    """Ни у склада, ни у разбора нет своего числа: предел один.

    Запрещается МЕСТО, а не написание: `cut_reason` и есть предел, она обрезает
    сама. Копия числа рядом разошлась бы с этой молча — так уже было, когда
    диагнозы переросли предел, о котором не знали.
    """
    for name in ("egrn_archive.py", "egrn_store.py"):
        source = (ROOT / "auction_search" / name).read_text(encoding="utf-8")
        body = source.replace("def cut_reason", "")
        hits = [line for line in body.splitlines()
                if re.search(r'"(?:reason|why)":.*\[:\d+\]', line)]
        assert not hits, (name, hits)


def test_the_store_cuts_the_reread_reason_by_the_same_limit(tmp_path):
    """Почему перечитать не дали — тот же предел и та же приписка."""
    long = "HTTP 503 после трёх попыток; " * 40
    kept = egrn_store.remember_reread(tmp_path, "21000005000000031472/1",
                                  version=egrn_archive.READER_VERSION,
                                  ok=False, why=long)

    said = kept["reread"]["why"]
    assert said.startswith("HTTP 503 после трёх попыток")
    assert said.endswith(f"… (обрезано с {len(long)} знаков)"), said[-60:]
    assert len(said) <= egrn_archive.REASON_LIMIT + 40


def test_the_limit_and_the_reader_version_are_bumped_together():
    """Меняя предел отказа, поднимают версию читателя — иначе починка не доедет.

    Текст отказа — такой же ответ читателя, как запись, и `stale()` сравнивает
    ВЕРСИЮ, а не длину. Значит предел, поднятый без версии, оставляет уже
    записанные обрезанными отказы «свежими» навсегда: на проде их было 56
    (замер 15.09.2026), и починка не доехала бы ровно до того, ради чего
    написана.

    Здесь равенство пары целиком — и это само утверждение: проверка обязана
    падать при правке ЛЮБОЙ половины, чтобы вторая была решена, а не забыта.
    Поднимаете предел — поднимите версию и поправьте эту пару.
    """
    assert (egrn_archive.REASON_LIMIT, egrn_archive.READER_VERSION) == (400, 6), (
        "предел отказа и версия читателя связаны: изменив одно, решите про другое")


def test_a_refusal_written_by_the_previous_reader_is_behind(tmp_path):
    """Отказ прежнего читателя отстаёт — на том пределе, что был до правки.

    Механизм проверяется в `test_a_refused_document_is_read_again_too`, здесь
    же — сам случай, из-за которого версию и поднимали: отказ, обрезанный
    прежним пределом в 200 знаков, обязан считаться отстающим, иначе его
    никогда не перечитают.
    """
    cut = "в форме не прочитан кадастровый номер объекта: вид «зда" + "х" * 150
    kept = {"records": [], "uploads": [{"file": "ЕГРН 1021.pdf", "unread": [
        {"file": "ЕГРН 1021.pdf", "reason": cut[:200],
         "reader_version": egrn_archive.READER_VERSION - 1}]}]}

    behind = egrn_store.stale(kept)
    assert behind["refusals"] == 1 and behind["refusals_behind"] == 1, behind
    assert egrn_store.reread_due(kept) is True, behind

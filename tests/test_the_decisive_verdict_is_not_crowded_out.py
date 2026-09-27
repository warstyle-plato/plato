"""Решающий вердикт о составе территории виден, а не вытеснен повторами.

Замер прода 25.09.2026 по МКАД, 41 км (после починки отбора вложений): площадка
отдала 13 своих файлов, вердикты по ним наконец доехали до надписи — и надпись
кончалась так:

    «Территория.Памятка победителя.16995746.pdf — в документе 2 слов и ни одного
    кадастрового номера — та — таблицы состава нет в прочитанных»

Два дефекта в одном:

1. **Повторы схлопывались по полному тексту причины.** А в тексте стоит число
   слов документа — у каждого вложения своё, поэтому «в документе N слов и ни
   одного кадастрового номера» не схлопывалось само с собой ни разу. Список
   забился ответами одного вида, и вердикт по «Сведениям о земельных участках»
   — единственному вложению, где таблица состава и должна стоять, — в него не
   попал вовсе: чем он был, замер так и не показал. Наш пробел остался
   невидимым, а на экране стояли ответы документов.
2. **Обрезка резала посреди слова.** «та —» это середина слова «таблицы»:
   предел 400 знаков применялся счётом символов, и обрывок читался как текст.

Правило: вид ответа объявляет читатель состава (`TABLE_VERDICT_RANKS`), сводка
схлопывает по ВИДУ и ставит наш пробел прежде ответа документа, а обрезка
причины идёт по границе перечня и называет себя.

Запуск: python3 -m pytest tests/test_the_decisive_verdict_is_not_crowded_out.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import krt_notice, krt_pipeline, krt_territory  # noqa: E402

MARK = "состав территории не разобран: "
# Настоящие имена вложений лота 21000005000000031293 (МКАД, 41 км).
CROWD = [
    "Документация по торгам",
    "Территория.Памятка победителя.16995746.pdf",
    "Территория.Лотовая документация.16995746.pdf",
    "Территория.Проект договора.16995746.pdf",
    "Территория.График КРТ.16995746.pdf",
    "Территория.Извещение.16995746.pdf",
    "Территория.Форма заявки.16995746.pdf",
    "Территория.Требования к участникам.16995746.pdf",
    "Территория.Порядок проведения.16995746.pdf",
    "Территория.Реквизиты.16995746.pdf",
    "Территория.Согласие.16995746.pdf",
    "Территория.Опись.16995746.pdf",
]
DECIDING = "Территория.Сведения о земельных участках.16995746.pdf"


def _mkad_ledger() -> dict:
    """Журнал вложений формы МКАД: двенадцать ответов одного вида и один решающий.

    Число слов у каждого вложения своё — именно оно ломало схлопывание по
    тексту, поэтому подделать его одинаковым нельзя: проверка перестала бы
    ловить дефект.
    """
    skipped = []
    for number, title in enumerate(CROWD, start=1):
        kind, why = krt_notice._why_no_table({"words": 120 * number + 7})
        assert kind == "no_cadastral"
        skipped.append({"document": title, "url": f"https://x/{number}",
                        "why": f"{MARK}{why}"[:400], "verdict": kind})
    # Решающий вердикт стоит ПОСЛЕДНИМ: у МКАД «Сведения о земельных участках»
    # разбирались после лотовой документации, и порядок не должен решать.
    kind, why = krt_notice._why_no_table({"words": 1840, "cadastral_x": [251, 253, 383]})
    assert kind == "columns_missed"
    skipped.append({"document": DECIDING, "url": "https://x/deciding",
                    "why": f"{MARK}{why}"[:400], "verdict": kind})
    return {"skipped": skipped}


def test_repeats_of_one_kind_do_not_crowd_out_our_own_gap() -> None:
    said = krt_pipeline._table_verdicts(_mkad_ledger())

    assert DECIDING in said, "решающий вердикт не попал в сводку вовсе"
    assert "не попал в окно колонки участка" in said
    assert "Это наш пробел" in said
    # Наш пробел стоит ПРЕЖДЕ ответа документа: «таблицы тут нет» у памятки
    # победителя — это норма, а «колонки не там» чинится кодом.
    assert said.index(DECIDING) < said.index("ни одного кадастрового номера"), said
    # Двенадцать ответов одного вида — одна строка, и её кратность названа.
    assert said.count("ни одного кадастрового номера") == 1
    assert "и ещё 11 с тем же ответом" in said, said


def test_the_repeats_differ_in_text_so_the_old_rule_could_not_collapse_them() -> None:
    """Предохранитель: по тексту эти причины НЕ повторяются, и в этом было дело.

    Без него проверка выше прошла бы и на прежнем правиле — достаточно, чтобы
    причины оказались текстуально равны.
    """
    reasons = [str(one["why"])[len(MARK):] for one in _mkad_ledger()["skipped"]]
    crowd = [one for one in reasons if "ни одного кадастрового номера" in one]
    assert len(crowd) == len(CROWD)
    assert len(set(crowd)) == len(CROWD), "число слов обязано различаться"
    # Прежнее правило: повтор отсеивался, если текст причины уже назван. На этих
    # данных оно не отсеивает ничего — список набивается до предела.
    kept: list[str] = []
    for reason in reasons:
        if not any(reason in one for one in kept):
            kept.append(reason)
    assert len(kept) == len(reasons)
    assert DECIDING not in "; ".join(kept[:3]), "иначе дефект не воспроизведён"


def test_an_unnamed_verdict_is_not_hidden_behind_the_documents_answer() -> None:
    """Вид не назван — это НАШ неразобранный отказ, и он стоит выше «таблицы тут нет»."""
    kind, documents_answer = krt_notice._why_no_table({"words": 700})
    ledger = {"skipped": [
        {"document": "Территория.Опись.pdf", "why": f"{MARK}{documents_answer}",
         "verdict": kind},
        {"document": "Территория.Схема.pdf",
         "why": f"{MARK}нечем прочитать PDF: no module named 'pymupdf'"},
    ]}
    said = krt_pipeline._table_verdicts(ledger)
    assert said.index("нечем прочитать PDF") < said.index("ни одного кадастрового")
    assert krt_notice.table_verdict_rank("") < krt_notice.table_verdict_rank("no_cadastral")


def test_every_verdict_the_reader_gives_has_a_declared_rank() -> None:
    """Правило объявлено — читатели им пользуются. Вид, которого нет в карте
    важности, встал бы в сводке произвольно и молча."""
    seen = [{}, {"words": 500}, {"words": 500, "cadastral_x": [250]}]
    kinds = {krt_notice._why_no_table(one)[0] for one in seen}
    assert kinds == {"scan", "no_cadastral", "columns_missed"}
    assert kinds <= set(krt_notice.TABLE_VERDICT_RANKS)
    assert "no_reader" in krt_notice.TABLE_VERDICT_RANKS


def test_the_refusal_carries_its_kind_out_of_the_reader() -> None:
    """Вид едет ИЗ читателя вместе с отказом, а не угадывается по тексту."""
    pymupdf = pytest.importorskip("pymupdf")
    document = pymupdf.open()
    document.new_page()
    with pytest.raises(krt_notice.NoticeProblem) as refusal:
        krt_notice.read_bytes(document.tobytes())
    assert refusal.value.kind == "scan"


def test_a_long_reason_is_cut_on_a_boundary_and_says_so(tmp_path) -> None:
    """Обрезка не рвёт слово и не выдаёт укороченное за полное."""
    ledger = _mkad_ledger()
    # Неразобранные отказы схлопнуть по виду нельзя — вида у них нет, и текст у
    # каждого свой. Именно они и делают перечень длинным.
    for number in range(6):
        ledger["skipped"].append({
            "document": f"Территория.Приложение {number}.16995746.pdf",
            "why": f"{MARK}нечем прочитать PDF: cannot open broken document "
                   f"(xref {number}0421, страница {number})"})
    said = krt_pipeline._table_verdicts(ledger)
    head = ("вложения лота площадка отдала, их 13 прочитано, но не прочитано "
            "вложений: 3 (Территория.Фото объекта.16995746.zip; "
            "Территория.Постановление.16995746.pdf; "
            "Территория.Схема границ.16995746.pdf)")
    why = f"{head}. О прочитанных читатель состава сказал: {said}"
    assert len(why) > krt_territory.WHY_LIMIT, "иначе предел не проверяется"

    krt_territory.remember_attempt("lot:mkad", outcome="unread", why=why,
                                   documents=13, root=tmp_path)
    stored = json.loads(
        krt_territory.attempt_path("lot:mkad", root=tmp_path).read_text(encoding="utf-8"))
    kept = str(stored["why"])
    assert kept.endswith("… (дальше обрезано)"), kept[-60:]
    body = kept[:-len("… (дальше обрезано)")]
    assert why.startswith(body), "обрезка изменила текст, а не укоротила его"
    # Слово не разорвано: следом за концом идёт граница, а не буква.
    assert why[len(body):len(body) + 1] in (" ", ";", ""), repr(why[len(body):len(body) + 8])
    # Решающий вердикт стоит в начале перечня и обрезку переживает.
    assert DECIDING in kept and "Это наш пробел" in kept
    note = krt_territory._attempt_problem(stored)
    assert "Это наш пробел" in note and DECIDING in note

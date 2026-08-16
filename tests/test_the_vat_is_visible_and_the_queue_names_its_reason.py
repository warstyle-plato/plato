"""Две вещи, которых человек не мог увидеть, глядя прямо на них.

**НДС в отчёте.** Движок его считал, книга платила, чистая прибыль падала на
миллиард — а на экране налог был один: «Налог на прибыль». Блок «Налоговая
база по реализованным продуктам» обрывался на нём, экономика не сходилась
(прибыль до налога минус налог ≠ чистая прибыль), и разницу человеку было
негде найти. Числитель LLCR тоже не сходился: движок вычитает НДС, а столбец
его не показывал — покрытие выглядело необъяснимо низким.

**Причина срыва Платона.** Обратная схема: ядро кладёт задание в очередь и
ждёт, Render его забирает. Когда никто не приходил, ядро отвечало догадкой —
«проверьте, запущен ли разбор очереди». Под этой одной фразой прятались три
разных случая: разбор не запущен вовсе, Render заснул, разбор жив, но задания
не берёт. Ядро при этом знает факт, который их различает, — приходил ли кто-то
за очередью и когда.

Правило проекта прежнее: ошибка, которую видно не ту, хуже невидимой.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


@pytest.fixture(scope="module")
def result():
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update(apartment_price_th=650, commercial_price_th=650,
                  parking_price_th=5000, purchase_price_mln=700)
    return core.calculate(core.CalcRequest(
        inputs=inputs, tep=copy.deepcopy(core.TEP_DEFAULT), rates=[]))


# --- НДС дошёл до сводки ---------------------------------------------------------

def test_the_summary_carries_the_vat(result):
    """Поверхности читают summary; без ключа налог там не появится ни в PDF,
    ни в книге, ни на странице."""
    assert result["summary"]["vat"] == pytest.approx(result["finance"]["vat"], rel=1e-9)
    assert result["summary"]["vat"] > 0


def test_the_phased_summary_carries_it_too():
    """Очереди складывают свои НДС — сводка обязана нести сумму."""
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update(apartment_price_th=650, commercial_price_th=650, parking_price_th=5000)
    bundle = core._run_authoritative_model(
        inputs, copy.deepcopy(core.TEP_DEFAULT), [],
        {"enabled": True, "mode": "phased", "phase_count": 3, "user_enabled": True,
         "phase_gap_months": 12,
         "phases": [{"name": f"О{i+1}", "start_offset_months": 12 * i,
                     "construction_months": 24} for i in range(3)]})
    consolidated = bundle["consolidated"]
    assert consolidated["summary"]["vat"] == pytest.approx(
        consolidated["finance"]["vat"], rel=1e-9)


def test_the_unit_economics_show_the_vat(result):
    """Удельная экономика — на обеих базах, как всё остальное в отчёте."""
    line = next(item for item in result["report"]["unit_economics"]
                if item["label"] == "НДС")
    assert line["total"] == pytest.approx(result["finance"]["vat"], rel=1e-9)
    assert line["per_gns_th"] > 0 and line["per_saleable_th"] > 0


# --- НДС виден на странице -------------------------------------------------------

def test_the_tax_card_names_the_vat():
    """Блок налоговой базы обрывался на налоге на прибыль."""
    page = core.PAGE
    assert "НДС к уплате" in page
    assert "Итого налоги" in page


def test_the_llcr_column_subtracts_the_vat():
    """Движок вычитает НДС из числителя — столбец обязан это показывать,
    иначе он не сходится к собственному итогу."""
    start = core.PAGE.index("llcrTable.innerHTML=")
    block = core.PAGE[start:core.PAGE.index("Числитель LLCR", start)]
    assert "f.vat" in block


def test_the_economics_table_reconciles():
    """Прибыль до налога минус налог давала не чистую прибыль."""
    start = core.PAGE.index("economicsTable.innerHTML=")
    block = core.PAGE[start:core.PAGE.index("Чистая прибыль", start)]
    assert "summary.vat" in block


def test_the_pdf_and_the_model_export_carry_it():
    """Тот же налог в выгрузке модели и в приложении к PDF."""
    assert ("vat", "НДС", "mln") in core._MODEL_SUMMARY_ROWS


# --- очередь называет причину ----------------------------------------------------

def test_without_a_puller_the_reason_is_named():
    """Никто не приходил — значит, разбор не запущен, и это говорится прямо."""
    (core._PLATO_STAGE_DIR / "puller.seen").unlink(missing_ok=True)
    assert core._plato_puller_seen_ago() is None
    reason = core._plato_puller_diagnosis()
    assert "ни разу" in reason
    assert "PLATO_PULL_URL" in reason


def test_a_fresh_poll_moves_the_blame_to_the_worker():
    """Связь есть — значит, виноват не адрес и не сон, а сам разбор."""
    core._plato_puller_seen_touch()
    ago = core._plato_puller_seen_ago()
    assert ago is not None and ago < 5
    assert "дело в самом разборе" in core._plato_puller_diagnosis()
    (core._PLATO_STAGE_DIR / "puller.seen").unlink(missing_ok=True)


def test_a_stale_poll_reads_as_a_sleeping_service():
    """Приходил час назад и замолчал — это сон, а не отсутствующая настройка."""
    path = core._PLATO_STAGE_DIR / "puller.seen"
    path.parent.mkdir(parents=True, exist_ok=True)
    import time

    path.write_text(str(time.time() - 3600), encoding="utf-8")
    assert "заснул" in core._plato_puller_diagnosis()
    path.unlink(missing_ok=True)


def test_the_marker_is_not_mistaken_for_a_job():
    """Отметка лежит в том же каталоге, что и задания: она не должна попасть
    ни в счётчик ожидающих, ни в выборку на исполнение."""
    core._plato_puller_seen_touch()
    assert list(core._PLATO_STAGE_DIR.glob("job_*.json")) == []
    assert core._plato_job_claim() == {}
    (core._PLATO_STAGE_DIR / "puller.seen").unlink(missing_ok=True)

"""Новая сборка читает НЦС вне постоянного data/, включая сборку настоящей PAGE.

Изолируем только упаковку НЦС: остальные модули и прежний нормативный реестр
берутся из репозитория. Свежий процесс не может получить каталог из кэша
родительского процесса или подхватить education_ncs.py из рабочей копии.
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
ASSET = Path("reference_data/education_ncs_2026.json")
PROBE = """
import json
from decimal import Decimal
from pathlib import Path
import socket
import sys

stage, source = map(Path, sys.argv[1:])
sys.path[:0] = [str(stage), str(source)]

def refuse_network(*args, **kwargs):
    raise AssertionError('NCS packaging probe must not use the network')

socket.socket.connect = refuse_network
socket.create_connection = refuse_network

import education_ncs
assert Path(education_ncs.__file__).parent == stage
# Importing the real engine executes page_build, including catalog embedding.
import main_legacy as core
import mo_vri_benefits

expected = json.loads((stage / 'reference_data/education_ncs_2026.json').read_text())
assert len(expected['tables']) == 37
assert sum(len(table['points']) for table in expected['tables']) == 89
assert education_ncs.catalog() == expected
assert education_ncs.rate('school', '03-03-007', Decimal(675))['rate'] == 1321940
assert education_ncs.rate('kindergarten', '03-01-001', Decimal(60))['rate'] == 2131470
result = mo_vri_benefits.estimate({'schema': 1, 'rows': [{
    'id': 'education', 'kind': 'school', 'required_places': 400,
    'planned_places': 675, 'valuation_mode': 'ncs', 'ncs_table': '03-03-007',
}]}, inputs={}, tep={})
assert result['total_rub'] == 363533500
catalog_literal = core.PAGE.split('const MO_BENEFITS_CATALOG=', 1)[1]
embedded, _ = json.JSONDecoder().raw_decode(catalog_literal)
assert embedded['education_ncs'] == expected
assert '__DEVELOPAID_MO_BENEFITS_CATALOG__' not in core.PAGE
print('NCS rate, benefit and real PAGE catalog: PASS')
"""


@pytest.mark.parametrize("mutable_data", ["missing", "empty", "stale"])
def test_packaged_ncs_survives_mutable_data_mount(tmp_path, mutable_data):
    stage = tmp_path / "app"
    stage.mkdir()
    shutil.copy2(ROOT / "education_ncs.py", stage)
    (stage / ASSET.parent).mkdir()
    shutil.copy2(ROOT / ASSET, stage / ASSET)
    data = stage / "data"
    if mutable_data != "missing":
        data.mkdir()
    if mutable_data == "stale":
        (data / "education_ncs_2026.json").write_text('{"tables": []}')

    environment = os.environ.copy()
    environment.pop("DEVELOPAID_ADMIN_KEY", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["DATA_DIR"] = str(data)
    done = subprocess.run(
        [sys.executable, "-I", "-c", PROBE, str(stage), str(ROOT)],
        cwd=stage, env=environment, capture_output=True, text=True, timeout=45,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "NCS rate, benefit and real PAGE catalog: PASS" in done.stdout
    if mutable_data == "missing":
        assert not (data / "education_ncs_2026.json").exists()
    elif mutable_data == "empty":
        assert list(data.iterdir()) == []
    else:
        assert (data / "education_ncs_2026.json").read_text() == '{"tables": []}'

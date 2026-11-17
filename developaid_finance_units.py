"""An explicit owner-declared storage unit belongs to exact saved FM bytes."""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import re
from pathlib import Path

UNITS = {'руб.': 1., 'тыс. руб.': 1000., 'млн руб.': 1000000.}


def metadata(path):
    try:
        path = Path(path)
    except TypeError:
        return {}
    if path.name != 'finance.xlsx':
        return {}
    try:
        value = json.loads(path.with_name('finance_meta.json').read_text())
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def resolve(header, meta, source_sha256):
    if not isinstance(source_sha256, str) or not re.fullmatch(r'[a-f0-9]{64}', source_sha256):
        return header
    declaration = (meta if isinstance(meta, dict) else {}).get('money_unit')
    if not isinstance(declaration, dict) or declaration.get('basis') != 'owner_declaration' \
            or declaration.get('source_sha256') != source_sha256 \
            or not isinstance(declaration.get('unit'), str) or declaration['unit'] not in UNITS:
        return header
    if header.get('state') not in {'missing', 'observed'}:
        return header
    unit = declaration['unit']
    if header.get('state') == 'observed' and header.get('recognized_unit') != unit:
        return dict(header, state='ambiguous', recognized_unit=None,
                    reason='Объявленные единицы расходятся с шапкой финансовой модели.')
    return dict(header, state='observed', recognized_unit=unit,
                basis='owner_declaration', source_sha256=source_sha256,
                header_evidence=copy.deepcopy(header), declaration=copy.deepcopy(declaration))


def configure(project, unit='', *, expected_source_sha256=''):
    import developaid_monitor as monitor
    import developaid_finance_allocations as allocations
    import developaid_schedule_versions as versions

    if not isinstance(project, str) or not project.strip() or len(project) > 200 or any(c in project for c in ('/', '\\', '\0')):
        raise ValueError('Некорректный проект.')
    if unit and unit not in UNITS:
        raise ValueError('Выберите рубли, тысячи или миллионы рублей.')
    with allocations.source_lock(project):
        path = monitor._project_dir(project) / 'baseline' / 'finance.xlsx'
        if not path.exists():
            raise ValueError('Финансовая модель не загружена.')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        meta = monitor.finance_baseline_meta(project)
        if meta.get('source_sha256') and meta['source_sha256'] != digest:
            raise ValueError('Финансовая модель изменилась; обновите данные.')
        if unit:
            if expected_source_sha256 != digest:
                raise ValueError('Финансовая модель изменилась; обновите данные.')
            declaration = dict(unit=unit, basis='owner_declaration', source_sha256=digest,
                recorded_at=dt.datetime.now(dt.timezone.utc).isoformat())
            meta.update(source_sha256=digest, money_unit=declaration)
            versions._atomic(path.with_name(monitor.FINANCE_META),
                             json.dumps(meta, ensure_ascii=False).encode())
        return dict(source_sha256=digest, money_unit=meta.get('money_unit'),
                    file_name=meta.get('file_name') or 'finance.xlsx', taken_at=meta.get('taken_at'))

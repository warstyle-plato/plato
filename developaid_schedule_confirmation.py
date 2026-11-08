"""Private, version-bound human confirmations of the PM calendar and RNV chain.

These are evidence about a particular source, not approval of a forecast or a
substitute for physical quantities. Append-only events preserve revocations;
historical cuts never see a confirmation recorded after their date.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

import developaid_monitor as monitor


class ConfirmationProblem(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _today() -> dt.date:
    return _now().date()


def _source_sha(project: str) -> str:
    path = monitor._project_dir(project) / 'baseline' / 'pm.xlsx'
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return ''


def _events(folder: Path) -> list[dict]:
    # Malformed audit data must fail closed rather than uncover an older approval.
    events = []
    for revision, path in enumerate(sorted(folder.glob('[0-9]*.json')), 1):
        event = json.loads(path.read_text(encoding='utf-8'))
        if (event['revision'] != revision or path.stem != f'{revision:012d}'
                or not re.fullmatch(r'[0-9a-f]{64}', event['source_sha256'])
                or event['calendar_basis'] not in {'unconfirmed', 'calendar_days'}
                or type(event['rnv_chain_complete']) is not bool
                or not isinstance(event['note'], str)
                or dt.datetime.fromisoformat(event['recorded_at']).utcoffset() != dt.timedelta(0)):
            raise ValueError('invalid confirmation history')
        events.append(event)
    return events


def view(project: str, cut: str = '', *, source_sha256: str | None = None) -> dict:
    day = dt.date.fromisoformat(cut) if cut else _today()
    sha = _source_sha(project) if source_sha256 is None else source_sha256
    events = _events(monitor._project_dir(project) / 'schedule_confirmations')
    matching = [event for event in events if sha and event['source_sha256'] == sha
                and dt.datetime.fromisoformat(event['recorded_at']).date() <= day]
    latest = matching[-1] if matching else {}
    return {'source_sha256': sha, 'revision': events[-1]['revision'] if events else 0,
            'calendar_basis': latest.get('calendar_basis', 'unconfirmed'),
            'rnv_chain_complete': latest.get('rnv_chain_complete', False),
            'note': latest.get('note', ''), 'recorded_at': latest.get('recorded_at'),
            'cut': day.isoformat(), 'can_edit': bool(sha) and day == _today()}


def save(project: str, source_sha256: str, revision: int, calendar_basis: str,
         rnv_chain_complete: bool, note: str) -> dict:
    try:
        import fcntl
    except ImportError:
        raise ConfirmationProblem('Сохранение подтверждений недоступно в этой среде.', 503) from None
    if calendar_basis not in {'unconfirmed', 'calendar_days'}:
        raise ConfirmationProblem('Поддерживается только расчёт в календарных днях, включая выходные и праздники.')
    if type(rnv_chain_complete) is not bool:
        raise ConfirmationProblem('Укажите, проверена ли полнота цепочки до получения РНВ.')
    if not note.strip() or len(note) > 1000:
        raise ConfirmationProblem('Укажите основание проверки или снятия подтверждения (до 1000 знаков).')
    folder = monitor._project_dir(project) / 'schedule_confirmations'
    folder.mkdir(parents=True, exist_ok=True)
    # Production uses two workers: optimistic revision plus a process-shared lock
    # prevent one editor from silently overwriting another editor's decision.
    with (folder / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = view(project)
        if not current['source_sha256']:
            raise ConfirmationProblem('Сначала загрузите исходную PM-выгрузку со связями работ.')
        if source_sha256 != current['source_sha256'] or revision != current['revision']:
            raise ConfirmationProblem('График или подтверждение изменились. Обновите данные и проверьте их заново.', 409)
        event = {'revision': revision + 1, 'source_sha256': source_sha256,
                 'calendar_basis': calendar_basis, 'rnv_chain_complete': rnv_chain_complete,
                 'note': note.strip(), 'recorded_at': _now().isoformat(),
                 'actor': 'administrator'}
        # Write fully before exposing the event to readers. A failed write must
        # neither truncate prior evidence nor be mistaken for a revocation.
        fd, temporary = tempfile.mkstemp(prefix='.event-', dir=folder)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(event, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, folder / f'{event["revision"]:012d}.json')
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return view(project)


def qualify(project: str, pm: dict, cut: str) -> dict:
    """Attach confirmation only to the bytes actually parsed by the PM reader."""
    try:
        state = view(project, cut, source_sha256=pm.get('source_sha256', ''))
    except (OSError, ValueError, KeyError, TypeError):
        return dict(pm, calendar_confirmed=False, rnv_chain_complete=False, confirmation={},
                    validation_issues=list(pm.get('validation_issues') or []) + [
                        'Историю проверок исходного графика не удалось прочитать. '
                        'Подтверждения календаря и цепочки до РНВ не применены.'])
    return dict(pm, calendar_confirmed=state['calendar_basis'] == 'calendar_days',
                rnv_chain_complete=state['rnv_chain_complete'], confirmation=state)

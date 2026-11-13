"""Administrative historical fact proof; never an alternative calendar view."""
import hashlib
import json

import developaid_monitor as monitor
import developaid_schedule_gpr_physical as physical
import developaid_schedule_completed_facts as completed
import developaid_cumulative_progress as cumulative


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def projection(project, cut):
    selected = monitor._baseline_state(project, cut)
    source = physical._source(project, cut, _archival=True)
    snapshot = physical._snapshot(project, cut)
    state = physical._state(project, cut, source, snapshot)
    known = bool(selected['source_sha256'] and snapshot and cumulative.snapshot_date(snapshot))
    factual = {'archival_source_sha256': selected['source_sha256'],
               'snapshot_id': (snapshot or {}).get('snapshot_id'),
               'manual': monitor.work_facts(project, cut, archival=True),
               'quantities': cumulative.quantity_views(snapshot, cut),
               'completed': completed.build(project, cut, snapshot, physical=physical)}
    sid = (snapshot or {}).get('snapshot_id')
    return {'cut': cut, 'known': known,
            'archival_source_sha256': selected['source_sha256'],
            'archival_source_revision': selected['revision'],
            'snapshot_id': sid, 'snapshot_sha256': (snapshot or {}).get('sha256') or (sid or '')[11:],
            'physical_revision': state['revision'],
            'physical_configuration_sha256': _digest(state['configuration']) if known else None,
            'factual_state_sha256': _digest(factual) if known else None}

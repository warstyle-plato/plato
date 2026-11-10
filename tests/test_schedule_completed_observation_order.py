"""An old KS backfill and a new KS reading have different temporal meaning."""
import copy
import datetime as dt

import pytest

import developaid_schedule_gpr_physical as physical
from test_schedule_links_carry import site, save, approve, book, config, PROJECT, TODAY
from test_schedule_physical import snapshot


@pytest.mark.parametrize('actual,observed,completed_hour,partial_hour,retained', [
    ('2026-11-07', '2026-11-06', 8, 18, True),
    ('2026-11-05', '2026-11-09', 8, 18, False),
    ('2026-11-09', '2026-11-09', 8, 18, False),
    ('2026-11-09', '2026-11-09', 18, 8, True),
])
def test_saved_readings_order_by_observation_then_utc_save_time(
        site, monkeypatch, actual, observed, completed_hour, partial_hour, retained):
    def clock(hour):
        monkeypatch.setattr(physical, '_now', lambda:
            dt.datetime(2026, 11, 9, hour, tzinfo=dt.timezone.utc))
    clock(completed_hour)
    save(TODAY, config(actual))
    approve(book(finish='2027-03-01'))
    archive = snapshot()
    archive['snapshot_id'] = observed + '-' + 'c' * 64
    archive['ledgers'][0]['items'][0].update(completed_quantity=60, periods=[])
    site[1]['current'] = site[1][archive['snapshot_id']] = archive
    clock(partial_hour)
    save(TODAY, config())
    before = {str(p): p.read_bytes() for p in site[0].rglob('*.json')}
    original = copy.deepcopy(site[1])
    state = physical.catalog(PROJECT, TODAY)
    assert state['model']['tasks'][0]['progress'] == pytest.approx(.6)
    facts = state['model']['completed_facts']['qualified_task_completions']
    assert len(facts) == int(retained)
    if retained:
        assert facts[0]['actual_finish'] == actual
    assert site[1] == original
    assert before == {str(p): p.read_bytes() for p in site[0].rglob('*.json')}

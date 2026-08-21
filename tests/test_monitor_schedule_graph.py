import datetime

import developaid_monitor_schedule_graph as graph


def test_parse_russian_project_links():
    rows = graph._parse_predecessors("702ОН+30д;759НН;1438ОО-5д;904НО")
    assert rows == [
        {"id": "702", "type": "FS", "lag_days": 30},
        {"id": "759", "type": "SS", "lag_days": 0},
        {"id": "1438", "type": "FF", "lag_days": -5},
        {"id": "904", "type": "SF", "lag_days": 0},
    ]


def test_delay_only_propagates_when_dependency_requires_it():
    d = datetime.date
    pm = {"tasks": {
        "1": {"id":"1","name":"Фасад","start":d(2026,1,1),"finish":d(2026,1,10),"duration_days":9,
              "predecessors":[],"free_float_days":0,"total_float_days":0},
        "2": {"id":"2","name":"Отделка","start":d(2026,1,20),"finish":d(2026,1,30),"duration_days":10,
              "predecessors":[{"id":"1","type":"FS","lag_days":0}],"free_float_days":0,"total_float_days":10},
        "3": {"id":"3","name":"Кровля","start":d(2026,1,5),"finish":d(2026,1,25),"duration_days":20,
              "predecessors":[],"free_float_days":0,"total_float_days":0},
    }}
    tasks = graph._propagate(pm, {"1": d(2026,1,25), "3": d(2026,2,20)})
    assert tasks["2"]["forecast_start"] == d(2026,1,25)
    assert tasks["2"]["inherited_delay_days"] == 5
    assert tasks["1"]["forecast_finish"] == d(2026,1,25)
    assert tasks["3"]["forecast_finish"] == d(2026,2,20)

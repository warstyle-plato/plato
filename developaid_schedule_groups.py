"""Presentation groups retain source sections and never assign calculation weights."""
import re

ORDER = ('ПИР', 'Конструктив', 'Фасады', 'ВИС. Подземная часть',
         'ВИС. Надземная часть', 'Отделка помещений', 'Наружные сети', 'Благоустройство')


def section(row, assignment=None):
    original = row.get('section') or 'Без этапа'
    if re.match(r'^Этап\s+[1-5]\.\s*(Разработка проекта|АГР|Экспертиза|Сопроводительная)', original, re.I):
        return 'ПИР'
    if ((assignment or {}).get('element_id') == 'landscape'
            or row.get('construction_work') is True and re.match(r'^Благоустройство\b', row.get('name') or '', re.I)):
        return 'Благоустройство'
    return original


def order(name):
    return (ORDER.index(name) if name in ORDER else len(ORDER), name)


def metadata(rows):
    from developaid_schedule_plan_scenario import group
    grouped = {}
    for row in rows:
        grouped.setdefault(section(row), []).append(row)
    return dict(by_id={str(r['id']): section(r) for r in rows}, order=list(ORDER),
                summaries={name: group(members) for name, members in grouped.items()})

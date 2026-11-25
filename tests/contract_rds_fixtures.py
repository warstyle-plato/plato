"""Synthetic primary statement and RDS, through the native plan/fact/card pipeline."""
import copy

import developaid_contract_comparison_export as export
import developaid_contract_fact as fact
import developaid_contract_files as files
import developaid_contract_plan as plan
import developaid_contract_rds as rds
import developaid_contract_schedule_links as links

PROJECT, CUT, CONTRACT = 'Учебный проект', '2026-03-05', 'c'*64


def native_card(*, unknown=False, empty=False, finished=False):
    cut = '2026-03-15' if finished else CUT
    positions = [
        {'number': '3.1', 'name': 'Кладка стен', 'unit': 'м3', 'quantity': 20.0,
         'unit_price': {'material': 0.0, 'work': 50.0, 'total': 50.0},
         'amount': {'material': 0.0, 'work': 1000.0, 'total': 1000.0}, 'page': 1, 'group': None, 'section': None},
        {'number': '3.2', 'name': 'Работа с нулевым фактом', 'unit': 'м2', 'quantity': 10.0,
         'unit_price': {'material': 0.0, 'work': 100.0, 'total': 100.0},
         'amount': {'material': 0.0, 'work': 1000.0, 'total': 1000.0}, 'page': 1, 'group': None, 'section': None},
    ]
    schedule = {'lines': [{'code': p['number'], 'name': p['name'], 'start': '2026-03-01',
                           'finish': '2026-03-10', 'parent': None} for p in positions],
                'assumption': 'Границы взяты из подписанных интервалов диаграммы.'}
    estimate = {'scope': 'full', 'positions': positions, 'structure': [], 'warnings': [], 'totals': []}
    estimate['links'] = links.propose(estimate, schedule)
    edition = {'sha256': 'a'*64, 'estimate_sha256': 'a'*64, 'title': 'Учебная редакция',
               'date': '2026-02-01', 'estimate_title': 'Расчёт.pdf', 'estimates': [estimate],
               'schedule': schedule, 'schedule_title': 'ГПР.pdf', 'schedule_sha256': 'b'*64, 'start': None}
    physical = []
    for index, position in enumerate(positions):
        quantity = (20.0 if finished else 6.0) if index == 0 else 0.0
        period = {'quantity': quantity, 'material_quantity': 0.0, 'amount': quantity*position['unit_price']['work'],
                  'work_amount': quantity*position['unit_price']['work'], 'material_amount': 0.0,
                  'amount_split': True, 'date_start': '2026-03-01',
                  'date_end': '2026-03-14' if finished else CUT,
                  'label': 'КС-2 № 1', 'source': {'row': index+5, 'sheet': 'КС-6а'}}
        item = {'position': position['number'], 'name': position['name'], 'unit': position['unit'],
                'plan_quantity': position['quantity'], 'completed_quantity': quantity,
                'reported_completed_quantity': quantity, 'periods': [period]}
        if unknown and index == 0:
            item.update(completed_quantity=None, quantity_basis='Дата выполнения не подтверждена')
            item['periods'][0].update(date_end=None)
        physical.append(item)
    found = fact.acts({'physical_items': physical})
    planned = plan.build([] if empty else [edition], cut)
    performed = fact.build([] if empty else [edition], planned['in_force'], found, cut)
    binding = {'number': 'Т-1', 'date': '2026-02-01'}
    documents = [] if empty else [
        {'sha256': 'a'*64, 'title': 'Расчёт.pdf', 'contract': binding, 'estimates': [estimate]},
        {'sha256': 'b'*64, 'title': 'ГПР.pdf', 'contract': binding, 'schedule': schedule}]
    listed = files._with_control({'contract_id': CONTRACT, 'documents': documents, 'plan': planned,
                                  'fact': performed}, found, cut)
    cached = {'ok': True, 'pending': False, **listed}
    cached['rds_comparison'] = rds.build(cached)
    cached['comparison_export'] = export.bind_snapshot(PROJECT, cut, CONTRACT, cached,
        {'contract': 'Т-1', 'contractor': 'Учебный подрядчик'})
    return copy.deepcopy(cached)

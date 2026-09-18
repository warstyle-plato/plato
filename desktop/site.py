"""Use the existing public site services; keep calculations and projects local."""
from __future__ import annotations
import copy
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field
import developaid_v2_form as form

HOST = 'https://developaid.ru'
NUMBER = re.compile(r'^\d{2}:\d{2}:\d{6,8}:\d+$')
MARKERS = ['_glavapu_import', '_manual_tep_import', '_mo_calc', '_cadastral_analysis',
           '_site_area_user_set', '_site_density_user_set', '_desktop_site']
FLAGS = ['offices_enabled', 'retail_enabled', 'above_parking_enabled', 'sports_enabled']

class LookupRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)

class SiteRequest(BaseModel):
    cadastral_numbers: list[str] = Field(min_length=1, max_length=30)
    query: str = Field(default='', max_length=2000)
    region: Literal['auto', 'msk', 'mo'] = 'auto'


def remote(path: str, payload: dict) -> dict:
    if path not in {'/land/lookup', '/cadastral/analyze', '/cadastral/tep-server', '/mo/calculate'}:
        raise ValueError('Неизвестный сервис участка')
    url = HOST + path
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={
        'Content-Type': 'application/json', 'Accept': 'application/json',
        'User-Agent': 'DevelopAid-Desktop/0.2'})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            if response.geturl() != url:
                raise ValueError('Сервис участка перенаправил запрос. Данные проекта не изменены.')
            raw = response.read(4_000_001)
        if len(raw) > 4_000_000:
            raise ValueError('Слишком большой ответ сервиса участка')
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError('Некорректный ответ сервиса участка')
        return result
    except urllib.error.HTTPError as exc:
        try:
            reason = json.loads(exc.read(8000)).get('detail', '')
        except Exception:
            reason = ''
        raise ValueError(f'Сервис участка ответил ошибкой {exc.code}. {str(reason)[:400]}') from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ValueError('Не удалось связаться с DevelopAid. Проверьте интернет и повторите поиск. '
                         'Данные проекта не изменены.') from exc


def lookup(req: LookupRequest) -> dict:
    query = req.query.strip().replace('：', ':')
    if not query:
        raise ValueError('Введите кадастровый номер или адрес')
    if ':' in query:
        numbers = list(dict.fromkeys(x.strip() for x in re.split(r'[,;\n]+', query) if x.strip()))
        if len(numbers) > 30 or any(not NUMBER.fullmatch(x) for x in numbers):
            raise ValueError('Нужен кадастровый номер вида 77:09:0004014:13. '
                             'Несколько номеров разделяйте запятой или новой строкой.')
        return {'items': [{'cadastral_number': n, 'address': 'Номер введён вручную — проверяется при получении ТЭП'}
                          for n in numbers], 'warnings': []}
    data = remote('/land/lookup', {'query': query, 'limit': 30})
    items, seen = [], set()
    for row in data.get('results', []):
        number = str(row.get('cadastral_number') or '')
        if row.get('found') and row.get('kind') == 'land' and NUMBER.fullmatch(number) and number not in seen:
            seen.add(number)
            items.append({key: row.get(key) for key in ('cadastral_number', 'address', 'area_sqm')})
    warnings = [str(x) for x in data.get('warnings', [])]
    if data.get('reason'):
        warnings.append(str(data['reason']))
    return {'items': items, 'warnings': warnings,
            'message': '' if items else 'Участок не найден. Уточните адрес до дома или введите кадастровый номер.'}


def preview(core, req: SiteRequest) -> dict:
    numbers = list(dict.fromkeys(n.strip() for n in req.cadastral_numbers))
    if any(not NUMBER.fullmatch(n) for n in numbers):
        raise ValueError('Проверьте кадастровые номера')
    region, analysis = req.region, None
    if region != 'mo':
        analysis = remote('/cadastral/analyze', {'cadastral_numbers': numbers})
        recognized = set(analysis.get('recognized') or [])
        if recognized != set(numbers):
            raise ValueError('Сервис не подтвердил все выбранные участки. Проверьте номера: '
                             + ', '.join(n for n in numbers if n not in recognized))
        inside = bool((analysis.get('territory') or {}).get('inside_moscow'))
        if region == 'auto':
            region = 'msk' if inside else 'mo' if all(n.startswith('50:') for n in numbers) else ''
        if not region or (region == 'msk' and not inside):
            raise ValueError('Нормативный ТЭП доступен для Москвы и Московской области. '
                             'Проверьте территорию или задайте ТЭП вручную.')
    patch = {key: 0 for key in form.territory_input_keys(core)}
    patch.update({key: False for key in FLAGS})
    tep = copy.deepcopy(core.TEP_DEFAULT)
    for row in tep.values():
        for key in row:
            if key != 'label': row[key] = 0
    if region == 'mo':
        data = remote('/mo/calculate', {'query': ', '.join(numbers), 'limit': 30})
        territory = data.get('territory') or {}
        if set(territory.get('cadastral_numbers') or []) != set(numbers):
            raise ValueError('В расчёт области попали не все выбранные участки. Данные не применены.')
        patch.update(data.get('inputs') or {})
        patch['site_area_ha'] = territory.get('site_area_ha', 0)
        patch['site_density_sqm_per_ha'] = data.get('density_sqm_per_ha', 0)
        patch['_mo_calc'] = {key: data.get(key) for key in ('query', 'territory', 'density_sqm_per_ha', 'vri', 'social', 'balance', 'warnings')}
        for key, row in (data.get('tep') or {}).items():
            tep[key] = {**tep.get(key, {}), **row}
        source = 'ЕГРН / НСПД · нормативы РНГП Московской области'
    else:
        data = remote('/cadastral/tep-server', {'cadastral_numbers': numbers, 'cadastral_analysis': analysis})
        if not data.get('mappings', {}).get('tep'):
            raise ValueError('Сервис не вернул ТЭП. Параметры проекта не изменены.')
        imported = form.inputs_from_glavapu(core, data, {'vri_region': 'msk'})
        keys = set(patch) | set(data.get('mappings', {}).get('inputs') or {})
        keys.update(['_glavapu_import', 'social_mode', 'site_density_sqm_per_ha', 'site_area_ha'])
        patch.update({key: imported['inputs'][key] for key in keys if key in imported['inputs']})
        patch['_cadastral_analysis'] = analysis
        tep = imported['tep']
        territory = analysis.get('territory') or {}
        source = str((data.get('source') or {}).get('format') or 'Расчёт ТЭП DevelopAid')
    patch['vri_region'] = region
    patch['_desktop_site'] = {'query': req.query, 'cadastral_numbers': numbers, 'region': region,
                              'source_label': source, 'received_at': datetime.now(timezone.utc).isoformat()}
    return {'inputs_patch': patch, 'clear_keys': MARKERS, 'tep': tep, 'cadastral_numbers': numbers,
            'source_label': source, 'region': region, 'warnings': data.get('warnings') or [],
            'site_area_ha': patch.get('site_area_ha'), 'address': territory.get('address') or req.query}

"""Фото со стройки из чата площадки — для сводки руководству.

Бот уже читает привязанный чат стройки (ежедневные отчёты); фото оттуда он
тоже забирает: на Render качает средний размер снимка и отдаёт ядру
подписанным маршрутом — ядро до api.telegram.org не достаёт. Здесь — только
хранение на ядре и выбор.

В сводку автоматически выбирается до пяти снимков каждого дня. Выбор устойчив
при неизменном наборе снимков и одинаков для недели и месяца. Ручной выбор
имеет приоритет: первый ручной переход фиксирует набор дня, последующие
загрузки его не подменяют. Отсутствие отметки не равно явному исключению.
Старые ручные наборы сохраняются, в том числе более пяти снимков.

В отчёт встраиваются уменьшенные копии, исходные байты не меняются. Производный
кэш ограничен и разделяется воркерами под замком; чтение сводки не пишет выбор.

Журнал тот же, что у записей «Общая информация» (`developaid_project_notes`):
дописывание под замком файла, воркеров два. Снимок — файлом рядом, имя —
постоянный идентификатор Telegram, поэтому повторно присланный вебхук не
плодит копий.
"""

from __future__ import annotations

import base64
import datetime
import fcntl
import hashlib
import io
import json
import os
import re
import tempfile
import warnings
from pathlib import Path
from typing import Any

import developaid_monitor as monitor
from developaid_project_notes import _append, _now, _read

MAX_BYTES = 5 * 1024 * 1024
_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_MAX_CAPTION = 1000
AUTO_PER_DAY = 5
SELECTION_POLICY = 'site-photo-daily-v2'
PREVIEW_VERSION = 'site-photo-preview-v1'
PREVIEW_MAX_EDGE = 1280
PREVIEW_MAX_BYTES = 96 * 1024
PREVIEW_MAX_PIXELS = 40_000_000
PREVIEW_CACHE_BYTES = 32 * 1024 * 1024
PREVIEW_CACHE_FILES = 512
_CACHE_NAME = re.compile(r'^[a-f0-9]{64}\.jpg$')


def _day(value):
    try:
        return value if isinstance(value, str) and datetime.date.fromisoformat(value).isoformat() == value else None
    except ValueError:
        return None


def _atomic_bytes(path, data):
    fd, name = tempfile.mkstemp(prefix='.preview-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _folder(project: str) -> Path:
    folder = monitor._project_dir(project) / "photos"
    (folder / "files").mkdir(parents=True, exist_ok=True)
    return folder


def _file(project: str, photo_id: str) -> Path:
    if not _ID.fullmatch(str(photo_id or "")):
        raise ValueError("неверный идентификатор фото")
    folder = _folder(project) / "files"
    return monitor._inside(folder, f"{photo_id}.jpg")


def _is_image(data: bytes) -> bool:
    return data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n"


def store(project: str, data: bytes, photo_id: str, day: str, author: str = "",
          caption: str = "", at: str = "", message_id: int = 0) -> dict[str, Any]:
    """Положить снимок из чата. Повтор того же снимка — не новая запись."""
    if not data or len(data) > MAX_BYTES:
        raise ValueError(f"снимок пустой или больше {MAX_BYTES // (1024 * 1024)} МБ")
    if not _is_image(data):
        raise ValueError("это не снимок JPEG или PNG")
    if not _day(day):
        raise ValueError("дата снимка нужна в виде ГГГГ-ММ-ДД")
    path = _file(project, photo_id)
    log = _folder(project) / "log.jsonl"
    entry = {"kind": "photo", "id": photo_id, "day": day, "at": at or _now(),
             "author": str(author or "").strip()[:200],
             "caption": str(caption or "").strip()[:_MAX_CAPTION],
             "message_id": int(message_id or 0), "size": len(data)}
    duplicate = {}

    def check(rows: list[dict[str, Any]]) -> None:
        for row in rows:
            if isinstance(row,dict) and row.get("kind") == "photo" and row.get("id") == photo_id:
                duplicate.update(row)
                raise FileExistsError(photo_id)
        # The journal lock protects duplicate IDs across workers too. A repeated
        # webhook must not overwrite the first original before discovering it.
        _atomic_bytes(path, data)

    # The complete original is placed atomically before its journal row.
    try:
        _append(log, entry, check)
    except FileExistsError:
        return {**duplicate, "duplicate": True}
    return entry


def select(project: str, photo_id: str, chosen: bool, by: str) -> dict[str, Any]:
    """Отметить фото для сводки или снять отметку. Каждая отметка — строка журнала."""
    if type(chosen) is not bool:
        raise ValueError('выбор фото должен быть явным: да или нет')
    if not _ID.fullmatch(str(photo_id or '')):
        raise ValueError('неверный идентификатор фото')
    log = _folder(project) / "log.jsonl"
    entry = {"kind": "select", "id": photo_id, "chosen": chosen,
             "by": str(by or "").strip()[:200], "at": _now()}

    def check(rows: list[dict[str, Any]]) -> None:
        current = _effective(project, rows)
        item = next((row for row in current if row['id'] == photo_id), None)
        if item is None:
            raise KeyError(f"фото {photo_id} не найдено")
        if not item['day_manual']:
            # Snapshot and edit are one journal entry under the same existing
            # lock. Report reads never persist an automatic/default selection.
            entry.update(selection_policy=SELECTION_POLICY, selection_day=item['day'],
                         selection_base_ids=[row['id'] for row in current
                             if row['day'] == item['day'] and row['chosen']])

    return _append(log, entry, check)


def _automatic(project, day, ids):
    scope = monitor._project_dir(project).name
    def rank(photo_id):
        value = json.dumps([SELECTION_POLICY, scope, day, photo_id], ensure_ascii=False)
        return hashlib.sha256(value.encode()).hexdigest(), photo_id
    return set(sorted(ids, key=rank)[:AUTO_PER_DAY])


def _effective(project, rows):
    """Pure journal replay; no photo reads, random state or selection writes."""
    items, days, manual = {}, {}, {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        photo_id = row.get('id')
        if not isinstance(photo_id,str) or not _ID.fullmatch(photo_id):
            continue
        if row.get('kind') == 'photo' and photo_id not in items and _day(row.get('day')):
            items[photo_id] = {**row, 'at':str(row.get('at') or ''), 'manual_selection': None, 'chosen_by': ''}
            days.setdefault(row['day'], []).append(photo_id)
        elif row.get('kind') == 'select' and photo_id in items and type(row.get('chosen')) is bool:
            day = items[photo_id]['day']
            if day not in manual:
                baseline = row.get('selection_base_ids')
                valid = (row.get('selection_policy') == SELECTION_POLICY and row.get('selection_day') == day
                    and isinstance(baseline, list) and len(baseline) <= AUTO_PER_DAY
                    and all(isinstance(value, str) for value in baseline)
                    and len(set(baseline)) == len(baseline)
                    and all(value in items and items[value]['day'] == day for value in baseline)
                    and set(baseline) == _automatic(project,day,days[day]))
                # Legacy selections had no automatic cohort: retain exactly the
                # explicit manual inclusions/exclusions from that day.
                manual[day] = set(baseline) if valid else set()
            if row['chosen']:
                manual[day].add(photo_id)
            else:
                manual[day].discard(photo_id)
            items[photo_id].update(manual_selection=row['chosen'], chosen_by=row.get('by') or '')
    for day, ids in days.items():
        chosen = manual[day] if day in manual else _automatic(project, day, ids)
        for photo_id in ids:
            items[photo_id].update(chosen=photo_id in chosen, day_manual=day in manual,
                selection_mode='manual' if day in manual else 'automatic')
    return sorted(items.values(), key=lambda item:(item['day'], item.get('at') or '', item['id']))


def photos(project: str, start: Any = None, end: Any = None) -> list[dict[str, Any]]:
    """Снимки за период (по дню в чате) с последней отметкой выбора."""
    folder = monitor._project_dir(project) / "photos"
    rows = _read(folder / "log.jsonl")
    first = monitor._iso(start) if start else ""
    last = monitor._iso(end) if end else "9999-12-31"
    return [item for item in _effective(project, rows) if first <= item['day'] <= last]


def read(project: str, photo_id: str) -> bytes:
    path = _file(project, photo_id)
    if not path.exists():
        raise KeyError(f"файла фото {photo_id} нет")
    if path.is_symlink():
        raise PreviewProblem('source_unsafe','Исходный снимок недоступен для безопасного чтения.')
    with path.open('rb') as handle:
        raw = handle.read(MAX_BYTES+1)
    if not raw or len(raw) > MAX_BYTES:
        raise PreviewProblem('source_size','Исходный снимок пустой или превышает допустимый размер.')
    return raw


class PreviewProblem(ValueError):
    def __init__(self,code,detail):
        super().__init__(detail)
        self.code = code


def _compress_pixels(data):
    from PIL import Image, ImageOps
    with Image.open(io.BytesIO(data)) as original:
        if original.format not in {'JPEG', 'PNG'} or original.width*original.height > PREVIEW_MAX_PIXELS:
            raise PreviewProblem('image_bounds','Размер или формат снимка не поддерживается для уменьшенной копии.')
        if original.format == 'JPEG':
            original.draft('RGB',(PREVIEW_MAX_EDGE,PREVIEW_MAX_EDGE))
        image = ImageOps.exif_transpose(original)
        if image.mode in ('RGBA', 'LA') or 'transparency' in image.info:
            rgba = image.convert('RGBA')
            white = Image.new('RGB', image.size, 'white')
            white.paste(rgba, mask=rgba.getchannel('A'))
            image = white
        else:
            image = image.convert('RGB')
        image.thumbnail((PREVIEW_MAX_EDGE,PREVIEW_MAX_EDGE), Image.Resampling.LANCZOS)
        while True:
            for quality in (88,80,72,64,56,48,40):
                buffer = io.BytesIO()
                image.save(buffer,'JPEG',quality=quality,optimize=True,progressive=True)
                raw = buffer.getvalue()
                if len(raw) <= PREVIEW_MAX_BYTES:
                    return raw, image.size
            edge = max(image.size)
            if edge <= 320:
                raise PreviewProblem('preview_size','Не удалось подготовить уменьшенную копию в допустимом размере.')
            edge = max(320,int(edge*.8))
            image.thumbnail((edge,edge),Image.Resampling.LANCZOS)


def _compress(data):
    from PIL import Image
    with warnings.catch_warnings():
        warnings.simplefilter('error',Image.DecompressionBombWarning)
        try:
            return _compress_pixels(data)
        except (OSError,Image.DecompressionBombError,Image.DecompressionBombWarning):
            raise PreviewProblem('image_unreadable','Не удалось прочитать исходный снимок как JPEG или PNG. Оригинал сохранён.') from None


def _cached_preview_valid(data):
    from PIL import Image
    if not data or len(data) > PREVIEW_MAX_BYTES:
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format != 'JPEG' or max(image.size) > PREVIEW_MAX_EDGE:
                    return None
                size = image.size
                image.load()
        return size
    except (OSError,ValueError,Image.DecompressionBombError,Image.DecompressionBombWarning):
        return None


def _prune_previews(folder, reserve=0):
    files = []
    for path in folder.iterdir():
        if path.name.startswith('.preview-') and path.suffix == '.tmp':
            path.unlink(missing_ok=True)
        elif _CACHE_NAME.fullmatch(path.name):
            stat = path.lstat()
            files.append((stat.st_mtime,path,stat.st_size))
    total = sum(size for _,_,size in files)
    count = len(files)
    for _,path,size in sorted(files):
        if total+reserve <= PREVIEW_CACHE_BYTES and count+(reserve>0) <= PREVIEW_CACHE_FILES:
            break
        path.unlink(missing_ok=True)
        total -= size
        count -= 1


def preview(project, photo_id):
    """Bounded derived JPEG; source bytes, journal and selection stay intact."""
    data = read(project,photo_id)
    source_sha = hashlib.sha256(data).hexdigest()
    key = hashlib.sha256(json.dumps([PREVIEW_VERSION,source_sha,PREVIEW_MAX_EDGE,PREVIEW_MAX_BYTES]).encode()).hexdigest()
    folder = monitor._project_dir(project)/'photos'/'.report-previews'
    compressed, size = None, None
    cached = False
    try:
        if folder.is_symlink():
            raise OSError('unsafe derived cache')
        folder.mkdir(mode=0o700,parents=True,exist_ok=True)
        lock_path = folder/'.lock'
        fd = os.open(lock_path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'a+b') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            try:
                _prune_previews(folder)
                path = folder/(key+'.jpg')
                if path.is_file() and not path.is_symlink():
                    with path.open('rb') as handle:
                        candidate = handle.read(PREVIEW_MAX_BYTES+1)
                    size = _cached_preview_valid(candidate)
                    if size:
                        compressed, cached = candidate, True
                if compressed is None:
                    compressed,size = _compress(data)
                    if path.exists() or path.is_symlink():
                        path.unlink()
                    _prune_previews(folder,len(compressed))
                    _atomic_bytes(path,compressed)
            finally:
                fcntl.flock(lock,fcntl.LOCK_UN)
    except OSError:
        # Cache failure must not discard a readable original. This is still a
        # bounded derived copy, never a fallback embedding of the full source.
        compressed,size = _compress(data)
        cached = False
    return {'bytes':compressed,'width':size[0],'height':size[1],
            'source_sha256':source_sha,'sha256':hashlib.sha256(compressed).hexdigest(),
            'preview_version':PREVIEW_VERSION,'cache_hit':cached}


def for_report(project: str, start: datetime.date, end: datetime.date) -> dict[str, Any]:
    """Выбранные фото периода — встраиваются в документ строкой data URI."""
    found = photos(project, start, end)
    chosen = [item for item in found if item["chosen"]]
    items, skipped = [], []
    for item in chosen:
        try:
            result = preview(project,item['id'])
        except (KeyError,OSError,ValueError,ImportError) as exc:
            skipped.append({'id':item['id'],'day':item['day'],
                'code':exc.code if isinstance(exc,PreviewProblem) else 'source_missing' if isinstance(exc,(KeyError,FileNotFoundError)) else 'preview_unavailable',
                'reason':str(exc) if isinstance(exc,PreviewProblem) else
                         'Исходный снимок не найден.' if isinstance(exc,(KeyError,FileNotFoundError)) else
                         'Не удалось подготовить уменьшенную копию этого снимка. Остальные фотографии сохранены в сводке.'})
            continue
        items.append({**item, **{key:result[key] for key in ('width','height','source_sha256','sha256','preview_version')},
                      'preview_bytes':len(result['bytes']), 'src':'data:image/jpeg;base64,'
                      +base64.b64encode(result['bytes']).decode('ascii')})
    manual = sum(item['day_manual'] for item in chosen)
    manual_notice = (' Ручной набор: '+str(manual)+' фото. Сохранены все ручные отметки.' if manual else '')
    return {"total": len(found), "selected":len(chosen), "items": items,'skipped':skipped,
            'manual_selected':manual,'automatic_selected':len(chosen)-manual,
            'selection_policy':SELECTION_POLICY,
            'notice':'Автоматически до 5 фото за день. Ручной выбор можно изменить. В сводке уменьшенные копии; оригиналы сохранены.'+manual_notice}

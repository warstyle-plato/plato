"""Bounded, complete HTML messages for the generated teaser card (b/i/code)."""
from __future__ import annotations

import re

_TOKEN = re.compile(r'(<[^>]*>|&(?:#\d+|#x[\da-fA-F]+|[A-Za-z][A-Za-z\d]+);)')
_TAG = re.compile(r'<(/?)(b|i|u|s|code|pre)>')


def _units(value: str) -> int:
    return len(value.encode('utf-16-le')) // 2


def split_intake_html(text: str, limit: int = 3900) -> list[str]:
    """Keep all text, entities and Unicode; close/reopen emphasis at boundaries.

    Count the encoded markup too, conservatively below Telegram's 4096 visible
    characters. Prefer whole lines/words, but a single long line also splits.
    The input is the application's escaped card, never arbitrary remote HTML.
    """
    if limit < 64:
        raise ValueError('Лимит сообщения слишком мал.')
    parts, current, stack = [], [], []
    used, has_text = 0, False

    def closing() -> str:
        return ''.join('</' + tag + '>' for tag in reversed(stack))

    def flush() -> None:
        nonlocal current, used, has_text
        if not has_text:
            raise ValueError('Разметка карточки превышает лимит сообщения.')
        parts.append(''.join(current) + closing())
        current = ['<' + tag + '>' for tag in stack]
        used, has_text = _units(''.join(current)), False

    for token in _TOKEN.split(str(text)):
        if not token:
            continue
        if token.startswith('<'):
            tag = _TAG.fullmatch(token)
            if tag is None:
                raise ValueError('Неизвестная разметка карточки.')
            name = tag[2]
            if tag[1]:
                if not stack or stack[-1] != name:
                    raise ValueError('Незакрытая разметка карточки.')
                current.append(token)
                used += _units(token)
                stack.pop()
            else:
                if used + _units(token) + _units('</' + name + '>' + closing()) > limit:
                    flush()
                current.append(token)
                used += _units(token)
                stack.append(name)
            continue
        if _TOKEN.fullmatch(token):  # An escaped entity is indivisible.
            if used + _units(token) + _units(closing()) > limit:
                flush()
            current.append(token)
            used += _units(token)
            has_text = True
            continue
        while token:
            available = limit - used - _units(closing())
            if _units(token) <= available:
                current.append(token)
                used += _units(token)
                has_text = True
                break
            size, take = 0, 0
            for character in token:
                size += _units(character)
                if size > available:
                    break
                take += 1
            if not take:
                flush()
                continue
            boundary = token.rfind('\n', 0, take)
            if boundary < 0:
                boundary = token.rfind(' ', 0, take)
            if boundary >= 0:
                take = boundary + 1
            current.append(token[:take])
            used += _units(token[:take])
            has_text = True
            token = token[take:]
            flush()
    if stack:
        raise ValueError('Незакрытая разметка карточки.')
    if has_text:
        parts.append(''.join(current))
    return parts

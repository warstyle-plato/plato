"""Что говорит сама карточка krt.mos.ru: застройщик и реновация.

Прежде эти два признака искались в проекте решения и в публикациях. В решении
их нет — измерено на восьми живых документах: «оператор», «застройщик»,
«государственных нужд», «изъятие», «победитель» ноль раз из восьми. Отсюда был
сделан вывод, что официальный источник о них молчит, и он оказался неверным:
молчит РЕШЕНИЕ, а карточка каталога говорит прямо (живой ответ, 31.08.2026).

На шестидесяти прочитанных карточках:

* «Застройщик» — 27 из 30 «В реализации» и назван по имени отдельным блоком:
  АО «Главстрой», КП «КРТ», ГБУ «ГлавАПУ»;
* «реновация» — 12 из 30 «В реализации», прозой в описании площадки; у
  планируемых ни одной, и это правильно: программу называют, когда стройка
  уже идёт;
* оборота «городские нужды» на карточках нет вовсе — 0 из 60. Город называет
  это реновацией, и искать надо её.

Ловушка, ради которой написан отдельный тест: слова «жилой застройки» и
«нежилой застройки» встречаются на ВСЕХ карточках — это названия типовых
приложений («Примерная форма договора о КРТ нежилой застройки»), а не вид этой
площадки. Читать вид КРТ отсюда нельзя: получишь сто процентов совпадений и ни
одного факта.

Источник бесплатный и официальный, поэтому он идёт первым, а публикации —
вторым слоем, для планируемых площадок, где карточка ещё молчит.
"""

from __future__ import annotations

import html as html_module
import re
from typing import Any

# Блок роли на карточке: имя в заголовке, роль подписью под ним.
_ITEM = re.compile(
    r'__extra__item">(?P<body>.*?)__item__caption"><span>(?P<role>[^<]*)</span>',
    re.S)
_TITLE = re.compile(r'__item__title">(?P<name>.*?)</h3>', re.S)
_TAGS = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
# Описание площадки — колонка прозы рядом с ТЭП. Реновация живёт именно там.
_DESCRIPTION = re.compile(
    r'project-detail__description__main__col">(?P<body>.*?)</div>', re.S)
_SENTENCE = re.compile(r"[^.!?]*[.!?]")
# Городской застройщик — казённое предприятие или учреждение. Такую площадку
# город делает сам, и «войти» в неё нельзя: это ответ, а не оттенок.
_CITY_FORMS = ("кп ", "гку", "гбу", "гуп", "казенное предприятие",
               "казённое предприятие", "департамент", "москомархитектур")


def _text(raw: str) -> str:
    return _SPACE.sub(" ", html_module.unescape(_TAGS.sub(" ", raw or ""))).strip()


def _is_city(name: str) -> bool:
    low = " " + name.lower().replace("«", '"').replace("»", '"') + " "
    return any(form in low for form in _CITY_FORMS)


def parse(page: str) -> dict[str, Any]:
    """Разобрать карточку. Чего на ней нет, того не выдумываем."""
    out: dict[str, Any] = {
        "roles": [], "developers": [], "city_operator": False,
        "renovation": False, "renovation_quote": "", "description": "",
    }
    if not page:
        return out
    for item in _ITEM.finditer(page):
        title = _TITLE.search(item.group("body"))
        name = _text(title.group("name")) if title else ""
        role = _text(item.group("role"))
        if not name or not role:
            continue
        out["roles"].append({"name": name, "role": role})
        if "застройщик" in role.lower():
            out["developers"].append(name)
            if _is_city(name):
                out["city_operator"] = True

    # Колонок описания две: в первой ТЭП парами «подпись: <b>число</b>», во
    # второй проза. Различать их по точке нельзя — «Площадь, га: 73.62» тоже с
    # точкой, и у планируемой площадки описанием становился её же ТЭП.
    described = [_text(block.group("body")) for block in _DESCRIPTION.finditer(page)
                 if "</span><b>" not in block.group("body")]
    prose = [text for text in described if len(text) > 120]
    out["description"] = max(prose, key=len) if prose else ""
    for sentence in _SENTENCE.findall(out["description"]):
        if "реноваци" in sentence.lower():
            out["renovation"] = True
            out["renovation_quote"] = sentence.strip()
            break
    return out

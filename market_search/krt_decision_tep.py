"""ТЭП площадки из проекта решения о КРТ: документ отвечает там, где молчит каталог.

Каталог krt.mos.ru показывает площадку с её ТЭП, а площадка, у которой карточки
ещё нет, приезжает к нам одним заголовком решения — без единой цифры. На экране
это выглядело так: «Оценка Платона: 0/100 · ТЭП не указан», и владелец прочитал
это ровно так, как оно написано: «на mos.ru уже появилось pdf решения, а мы его
не видим и пишем в блоке КРТ что 0» (04.09.2026).

Числа в решении есть, и это те же числа: на 26 площадках, у которых нашлись и
карточка, и решение, «предельная (максимальная) суммарная поэтажная площадь …
жилого назначения» совпала с колонкой «Жилое назначение» каталога во всех
случаях, где она названа, а сумма всех максимальных СПП — с «Общим объёмом
застройки» там, где сходится и площадь территории. Расходится она ровно там,
где расходится площадь в гектарах, то есть где сопоставление взяло не ту
площадку или документ другой редакции: **гектары — самопроверка пары**, и
называть её обязан вызывающий, а не прятать в округление.

Три вещи, каждая из которых стоила отдельного захода по живым документам
(24 решения, снятых с mos.ru 04.09.2026).

**Назначение стоит внутри самой формулы, и без него величины складывать
нельзя.** Строка бывает трёх видов: «СПП объектов капитального строительства
жилого назначения», «…нежилого назначения» (а также «делового и иного»,
«общественно-делового и производственного») и «…» без назначения вовсе. Первая
версия складывала их подряд и на Тропаревской давала 145 890 м² вместо 48 000 —
жилое, нежилое и общее в одной сумме.

**Ноль — это ответ.** У КРТ под улично-дорожную сеть и благоустройство решение
прямо пишет «предельная (максимальная) суммарная поэтажная площадь … – 0 кв. м»
(ул. 6-я Радиальная, Ленинградское ш., влд. 96А). Отфильтровать ноль как «не
нашли» значит показать «не знаем» там, где город сказал «строить нельзя».

**Слово в PDF рвётся пробелом.** «капиталь ного», «пл ощадь», «подлеж ат
территори и», «по длежит» — извлечённый текст несёт переносы как пробелы, и
поиск по целому слову не срабатывает на каждом шестом документе. Поэтому
образцы собираются посимвольно (`_loose`), а не пишутся строкой.

Ничего не считает: складывает названные документом части и отдаёт их вместе с
цитатой. Пересчёт метров в другие метры — работа движка, а не читателя.
"""

from __future__ import annotations

import re
from typing import Any

_SPACE = re.compile(r"\s+")
# Число берут целиком: «26,856 млн» уже читалось как 856 млн, «3 306 021 ₽/м²» —
# как 306 021. Левый охранник не даёт начать сопоставление с середины числа.
_NUMBER = r"(?<![\d.,])(\d[\d   ]*(?:[.,]\d+)?)"


def _loose(phrase: str) -> str:
    """Образец, переживающий перенос строки внутри слова."""
    return r"\s*".join(re.escape(char) for char in phrase.replace(" ", ""))


_MAXIMUM = re.compile(r"(?iu)" + _loose("предельная") + r"\s*\(\s*"
                      + _loose("максимальная") + r"\s*\)\s*")
_SPP = re.compile(r"(?iu)" + _loose("суммарнаяпоэтажнаяплощадь"))
_FLATS = re.compile(r"(?iu)" + _loose("площадьквартир"))
_NONRES_GROUND = re.compile(r"(?iu)" + _loose("нежилаяназемнаяплощадь"))
_VALUE = re.compile(r"(?iu)[–—-]\s*" + _NUMBER + r"\s*" + _loose("кв"))
_HOUSING_PURPOSE = re.compile(r"(?iu)" + _loose("жилогоназначения"))
# Нежилое назначение город пишет по-разному: «нежилого», «делового и иного»,
# «общественно-делового и производственного». Общее у них одно — это не жильё.
_NONRES_PURPOSE = re.compile("(?iu)" + "|".join(_loose(word) for word in (
    "нежилогоназначения", "деловогоиногоназначения", "деловог",
    "производственногоназначения", "иногоназначения",
)))
_AREA_HEAD = re.compile(r"(?iu)" + _loose("комплексному") + r"\s*"
                        + _loose("развитию") + r"\s*" + _loose("подлеж"))
_AREA = re.compile(r"(?iu)" + _loose("площадью") + r"\s*" + _NUMBER + r"\s*"
                   + _loose("га") + r"\b")
_INCLUDING = re.compile(r"(?iu)" + _loose("втомчисле"))


def _number(raw: str | None) -> float | None:
    if raw is None:
        return None
    flat = re.sub(r"[\s  ]", "", str(raw)).replace(",", ".")
    try:
        return float(flat)
    except ValueError:
        return None


def _clause(text: str, start: int, limit: int = 420) -> str:
    """Хвост формулы до конца предложения. «кв. м.» точкой не считается."""
    tail = text[start:start + limit]
    stop = re.search(r"(?<!кв)\.\s+[А-ЯЁA-Z]|;\s", tail)
    return tail[:stop.start()] if stop else tail


def _purpose(window: str) -> str:
    """Жильё, нежилое или назначение не названо — по словам самого документа."""
    if _HOUSING_PURPOSE.search(window):
        return "housing"
    if _NONRES_PURPOSE.search(window):
        return "nonres"
    return "unnamed"


def parse(text: str) -> dict[str, Any]:
    """Разобрать ТЭП решения. Не назвал документ величину — `None`, а не ноль."""
    flat = _SPACE.sub(" ", str(text or ""))
    parts: dict[str, list[float]] = {
        "spp_housing": [], "spp_nonres": [], "spp_unnamed": [],
        "flats": [], "nonres_ground": [],
        # «В том числе» — ЧАСТЬ уже посчитанного целого: в общий объём она не
        # идёт, а назначение называет. На Большом Тишинском вся СПП 9 800 м²
        # объявлена так («в том числе объектов жилого назначения – 9 800 кв.м»),
        # и без этого разбора площадка выглядела нежилой.
        "inner_housing": [], "inner_nonres": [],
    }
    quotes: dict[str, str] = {}
    for head in _MAXIMUM.finditer(flat):
        rest = flat[head.end():head.end() + 460]
        for pattern, kind in ((_SPP, "spp"), (_FLATS, "flats"),
                              (_NONRES_GROUND, "nonres_ground")):
            hit = pattern.match(rest)
            if not hit:
                continue
            clause = _clause(rest, hit.end())
            found = _VALUE.search(clause)
            if found is None:
                break
            value = _number(found.group(1))
            if value is None:
                break
            if kind == "spp":
                key = "spp_" + _purpose(clause[:found.start()])
                # Части «в том числе»: своё назначение и своё число, но целое
                # они не увеличивают — их сумма и есть уже посчитанное целое.
                for inner in _INCLUDING.finditer(clause, found.end()):
                    tail = _clause(clause, inner.end(), 200)
                    side = _VALUE.search(tail)
                    purpose = _purpose(tail[:side.start()] if side else tail)
                    if side is None or purpose == "unnamed":
                        continue
                    inner_value = _number(side.group(1))
                    if inner_value is not None:
                        parts["inner_" + purpose].append(inner_value)
            else:
                key = kind
            parts[key].append(value)
            quotes.setdefault(
                key, _SPACE.sub(" ", flat[head.start():head.end()] + rest[:hit.end()] + clause)[:320])
            break

    def total(*keys: str) -> float | None:
        picked = [value for key in keys for value in parts[key]]
        return sum(picked) if picked else None

    area_ha = None
    head = _AREA_HEAD.search(flat)
    if head:
        found = _AREA.search(flat, head.end(), head.end() + 500)
        if found:
            area_ha = _number(found.group(1))
    return {
        "area_ha": area_ha,
        # Общий объём — сумма ВСЕХ максимальных СПП документа: город называет
        # их по зонам и по назначениям, и целое здесь складывается из частей.
        # Части «в том числе» в эту сумму не входят: они уже в ней.
        "total_gfa_sqm": total("spp_housing", "spp_nonres", "spp_unnamed"),
        "housing_gfa_sqm": total("spp_housing", "inner_housing"),
        "nonresidential_gfa_sqm": total("spp_nonres", "inner_nonres"),
        # Площадь квартир — НЕ жилое назначение: на Лихачевском это 30 304 м²
        # против 50 400 м² жилой СПП. Своё поле и своё имя.
        "flats_sqm": total("flats"),
        "nonresidential_ground_sqm": total("nonres_ground"),
        "parts": {key: len(value) for key, value in parts.items()},
        "quotes": quotes,
        "read": any(parts[key] for key in parts) or area_ha is not None,
    }


def catalogue_mismatch(tep: dict[str, Any], project: dict[str, Any]) -> list[str]:
    """Чем разбор решения не сошёлся с карточкой каталога. Пусто — сошлось.

    Гектары здесь главная улика: расходится площадь территории — значит пара
    «решение ↔ карточка» собрана неверно, и метрам такой пары верить нельзя.
    Сверка не чинит расхождение, она не даёт выдать одно за другое.
    """
    out: list[str] = []
    for key, name, tolerance in (
        ("area_ha", "площадь территории", 0.02),
        ("total_gfa_sqm", "общий объём", 0.02),
        ("housing_gfa_sqm", "жильё", 0.02),
    ):
        ours, theirs = tep.get(key), project.get(key)
        if ours is None or theirs is None:
            continue
        base = max(abs(float(theirs)), 1.0)
        if abs(float(ours) - float(theirs)) / base > tolerance:
            out.append(f"{name}: в решении {ours:g}, в каталоге {float(theirs):g}")
    return out

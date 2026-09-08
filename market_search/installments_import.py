"""Импорт свода рассрочек TrendAgent в справочник рынка.

Что это за источник и почему он нужен. «Пульс» и bnMAP отвечают на «почём» и
«сколько продали»; чем сосед торгует ПОМИМО цены, не отвечает ни один. А
торгует он условиями: первым взносом, сроком рассрочки, скидкой к прайсу за
короткий срок или удорожанием за длинный, ключами до полной оплаты. Наше
сравнение цен — витрина против витрины (правило записано), и рассрочка ровно
эту витрину и двигает: сосед с тем же прайсом и нулевым ПВ продаёт дешевле, чем
выглядит.

Что измерено в самом файле до разбора (свод от 08.09.2026):

* Лист «Рассрочки. Москва» — 1116 строк-программ, 195 застройщиков, 642 имени
  объектов (имена ЖК лежат в одной ячейке через перевод строки).
* «Есть рассрочка?»: Да 1024, Нет 92. «Цена»: базовая 464, со скидкой 279,
  с удорожанием 135 — то есть у трети программ рассрочка стоит денег, а у
  четверти наоборот дешевле прайса.
* **Колонка «Месяц обновления» источником свежести быть не может**: она
  заполнена в 314 строках из 1116, и все её даты — весна 2025 года. Свежесть
  доказывают сроки самих программ: «до 20.12.2026», «до 30.09.2027» — они
  впереди, значит свод живой. Дата снимка берётся у файла, а не у колонки, и
  говорится вслух.
* Совпадение с нашим справочником — 201 имя из 642, накрыто 172 проекта из 685.
  Это и есть охват: у остальных соседей условий нет, и это «не знаем», а не
  «рассрочки не дают».

Правило тождества имени здесь не своё: `canonical_key` и `same_project` —
единственное определение «это один проект» на весь модуль. Своё TrendAgent
добавляет только хвосты, которыми он режет объект на строки: «корп. 2»,
«1 оч», «(паркинг)». Они снимаются до сравнения — это чистка ввода, а не второе
правило.

Запуск:

    python3 -m market_search.installments_import TrendAgent.xlsx \\
        --out market_search/registry_data
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
from pathlib import Path
from typing import Any, Iterable

from .normalize import canonical_key
from .pulse_report_import import rows as sheet_rows

SHEET = "Рассрочки. Москва"

# Подписи колонок берутся из шапки листа, а не по номеру: колонку в свод
# добавят, и разбор молча уедет на соседнюю.
COL_BUILDER = "Застройщик"
COL_OBJECTS = "На какие объекты действует"
COL_HAS = "Есть рассрочка?"
COL_PRICE = "Цена"
COL_DOWN = "ПВ"
COL_TERM = "Срок рассрочки"
COL_KEYS = "Возможно ли получение ключей до полной оплаты рассрочки"
COL_MORTGAGE = "Возможен переход на ипотеку"
COL_KIND = "Тип недвижимости"

# Хвосты, которыми TrendAgent режет объект на строки. «Павелецкая от Гранель
# корп. 2» и «Кантемировский 1 оч» — тот же проект нашего справочника; без
# снятия хвоста они не находятся вовсе (198 имён против 155).
_TAIL_RE = re.compile(
    r"\s*[(,]?\s*(?:корп\w*\.?\s*[\d,\s]+|\d+\s*оч(?:\.|ередь)?|паркинг\w*|кладов\w*|"
    r"секц\w*|апартаменты|квартиры)\s*\)?\s*$",
    flags=re.I,
)

_NO = ("нет рассрочки", "нет", "под запрос", "-", "—")

PRICE_BASE = "базовая"
PRICE_DISCOUNT = "скидка"
PRICE_MARKUP = "удорожание"


def clean_object_name(value: str) -> str:
    """Имя объекта без хвоста корпуса и очереди."""
    name = str(value or "").strip(" ,.-\n\t")
    previous = None
    while previous != name:
        previous = name
        name = _TAIL_RE.sub("", name).strip(" ,.-")
    return name


# Уточнение объекта, перенесённое на свою строку: «(2 корпус)», «(этаж № -1)»,
# «(кроме паркинга)». Именем оно не является — это продолжение предыдущего, и
# то же правило уже записано для голого номера в адресах КРТ. Без него в свод
# приезжали объекты «(3» и «(кроме этажа № -1)».
_QUALIFIER_RE = re.compile(
    r"^[(\s]*(?:кроме\s|\d|корп|очеред|секц|этаж|паркинг|кладов|стилобат|башн|дом\b|бц\b)",
    flags=re.I,
)


def object_names(value: Any) -> list[str]:
    """Имена ЖК из одной ячейки: TrendAgent пишет их через перевод строки."""
    out: list[str] = []
    for part in re.split(r"[\n;]+", str(value or "")):
        part = part.strip(" ,.-\t")
        if not part:
            continue
        if _QUALIFIER_RE.match(part) and out:
            continue
        name = clean_object_name(part)
        if name and name.casefold() not in _NO:
            out.append(name)
    return out


def yes_no(value: Any) -> bool | None:
    """«Да»/«Нет» третьим ответом: «под запрос» и «индивидуально» — не «нет»."""
    text = str(value or "").strip().casefold()
    if not text:
        return None
    if text.startswith("да"):
        return True
    if text in {"нет", "нельзя"}:
        return False
    return None


def down_payment_pct(value: Any) -> float | None:
    """Первый взнос долей проекта.

    В свод он приходит долей (`0.3`), процентом («20.1%») и вилкой («от 20%»);
    у вилки берётся нижняя граница — это тот взнос, с которым в проект можно
    войти. Рублёвая сумма («1 600 000 р.») долей не является и не считается:
    доля от неизвестной цены выглядела бы измеренной.
    """
    text = str(value or "").strip().replace(",", ".")
    if not text or text.casefold() in _NO:
        return None
    if "р." in text.casefold() or "руб" in text.casefold() or "млн" in text.casefold():
        return None
    found = re.search(r"\d+(?:\.\d+)?", text)
    if not found:
        return None
    number = float(found.group(0))
    if "%" in text or number > 1:
        return round(number, 1) if 0 < number <= 100 else None
    return round(number * 100, 1)


def term_months(value: Any, *, today: datetime.date | None = None) -> int | None:
    """Срок рассрочки в месяцах.

    Три формы пишут одно и то же: «1 год», «18 месяцев» и «до 30.09.2027». Третья
    считается от даты снимка — иначе срок до даты вообще не число. Формы «до
    ввода в эксплуатацию» и «за месяц до РВ» сроком не становятся: ввод у каждого
    проекта свой, и подставить его нам нечем.
    """
    text = str(value or "").strip().replace(",", ".").casefold()
    if not text or text in _NO:
        return None
    # «за 1 месяц до РВ» — это срок, привязанный к вводу, а не рассрочка на
    # месяц. Число здесь принадлежит другому обороту, и взятое как срок оно
    # выглядит измеренным ровно так же, как настоящий.
    if text.startswith("за ") or "до рв" in text or "до ввода" in text:
        return None
    date = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text)
    if date:
        base = today or datetime.date.today()
        target = datetime.date(int(date.group(3)), int(date.group(2)), int(date.group(1)))
        months = (target.year - base.year) * 12 + target.month - base.month
        return months if months > 0 else None
    found = re.search(r"(\d+(?:\.\d+)?)\s*(год|года|лет|мес)", text)
    if not found:
        return None
    number = float(found.group(1))
    months = number * 12 if found.group(2) != "мес" else number
    return int(round(months)) if months > 0 else None


def price_term(value: Any) -> str | None:
    """Что рассрочка делает с прайсом: ничего, скидку или удорожание."""
    text = str(value or "").strip().casefold()
    if not text or text in _NO:
        return None
    if "удорожан" in text:
        return PRICE_MARKUP
    if "скидк" in text:
        return PRICE_DISCOUNT
    if "цена" in text:
        return PRICE_BASE
    return None


def read_programs(path: Path, *, today: datetime.date | None = None) -> list[dict[str, Any]]:
    """Строки листа рассрочек как программы. Шапка читается, а не нумеруется."""
    letters: dict[str, str] = {}
    out: list[dict[str, Any]] = []
    for row in sheet_rows(path, SHEET):
        if not letters:
            # Шапку ищем по подписям, а не по номеру строки: над ней стоит
            # пояснение и пустая строка, а пустых строк поток не отдаёт вовсе —
            # счёт «третья сверху» промахивался на две.
            found = {str(text).strip(): letter for letter, text in row.items()}
            if COL_OBJECTS in found and COL_HAS in found:
                missing = [
                    name
                    for name in (COL_OBJECTS, COL_HAS, COL_DOWN, COL_TERM, COL_PRICE)
                    if name not in found
                ]
                if missing:
                    raise KeyError("в листе рассрочек нет колонок: " + ", ".join(missing))
                letters = found
            continue

        def value(name: str) -> Any:
            letter = letters.get(name)
            return row.get(letter) if letter else None

        names = object_names(value(COL_OBJECTS))
        if not names:
            continue
        out.append(
            {
                "names": names,
                "builder": str(value(COL_BUILDER) or "").strip(),
                "has_installment": yes_no(value(COL_HAS)),
                "down_payment_pct": down_payment_pct(value(COL_DOWN)),
                "term_months": term_months(value(COL_TERM), today=today),
                "price_term": price_term(value(COL_PRICE)),
                "keys_before_payment": yes_no(value(COL_KEYS)),
                "to_mortgage": yes_no(value(COL_MORTGAGE)),
                "property_kind": str(value(COL_KIND) or "").strip(),
            }
        )
    if not letters:
        raise KeyError(f"в листе «{SHEET}» не нашлась шапка с колонкой «{COL_OBJECTS}»")
    return out


def _fold_programs(programs: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Свод программ одного проекта.

    Показывается САМАЯ МЯГКАЯ программа — наименьший взнос и наибольший срок,
    — потому что покупатель выбирает её, а число программ стоит рядом: одна
    мягкая программа среди пяти жёстких и пять мягких выглядят иначе.
    """
    items = list(programs)
    offered = [p for p in items if p.get("has_installment")]
    downs = [p["down_payment_pct"] for p in offered if p.get("down_payment_pct") is not None]
    terms = [p["term_months"] for p in offered if p.get("term_months") is not None]
    price_terms = [p["price_term"] for p in offered if p.get("price_term")]
    out: dict[str, Any] = {
        "programs": len(items),
        "offered": len(offered),
        "has_installment": bool(offered) if items else None,
    }
    if downs:
        out["down_payment_pct"] = min(downs)
    if terms:
        out["term_months"] = max(terms)
    if price_terms:
        out["price_terms"] = {
            term: price_terms.count(term) for term in sorted(set(price_terms))
        }
    if any(p.get("keys_before_payment") for p in offered):
        out["keys_before_payment"] = True
    elif offered and all(p.get("keys_before_payment") is False for p in offered):
        out["keys_before_payment"] = False
    if any(p.get("to_mortgage") for p in offered):
        out["to_mortgage"] = True
    return out


def build(
    path: Path,
    projects: dict[str, dict[str, Any]],
    *,
    today: datetime.date | None = None,
    saved_at: str | None = None,
) -> dict[str, Any]:
    """Свод рассрочек по нашим проектам плюс честный охват.

    `projects` — наш справочник: идентификатор → карточка с именем. Совпадение
    ищется каноническим ключом модуля; несовпавшее имя не выбрасывается, а
    остаётся в файле списком: молча потерянный объект читается как объект без
    рассрочки.
    """
    programs = read_programs(path, today=today)
    index: dict[str, str] = {}
    for identifier, card in projects.items():
        key = canonical_key(str(card.get("name") or ""))
        if key:
            index.setdefault(key, str(identifier))

    matched: dict[str, list[dict[str, Any]]] = {}
    seen_names: set[str] = set()
    hit_names: set[str] = set()
    for program in programs:
        for name in program["names"]:
            seen_names.add(name)
            identifier = index.get(canonical_key(name))
            if identifier is None:
                continue
            hit_names.add(name)
            matched.setdefault(identifier, []).append(program)

    out_projects = {
        identifier: {
            "name": str(projects[identifier].get("name") or ""),
            **_fold_programs(items),
        }
        for identifier, items in sorted(matched.items())
    }
    return {
        "source": "TrendAgent, свод рассрочек по Москве",
        "sheet": SHEET,
        "saved_at": saved_at or datetime.date.today().isoformat(),
        "programs": len(programs),
        "objects": len(seen_names),
        "objects_matched": len(hit_names),
        "registry_projects": len(projects),
        "projects": out_projects,
        "unmatched": sorted(seen_names - hit_names),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("book", type=Path)
    parser.add_argument("--out", type=Path, default=Path("market_search/registry_data"))
    parser.add_argument("--cards", type=Path, default=None)
    parser.add_argument("--month", default=None)
    parser.add_argument("--saved-at", default=None)
    args = parser.parse_args(argv)

    folder = args.out
    cards_path = args.cards
    if cards_path is None:
        found = sorted(folder.glob("moscow-cards-*.json"))
        if not found:
            raise SystemExit("не найден справочник карточек moscow-cards-*.json")
        cards_path = found[-1]
    payload = json.loads(cards_path.read_text(encoding="utf-8"))
    projects = payload.get("cards") or {}

    saved = args.saved_at or datetime.date.fromtimestamp(args.book.stat().st_mtime).isoformat()
    digest = build(args.book, projects, saved_at=saved)
    month = args.month or saved[:7]
    target = folder / f"moscow-installments-{month}.json"
    target.write_text(
        json.dumps(digest, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"{target}: программ {digest['programs']}, объектов {digest['objects']}, "
        f"совпало {digest['objects_matched']}, наших проектов "
        f"{len(digest['projects'])} из {digest['registry_projects']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Имя продукта выручки — имя, а не ключ.

На экране владельца в структуре выручки стоял «object_parking» — рядом с
«Квартиры» и «Кладовые» (10.09.2026). Продукт этот появился позже строк ТЭП,
своей строки не имеет, а `productName` читала только `TEP_DEFAULT`. Ровно то
же было в расходах: «resettlement» и «demolition» латиницей среди русских
названий, и правило оттуда — **имя без единой русской буквы это не имя, а
ключ**.

Проверка гоняет НАСТОЯЩИЙ расчёт и берёт список продуктов из его отчёта: тот,
что заведут завтра, попадёт в проверку тем, что он появился, а не тем, что о
нём вспомнили. Ответ об имени один (`product_labels`), и страница читает его
подстановкой — литерала там быть не должно.
"""

import re

import main_legacy as core

# Паркинг — продукт своего объекта; в этих проверках места продаёт офисник.
OFFICE_PARKING = core.object_parking_product_key("offices")

RUSSIAN = re.compile(r"[а-яё]", re.IGNORECASE)


def _revenue_product_keys() -> list[str]:
    inputs = dict(core.DEFAULT_INPUTS)
    # Отдельно стоящие объекты включены намеренно: без метров их продуктов в
    # отчёте нет вовсе, и проверка была бы слепа ровно к тому продукту, из-за
    # которого написана.
    for obj in core.STANDALONE_OBJECTS:
        inputs[obj.enabled_key] = True
    req = core.CalcRequest(inputs=inputs, tep=dict(core.TEP_DEFAULT))
    result = core.calculate(req)
    report = result.get("report") or {}
    keys = [str(item["key"]) for item in (report.get("products") or [])]
    # Продукт выручки без строки отчёта (паркинг объекта без мест) всё равно
    # стоит в структуре выручки — и его имя тоже едет на экран.
    keys += [key for key in (result.get("revenue") or {})
             if key != "total" and key not in keys]
    assert len(keys) > 5, f"продуктов в отчёте почти нет: {keys}"
    return keys


def test_every_revenue_product_has_a_russian_name():
    labels = core.product_labels()
    nameless = [key for key in _revenue_product_keys()
                if not RUSSIAN.search(labels.get(key, ""))]
    assert nameless == [], (
        "продукт выручки уедет на экран сырым ключом: "
        + ", ".join(nameless)
    )


def test_the_check_would_catch_a_bare_key():
    """Сторож, не падающий на поломке, — не сторож."""
    labels = dict(core.product_labels())
    labels.pop(OFFICE_PARKING, None)
    nameless = [key for key in _revenue_product_keys()
                if not RUSSIAN.search(labels.get(key, ""))]
    assert nameless == [OFFICE_PARKING], nameless


def test_the_page_reads_the_names_from_the_engine():
    page = core.PAGE
    assert core.PRODUCT_LABELS_PLACEHOLDER not in page, "плейсхолдер не подставлен"
    for label in core.NON_TEP_PRODUCT_LABELS.values():
        assert label in page, f"имя не доехало на страницу: {label}"
    # Копии карты имён на странице нет: её негде обновлять.
    assert page.count("const PRODUCT_LABELS=") == 1

"""Лист ПРОВЕРКИ узнаёт о дописанных объектах из карты, а не из литералов.

Шаблон v4 несёт ТРИ блока отдельно стоящих объектов; всё, что ниже, книга
дописывает копированием. Пока строки дописанных были выписаны в подменах
руками, четвёртый объект пришлось вносить туда отдельной правкой, а пятый
дал бы «FAIL» на верном расчёте — ровно то, из-за чего однажды перестали
читать проверку лимита при переносе долга.
"""
import main_legacy as core


def _template_xml() -> str:
    """Лист ПРОВЕРКИ таким, каким его несёт шаблон владельца.

    Собирать этот лист руками нельзя: рукописная копия — вторая жизнь у
    формул книги, и она отстаёт в тот же день, когда код учится новой. Так и
    вышло: код выучил строку 49, а копия о ней не знала, и две проверки упали
    на ВЕРНОМ коде. Заодно снимается вторая беда — фикстура, собранная теми же
    константами, что и код, подтверждает саму себя.
    """
    import zipfile

    with zipfile.ZipFile(core._V4_TEMPLATE_PATH) as source:
        return source.read(core._v4_sheet_path(source, "ПРОВЕРКИ")).decode("utf-8")


def test_every_object_of_the_map_reaches_the_checks():
    template = set(core._V4_TEMPLATE_OBJECT_REVENUE_ROWS)
    added = [row for _, row in core._V4_OBJECT_PRODUCT_CELLS.values()
             if row not in template]
    # Предохранитель: если дописанных объектов нет вовсе, проверка не значит
    # ничего — подмены выходят тождественными.
    assert added, "в карте нет ни одного дописанного объекта"

    missing: list[str] = []
    out = core._v4_object_checks(_template_xml(), missing)

    assert missing == []
    for row in added:
        assert core.xml_escape(f"'ОБЪЕКТЫ'!B{row}") in out, row
        assert core.xml_escape(
            f"'ОБЪЕКТЫ'!B{row + core._V4_OBJECT_CHECKS_CAPEX_SHIFT}") in out, row


def test_a_fifth_object_reaches_the_checks_without_touching_the_swaps(monkeypatch):
    """Объект, заведённый завтра, попадает в проверку тем, что он появился."""
    fifth_queue, fifth_revenue = 210, 226
    cells = dict(core._V4_OBJECT_PRODUCT_CELLS)
    assert fifth_revenue not in {row for _, row in cells.values()}
    cells["storage_block"] = (fifth_queue, fifth_revenue)
    monkeypatch.setattr(core, "_V4_OBJECT_PRODUCT_CELLS", cells)

    missing: list[str] = []
    out = core._v4_object_checks(_template_xml(), missing)

    assert missing == []
    assert core.xml_escape(f"'ОБЪЕКТЫ'!B{fifth_revenue}") in out
    assert core.xml_escape(
        f"'ОБЪЕКТЫ'!B{fifth_revenue + core._V4_OBJECT_CHECKS_CAPEX_SHIFT}") in out


def test_an_unrecognised_formula_is_named_not_passed_over():
    missing: list[str] = []
    out = core._v4_object_checks("<c r=\"B40\"><f>SUM(1,2)</f></c>", missing)

    # Утверждение здесь — «ни одна подмена не прошла молча», а не «их ровно
    # три»: счёт падал бы на ДОБАВЛЕННОЙ подмене, ничего не сказав о поломке.
    assert out == "<c r=\"B40\"><f>SUM(1,2)</f></c>"
    assert missing
    assert all(m.startswith("ПРОВЕРКИ: формула не опознана") for m in missing)

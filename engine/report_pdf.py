"""PDF-отчёт проекта: сборка отчёта _build_developaid_pdf.

Гарнитуры, форматирование чисел, разделы отчёта (объектная вёрстка,
финансирование, покупка участка) и сама вёрстка PDF.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён на том месте, где этот код стоял раньше
(`_engine_part("report_pdf")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

# Встроенные в PDF гарнитуры кириллицы не содержат, поэтому отчёт целиком —
# и таблицы, и заголовки, и колонтитул — набирается подключённым TTF. Каталоги
# различаются между дистрибутивами: у Debian это liberation, у части сборок
# liberation2, поэтому ищем по обоим и не привязываемся к одному пути.
_PDF_FONT_DIRS = (
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/liberation",
    "/usr/share/fonts/truetype/liberation2",
    "/usr/share/fonts/dejavu",
)
_PDF_REGULAR_FILES = ("DejaVuSans.ttf", "LiberationSans-Regular.ttf")
_PDF_BOLD_FILES = ("DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf")


def _pdf_find_font(names: tuple[str, ...]) -> str | None:
    for name in names:
        for directory in _PDF_FONT_DIRS:
            candidate = Path(directory) / name
            if candidate.is_file():
                return str(candidate)
    return None


def _pdf_font_names() -> tuple[str, str]:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    regular = _pdf_find_font(_PDF_REGULAR_FILES)
    bold = _pdf_find_font(_PDF_BOLD_FILES)
    if not regular or not bold:
        raise RuntimeError(
            "На сервере не найден шрифт с кириллицей для PDF. "
            "Установите пакеты fontconfig и fonts-dejavu-core "
            "(в образе они ставятся в Dockerfile) и пересоберите контейнер."
        )
    if "DevelopAidSans" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DevelopAidSans", regular))
    if "DevelopAidSansBold" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DevelopAidSansBold", bold))
    return "DevelopAidSans", "DevelopAidSansBold"


def _project_articles_term(tep_report: dict[str, Any]) -> Any:
    """Имя базы общепроектных статей — то, что назвал движок."""
    return TERMS.get(str(tep_report.get("project_articles_area") or ""), CORE_TOTAL_AREA)


def _project_articles_sqm(tep_report: dict[str, Any]) -> float:
    """База общепроектных статей, м² — число движка (`project_articles_sqm`).

    У жилого и смешанного проекта это суммарная площадь МКД в ГНС, у чисто
    нежилого — суммарная площадь объектов (`object_rate_is_turnkey`). Отчёт
    старого формата поля не несёт — тогда база по-прежнему МКД.
    """
    if tep_report.get("project_articles_sqm") is not None:
        return float(tep_report.get("project_articles_sqm") or 0.0)
    return (float(tep_report.get("core_above_gns") or 0.0)
            + float(tep_report.get("core_under_gns") or 0.0))


def _above_ground_sqm(tep_report: dict[str, Any]) -> float:
    """Наземная часть проекта: строительный объём минус подземные СТРОКИ.

    Вычитается только подземная часть, которая в этом объёме стоит, — гараж
    МКД и кладовые. Гараж отдельно стоящего объекта живёт полем на его строке
    и в `total.gns` не входит вовсе: вычесть его значило бы занизить наземную
    площадь на объект, которого в ней и не было.

    Берётся из тех же строк ТЭП, что и вся таблица отчёта: заводить вторую
    арифметику ради подписи нельзя — она разойдётся с числами над ней.
    """
    return max(0.0, _number_or_zero((tep_report.get("total") or {}).get("gns"))
               - _core_underground_sqm(tep_report))


def _core_underground_sqm(tep_report: dict[str, Any]) -> float:
    """Подземная часть МКД — та, что движок и так считает своей базой.

    Читается `core_under_gns`, а не строка гаража: кладовые лежат на том же
    подземном этаже и в наземную площадь не входят, а перебор строк их терял —
    подпись отчёта относила их к наземной части. Перебор остаётся запасным
    путём для отчётов, собранных до появления базы.
    """
    base = tep_report.get("core_under_gns")
    if base is not None:
        return _number_or_zero(base)
    return sum(_number_or_zero(row.get("gns"))
               for row in (tep_report.get("rows") or [])
               if str(row.get("key")) in _UNDERGROUND_TEP_KEYS)


def _underground_sqm(tep_report: dict[str, Any]) -> float:
    """Вся подземная часть проекта: МКД, кладовые и гаражи объектов.

    Гараж офисника или ТЦ — такая же подземная площадь, как гараж дома: своя
    себестоимость метра, свой продукт местами. В подпись отчёта он не входил
    вовсе, при том что в `summary.underground_gns_sqm` и в статье CAPEX он
    есть, — две величины под одним именем.
    """
    return _core_underground_sqm(tep_report) + sum(
        _number_or_zero(row.get("under_gns"))
        for row in (tep_report.get("rows") or []))


def _number_or_zero(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if result == result else 0.0


def _pdf_num(value: Any, decimals: int = 1) -> str:
    try:
        number = float(value or 0)
    except Exception:
        return "—"
    return f"{number:,.{decimals}f}".replace(",", " ").replace(".", ",")


def _pdf_count_text(value: Any, measure: str) -> str:
    """«1 362 квартир» — одна неразрывная строка ячейки PDF.

    Число и мера связаны неразрывным пробелом, разряды числа — тоже: узкая
    колонка «Кол-во» рвала «квартир» на «кварти / р», а «1 199» — на две
    строки. Пробелы внутри длинной меры («посещений в смену») остаются
    обычными — там перенос по словам законен.
    """
    return _pdf_num(value, 0).replace(" ", "\u00a0") + "\u00a0" + measure


def _pdf_count_column_width(cells: "list[str]", font: str, size: float,
                            padding: float, minimum: float) -> float:
    """Ширина колонки количества по самому длинному неразрывному куску.

    Колонка не угадывается числом миллиметров: мера у продуктов своя, и
    «4 500 посещений в смену» длиннее «250 мест». Ячейка переносится только
    по обычным пробелам и по строкам, поэтому ширину задаёт самое длинное
    слово с неразрывными пробелами, плюс поля ячейки.
    """
    from reportlab.pdfbase.pdfmetrics import stringWidth
    widest = 0.0
    for cell in cells:
        for line in str(cell or "").split("\n"):
            for token in line.split(" "):
                widest = max(widest, stringWidth(token, font, size))
    return max(minimum, widest + 2 * padding + 1.0)


def _pdf_unit_num(value: Any, digits: int) -> str:
    """Удельное: нулевая база — прочерк, а не «0,0» (движок отдаёт None)."""
    return "—" if value is None else _pdf_num(value, digits)


def _pdf_unit_base(item: dict[str, Any]) -> str:
    """База удельного строки — подпись из словаря по ключу движка."""
    base = str(item.get("base") or "")
    return f"м² {TERMS[base].genitive}" if base in TERMS else "—"


def _pdf_unit_saleable(item: dict[str, Any], digits: int) -> str:
    """На м² продаваемой — для сравнения с ценой; у строк с этой базой не повторяется."""
    if str(item.get("base") or "") == UNIT_BASE_SALEABLE:
        return "—"
    return _pdf_unit_num(item.get("per_saleable_th"), digits)


def _pdf_unit_bases_note(summary: dict[str, Any]) -> str:
    """Площади баз удельных — числами движка и словами словаря."""
    bases = summary.get("unit_bases") or {}
    parts = [f"{TERMS[key].name} — {_pdf_num(bases.get(key), 0)} м²"
             for key in (UNIT_BASE_TOTAL, UNIT_BASE_SALEABLE, UNIT_BASE_CORE_ABOVE, UNIT_BASE_CORE_UNDER)
             if key in TERMS and bases.get(key) is not None]
    return ("Базы удельных: " + "; ".join(parts) + ". Расходы — на "
            f"{TOTAL_AREA.genitive}, выручка и прибыль — на {SALEABLE_AREA.genitive}, "
            f"СМР наземной части — на {CORE_ABOVE_AREA.genitive}, подземной — на "
            f"{CORE_UNDER_AREA.genitive}.") if parts else ""


def _pdf_money(value: Any) -> str:
    try:
        number = float(value or 0)
    except Exception:
        return "—"
    if abs(number) >= 1_000_000_000:
        return _pdf_num(number / 1_000_000_000, 2) + " млрд ₽"
    return _pdf_num(number / 1_000_000, 1) + " млн ₽"


def _pdf_pct(value: Any) -> str:
    try:
        return _pdf_num(float(value or 0) * 100, 1) + "%"
    except Exception:
        return "—"


def _phase_comparison_pdf(table: dict[str, Any], regular: str, bold: str, colors: Any) -> Any:
    """Таблица сравнения очередей для PDF — печать `phase_comparison_table`.

    Блок открывается строкой-заголовком во всю ширину; итог жирный и с линией
    сверху, слагаемое и «из них» — с отступом: то же, что на странице.
    """
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Table, TableStyle

    cell = ParagraphStyle("pc_cell", fontName=regular, fontSize=6.8, leading=8.2,
                          textColor=colors.HexColor("#222222"))
    num = ParagraphStyle("pc_num", parent=cell, alignment=2)
    strong = ParagraphStyle("pc_strong", parent=cell, fontName=bold,
                            textColor=colors.HexColor("#111111"))
    strong_num = ParagraphStyle("pc_strong_num", parent=strong, alignment=2)
    head = ParagraphStyle("pc_head", parent=strong, fontSize=6.6)
    muted = ParagraphStyle("pc_muted", parent=cell, textColor=colors.HexColor("#666666"))

    def text(value: Any) -> str:
        return (str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    def one(value: Any) -> str:
        # Одна цифра после запятой так, как округляет страница (половина —
        # вверх по короткой записи числа): иначе «вводная 10,25» выходит
        # 10,3 на экране и 10,2 в PDF.
        from decimal import ROUND_HALF_UP, Decimal
        return _pdf_num(float(Decimal(repr(float(value or 0))).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP)), 1)

    def fmt(row: dict[str, Any], value: Any) -> str:
        if value is None or value == "":
            return "—"
        kind = row.get("kind")
        if kind == "money":
            # Одна единица на таблицу, как на странице: «166,0 млн» под
            # «3,15 млрд» читается как другой масштаб колонки.
            return _pdf_num(float(value) / 1_000_000_000, 2) + " млрд ₽"
        if kind == "qty":
            unit = str(row.get("unit") or "")
            return (_pdf_num(value, 0 if unit == "шт." else 1) + " " + unit).strip()
        if kind == "th":
            return one(value)
        if kind == "pct":
            return _pdf_pct(value)
        if kind == "mult":
            return _pdf_num(value, 2) + "x"
        if kind == "date":
            raw = str(value)[:10]
            return f"{raw[8:10]}.{raw[5:7]}.{raw[:4]}" if len(raw) == 10 else raw
        return str(value)

    def label(row: dict[str, Any]) -> str:
        out = str(row.get("label") or "")
        if row.get("rate_input") is not None:
            out += f" (вводная {one(row['rate_input'])})"
        if row.get("kind") == "th":
            out += ", тыс ₽/м²"
        return out

    columns = list(table.get("columns") or [])
    span = len(columns) + 2
    data: list[list[Any]] = [[Paragraph("Показатель", head)]
                             + [Paragraph(text(n), ParagraphStyle("pc_hn", parent=head, alignment=2))
                                for n in columns + ["Свод"]]]
    style: list[tuple] = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#111111")),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, colors.HexColor("#E2E2E2")),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]
    # Делители удельных — одна подпись таблицы мелким шрифтом под шапкой,
    # как на странице, а не строки-показатели.
    note = ParagraphStyle("pc_note", parent=muted, fontSize=5.8, leading=7.0)
    section = ParagraphStyle("pc_section", parent=strong, fontSize=8.2, leading=10,
                             textColor=colors.white)
    divisors = [
        text(str(d.get("label") or "")) + ": " + " · ".join(
            [text(n) + " " + _pdf_num(v, 0) for n, v in zip(columns, d.get("values") or [])]
            + ["свод " + _pdf_num(d.get("total"), 0)]) + " " + text(str(d.get("unit") or ""))
        for d in table.get("divisors") or []]
    if divisors:
        i = len(data)
        data.append([Paragraph("Удельные показатели — делители: " + "<br/>".join(divisors), note)]
                    + [""] * (span - 1))
        style += [("SPAN", (0, i), (-1, i)), ("TOPPADDING", (0, i), (-1, i), 4)]
    for block in table.get("blocks") or []:
        i = len(data)
        # Заголовок раздела — тёмная полоса крупнее итогов: жирное «Итого» с
        # линией выглядело так же, и разделы терялись (владелец, 29.09.2026).
        data.append([Paragraph(text(str(block.get("title") or "").upper()), section)] + [""] * (span - 1))
        style += [("SPAN", (0, i), (-1, i)), ("TOPPADDING", (0, i), (-1, i), 4),
                  ("BOTTOMPADDING", (0, i), (-1, i), 4),
                  ("BACKGROUND", (0, i), (-1, i), colors.HexColor("#111111"))]
        for row in block.get("rows") or []:
            i = len(data)
            if row.get("kind") == "note":
                data.append([Paragraph(text(str(row.get("label") or "")), note)] + [""] * (span - 1))
                style += [("SPAN", (0, i), (-1, i)), ("LEFTPADDING", (0, i), (0, i), 12)]
                continue
            role = row.get("role") or ""
            lab_style = strong if role == "total" else (muted if role in ("part", "sub") else cell)
            num_style = strong_num if role == "total" else num
            values = list(row.get("values") or []) + [row.get("total")]
            data.append([Paragraph(text(label(row)), lab_style)]
                        + [Paragraph(text(fmt(row, v)), num_style) for v in values])
            if role == "total":
                style.append(("LINEABOVE", (0, i), (-1, i), 0.9, colors.HexColor("#111111")))
            if role in ("part", "sub"):
                style.append(("LEFTPADDING", (0, i), (0, i), 12))
    label_w = 62 * mm
    rest = (170 * mm - label_w) / max(1, len(columns) + 1)
    out = Table(data, colWidths=[label_w] + [rest] * (len(columns) + 1), repeatRows=1, hAlign="LEFT")
    out.setStyle(TableStyle(style))
    return out


def _pdf_entry_cost_rows(result: dict[str, Any],
                         expense_structure: list[dict[str, Any]]) -> list[list[str]]:
    """Цена входа и плата за ВРИ — из расчёта, а не из формы.

    Форма не знает ни о льготе, ни о доле очереди. При стопроцентной льготе
    отчёт печатал полную плату за смену ВРИ как расход, которого в модели нет:
    ключевая экономика не сходилась с собственной структурой расходов ниже, и
    оба числа выглядели достоверно.
    """
    purchase = 0.0
    for group in expense_structure or []:
        if str(group.get("label")) == "Цена приобретения":
            purchase = float(group.get("value") or 0)
            break
    paid = float((result.get("capex") or {}).get("land_rights") or 0)
    relief = float(((result.get("vri") or {}).get("totals") or {}).get("relief") or 0)
    # Стоимость сделки — две строки и итог, когда в ней есть выкуп ЗУ/ОКС у
    # третьих лиц (решение владельца, 29.09.2026). Разбивка — из сводки
    # расчёта, итог — та же группа структуры расходов.
    deal = result.get("deal") or {}
    buyout = float(deal.get("buyout_mln") or 0) * 1_000_000
    deal_rows = ([["Цена участка / права", _pdf_money(purchase - buyout)],
                  ["Выкуп ЗУ/ОКС у третьих лиц (кадастровая стоимость, не цена сделки)",
                   _pdf_money(buyout)],
                  ["Стоимость сделки", _pdf_money(purchase)]]
                 if buyout > 0 else [["Цена приобретения", _pdf_money(purchase)]])
    return [
        *deal_rows,
        ["Смена ВРИ / земельные права",
         _pdf_money(paid) + (f" (льгота {_pdf_money(relief)})" if relief > 0 else "")],
    ]


def _layout_dscr(layout: Any) -> float | None:
    """DSCR кредита объекта для вердикта — только у проекта без ДДУ.

    У проекта с БРИДЖем и ПФ вердикт меряет LLCR, как прежде; у проекта без
    них — минимальный DSCR объектов из `report_layout`. Нет DSCR (прямая
    продажа без аренды) — вердикт без долговой проверки.
    """
    if not isinstance(layout, dict) or layout.get("project_finance", True):
        return None
    metric = layout.get("debt_metric")
    if isinstance(metric, dict):
        return float(metric["value"]) if metric.get("key") == "dscr" else None
    values = [float(t["value"]) for t in layout.get("nonres_tiles") or []
              if t.get("unit") == "mult" and t.get("value") is not None]
    return min(values) if values else None


def _layout_no_debt_cover(layout: Any) -> bool:
    """У проекта без ПФ нет показателя долга (`debt_metric.key` пуст): кредит
    объектов гасится продажами. Вердикт тогда не говорит ни об LLCR, ни о DSCR."""
    metric = layout.get("debt_metric") if isinstance(layout, dict) else None
    return isinstance(metric, dict) and not metric.get("key")


def _purchase_feasibility(
    purchase_price_mln: Any,
    net_profit_mln: Any,
    llcr: Any,
    debt_amount: Any = 0.0,
    ending_debt_mln: Any = 0.0,
    default_date: Any = None,
    pf_shortfall_mln: Any = 0.0,
    pf_shortfall_month: Any = None,
    object_dscr: Any = None,
    no_debt_cover: bool = False,
) -> dict[str, str]:
    """Вердикт по вводным плюс оговорка о дефолте, если он в модели был.

    Дефолт в дату раскрытия эскроу — факт о расчёте, а не ещё одна ветка
    вердикта: он верен и при низком LLCR, и при высоком, и спорить с ними за
    очередь ему незачем. Прежде он звучал ровно в одном случае — когда долг
    оставался непогашенным на КОНЕЦ горизонта. Если остаточные продажи его
    закрывали, вердикт молчал, и прибыль печаталась голым числом: банк при
    этом ждал погашения в РВЭ и не получил его (владелец, 30.08.2026:
    «значит нельзя писать и чистую прибыль»).
    """
    verdict = _purchase_feasibility_base(
        purchase_price_mln, net_profit_mln, llcr, debt_amount, ending_debt_mln,
        object_dscr, no_debt_cover)
    verdict = _financing_not_closed_clause(
        verdict, pf_shortfall_mln, pf_shortfall_month)
    when = str(default_date or "").strip()
    # У ветки «Дефолтный» оговорка уже своя, и повторять её нечем.
    if not when or verdict.get("status") in ("default", "not_available"):
        return verdict
    verdict = dict(verdict)
    verdict["conditional"] = True
    verdict["default_date"] = when
    verdict["text"] = verdict["text"].rstrip() + (
        f" В модели есть дефолт: {_month_in_words(when)} раскрытого эскроу не "
        "хватило на погашение ПФ. Долг закрывается позже, продажами следующих "
        "периодов, — но только если банк на это согласится: пени и досрочное "
        "требование модель не считает. Значит показанная чистая прибыль — при "
        "этом допущении, а не результат.")
    return verdict


def _financing_not_closed_clause(
    verdict: dict[str, str], shortfall_mln: Any, shortfall_month: Any,
) -> dict[str, str]:
    """Одобренного лимита ПФ не хватило — экономика показана при допущении.

    Движок это умел с самого начала: доходит выборка до потолка — остаток
    уходит в `pf_shortfall` с месяцем первой нехватки. А до вердикта величина
    не доезжала вовсе — её не было ни в своде, ни в отчёте, только в
    `finance`, — и проект, которому банк не дал трети нужных денег, получал
    «Предварительно целесообразна» ровно тем же текстом, что и полностью
    профинансированный.

    Ветка здесь не заводится, и это не упущение: приписка того же рода, что у
    дефолта в РВЭ (решение владельца, 30.08.2026), — она верна и при LLCR
    0,99, и при 1,38, и спорить с ними за очередь ей незачем. Чего модель НЕ
    делает: не выдумывает, откуда возьмутся недостающие деньги, и не считает
    их стоимость. Она называет сумму, месяц и то, что дальше посчитано так,
    будто их кто-то дал.
    """
    try:
        gap = float(shortfall_mln or 0.0)
    except (TypeError, ValueError):
        gap = 0.0
    # Полмиллиона — тот же порог, по которому отчёт печатает остаток ПФ:
    # копейки округления новостью не являются.
    if gap <= 0.5:
        return verdict
    verdict = dict(verdict)
    # Заголовок положительной ветки — единственный, который правится. «Предварительно
    # целесообразна» это утверждение без условий, а условие как раз есть, и в
    # PDF с чатом видно прежде всего заголовок: текст под ним читают не все.
    # У прочих веток («нецелесообразна», «требует пересмотра», «дефолтный»)
    # заголовок зелёным светом и не был — там хватает приписки.
    if verdict.get("status") == "positive":
        verdict["status"] = "review"
        verdict["title"] = "Целесообразность не подтверждена: финансирование не закрыто"
    verdict["conditional"] = True
    verdict["financing_gap"] = True
    verdict["pf_shortfall_mln"] = gap
    when = str(shortfall_month or "").strip()
    verdict["pf_shortfall_month"] = when
    since = f" — впервые {_month_in_words(when)}" if len(when) >= 7 else ""
    verdict["text"] = verdict["text"].rstrip() + (
        f" Финансирование не закрыто: одобренного лимита ПФ не хватает на "
        f"{_telegram_number(gap, 1)} млн ₽{since}. Дальше посчитано так, будто "
        "эти деньги проект получил: источника у них в модели нет, и их "
        "стоимость не учтена. Пока лимит не подтверждён, показанные прибыль, "
        "маржинальность и LLCR — при этом допущении, а не результат.")
    return verdict


def _month_in_words(iso: Any) -> str:
    """«2030-01-01» → «в январе 2030». Пустое — «в дату раскрытия»."""
    text = str(iso or "").strip()
    if len(text) < 7:
        return "в дату раскрытия эскроу"
    try:
        year, month = int(text[:4]), int(text[5:7])
    except ValueError:
        return "в дату раскрытия эскроу"
    if not 1 <= month <= 12:
        return "в дату раскрытия эскроу"
    return f"в {_MONTHS_IN[month - 1]} {year}"


# Предложный падеж списком, а не заменой окончаний: правило «я→е» однажды
# даст «в феврале» из чего угодно. Тот же список, той же формы, что на
# странице (RU_MONTHS_IN) — но объявить его один раз на два языка нечем.
_MONTHS_IN = ("январе", "феврале", "марте", "апреле", "мае", "июне", "июле",
              "августе", "сентябре", "октябре", "ноябре", "декабре")


def _purchase_feasibility_base(
    purchase_price_mln: Any,
    net_profit_mln: Any,
    llcr: Any,
    debt_amount: Any = 0.0,
    ending_debt_mln: Any = 0.0,
    object_dscr: Any = None,
    no_debt_cover: bool = False,
) -> dict[str, str]:
    """Return a short preliminary purchase-feasibility conclusion.

    `object_dscr` — у проекта без ДДУ (`report_layout.project_finance` ложно)
    долг — кредит объекта, и его покрытие меряет DSCR, а не LLCR: те же
    пороги 1,00x и 1,20x.

    The conclusion uses only the current model parameters. It does not estimate
    market value or calculate an alternative purchase price.
    """
    try:
        purchase_price = float(purchase_price_mln or 0.0)
    except (TypeError, ValueError):
        purchase_price = 0.0
    try:
        net_profit = float(net_profit_mln or 0.0)
    except (TypeError, ValueError):
        net_profit = 0.0
    try:
        llcr_value = float(llcr or 0.0)
    except (TypeError, ValueError):
        llcr_value = 0.0
    try:
        debt = float(debt_amount or 0.0)
    except (TypeError, ValueError):
        debt = 0.0
    try:
        ending_debt = float(ending_debt_mln or 0.0)
    except (TypeError, ValueError):
        ending_debt = 0.0

    if purchase_price <= 0:
        return {
            "status": "not_available",
            "title": "Вывод не сформирован",
            "text": "Цена покупки не указана, поэтому оценить целесообразность приобретения при текущих параметрах нельзя.",
        }
    # Непогашенный долг на конец проекта — дефолт, и он старше бумажной
    # прибыли: для инвестора такой проект не «прибыльный с оговоркой», а
    # дефолтный (решение владельца, 27.08.2026). Закрыть дыру «вкладом
    # акционера» — значит показать благотворительность как инвестицию.
    if ending_debt > 0.5:
        return {
            "status": "default",
            "title": "Дефолтный: долг не погашается",
            "text": (
                "На конец проекта остаётся непогашенный долг "
                f"{_telegram_number(ending_debt, 1)} млн ₽ — денежного потока "
                "проекта не хватает вернуть кредит. Показанная чистая прибыль — "
                "бумажная: чтобы рассчитаться с банком, инвестору пришлось бы "
                "доплатить эту сумму своими деньгами. Для инвестора проект "
                "дефолтный, а не прибыльный."
            ),
        }
    if net_profit <= 0:
        return {
            "status": "negative",
            "title": "Предварительно нецелесообразна",
            "text": "При текущей цене покупки и принятых параметрах проект не формирует положительную чистую прибыль.",
        }
    if object_dscr is not None:
        dscr = float(object_dscr)
        shown = _telegram_number(dscr, 2)
        if dscr < 1.0:
            return {"status": "negative", "title": "Предварительно нецелесообразна",
                    "text": f"Проект прибылен, но NOI не покрывает обслуживание кредита объекта: DSCR {shown}x — ниже 1,00x."}
        if dscr < 1.20:
            return {"status": "review", "title": "Требует пересмотра условий покупки",
                    "text": f"Проект формирует прибыль, однако DSCR кредита объекта {shown}x — ниже целевого уровня 1,20x. Следует проверить аренду, долю кредита, ставку и срок."}
        return {"status": "positive", "title": "Предварительно целесообразна",
                "text": f"При текущей цене покупки проект формирует положительную чистую прибыль, а DSCR кредита объекта {shown}x — не ниже 1,20x."}
    if debt > 0 and llcr_value < 1.0:
        return {
            "status": "negative",
            "title": "Предварительно нецелесообразна",
            "text": "Проект прибылен, но денежного потока недостаточно для обслуживания расчётной долговой нагрузки: LLCR ниже 1,00x.",
        }
    if debt > 0 and llcr_value < 1.20:
        return {
            "status": "review",
            "title": "Требует пересмотра условий покупки",
            "text": "Проект формирует прибыль, однако LLCR ниже целевого уровня 1,20x. Следует проверить цену покупки, себестоимость, сроки и условия финансирования.",
        }
    if debt > 0:
        return {
            "status": "positive",
            "title": "Предварительно целесообразна",
            "text": "При текущей цене покупки проект формирует положительную чистую прибыль, а LLCR находится не ниже целевого уровня 1,20x.",
        }
    if no_debt_cover:
        return {
            "status": "positive",
            "title": "Предварительно целесообразна",
            "text": "При текущей цене покупки проект формирует положительную чистую прибыль; кредит объектов гасится выручкой прямых продаж, покрытие долга NOI не меряется — погашение кредита показано в «Финансировании объекта».",
        }
    return {
        "status": "positive",
        "title": "Предварительно целесообразна",
        "text": "При текущей цене покупки проект формирует положительную чистую прибыль; долговое финансирование не создаёт ограничений по LLCR.",
    }


class _PdfSection:
    """Метка секции в потоке отчёта.

    Разделы собирались в том порядке, в каком их удобно было считать, и отчёт
    читался не как разбор проекта, а как история правок: удельные расходы
    стройки стояли на первой странице до ТЭП, вводные — после выводов и
    чувствительности, а графики продаж жили в блоке финансирования. Порядок
    вычислений менять нельзя (одно опирается на другое), поэтому разделы
    помечаются здесь, а собираются в читаемом порядке при сборке документа.
    """

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name


def _project_cadastral_numbers(inputs: dict[str, Any]) -> list[str]:
    """Все кадастровые номера проекта — из первого места, где проект хранит
    участок номерами: снимок поиска ЕГРН (`_land_lookup.query`), поле
    `cadastral_numbers`, вписанное в поле участка (`_cadastral_query`), расчёт
    ТЭП по номеру (`_cadastral_analysis`). Поиск по адресу номеров не даёт и
    следующие места не заслоняет. Без обрезки: территория КРТ из двадцати
    участков — двадцать номеров, и тизер, таблица и карта читают этот список
    целиком."""
    inputs = inputs or {}
    analysis = inputs.get("_cadastral_analysis") or {}
    analysed = analysis.get("recognized") or analysis.get("requested") or []
    sources = (
        (inputs.get("_land_lookup") or {}).get("query"),
        inputs.get("cadastral_numbers"),
        inputs.get("_cadastral_query"),
        " ".join(_land_text(item) for item in analysed) if isinstance(analysed, list)
        else analysed,
    )
    for source in sources:
        numbers: list[str] = []
        for n in re.findall(r"(?<![\d:])\d{2}:\d{2}:\d{6,8}:\d+", _land_text(source)):
            if n not in numbers:
                numbers.append(n)
        if numbers:
            return numbers
    return []


_PDF_NOT_RECEIVED = "не получено от источника"


def _pdf_screening_rows(numbers: list[str], screening: dict[str, Any] | None,
                        failure: str = "") -> list[list[str]]:
    """Строки ограничений полного PDF — по каждому участку проекта (#655).

    Прежде скринились первые десять номеров, а таблица строилась из находок:
    участок без ответа источника или за пределом десятки в отчёт не попадал
    вовсе и читался как чистый. Теперь у каждого номера есть хотя бы одна
    строка: находки, «ограничений не обнаружено», «не проверялся» с причиной
    или «не получено от источника» с тем, что сказал источник."""
    by_number = {str(p.get("cadastral_number") or ""): p
                 for p in (screening or {}).get("parcels") or []}
    threshold = (screening or {}).get("min_area_sqm")
    rows: list[list[str]] = []
    for number in numbers:
        parcel = by_number.get(number)
        if screening is None:
            rows.append([number, _PDF_NOT_RECEIVED,
                         "Скрининг НСПД не выполнен: " + (failure or "сервис не ответил"), "—"])
            continue
        if parcel is None:
            rows.append([number, _PDF_NOT_RECEIVED,
                         "Участка нет в ответе скрининга НСПД", "—"])
            continue
        if not parcel.get("found"):
            rows.append([number, _PDF_NOT_RECEIVED,
                         str(parcel.get("note") or "Сведения ЕГРН по номеру не получены."), "—"])
            continue
        if parcel.get("too_small"):
            edge = (f" {_pdf_num(threshold, 0)} м²" if threshold else "")
            rows.append([number, "не проверялся",
                         f"Участок меньше порога скрининга{edge}", "—"])
            continue
        if not parcel.get("center"):
            rows.append([number, "не проверялся",
                         "Границы участка не получены — НСПД об ограничениях не спрашивали", "—"])
            continue
        findings = parcel.get("findings") or []
        if not findings:
            rows.append([number, "ограничений не обнаружено", "—", "—"])
            continue
        for finding in findings:
            mark = {"killer": "СТОП", "economic": "ВЛИЯЕТ"}.get(
                finding.get("flag_class"), "справка")
            regs = finding.get("reg_numbers") or (
                [finding.get("reg_number")] if finding.get("reg_number") else [])
            basis = ", ".join(str(n) for n in regs if n)
            if finding.get("document_number"):
                basis = (basis + " · " if basis else "") + str(finding["document_number"])
            share = finding.get("coverage_pct")
            impact = str(finding.get("impact", ""))
            if share is not None:
                impact = f"{impact} · накрывает ~{_pdf_num(share, 0)}% участка".strip(" ·")
            rows.append([number, f"{mark} · {finding.get('name','')}", impact, basis or "—"])
    return rows


def _pdf_ordered_story(story: list[Any], order: list[tuple[str, bool]],
                       page_break: Any) -> list[Any]:
    """Поток отчёта, пересобранный по секциям.

    До первой метки идёт шапка — она остаётся на месте. Разрыв страницы
    ставится перед секцией, только если в ней что-то есть: пустая секция не
    имеет права оставлять за собой пустую страницу.
    """
    head: list[Any] = []
    sections: dict[str, list[Any]] = {}
    current: str | None = None
    for item in story:
        if isinstance(item, _PdfSection):
            current = item.name
            sections.setdefault(current, [])
            continue
        (sections[current] if current is not None else head).append(item)
    out = list(head)
    for name, breaks_page in order:
        block = sections.get(name) or []
        if not block:
            continue
        if breaks_page and out:
            out.append(page_break())
        out.extend(block)
    return out


def _pdf_pf_step_rows(financing: dict[str, Any]) -> list[list[str]]:
    """Ступени надбавки по покрытию эскроу — строками таблицы финансирования.

    Средняя ставка без лестницы объяснима, с лестницей — нет: банк спросит,
    почему процент такой, и ответ «в среднем 0,22%» его не устроит. Показываем
    ступень, её ставку и сколько месяцев она действовала. Ступеней нет — нет и
    строк: у большинства НКЛ ставка одна.
    """
    rows: list[list[str]] = []
    for step in (financing.get("pf_special_steps") or []):
        edge = str(step.get("coverage_from_pct", "")).replace(".", ",")
        rate = str(step.get("rate_pct", "")).replace(".", ",")
        rows.append([f"Ступень: покрытие от {edge}%",
                     f"{rate}% · {int(step.get('months') or 0)} мес."])
    return rows


# Легенда графика покрытия эскроу объявлена один раз. Её читают страница и PDF,
# и разошедшиеся подписи одних и тех же линий — это две версии правды об одном
# графике: копии уже разошлись, одна называла накопленное накопленным, вторая
# нет. Стиль здесь назван, а не нарисован: у страницы это CSS, у PDF — штрих.
_ESCROW_CHART_LEGEND: tuple[tuple[str, str, str], ...] = (
    ("Эскроу накоплено", "#2D6A4F", "area"),
    ("Обязательство: тело + начисленные проценты и комиссии", "#A35D00", "line"),
    ("Тело ПФ", "#A35D00", "dash4"),
    ("Чем эскроу не перекрыт", "#A35D00", "band"),
    ("Раскрыто с эскроу, накопленным итогом", "#1B5E77", "dash6"),
    ("Продано после ввода, накопленным итогом", "#1B5E77", "thin"),
)
ESCROW_CHART_LEGEND_PLACEHOLDER = "__DEVELOPAID_ESCROW_LEGEND__"


def _escrow_chart_legend_html() -> str:
    """Та же легенда разметкой страницы."""
    spans = []
    for text, colour, style in _ESCROW_CHART_LEGEND:
        if style == "dash4":
            fill = f"repeating-linear-gradient(90deg,{colour} 0 4px,transparent 4px 7px)"
        elif style == "dash6":
            fill = f"repeating-linear-gradient(90deg,{colour} 0 6px,transparent 6px 10px)"
        elif style == "area":
            fill = f"{colour};opacity:.45;height:9px"
        elif style == "band":
            fill = f"{colour};opacity:.25;height:9px"
        elif style == "thin":
            fill = f"{colour};opacity:.55;height:2px"
        else:
            fill = colour
        spans.append(f'<span><i style="background:{fill}"></i>{html.escape(text)}</span>')
    return '<div class="legend">' + "".join(spans) + "</div>"


def _pdf_nonres_value(row: dict[str, Any]) -> str:
    """Значение строки нежилья и гостиницы (`nonres_report`, `hotel_report`,
    `report_layout`) для PDF. Отсутствующее — «—», а не ноль."""
    unit, value = row.get("unit"), row.get("value")
    if value is None and unit not in ("text", "section"):
        return "—"
    if unit == "mln":
        return _pdf_num(float(value) / 1e6, 1) + " млн ₽"
    if unit == "rub_unit":
        return _pdf_num(float(value), 0) + " ₽"
    if unit == "count":
        return _pdf_num(float(value), 0)
    if unit == "years":
        return _pdf_num(float(value), 1)
    if unit == "rub":
        return _pdf_money(value)
    if unit == "pct":
        return _pdf_num(float(value or 0) * 100, 1) + "%"
    if unit == "mult":
        return "—" if value is None else _pdf_num(float(value), 2) + "x"
    if unit == "date":
        return ".".join(reversed(str(value or "—")[:7].split("-")))
    if unit == "section":
        return " "  # пустая клетка: «—» значило бы «нет данных»
    return str(value or "—")


# Метки PDF у разделов объектной вёрстки: свои — `object_<ключ>`, общие
# с жилой — финансирование (кредит объекта и собственное участие),
# чувствительность и календарь.
_PDF_OBJECT_SHARED = {"finance": "financing", "sensitivity": "sensitivity",
                      "calendar": "calendar"}


def _pdf_section_order(object_sections: dict[str, Any]) -> list[tuple[str, bool]]:
    """Порядок разделов PDF — порядок `report_layout.sections` движка.

    Жилой: разбор проекта — что за участок → что на нём выходит → на чём
    считали → сколько стоит → сколько приносит → чем финансируется → чем
    рискуем → когда. Объектный: девять разделов владельца; реализуемость
    посадки — в разделе «Объект и участок».
    """
    if not object_sections:
        return [
            ("tep", False), ("vri", False), ("screening", True), ("summary", False),
            ("phases", True), ("premises", True),
            ("expenses", False), ("expenses_detail", False),
            ("income", True), ("financing", True), ("sensitivity", True),
            ("calendar", False), ("footer", False),
        ]
    order: list[tuple[str, bool]] = []
    for index, key in enumerate(object_sections):
        name = _PDF_OBJECT_SHARED.get(key, f"object_{key}")
        order.append((name, index > 0 and key != "calendar"))
        if key == "object":
            order.append(("screening", False))
    return order + [("footer", False)]


def _pdf_object_value(row: dict[str, Any]) -> str:
    """Значение строки объектной вёрстки: единицы `nonres_report` плюс метры,
    места, тыс ₽/м² и вводная со своей единицей."""
    unit, value = row.get("unit"), row.get("value")
    if unit in ("sqm", "count", "th", "num") and value is None:
        return "—"
    if unit == "sqm":
        return _pdf_num(value, 0) + " м²"
    if unit == "count":
        return _pdf_num(value, 0)
    if unit == "th":
        return _pdf_num(value, 1) + " тыс ₽/м²"
    if unit == "num":
        return (_pdf_num(value, 2).rstrip("0").rstrip(",") + (" " + str(row["suffix"])
                                                             if row.get("suffix") else ""))
    return _pdf_nonres_value(row)


def _object_pdf_sections(story: list[Any], sections: dict[str, Any], inputs: dict[str, Any],
                         P: Any, table: Any, h2: Any, small: Any, normal: Any,
                         KeepTogether: Any, Spacer: Any, mm: float, *,
                         sensitivity_done: bool) -> None:
    """Разделы объектной вёрстки в поток PDF — блоками движка, без пересчёта."""
    for key, section in sections.items():
        if key in ("finance", "calendar") or (key == "sensitivity" and sensitivity_done):
            continue
        story.append(_PdfSection(_PDF_OBJECT_SHARED.get(key, f"object_{key}")))
        story.append(P(str(section.get("title") or ""), h2))
        _object_pdf_blocks(story, section, inputs, P, table, small, KeepTogether, Spacer, mm)


def _object_pdf_blocks(story: list[Any], section: dict[str, Any], inputs: dict[str, Any],
                       P: Any, table: Any, small: Any, KeepTogether: Any, Spacer: Any,
                       mm: float) -> None:
    """Блоки одного раздела объектной вёрстки — таблицами движка."""
    for block in section.get("blocks") or []:
        title = str(block.get("title") or "")
        ref = block.get("ref")
        if block.get("kind") == "verdict" and section.get("verdict"):
            verdict = section["verdict"]
            story.append(table([["Вывод", str(verdict.get("title") or "")],
                                ["Основание", str(verdict.get("text") or "")]],
                               [45*mm, 125*mm], header=False, font_size=8.0))
            continue
        if ref == "goal_seek":
            goal = section.get("goal_seek") or {}
            story.append(P(
                (f"{title}: подбирается на странице отчёта полным пересчётом модели — "
                 f"наибольшая цена участка, при которой «{goal.get('label')}» не ниже "
                 f"{_pdf_num(goal.get('target'), 2)}x.") if goal.get("metric")
                else f"{title}: {goal.get('reason') or 'показателя долга у проекта нет.'}",
                small))
            continue
        if ref == "site":
            rows = []
            area = float(inputs.get("site_area_ha") or 0)
            if area > 0:
                rows.append(["Площадь участка", _pdf_num(area, 4) + " га"])
            numbers = _project_cadastral_numbers(inputs)
            if numbers:
                rows.append(["Кадастровые номера", ", ".join(numbers)])
            if rows:
                story.append(KeepTogether([P(title, small),
                                           table(rows, [60*mm, 110*mm], header=False)]))
            continue
        if ref == "sensitivity":
            brief = ", ".join(str(r.get("value") or "") for r in section.get("brief") or [])
            story.append(P("Чувствительность не рассчитана на вкладке — факторы объекта: "
                           + (brief or "—") + ".", small))
            continue
        if block.get("years"):
            columns = block.get("columns") or []
            rows = [[str(c[1]) for c in columns]]
            for year in block["years"]:
                rows.append([str(year.get(c[0])) if c[2] == "text"
                             else _pdf_object_value({"unit": c[2], "value": year.get(c[0])})
                             for c in columns])
            width = 170 / max(1, len(columns))
            story.append(KeepTogether([P(title, small),
                                       table(rows, [width*mm] * len(columns), font_size=6.8)]))
            continue
        rows = [[title or " ", " "]]
        for row in block.get("rows") or []:
            rows.append([str(row.get("label") or ""), _pdf_object_value(row)])
        story.append(table(rows, [112*mm, 58*mm], font_size=7.6))
        story.append(Spacer(1, 2*mm))


def _build_developaid_pdf(payload: dict[str, Any]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.graphics.shapes import Circle, Drawing, Line, PolyLine, Polygon, Rect, String
    from reportlab.platypus import KeepTogether, SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

    regular, bold = _pdf_font_names()
    result = payload.get("result") or {}
    inputs = payload.get("inputs") or {}
    summary = result.get("summary") or {}
    report = result.get("report") or {}
    financing = report.get("financing") or {}
    tep_report = result.get("tep") or {}
    products = report.get("products") or []
    expense_structure = report.get("expense_structure") or []
    calendar_data = report.get("calendar") or {}
    # Проект без жилья — свои разделы (`report.object_report`, вёрстку выбрал
    # движок в `report_layout.kind`): PDF их печатает, а не собирает.
    _object_sections = {str(sec.get("key")): sec
                        for sec in (report.get("object_report") or {}).get("sections") or []}
    _object_calendar = (_object_sections.get("calendar") or {}).get("calendar") or {}
    if _object_calendar.get("events"):
        calendar_data = _object_calendar
    cads = payload.get("cadastral_numbers") or []
    source_label = str(payload.get("source_label") or "ТЭП DevelopAid")
    scenario_key = str(payload.get("scenario") or "base")
    scenario_label = {"conservative":"Консервативный","base":"Базовый","optimistic":"Оптимистичный"}.get(scenario_key, scenario_key or "Базовый")
    # Класс — то же решение, что у карточки и предпосылок (`project_class_view`).
    _class_view = project_class_view(inputs)
    class_label = _class_view["label"]
    class_title = "Класс жилья" if _class_view["kind"] == "housing" else _class_view["title"]
    project_name = str(payload.get("project_name") or "").strip()
    title_scope = project_name or (", ".join(str(x) for x in cads) if cads else "Девелоперский проект")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf,pagesize=A4,rightMargin=14*mm,leftMargin=14*mm,topMargin=14*mm,bottomMargin=15*mm,title=f"DevelopAid — {title_scope}",author="DevelopAid")
    styles = getSampleStyleSheet()
    normal = ParagraphStyle("normal_ru",parent=styles["BodyText"],fontName=regular,fontSize=8.8,leading=12,textColor=colors.HexColor("#222222"))
    small = ParagraphStyle("small_ru",parent=normal,fontSize=7.4,leading=9.5,textColor=colors.HexColor("#666666"))
    h1 = ParagraphStyle("h1_ru",parent=styles["Title"],fontName=bold,fontSize=20,leading=24,spaceAfter=5,textColor=colors.HexColor("#111111"))
    h2 = ParagraphStyle("h2_ru",parent=styles["Heading2"],fontName=bold,fontSize=12.5,leading=16,spaceBefore=8,spaceAfter=6,textColor=colors.HexColor("#111111"))

    def P(value: Any, style=normal):
        text = str(value if value not in (None, "") else "—")
        return Paragraph(html.escape(text).replace("\n", "<br/>"), style)

    def table(rows, widths=None, header=True, font_size=8.0):
        converted=[]
        for r_idx,row in enumerate(rows):
            converted.append([cell if hasattr(cell,'wrap') else P(cell, small if (header and r_idx==0) else normal) for cell in row])
        t=Table(converted,colWidths=widths,repeatRows=1 if header else 0,hAlign='LEFT')
        commands=[('FONTNAME',(0,0),(-1,-1),regular),('FONTSIZE',(0,0),(-1,-1),font_size),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('GRID',(0,0),(-1,-1),0.35,colors.HexColor('#D8D8D8')),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)]
        if header and rows:
            commands += [('BACKGROUND',(0,0),(-1,0),colors.HexColor('#F1F1EF')),('FONTNAME',(0,0),(-1,0),bold)]
        t.setStyle(TableStyle(commands));return t

    def chart_month(value: Any) -> str:
        try:
            parsed = d(str(value)[:10])
            return f"{parsed.month:02d}.{parsed.year}"
        except Exception:
            return str(value or "—")[:7]

    def tornado_chart(rows: list[dict[str, Any]], base: float, digits: int) -> Drawing | None:
        """Горизонтальные плечи от базовой линии, как на вкладке.

        Плечо рисуется от базы к своему значению, поэтому случай, когда рост
        параметра ухудшает показатель, отображается сам собой.
        """
        values = [base]
        for row in rows:
            for key in ("low_result", "high_result"):
                if row.get(key) is not None:
                    values.append(float(row[key]))
        low, high = min(values), max(values)
        if high - low < 1e-9:
            high = low + 1.0
        span = (high - low) * 1.08
        low -= (high - low) * 0.04
        width, row_h = 500, 17
        label_width, plot = 170, 250
        height = 14 + row_h * len(rows)
        drawing = Drawing(width, height)

        def position(value: float) -> float:
            return label_width + (value - low) / span * plot

        for index, row in enumerate(rows):
            y = height - 14 - index * row_h
            label = str(row.get("label") or "—")
            if len(label) > 30:
                label = label[:28] + "…"
            drawing.add(String(0, y, label, fontName=regular, fontSize=7,
                               fillColor=colors.HexColor("#333333")))
            for key, colour in (("low_result", "#A35D00"), ("high_result", "#2D6A4F")):
                value = row.get(key)
                if value is None:
                    continue
                start = min(position(base), position(float(value)))
                end = max(position(base), position(float(value)))
                drawing.add(Rect(start, y - 2, max(1.0, end - start), 9,
                                 fillColor=colors.HexColor(colour), strokeColor=None))
            pair = [row.get("low_result"), row.get("high_result")]
            pair = [float(v) for v in pair if v is not None]
            if pair:
                drawing.add(String(position(max(pair)) + 4, y, _pdf_num(max(pair), digits),
                                   fontName=regular, fontSize=6.5,
                                   fillColor=colors.HexColor("#777777")))
        drawing.add(Line(position(base), 2, position(base), height - 4,
                         strokeColor=colors.HexColor("#111111"), strokeWidth=1))
        return drawing

    def expense_bar_chart(items: list[dict[str, Any]]) -> Drawing | None:
        ranked = [
            {"label": str(item.get("label") or "—"), "value": float(item.get("value") or 0)}
            for item in items if float(item.get("value") or 0) > 0
        ]
        ranked.sort(key=lambda item: item["value"], reverse=True)
        if not ranked:
            return None
        if len(ranked) > 7:
            ranked = ranked[:6] + [{
                "label": "Прочие расходы",
                "value": sum(item["value"] for item in ranked[6:]),
            }]
        width, row_h = 500, 20
        height = 18 + row_h * len(ranked)
        drawing = Drawing(width, height)
        maximum = max(item["value"] for item in ranked) or 1.0
        label_width, bar_width = 174, 240
        for index, item in enumerate(ranked):
            y = height - 18 - index * row_h
            label = item["label"]
            if len(label) > 31:
                label = label[:29] + "…"
            drawing.add(String(
                0, y, label, fontName=regular, fontSize=7.5,
                fillColor=colors.HexColor("#333333"),
            ))
            drawing.add(Rect(
                label_width, y - 2,
                max(1.0, bar_width * item["value"] / maximum), 9,
                fillColor=colors.HexColor("#202020" if index == 0 else "#777777"),
                strokeColor=None,
            ))
            drawing.add(String(
                width, y, _pdf_num(item["value"] / 1_000_000_000, 2),
                fontName=bold, fontSize=7.5, textAnchor="end",
                fillColor=colors.HexColor("#222222"),
            ))
        drawing.add(String(
            width, height - 7, "млрд ₽", fontName=regular, fontSize=6.5,
            textAnchor="end", fillColor=colors.HexColor("#777777"),
        ))
        return drawing

    def line_chart(
        rows: list[dict[str, Any]],
        series: list[dict[str, Any]],
        unit: str,
        height: float = 132,
    ) -> Drawing | None:
        if not rows:
            return None
        width = 500
        left, right, bottom, top = 42, 8, 22, 22
        plot_w, plot_h = width - left - right, height - bottom - top

        values: list[float] = []
        for row in rows:
            for spec in series:
                active = spec.get("active")
                if active and not active(row):
                    continue
                values.append(float(row.get(spec["key"], 0.0) or 0.0) * float(spec.get("factor", 1.0)))
        maximum = max(values or [0.0])
        if maximum <= 0:
            return None
        maximum *= 1.08

        drawing = Drawing(width, height)
        x_at = lambda index: left + (plot_w * index / max(len(rows) - 1, 1))
        y_at = lambda value: bottom + plot_h * max(0.0, value) / maximum

        for tick in range(5):
            value = maximum * tick / 4
            y = y_at(value)
            drawing.add(Line(left, y, width - right, y, strokeColor=colors.HexColor("#E2E2E2"), strokeWidth=0.5))
            drawing.add(String(
                left - 5, y - 2, _pdf_num(value, 1), fontName=regular,
                fontSize=6.5, textAnchor="end", fillColor=colors.HexColor("#777777"),
            ))

        legend_x = left
        for spec in series:
            color = colors.HexColor(spec["color"])
            drawing.add(Line(legend_x, height - 8, legend_x + 13, height - 8, strokeColor=color, strokeWidth=2.2))
            drawing.add(String(
                legend_x + 17, height - 11, spec["label"], fontName=regular,
                fontSize=6.8, fillColor=colors.HexColor("#444444"),
            ))
            legend_x += 17 + min(105, 4.6 * len(spec["label"]))
        drawing.add(String(
            width - right, height - 11, unit, fontName=regular, fontSize=6.5,
            textAnchor="end", fillColor=colors.HexColor("#777777"),
        ))

        for spec in series:
            color = colors.HexColor(spec["color"])
            segments: list[list[tuple[float, float]]] = []
            current: list[tuple[float, float]] = []
            for index, row in enumerate(rows):
                active = spec.get("active")
                if active and not active(row):
                    if current:
                        segments.append(current)
                        current = []
                    continue
                value = float(row.get(spec["key"], 0.0) or 0.0) * float(spec.get("factor", 1.0))
                current.append((x_at(index), y_at(value)))
            if current:
                segments.append(current)
            for points in segments:
                if len(points) >= 2:
                    drawing.add(PolyLine(points, strokeColor=color, strokeWidth=2.0, fillColor=None))
                elif points:
                    drawing.add(Circle(points[0][0], points[0][1], 1.7, fillColor=color, strokeColor=None))

        marker_indexes = sorted(set([0, len(rows) // 2, len(rows) - 1]))
        for index in marker_indexes:
            drawing.add(String(
                x_at(index), 5, chart_month(rows[index].get("month")),
                fontName=regular, fontSize=6.4, textAnchor="middle",
                fillColor=colors.HexColor("#777777"),
            ))
        return drawing

    def sales_bar_chart(rows: list[dict[str, Any]], height: float = 108,
                        key: str = "sales", factor: float = 1 / 1_000_000_000,
                        unit_label: str = "млрд ₽/мес.", digits: int = 1) -> Drawing | None:
        if not rows:
            return None
        values = [max(0.0, float(row.get(key, 0.0) or 0.0) * factor) for row in rows]
        maximum = max(values or [0.0])
        if maximum <= 0:
            return None
        width = 500
        left, right, bottom, top = 42, 8, 21, 12
        plot_w, plot_h = width - left - right, height - bottom - top
        maximum *= 1.08
        drawing = Drawing(width, height)
        for tick in range(4):
            value = maximum * tick / 3
            y = bottom + plot_h * value / maximum
            drawing.add(Line(left, y, width - right, y, strokeColor=colors.HexColor("#E5E5E5"), strokeWidth=0.5))
            drawing.add(String(
                left - 5, y - 2, _pdf_num(value, digits), fontName=regular,
                fontSize=6.5, textAnchor="end", fillColor=colors.HexColor("#777777"),
            ))
        slot = plot_w / max(len(rows), 1)
        bar_width = max(1.0, slot * 0.72)
        for index, value in enumerate(values):
            if value <= 0:
                continue
            x = left + index * slot + (slot - bar_width) / 2
            drawing.add(Rect(
                x, bottom, bar_width, plot_h * value / maximum,
                fillColor=colors.HexColor("#202020"), strokeColor=None,
            ))
        drawing.add(String(
            width - right, height - 8, unit_label, fontName=regular,
            fontSize=6.5, textAnchor="end", fillColor=colors.HexColor("#777777"),
        ))
        for index in sorted(set([0, len(rows) // 2, len(rows) - 1])):
            x = left + (index + 0.5) * slot
            drawing.add(String(
                x, 4, chart_month(rows[index].get("month")),
                fontName=regular, fontSize=6.4, textAnchor="middle",
                fillColor=colors.HexColor("#777777"),
            ))
        return drawing

    def gantt_drawings(items: list[dict[str, Any]], chunk_size: int = 18) -> list[Drawing]:
        """Build a real calendar Gantt for the PDF report.

        Bars are positioned by actual project dates. Milestones are diamonds.
        Multi-phase projects keep separate event rows and use phase colours.
        Long calendars are split into several repeated-axis drawings.
        """
        prepared: list[dict[str, Any]] = []
        for raw in items:
            try:
                start = d(raw.get("start"))
                end = d(raw.get("end") or raw.get("start"))
            except Exception:
                continue
            if end < start:
                start, end = end, start
            item = dict(raw)
            item["_start"] = start
            item["_end"] = end
            prepared.append(item)
        if not prepared:
            return []

        first = min(item["_start"] for item in prepared)
        last = max(item["_end"] for item in prepared)
        q_month = ((first.month - 1) // 3) * 3 + 1
        horizon_start = date(first.year, q_month, 1)
        last_q_month = ((last.month - 1) // 3) * 3 + 1
        horizon_end = add_months(date(last.year, last_q_month, 1), 3)
        total_days = max(1, (horizon_end - horizon_start).days)

        width = 500.0
        label_width = 148.0
        track_x = label_width
        track_width = width - label_width
        axis_height = 36.0
        row_height = 19.0
        phase_palette = ["#171717", "#A35D00", "#2D6A4F", "#4F6D7A", "#7A5C61"]
        group_palette = {
            "Финансирование": "#4B4B4B",
            "Продажи": "#7B7B7B",
            "Социальная нагрузка": "#A0A0A0",
            "Строительство": "#202020",
            "Подготовка": "#666666",
            "Ключевые вехи": "#111111",
        }

        def x_at(value: date) -> float:
            ratio = (value - horizon_start).days / total_days
            return track_x + track_width * max(0.0, min(1.0, ratio))

        chunks = [prepared[i:i + chunk_size] for i in range(0, len(prepared), chunk_size)]
        drawings: list[Drawing] = []
        for chunk in chunks:
            rows: list[tuple[str, Any]] = []
            previous_group = None
            for item in chunk:
                group = str(item.get("group") or "Прочее")
                if group != previous_group:
                    rows.append(("group", group))
                    previous_group = group
                rows.append(("event", item))

            height = axis_height + row_height * len(rows) + 4.0
            drawing = Drawing(width, height)
            body_top = height - axis_height

            drawing.add(Rect(0, body_top, width, axis_height, fillColor=colors.HexColor("#F6F6F4"), strokeColor=None))
            drawing.add(Line(label_width, 0, label_width, height, strokeColor=colors.HexColor("#CFCFCF"), strokeWidth=0.6))
            drawing.add(String(4, height - 13, "Этап / событие", fontName=bold, fontSize=7.4, fillColor=colors.HexColor("#222222")))

            quarter = horizon_start
            while quarter < horizon_end:
                next_quarter = add_months(quarter, 3)
                x = x_at(quarter)
                x_next = x_at(next_quarter)
                drawing.add(Line(x, 0, x, body_top, strokeColor=colors.HexColor("#DDDDDD"), strokeWidth=0.45))
                drawing.add(String((x + x_next) / 2, height - 29, f"Q{((quarter.month - 1) // 3) + 1}", fontName=regular, fontSize=6.2, textAnchor="middle", fillColor=colors.HexColor("#666666")))
                quarter = next_quarter
            drawing.add(Line(x_at(horizon_end), 0, x_at(horizon_end), body_top, strokeColor=colors.HexColor("#DDDDDD"), strokeWidth=0.45))

            for year in range(horizon_start.year, horizon_end.year + 1):
                ys = max(horizon_start, date(year, 1, 1))
                ye = min(horizon_end, date(year + 1, 1, 1))
                if ye <= ys:
                    continue
                x1, x2 = x_at(ys), x_at(ye)
                drawing.add(String((x1 + x2) / 2, height - 12, str(year), fontName=bold, fontSize=7.0, textAnchor="middle", fillColor=colors.HexColor("#333333")))
                drawing.add(Line(x1, 0, x1, height, strokeColor=colors.HexColor("#B9B9B9"), strokeWidth=0.75))

            for row_index, (kind, value) in enumerate(rows):
                y = body_top - (row_index + 1) * row_height
                drawing.add(Line(0, y, width, y, strokeColor=colors.HexColor("#E4E4E4"), strokeWidth=0.4))
                if kind == "group":
                    drawing.add(Rect(0, y, width, row_height, fillColor=colors.HexColor("#F1F1EF"), strokeColor=None))
                    drawing.add(String(4, y + 6, str(value).upper(), fontName=bold, fontSize=6.5, fillColor=colors.HexColor("#666666")))
                    continue

                item = value
                label = str(item.get("label") or "—")
                phase_name = str(item.get("phase_name") or "").strip()
                if phase_name and phase_name.lower() not in label.lower():
                    label = f"{phase_name} · {label}"
                if len(label) > 34:
                    label = label[:32] + "…"
                start = item["_start"]
                end = item["_end"]
                drawing.add(String(4, y + 9, label, fontName=regular, fontSize=6.7, fillColor=colors.HexColor("#222222")))
                date_label = start.strftime("%m.%Y") if start == end else f"{start.strftime('%m.%Y')}—{end.strftime('%m.%Y')}"
                drawing.add(String(4, y + 2.3, date_label, fontName=regular, fontSize=5.4, fillColor=colors.HexColor("#777777")))

                phase_index = int(item.get("phase_index") or 0)
                colour = phase_palette[min(max(phase_index - 1, 0), len(phase_palette) - 1)] if phase_index else group_palette.get(str(item.get("group") or ""), "#333333")
                fill = colors.HexColor(colour)
                x1 = x_at(start)
                x2 = x_at(end + timedelta(days=1))
                centre_y = y + row_height / 2
                milestone = str(item.get("kind") or "") == "milestone" or start == end
                if milestone:
                    size = 4.1
                    drawing.add(Polygon([x1, centre_y + size, x1 + size, centre_y, x1, centre_y - size, x1 - size, centre_y], fillColor=fill, strokeColor=None))
                else:
                    drawing.add(Rect(x1, centre_y - 4.0, max(2.2, x2 - x1), 8.0, fillColor=fill, strokeColor=None))

            drawing.add(Line(0, 0, width, 0, strokeColor=colors.HexColor("#CFCFCF"), strokeWidth=0.6))
            drawings.append(drawing)
        return drawings

    story=[P("DevelopAid",h1),P("Инвестиционный отчёт по девелоперскому проекту",h2),P(title_scope,ParagraphStyle("scope",parent=h2,fontSize=11,textColor=colors.HexColor('#555555')))]
    meta=[["Дата расчёта",date.today().strftime("%d.%m.%Y")],["Источник ТЭП",source_label],[class_title,class_label],["Сценарий",scenario_label]]
    # Класс жилья у проекта без жилья ничего не значит (`report_layout.housing`).
    if not (report.get("layout") or {}).get("housing", True):
        meta=[row for row in meta if row[0]!="Класс жилья"]
    # Один расчёт — один идентификатор: у пары «PDF + книга» из одного ответа
    # бота он совпадает, и сверка начинается с него, а не со спора о версиях.
    meta.append(["Идентификатор расчёта",
                 f"{_calculation_fingerprint(inputs, payload.get('tep'), payload.get('phasing'))}"
                 f" · DevelopAid {VERSION}"])
    if cads: meta.append(["Кадастровые номера",", ".join(str(x) for x in cads)])
    parity_problems = [str(item) for item in (payload.get("parity_problems") or [])]
    story += [Spacer(1,4*mm),table(meta,[45*mm,125*mm],header=False),Spacer(1,5*mm)]
    if parity_problems:
        story.append(P(
            "<b>Расчёт в окне разошёлся с расчётом на сервере.</b> В отчёт взяты "
            "числа сервера: " + "; ".join(parity_problems[:4])
            + ". Чаще всего это старая страница в браузере — обновите её.",
            ParagraphStyle("parity", parent=small, fontSize=8.0,
                           textColor=colors.HexColor("#A35D00"))))
    # Реализуемость посадки идёт ПЕРЕД финансовым выводом (архитектура,
    # раздел «Места в интерфейсе»): сначала что мешает строить, потом деньги.
    # Отчёт не имеет права падать из-за внешнего сервиса: отказ называется
    # по каждому участку, а не прячется пропуском раздела. Проверяются все
    # участки проекта, без предела (#655).
    screening_numbers = _project_cadastral_numbers(inputs)
    screening = None
    screening_failure = ""
    if screening_numbers:
        try:
            screening = land_screening(cad=",".join(screening_numbers), limit=0)
        except Exception as exc:
            screening_failure = _land_text(getattr(exc, "detail", "") or str(exc)) or type(exc).__name__
            logging.warning("PDF: скрининг участков не выполнен: %s", screening_failure)
    if screening_numbers:
        verdict = (screening or {}).get("verdict") or {}
        story.append(_PdfSection("screening"))
        story.append(P("Реализуемость посадки", h2))
        headline = (verdict.get("headline", "") if screening is not None
                    else "Скрининг не выполнен: источник ограничений не ответил")
        story.append(P(headline, ParagraphStyle(
            "screening_head", parent=normal, fontName=bold, fontSize=9.5)))
        rows = _pdf_screening_rows(screening_numbers, screening, screening_failure)
        missing = len({r[0] for r in rows if r[1] == _PDF_NOT_RECEIVED})
        story.append(P(
            f"Проверено участков: {len(screening_numbers) - missing} из {len(screening_numbers)}"
            + (f"; по {missing} — {_PDF_NOT_RECEIVED}, ограничения по ним неизвестны."
               if missing else "."), small))
        story.append(table([["Участок", "Ограничение", "Влияние", "Основание"]] + rows,
                           [40*mm, 50*mm, 48*mm, 32*mm]))
        if verdict.get("free_pct") is not None:
            story.append(P(
                f"Свободно от ограничений ~{_pdf_num(verdict['free_pct'], 0)}% площади участка "
                "(оценка наложением границ зон на контур ЕГРН, точность порядка процента).",
                small))
        if verdict.get("disclaimer"):
            story.append(P(verdict.get("disclaimer", ""), small))
        story.append(Spacer(1, 4*mm))
    story.append(_PdfSection("summary"));story.append(P("Ключевая экономика",h2))
    # Прибыль при непогашенном долге — бумажная: для инвестора проект
    # дефолтный, а не прибыльный (решение владельца, 27.08.2026), и строка
    # прибыли обязана говорить это сама, а не полагаться на вывод ниже.
    _carried_out=float(financing.get('debt_carried_out') or 0)
    # Три разных исхода, и оговорка у каждого своя. Средний прежде молчал:
    # долг не погашен в РВЭ, но остаточные продажи закрыли его к концу
    # горизонта — и прибыль печаталась голым числом, хотя держится она на
    # согласии банка, которого в модели не спрашивали.
    _default_note=(" — бумажная: долг не погашен" if float(financing.get('ending_pf') or 0)>500_000
                   else " — условная: в модели дефолт, долг закрыт продажами "
                        "следующих периодов" if str(financing.get('default_date') or '').strip()
                   else " — долг очереди принят следующей" if _carried_out>500_000 else "")
    kpis=[
        *_pdf_entry_cost_rows(result, expense_structure),
        ["Выручка",_pdf_money(summary.get('revenue'))],["Расходы всего",_pdf_money(summary.get('total_expenses'))],["EBITDA",_pdf_money(summary.get('ebitda'))],["Чистая прибыль",_pdf_money(summary.get('net_profit'))+_default_note],["Маржинальность",_pdf_pct(summary.get('margin'))],["LLCR",_pdf_num(summary.get('llcr'),2)+"x"],["Расчётный БРИДЖ",_pdf_money(financing.get('calculated_bridge'))],["Фактический пик БРИДЖ",_pdf_money(financing.get('actual_bridge'))],["Пиковая (непокрытая эскроу) задолженность ПФ",_pdf_money(financing.get('pf_uncovered_peak'))],["Проценты и комиссии",_pdf_money(financing.get('interest_and_fees'))],
    ]
    # Остаток ПФ на конец проекта — это несостоявшееся погашение, а не деталь
    # финансирования: без него отчёт выглядел безупречно при непогашенном долге.
    _ending_pf=float(financing.get('ending_pf') or 0)
    _rve_pf_shortfall=float(financing.get('rve_pf_shortfall') or 0)
    if _rve_pf_shortfall>500_000:
        kpis.append(["Остаток ПФ после раскрытия эскроу в РВЭ",
                     _pdf_money(_rve_pf_shortfall)])
    # Непокрытая потребность — у числа, а не только в плашке вердикта: плашку
    # пролистывают, таблицу показателей нет. Требуемый лимит печатается рядом
    # с одобренным — «не хватает 16 млрд» без обеих баз не проверить.
    _pf_gap=float(financing.get('pf_shortfall') or 0)
    if _pf_gap>500_000:
        kpis.append(["Требуемый лимит ПФ",_pdf_money(financing.get('pf_limit_required'))])
        kpis.append(["Одобренный лимит ПФ",_pdf_money(financing.get('pf_limit_approved'))])
        kpis.append(["Непокрытая потребность в ПФ (финансирование не закрыто)",
                     _pdf_money(_pf_gap)])
    if _ending_pf>500_000:
        kpis.append(["Непогашенный долг ПФ на конец проекта",_pdf_money(_ending_pf)])
    elif _carried_out>500_000:
        kpis.append(["Долг передан в ПФ следующей очереди",_pdf_money(_carried_out)])
    # Нежилой проект без ДДУ: БРИДЖа, ПФ и LLCR у него нет — строки банка
    # уходят, а на их место встают деньги объектов (`report.layout`).
    _layout = report.get("layout") or {}
    if _layout and not _layout.get("project_finance", True):
        _bank = {"LLCR", "Расчётный БРИДЖ", "Фактический пик БРИДЖ",
                 "Пиковая (непокрытая эскроу) задолженность ПФ"}
        kpis = [row for row in kpis if row[0] not in _bank]
    kpis += [[str(t.get("label") or ""), _pdf_nonres_value(t)]
             for t in _layout.get("nonres_tiles") or []]
    story.append(table([["Показатель","Значение"]]+kpis,[112*mm,58*mm]))
    story.append(_PdfSection("vri"))
    # Основание платы за ВРИ — тремя множителями формулы ГлавАПУ. Расхождение
    # платы между двумя расчётами одного участка всегда сидит в одном из них
    # (чаще в базовой стоимости — город индексирует её поквартально), и без
    # расшифровки его приходилось искать перепиской со скриншотами.
    _vri_src = (inputs.get("_glavapu_import") or {}).get("normalized") or {}
    _vri_spp = float(_vri_src.get("spp_total_sqm") or 0)
    _vri_rent = _vri_src.get("rent_coefficient")
    _vri_base = _vri_src.get("vri_base_cost_rub")
    if _vri_spp > 0 and _vri_rent and _vri_base:
        story.append(P(
            f"Плата за смену ВРИ — по формуле ГлавАПУ: СПП {_pdf_num(_vri_spp, 0)} м²"
            f" × коэффициент аренды {_pdf_num(_vri_rent, 4)}"
            f" × базовая стоимость {_pdf_num(_vri_base, 0)} ₽/м² × 1,8964."
            " Базовую стоимость город индексирует поквартально — расчёты разных"
            " дат по одному участку могут отличаться на величину индексации.",
            small))
    story.append(_PdfSection("summary"))
    # Удельная экономика проекта была только в книге и на странице, а в отчёте
    # её не было вовсе: решение принимают по рублю на метр, а не по миллиардам.
    # Обе базы обязаны стоять рядом — на ГНС считают стройку, на продаваемую
    # сравнивают с ценой продажи, и подмена одной другой ошибается вдвое.
    unit_economics = report.get("unit_economics") or []
    if unit_economics:
        # Каждая строка — на свою базу, и база названа в строке (решение 4
        # ревизии книги); вторая колонка — на продаваемую, для сравнения с
        # ценой. У строк, чья база и есть продаваемая, она не повторяется.
        ue_rows = [["Показатель", "Всего", "На м² своей базы", "База",
                    "тыс ₽/м² продаваемой"]]
        for item in unit_economics:
            ue_rows.append([
                str(item.get("label") or "—"),
                _pdf_money(item.get("total")),
                _pdf_unit_num(item.get("per_base_th"), 1),
                _pdf_unit_base(item),
                _pdf_unit_saleable(item, 1),
            ])
        story.append(KeepTogether([
            P("Удельная экономика проекта", h2),
            table(ue_rows, [40*mm, 32*mm, 24*mm, 50*mm, 24*mm], font_size=7.2),
            # База — НАЗЕМНАЯ площадь: подземная в ГНС не входит, у неё своя
            # экономика — свой метр стройки и продукт, продаваемый местами
            # (решение владельца, 04.09.2026). Строительный объём стоит рядом
            # своим числом: на нём считаются общие статьи, и без него удельный
            # показатель читается как посчитанный по всему объёму. Термин наш:
            # город считает нагрузки от суммарной поэтажной площади.
            P(_pdf_unit_bases_note(summary) + " "
              "Общие статьи (ИРД, проектирование, подготовка, "
              f"сети, сдача, содержание) считаются от {_project_articles_term(tep_report).genitive} — "
              f"{_pdf_num(_project_articles_sqm(tep_report), 0)} м²: "
              + ("квартиры, коммерция 1 этажа, подземный паркинг и кладовые. "
                 if _project_articles_term(tep_report) is CORE_TOTAL_AREA
                 else "здания объектов и их подземные гаражи. ") +
              f"База продаваемой — {_pdf_num(summary.get('monetizable_saleable_sqm'), 0)} м² "
              "монетизируемой площади (паркинг и кладовые продаются штуками и в неё "
              "не входят). Показатели на метр — термины финансовой модели DevelopAid, "
              "а не градостроительной методики: город считает нагрузки от суммарной "
              "поэтажной площади.", small),
        ]))
    story.append(_PdfSection("expenses_detail"))
    # Удельные расходы стройки — детализация структуры расходов, а не свод:
    # по ним читается себестоимость, но читать её раньше ТЭП бессмысленно.
    construction_costs = report.get("construction_costs") or []
    if construction_costs:
        # Вторая база в заголовке обязательна: без неё 23 тыс ₽/м² подземной
        # части читались как ставка на подземный метр (она — 190, во вводных).
        # СМР — на ту часть, на которую начислено; прочие статьи — на
        # суммарную площадь в ГНС. База — в строке, из движка.
        cc_rows = [["Статья", "млн ₽", "На м² своей базы", "База",
                    "тыс ₽/м² продаваемой"]]
        for item in construction_costs:
            cc_rows.append([
                str(item.get("label") or "—"),
                _pdf_num(float(item.get("value") or 0) / 1e6, 1),
                _pdf_unit_num(item.get("per_base_th"), 2),
                _pdf_unit_base(item),
                _pdf_unit_saleable(item, 2),
            ])
        story.append(KeepTogether([
            P("Удельные расходы строительства", h2),
            table(cc_rows, [52*mm, 22*mm, 24*mm, 48*mm, 24*mm], font_size=7.2),
            P("Внутренние инженерные сети входят в СМР соответствующей части.", small),
        ]))
    story.append(_PdfSection("summary"))
    purchase_assessment = _purchase_feasibility(
        inputs.get("purchase_price_mln"),
        float(summary.get("net_profit") or 0) / 1_000_000,
        summary.get("llcr"),
        max(
            float(financing.get("calculated_bridge") or 0),
            float(financing.get("pf_uncovered_peak") or 0),
        ),
        float(financing.get("ending_pf") or 0) / 1_000_000,
        financing.get("default_date"),
        float(financing.get("pf_shortfall") or 0) / 1_000_000,
        financing.get("pf_shortfall_month"),
        _layout_dscr(report.get("layout")),
        _layout_no_debt_cover(report.get("layout")),
    )
    story.append(KeepTogether([
        P("Оценка целесообразности покупки", h2),
        table([
            ["Вывод", purchase_assessment["title"]],
            ["Основание", purchase_assessment["text"]],
        ], [45*mm, 125*mm], header=False, font_size=8.0),
    ]))
    story.append(_PdfSection("tep"));story.append(P("ТЭП",h2))
    # Переданные метры строятся и не продаются: в продаваемой их нет.
    # В книге колонка переданного была с самого начала, а отчёт о
    # переданном молчал — и читался так, будто продано всё построенное
    # (владелец, 10.09.2026). Колонка появляется вместе с числом: постоянный
    # столбец нулей — шум, а не полнота.
    # Строка продукта, которого нет в проекте, не печатается — то же
    # правило, что у ТЭП тизера (`row_listed`).
    rows_data = [row for row in (tep_report.get('rows') or []) if row_listed(row)]
    total=tep_report.get('total') or {}
    given = sum(float(row.get('transfer') or 0) for row in rows_data)
    # Итог количества — разбор по мере счёта, а не сумма: квартиры,
    # машино-места и места детского сада складывались в число, не значащее
    # ничего. Строка продукта тоже называет свою меру: «250 шт.» у ДОО читалось
    # как штуки, а это места.
    # Итог — мера на строку: через « · » в одну строку он разваливался в
    # узкой колонке на семь обрывков.
    def _count(row):
        measure = tep_count_measure(row.get('key'))
        return _pdf_count_text(row.get('units'), measure) if measure else '—'
    _counts = '\n'.join(_pdf_count_text(value, measure)
                        for measure, value in (total.get('units_by_measure') or {}).items()
                        if value) or '—'
    # Свой паркинг отдельно стоящего объекта — продукт, и в ТЭП он стоит
    # подстрокой с местами, как на экране: полем на строке объекта его в
    # печати не было вовсе. Метры гаража названы в подписи — в колонке ГНС
    # они читались бы наземными. В итог эти места входят через разбор по мере
    # счёта: там они в графе «м/м», отдельно складывать их нечего.
    def _park_label(row):
        under=float(row.get('parking_under_units') or 0)
        over=float(row.get('parking_over_units') or 0)
        sold=float(row.get('parking_saleable_units') or 0)
        where=[]
        if under: where.append("подземных "+_pdf_num(under,0)
                               +(f" (гараж {_pdf_num(row.get('under_gns'),0)} м²)"
                                 if float(row.get('under_gns') or 0) else ""))
        if over: where.append("на первых этажах "+_pdf_num(over,0)+" (в ГНС здания)")
        guest=float(row.get('parking_guest_units') or 0)
        tail=("продаётся "+_pdf_num(sold,0)+(", гостевых "+_pdf_num(guest,0) if guest else "")
              if sold else "не продаются — обеспечивают посетителей")
        return "   в т.ч. паркинг объекта, мест: "+"; ".join(where+[tail])
    def _park_count(row):
        return _pdf_count_text(row.get('parking_units'), COUNT_PARKING)

    def _tep_widths(rows, middle):
        """Колонка «Кол-во» — по своему содержимому, остаток — названию."""
        count_w = _pdf_count_column_width([row[-1] for row in rows[1:]], regular,
                                          normal.fontSize, 5, 22*mm)
        return [170*mm - sum(middle) - count_w, *middle, count_w]
    if given > 0:
        tep_rows=[["Продукт",TOTAL_AREA.with_unit(),"Продаваемая, м²",
                   f"{TRANSFER_WORD}, м²","Кол-во"]]
        for row in rows_data:
            tep_rows.append([row.get('label') or row.get('key') or '—',
                             _pdf_num(row.get('gns'),0),_pdf_num(row.get('saleable'),0),
                             _pdf_num(row.get('transfer'),0),_count(row)])
            if float(row.get('parking_units') or 0):
                tep_rows.append([_park_label(row),"—","—","—",_park_count(row)])
        tep_rows.append(["Итого",_pdf_num(total.get('gns'),0),_pdf_num(total.get('saleable'),0),
                         _pdf_num(given,0),_counts])
        story.append(table(tep_rows,_tep_widths(tep_rows,[28*mm,30*mm,30*mm])))
        story.append(P("Переданные метры строятся, но не продаются: в продаваемой "
                       f"площади их нет. {TRANSFER_RECIPIENT_NOTE.capitalize()}.",
                       small))
    else:
        tep_rows=[["Продукт",TOTAL_AREA.with_unit(),"Продаваемая, м²","Кол-во"]]
        for row in rows_data:
            tep_rows.append([row.get('label') or row.get('key') or '—',_pdf_num(row.get('gns'),0),_pdf_num(row.get('saleable'),0),_count(row)])
            if float(row.get('parking_units') or 0):
                tep_rows.append([_park_label(row),"—","—",_park_count(row)])
        tep_rows.append(["Итого",_pdf_num(total.get('gns'),0),_pdf_num(total.get('saleable'),0),_counts])
        story.append(table(tep_rows,_tep_widths(tep_rows,[32*mm,36*mm])))
    # Обеспеченность — готовый ответ расчёта (`parking_provision`), а не
    # деление здесь: страница, тизер, Платон и книга печатают то же число.
    _provision = ((result.get("parking") or {}).get("provision") or {}).get("label")
    if _provision:
        story.append(P(f"Обеспеченность парковкой: {_provision} — все машино-места проекта "
                       "на всю нормативную потребность: жители, коммерция, отдельные "
                       "объекты и соцобъекты.", small))

    # Очередность меняет проект целиком — сроки, инфляцию затрат, стартовые цены
    # и нагрузку по финансированию, — а отчёт о ней молчал: сводные цифры были,
    # а из чего они сложились, увидеть было негде.
    comparison = result.get("comparison") or []
    if len(comparison) > 1:
        story.append(_PdfSection("phases"));story.append(P("Очереди проекта",h2))
        phase_cfg = {str(item.get("name") or ""): item for item in
                     ((payload.get("phasing") or {}).get("phases") or [])}
        params=[["Очередь","Сдвиг старта, мес.","Строительство, мес.","Инфляция затрат","Индексация цены"]]
        for item in comparison:
            cfg = phase_cfg.get(str(item.get("name") or "")) or {}
            params.append([
                str(item.get("name") or "—"),
                _pdf_num(cfg.get("start_offset_months"),0) if cfg else "—",
                _pdf_num(cfg.get("construction_months"),0) if cfg else "—",
                _pdf_num((float(item.get("cost_inflation_factor") or 1)-1)*100,1)+"%",
                _pdf_num((float(item.get("sales_price_inflation_factor") or 1)-1)*100,1)+"%",
            ])
        story.append(table(params,[30*mm,35*mm,38*mm,34*mm,33*mm],font_size=7.4))
        story.append(P("Сравнение очередей",h2))
        # Та же таблица, что на странице, и из того же места —
        # `phase_comparison_table`: состав, порядок блоков и числа решает
        # движок, PDF только печатает. Прежде отчёт печатал своё сравнение
        # пятью таблицами в своём порядке, и две раскладки одного сравнения
        # расходились (владелец, 27.09.2026: «PDF тоже надо сделать то же»).
        story.append(_phase_comparison_pdf(phase_comparison_table(result), regular, bold, colors))
        story.append(P("Удельные показатели — в тыс. ₽ за м² своего делителя; итог по ним — "
                       "отношение сумм, а не среднее по очередям.", small))
        # Причина, по которой долг сменил очередь или остался на своей: без неё
        # обнулённый долг первой очереди рядом с выросшим долгом второй
        # читается как ошибка расчёта. Раздел «Непогашенный долг и перенос
        # между очередями» стал строками блока «Финансирование»; здесь —
        # объяснение к ним.
        _carry = result.get("debt_carry") if isinstance(result.get("debt_carry"), dict) else {}
        _has_debt = any(
            float(i.get("ending_pf") or 0) > 500_000
            or float(i.get("debt_carried_out") or 0) > 500_000
            or float(i.get("carried_debt_in") or 0) > 500_000
            for i in comparison)
        if _carry.get("note"):
            story.append(P(str(_carry["note"]),small))
        elif _has_debt:
            story.append(P(
                "Перенос долга между очередями выключен: непогашенный остаток "
                "остаётся на очереди, которая его набрала, и означает дефолт по "
                "её линии. Итог по проекту при этом складывается из очередей.",small))
        phase_financing = result.get("phase_financing") or {}
        if phase_financing.get("rows"):
            story.append(P(
                ("Единый денежный поток проекта включён. " if phase_financing.get("enabled")
                 else "Независимое финансирование очередей включено. ")
                + "Свободный cash учитывается только после обслуживания долга более ранней "
                  "очереди; эскроу, будущая прибыль и банковские лимиты не используются.", small))
        # Кассовая и аллоцированная прибыль очереди — разные показатели с
        # одинаковой суммой по проекту; без словаря их сравнивали лоб в лоб
        # с книгой и читали методику как расхождение моделей.
        allocated_parts = [
            f"{item.get('name')}: {_pdf_money(item.get('allocated_net_profit'))}"
            for item in comparison if item.get("allocated_net_profit") is not None]
        if allocated_parts:
            story.append(P(
                "Чистая прибыль очередей — кассовая, как в CF-листах Excel-книги: общие "
                "расходы (покупка, ВРИ, соцнагрузка) стоят в очереди их оплаты. "
                "Аллоцированная прибыль разносит их экономически: "
                + "; ".join(allocated_parts)
                + ". Сумма по проекту в обеих раскладках одна.", small))

    # Раздел появляется только если чувствительность считали на вкладке.
    # Гнать полсотни расчётов внутри сборки PDF ради раздела, который никто не
    # просил, незачем — а сборка отчёта и так идёт следом за карточкой.
    sensitivity = payload.get("sensitivity") if isinstance(payload.get("sensitivity"), dict) else None
    if sensitivity and (sensitivity.get("items") or []):
        base = sensitivity.get("base") or {}
        digits = int(base.get("digits") or 2)
        rows = list(sensitivity["items"])[:14]
        story.append(_PdfSection("sensitivity"))
        story.append(P("Чувствительность проекта",h2))
        story.append(P(
            f"Показатель: {base.get('label') or ''} · база "
            f"{_pdf_num(base.get('value'), digits)} {base.get('unit') or ''} · "
            f"охват: {base.get('scope_label') or ''}"
            + ("" if base.get("project_value") is None else
               f" (не весь проект: у проекта {_pdf_num(base.get('project_value'), digits)} "
               f"{base.get('unit') or ''})")
            + " · отклонение "
            f"{_pdf_num(sensitivity.get('change_pct'), 0)}% и "
            f"{_pdf_num(sensitivity.get('duration_change_months'), 0)} мес. для сроков. "
            "Меняется один параметр за расчёт.", small))
        chart = tornado_chart(rows, float(base.get("value") or 0), digits)
        if chart:
            story.extend([chart, Spacer(1, 3*mm)])
        table_rows=[["Параметр","Ниже","Выше","Размах"]]
        for row in rows:
            table_rows.append([
                str(row.get("label") or "—"),
                _pdf_num(row.get("low_result"), digits),
                _pdf_num(row.get("high_result"), digits),
                _pdf_num(row.get("impact"), digits),
            ])
        story.append(table(table_rows,[92*mm,26*mm,26*mm,26*mm],font_size=7.4))
        for line in (sensitivity.get("verdict") or []):
            story.append(P(str(line), small))

    story.append(_PdfSection("premises"));story.append(P("Цены и основные предпосылки",h2))
    # Класс — то же решение, что у карточки «Ключевые параметры»
    # (`project_class_view`): у гостиницы — звёздность, а не класс жилья.
    _class_dev=project_class_view(inputs)
    premise_rows=[["Параметр","Значение"],[_class_dev["title"],_class_dev["label"]],["Стартовая цена квартир",_pdf_num(inputs.get('apartment_price_th'),0)+" тыс. ₽/м²"],["Стартовая цена коммерции",_pdf_num(inputs.get('commercial_price_th'),0)+" тыс. ₽/м²"],["Цена подземного машино-места",_pdf_num(inputs.get('parking_price_th'),0)+" тыс. ₽/шт."],["СМР наземной части",_pdf_num(inputs.get('main_above_th_per_sqm'),0)+" тыс. ₽/м² наземной части"],["СМР подземной части",_pdf_num(inputs.get('main_under_th_per_sqm'),0)+" тыс. ₽/м² подземной части"],["Наружные инженерные сети, в т.ч. техприсоединение",_pdf_num(inputs.get('utilities_th_per_sqm'),1)+" тыс. ₽/м² "+CORE_TOTAL_AREA.genitive],["Доля продаж до РВЭ",_pdf_num(inputs.get('share_before_rve_pct'),1)+"%"],["Налог на прибыль",_pdf_num(inputs.get('profit_tax_pct'),1)+"%"]]
    # Тип проекта называется только там, где он не тот, что у всех: строка
    # «Жилой / смешанный» в каждом отчёте — постоянная приписка, а такие
    # перестают читаться. Оставшееся от жилья идёт своей строкой, потому что
    # это не предпосылка, а расхождение вводных с объявленным типом.
    # Оставшееся берётся из свода, а не считается здесь заново: второй счёт
    # той же величины однажды разошёлся бы с экраном, и обе строки выглядели
    # бы верными.
    _kind = str(summary.get("project_kind") or "")
    if _kind in PROJECT_KINDS_WITHOUT_HOUSING:
        # Цены и темп проекта принадлежат продуктам МКД: у объекта свой
        # профиль продаж и своя цена места. Напечатанные у нежилого проекта,
        # они читались бы как предпосылки его расчёта.
        _mkd_premises = {"Стартовая цена квартир", "Стартовая цена коммерции",
                         "Цена подземного машино-места", "Доля продаж до РВЭ"}
        if _kind == PROJECT_KIND_HOTEL:
            # Стройку гостиницы считает её ставка (`hotel_cost_th_per_sqm`),
            # а не ставки жилья: СМР дома и сети класса жилья у неё не
            # участвуют, и напечатанные они читались бы её предпосылкой.
            _mkd_premises |= {"СМР наземной части", "СМР подземной части",
                              "Наружные инженерные сети, в т.ч. техприсоединение"}
        premise_rows = [row for row in premise_rows if row[0] not in _mkd_premises]
        # Тип и остаток жилья — строки движка (`project_kind_rows`), те же,
        # что в разделе «Объект и участок» рамки объекта. Остаток назван, но
        # не посчитан (`residential_excluded`).
        premise_rows += [[row["label"], row["value"]] for row in project_kind_rows(summary)]
    story.append(table(premise_rows,[105*mm,65*mm]))
    if _class_dev["rows"]:
        # Ушёл от базы — скажи об этом: молча два отчёта «одного класса»
        # разойдутся, и оба будут выглядеть достоверно.
        # Единица стоит у числа: профиль класса перестал быть только деньгами —
        # норматив площади на человека это м²/чел., и «5 → 8» без единицы
        # читается ставкой. Слово «ставки» по той же причине снято.
        _dev_text="; ".join(
            f"{item['label']} {_pdf_num(item['base'],1)} → {_pdf_num(item['actual'],1)}"
            + (f" {item['unit']}" if item.get("unit") else "")
            for item in _class_dev["rows"])
        story.append(Spacer(1,1.5*mm))
        story.append(P(f"Отличается от базы класса «{_class_dev['label']}»: {_dev_text}.",
                       ParagraphStyle("class_dev",parent=small,fontSize=8.0,
                                      textColor=colors.HexColor("#a02418"))))
    story.append(_PdfSection("expenses"));story.append(P("Структура расходов",h2))
    expense_chart=expense_bar_chart(expense_structure)
    if expense_chart:
        story.extend([expense_chart,Spacer(1,2*mm)])
    # Рубль на метр — в обеих базах, как во всех удельных отчёта: именно по
    # этим статьям спорят с подрядчиком и с банком, а в долях процента спор
    # не ведут.
    # Все строки — расходы, база у них одна (решение 4 ревизии книги):
    # суммарная площадь в ГНС; подпись — из словаря терминов.
    expense_rows=[["Статья","Сумма","Доля",unit_label(UNIT_BASE_TOTAL).replace("тыс. ","тыс "),"тыс ₽/м² продаваемой"]]
    total_expense=sum(float(item.get('value') or 0) for item in expense_structure) or float(summary.get('total_expenses') or 0)
    for item in expense_structure:
        value=float(item.get('value') or 0)
        if value==0: continue
        # Удельные берутся из расчёта, без запасного счёта на месте. Запасной
        # счёт здесь уже стоил дорого: свод по очередям приходил без удельных,
        # печать досчитывала их сама и выглядела безупречно, а страница
        # показывала нули во всех строках. Одна поверхность прикрывала ошибку
        # другой, и найти её удалось только глазами.
        expense_rows.append([item.get('label') or '—',_pdf_money(value),
                             (_pdf_num(value/total_expense*100,1)+'%') if total_expense else '—',
                             _pdf_unit_num(item.get('per_base_th'),1),
                             _pdf_unit_num(item.get('per_saleable_th'),1)])
        # Отдельно стоящий объект меряется своей площадью, наземный паркинг —
        # своими местами. Числа считает движок; отчёт носят в банк, и
        # расходиться с экраном ему нельзя — подстроки те же.
        # Строки объекта собраны движком — здание и свой гараж порознь, база
        # названа в ячейке, как на экране.
        for line in (l for part in item.get('items') or [] for l in part.get('lines') or []):
            _base=(" "+str(line.get('basis'))) if line.get('basis') else ""
            _gns='—' if line.get('gns_th') is None else _pdf_num(line['gns_th'],1)+_base
            if line.get('per_unit_mln') is not None:
                _sal=_pdf_num(line['per_unit_mln'],2)+" млн ₽/место"
            else:
                _sal='—' if line.get('saleable_th') is None else _pdf_num(line['saleable_th'],1)+_base
            expense_rows.append(["   в т.ч. "+str(line.get('label') or '—'),
                                 _pdf_money(line.get('value') or 0),"—",_gns,_sal])
    expense_rows.append(["Итого расходы",_pdf_money(total_expense),"100,0%" if total_expense else "—",
                         _pdf_unit_num(summary.get('full_cost_per_total_area_th'),1),
                         _pdf_num(summary.get('full_cost_per_saleable_th'),1)])
    story.append(table(expense_rows,[62*mm,32*mm,20*mm,28*mm,28*mm],font_size=7.4))
    _exp_note=next((str(i.get('items_note') or '') for i in expense_structure
                    if i.get('items') and i.get('items_note')),'')
    if _exp_note:
        story.append(P(_exp_note,small))
    # Пустая статья называется и на бумаге: нулевая строка в таблицу не
    # попадает, а отчёт носят в банк — отсутствие благоустройства там читается
    # как «его не будет», а не как «мы его не посчитали». Фраза берётся из
    # свода целиком: второй текст об одной пустоте разошёлся бы с экраном.
    _land_gap=str(summary.get('landscaping_gap') or '')
    if _land_gap:
        story.append(P(_land_gap,ParagraphStyle("land_gap",parent=small,fontSize=8.0,
                                                textColor=colors.HexColor("#a02418"))))
    story.append(_PdfSection("income"));story.append(P("Продажи и продукты",h2))
    product_rows=[["Продукт","Объём","Темп до РВЭ","Стартовая цена","Средняя цена","Выручка"]]
    for item in products:
        # Непродаваемое в таблицу ПРОДАЖ не идёт: соцобъект стоял тут строкой
        # с объёмом «350 м²» и выручкой ноль, хотя 350 — это места. Его метры
        # и мощность названы в таблице ТЭП, где у них своя мера.
        if item.get('sellable') is False or item.get('excluded'): continue
        quantity=float(item.get('quantity') or 0);revenue=float(item.get('revenue') or 0)
        built=float(item.get('built_units') or 0)
        # Паркинг объекта с местами, которые не продаются (ТЦ, ФОК), — тоже
        # строка своего объекта: построено есть, продаётся ноль, как на экране.
        if quantity<=0 and revenue<=0 and built<=0: continue
        unit=item.get('unit') or ''
        pace=item.get('pace_pre')
        volume=_pdf_num(quantity,0)+(' '+unit if unit else '')
        if built>0:
            volume+=f" из {_pdf_num(built,0)} построенных"
        product_rows.append([item.get('label') or '—',volume,
                             (_pdf_num(pace,0)+' '+unit+'/мес') if pace else '—',
                             _pdf_num(item.get('start_price_th'),0)+" тыс. ₽",_pdf_num(item.get('avg_price_th'),0)+" тыс. ₽",_pdf_money(revenue)])
    story.append(table(product_rows,[45*mm,26*mm,28*mm,26*mm,26*mm,29*mm],font_size=7.4))
    # Профиль продаж и лестница цены объекта — под таблицей, своими словами:
    # средняя цена без них не объясняет, откуда взялась.
    for item in products:
        notes = []
        if item.get("sales_profile"):
            notes.append(f"профиль продаж {item['sales_profile']}")
        if item.get("price_ladder"):
            notes.append(f"лестница цены {item['price_ladder']}")
        notes += [str(w) for w in (item.get("schedule_warnings") or [])]
        if notes:
            story.append(P(f"{item.get('label') or '—'}: " + "; ".join(notes) + ".", small))
    # ТЦ и офисы вне ДДУ — таблицей движка (`nonres_report`), той же, что на
    # экране: прямая продажа или аренда с выходом и свой кредит объекта.
    for _nr in report.get("nonres_strategy") or []:
        _nr_rows = [["Нежильё — стратегия реализации: " + str(_nr.get("title") or ""), " "]]
        for _row in _nr.get("rows") or []:
            # Блок «Итог объекта» — заголовком строки, без значения.
            _nr_rows.append([str(_row.get("label") or "").upper()
                             if _row.get("unit") == "section" else str(_row.get("label") or ""),
                             _pdf_nonres_value(_row)])
        story.append(KeepTogether([table(_nr_rows, [112*mm, 58*mm], font_size=7.6)]
                                  + [P(str(w), small) for w in _nr.get("warnings") or []]))
    # Гостиница — таблицей движка (`hotel_report`), той же, что на экране:
    # ключевые показатели и годовой USALI. Незаполненная — названа, не нулями.
    _hotel = report.get("hotel")
    if _hotel:
        story.append(P("Гостиница — эксплуатация (USALI)", h2))
        if not _hotel.get("computed"):
            story.append(P("Гостиница не считается: не заданы "
                           + ", ".join(str(m) for m in _hotel.get("missing") or []) + ".", small))
        else:
            _h_rows = [["Показатель", "Значение"]]
            for _row in _hotel.get("rows") or []:
                _h_rows.append([str(_row.get("label") or ""), _pdf_nonres_value(_row)])
            story.append(table(_h_rows, [112*mm, 58*mm], font_size=7.4))
            for _w in _hotel.get("warnings") or []:
                story.append(P(str(_w), small))
            _usali = _hotel.get("usali") or {}
            _years = list(_usali.get("years") or [])
            # Годы — колонками, по шесть на таблицу: пятнадцать лет на А4 не
            # читаются. Деньги — в млн ₽, как в «Своде» эталонных моделей.
            for _start in range(0, len(_years), 6):
                _span = _years[_start:_start + 6]
                _u_rows = [["USALI, млн ₽"] + [str(y) for y in _span]]
                for _line in _usali.get("rows") or []:
                    _vals = (_line.get("values") or [])[_start:_start + 6]
                    _cells = []
                    for _v in _vals:
                        if _v is None:
                            _cells.append("—")
                        elif _line.get("unit") == "rub":
                            _cells.append(_pdf_num(float(_v) / 1e6, 1))
                        else:
                            _cells.append(_pdf_nonres_value({"unit": _line.get("unit"), "value": _v}))
                    _u_rows.append([str(_line.get("label") or "")] + _cells)
                _w0 = 62*mm
                story.append(table(_u_rows, [_w0] + [(170*mm - _w0) / max(1, len(_span))] * len(_span),
                                   font_size=6.8))
    # Квартиры продаются штуками. «40 квартир в месяц» проверяется отделом
    # продаж и рынком, «2 400 м² в месяц» — нет, а в отчёте был только метр.
    apartment_sales = report.get("apartment_sales") or {}
    if float(apartment_sales.get("units_total") or 0) > 0:
        story.append(KeepTogether([
            P("Темп продаж квартир", h2),
            table([
                ["Показатель", "Значение"],
                ["Квартир в проекте", _pdf_num(apartment_sales.get("units_total"), 0) + " шт."],
                ["Средняя площадь квартиры", _pdf_num(apartment_sales.get("avg_unit_sqm"), 1) + " м²"],
                ["Средняя цена квартиры", _pdf_money(float(apartment_sales.get("avg_unit_price_mln") or 0) * 1e6)],
                ["Темп до РВЭ", _pdf_num(apartment_sales.get("pace_pre_rve_units"), 1) + " кв./мес."],
                ["Средний темп за весь период продаж", _pdf_num(apartment_sales.get("pace_units"), 1) + " кв./мес."],
                ["Пиковый месяц", _pdf_num(apartment_sales.get("peak_units"), 1) + " кв."],
                ["Длительность продаж", _pdf_num(apartment_sales.get("months"), 0) + " мес."],
            ], [112*mm, 58*mm], font_size=7.6),
            P("Штуки пересчитаны из помесячных продаж по средней площади квартиры "
              "из ТЭП: изменится нарезка — изменится и темп.", small),
        ]))
    _financing_start = len(story)
    story.append(_PdfSection("financing"));story.append(P("Финансирование и динамика проекта",h2))
    # Раскрытие эскроу — событие очереди, и у каждой оно своё. На
    # многоочередном проекте подписи «в РВЭ» называли моментом сумму
    # разнесённых во времени событий (владелец, 31.08.2026). Величины те же,
    # но названы итогами; по очередям они стоят в разделе «Очереди проекта».
    _pdf_phased = len(result.get("comparison") or []) > 1
    def _pdf_rve_label(base: str) -> str:
        return f"{base} — всего" if _pdf_phased else f"{base} в РВЭ"
    finance_rows=[["Показатель","Значение"],[("Расчётный БРИДЖ — сумма лимитов очередей" if _pdf_phased else "Расчётный БРИДЖ"),_pdf_money(financing.get('calculated_bridge'))],[("Пик одновременно открытых линий БРИДЖа очередей (тело долга)" if _pdf_phased else "Пиковый фактический БРИДЖ (тело долга)"),_pdf_money(financing.get('actual_bridge'))],["Собственные средства до ПФ",_pdf_money(financing.get('own_funds'))],["Пик БРИДЖ с капитализацией процентов (справочно)",_pdf_money(financing.get('bridge_peak_capitalized') or financing.get('actual_bridge'))],["Пиковая (непокрытая эскроу) задолженность ПФ",_pdf_money(financing.get('pf_uncovered_peak'))],[_pdf_rve_label("Долг ПФ перед раскрытием"),_pdf_money(financing.get('rve_pf_before_repayment'))],[_pdf_rve_label("Раскрытый эскроу"),_pdf_money(financing.get('rve_escrow_release'))],["Из него на погашение ПФ",_pdf_money(financing.get('rve_pf_repayment'))],[_pdf_rve_label("Не покрыто эскроу при раскрытии"),_pdf_money(financing.get('rve_pf_shortfall'))],[("Лимит ПФ — сумма по очередям" if _pdf_phased else "Лимит ПФ"),_pdf_money(financing.get('pf_limit'))],*([["Общий лимит ПФ по генеральным условиям — ожидание, потолком очередей не служит",_pdf_money(financing.get('pf_limit_general'))]] if (_pdf_phased and float(financing.get('pf_limit_general') or 0)>500_000) else []),["Текущая ключевая ставка",_pdf_pct(financing.get('current_key_rate'))],["Спред БРИДЖ",_pdf_pct(financing.get('bridge_spread'))],["Ставка БРИДЖ на текущей ключевой",_pdf_pct(financing.get('current_bridge_rate'))],["Средняя ключевая за период БРИДЖ",_pdf_pct(financing.get('avg_bridge_key_rate'))],["Средневзвешенная ставка БРИДЖ за период",_pdf_pct(financing.get('avg_bridge_rate'))],["Средняя фактическая ставка ПФ",_pdf_pct(financing.get('avg_pf_effective_rate'))],*_pdf_pf_step_rows(financing),["Проценты и комиссии",_pdf_money(financing.get('interest_and_fees'))],["Непогашенный долг ПФ на конец проекта",_pdf_money(financing.get('ending_pf'))],*([["Долг передан в ПФ следующей очереди",_pdf_money(financing.get('debt_carried_out'))]] if float(financing.get('debt_carried_out') or 0)>500_000 else []),*([["в т.ч. принято от предыдущей очереди",_pdf_money(financing.get('carried_debt_in'))]] if (not _pdf_phased and float(financing.get('carried_debt_in') or 0)>500_000) else []),["LLCR",_pdf_num(summary.get('llcr'),2)+"x"]]
    story.append(table(finance_rows,[112*mm,58*mm],font_size=7.6))

    # Restore the bridge-purpose disclosure that exists in the web report.
    # VRI is deliberately absent: it is funded directly by PF at RnS/permit.
    bridge_total = float(financing.get("calculated_bridge") or 0.0)
    capex_data = result.get("capex") or {}

    # Режим «строительство и компенсация» PDF не знал: денежная часть падала
    # в ноль и молча уезжала в «приобретение проекта», а сайт в той же строке
    # показывал её отдельно. Два достоверных на вид отчёта с разными числами —
    # ровно то, что правило «поверхности считают одинаково» запрещает.
    # Состав лимита приходит из расчёта — печать его не пересобирает: в БРИДЖ
    # входит только то, что платится ДО РнС, и вычитание «итог минус…» при
    # рассрочке покупки дало бы второе, расходящееся число. Помощник общий на
    # свод и на очереди: у каждой очереди свой лимит и свой состав.
    def _bridge_uses(res: dict[str, Any]) -> tuple[float, list[tuple[str, float]]]:
        res_financing = ((res.get("report") or {}).get("financing")) or {}
        total = float(res_financing.get("calculated_bridge") or 0.0)
        parts = dict(res_financing.get("calculated_bridge_parts") or {})
        uses = [
            ("Приобретение проекта", float(parts.get("purchase") or 0.0)),
            ("Социальная компенсация", float(parts.get("social") or 0.0)),
            ("Проектирование - стадия П", float(parts.get("design_p") or 0.0)),
            ("Проектирование - стадия РД", float(parts.get("design_rd") or 0.0)),
        ]
        return total, [(label, value) for label, value in uses if value > 0.5]

    def _bridge_use_rows(total: float, uses: list[tuple[str, float]],
                         footer: str) -> list[list[str]]:
        rows = []
        for label, value in uses:
            share = _pdf_num(value / total * 100, 1) + "%" if total else "—"
            rows.append([label, _pdf_money(value), share])
        rows.append([footer, _pdf_money(total), "100,0%" if total else "—"])
        return rows

    bridge_total, bridge_uses = _bridge_uses(result)
    bridge_rows = [["Цель", "Сумма", "Доля"]] + _bridge_use_rows(
        bridge_total, bridge_uses, "ИТОГО БРИДЖ")
    # График платежей за покупку — до структуры БРИДЖа: лимит считается от
    # всей цены, а выборка идёт за платежами, и разница между ними видна
    # только когда напечатаны сроки.
    purchase_plan = report.get("purchase") or {}
    if purchase_plan.get("custom") or purchase_plan.get("warnings"):
        purchase_rows = [["Дата", "Сумма", "Доля цены"]]
        for item in purchase_plan.get("rows") or []:
            when = str(item.get("date") or "")[:10]
            purchase_rows.append([
                ".".join(reversed(when.split("-"))) if when else "—",
                _pdf_money(float(item.get("amount_mln") or 0) * 1e6),
                _pdf_num(float(item.get("share") or 0) * 100, 1) + "%",
            ])
        block = [P("График платежей за покупку", h2),
                 table(purchase_rows, [60*mm, 60*mm, 50*mm], font_size=8.0)]
        for warning in purchase_plan.get("warnings") or []:
            block.append(P(str(warning), small))
        story.append(KeepTogether(block))

    # Лимит БРИДЖа — цифра одного договора, и у проекта с очередями таких
    # договоров столько же, сколько очередей: открыты они в разные годы, и
    # сложенные в одну сумму дают лимит, которого никто не выдавал («это
    # глупость, а не расчётный бридж», владелец, 04.09.2026). Экран уже
    # разбирает его по очередям, и отчёт обязан говорить то же самое.
    _bridge_limit_phases = [item for item in (payload.get("phases") or [])
                            if isinstance(item, dict)]
    if len(_bridge_limit_phases) > 1:
        phase_bridge_rows = [["Цель", "Сумма", "Доля"]]
        for item in _bridge_limit_phases:
            name = str(item.get("name") or "Очередь")
            total_q, uses_q = _bridge_uses(item.get("result") or {})
            if not uses_q:
                phase_bridge_rows.append([name + " - лимит БРИДЖа не рассчитывается", "", ""])
                continue
            phase_bridge_rows.append([name, "", ""])
            phase_bridge_rows.extend(_bridge_use_rows(
                total_q, uses_q, "Лимит БРИДЖа " + name))
        story.append(KeepTogether([
            P("Расчётный лимит БРИДЖа - по очередям", h2),
            table(phase_bridge_rows, [98*mm, 45*mm, 27*mm], font_size=8.0),
            P("Лимит считает банк по каждому договору отдельно: у каждой очереди "
              "своя линия до открытия её ПФ. Сложенные вместе, лимиты дали бы "
              "договор, которого никто не выдавал, поэтому свода здесь нет.", small),
        ]))
    else:
        story.append(KeepTogether([
            P("Структура расчётного БРИДЖА", h2),
            table(bridge_rows, [98*mm, 45*mm, 27*mm], font_size=8.0),
        ]))

    # Фактический пик — по статьям, оплаченным к его месяцу. Без этой таблицы
    # разница между лимитом методики и реальной потребностью («остальное
    # вашими») читалась только глазами по структуре расходов.
    actual_structure = list(financing.get("actual_bridge_structure") or [])
    # По очередям — у каждой свой БРИДЖ и свой месяц пика; свод — подписью.
    pdf_phase_items = [item for item in (payload.get("phases") or []) if isinstance(item, dict)]
    if len(pdf_phase_items) > 1:
        for item in pdf_phase_items:
            pf_fin = ((item.get("result") or {}).get("report") or {}).get("financing") or {}
            rows_q = list(pf_fin.get("actual_bridge_structure") or [])
            name_q = str(item.get("name") or "Очередь")
            if not rows_q:
                continue
            peak_q = float(pf_fin.get("actual_bridge") or 0)
            month_q = str(pf_fin.get("actual_bridge_month") or "")
            table_q = [["Статья", "Оплачено к пику очереди", "Доля"]]
            for row_q in rows_q:
                table_q.append([str(row_q.get("label") or "—"), _pdf_money(float(row_q.get("value") or 0)),
                                _pdf_num(float(row_q.get("share") or 0) * 100, 1) + "%"])
            table_q.append([f"ПИК БРИДЖА {name_q}", _pdf_money(peak_q), "100,0%" if peak_q else "—"])
            story.append(KeepTogether([
                P(f"Структура фактического БРИДЖА · {name_q}"
                  + (f" · {'.'.join(reversed(month_q.split('-')))}" if month_q else ""), h2),
                table(table_q, [98*mm, 45*mm, 27*mm], font_size=8.0),
            ]))
        story.append(P("У каждой очереди свой БРИДЖ до открытия её ПФ; оплачено к месяцу пика этой очереди. "
                       + (f"Свод: наибольшая сумма одновременно открытых линий — "
                          f"{_pdf_money(float(financing.get('actual_bridge') or 0))}."
                          if financing.get("actual_bridge") else ""), small))
        actual_structure = []
    if actual_structure:
        actual_peak = float(financing.get("actual_bridge") or 0)
        actual_rows = [["Статья", "Оплачено к пику", "Доля"]]
        for item in actual_structure:
            value = float(item.get("value") or 0)
            actual_rows.append([
                str(item.get("label") or "—"), _pdf_money(value),
                _pdf_num(float(item.get("share") or 0) * 100, 1) + "%",
            ])
        actual_rows.append(["ПИК БРИДЖА", _pdf_money(actual_peak),
                            "100,0%" if actual_peak else "—"])
        month = str(financing.get("actual_bridge_month") or "")
        queues = financing.get("actual_bridge_queues") or {}
        on_bridge = [str(name) for name in (queues.get("on_bridge") or [])]
        queue_note = ""
        if on_bridge:
            tails = []
            if queues.get("refinanced"):
                tails.append(", ".join(map(str, queues["refinanced"]))
                             + " к этому месяцу уже на ПФ — их расходы сюда не входят")
            if queues.get("not_started"):
                tails.append(", ".join(map(str, queues["not_started"])) + " ещё не начаты")
            queue_note = ("Пик свода — месяц, когда на БРИДЖе " + ", ".join(on_bridge)
                          + ("; " + "; ".join(tails) if tails else "") + ". ")
        story.append(KeepTogether([
            P("Структура фактического БРИДЖА"
              + (f" · {'.'.join(reversed(month.split('-')))}" if month else "")
              + (f" · на БРИДЖе: {', '.join(on_bridge)}" if on_bridge else ""), h2),
            table(actual_rows, [98*mm, 45*mm, 27*mm], font_size=8.0),
            P(queue_note
              + "Оплачено к месяцу пика. До открытия ПФ у очереди нет ни выручки, ни ПФ, "
              "поэтому остаток её БРИДЖа равен оплаченному; разница с расчётным лимитом — "
              "расходы, под которые лимит не даётся.", small),
        ]))

    timeline_rows=list((result.get("finance") or {}).get("rows") or [])
    debt_chart=line_chart(
        timeline_rows,
        [
            {"label":"БРИДЖ","key":"bridge_balance","factor":1/1_000_000_000,"color":"#171717","active":lambda row:float(row.get("bridge_balance",0) or 0)>0},
            {"label":"ПФ","key":"pf_balance","factor":1/1_000_000_000,"color":"#A35D00","active":lambda row:float(row.get("pf_balance",0) or 0)>0},
            {"label":"Эскроу","key":"escrow","factor":1/1_000_000_000,"color":"#2D6A4F","active":lambda row:float(row.get("escrow",0) or 0)>0},
        ],
        "млрд ₽",
        height=128,
    )
    if debt_chart:
        story.append(KeepTogether([P("Долг и наполнение эскроу",h2),debt_chart]))

    # Тот же вопрос, но полной мерой: банку в раскрытие причитается тело И
    # начисленное. График выше сравнивает счёт с телом и на этот вопрос не
    # отвечает — «эскроу выше долга» читалось бы как «рассчитались».
    def escrow_cover_chart(rows: list[dict[str, Any]], cover: dict[str, Any],
                           height: float = 132) -> Drawing | None:
        """Заливка, а не линии: ответ на «перекрывает или нет» — это площадь.

        Линии отвечали хуже: две кривые рядом видно, а разрыв между ними —
        нет. Заливкой видно и его, и то, что после раскрытия остаток гасят
        продажи, а не эскроу.
        """
        def duty(row: dict[str, Any]) -> float:
            return float(row.get("pf_obligation", 0.0) or 0.0)

        def escrow_of(row: dict[str, Any]) -> float:
            return float(row.get("escrow", 0.0) or 0.0)

        data = [row for row in rows if duty(row) > 0 or escrow_of(row) > 0]
        if len(data) < 2:
            return None
        def cum_of(row: dict[str, Any], key: str) -> float:
            return float(row.get(key, 0.0) or 0.0)

        width = 500
        from reportlab.pdfbase.pdfmetrics import stringWidth
        # Легенда шире одной строки: подписей шесть, а ширина листа не растёт.
        # Раскладка считается до геометрии — иначе верхнее поле не знает,
        # сколько строк над ним.
        legend_rows, line_x = 1, 0.0
        for text, _colour, _style in _ESCROW_CHART_LEGEND:
            step = 22 + stringWidth(text, regular, 6.4)
            if line_x and line_x + step > width - 42:
                legend_rows += 1
                line_x = 0.0
            line_x += step
        left, right, bottom = 42, 30, 22
        # Легенда переносом не отнимает у графика поле, а поднимает крышу:
        # подписей стало шесть, и съеденная ими треть высоты — это сплющенный
        # долг, ровно то, от чего уходили. Подписи осей идут под легендой:
        # на одной строке с ней они наезжали друг на друга.
        height = height + 10 * (legend_rows - 1)
        top_pad = 12 + 10 * legend_rows
        plot_w, plot_h = width - left - right, height - bottom - top_pad
        peak = max(max(duty(row), escrow_of(row)) for row in data) * 1.08 or 1.0
        # Долг — «сколько должны сейчас», накопленное — «сколько пришло с
        # начала»: на одной шкале второе перерастает первое и сплющивает его
        # в нижнюю треть. У накопленного своя ось справа.
        cum_peak = max(max(cum_of(row, "escrow_released_cumulative"),
                           cum_of(row, "sales_after_rve_cumulative"))
                       for row in data) * 1.08 or 1.0
        drawing = Drawing(width, height)
        x_at = lambda i: left + plot_w * i / (len(data) - 1)
        y_at = lambda v: bottom + plot_h * max(0.0, v) / peak
        y_cum = lambda v: bottom + plot_h * max(0.0, v) / cum_peak

        for tick in range(5):
            value = peak * tick / 4
            y = y_at(value)
            drawing.add(Line(left, y, width - right, y,
                             strokeColor=colors.HexColor("#E2E2E2"), strokeWidth=0.5))
            drawing.add(String(left - 5, y - 2, _pdf_num(value / 1_000_000_000, 1),
                               fontName=regular, fontSize=6.5, textAnchor="end",
                               fillColor=colors.HexColor("#777777")))

        # Свод складывает счета очередей, а даты раскрытия у них разные: в
        # месяц первой выборки ПФ второй очереди на линии стоит почти только
        # эскроу ПЕРВОЙ, и одной площадью это читается как «выборка сразу
        # покрыта» (владелец, 04.09.2026). Отчёт носят в банк, и расходиться
        # с экраном ему нельзя — здесь те же слои.
        # Число слоёв — по САМОЙ длинной строке, а не по первой: в первом
        # месяце счёт может быть ещё не у всех очередей, и слой пропал бы
        # молча вместе с очередью.
        parts = list(range(max((len(row.get("escrow_by_phase") or []) for row in data),
                               default=0)))
        if len(parts) > 1:
            for layer in range(len(parts)):
                def _below(row: dict[str, Any], k: int = layer) -> float:
                    return sum(float(v or 0.0)
                               for v in (row.get("escrow_by_phase") or [])[:k])

                def _upto(row: dict[str, Any], k: int = layer) -> float:
                    values = row.get("escrow_by_phase") or []
                    return _below(row, k) + float((values[k] if k < len(values) else 0.0) or 0.0)

                band = [(x_at(i), y_at(_upto(row))) for i, row in enumerate(data)]
                band += [(x_at(i), y_at(_below(data[i]))) for i in reversed(range(len(data)))]
                drawing.add(Polygon([c for point in band for c in point],
                                    fillColor=colors.HexColor("#2D6A4F"),
                                    fillOpacity=0.14 + 0.10 * layer,
                                    strokeColor=colors.HexColor("#2D6A4F"), strokeWidth=0.4))
            layer_names = [str(x) for x in (cover.get("phase_names") or [])][:len(parts)]
            drawing.add(String(left + 4, bottom + plot_h - 8,
                               "эскроу — слоями по очередям, снизу вверх"
                               + (": " + " · ".join(layer_names)
                                  if len(layer_names) == len(parts) else ""),
                               fontName=regular, fontSize=6.4,
                               fillColor=colors.HexColor("#2D6A4F")))
        else:
            escrow_area = [(x_at(0), y_at(0))]
            for index, row in enumerate(data):
                escrow_area.append((x_at(index), y_at(escrow_of(row))))
            escrow_area.append((x_at(len(data) - 1), y_at(0)))
            drawing.add(Polygon([c for point in escrow_area for c in point],
                                fillColor=colors.HexColor("#2D6A4F"), fillOpacity=0.30,
                                strokeColor=None))

        run: list[int] = []

        def flush() -> None:
            if len(run) > 1:
                points = [(x_at(i), y_at(duty(data[i]))) for i in run]
                points += [(x_at(i), y_at(escrow_of(data[i]))) for i in reversed(run)]
                drawing.add(Polygon([c for point in points for c in point],
                                    fillColor=colors.HexColor("#A35D00"),
                                    fillOpacity=0.18, strokeColor=None))
            run.clear()

        for index, row in enumerate(data):
            if duty(row) - escrow_of(row) > 0:
                run.append(index)
            else:
                flush()
        flush()

        def polyline(value, colour: str, w: float, dash=None) -> None:
            points = [(x_at(i), y_at(value(row))) for i, row in enumerate(data)]
            line = PolyLine([c for point in points for c in point],
                            strokeColor=colors.HexColor(colour), strokeWidth=w,
                            fillColor=None)
            if dash:
                line.strokeDashArray = dash
            drawing.add(line)

        polyline(duty, "#A35D00", 1.8)
        polyline(lambda row: float(row.get("pf_balance", 0.0) or 0.0), "#A35D00", 0.8, [2, 2])
        polyline(escrow_of, "#2D6A4F", 1.4)
        # Раскрытие эскроу и продажи после ввода — разные события, и одной
        # линией они врут: ступенька читалась как «после ввода продали на
        # столько», хотя продаж в этот месяц нет — это деньги предыдущих лет,
        # снятые со счетов разом.
        def cum_polyline(key: str, w: float, dash=None, opacity: float = 1.0) -> None:
            if not any(cum_of(row, key) > 0 for row in data):
                return
            points = [(x_at(i), y_cum(cum_of(row, key))) for i, row in enumerate(data)]
            line = PolyLine([c for point in points for c in point],
                            strokeColor=colors.HexColor("#1B5E77"), strokeWidth=w,
                            fillColor=None)
            if dash:
                line.strokeDashArray = dash
            if opacity < 1.0:
                line.strokeOpacity = opacity
            drawing.add(line)

        cum_polyline("escrow_released_cumulative", 1.4, [4, 3])
        cum_polyline("sales_after_rve_cumulative", 1.0, None, 0.55)
        for tick in range(5):
            value = cum_peak * tick / 4
            drawing.add(String(width - right + 4, y_cum(value) - 2,
                               _pdf_num(value / 1_000_000_000, 1), fontName=regular,
                               fontSize=6.5, textAnchor="start",
                               fillColor=colors.HexColor("#1B5E77")))

        rve = str(cover.get("rve") or "")[:7]
        for index, row in enumerate(data):
            if str(row.get("month") or "")[:7] == rve:
                drawing.add(Line(x_at(index), bottom, x_at(index), bottom + plot_h,
                                 strokeColor=colors.HexColor("#666666"), strokeWidth=0.6,
                                 strokeDashArray=[2, 2]))
                drawing.add(String(x_at(index) - 4, bottom + plot_h - 8, "раскрытие эскроу",
                                   fontName=regular, fontSize=6.2, textAnchor="end",
                                   fillColor=colors.HexColor("#555555")))
                break

        # Остаток — из свода движка, а не из последней нарисованной точки:
        # рисуются только месяцы с долгом или счётом, и у погасившейся очереди
        # последняя из них лежит до погашения.
        ending = float(cover.get("ending_unpaid", 0.0) or 0.0)
        if ending > 1_000_000:
            drawing.add(Circle(x_at(len(data) - 1), y_at(ending), 1.8,
                               fillColor=colors.HexColor("#A35D00"), strokeColor=None))
            drawing.add(String(x_at(len(data) - 1) - 4, y_at(ending) + 17,
                               "не погашено " + _pdf_money(ending), fontName=regular,
                               fontSize=6.4, textAnchor="end",
                               fillColor=colors.HexColor("#A35D00")))

        x, y_legend = left, height - 7
        for text, colour, style in _ESCROW_CHART_LEGEND:
            step = 22 + stringWidth(text, regular, 6.4)
            if x > left and x + step > width - 42:
                x, y_legend = left, y_legend - 10
            if style in ("area", "band"):
                mark = Rect(x, y_legend - 3, 12, 6,
                            fillColor=colors.HexColor(colour),
                            fillOpacity=0.45 if style == "area" else 0.25,
                            strokeColor=None)
            else:
                mark = Line(x, y_legend, x + 12, y_legend,
                            strokeColor=colors.HexColor(colour),
                            strokeWidth=1.0 if style == "thin" else 2.0)
                if style == "dash4":
                    mark.strokeDashArray = [3, 2]
                elif style == "dash6":
                    mark.strokeDashArray = [4, 3]
                if style == "thin":
                    mark.strokeOpacity = 0.55
            drawing.add(mark)
            drawing.add(String(x + 16, y_legend - 3, text, fontName=regular, fontSize=6.4,
                               fillColor=colors.HexColor("#444444")))
            x += step
        # Две оси — две подписи: без них правая колонка чисел читается как
        # продолжение левой.
        axis_y = bottom + plot_h + 3
        drawing.add(String(left, axis_y, "долг и эскроу, млрд ₽", fontName=regular,
                           fontSize=6.4, textAnchor="start",
                           fillColor=colors.HexColor("#777777")))
        drawing.add(String(width - 2, axis_y, "накопленным итогом, млрд ₽", fontName=regular,
                           fontSize=6.4, textAnchor="end",
                           fillColor=colors.HexColor("#1B5E77")))
        for index in sorted(set([0, len(data) // 2, len(data) - 1])):
            drawing.add(String(x_at(index), 5, chart_month(data[index].get("month")),
                               fontName=regular, fontSize=6.4, textAnchor="middle",
                               fillColor=colors.HexColor("#777777")))
        return drawing

    def escrow_cover_block(rows: list[dict[str, Any]], cover: dict[str, Any],
                           title: str, heading=None) -> list[Any]:
        chart = escrow_cover_chart(rows, cover)
        lines = [P(line, small) for line in (cover.get("lines") or [])]
        if not chart and not lines:
            return []
        return [P(title, heading or h2)] + ([chart] if chart else []) + lines

    escrow_cover = financing.get("escrow_cover") or {}
    block = escrow_cover_block(timeline_rows, escrow_cover,
                               "Эскроу против обязательств по ПФ")
    if block:
        story.append(KeepTogether(block))

    # По очередям — своим блоком: дата раскрытия у каждой своя, и свод на
    # вопрос «какой очереди не хватило» не отвечает.
    phase_rows = {str(item.get("name") or ""): (((item.get("result") or {}).get("finance") or {}).get("rows") or [])
                  for item in (payload.get("phases") or [])}
    for cover in (financing.get("escrow_cover_phases") or []):
        name = str(cover.get("label") or "Очередь")
        block = escrow_cover_block(phase_rows.get(name) or [], cover, name, h2)
        if block:
            story.append(KeepTogether(block))

    rate_chart=line_chart(
        timeline_rows,
        [
            {"label":"Ключевая ставка","key":"key_rate","factor":100,"color":"#777777"},
            {"label":"БРИДЖ","key":"bridge_rate","factor":100,"color":"#171717","active":lambda row:float(row.get("bridge_balance",0) or 0)>0},
            {"label":"Фактическая ПФ","key":"pf_rate","factor":100,"color":"#A35D00","active":lambda row:float(row.get("pf_balance",0) or 0)>0},
        ],
        "%",
        height=128,
    )
    if rate_chart:
        story.append(KeepTogether([P("Ставки финансирования",h2),rate_chart]))
    if _layout and not _layout.get("project_finance", True):
        # Банковского блока у проекта без ДДУ нет: печатать нули БРИДЖа,
        # ПФ и эскроу значило бы называть их «посчитанными и пустыми».
        del story[_financing_start:]
        story.append(_PdfSection("financing"))
        story.append(P("Финансирование", h2))
        _hotel_finance = ((report.get("object_report") or {}).get("hotel")
                          and _object_sections.get("finance"))
        if _hotel_finance:
            # Гостиница — свой кредит и своё правило капитала; блоки раздела
            # те же, что на странице (`hotel_object_report`).
            story.append(P("Банк ПФ гостиницу не кредитует: стройку и общие затраты "
                           "финансирует кредит гостиницы на долю затрат, остальное — "
                           "собственный капитал. Пока кредит не погашен, свободный поток "
                           "после процентов и налога гасит долг, собственнику — после "
                           "погашения.", small))
            _object_pdf_blocks(story, _hotel_finance, inputs, P, table, small,
                               KeepTogether, Spacer, mm)
        else:
            story.append(P("Проект без продаж по ДДУ: БРИДЖа, проектного финансирования и "
                           "эскроу нет. Стройку и общие затраты финансирует кредит объекта "
                           "на долю стоимости, остальное — собственный капитал.", small))
    # Кредит объектов вне ДДУ — в разделе «Финансирование», той же таблицей
    # движка (`nonres_financing_report`), что на экране: условия, выборка,
    # платёж, баллон, погашение и обслуживание по годам. Прежде раздел у
    # нежилого проекта был пуст, а таблица стояла среди продуктов.
    if report.get("nonres_financing"):
        loan_chart = line_chart(
            timeline_rows,
            [{"label": "Кредит объектов — остаток", "key": "nonres_loan_balance",
              "factor": 1/1_000_000_000, "color": "#171717",
              # Месяц погашения (остаток 0) тоже точка: без него линия
              # обрывалась на последнем остатке, и долг выглядел непогашенным.
              "active": lambda row: (float(row.get("nonres_loan_balance", 0) or 0) > 0
                                     or float(row.get("nonres_loan_repayment", 0) or 0) > 0)}],
            "млрд ₽",
            height=118,
        )
        if loan_chart:
            story.append(KeepTogether([P("Кредит объектов — остаток долга", h2), loan_chart]))
    for _nf in report.get("nonres_financing") or []:
        _years_cols = _nf.get("columns") or []
        _nf_rows = [["Финансирование объекта: " + str(_nf.get("title") or ""), " "]]
        for _row in _nf.get("rows") or []:
            _nf_rows.append([str(_row.get("label") or "").upper()
                             if _row.get("unit") == "section" else str(_row.get("label") or ""),
                             _pdf_nonres_value(_row)])
        # Длинная таблица переносится со строкой заголовка, а не прыгает
        # целиком на следующую страницу, оставляя раздел пустым.
        story.append(table(_nf_rows, [112*mm, 58*mm], font_size=7.6))
        _parts = []
        if _nf.get("years") and _years_cols:
            _yrows = [[str(c[1]) for c in _years_cols]]
            for _y in _nf["years"]:
                _yrows.append([str(_y.get(c[0])) if c[2] == "text"
                               else _pdf_nonres_value({"unit": c[2], "value": _y.get(c[0])})
                               for c in _years_cols])
            _parts.append(P("Обслуживание кредита по годам", small))
            _parts.append(table(_yrows, [14*mm] + [26*mm] * (len(_years_cols) - 1), font_size=6.8))
        if _parts:
            story.append(KeepTogether(_parts))
    # Собственное участие — та же таблица, что на экране
    # (`equity_participation_report`): вложения, возврат, результат, по годам.
    _eq = report.get("equity_participation") or {}
    if _eq.get("rows"):
        story.append(P("Собственное участие", h2))
        _eq_rows = [["Показатель", "Значение"]]
        for _row in _eq["rows"]:
            _eq_rows.append([str(_row.get("label") or "").upper()
                             if _row.get("unit") == "section" else str(_row.get("label") or ""),
                             _pdf_nonres_value(_row)])
        story.append(table(_eq_rows, [112*mm, 58*mm], font_size=7.6))
        _cols = _eq.get("columns") or []
        if _eq.get("years") and _cols:
            _yrows = [[str(c[1]) for c in _cols]]
            for _y in _eq["years"]:
                _yrows.append([str(_y.get(c[0])) if c[2] == "text"
                               else _pdf_nonres_value({"unit": c[2], "value": _y.get(c[0])})
                               for c in _cols])
            story.append(KeepTogether([P("Собственный капитал по годам", small),
                                       table(_yrows, [16*mm] + [38*mm] * (len(_cols) - 1),
                                             font_size=6.8)]))

    story.append(_PdfSection("income"))
    pace_chart=sales_bar_chart(timeline_rows,height=104)
    if pace_chart:
        story.append(KeepTogether([P("Месячный темп продаж",h2),pace_chart]))

    # Тот же темп в штуках квартир: денежный график прячет и рост цены, и
    # изменение нарезки — по нему не видно, сколько квартир уходит в месяц.
    apartment_pace_rows = (report.get("apartment_sales") or {}).get("rows") or []
    units_chart=sales_bar_chart(apartment_pace_rows,height=104,key="units",
                                factor=1.0,unit_label="квартир/мес.",digits=0)
    if units_chart:
        story.append(KeepTogether([P("Месячный темп продаж квартир, шт.",h2),units_chart]))

    story.append(_PdfSection("calendar"))
    events=calendar_data.get('events') or []
    if events:
        gantt_pages=gantt_drawings(events)
        for page_index,gantt in enumerate(gantt_pages):
            story.append(PageBreak())
            _cal_title = str((_object_sections.get("calendar") or {}).get("title")
                             or "Календарный план проекта")
            story.append(P(_cal_title if page_index==0 else _cal_title+" · продолжение",h2))
            story.append(gantt)
        story.append(Spacer(1,2*mm))
        story.append(P("Полосы построены по фактическим датам модели; ромбами отмечены ключевые вехи. При включённой очередности этапы каждой очереди показаны отдельными строками.",small))
    if _object_sections:
        _object_pdf_sections(story, _object_sections, inputs, P, table, h2, small, normal,
                             KeepTogether, Spacer, mm, sensitivity_done=bool(
                                 sensitivity and (sensitivity.get("items") or [])))
    story.append(_PdfSection("footer"))
    story.extend([Spacer(1,4*mm),P("Отчёт сформирован автоматически DevelopAid на основании текущих вводных модели. Перед инвестиционным решением требуется проверка исходных данных, юридических предпосылок и условий кредитования.",small)])

    def footer(canvas,doc_obj):
        canvas.saveState();canvas.setFont(regular,7);canvas.setFillColor(colors.HexColor('#777777'));canvas.drawString(14*mm,8*mm,'DevelopAid · Девелоперская инвестиционная модель');canvas.drawRightString(A4[0]-14*mm,8*mm,f'Стр. {doc_obj.page}');canvas.restoreState()
    # Разбор проекта, а не история правок: что за участок → что на нём выходит
    # → на чём считали → сколько стоит → сколько приносит → чем финансируется
    # → чем рискуем → когда.
    story = _pdf_ordered_story(story, _pdf_section_order(_object_sections), PageBreak)
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return buf.getvalue()

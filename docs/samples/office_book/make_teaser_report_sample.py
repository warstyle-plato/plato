"""Образец тизера и ключевых страниц отчёта офисного проекта (два пути рядом).

Цифры — из движка (collect.py / be.py), вводные восстановлены по файлам владельца.
"""
import json, sys
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                                PageBreak, KeepTogether)
from reportlab.graphics.shapes import Drawing, Rect, String, Line

SP = "/tmp/claude-0/-home-user-plato/c936f76f-bdf5-5950-84e0-841f7b792428/scratchpad/"
S = json.load(open(SP + "sample.json"))
B = json.load(open(SP + "be.json"))
D, I = S["direct"], S["income"]

pdfmetrics.registerFont(TTFont("R", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("B", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))

NAVY = colors.HexColor("#17365D"); LIGHT = colors.HexColor("#EAF2F8"); GREY = colors.HexColor("#5F6B76")
LINE = colors.HexColor("#C9D3DE"); RED = colors.HexColor("#B00020"); SALE = colors.HexColor("#2F6DB5")
RENT = colors.HexColor("#C26A0A"); SOFT = colors.HexColor("#F6F8FA"); NOTE = colors.HexColor("#FFF6E0")

st = {
    "h1": ParagraphStyle("h1", fontName="B", fontSize=13.5, leading=17, textColor=NAVY),
    "h2": ParagraphStyle("h2", fontName="B", fontSize=10.5, leading=13, textColor=NAVY, spaceBefore=5, spaceAfter=3),
    "p": ParagraphStyle("p", fontName="R", fontSize=8.4, leading=11),
    "small": ParagraphStyle("s", fontName="R", fontSize=7, leading=9, textColor=GREY),
    "cell": ParagraphStyle("c", fontName="R", fontSize=7.8, leading=9.6),
    "cellb": ParagraphStyle("cb", fontName="B", fontSize=7.8, leading=9.6),
    "verdict": ParagraphStyle("v", fontName="R", fontSize=9.2, leading=12.5),
    "tag": ParagraphStyle("t", fontName="B", fontSize=7, leading=9, textColor=colors.white),
}
W = A4[0] - 24 * mm


def m(v, d=0):
    """млн ₽ из рублей, русская запись."""
    if v is None:
        return "—"
    x = v / 1e6
    s = f"{x:,.{d}f}".replace(",", " ").replace(".", ",")
    return s.replace("-", "−")


def pct(v, d=1):
    return "—" if v is None else f"{v*100:.{d}f}".replace(".", ",").replace("-", "−") + "%"


def num(v, d=0):
    return f"{v:,.{d}f}".replace(",", " ").replace(".", ",").replace("-", "−")


def P(t, s="cell"):
    return Paragraph(t, st[s])


def table(rows, widths, head=True, zebra=True, bold_rows=(), colhead_colors=None, align_right_from=1, left_cols=()):
    data = [[P(c, "cellb" if (head and r == 0) or r in bold_rows else "cell") if isinstance(c, str) else c
             for c in row] for r, row in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if head else 0)
    cmds = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE),
            ("TOPPADDING", (0, 0), (-1, -1), 2.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
            ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]
    if head:
        cmds += [("BACKGROUND", (0, 0), (-1, 0), LIGHT), ("LINEBELOW", (0, 0), (-1, 0), 0.8, NAVY)]
    if colhead_colors:
        for col, c in colhead_colors.items():
            cmds += [("LINEABOVE", (col, 0), (col, 0), 2.5, c)]
    for r in bold_rows:
        cmds += [("BACKGROUND", (0, r), (-1, r), SOFT)]
    t.setStyle(TableStyle(cmds))
    for row in data:
        for j, c in enumerate(row):
            if j >= align_right_from and j not in left_cols and isinstance(c, Paragraph):
                c.style = ParagraphStyle("r", parent=c.style, alignment=2)
    return t


def band(text, color=NAVY):
    t = Table([[P(text, "tag")]], colWidths=[W])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), color), ("LEFTPADDING", (0, 0), (-1, -1), 5),
                           ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    return t


def boxed(flow, bg=NOTE, width=W):
    t = Table([[flow]], colWidths=[width])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                           ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                           ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    return t


# --- графики -----------------------------------------------------------------

def tornado(path, title, color, width, height=52 * mm):
    sens = S[path]["sens"]; base = S[path]["npv"]
    names = [("rent", "Ставка аренды ±10%"), ("occ", "Заполняемость ±5 п.п."), ("cap", "Ставка капитализации ±1 п.п."),
             ("price", "Цена продажи ±10%"), ("cost", "Стоимость стройки ±10%"), ("entry", "Цена входа ±10% (±68 млн)")]
    rows = []
    for key, label in names:
        lo, hi = sens[key]["lo"][0] - base, sens[key]["hi"][0] - base
        rows.append((label, lo, hi))
    rows.sort(key=lambda r: -max(abs(r[1]), abs(r[2])))
    span = max(max(abs(r[1]), abs(r[2])) for r in rows) or 1
    dw = Drawing(width, height)
    dw.add(String(0, height - 9, title, fontName="B", fontSize=8, fillColor=NAVY))
    label_w = 44 * mm; axis_x = label_w + (width - label_w - 14 * mm) / 2; half = (width - label_w - 14 * mm) / 2
    top = height - 20; step = (height - 30) / len(rows)
    dw.add(Line(axis_x, 6, axis_x, top + 6, strokeColor=GREY, strokeWidth=0.6))
    for i, (label, lo, hi) in enumerate(rows):
        y = top - i * step
        dw.add(String(0, y - 3, label, fontName="R", fontSize=6.6, fillColor=colors.black))
        if abs(lo) < 1e5 and abs(hi) < 1e5:
            dw.add(String(axis_x + 3, y - 3, "не влияет на этот путь", fontName="R", fontSize=6.3, fillColor=GREY))
            continue
        for v in (lo, hi):
            w = abs(v) / span * half
            x = axis_x if v >= 0 else axis_x - w
            dw.add(Rect(x, y - 4, max(w, 0.8), 8, fillColor=color if v >= 0 else colors.HexColor("#9AA5B1"),
                        strokeColor=None))
            txt = ("+" if v > 0 else "") + m(v)
            tx = x + w + 2 if v >= 0 else x - 2
            dw.add(String(tx, y - 3, txt, fontName="R", fontSize=6.3, fillColor=colors.black,
                          textAnchor="start" if v >= 0 else "end"))
    dw.add(String(axis_x, 0, f"от базового NPV {m(base)} млн ₽", fontName="R", fontSize=6.3,
                  fillColor=GREY, textAnchor="middle"))
    return dw


def timeline(width, height=19 * mm):
    dw = Drawing(width, height)
    y0, y1 = 2027.0, 2036.0
    lx = 34 * mm; scale = (width - lx - 4) / (y1 - y0)
    X = lambda yr, mo=1: lx + (yr + (mo - 1) / 12 - y0) * scale
    rows = [("Документы до разрешения", 2027, 1, 2028, 7, NAVY), ("Стройка", 2028, 7, 2030, 7, NAVY),
            ("Продажа блоками", 2030, 7, 2031, 7, SALE), ("Аренда, удержание", 2030, 7, 2035, 7, RENT)]
    for i, (lab, a, am, b, bm, c) in enumerate(rows):
        y = height - 12 - i * 9
        dw.add(String(0, y, lab, fontName="R", fontSize=6.6))
        dw.add(Rect(X(a, am), y - 1, X(b, bm) - X(a, am), 6.5, fillColor=c, strokeColor=None))
    dw.add(String(X(2035, 6) + 2, height - 12 - 3 * 9 + 0.5, "выход", fontName="R", fontSize=6, fillColor=RENT))
    for yr in range(2027, 2037):
        dw.add(String(X(yr), 0, str(yr), fontName="R", fontSize=6, fillColor=GREY, textAnchor="middle"))
    return dw


def noi_bars(width, height=40 * mm):
    yrs = [y for y in B["years"] if y["rent_revenue"]]
    dw = Drawing(width, height)
    mx = max(y["rent_revenue"] for y in yrs)
    bw = (width - 10) / len(yrs)
    for i, y in enumerate(yrs):
        x = 5 + i * bw
        h_rev = y["rent_revenue"] / mx * (height - 22)
        h_noi = y["noi"] / mx * (height - 22)
        dw.add(Rect(x + 4, 12, bw * 0.38, h_rev, fillColor=colors.HexColor("#E7C9A6"), strokeColor=None))
        dw.add(Rect(x + 4 + bw * 0.38 + 2, 12, bw * 0.38, h_noi, fillColor=RENT, strokeColor=None))
        dw.add(String(x + bw / 2, 3, str(y["year"]), fontName="R", fontSize=6, textAnchor="middle", fillColor=GREY))
        dw.add(String(x + 4 + bw * 0.57 + 1, 14 + h_noi, m(y["noi"]), fontName="R", fontSize=5.8, textAnchor="middle"))
    dw.add(Rect(5, height - 7, 6, 5, fillColor=colors.HexColor("#E7C9A6"), strokeColor=None))
    dw.add(String(13, height - 7, "Доход аренды", fontName="R", fontSize=6.3))
    dw.add(Rect(65, height - 7, 6, 5, fillColor=RENT, strokeColor=None))
    dw.add(String(73, height - 7, "NOI — после расходов эксплуатации и налога на имущество", fontName="R", fontSize=6.3))
    return dw


# --- общие числа (один владелец каждого числа) ---------------------------------
AREA = 15030.0
YOC = I["noi_stab"] / I["cost_total"]
YOC_ENGINE = I["noi_stab"] / I["obj_capex"]


def compare_rows(full=False):
    r = [["", "Продажа блоками (купля-продажа после ввода)", "Аренда 5 лет и продажа здания"],
         ["Выручка, с НДС", m(D["revenue"]), f"{m(I['revenue'])}<br/><font size=6.5 color='#5F6B76'>аренда {m(I['rent_rev'])} + продажа здания {m(I['exit_rev'])}</font>"],
         ["Затраты на создание, с НДС (с участком 680)", m(D["cost_total"]), m(I["cost_total"])],
         ["Расходы на продажу или эксплуатацию",
          f"{m(D['selling'])}<br/><font size=6.5 color='#5F6B76'>маркетинг и брокеры 7%</font>",
          f"{m(I['opex'] + I['prop_tax'])}<br/><font size=6.5 color='#5F6B76'>эксплуатация {m(I['opex'])} + налог на имущество {m(I['prop_tax'])}</font>"],
         ["Проценты и комиссии банка", m(D["fin_cost"]), m(I["fin_cost"])],
         ["Налог на прибыль", m(D["tax"]), m(I["tax"])],
         ["Чистая прибыль", m(D["net"]), m(I["net"])],
         ["NPV проекта при ставке 20%", m(D["npv"]), m(I["npv"])],
         ["IRR проекта (до кредита)", pct(D["irr"]), pct(I["irr"])],
         ["Пик собственных денег (что вложит владелец до возврата)", m(D["equity_peak"]), m(I["equity_peak"])]]
    bold = (6, 7)
    if full:
        r += [["Стабилизированный NOI, год (2032)", "не применяется", m(I["noi_stab"])],
              ["Доходность на затраты: NOI / все затраты", "не применяется", pct(YOC)],
              ["Ставка капитализации при продаже здания", "не применяется", pct(0.105)],
              ["Стоимость здания при продаже: NOI следующего года / ставка", "не применяется",
               f"{m(I['noi_fwd'])} / 10,5% = {m(I['exit_value'])}"],
              ["Покрытие платежей банку из NOI, минимум (DSCR)", "не применяется", num(I["dscr"], 2).replace(".", ",")]]
    return r, bold


def teaser():
    s = []
    s.append(P("Офисный проект: Москва, Пролетарский проспект, вл. 20", "h1"))
    s.append(P("Четыре участка одним контуром: 77:05:0005007:82, :99, :45, :28, всего 0,243 га. "
               "Тизер, страница 1 из 2. Все суммы — млн ₽ с НДС, если не сказано иное.", "small"))
    s.append(Spacer(1, 4))
    mp = Drawing(W * 0.56, 72 * mm)
    mp.add(Rect(0, 0, W * 0.56, 72 * mm, fillColor=colors.HexColor("#E9EEF2"), strokeColor=LINE))
    mp.add(String(W * 0.28, 38 * mm, "Карта: четыре участка одним контуром", fontName="B", fontSize=8.5,
                  fillColor=GREY, textAnchor="middle"))
    mp.add(String(W * 0.28, 33 * mm, "на треть страницы, с улицами и метро (в образце — место под неё)",
                  fontName="R", fontSize=7, fillColor=GREY, textAnchor="middle"))
    facts = table([["Участок и продукт", ""],
                   ["Площадь участков", "2 430 м²"],
                   ["Разрешённое использование", "коротко по классификатору¹"],
                   ["Наземная площадь здания", "22 842 м²"],
                   ["Общая площадь", "21 472 м²"],
                   ["Арендопригодная = продаваемая", "15 030 м²"],
                   ["Эффективность: арендная / наземная", pct(15030 / 22842)],
                   ["Подземный паркинг", "68 мест, 2 380 м²²"],
                   ["Цена входа", "680 = участок 5 + выкуп участков и зданий 675"],
                   ["Начало, ввод", "01.2027, 07.2030"]],
                  [W * 0.2, W * 0.22])
    row = Table([[mp, facts]], colWidths=[W * 0.57, W * 0.43])
    row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    s.append(row)
    s.append(Spacer(1, 5))
    s.append(boxed(P(
        "<b>Вывод.</b> При цене входа 680 млн ₽ проект не окупается ни продажей, ни арендой. "
        f"Продажа теряет меньше: NPV {m(D['npv'])} против {m(I['npv'])} у аренды. "
        f"Участок здесь не решает дело: даже бесплатный, он оставляет NPV {m(B['free_land_direct'])} при продаже "
        f"и {m(B['free_land_income'])} при аренде. "
        f"Проект выходит в ноль при стартовой цене продажи <b>{num(B['sale_price_be'])} тыс. ₽/м²</b> (заложено 273) "
        f"или при ставке аренды <b>{num(B['rent_be'] * 12, 0)} тыс. ₽/м² в год</b> (заложено 30).", "verdict")))
    s.append(Spacer(1, 5))
    s.append(P("Два пути одним расчётом", "h2"))
    rows, bold = compare_rows()
    s.append(table(rows, [W * 0.40, W * 0.30, W * 0.30], bold_rows=bold, colhead_colors={1: SALE, 2: RENT}))
    s.append(Spacer(1, 4))
    s.append(P("¹ Полный текст разрешённого использования из ЕГРН — в примечании на странице 2, без капса. "
               "² Паркинг — часть продукта: при продаже места продаются, при аренде сдаются по 8 тыс. ₽ в месяц за место "
               "(61 место, 7 гостевых не сдаются). Обе колонки — один расчёт движка; IRR и NPV проекта считаются до кредита.",
               "small"))
    s.append(PageBreak())

    # стр. 2
    s.append(P("Почему так и от чего зависит", "h1"))
    s.append(P("Тизер, страница 2 из 2.", "small"))
    s.append(Spacer(1, 3))
    unit = table([["На 1 м² арендопригодной площади", "тыс. ₽/м²"],
                  ["Все затраты на создание, с участком", num(D["cost_total"] / AREA / 1e3, 1)],
                  ["Выручка от продажи блоками, в среднем", num(D["revenue"] / AREA / 1e3, 1)],
                  ["Стоимость здания при продаже после аренды", num(I["exit_value"] / AREA / 1e3, 1)],
                  ["NOI в год после заполнения", num(I["noi_stab"] / AREA / 1e3, 1)]],
                 [W * 0.33, W * 0.14])
    spread = boxed(P(
        f"<b>Главный показатель офиса.</b> Доходность на затраты {pct(YOC)} ниже ставки капитализации 10,5%. "
        f"Это значит, что готовое здание стоит дешевле, чем обходится его строительство: "
        f"{m(I['exit_value'])} против {m(I['cost_total'])} млн ₽. "
        "Строить, чтобы сдавать, выгодно, только когда доходность на затраты выше ставки капитализации "
        "хотя бы на 1,5–2 процентных пункта.", "p"), bg=SOFT, width=W * 0.5)
    r = Table([[unit, spread]], colWidths=[W * 0.49, W * 0.51])
    r.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    s.append(r)
    s.append(P("Чувствительность: насколько меняется NPV, млн ₽", "h2"))
    tw = (W - 6 * mm) / 2
    t = Table([[tornado("direct", "Продажа блоками", SALE, tw), tornado("income", "Аренда и продажа здания", RENT, tw)]],
              colWidths=[tw + 3 * mm, tw + 3 * mm])
    t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    s.append(t)
    s.append(P("Аренда: доход и NOI по годам, млн ₽", "h2"))
    s.append(noi_bars(W))
    s.append(P("Сроки", "h2"))
    s.append(timeline(W))
    s.append(P("Что проверить до решения", "h2"))
    for line in [
        f"Ставка аренды 30 тыс. ₽/м² в год и цена продажи 273 тыс. ₽/м² — стартовые допущения образца. Их нужно сверить с рынком "
        "Южного округа: от них результат зависит сильнее всего.",
        f"Кредит (ключевая ставка плюс 4 п.п.) съедает аренду: платёж банку {m(63774246)} млн в месяц, а NOI после заполнения около "
        f"{m(I['noi_stab'] / 12)} млн. Покрытие платежей {num(I['dscr'], 2).replace('.', ',')} при норме банка от 1,2.",
        "Три из четырёх участков меньше 1 000 м². Ограничения проверены по общему контуру всех четырёх участков, а не по каждому отдельно."]:
        s.append(P("• " + line))
    s.append(Spacer(1, 3))
    s.append(P("Примечание 1. Полный текст разрешённого использования по ЕГРН — обычным регистром, целиком. "
               "Расчёт: движок 0.26.89, обе колонки и все графики — один расчёт.", "small"))
    return s


def report():
    s = [PageBreak()]
    s.append(band("ПОЛНЫЙ ОТЧЁТ · КЛЮЧЕВЫЕ СТРАНИЦЫ ОБРАЗЦА"))
    s.append(Spacer(1, 4))
    s.append(P("1. Два пути одним расчётом", "h1"))
    s.append(P("Офис можно продать блоками после ввода или сдавать пять лет и продать здание целиком. "
               "Обе колонки посчитаны одним расчётом на одних площадях, сроках и затратах. Отличаются только деньги после ввода и кредит.", "p"))
    s.append(Spacer(1, 4))
    rows, bold = compare_rows(full=True)
    s.append(table(rows, [W * 0.42, W * 0.29, W * 0.29], bold_rows=bold, colhead_colors={1: SALE, 2: RENT}))
    s.append(Spacer(1, 6))
    s.append(P("При какой цене и ставке проект выходит в ноль", "h2"))
    s.append(table([["Что меняем", "Заложено", "Ноль по NPV", "Комментарий"],
                    ["Стартовая цена продажи, тыс. ₽/м²", "273", num(B["sale_price_be"]),
                     "Путь «продажа». Цена растёт до ввода на 1,5% в месяц, как во вводных."],
                    ["Ставка аренды, тыс. ₽/м² в год, с НДС", "30", num(B["rent_be"] * 12),
                     "Путь «аренда». Заполняемость 92%, расходы эксплуатации 18% дохода."],
                    ["Цена входа, млн ₽", "680", "ниже нуля",
                     f"Даже бесплатный участок: NPV {m(B['free_land_direct'])} при продаже, {m(B['free_land_income'])} при аренде."]],
                   [W * 0.30, W * 0.12, W * 0.13, W * 0.45], align_right_from=1, left_cols=(3,)))
    s.append(Spacer(1, 6))
    s.append(boxed(P(
        "<b>Одно число — одна подпись.</b> Выручка везде одна: та, что в этой таблице, с НДС. "
        "Её повторяют тизер, страница и книга, второй «выручки ДДУ» у офиса нет. "
        "Собственные деньги показаны одним числом на каждый путь, с подписью, что в него входит: участок и стройка без кредита, "
        "до того как деньги начнут возвращаться. Строк «собственные средства до проектного финансирования» и "
        "«фактическая ставка проектного финансирования» у офиса нет: без продажи по ДДУ нет счетов эскроу.", "p"), bg=SOFT))

    s.append(PageBreak())
    s.append(P("2. Аренда: от ставки к NOI и стоимости здания", "h1"))
    s.append(P("Как складывается доход: арендопригодная площадь × ставка × заполняемость, плюс аренда машино-мест. "
               "Из дохода вычитаются расходы эксплуатации и налог на имущество, остаётся NOI — чистый операционный доход.", "p"))
    s.append(Spacer(1, 4))
    yrows = [["Год", "Заполняемость", "Доход аренды", "Эксплуатация", "Налог на имущество", "NOI"]]
    for y in B["years"]:
        if not y["rent_revenue"]:
            continue
        yrows.append([str(y["year"]), pct(y["occupancy"], 0), m(y["rent_revenue"], 1), m(y["opex"], 1),
                      m(y["property_tax"], 1), m(y["noi"], 1)])
    yrows.append(["Итого за 5 лет", "", m(I["rent_rev"], 1), m(I["opex"], 1), m(I["prop_tax"], 1),
                  m(I["rent_rev"] - I["opex"] - I["prop_tax"], 1)])
    s.append(table(yrows, [W * 0.16] + [W * 0.168] * 5, bold_rows=(len(yrows) - 1,)))
    s.append(P("2030 и 2035 — неполные годы: ввод в июле 2030, продажа здания в июне 2035. Заполнение с 55% до 92% за 18 месяцев.", "small"))
    s.append(Spacer(1, 5))
    s.append(P("Продажа здания через 5 лет", "h2"))
    s.append(table([["Шаг", "млн ₽"],
                    ["NOI следующих 12 месяцев после срока аренды", m(I["noi_fwd"], 1)],
                    ["Ставка капитализации", "10,5%"],
                    ["Стоимость здания = NOI / ставка", m(I["exit_value"], 1)],
                    ["Расходы на сделку, 1%", "−" + m(I["exit_value"] * 0.01, 1)],
                    ["Получено от продажи здания", m(I["exit_value"] * 0.99, 1)]],
                   [W * 0.6, W * 0.2], bold_rows=(5,)))
    s.append(Spacer(1, 5))
    s.append(P("Кредит при аренде", "h2"))
    s.append(table([["Показатель", "Значение"],
                    ["Долг на дату ввода, с процентами за стройку", m(I["loan_peak"]) + " млн ₽"],
                    ["Платёж банку по графику (аннуитет 10 лет, остаток 20% в конце)", "63,8 млн ₽ в месяц"],
                    ["NOI в месяц после заполнения", m(I["noi_stab"] / 12, 1) + " млн ₽"],
                    ["Покрытие платежей из NOI, минимум", num(I["dscr"], 2).replace(".", ",") + " (банк ждёт от 1,2)"],
                    ["Ключевая ставка в среднем за срок кредита", pct(I["rate"]) + ", кредит дороже на 4 п.п."]],
                   [W * 0.6, W * 0.3]))
    s.append(Spacer(1, 5))
    s.append(boxed(P(
        f"<b>Исправление в расчёте.</b> Сейчас движок делит NOI только на стройку здания ({m(I['obj_capex'])} млн) и показывает "
        f"доходность на затраты {pct(YOC_ENGINE)}. Правильная база — все затраты с участком и общими статьями "
        f"({m(I['cost_total'])} млн), и тогда доходность {pct(YOC)}. В отчёте подпись будет называть делитель.", "p")))

    s.append(PageBreak())
    s.append(P("3. Продажа блоками", "h1"))
    s.append(P("Офисы продаются по договорам купли-продажи после ввода, без ДДУ и без счетов эскроу. "
               "Деньги покупателей сразу гасят кредит на стройку.", "p"))
    s.append(Spacer(1, 4))
    drows = [["Год", "Выручка, с НДС", "Доля продаж"]]
    for y in D["years"]:
        if y["sale_revenue"]:
            drows.append([str(y["year"]), m(y["sale_revenue"], 1), pct(y["sale_revenue"] / D["sale_rev"], 0)])
    drows.append(["Итого", m(D["sale_rev"], 1), "100%"])
    s.append(table(drows, [W * 0.2, W * 0.25, W * 0.2], bold_rows=(len(drows) - 1,)))
    s.append(Spacer(1, 5))
    s.append(table([["Показатель", "Значение"],
                    ["Срок продаж после ввода", "12 месяцев, равномерно"],
                    ["Расходы на продажу (маркетинг и брокеры)", m(D["selling"], 1) + " млн ₽, 7% выручки"],
                    ["Кредит: пик долга", m(D["loan_peak"]) + " млн ₽"],
                    ["Кредит: проценты и комиссии", m(D["fin_cost"]) + " млн ₽"],
                    ["Ключевая ставка в среднем за срок кредита", pct(D["rate"]) + ", кредит дороже на 4 п.п."],
                    ["Возможность: предварительные договоры до ввода", "сдвиг старта продаж во вводных"]],
                   [W * 0.55, W * 0.4]))
    s.append(Spacer(1, 6))
    s.append(P("4. Чувствительность", "h1"))
    s.append(P("Каждая строка меняет одно допущение, остальное как в базе. Цифры — NPV проекта, млн ₽.", "p"))
    s.append(Spacer(1, 3))
    names = [("rent", "Ставка аренды", "−10%", "+10%"), ("occ", "Заполняемость", "87%", "97%"),
             ("cap", "Ставка капитализации", "11,5%", "9,5%"), ("price", "Цена продажи", "−10%", "+10%"),
             ("cost", "Стоимость стройки", "+10%", "−10%"), ("entry", "Цена входа", "+68 млн", "−68 млн")]
    srows = [["Допущение", "Хуже", "Лучше", "Продажа: NPV хуже / лучше", "Аренда: NPV хуже / лучше"]]
    for key, lab, a, b in names:
        def cell(path):
            lo, hi = S[path]["sens"][key]["lo"][0], S[path]["sens"][key]["hi"][0]
            if abs(lo - S[path]["npv"]) < 1e5 and abs(hi - S[path]["npv"]) < 1e5:
                return "не влияет"
            return f"{m(lo)} / {m(hi)}"
        srows.append([lab, a, b, cell("direct"), cell("income")])
    s.append(table(srows, [W * 0.24, W * 0.11, W * 0.11, W * 0.27, W * 0.27]))
    s.append(P("В нынешнем отчёте размах по цене входа показан нулём. В новом строка меняет NPV, и видно, сколько стоят ±68 млн цены входа.", "small"))

    s.append(PageBreak())
    s.append(P("5. Участки и ограничения", "h1"))
    s.append(P("Территория из четырёх участков проверяется по общему контуру. Маленький участок не выпадает из проверки, "
               "а входит в контур вместе с соседними.", "p"))
    s.append(Spacer(1, 4))
    s.append(table([["Кадастровый номер", "Площадь", "Разрешённое использование, коротко", "Проверка ограничений"],
                    ["77:05:0005007:82", "из ЕГРН", "по классификатору", "в общем контуре"],
                    ["77:05:0005007:99", "из ЕГРН", "по классификатору", "в общем контуре"],
                    ["77:05:0005007:45", "из ЕГРН", "по классификатору", "в общем контуре"],
                    ["77:05:0005007:28", "3 м²", "по классификатору", "в общем контуре"],
                    ["Вместе", "2 430 м²", "", "проверено один раз"]],
                   [W * 0.24, W * 0.14, W * 0.32, W * 0.30], bold_rows=(5,), align_right_from=4))
    s.append(P("Полный текст разрешённого использования из ЕГРН печатается примечанием, обычным регистром.", "small"))
    s.append(Spacer(1, 8))
    s.append(P("6. Книга Excel: новое устройство", "h1"))
    s.append(P("Книга офиса строится от тех же вводных, что и расчёт. Статьи идут сверху вниз, время — слева направо, "
               "рядом сводка по годам. Заголовки закреплены, у чисел форматы, печать альбомом в ширину листа.", "p"))
    s.append(Spacer(1, 3))
    s.append(table([["Лист", "Что на нём"],
                    ["Итог", "Два пути рядом, вывод, при какой ставке и цене проект выходит в ноль, графики"],
                    ["Допущения", "Только то, что нужно офису, по блокам. Поля для правки выделены цветом"],
                    ["Площади и паркинг", "Наземная, общая, арендопригодная площадь, эффективность, машино-места"],
                    ["Стройка", "Смета по статьям, график оплат по месяцам"],
                    ["Продажа", "Путь 1: продажи блоками, расходы на продажу, кредит"],
                    ["Аренда", "Путь 2: заполняемость, доход, эксплуатация, NOI, продажа здания, кредит"],
                    ["Денежный поток", "Оба пути: по месяцам и по годам, NPV и IRR"],
                    ["Чувствительность", "Аренда, заполняемость, ставка капитализации, цена, стройка, цена входа"],
                    ["Сверка", "Каждый итог книги против расчёта"]],
                   [W * 0.22, W * 0.78], align_right_from=9))
    return s


def page_no(canvas, doc):
    canvas.saveState(); canvas.setFont("R", 6.5); canvas.setFillColor(GREY)
    canvas.drawString(12 * mm, 7 * mm, "DevelopAid · образец офисного проекта · вводные восстановлены по присланным файлам")
    canvas.drawRightString(A4[0] - 12 * mm, 7 * mm, f"стр. {doc.page}")
    canvas.restoreState()


doc = SimpleDocTemplate(sys.argv[1], pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm,
                        topMargin=11 * mm, bottomMargin=12 * mm, title="Образец: офис, Пролетарский пр., вл. 20")
doc.build(teaser() + report(), onFirstPage=page_no, onLaterPages=page_no)

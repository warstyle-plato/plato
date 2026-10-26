#!/usr/bin/env python3
"""Визуальная проверка прода после выката: что видит человек на экране.

`prod_smoke.py` проверяет, что поверхности отдаются и сходятся с эталоном.
Здесь смотрится то, что владелец до сих пор ловил сам по скриншотам:
«undefined» и «NaN» в тексте, пустые блоки, прочерк вместо числа, прокрутка
вбок на телефоне, обрезанный текст, одно число по-разному на странице, в PDF
и в тизере, жаргон в видимых надписях (`docs/plain_language.md`).

Сценарии — жильё (страница по умолчанию), офис и ТЦ (тот же путь, что у
`tests/test_strategies_are_compared_everywhere.py`); каждый в чистом профиле
браузера, расчёт ждётся признаком (`tests/browser.wait_for_result`), а не
паузой. PDF и тизер — фоновой сборкой с билетом, как у кнопок страницы.
«Сводка руководству» (`/report`) — с ключом администратора в браузере, как
по кнопке «Ключ администратора»; ключ не печатается.

Красный выход (код 1) — только явная поломка: «undefined»/«NaN»/«null» в
тексте, обязательный блок пуст или отсутствует, слой страницы не нашёл узлы,
документ не собрался. Остальное — замечания: они в итоге и в JSON, но прогон
не краснят.

Запуск:  python3 scripts/prod_visual.py --base https://developaid.ru
Ключ администратора: PROD_SMOKE_ADMIN_KEY (без него расчёт за входом —
проверка пропускается с этой причиной, а не зеленеет).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import prod_smoke as smoke  # noqa: E402
from plain_language_inventory import JARGON, TELEGRAPH  # noqa: E402

BREAK, NOTE = "break", "note"
MARK = {BREAK: "❌", NOTE: "⚠️"}
DESKTOP = {"width": 1440, "height": 1000}
PHONE = {"width": 390, "height": 844}

# Ключевые строки, которые печатают и страница, и PDF, и тизер. Одно число —
# один владелец ответа: подпись та же, число обязано совпасть с точностью до
# округления показанных знаков.
KEY_LABELS = (
    "NPV проекта (до финансирования)",
    "IRR проекта (до финансирования)",
    "Чистая прибыль проекта",
    "Пик собственных средств",
    "Цена входа (участок, сделка)",
    "Максимум цены входа",
    "Запас к цене",
)


@dataclass
class Finding:
    severity: str
    surface: str
    kind: str
    where: str
    text: str
    new: bool = True  # появилось после этого выката (нет в прошлом прогоне)

    @property
    def key(self) -> str:
        """Одно и то же замечание между прогонами: цифры текста (даты,
        суммы подписи) не делают его новым."""
        return "|".join((self.surface, self.kind, self.where, re.sub(r"\d+", "#", self.text)))


def mark_new(findings: list[Finding], baseline: dict[str, Any] | None) -> None:
    """Новое — то, чего не было в прошлом прогоне: его возвращают автору
    выката. Прошлого прогона нет — автора у замечаний нет (они старше
    выката), и они идут владельцу одним списком, а не автору случайного PR."""
    known = {f.get("key") for f in (baseline or {}).get("findings", [])}
    for f in findings:
        f.new = baseline is not None and f.key not in known


# --- что видит человек: один снимок отрисованной страницы ------------------
# Видимость — по геометрии (getClientRects), а не по исходнику: скрытый узел
# со словом «undefined» человек не видит, и замечанием он не считается.
SCAN_JS = r"""(opts) => {
  const vw = document.documentElement.clientWidth;
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const shown = el => {
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return false;
    }
    return el.getClientRects().length > 0;
  };
  const where = el => {
    const parts = [];
    for (let e = el; e && e.nodeType === 1 && parts.length < 4; e = e.parentElement) {
      if (e.id) { parts.unshift('#' + e.id); break; }
      const cls = [...e.classList].slice(0, 2).join('.');
      parts.unshift(e.tagName.toLowerCase() + (cls ? '.' + cls : ''));
    }
    const sec = el.closest && el.closest('[id^="rsObj-"], .report-section, .card, #iaVerdict, section');
    const title = sec && sec.querySelector('.section-title, .report-section-title, h2, h3');
    return parts.join(' > ') + (title ? ' («' + clean(title.textContent).slice(0, 50) + '»)' : '');
  };
  const BAD = /(^|[^A-Za-zА-Яа-я])(undefined|NaN|null|Infinity|\[object Object\])(?![A-Za-zА-Яа-я])/;
  const out = {bad: [], texts: [], empty: [], clipped: [], dashes: [], pairs: [],
               overflow: null, missing_layer: '', blocks: {}};
  const seenText = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const el = n.parentElement;
    if (!el || /^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE)$/.test(el.tagName)) continue;
    const t = clean(n.textContent);
    if (!t || !shown(el)) continue;
    const m = t.match(BAD);
    if (m) out.bad.push({token: m[2], text: t.slice(0, 120), where: where(el)});
    const block = el.closest('p, li, small, button, label, .hint, .note, td, th, h2, h3, span, b, div') || el;
    const bt = clean(block.innerText);
    if (bt && !seenText.has(bt) && bt.length <= 400) { seenText.add(bt); out.texts.push({text: bt, where: where(block)}); }
  }
  document.querySelectorAll('input, select, textarea').forEach(el => {
    if (!shown(el) || el.type === 'hidden' || el.type === 'checkbox') return;
    const v = el.tagName === 'SELECT' ? (el.selectedOptions[0] || {}).text || '' : el.value;
    const m = String(v).match(BAD);
    if (m) out.bad.push({token: m[2], text: String(v).slice(0, 120), where: where(el)});
  });
  // Заголовок без содержимого: в его карточке нет ничего, кроме него.
  document.querySelectorAll('.section-title, .report-section-title, h2, h3').forEach(h => {
    if (!shown(h)) return;
    const box = h.closest('.card, .report-section, .ia-verdict, section') || h.parentElement;
    if (!box || box === document.body) return;
    const rest = clean(box.innerText).replace(clean(h.innerText), '').trim();
    const visual = box.querySelector('canvas, svg, img, table, iframe');
    if (rest.length < 3 && !visual) out.empty.push({title: clean(h.innerText).slice(0, 80), where: where(box)});
  });
  // Обрезанный текст: содержимое шире/выше своей коробки, а коробка его прячет.
  document.querySelectorAll('body *').forEach(el => {
    if (!el.children.length && el.textContent.trim() && shown(el)) {
      const cs = getComputedStyle(el);
      const hides = /hidden|clip/.test(cs.overflow + cs.overflowX + cs.overflowY);
      if (hides && cs.textOverflow !== 'ellipsis'
          && (el.scrollWidth > el.clientWidth + 2 || el.scrollHeight > el.clientHeight + 2))
        out.clipped.push({text: clean(el.textContent).slice(0, 80), where: where(el)});
    }
  });
  // Пары «подпись → значение»: строки таблиц и плитки решения.
  document.querySelectorAll('tr').forEach(tr => {
    const c = tr.querySelectorAll('td, th');
    if (c.length >= 2 && shown(tr)) out.pairs.push([clean(c[0].textContent), clean(c[c.length - 1].textContent), where(tr), false]);
  });
  document.querySelectorAll('.ia-verdict-cell').forEach(cell => {
    const l = cell.querySelector('span'), v = cell.querySelector('b');
    if (l && v && shown(cell)) out.pairs.push([clean(l.textContent), clean(v.textContent), where(cell), cell.classList.contains('wait')]);
  });
  // Прокрутка вбок: страница шире окна — кто вылез за край.
  const sw = document.documentElement.scrollWidth;
  if (sw > vw + 1) {
    const off = [];
    document.querySelectorAll('body *').forEach(el => {
      if (off.length >= 6 || !shown(el)) return;
      const r = el.getBoundingClientRect();
      if (r.right > vw + 1 && r.width > 0) {
        for (let p = el.parentElement; p; p = p.parentElement) {
          const cs = getComputedStyle(p);
          if (/auto|scroll|hidden|clip/.test(cs.overflowX)) return;  // прокрутка внутри своей коробки
        }
        off.push({where: where(el), right: Math.round(r.right)});
      }
    });
    if (off.length) out.overflow = {page: sw, view: vw, offenders: off};
  }
  const miss = document.querySelector('.ia-missing');
  if (miss && shown(miss)) out.missing_layer = clean(miss.innerText).slice(0, 400);
  const verdict = document.getElementById('iaVerdict');
  out.blocks.verdict = verdict && shown(verdict) ? {
    title: clean((document.getElementById('iaVerdictTitle') || {}).textContent),
    stamp: clean((document.getElementById('iaVerdictStamp') || {}).textContent),
    tiles: [...verdict.querySelectorAll('.ia-verdict-cell')].length,
    ceiling: clean(([...verdict.querySelectorAll('.ia-verdict-cell')]
      .find(c => clean((c.querySelector('span') || {}).textContent) === 'Максимум цены входа') || {}).textContent)} : null;
  const decision = document.getElementById('rsObj-decision');
  out.blocks.decision = decision && shown(decision) ? clean(decision.innerText).length : null;
  const card = document.querySelector('[data-strategy-compare-card]');
  out.blocks.strategy = card && shown(card) ? card.querySelectorAll('tbody tr').length : null;
  return out;
}"""


# --- судьи: чистые функции над снимком и текстом документа -----------------

def judge_scan(scan: dict[str, Any], surface: str, *, layout_only: bool = False,
               required: tuple[str, ...] = ()) -> list[Finding]:
    """Снимок страницы → замечания. `layout_only` — второй взгляд на ширине
    телефона: тексты уже проверены на широком окне, здесь только вёрстка."""
    found: list[Finding] = []
    if scan.get("overflow"):
        o = scan["overflow"]
        names = ", ".join(f"{x['where']} (до {x['right']} px)" for x in o["offenders"][:4])
        found.append(Finding(NOTE, surface, "прокрутка вбок", names,
                             f"страница шириной {o['page']} px при окне {o['view']} px"))
    for c in scan.get("clipped", [])[:8]:
        found.append(Finding(NOTE, surface, "обрезанный текст", c["where"], c["text"]))
    if layout_only:
        return found
    for b in scan.get("bad", [])[:10]:
        found.append(Finding(BREAK, surface, f"«{b['token']}» в тексте", b["where"], b["text"]))
    for e in scan.get("empty", [])[:10]:
        found.append(Finding(NOTE, surface, "заголовок без содержимого", e["where"], e["title"]))
    if scan.get("missing_layer"):
        found.append(Finding(BREAK, surface, "слой страницы не нашёл узлы", ".ia-missing",
                             scan["missing_layer"]))
    for label, value, where, wait in scan.get("pairs", []):
        if not wait and value in ("—", "-", "–", "0", "0,0", "0 млрд ₽", "0 млн ₽") and _key_label(label):
            found.append(Finding(NOTE, surface, "прочерк или ноль вместо числа", where,
                                 f"{label}: {value}"))
    blocks = scan.get("blocks") or {}
    titles = {"verdict": "Инвестиционное решение", "decision": "Решение",
              "strategy": "Сравнение стратегий"}
    for key in required:
        value = blocks.get(key)
        if value is None:
            found.append(Finding(BREAK, surface, "обязательный блок не показан", titles[key],
                                 "блока нет на странице"))
        elif (key == "verdict" and not value.get("tiles")) or (key != "verdict" and not value):
            found.append(Finding(BREAK, surface, "обязательный блок пуст", titles[key],
                                 "заголовок есть, содержимого нет"))
    verdict = blocks.get("verdict") or {}
    # «не подбирается» — у проекта нет показателя покрытия, подбирать не по чему.
    if "verdict" in required and verdict and not verdict.get("stamp") \
            and "не подбирается" not in str(verdict.get("ceiling") or ""):
        found.append(Finding(NOTE, surface, "потолок цены входа не подобран", "#iaVerdictStamp",
                             "подбор не ответил — плитки остались без подписи источника"))
    found += judge_language(scan.get("texts", []), surface)
    return found


def judge_language(texts: list[dict[str, str]], surface: str, limit: int = 8) -> list[Finding]:
    """Жаргон и телеграф — словами `scripts/plain_language_inventory.py`
    (один список на инвентаризацию и на прод)."""
    found: list[Finding] = []
    for item in texts:
        text = item["text"]
        if len(re.findall("[А-Яа-яЁё]", text)) < 12:
            continue  # подписи и числа таблиц — не фраза
        words = sorted({m.group(0) for m in JARGON.finditer(text)})
        flags = (["жаргон: " + ", ".join(words)] if words else []) + \
                (["телеграф"] if TELEGRAPH.search(text) else [])
        if flags:
            found.append(Finding(NOTE, surface, "; ".join(flags), item["where"], text[:160]))
        if len(found) >= limit:
            break
    return found


def _key_label(label: str) -> str | None:
    norm = _flat(label)
    return next((k for k in KEY_LABELS if norm.startswith(_flat(k))), None)


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\u00a0", " ").replace("\u202f", " ")).strip()


NUMBER = re.compile(
    r"(?P<num>[-−]?\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:,\d+)?|[-−]?\d+(?:,\d+)?)\s*"
    r"(?P<scale>млрд|млн|тыс\.?)?\s*(?P<unit>₽|%|x|×)?")
SCALE = {"млрд": 1e9, "млн": 1e6, "тыс": 1e3, "тыс.": 1e3}


def parse_numbers(text: str) -> list[tuple[float, float, str]]:
    """(значение, полуширина округления, род) для чисел текста. Род: «₽»,
    «%», «x» или «» — сравниваются только числа одного рода."""
    out = []
    for m in NUMBER.finditer(_flat(text)):
        raw = re.sub(r"[ \u00a0\u202f]", "", m.group("num")).replace("−", "-")
        scale = SCALE.get(m.group("scale") or "", 1.0)
        unit = m.group("unit") or ""
        unit = "x" if unit == "×" else unit
        if m.group("scale") and not unit:
            unit = "₽"
        decimals = len(raw.split(",")[1]) if "," in raw else 0
        value = float(raw.replace(",", ".")) * scale
        out.append((value, 0.5 * 10 ** -decimals * scale, unit))
    return out


def same_number(page_value: str, window: str) -> bool:
    """Есть ли в окне документа то же число, что на странице, с точностью до
    округления показанных знаков обоих."""
    shown = parse_numbers(page_value)
    if not shown:
        return True  # на странице не число («не подобран») — сверять нечего
    value, half, unit = shown[0]
    for v, h, u in parse_numbers(window):
        if u == unit and abs(v - value) <= half + h + 1e-9:
            return True
    return False


def judge_numbers(pairs: list[list[Any]], doc_text: str, surface: str, scenario: str) -> list[Finding]:
    """Одно ключевое число на странице и в документе: подпись есть в обоих —
    число обязано совпасть. Подписи нет в документе — не замечание: состав
    документа сверяет `prod_smoke.py` и тесты."""
    text = _flat(doc_text)
    found: list[Finding] = []
    seen: set[str] = set()
    for label, value, where, wait in pairs:
        key = _key_label(label)
        if not key or key in seen or wait or not parse_numbers(value):
            continue
        seen.add(key)
        windows = [text[m.end():m.end() + 90] for m in re.finditer(re.escape(_flat(key)), text)]
        if windows and not any(same_number(value, w) for w in windows):
            found.append(Finding(NOTE, surface, "число расходится со страницей", key,
                                 f"{scenario}: на странице «{value}», в документе «{windows[0].strip()[:70]}»"))
    return found


# --- прогон ---------------------------------------------------------------

SET_FIELD = r"""([id, value]) => {
  const el = document.querySelector(`[data-field="${id}"] input, [data-field="${id}"] select`);
  if (!el) throw new Error('поле ' + id + ' не найдено на странице');
  if (el.type === 'checkbox') el.checked = value; else el.value = value;
  el.onchange();
}"""

# Сценарий — шаги человека по полям, как в тестах сравнения стратегий.
SCENARIOS: dict[str, dict[str, Any]] = {
    # «Решение» объекта (`#rsObj-decision`) рисует отчёт нежилого проекта; у
    # жилья решение — блок «Инвестиционное решение».
    "жильё": {"steps": [], "required": ("verdict",)},
    "офис": {"steps": [("set", "offices_enabled", True), ("kind", "nonresidential"),
                       ("set", "offices_strategy", "direct"), ("set", "purchase_price_mln", 300)],
             "required": ("verdict", "decision", "strategy")},
    "ТЦ": {"steps": [("set", "retail_enabled", True), ("kind", "nonresidential"),
                     ("set", "retail_strategy", "income"), ("set", "purchase_price_mln", 300)],
           "required": ("verdict", "decision", "strategy")},
}


def _new_page(browser, admin_key: str, viewport: dict[str, int]):
    context = browser.new_context(viewport=viewport)
    page = context.new_page()
    if os.environ.get("HTTPS_PROXY") and os.environ.get("PROD_SMOKE_ROUTE_VIA_PYTHON", "1") == "1":
        smoke._route_via_python(page)
    if admin_key:
        page.add_init_script(
            f"try{{localStorage.setItem('plato_projects_key',{json.dumps(admin_key)})}}catch(e){{}}")
    return context, page


def check_scenario(browser, base: str, name: str, admin_key: str, out: Path,
                   log: Callable[[str], None]) -> tuple[list[Finding], dict[str, Any] | None]:
    """Главная страница одного сценария: расчёт, «Результат», снимки на
    широком окне и на телефоне. Возвращает замечания и груз для документов."""
    import browser as stand  # tests/browser.py: ожидание итога признаком

    spec = SCENARIOS[name]
    surface = f"Главная, {name}"
    context, page = _new_page(browser, admin_key, DESKTOP)
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)[:200]))
    page.on("dialog", lambda d: (errors.append("окно: " + d.message[:200]), d.dismiss()))
    try:
        page.goto(base + "/", wait_until="domcontentloaded", timeout=120_000)
        stand.wait_for_result(page, 180_000)
        for step in spec["steps"]:
            if step[0] == "set":
                page.evaluate(SET_FIELD, [step[1], step[2]])
            else:
                page.evaluate(f"() => {{ applyProjectKind({json.dumps(step[1])});"
                              " if (typeof closeProjectKindDialog==='function') closeProjectKindDialog(); }")
            stand.wait_for_result(page, 180_000)
        # «Результат» — кнопкой раздела, как человек: она же заказывает подбор потолка.
        page.evaluate("() => { const b=[...document.querySelectorAll('.ia-nav button')]"
                      ".find(x=>x.textContent.trim()==='Результат'); if(b) b.click(); else openTab('report'); }")
        try:
            page.wait_for_function("() => !!(document.getElementById('iaVerdictStamp')||{}).textContent",
                                   timeout=240_000)
        except Exception:  # noqa: BLE001 — нет подписи подбора называет судья
            log(f"{name}: подбор потолка не ответил за 240 с")
        if "strategy" in spec["required"]:
            try:
                page.wait_for_function(
                    "() => document.querySelectorAll('[data-strategy-compare-card] .strategy-points li').length > 0",
                    timeout=180_000)
            except Exception:  # noqa: BLE001
                log(f"{name}: точки безразличия стратегий не пришли за 180 с")
        scan = page.evaluate(SCAN_JS, {})
        page.screenshot(path=str(out / f"main-{name}-desktop.png"), full_page=True)
        found = judge_scan(scan, surface, required=spec["required"])
        payload = page.evaluate("JSON.parse(JSON.stringify(currentPdfReportPayload()))")
        page.set_viewport_size(PHONE)
        page.wait_for_timeout(500)  # перерисовка вёрстки, не расчёт: расчёт уже окончен
        phone = page.evaluate(SCAN_JS, {})
        page.screenshot(path=str(out / f"main-{name}-phone.png"), full_page=True)
        found += judge_scan(phone, surface + ", телефон", layout_only=True)
        found += [Finding(NOTE, surface, "ошибка скрипта страницы", "консоль", e) for e in errors[:5]]
        (out / f"main-{name}.json").write_text(json.dumps(scan, ensure_ascii=False, indent=1), encoding="utf-8")
        return found, {"payload": payload, "pairs": scan["pairs"]}
    finally:
        context.close()


def check_team_report(browser, base: str, admin_key: str, out: Path) -> list[Finding]:
    """«Сводка руководству»: ключ администратора в браузере, как по кнопке."""
    found: list[Finding] = []
    for label, viewport in (("", DESKTOP), (", телефон", PHONE)):
        context, page = _new_page(browser, admin_key, viewport)
        try:
            page.goto(base + "/report", wait_until="domcontentloaded", timeout=120_000)
            try:
                page.wait_for_function(
                    "() => { const a=document.getElementById('privateArea');"
                    " return a && !a.classList.contains('hidden') && a.innerText.replace(/\\s+/g,'').length > 200"
                    " && !document.querySelector('.msg.warn'); }", timeout=120_000)
            except Exception:  # noqa: BLE001
                login = page.evaluate("() => (document.getElementById('loginMsg')||{}).textContent||''")
                page.screenshot(path=str(out / f"report{'-phone' if label else ''}.png"), full_page=True)
                found.append(Finding(BREAK, "Сводка руководству" + label, "сводка не открылась",
                                     "#privateArea", (login or "содержимое не появилось за 120 с")[:200]))
                continue
            page.wait_for_timeout(1500)  # дорисовка фото и графиков после ответа
            scan = page.evaluate(SCAN_JS, {})
            page.screenshot(path=str(out / f"report{'-phone' if label else ''}.png"), full_page=True)
            found += judge_scan(scan, "Сводка руководству" + label, layout_only=bool(label))
        finally:
            context.close()
    return found


def build_document(base: str, kind: str, body: dict[str, Any],
                   log: Callable[[str], None]) -> tuple[bytes | None, str]:
    """PDF или тизер фоновой сборкой: 202 с билетом → опрос. Ответ — PDF или причина."""
    path = "/report/pdf" if kind == "pdf" else "/report/teaser"
    status, _, data, _ = smoke.fetch("POST", base + path, body, timeout=600, log=log)
    deadline = time.monotonic() + 1500
    while status == 202 and time.monotonic() < deadline:
        ticket = str((json.loads(data or b"{}") or {}).get("ticket") or "")
        if not ticket:
            break
        time.sleep(5)
        status, _, data, _ = smoke.fetch("GET", f"{base}{path}/{ticket}", timeout=120, log=log)
    if data.startswith(b"%PDF"):
        return data, ""
    try:
        detail = str((json.loads(data) or {}).get("detail") or "")[:200]
    except Exception:  # noqa: BLE001
        detail = data[:200].decode("utf-8", "replace")
    return None, f"HTTP {status}: {detail or 'не PDF'}"


def check_documents(base: str, name: str, page: dict[str, Any], admin_key: str, out: Path,
                    log: Callable[[str], None]) -> list[Finding]:
    found: list[Finding] = []
    body = {"session": "", "access_key": admin_key, **page["payload"]}
    for kind, title in (("teaser", "Тизер"), ("pdf", "Полный PDF")):
        surface = f"{title}, {name}"
        try:
            pdf, reason = build_document(base, kind, body, log)
        except smoke.NetworkDrop as exc:
            pdf, reason = None, str(exc)
        if pdf is None:
            found.append(Finding(BREAK, surface, "документ не собрался", "фоновая сборка", reason))
            continue
        (out / f"{kind}-{name}.pdf").write_bytes(pdf)
        text, _ = smoke.pdf_text(pdf)
        for token in ("undefined", "NaN", "[object Object]", "None ", "Infinity"):
            if token in text:
                at = text.index(token)
                found.append(Finding(BREAK, surface, f"«{token.strip()}» в тексте", "PDF",
                                     _flat(text[max(0, at - 60):at + 40])))
        found += judge_numbers(page["pairs"], text, surface, name)
    return found


def run(base: str, admin_key: str, out: Path, log: Callable[[str], None],
        scenarios: list[str], documents: bool) -> tuple[list[Finding], list[str]]:
    from playwright.sync_api import sync_playwright

    out.mkdir(parents=True, exist_ok=True)
    findings: list[Finding] = []
    skipped: list[str] = [
        "Мини-приложение Telegram: без живого аккаунта Telegram не открывается (нужна подпись initData).",
        "Состав против образцов владельца: машинного списка блоков образца в репозитории нет.",
    ]
    if not admin_key:
        skipped.append("Расчёт, документы и сводка: нет ключа PROD_SMOKE_ADMIN_KEY — всё за входом.")
        return findings, skipped
    with sync_playwright() as p:
        browser = smoke._chromium_launch(p)
        try:
            for name in scenarios:
                log(f"сценарий «{name}»")
                try:
                    found, page = check_scenario(browser, base, name, admin_key, out, log)
                except Exception as exc:  # noqa: BLE001 — сценарий падает отдельно
                    first = (str(exc).splitlines() or [""])[0][:300]
                    findings.append(Finding(BREAK, f"Главная, {name}", "сценарий не дошёл до итога",
                                            "расчёт страницы", f"{type(exc).__name__}: {first}"))
                    continue
                findings += found
                if documents and page:
                    findings += check_documents(base, name, page, admin_key, out, log)
            log("сводка руководству")
            try:
                findings += check_team_report(browser, base, admin_key, out)
            except Exception as exc:  # noqa: BLE001
                findings.append(Finding(BREAK, "Сводка руководству", "страница не открылась", "/report",
                                        f"{type(exc).__name__}: {str(exc)[:200]}"))
        finally:
            browser.close()
    return findings, skipped


def _table(findings: list[Finding], limit: int = 40) -> list[str]:
    cell = lambda s: str(s).replace("|", "\\|").replace("\n", " ")[:160]  # noqa: E731
    lines = ["| | Поверхность | Что | Где | Текст |", "|---|---|---|---|---|"]
    for f in sorted(findings, key=lambda f: f.severity != BREAK)[:limit]:
        lines.append(f"| {MARK[f.severity]} | {cell(f.surface)} | {cell(f.kind)} | {cell(f.where)} | {cell(f.text)} |")
    if len(findings) > limit:
        lines.append(f"\nЕщё {len(findings) - limit} — в `visual-result.json` артефакта.")
    return lines


def author_note(findings: list[Finding], base: str, prod: dict[str, Any]) -> str:
    """Сообщение автору выката: только новое. Пусто — писать некому и не о чем."""
    new = [f for f in findings if f.new]
    if not new:
        return ""
    breaks = sum(f.severity == BREAK for f in new)
    lines = [f"## {'❌' if breaks else '⚠️'} После выката на проде появилось новое на экране",
             "", f"Прод `{base}`, версия {prod.get('version')} ({str(prod.get('commit') or '')[:12]}). "
             f"Поломок {breaks}, замечаний {len(new) - breaks}. Этих пунктов не было в прошлом прогоне "
             "визуальной проверки — вероятнее всего, их принёс этот PR.", ""]
    lines += _table(new, 25)
    lines += ["", "Снимки страниц, PDF и тизеры — в артефакте прогона `prod-visual`."]
    return "\n".join(lines) + "\n"


def summary_markdown(findings: list[Finding], skipped: list[str], base: str,
                     prod: dict[str, Any], last_pr: str) -> str:
    breaks = [f for f in findings if f.severity == BREAK]
    head = ("❌ Визуал прода: явная поломка" if breaks else
            "⚠️ Визуал прода: замечания" if findings else "✅ Визуал прода: замечаний нет")
    lines = [f"## {head}", "",
             f"Прод `{base}`, версия {prod.get('version')} ({str(prod.get('commit') or '')[:12]}), "
             f"выкат: {last_pr}. Поломок {len(breaks)}, замечаний {len(findings) - len(breaks)}.", ""]
    new = [f for f in findings if f.new]
    old = [f for f in findings if not f.new]
    if new:
        lines += ["### Новое после этого выката", ""] + _table(new) + [""]
    if old:
        lines += ["### Было и раньше", ""] + _table(old)
    if skipped:
        lines += ["", "Не проверено:"] + [f"- {s}" for s in skipped]
    lines += ["", "Снимки страниц, PDF и тизеры — в артефакте прогона `prod-visual`."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="https://developaid.ru")
    parser.add_argument("--wait-commit", default="", help="ждать, пока /health отдаст этот коммит")
    parser.add_argument("--wait-timeout", type=int, default=600)
    parser.add_argument("--last-pr", default="")
    parser.add_argument("--scenarios", default=",".join(SCENARIOS))
    parser.add_argument("--no-documents", action="store_true", help="без PDF и тизера")
    parser.add_argument("--summary", default="")
    parser.add_argument("--json", default="")
    parser.add_argument("--out", default="visual-out")
    parser.add_argument("--baseline", default="", help="JSON прошлого прогона: что уже было до выката")
    parser.add_argument("--author-note", default="", help="куда записать сообщение автору (только новое)")
    args = parser.parse_args(argv)

    base = args.base.rstrip("/")
    admin_key = os.environ.get("PROD_SMOKE_ADMIN_KEY", "").strip()
    log = lambda message: print(message, file=sys.stderr, flush=True)  # noqa: E731
    findings: list[Finding] = []
    skipped: list[str] = []
    arrived = smoke.wait_for_commit(base, args.wait_commit, args.wait_timeout, log) \
        if args.wait_commit else None
    if arrived and arrived.status != smoke.OK:
        skipped.append(f"Всё: прод не отдаёт собранный коммит ({arrived.got}) — старую версию не смотрим.")
    else:
        scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip() in SCENARIOS]
        try:
            findings, skipped = run(base, admin_key, Path(args.out), log, scenarios, not args.no_documents)
        except Exception as exc:  # noqa: BLE001 — итог пишется всегда
            findings.append(Finding(BREAK, "Прогон", "прогон прерван", "scripts/prod_visual.py",
                                    f"{type(exc).__name__}: {str(exc)[:300]}"))
    baseline = None
    if args.baseline and Path(args.baseline).is_file():
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    mark_new(findings, baseline)
    complete = bool(admin_key) and not (arrived and arrived.status != smoke.OK) and not any(
        f.kind in ("сценарий не дошёл до итога", "прогон прерван", "страница не открылась") for f in findings)
    prod = smoke.health(base)
    if args.author_note:
        Path(args.author_note).write_text(author_note(findings, base, prod), encoding="utf-8")
    text = summary_markdown(findings, skipped, base, prod, args.last_pr or "не указан")
    print(text)
    if args.summary:
        Path(args.summary).write_text(text, encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps({
            "base": base, "prod": {k: prod.get(k) for k in ("version", "commit")},
            "last_pr": args.last_pr, "skipped": skipped,
            # Полный ли прогон: только он годится в базу «что было до выката»
            # для следующего — иначе непроверенное в следующий раз выглядит новым.
            "complete": complete,
            "findings": [{**asdict(f), "key": f.key} for f in findings]}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if any(f.severity == BREAK for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())

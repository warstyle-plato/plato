#!/usr/bin/env python3
"""Посадка ↔ нормативы: эталонные участки против того, что выдаёт сайт.

Прод-смоук (`scripts/prod_smoke.py`) проверяет, что поверхности открываются.
Здесь проверяется, что числа на них не расходятся с нормой и что ограничение,
найденное скринингом, не теряется по дороге к ТЭП. Участки и зона норматива —
в `scripts/site_norms_reference.json`; разбор и протокол — `docs/site_norms_check.md`.

Нормы записаны здесь своими числами со ссылкой на акт, а не прочитаны из движка:
проверка, которая берёт число там же, где движок, соглашается с ним по
построению. Каждое число стоит в реестре `data/normatives/registry.json`.

Только чтение, вход не нужен: скрининг, разбор кадастра, ТЭП калькулятора
ГлавАПУ и расчёт по Московской области открыты без входа.

Статусы: «ок», «нарушение» (сайт расходится с нормой или сам с собой —
красный прогон), «вопрос» (опоры в реестре нет — не вердикт), «нет данных»
(источник не ответил — причина названа; это не «ок»).

Запуск:  python3 scripts/site_norms_check.py --base https://developaid.ru
"""

from __future__ import annotations

import argparse
import http.client
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = ROOT / "scripts" / "site_norms_reference.json"

OK, VIOLATION, QUESTION, NO_DATA = "ок", "нарушение", "вопрос", "нет данных"

# 945-ПП, приложение 5 в ред. 2118-ПП (реестр moscow-945-pp, verified):
# Nп = S / (S₁ × 2,1) × 0,8; гостевые — 10 % постоянных (п. 6.2.3.2).
# S₁ = 33 м² площади квартир на человека — 2152-ПП, табл. 1.4.1 (moscow-2152-pp).
MSK_SQM_PER_PERSON = 33.0
MSK_HOUSEHOLD = 2.1
MSK_PERMANENT_FACTOR = 0.8
MSK_GUEST_SHARE = 0.10
# 945-ПП, приложение 6: встроенно-пристроенные помещения — 90 м² нежилой
# наземной площади на место, × К1 × К2 (moscow-945-pp, verified).
MSK_ATTACHED_SQM_PER_SPACE = 90.0
# 2151-ПП, табл. 1.4.1 и 1.4.2 (moscow-2151-pp; числа сверены 16.10.2026):
# мест на 1000 жителей по зонам нормирования 1 / 2.
MSK_SOCIAL_PER_1000 = {"kindergarten": {1: 44, 2: 63}, "school": {1: 90, 2: 124}}

# Флаги скрининга, которые обязаны оставить след в ТЭП: ключ — как зону
# называет НСПД (тип, имя или категория слоя), значение — слова, по которым
# след ищется в предупреждениях ТЭП.
FLAG_WORDS = {
    "особо охраняем": ("ООПТ", "особо охраняем"),
    "приаэродромн": ("приаэродромн", "аэродром"),
    "культурного наследия": ("культурного наследия", "ОКН"),
    "охранная зона": ("охранн",),
    "санитарно-защитн": ("санитарно-защитн", "СЗЗ"),
    "леснич": ("лес",),
}


@dataclass
class Check:
    cad: str
    code: str
    status: str
    text: str


# ---------------------------------------------------------------------------
# Чистые проверки: на вход — ответы сайта, на выход — список Check.


def _ceil(value: float) -> int:
    # Норма даёт число с хвостом из умножения: 134,80000000000001 → 135, а не 136.
    return math.ceil(round(value, 6))


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def check_moscow_tep(ref: dict[str, Any], tep: dict[str, Any]) -> list[Check]:
    """ТЭП калькулятора ГлавАПУ против 945-ПП и 2151-ПП, своими числами."""
    cad = ref["cad"]
    n = tep.get("normalized") or {}
    out: list[Check] = []
    apartments = _num(n.get("apartment_area_sqm"))
    if not apartments:
        return [Check(cad, "ТЭП", NO_DATA, "в ответе ТЭП нет площади квартир — нормы сверить не с чем")]

    def compare(code: str, label: str, shown: Any, expected: int, basis: str) -> None:
        got = _num(shown)
        if got is None:
            out.append(Check(cad, code, NO_DATA, f"{label}: сайт числа не отдал ({basis} даёт {expected})"))
        elif round(got) == expected:
            out.append(Check(cad, code, OK, f"{label}: {round(got)} — как по норме ({basis})"))
        else:
            out.append(Check(cad, code, VIOLATION,
                             f"{label}: сайт {round(got)}, норма {expected} ({basis})"))

    permanent = _ceil(apartments / (MSK_SQM_PER_PERSON * MSK_HOUSEHOLD) * MSK_PERMANENT_FACTOR)
    compare("П1", "постоянные места жителей", n.get("parking_permanent"), permanent,
            "945-ПП прил. 5 в ред. 2118-ПП: S / (33 × 2,1) × 0,8")
    shown_permanent = _num(n.get("parking_permanent")) or permanent
    compare("П2", "гостевые места", n.get("parking_guest"), _ceil(shown_permanent * MSK_GUEST_SHARE),
            "945-ПП п. 6.2.3.2: 10 % постоянных")
    k1, k2 = _num(n.get("parking_k1_coefficient")), _num(n.get("parking_k2_coefficient"))
    commerce = (_num(n.get("ground_commercial_np_sqm")) or 0.0)
    if k1 and k2 and commerce > 0 and not (_num(n.get("standalone_nonres_np_sqm")) or 0.0):
        compare("П3", "места встроенной коммерции", n.get("parking_attached"),
                _ceil(commerce / MSK_ATTACHED_SQM_PER_SPACE * k1 * k2),
                f"945-ПП прил. 6: {commerce:.0f} м² / 90 × К1 {k1:g} × К2 {k2:g}")
    population = math.ceil(round(apartments / MSK_SQM_PER_PERSON, 6))
    zone = int(ref.get("zone") or 0)
    if zone in (1, 2):
        for code, key, label in (("С1", "kindergarten", "места в детских садах"),
                                 ("С2", "school", "места в школах")):
            per = MSK_SOCIAL_PER_1000[key][zone]
            compare(code, label, n.get(f"required_{key}_places"), _ceil(population * per / 1000),
                    f"2151-ПП, зона {zone}: {per} на 1000 жителей × {population} жителей")
    return out


def check_drift_warning(ref: dict[str, Any], warnings: list[str]) -> list[Check]:
    """Предупреждение о расхождении формул обязано быть про этот участок.

    Состояние сверки общее на процесс: числа, найденные на одном участке, не
    должны стоять под ТЭП другого без его номера."""
    cad = ref["cad"]
    drift = [w for w in warnings if "разошлись" in str(w)]
    if not drift:
        return []
    if any(cad in str(w) for w in drift):
        return [Check(cad, "Р1", QUESTION, "формулы сервера разошлись с калькулятором ГлавАПУ на этом "
                      "участке — нужна сверка методики")]
    return [Check(cad, "Р1", VIOLATION, "под ТЭП стоит предупреждение о расхождении формул без номера "
                  "участка — его числа относятся к другому участку: " + str(drift[0])[:220])]


def check_restrict_area(ref: dict[str, Any], tep: dict[str, Any],
                        screening: dict[str, Any]) -> list[Check]:
    """Найденная скринингом зона, режущая пятно, должна дойти до калькулятора."""
    cad = ref["cad"]
    url = str((tep.get("source") or {}).get("calculator_url") or "")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    restrict = _num((query.get("restrictArea") or [None])[0])
    cut = [f for f in _findings(screening)
           if f.get("flag_class") == "economic" and "охранн" in _flag_text(f)
           and (_num(f.get("coverage_pct")) or 0) > 0]
    if not cut or restrict is None:
        return []
    share = max(_num(f.get("coverage_pct")) or 0 for f in cut)
    if restrict > 0:
        return [Check(cad, "Р2", OK, f"зона ограничений ({share:g} % участка) передана в калькулятор")]
    return [Check(cad, "Р2", VIOLATION,
                  f"скрининг нашёл охранную зону на {share:g} % участка («строить нельзя — режет "
                  f"пятно»), а калькулятор ГлавАПУ получил restrictArea=0 и посчитал ТЭП на всю площадь")]


def check_screening(ref: dict[str, Any], screening: dict[str, Any], tep_text: str) -> list[Check]:
    """Граница метода и след флагов в ТЭП."""
    cad = ref["cad"]
    parcel = (screening.get("parcels") or [{}])[0]
    if not parcel.get("found", False):
        return [Check(cad, "З0", NO_DATA, "скрининг не нашёл участок")]
    out: list[Check] = []
    findings = _findings(screening)
    verdict = parcel.get("verdict") or screening.get("verdict") or {}
    disclaimer = str(verdict.get("disclaimer") or "")
    has_zone = any("территориальн" in _flag_text(f) for f in findings)
    if not has_zone:
        if "территориальн" in disclaimer.lower():
            out.append(Check(cad, "З1", OK, "зона ПЗЗ не получена, и оговорка это говорит"))
        else:
            out.append(Check(cad, "З1", VIOLATION,
                             f"территориальная зона ПЗЗ не получена, а вердикт «{verdict.get('headline')}» "
                             "не говорит, что разрешённость застройки в зоне не проверялась"))
    expected = set(ref.get("expect_flags") or [])
    got = {f.get("flag_class") for f in findings if f.get("flag_class") in ("killer", "economic")}
    if expected != got:
        out.append(Check(cad, "З2", QUESTION,
                         f"флаги скрининга изменились: ждали {sorted(expected) or 'нет'}, "
                         f"сейчас {sorted(got) or 'нет'} — проверить источник"))
    low = tep_text.lower()
    for f in findings:
        whole = (_num(f.get("coverage_pct")) or 0) >= 99
        if f.get("flag_class") == "killer" or (f.get("flag_class") == "economic" and whole):
            text = _flag_text(f)
            words = next((w for key, w in FLAG_WORDS.items() if key in text), ())
            if words and not any(w.lower() in low for w in words):
                cover = f"{_num(f.get('coverage_pct')) or 0:g} % участка"
                out.append(Check(cad, "З3", VIOLATION,
                                 f"скрининг: «{f.get('name') or f.get('type_zone')}» на {cover} "
                                 f"({f.get('impact')}), а ТЭП и его предупреждения об этом молчат"))
    return out


def check_mo(ref: dict[str, Any], mo: dict[str, Any]) -> list[Check]:
    """Расчёт по Московской области: сам с собой и с границами умолчаний."""
    cad = ref["cad"]
    out: list[Check] = []
    vri = mo.get("vri") or {}
    delta = _num(vri.get("delta_rub"))
    used = _num(vri.get("payment_used_mln"))
    said_none = any("не определяется" in str(w) for w in vri.get("warnings") or [])
    if delta is not None and delta <= 0 and used and used > 0 and said_none:
        out.append(Check(cad, "В1", VIOLATION,
                         f"плата за смену ВРИ {used:g} млн ₽ идёт в модель («{vri.get('payment_basis')}»), "
                         "а рядом сказано «разница неположительная, плата по методике не определяется»"))
    density = _num(mo.get("density_sqm_per_ha"))
    if density == 30000.0:
        out.append(Check(cad, "Д1", QUESTION,
                         "плотность 30 000 м² квартир на гектар — умолчание без источника; таблицы 2 "
                         "РНГП МО (плотность застройки) в библиотеке норм нет"))
    balance = mo.get("balance") or {}
    remaining = _num(balance.get("remaining_ha"))
    if remaining is not None and remaining < 0:
        out.append(Check(cad, "Д2", QUESTION,
                         f"нормативные соцобъекты не помещаются на участок (остаток {remaining:g} га) — "
                         "посадка на нём физически не встаёт, а ТЭП предлагается к подстановке"))
    return out


def _findings(screening: dict[str, Any]) -> list[dict[str, Any]]:
    parcel = (screening.get("parcels") or [{}])[0]
    return [f for f in parcel.get("findings") or [] if isinstance(f, dict)]


def _flag_text(finding: dict[str, Any]) -> str:
    return " ".join(str(finding.get(k) or "") for k in ("type_zone", "name", "category")).lower()


# ---------------------------------------------------------------------------
# Сеть и прогон.


def _call(base: str, path: str, payload: dict[str, Any] | None, timeout: float) -> tuple[dict | None, str]:
    url = base.rstrip("/") + path
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8")), ""
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        return None, f"{path} ответил {exc.code}: {body}"
    except (OSError, ValueError, http.client.HTTPException) as exc:  # сеть, таймаут, не-JSON
        return None, f"{path}: {type(exc).__name__}: {exc}"


def run_parcel(base: str, ref: dict[str, Any], timeout: float) -> list[Check]:
    cad = ref["cad"]
    screening, error = _call(base, "/land/screening?cad=" + urllib.parse.quote(cad), None, timeout)
    if screening is None:
        return [Check(cad, "З0", NO_DATA, f"скрининг не ответил ({error})")]
    if ref["region"] == "mo":
        mo, error = _call(base, "/mo/calculate", {"query": cad}, timeout)
        if mo is None:
            return [Check(cad, "Т0", NO_DATA, f"расчёт МО не ответил ({error})")]
        said = (mo.get("warnings") or []) + ((mo.get("vri") or {}).get("warnings") or [])
        text = " ".join(str(w) for w in said)
        return check_screening(ref, screening, text) + check_mo(ref, mo)
    analysis, error = _call(base, "/cadastral/analyze", {"cadastral_numbers": cad}, timeout)
    if analysis is None:
        return [Check(cad, "Т0", NO_DATA, f"разбор кадастра не ответил ({error})")]
    tep, error = _call(base, "/cadastral/tep-server",
                       {"cadastral_numbers": cad, "cadastral_analysis": analysis}, timeout)
    if tep is None:
        return [Check(cad, "Т0", NO_DATA, f"ТЭП калькулятора не ответил ({error})")]
    warnings = [str(w) for w in tep.get("warnings") or []]
    text = " ".join(warnings + [str(w) for w in tep.get("notes") or []])
    return (check_screening(ref, screening, text) + check_moscow_tep(ref, tep)
            + check_drift_warning(ref, warnings) + check_restrict_area(ref, tep, screening))


def summary_markdown(base: str, checks: list[Check]) -> str:
    counts = {s: sum(c.status == s for c in checks) for s in (VIOLATION, QUESTION, NO_DATA, OK)}
    head = "❌" if counts[VIOLATION] else ("⚠️" if counts[NO_DATA] else "✅")
    lines = [f"## {head} Посадка ↔ нормативы: {base}", "",
             (f"Нарушений {counts[VIOLATION]}, вопросов {counts[QUESTION]}, "
              f"нет данных {counts[NO_DATA]}, в порядке {counts[OK]}."), "",
             "| Участок | Код | Статус | Что видно |", "|---|---|---|---|"]
    order = {VIOLATION: 0, NO_DATA: 1, QUESTION: 2, OK: 3}
    for c in sorted(checks, key=lambda c: (order[c.status], c.cad, c.code)):
        lines.append(f"| {c.cad} | {c.code} | {c.status} | {c.text.replace('|', '/')} |")
    lines += ["", "Коды и протокол — `docs/site_norms_check.md`."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base", default="https://developaid.ru")
    parser.add_argument("--only", default="", help="кадастровые номера через запятую")
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--summary", default="")
    parser.add_argument("--json", default="")
    args = parser.parse_args(argv)
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))["parcels"]
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    checks: list[Check] = []
    for ref in reference:
        if only and ref["cad"] not in only:
            continue
        started = time.monotonic()
        found = run_parcel(args.base, ref, args.timeout)
        checks += found
        worst = min((c.status for c in found), key=[VIOLATION, NO_DATA, QUESTION, OK].index, default=OK)
        print(f"{ref['cad']}: {worst}, {len(found)} проверок за {time.monotonic() - started:.0f} с", flush=True)
    text = summary_markdown(args.base, checks)
    print(text)
    if args.summary:
        Path(args.summary).write_text(text, encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps([asdict(c) for c in checks], ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    return 1 if any(c.status == VIOLATION for c in checks) else 0


if __name__ == "__main__":
    sys.exit(main())

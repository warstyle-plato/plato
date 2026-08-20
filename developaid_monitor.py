"""Недельный монитор действующего проекта: снимки выгрузок и срез по ним.

Почему сервис, а не лист в книге. Почти всё, что мы разбирали на Гродненской,
оказалось не ошибкой методики, а следствием того, что файлы — снимки разных
моментов. Реестр книги отставал от реестра РСС на два месяца, и разрыв в
454,9 млн ₽ дважды был принят за расхождение подходов. Акты переезжают между
выгрузками: между РСС на 30.06 и на 20.08 из мая ушло 124,2 млн ₽, а в июнь
пришло 38,1. Увидеть это можно только сравнением двух снимков — в одном файле
такого не видно вовсе.

Отсюда три правила.

**Снимок не перезаписывается.** Каждая загрузка кладётся отдельно, со своей
датой. История — это не удобство, а единственный способ заметить, что прошлое
переписали.

**Продажи приходят отдельно от РСС.** РСС обновляют еженедельно, финансовую
модель — раз в месяц, и в ней продажи отставали на пять месяцев. Ждать книгу
значит не знать про продажи ничего; поэтому они вводятся сами по себе, и у них
своя дата актуальности.

**Считает сервер, страница рисует.** Правило старое и уже дважды нарушенное на
этом проекте: две поверхности, считающие каждая своё, расходятся молча и обе
выглядят достоверно.
"""

from __future__ import annotations

import datetime
import json
import os
import re
from pathlib import Path
from typing import Any

import developaid_actuals as actuals

_ROOT = Path(__file__).resolve().parent
_SNAPSHOT_DIR = Path(
    os.getenv("DEVELOPAID_MONITOR_DIR", "").strip()
    or (_ROOT / "data" / "monitor")
)


def _slug(name: str) -> str:
    """Имя проекта в имя каталога. Чужого пути отсюда не построить."""
    cleaned = re.sub(r"[^0-9a-zA-Zа-яА-ЯёЁ _-]+", "", str(name or "")).strip()
    cleaned = re.sub(r"\s+", "-", cleaned).strip("-.")
    return cleaned[:64] or "project"


def _project_dir(project: str) -> Path:
    path = _SNAPSHOT_DIR / _slug(project)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _iso(value: Any) -> str:
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.strftime("%Y-%m-%d")
    return str(value or "")


def _plain(value: Any) -> Any:
    """Даты и множества к тому, что переживёт JSON."""
    if isinstance(value, dict):
        return {_iso(k) if isinstance(k, (datetime.date, datetime.datetime))
                else str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, set):
        return sorted(str(item) for item in value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return _iso(value)
    return value


def store_estimate(project: str, data: bytes, taken_at: Any,
                   filename: str = "") -> dict[str, Any]:
    """Положить выгрузку РСС снимком. Существующий снимок не трогается.

    Дата снимка — это дата, на которую собран РСС, а не дата загрузки: файл
    приносят и через неделю после того, как его выгрузили.
    """
    day = _iso(actuals._as_month(taken_at) if len(_iso(taken_at)) == 7 else taken_at)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("дата снимка нужна в виде ГГГГ-ММ-ДД")
    folder = _project_dir(project) / "estimate"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{day}.xlsx"
    if path.exists():
        raise FileExistsError(f"снимок РСС на {day} уже загружен")
    path.write_bytes(data)
    (folder / f"{day}.json").write_text(json.dumps({
        "taken_at": day, "filename": filename, "bytes": len(data),
        "loaded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }, ensure_ascii=False), encoding="utf-8")
    return {"taken_at": day, "path": str(path), "bytes": len(data)}


def store_sales(project: str, rows: list[dict[str, Any]], taken_at: Any) -> dict[str, Any]:
    """Положить продажи. Они приходят отдельно: книга обновляется реже РСС.

    Строка — месяц, число лотов, площадь и выручка. Чего не дали, того не
    выдумываем: месяц без строки остаётся неизвестным, а не нулевым.
    """
    day = _iso(taken_at)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("дата продаж нужна в виде ГГГГ-ММ-ДД")
    cleaned = []
    for row in rows or []:
        month = actuals._as_month(row.get("month"))
        if month is None:
            continue
        cleaned.append({
            "month": _iso(month),
            "units": float(row.get("units") or 0),
            "area": float(row.get("area") or 0),
            "revenue": float(row.get("revenue") or 0),
        })
    folder = _project_dir(project) / "sales"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{day}.json").write_text(
        json.dumps({"taken_at": day, "rows": cleaned}, ensure_ascii=False),
        encoding="utf-8")
    return {"taken_at": day, "months": len(cleaned)}


def snapshots(project: str) -> dict[str, list[str]]:
    """Что уже загружено, по датам снимков."""
    folder = _project_dir(project)
    def dates(kind: str, suffix: str) -> list[str]:
        path = folder / kind
        if not path.exists():
            return []
        return sorted(item.stem for item in path.glob(f"*{suffix}"))
    return {"estimate": dates("estimate", ".xlsx"), "sales": dates("sales", ".json")}


def _latest(project: str, kind: str, suffix: str, upto: str = "") -> Path | None:
    folder = _project_dir(project) / kind
    if not folder.exists():
        return None
    items = sorted(folder.glob(f"*{suffix}"))
    if upto:
        items = [item for item in items if item.stem <= upto]
    return items[-1] if items else None


def build(
    project: str,
    cut: Any,
    programme: dict[str, Any] | None = None,
    upto: str = "",
) -> dict[str, Any]:
    """Собрать срез из последнего снимка, не позднее `upto`.

    Срез считается на сервере целиком: страница получает готовые числа и ничего
    не выводит сама.
    """
    estimate_path = _latest(project, "estimate", ".xlsx", upto)
    if estimate_path is None:
        raise FileNotFoundError("нет ни одного снимка РСС")
    sales_path = _latest(project, "sales", ".json", upto)
    sales = None
    if sales_path is not None:
        stored = json.loads(sales_path.read_text(encoding="utf-8"))
        sales = {"rows": [{
            "month": actuals._as_month(row["month"]), "fact": True,
            "units": row["units"], "area": row["area"],
            "price": (row["revenue"] / row["area"]) if row["area"] else 0.0,
            "revenue": row["revenue"],
        } for row in stored["rows"]]}

    report = actuals.monitor(
        actuals.read_estimate(estimate_path),
        actuals.read_payments(estimate_path),
        actuals.read_completed_works(estimate_path),
        actuals.read_contracts(estimate_path),
        cut=cut, programme=programme, sales=sales)
    report["source"] = {
        "estimate": estimate_path.stem,
        "sales": sales_path.stem if sales_path else "",
    }
    return _plain(report)


def trend(project: str, cut: Any, programme: dict[str, Any] | None = None,
          ) -> list[dict[str, Any]]:
    """Срез по каждому снимку: видно не только «где мы», но и «куда идём».

    «Отстаём на 275,4» — цифра. «Отставание росло четыре недели» — решение.
    """
    points = []
    for day in snapshots(project)["estimate"]:
        try:
            point = build(project, cut=cut, programme=programme, upto=day)
        except Exception:
            continue
        points.append({
            "snapshot": day,
            "paid": point["money"]["paid"],
            "accepted": point["money"]["accepted"],
            "contracted": point["money"]["contracted"],
            "paid_ahead": point["money"]["paid_ahead"],
            "gap": point["schedule"].get("gap"),
        })
    return points


def moved_between_snapshots(project: str, first: str, second: str) -> dict[str, Any]:
    """Что переписали в прошлом между двумя снимками.

    Акты переезжают: между РСС на 30.06 и на 20.08 из мая ушло 124,2 млн ₽, а в
    июнь пришло 38,1. Ни один отдельный файл этого не показывает — только пара.
    """
    def monthly(day: str) -> dict[str, float]:
        path = _project_dir(project) / "estimate" / f"{day}.xlsx"
        if not path.exists():
            raise FileNotFoundError(f"нет снимка РСС на {day}")
        out: dict[str, float] = {}
        for row in actuals.read_completed_works(path)["rows"]:
            if row["construction"] and row["date"]:
                key = row["date"].strftime("%Y-%m")
                out[key] = out.get(key, 0.0) + row["amount"]
        return out

    before, after = monthly(first), monthly(second)
    months = sorted(set(before) | set(after))
    moved = [{"month": month,
              "before": before.get(month, 0.0),
              "after": after.get(month, 0.0),
              "delta": after.get(month, 0.0) - before.get(month, 0.0)}
             for month in months]
    return {
        "first": first, "second": second,
        "rows": moved,
        # Переписанным считается только прошлое: месяцы, которые в первом
        # снимке уже были закрыты. Новые месяцы — это не переписывание, это
        # просто новые данные.
        "rewritten": [item for item in moved
                      if item["before"] > 0 and abs(item["delta"]) > 1e6],
    }

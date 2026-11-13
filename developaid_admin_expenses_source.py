"""Fixed, private source proof for AHR cached cells; no finance calculation/export.

Only cf_1_new leaf codes2.4 (excluding tax2.4.5) and the three cached money
cells are projected. No caller chooses files, sheets, ranges or formulas.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import io
import json
import math
import os
import re
import stat
import zipfile

import developaid_cached_source_audit as audit

PURPOSE = "ahr_cached_cells_v1"
MAX_SOURCE = 16 * 1024 * 1024
MAX_EXPANDED = 128 * 1024 * 1024
MAX_ROWS = 20000
MAX_COLUMNS = 1000
MAX_LEAVES = 400
MAX_OUTPUT = 256 * 1024
FIELDS = (("total", "итого"), ("fact", "факт"), ("plan", "план"))
_UNIT = re.compile(r"(?<![\w])(?:(?P<scale>тыс\.?|тысяч(?:ах|и|а)?|млн\.?|миллион(?:ах|ов|а|ы)?)"
                   r"\s{0,8})?(?:руб(?:лей|ля|ль|ли|\.)?|р\.|₽)(?![\w])", re.I)


class SourceProblem(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _copy(project):
    try:
        import fcntl
    except ImportError:
        raise SourceProblem("environment_unsupported") from None
    import developaid_monitor as monitor

    reader = aliases_reader = None
    folder = lock = None
    try:
        # Use the native namespace/one-hop alias rules without _project_dir:
        # that convenience function creates missing project directories.
        base = monitor._SNAPSHOT_DIR.absolute()
        aliases_reader = audit.Reader(base, "aliases")
        aliases = aliases_reader.read(".aliases.json")
        mapping = {}
        if aliases is not None:
            value = audit._json(aliases[0])
            if not isinstance(value, dict) or not isinstance(value.get("aliases"), dict):
                raise SourceProblem("project_identity_invalid")
            mapping = value["aliases"]
        original = audit._namespace(monitor._slug(project))
        selected = audit._namespace(mapping.get(original, original))
        if selected in mapping and mapping[selected] != selected:
            raise SourceProblem("project_identity_invalid")
        reader = audit.Reader(base / selected, "finance")
        folder = reader._directory("baseline")
        if folder is None:
            raise SourceProblem("source_missing")
        # Pin the validated directory: a symlink must not redirect even the
        # sidecar lock outside this existing project's baseline.
        before = os.fstat(folder)
        lock = os.open(".schedule_versions.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                       0o600, dir_fd=folder)
        found = os.fstat(lock)
        if not stat.S_ISREG(found.st_mode) or found.st_nlink != 1:
            raise SourceProblem("unsafe_lock")
        fcntl.flock(lock, fcntl.LOCK_EX)
        finance = reader.read("baseline/finance.xlsx", max_bytes=MAX_SOURCE)
        metadata = reader.read("baseline/finance_meta.json", max_bytes=65536)
        if finance is None:
            raise SourceProblem("source_missing")
        meta = audit._json(metadata[0]) if metadata else {}
        if not isinstance(meta, dict):
            raise SourceProblem("metadata_invalid")
        if "source_sha256" in meta and meta["source_sha256"] != finance[1]["sha256"]:
            raise SourceProblem("source_pair_mismatch")
        current = reader._directory("baseline")
        try:
            after = os.fstat(current) if current is not None else None
            if after is None or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise SourceProblem("source_changed")
        finally:
            if current is not None:
                os.close(current)
        reader.check_identity()
        aliases_after = aliases_reader.read(".aliases.json")
        if (aliases[1] if aliases else None) != (aliases_after[1] if aliases_after else None):
            raise SourceProblem("source_changed")
        return finance[0], meta, {"sha256": finance[1]["sha256"], "bytes": finance[1]["bytes"],
            "metadata_sha256": metadata[1]["sha256"] if metadata else None,
            "aliases_sha256": aliases[1]["sha256"] if aliases else None,
            "namespace_sha256": hashlib.sha256(selected.encode()).hexdigest(),
            "metadata_bound_to_bytes": "source_sha256" in meta}
    except (audit.AuditError, OSError, ValueError) as exc:
        if isinstance(exc, SourceProblem):
            raise
        raise SourceProblem("source_unavailable") from None
    finally:
        if lock is not None:
            os.close(lock)
        if folder is not None:
            os.close(folder)
        if reader is not None:
            reader.close()
        if aliases_reader is not None:
            aliases_reader.close()


def _raw(cell):
    value = cell.value
    if value is None:
        return {"cached_value": None, "value_type": "missing"}
    if isinstance(value, bool):
        kind = "boolean"
    elif isinstance(value, (int, float)):
        if not math.isfinite(value):
            return {"cached_value": None, "value_type": "invalid_nonfinite"}
        kind = "number"
    elif isinstance(value, str):
        if len(value) > 128:
            return {"cached_value": None, "value_type": "text_too_long"}
        kind = "error" if cell.data_type == "e" else "text"
    elif isinstance(value, (dt.datetime, dt.date, dt.time)):
        value, kind = value.isoformat(), "date"
    else:
        return {"cached_value": None, "value_type": "unsupported"}
    return {"cached_value": value, "value_type": kind}


def _unit_evidence(rows, column_count):
    """Quote currency tokens in the fixed header, never infer a scale from code."""
    tokens, sample, count = [], [], 0
    for _, cells in rows:
        for cell in cells:
            if cell.value is None:
                continue
            count += 1
            if len(sample) < 24:
                sample.append({"cell": cell.coordinate, "type": cell.data_type,
                    "value_sha256": hashlib.sha256(str(cell.value).encode()).hexdigest()})
            if not isinstance(cell.value, str) or "://" in cell.value:
                continue
            for match in _UNIT.finditer(cell.value):
                if cell.value[match.end():].lstrip().startswith(("/", "\\")):
                    continue  # Rubles per square metre are not the money-column scale.
                scale = (match["scale"] or "").lower()
                unit = "тыс. руб." if scale.startswith("тыс") else "млн руб." if scale else "руб."
                tokens.append({"cell": cell.coordinate, "raw_token": match[0], "recognized_unit": unit})
    kinds = {item["recognized_unit"] for item in tokens}
    return {"state": "missing" if not kinds else "observed" if len(kinds) == 1 else "ambiguous",
            "recognized_unit": next(iter(kinds)) if len(kinds) == 1 else None,
            "tokens": tokens[:64], "tokens_found": len(tokens), "omitted_tokens": max(0, len(tokens)-64),
            "context": {"sheet": "cf_1_new", "first_row": 1, "last_row": rows[-1][0],
                        "column_count": column_count, "nonempty_cells": count, "cell_hash_sample": sample}}


def _cells(data):
    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if sum(item.file_size for item in archive.infolist()) > MAX_EXPANDED:
            raise SourceProblem("workbook_size_limit")
    with contextlib.closing(load_workbook(io.BytesIO(data), read_only=True, data_only=True,
                                         keep_links=False)) as book:
        if "cf_1_new" not in book.sheetnames:
            raise SourceProblem("sheet_missing")
        sheet = book["cf_1_new"]
        if sheet.max_row > MAX_ROWS or sheet.max_column > MAX_COLUMNS:
            raise SourceProblem("worksheet_size_limit")
        header, columns, header_rows = None, None, []
        for index, cells in enumerate(sheet.iter_rows(max_row=min(sheet.max_row, 80)), 1):
            header_rows.append((index, cells))
            labels = [str(c.value or "").strip().lower().replace("ё", "е") for c in cells]
            if all(name in labels for _, name in FIELDS):
                if any(labels.count(name) != 1 for _, name in FIELDS):
                    raise SourceProblem("columns_ambiguous")
                header = index
                columns = {key: labels.index(label) for key, label in FIELDS}
                break
        if columns is None:
            raise SourceProblem("columns_missing")
        units = _unit_evidence(header_rows, sheet.max_column)
        items, all_codes = [], []
        for row, cells in enumerate(sheet.iter_rows(min_row=header+1, max_col=max(2, *columns.values())+1),
                                    header+1):
            code = str(cells[2].value or "").strip().rstrip(".")
            if not re.fullmatch(r"2\.4(?:\.\d+)*", code):
                continue
            if len(code) > 96:
                raise SourceProblem("code_size_limit")
            all_codes.append(code)
            if code == "2.4.5" or code.startswith("2.4.5."):
                continue
            items.append({"code": code, "row": row, "raw_code": _raw(cells[2]),
                "cells": {key: {"cell": f"{get_column_letter(column+1)}{row}", **_raw(cells[column])}
                          for key, column in columns.items()}})
        if len({item["code"] for item in items}) != len(items):
            raise SourceProblem("codes_ambiguous")
        leaves = [item for item in items if not any(code.startswith(item["code"]+".") for code in all_codes)]
        if len(leaves) > MAX_LEAVES:
            raise SourceProblem("projection_size_limit")
        if not leaves:
            raise SourceProblem("rows_missing")
    # A cached None stays distinguishable from an uncalculated formula; the
    # formula's text, references and external links are never returned.
    by_row = {item["row"]: item for item in leaves}
    with contextlib.closing(load_workbook(io.BytesIO(data), read_only=True, data_only=False,
                                         keep_links=False)) as book:
        for row, cells in enumerate(book["cf_1_new"].iter_rows(min_row=header+1, max_row=max(by_row),
                                      max_col=max(columns.values())+1), header+1):
            if row in by_row:
                for key, column in columns.items():
                    by_row[row]["cells"][key]["formula"] = cells[column].data_type == "f"
    return leaves, {key: f"{get_column_letter(column+1)}{header}" for key, column in columns.items()}, units


def capture(project, cut, *, runtime):
    """Project/cut choose one existing source; no source selectors are supported."""
    try:
        if not isinstance(project, str) or not isinstance(cut, str):
            raise ValueError()
        day = dt.date.fromisoformat(cut)
        if day.isoformat() != cut or not project.strip() or len(project) > 200:
            raise ValueError()
    except (ValueError, TypeError):
        raise SourceProblem("request_invalid") from None
    data, meta, source = _copy(project)
    try:
        version = dt.date.fromisoformat(meta.get("taken_at"))
    except (TypeError, ValueError):
        version = None
    source.update(sheet="cf_1_new", version_date=version.isoformat() if version else None)
    result = {"purpose": PURPOSE, "schema": 1, "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "runtime": {key: str(runtime.get(key) or "")[:64] for key in ("version", "commit")},
              "cut": cut, "source": source, "rows": [], "header_cells": {},
              "unit_evidence": {"state": "not_read", "recognized_unit": None, "tokens": []},
              "values_are_raw_cached_cells": True, "financial_acceptance": False}
    if version is None:
        result["state"] = "source_date_unknown"
    elif version > day:
        result["state"] = "source_after_cut"
    else:
        try:
            result["rows"], result["header_cells"], result["unit_evidence"] = _cells(data)
        except SourceProblem:
            raise
        except Exception:
            raise SourceProblem("workbook_unreadable") from None
        result["state"] = "ok"
    _, again_meta, again_source = _copy(project)
    if any(source[key] != again_source[key] for key in ("sha256", "namespace_sha256", "aliases_sha256")) \
            or meta != again_meta:
        raise SourceProblem("source_changed")
    if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > MAX_OUTPUT:
        raise SourceProblem("projection_size_limit")
    return result

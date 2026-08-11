"""Импорт помесячного отчёта о продажах в справочник проектов.

Отчёт приходит PDF-ом. Текст в нём лежит идентификаторами глифов, поэтому его
нельзя просто вырезать: нужна карта ToUnicode из самого файла. Разбор написан на
стандартной библиотеке — тянуть парсер PDF в образ ради одной выгрузки в месяц
незачем.

Запуск:

    python -m market_search.registry_import отчёт.pdf --months 2026-06 2026-07 \\
        --out data/market/registry/2026-07.json
"""

from __future__ import annotations

import argparse
import json
import re
import zlib
from pathlib import Path
from typing import Any

from .registry import parse_sales_report


def _tounicode_map(raw: bytes) -> dict[str, str]:
    cmap: dict[str, str] = {}
    for chunk in _streams(raw):
        if b"beginbfchar" not in chunk and b"beginbfrange" not in chunk:
            continue
        text = chunk.decode("latin-1")
        for block in re.findall(r"beginbfchar(.*?)endbfchar", text, re.S):
            for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
                cmap[src.upper()] = "".join(
                    chr(int(dst[i : i + 4], 16)) for i in range(0, len(dst), 4)
                )
        for block in re.findall(r"beginbfrange(.*?)endbfrange", text, re.S):
            for low, high, start in re.findall(
                r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block
            ):
                for code in range(int(low, 16), int(high, 16) + 1):
                    cmap[f"{code:04X}"] = chr(int(start, 16) + code - int(low, 16))
    return cmap


def _streams(raw: bytes) -> list[bytes]:
    out: list[bytes] = []
    for match in re.finditer(rb"stream\r?\n", raw):
        start = match.end()
        end = raw.find(b"endstream", start)
        if end < 0:
            continue
        try:
            out.append(zlib.decompress(raw[start:end]))
        except zlib.error:
            continue
    return out


def pdf_lines(raw: bytes) -> list[str]:
    """Строки текста в порядке отрисовки.

    Числа внутри массива TJ — это кернинг, а не текст. Прежде чем это было
    учтено, «Проект» читался как «П7ро6е6кт».
    """
    cmap = _tounicode_map(raw)

    def decode(hex_text: str) -> str:
        value = hex_text.upper()
        return "".join(cmap.get(value[i : i + 4], "") for i in range(0, len(value), 4))

    lines: list[str] = []
    for chunk in _streams(raw):
        if b"TJ" not in chunk and b"Tj" not in chunk:
            continue
        text = chunk.decode("latin-1")
        pattern = r"\[((?:[^\[\]\\]|\\.)*)\]\s*TJ|<([0-9A-Fa-f]+)>\s*Tj|\(((?:\\.|[^\\()])*)\)\s*Tj"
        for match in re.finditer(pattern, text, re.S):
            if match.group(1) is not None:
                buffer = ""
                for piece in re.finditer(r"<([0-9A-Fa-f]+)>|\(((?:\\.|[^\\()])*)\)", match.group(1)):
                    buffer += decode(piece.group(1)) if piece.group(1) else (piece.group(2) or "")
                lines.append(buffer)
            elif match.group(2) is not None:
                lines.append(decode(match.group(2)))
            else:
                lines.append(match.group(3) or "")
    return lines


def build_registry_payload(raw: bytes, *, months: list[str], source: str) -> dict[str, Any]:
    rows = parse_sales_report(pdf_lines(raw), months=months, source=source)
    return {"source": source, "months": months, "projects": rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Импорт отчёта о продажах в справочник проектов")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--months", nargs="+", required=True, help="Например: 2026-06 2026-07")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source", default=None)
    args = parser.parse_args(argv)

    payload = build_registry_payload(
        args.pdf.read_bytes(),
        months=list(args.months),
        source=args.source or args.pdf.name,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Проектов: {len(payload['projects'])} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

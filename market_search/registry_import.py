"""Импорт помесячного отчёта о продажах в справочник проектов.

Отчёт приходит PDF-ом. Текст в нём лежит идентификаторами глифов, поэтому его
нельзя просто вырезать: нужна карта ToUnicode из самого файла. Разбор написан на
стандартной библиотеке — тянуть парсер PDF в образ ради одной выгрузки в месяц
незачем.

Карта неполна: в июльском отчёте пяти глифов в ней нет вовсе, и «ё» — один из
них. Пока неизвестный код молча пропускался, «Мнёвники» становились
«Мнвниками», «Палашёвский 11» — «Палашвским», а выгрузка выглядела исправной.
Теперь неопознанный глиф превращается в U+FFFD и попадает в отчёт импорта с
образцом строки: букву можно назвать вручную ключом `--glyph`.

Запуск:

    python -m market_search.registry_import отчёт.pdf --months 2026-06 2026-07 \\
        --glyph 0318=ё --out data/market/registry/2026-07.json
"""

from __future__ import annotations

import argparse
import json
import re
import struct
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


UNKNOWN_GLYPH = "�"


def pdf_lines(raw: bytes, *, glyphs: dict[str, str] | None = None) -> list[str]:
    """Строки текста в порядке отрисовки.

    Числа внутри массива TJ — это кернинг, а не текст. Прежде чем это было
    учтено, «Проект» читался как «П7ро6е6кт».

    Код, которого нет ни в карте ToUnicode, ни в `glyphs`, отдаётся как U+FFFD.
    Пропуск здесь неотличим от исправного разбора, а буква из середины названия
    уезжает в справочник и больше ни с чем не совпадает.
    """
    return [line for line, _ in _decoded_lines(raw, glyphs)]


def _glyph_map(raw: bytes, glyphs: dict[str, str] | None) -> dict[str, str]:
    cmap = dict(_tounicode_map(raw))
    for code, char in _font_glyph_map(raw, cmap).items():
        cmap.setdefault(code, char)
    cmap.update({str(code).upper(): char for code, char in (glyphs or {}).items()})
    return cmap


def _font_glyph_map(raw: bytes, known: dict[str, str]) -> dict[str, str]:
    """Буквы из встроенного шрифта — вторая карта, когда ToUnicode неполна.

    В июльском отчёте ToUnicode не знает пяти глифов, среди них «ё». Шрифт знает
    всех: таблица `cmap` ведёт от символа к номеру глифа, и её достаточно
    развернуть. Работает это, пока код в потоке и есть номер глифа (Identity),
    поэтому карта не принимается на веру: она сверяется с ToUnicode на общих
    кодах и отбрасывается целиком при расхождении. Худший исход — сегодняшний
    U+FFFD, а не подставленная не та буква.
    """
    candidate: dict[str, str] = {}
    conflicting: set[str] = set()
    for font in _font_programs(raw):
        for gid, char in _truetype_cmap(font).items():
            code = f"{gid:04X}"
            if code in candidate and candidate[code] != char:
                conflicting.add(code)
            candidate[code] = char
    for code in conflicting:
        candidate.pop(code, None)
    if not candidate:
        return {}

    overlap = [code for code in candidate if code in known]
    if len(overlap) < 20:
        return {}
    agreed = sum(1 for code in overlap if candidate[code] == known[code])
    if agreed / len(overlap) < 0.95:
        return {}
    return candidate


def _font_programs(raw: bytes) -> list[bytes]:
    return [chunk for chunk in _streams(raw) if chunk[:4] in (b"\x00\x01\x00\x00", b"true")]


def _truetype_cmap(font: bytes) -> dict[int, str]:
    """Номер глифа → символ. Разбираются форматы 4 и 12, прочие пропускаются."""
    try:
        count = struct.unpack(">H", font[4:6])[0]
        tables: dict[str, tuple[int, int]] = {}
        for index in range(count):
            entry = 12 + 16 * index
            tag = font[entry : entry + 4].decode("latin-1")
            offset, length = struct.unpack(">II", font[entry + 8 : entry + 16])
            tables[tag] = (offset, length)
        if "cmap" not in tables:
            return {}
        base = tables["cmap"][0]
        subtables = struct.unpack(">H", font[base + 2 : base + 4])[0]
        out: dict[int, str] = {}
        for index in range(subtables):
            header = base + 4 + 8 * index
            _, _, offset = struct.unpack(">HHI", font[header : header + 8])
            out.update(_cmap_subtable(font, base + offset))
        return out
    except (struct.error, IndexError, UnicodeDecodeError, ValueError):
        return {}


def _cmap_subtable(font: bytes, start: int) -> dict[int, str]:
    out: dict[int, str] = {}
    fmt = struct.unpack(">H", font[start : start + 2])[0]
    if fmt == 4:
        double = struct.unpack(">H", font[start + 6 : start + 8])[0]
        segments = double // 2
        ends = struct.unpack(f">{segments}H", font[start + 14 : start + 14 + double])
        starts = struct.unpack(
            f">{segments}H", font[start + 16 + double : start + 16 + 2 * double]
        )
        deltas = struct.unpack(
            f">{segments}h", font[start + 16 + 2 * double : start + 16 + 3 * double]
        )
        range_base = start + 16 + 3 * double
        ranges = struct.unpack(f">{segments}H", font[range_base : range_base + double])
        for index in range(segments):
            if starts[index] == 0xFFFF:
                continue
            for code in range(starts[index], ends[index] + 1):
                if ranges[index] == 0:
                    gid = (code + deltas[index]) & 0xFFFF
                else:
                    address = range_base + index * 2 + ranges[index] + (code - starts[index]) * 2
                    if address + 2 > len(font):
                        continue
                    gid = struct.unpack(">H", font[address : address + 2])[0]
                    if gid:
                        gid = (gid + deltas[index]) & 0xFFFF
                if gid:
                    out[gid] = chr(code)
    elif fmt == 12:
        groups = struct.unpack(">I", font[start + 12 : start + 16])[0]
        for index in range(min(groups, 10_000)):
            entry = start + 16 + 12 * index
            first, last, gid = struct.unpack(">III", font[entry : entry + 12])
            for code in range(first, min(last, first + 4_096) + 1):
                out[gid + (code - first)] = chr(code)
    return out


_TEXT_RE = re.compile(
    r"\[((?:[^\[\]\\]|\\.)*)\]\s*TJ|<([0-9A-Fa-f]+)>\s*Tj|\(((?:\\.|[^\\()])*)\)\s*Tj", re.S
)
_PIECE_RE = re.compile(r"<([0-9A-Fa-f]+)>|\(((?:\\.|[^\\()])*)\)")


def _decoded_lines(
    raw: bytes, glyphs: dict[str, str] | None
) -> list[tuple[str, list[str]]]:
    """Строка и коды, которые в ней не удалось опознать."""
    cmap = _glyph_map(raw, glyphs)

    def decode(hex_text: str, unknown: list[str]) -> str:
        value = hex_text.upper()
        out = ""
        for index in range(0, len(value), 4):
            code = value[index : index + 4]
            char = cmap.get(code)
            if char is None:
                unknown.append(code)
                char = UNKNOWN_GLYPH
            out += char
        return out

    lines: list[tuple[str, list[str]]] = []
    for chunk in _streams(raw):
        if b"TJ" not in chunk and b"Tj" not in chunk:
            continue
        text = chunk.decode("latin-1")
        for match in _TEXT_RE.finditer(text):
            unknown: list[str] = []
            if match.group(1) is not None:
                buffer = ""
                for piece in _PIECE_RE.finditer(match.group(1)):
                    buffer += (
                        decode(piece.group(1), unknown)
                        if piece.group(1)
                        else (piece.group(2) or "")
                    )
                lines.append((buffer, unknown))
            elif match.group(2) is not None:
                lines.append((decode(match.group(2), unknown), unknown))
            else:
                lines.append((match.group(3) or "", unknown))
    return lines


def unresolved_glyphs(raw: bytes, *, glyphs: dict[str, str] | None = None) -> dict[str, str]:
    """Коды без буквы и строка, где встретился каждый.

    Отчёт импорта показывает их человеку: «0318 → Мн�вники от Гранель». Дальше
    букву называют руками ключом `--glyph`: назвать её может только тот, кто
    видит страницу.
    """
    found: dict[str, str] = {}
    for line, unknown in _decoded_lines(raw, glyphs):
        for code in unknown:
            found.setdefault(code, " ".join(line.split()))
    return found


def build_registry_payload(
    raw: bytes, *, months: list[str], source: str, glyphs: dict[str, str] | None = None
) -> dict[str, Any]:
    rows = parse_sales_report(pdf_lines(raw, glyphs=glyphs), months=months, source=source)
    return {"source": source, "months": months, "projects": rows}


def _glyph_argument(value: str) -> tuple[str, str]:
    code, _, char = str(value).partition("=")
    if not code.strip() or not char:
        raise argparse.ArgumentTypeError("ожидается КОД=БУКВА, например 0318=ё")
    return code.strip().upper(), char


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Импорт отчёта о продажах в справочник проектов")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--months", nargs="+", required=True, help="Например: 2026-06 2026-07")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source", default=None)
    parser.add_argument(
        "--glyph",
        action="append",
        type=_glyph_argument,
        default=[],
        help="Буква для кода, которого нет в карте шрифта: --glyph 0318=ё",
    )
    args = parser.parse_args(argv)

    raw = args.pdf.read_bytes()
    glyphs = dict(args.glyph)
    payload = build_registry_payload(
        raw,
        months=list(args.months),
        source=args.source or args.pdf.name,
        glyphs=glyphs,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Проектов: {len(payload['projects'])} -> {args.out}")

    unresolved = unresolved_glyphs(raw, glyphs=glyphs)
    if unresolved:
        print(f"Неопознанных глифов: {len(unresolved)} (в тексте они стоят как {UNKNOWN_GLYPH})")
        for code, sample in sorted(unresolved.items()):
            print(f"  {code} → {sample[:80]}")
        print("  Назвать букву: --glyph КОД=БУКВА")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

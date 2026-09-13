"""Архив вложения — один ответ на «чем его открыть» и «что в нём лежит».

Выписки ЕГРН на Росэлторге так и называются и лежат в зипах (владелец,
12.09.2026). До этого `.zip` в списке вложений был, а читателя у него не было
вовсе: разбор отвечал «unsupported document format», то есть наш пробел
выглядел как чужой формат.

Три правила, за которые отвечает этот модуль.

**Что не прочитано — называется.** Архив отдаёт не только выписки: рядом лежат
отсоединённые подписи (`.sig`), таблица стилей и картинки планов. Молча
выброшенное вложение читается как его отсутствие — ровно та ошибка, что уже
стоила нам глифа без буквы и молчаливого 404 НСПД. Поэтому открытие отдаёт и
прочитанное, и отвергнутое с причиной у каждого.

**Предел объявлен, а не подразумевается.** Архив приходит с чужой машины, и
десять килобайт в нём могут развернуться в гигабайты; диск у нас уже кончался
молча. Пределы (число записей, распакованный объём, глубина вложения) стоят
числами здесь, а упёршийся в них архив называет, во что упёрся, — обрезка без
слов неотличима от пустого архива.

**Имя записи бывает не в UTF-8.** Архиватор старой школы пишет имена в кодовой
странице DOS, и `zipfile` раскодирует их как cp437 — кириллица превращается в
псевдографику. Вид записи мы определяем расширением и содержимым, поэтому на
разбор это не влияет, но на экране имя обязано читаться. Между cp866 и cp1251
выбираем по тому, чего в строке больше: у cp866 байты 0xB0–0xDF — рамки, у
cp1251 те же байты — кириллица.

Запуск проверок: python3 -m pytest tests/test_the_archive_is_opened.py -q
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field

MAX_ENTRIES = 400
MAX_TOTAL_BYTES = 120 * 1024 * 1024
MAX_DEPTH = 3

_CYRILLIC = set(range(0x0400, 0x0460))
# Рамки и заливка cp866: ровно те байты, которые в cp1251 отданы кириллице.
_BOX = set(range(0x2500, 0x25A0)) | set(range(0x2580, 0x2600))


class ArchiveProblem(RuntimeError):
    """Архив не открылся или упёрся в объявленный предел."""


@dataclass(frozen=True)
class Entry:
    name: str
    data: bytes

    @property
    def suffix(self) -> str:
        tail = self.name.rsplit("/", 1)[-1]
        return ("." + tail.rsplit(".", 1)[-1].lower()) if "." in tail else ""


@dataclass
class Opened:
    entries: list[Entry] = field(default_factory=list)
    refused: list[dict[str, str]] = field(default_factory=list)
    archives: int = 0

    def refuse(self, name: str, reason: str) -> None:
        self.refused.append({"name": name, "reason": reason})


def looks_like_zip(data: bytes) -> bool:
    """Архив опознаётся первыми байтами, и только ими.

    Подпись площадки врёт в обе стороны: PDF приходит с типом
    `application/zip`, а зип — с `application/octet-stream` и без расширения.
    Поверь типу — и читаемый PDF получит отказ «архив не открылся», то есть
    чужая подпись выдаст себя за наш формат. Первые байты не врут.
    """
    return data[:2] == b"PK" and data[2:4] in (b"\x03\x04", b"\x05\x06", b"\x07\x08")


def is_office_package(data: bytes) -> bool:
    """Не архив вложений, а документ, который просто устроен архивом.

    DOCX, XLSX и ODT — это зипы, и открывать их как архив вложений значит
    показать человеку `word/document.xml` вместо текста письма. Отличает их
    содержимое, а не расширение: в OOXML лежит `[Content_Types].xml`, в ODF —
    `mimetype`.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
            if "[Content_Types].xml" in names:
                return True
            if "mimetype" in names:
                return archive.read("mimetype")[:28].startswith(b"application/vnd.oasis")
    except Exception:  # noqa: BLE001 — негодный зип архивом вложений не становится
        return False
    return False


def _score(text: str) -> int:
    return (sum(1 for ch in text if ord(ch) in _CYRILLIC)
            - sum(1 for ch in text if ord(ch) in _BOX))


def entry_name(info: zipfile.ZipInfo) -> str:
    """Имя записи так, как его написал архиватор.

    Флаг 0x800 значит «имя в UTF-8» — тогда `zipfile` уже прочитал его верно.
    Без флага имя лежит в кодовой странице DOS, а `zipfile` раскодировал его
    как cp437; байты возвращаются и читаются заново.
    """
    if info.flag_bits & 0x800:
        return info.filename
    try:
        raw = info.filename.encode("cp437")
    except UnicodeEncodeError:
        return info.filename
    best = info.filename
    best_score = _score(best)
    for encoding in ("cp866", "cp1251"):
        try:
            candidate = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if _score(candidate) > best_score:
            best, best_score = candidate, _score(candidate)
    return best


def open_zip(data: bytes, *, name: str = "", depth: int = 1,
             opened: Opened | None = None, budget: list[int] | None = None) -> Opened:
    """Записи архива, включая вложенные архивы. Отвергнутое называется причиной."""
    out = opened if opened is not None else Opened()
    left = budget if budget is not None else [MAX_TOTAL_BYTES]
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 — негодный архив называется своей ошибкой
        raise ArchiveProblem(f"архив не открылся: {type(exc).__name__}: {exc}") from exc
    out.archives += 1
    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            inner = entry_name(info)
            full = f"{name}/{inner}" if name else inner
            if len(out.entries) + len(out.refused) >= MAX_ENTRIES:
                out.refuse(full, f"в архиве больше {MAX_ENTRIES} записей — дальше не читали")
                break
            if info.file_size > left[0]:
                out.refuse(full, f"распакованный объём вышел за {MAX_TOTAL_BYTES // (1024 * 1024)} МБ")
                continue
            try:
                body = archive.read(info)
            except Exception as exc:  # noqa: BLE001
                out.refuse(full, f"запись не прочиталась: {type(exc).__name__}: {exc}")
                continue
            left[0] -= len(body)
            # DOCX внутри архива — это документ, а не второй архив: спустись в
            # него, и вместо текста письма наружу выйдет `word/document.xml`.
            if looks_like_zip(body) and not is_office_package(body):
                if depth >= MAX_DEPTH:
                    out.refuse(full, f"вложенный архив глубже {MAX_DEPTH} уровней — не открывали")
                    continue
                try:
                    open_zip(body, name=full, depth=depth + 1, opened=out, budget=left)
                except ArchiveProblem as exc:
                    out.refuse(full, str(exc))
                continue
            out.entries.append(Entry(name=full, data=body))
    return out

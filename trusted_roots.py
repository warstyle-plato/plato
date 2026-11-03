"""Добавочные корни удостоверяющих центров — объявлены один раз.

Российский госсайт обычным хранилищем корней не проверяется: сертификат
выпущен Минцифры, и этого корня в образе нет. Лечится это добавлением корня в
доверенные, а НЕ отключением проверки — выключенная проверка молча принимает
любой сертификат, и «мы читаем каталог города» перестаёт что-либо значить.
Такого переключателя здесь нет намеренно, и тест ищет его в исходнике.

Поддержка была написана под ГИС Торги и там же и осталась, а каталог КРТ ходил
наружу мимо неё — своим клиентом без всяких корней. На проде это значило, что
прямое чтение krt.mos.ru падало ВСЕГДА (`CERTIFICATE_VERIFY_FAILED`, живой
ответ ядра 31.08.2026), и каталог целиком приезжал запасным путём — сторонним
текстовым рендерером, у которого от разметки карточки не остаётся структуры.
Отсюда и съехавшие поля, и неопознанные карточки: причина была не в разборе.

То же правило, что и везде: модуль не заводит своего пути туда, где у сервиса
уже есть общий. Здесь общий путь был, а второй модуль до него не дотянулся —
поэтому он вынесен сюда, к обоим.

Файлы кладёт владелец машины в каталог `certs` рядом с `data`; в репозиторий
они не попадают (из песочницы адреса Минцифры закрыты). Каталог перечитывается
на каждом обращении: положенный корень начинает работать без выкатки.
"""

from __future__ import annotations

import os
import pathlib
import ssl

EXTRA_CA_DIR = os.environ.get("DEVELOPAID_EXTRA_CA_DIR", "certs")
_CA_SUFFIXES = (".crt", ".cer", ".pem")


def extra_ca_files(directory: str = "") -> list[str]:
    """Корни, которые мы добавляем к системным. Пусто — значит пусто."""
    root = directory or EXTRA_CA_DIR
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    return [os.path.join(root, name) for name in names
            if name.lower().endswith(_CA_SUFFIXES)]


def load_extra_roots(
    context: ssl.SSLContext, directory: str = ""
) -> tuple[list[str], list[str]]:
    """Добавляет наши корни к контексту. Возвращает принятые и отвергнутые.

    Различать «файл лежит» и «корень принят» обязаны мы, а не читатель.
    24.08.2026 по неверному адресу скачалась HTML-страница портала и легла в
    каталог с расширением `.cer`: файл на месте, доверия не прибавилось ни на
    грамм. Отчёт «корень добавлен» на таком файле был бы враньём того же рода,
    что «критических ограничений не обнаружено» там, где не спрашивали.
    """
    accepted: list[str] = []
    rejected: list[str] = []
    for path in extra_ca_files(directory):
        try:
            raw = pathlib.Path(path).read_bytes()
        except OSError:
            rejected.append(path)
            continue
        try:
            # Двоичный или текстовый — решает содержимое, а не расширение. По
            # ссылкам из самого сертификата (Authority Information Access)
            # издатель приезжает в DER, а `cafile` понимает только PEM: годный
            # корень отвергался бы как битый, и причина была бы невнятной.
            if raw.lstrip().startswith(b"-----BEGIN"):
                context.load_verify_locations(cadata=raw.decode("ascii", "strict"))
            else:
                context.load_verify_locations(cadata=raw)
        except (OSError, ssl.SSLError, ValueError, UnicodeDecodeError):
            # Битый файл — не повод доверять всему подряд и не повод молчать.
            rejected.append(path)
        else:
            accepted.append(path)
    return accepted, rejected


def trust_context(directory: str = "") -> ssl.SSLContext:
    """Системные корни плюс наши. Проверка остаётся включённой всегда."""
    context = ssl.create_default_context()
    load_extra_roots(context, directory)
    return context

"""Добавочные корни объявлены один раз и общие для всех, кто ходит наружу.

Поддержка была написана под ГИС Торги и там же осталась, а каталог КРТ ходил
своим клиентом без всяких корней. На проде это значило, что прямое чтение
`api.krt.mos.ru` падало ВСЕГДА — `CERTIFICATE_VERIFY_FAILED`, живой ответ ядра
31.08.2026, — и каталог города целиком приезжал запасным путём, сторонним
текстовым рендерером. У того от разметки карточки не остаётся структуры:
отсюда и съехавшие поля, и неопознанные карточки. Причина была не в разборе.

Правило то же, что и везде: модуль не заводит своего пути туда, где у сервиса
уже есть общий. Здесь общий путь был, а второй модуль до него не дотянулся.
"""

from __future__ import annotations

import ssl
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import trusted_roots  # noqa: E402


def test_the_market_client_carries_our_roots() -> None:
    """Клиент модуля рынка знает про наши корни — не своей копией, а общей."""
    from market_search import http as market_http

    assert market_http._trust_context is trusted_roots.trust_context
    source = (ROOT / "market_search" / "http.py").read_text(encoding="utf-8")
    assert "context=context" in source, "контекст собран и не передан в запрос"


def test_the_auction_adapter_uses_the_same_set() -> None:
    """Второй копии правила нет: две однажды разойдутся."""
    from auction_search.adapters import torgi_gov

    assert torgi_gov.trust_context is trusted_roots.trust_context
    assert torgi_gov.load_extra_roots is trusted_roots.load_extra_roots
    assert torgi_gov.EXTRA_CA_DIR == trusted_roots.EXTRA_CA_DIR


def test_verification_is_never_switched_off() -> None:
    """Выключенная проверка молча принимает любой сертификат.

    Тогда «мы читаем каталог города» перестаёт что-либо значить: читать могли
    и не его. Переключателя нет, и его отсутствие проверяется в исходнике, а
    не только в умолчании.
    """
    context = trusted_roots.trust_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    source = (ROOT / "trusted_roots.py").read_text(encoding="utf-8")
    assert "CERT_NONE" not in source
    assert "check_hostname = False" not in source


def test_a_file_that_lies_there_is_not_a_root_that_was_accepted(tmp_path) -> None:
    """«Файл лежит» и «корень принят» — разные вещи, и различаем их мы.

    По неверному адресу однажды скачалась HTML-страница портала и легла в
    каталог с расширением `.cer`. Отчёт «корень добавлен» на таком файле был бы
    враньём того же рода, что «ограничений не обнаружено» там, где не спрашивали.
    """
    (tmp_path / "junk.cer").write_bytes(b"<!doctype html><html>portal</html>")
    (tmp_path / "notes.txt").write_bytes(b"-----BEGIN CERTIFICATE-----")
    accepted, rejected = trusted_roots.load_extra_roots(
        ssl.create_default_context(), str(tmp_path))
    assert accepted == []
    assert [Path(p).name for p in rejected] == ["junk.cer"], (
        "негодный корень не назван, либо в набор попал не сертификат")


def test_an_empty_directory_is_empty_not_an_error(tmp_path) -> None:
    """Корней нет — это норма, а не поломка: их кладёт владелец машины."""
    assert trusted_roots.extra_ca_files(str(tmp_path)) == []
    assert trusted_roots.extra_ca_files(str(tmp_path / "нет-такого")) == []


def _openssl(*args: str, cwd: Path) -> None:
    import subprocess

    subprocess.run(("openssl",) + args, cwd=cwd, check=True, capture_output=True)


def _leaf_only_chain(where: Path) -> None:
    """Корень → промежуточный → лист. Сервер пришлёт ТОЛЬКО лист."""
    _openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
             "-keyout", "root.key", "-out", "root.pem", "-subj", "/CN=Test Root",
             cwd=where)
    _openssl("req", "-newkey", "rsa:2048", "-nodes", "-keyout", "sub.key",
             "-out", "sub.csr", "-subj", "/CN=Test Sub", cwd=where)
    (where / "ext.cnf").write_text(
        "basicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign\n")
    _openssl("x509", "-req", "-in", "sub.csr", "-CA", "root.pem", "-CAkey", "root.key",
             "-CAcreateserial", "-days", "2", "-extfile", "ext.cnf", "-out", "sub.pem",
             cwd=where)
    _openssl("req", "-newkey", "rsa:2048", "-nodes", "-keyout", "leaf.key",
             "-out", "leaf.csr", "-subj", "/CN=leaf.example", cwd=where)
    _openssl("x509", "-req", "-in", "leaf.csr", "-CA", "sub.pem", "-CAkey", "sub.key",
             "-CAcreateserial", "-days", "2", "-out", "leaf.pem", cwd=where)


def test_our_root_completes_a_chain_the_server_did_not_send(tmp_path) -> None:
    """Сервер прислал один лист — цепочку достраивает наш промежуточный.

    Это и есть прод: `api.krt.mos.ru` присылает ровно один сертификат, издатель
    GlobalSign, а промежуточный `gsgccr6alphasslca2025.crt` браузер дотягивает
    по ссылке Authority Information Access — Python этого не делает. Файл лежал
    на машине с 27.08.2026, и не хватало только кода, который в этот каталог
    смотрит.

    Проверяется поведением, а не чтением исходника: без нашего каталога тот же
    лист не проходит.
    """
    import shutil
    import subprocess

    if not shutil.which("openssl"):
        pytest.skip("openssl в образе нет — проверить цепочку нечем")

    _leaf_only_chain(tmp_path)
    certs = tmp_path / "certs"
    certs.mkdir()
    shutil.copy(tmp_path / "sub.pem", certs / "gsgccr6alphasslca2025.crt")

    def verify(*anchors: Path) -> bool:
        bundle = tmp_path / "bundle.pem"
        bundle.write_bytes(b"\n".join(p.read_bytes().rstrip() for p in anchors))
        done = subprocess.run(
            ("openssl", "verify", "-CAfile", str(bundle), str(tmp_path / "leaf.pem")),
            capture_output=True, text=True)
        return done.returncode == 0

    assert not verify(tmp_path / "root.pem"), (
        "лист без промежуточного не должен проходить — иначе проверка ничего не значит")
    assert verify(tmp_path / "root.pem", certs / "gsgccr6alphasslca2025.crt")

    # И наш код кладёт промежуточный именно в хранилище контекста.
    context = ssl.create_default_context(cafile=str(tmp_path / "root.pem"))
    accepted, rejected = trusted_roots.load_extra_roots(context, str(certs))
    assert [Path(p).name for p in accepted] == ["gsgccr6alphasslca2025.crt"]
    assert rejected == []
    subjects = {entry["subject"][-1][0][1] for entry in context.get_ca_certs()}
    assert {"Test Root", "Test Sub"} <= subjects, subjects

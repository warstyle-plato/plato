"""«Приложить документ» на сайте отвечает разбором, а не HTTP 500.

Владелец 05.10.2026: тизер «Москва, Южное Медведково» в окне Платона —
«Документ не разобрался: HTTP 500». `agent_document` ссылался на `portion`,
которую объявлял только Telegram-маршрут: NameError после ответа модели.

Запуск: python3 -m pytest tests/test_the_site_document_intake_answers.py -q
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import document_intake  # noqa: E402
import main_legacy as core  # noqa: E402


def test_the_site_document_route_returns_the_read_portion(monkeypatch) -> None:
    text = "Тизер участка. Площадь участка 1,2 га. ВРИ — многоэтажная жилая застройка."
    monkeypatch.setattr(core, "_require_web_access", lambda *_a, **_k: None)
    monkeypatch.setattr(core, "usage_track", lambda *_a, **_k: None)
    monkeypatch.setattr(document_intake, "extract_text",
                        lambda _data, _name: {"text": text, "pages": 1})
    monkeypatch.setattr(core, "plato_answer", lambda _payload, _request: {"answer": ""})

    req = core.AgentDocumentRequest(
        filename="Москва, Южное Медведково_Тизер.pdf",
        content_b64=base64.b64encode(b"%PDF-1.4 stub").decode(),
    )
    got = core.agent_document(req, None)

    portion = document_intake.intake_text({"text": text})
    assert got["document"]["read_chars"] == portion["read_chars"]
    assert got["document"]["total_chars"] == portion["total_chars"]
    assert got["document"]["trimmed"] is False
    assert "text" not in got["document"]



def test_the_file_is_read_before_the_picker_is_cleared() -> None:
    """Поле файла сбрасывается ПОСЛЕ чтения. Сброс до `arrayBuffer` на iOS
    Safari освобождает файл: вторая попытка владельца 05.10.2026 упала
    «The object can not be found here»."""
    page = core.PAGE
    start = page.index("async function sendAgentDocument")
    body = page[start:page.index("\n}", start)]
    read = body.index("file.arrayBuffer()")
    cleared = body.index("getElementById('aiFile').value=''")
    assert read < cleared, "поле файла сбрасывается раньше, чем файл прочитан"

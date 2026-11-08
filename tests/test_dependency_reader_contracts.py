"""Real SDK/PDF contracts behind dependency updates (no API/network or OCR models).

Run with the declared requirements-dev lock. These checks use the installed
libraries, rather than replacing their API with a fake module.
"""
from __future__ import annotations

from io import BytesIO
import json
from types import SimpleNamespace

import pytest


def test_real_anthropic_sdk_accepts_the_production_request_and_response(monkeypatch):
    import anthropic
    import httpx2
    import main

    core = main.core
    seen = []

    def respond(request):
        seen.append(json.loads(request.content))
        return httpx2.Response(200, request=request, json={
            'id': 'msg_synthetic', 'type': 'message', 'role': 'assistant',
            'model': 'claude-haiku-4-5',
            'content': [{'type': 'text', 'text': 'Synthetic SDK result'}],
            'stop_reason': 'end_turn', 'stop_sequence': None,
            'usage': {'input_tokens': 1, 'output_tokens': 1},
        })

    # The real SDK still builds/parses its HTTP message; only the transport is local.
    real_client = anthropic.Anthropic
    with httpx2.Client(transport=httpx2.MockTransport(respond)) as transport:
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'synthetic-sdk-contract-only')
        monkeypatch.setattr(anthropic, 'Anthropic', lambda **kw: real_client(
            **kw, http_client=transport, max_retries=0))
        result = core._anthropic_direct_request({
            'model': 'gpt-5.6', 'input': [{'role': 'user', 'content': 'Synthetic'}],
            'max_output_tokens': 50, 'reasoning': {'effort': 'low'},
        })
    assert core._extract_openai_text(result) == 'Synthetic SDK result'
    assert len(seen) == 1
    assert seen[0]['thinking'] == {'type': 'adaptive'}
    assert seen[0]['output_config'] == {'effort': 'low'}
    assert seen[0]['messages'] == [{'role': 'user', 'content': 'Synthetic'}]


def test_real_pdf_parser_and_production_ocr_raster_path_keep_page_bounds(monkeypatch):
    import pymupdf
    from reportlab.pdfgen import canvas
    import pdf_ocr

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    for number in ('12345', '67890'):
        pdf.setFont('Helvetica', 24)
        pdf.drawString(72, 700, number)
        pdf.showPage()
    pdf.save()
    source = buffer.getvalue()
    with pymupdf.open(stream=source, filetype='pdf') as parsed:
        assert parsed.page_count == 2
        assert '12345' in parsed[0].get_text()
        assert '67890' in parsed[1].get_text()

    calls = []

    def recognize(args, *, input, capture_output, timeout):
        calls.append((args, input, timeout))
        assert input.startswith(b'\x89PNG\r\n\x1a\n')
        assert capture_output is True
        return SimpleNamespace(returncode=0, stdout=b'synthetic OCR\n')

    # Tesseract/language availability is outside this library regression. PDF
    # opening, page limiting and rasterization run through the production function.
    monkeypatch.setattr(pdf_ocr, 'unavailable_reason', lambda: '')
    monkeypatch.setattr(pdf_ocr, 'subprocess', SimpleNamespace(run=recognize))
    assert pdf_ocr.text(source, pages=1, dpi=72) == 'synthetic OCR\n'
    assert len(calls) == 1
    assert calls[0][0] == ['tesseract', 'stdin', 'stdout', '-l', 'rus', '--psm', '6']
    assert calls[0][2] == pdf_ocr.PAGE_TIMEOUT_SECONDS


def test_pydantic_keeps_request_validation_before_private_monitor_handlers():
    from pydantic import ValidationError
    import main

    model = main.core.MonitorCumulativeProject
    request = model.model_validate({'project': 'synthetic', 'key': 'synthetic-key'})
    assert request.model_dump() == {
        'project': 'synthetic', 'key': 'synthetic-key', 'session': '',
    }
    for invalid in ({'project': ''}, {'project': 'x', 'key': 123},
                    {'project': 'x', 'key': 'x' * 4097}):
        with pytest.raises(ValidationError):
            model.model_validate(invalid)

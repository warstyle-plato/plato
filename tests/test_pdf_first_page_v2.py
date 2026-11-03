from __future__ import annotations

import io

from PIL import Image as PILImage
from reportlab.platypus import SimpleDocTemplate

import pdf_first_page_v2 as pdf_v2


def _payload():
    return {
        "inputs": {
            "_land_lookup": {
                "results": [
                    {
                        "found": True,
                        "cadastral_number": "77:00:0000000:1",
                        "area_sqm": 10000,
                        "contour_merc": [[
                            [1000.0, 1000.0],
                            [1100.0, 1000.0],
                            [1100.0, 1100.0],
                            [1000.0, 1100.0],
                            [1000.0, 1000.0],
                        ]],
                    }
                ]
            }
        }
    }


class _Response:
    def __init__(self, body: bytes):
        self.body = body


class _Core:
    def __init__(self):
        self.calls = []

    def land_basemap(self, bbox: str = "", width: int = 1024):
        self.calls.append((bbox, width))
        image = PILImage.new("RGB", (width, 465), "white")
        out = io.BytesIO()
        image.save(out, "PNG")
        return _Response(out.getvalue())

    @staticmethod
    def _pdf_font_names():
        return "Helvetica", "Helvetica-Bold"


def test_osm_parcel_image_is_a_real_renderable_image():
    core = _Core()
    flowable = pdf_v2._osm_parcel_image(_payload(), core)

    assert flowable is not None
    assert flowable.__class__.__name__ == "Image"
    assert core.calls and core.calls[0][1] == 960

    coords = [float(value) for value in core.calls[0][0].split(",")]
    assert len(coords) == 4
    assert coords[0] < 1000 < coords[2]
    assert coords[1] < 1000 < coords[3]

    # Exercise ReportLab's lazy image loading: this is the path that was broken
    # when ImageReader was passed to Platypus Image instead of the BytesIO file.
    pdf = io.BytesIO()
    SimpleDocTemplate(pdf).build([flowable])
    assert pdf.getvalue().startswith(b"%PDF")


def test_total_expenses_uses_report_expense_structure():
    result = {
        "report": {
            "expense_structure": [
                {"label": "A", "value": 10},
                {"label": "B", "value": 15.5},
            ]
        }
    }
    assert pdf_v2._total_expenses(result) == 25.5

"""Isolated full DevelopAid V2 staging for commercial-engine QA.

The staging app serves the normal V2 web interface from the feature branch,
including the separate non-residential beta contour, without touching main.
"""

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from developaid_v2 import install as install_v2

app = FastAPI(title="DevelopAid V2 commercial engine QA")
install_v2(app)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/v2", status_code=307)


@app.get("/health", include_in_schema=False)
def health() -> dict[str, object]:
    return {"ok": True, "surface": "v2", "commercial_engine": "beta-2"}

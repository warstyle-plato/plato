from __future__ import annotations

import os
import sys
from pathlib import Path


def data_directory() -> Path:
    if os.getenv("DEVELOPAID_DESKTOP_DATA"):
        return Path(os.environ["DEVELOPAID_DESKTOP_DATA"]).expanduser().resolve()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "DevelopAid"
    if sys.platform == "win32":
        return Path(os.getenv("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "DevelopAid"
    return Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "DevelopAid"


def load_engine(directory: Path):
    # This entrypoint owns a separate process. Never start the production app
    # or inherit its credentials/proxy configuration on a personal computer.
    directory.mkdir(parents=True, exist_ok=True)
    # Workbook cell chains can exceed Python's default 1000 frames (observed
    # in report cells B9/B10 on the default project). This process runs one
    # engine job at a time; the evaluator still detects circular references.
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 10000))
    for key in ("MO_CALC_API_URL", "PLATO_AI_URL", "PLATO_AI_PROXY_SECRET",
                "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN",
                "DEVELOPAID_ADMIN_KEY", "DEVELOPAID_ADMIN_IDS"):
        os.environ.pop(key, None)
    for key in ("AUCTION_KRT_WEEKLY", "AUCTION_KRT_WATCH", "NORMATIVES_WATCH",
                "NAGATINO_EGRN_READ", "GLAVAPU_HEADLESS"):
        os.environ[key] = "0"
    for key, name in (("DATA_DIR", "data"), ("DEVELOPAID_PROJECTS_DIR", "legacy_projects"),
                      ("PLATON_STATE_DIR", "platon"), ("DEVELOPAID_MONITOR_DIR", "monitor")):
        os.environ[key] = str(directory / name)
    import main
    core = main.core
    fonts = Path(__file__).parent / "fonts"
    core._PDF_FONT_DIRS = (str(fonts), *core._PDF_FONT_DIRS)
    from pdf_first_page_v2 import install
    install(core)
    return core

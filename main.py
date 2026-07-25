from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent


def _load_module(name: str, path: Path, *, package_dir: Path | None = None):
    kwargs = {}
    if package_dir is not None:
        kwargs["submodule_search_locations"] = [str(package_dir)]
    spec = importlib.util.spec_from_file_location(name, path, **kwargs)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"DevelopAid: cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if __name__ == "developaid_legacy":
    _core = _load_module("developaid_core", _ROOT / "main_legacy.py")
    globals().update({key: value for key, value in vars(_core).items() if key not in {"__name__", "__loader__", "__package__", "__spec__"}})
else:
    _entry = _load_module(
        "developaid_entry",
        _ROOT / "main" / "__init__.py",
        package_dir=_ROOT / "main",
    )
    app = _entry.app

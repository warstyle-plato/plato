from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_RUNTIME_VERSION = "0.12.36"


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

    class _LegacyProxy(types.ModuleType):
        def __setattr__(self, name, value):
            core = self.__dict__.get("_core")
            if core is not None and name not in {
                "__class__",
                "__dict__",
                "__name__",
                "__loader__",
                "__package__",
                "__spec__",
                "_core",
            }:
                setattr(core, name, value)
            super().__setattr__(name, value)

    _module = sys.modules[__name__]
    _module.__class__ = _LegacyProxy
    globals().update({
        key: value
        for key, value in vars(_core).items()
        if key not in {"__name__", "__loader__", "__package__", "__spec__"}
    })
else:
    _entry = _load_module(
        "developaid_entry",
        _ROOT / "main" / "__init__.py",
        package_dir=_ROOT / "main",
    )
    app = _entry.app
    app.version = _RUNTIME_VERSION

    _original_runtime_handler = _entry.legacy._telegram_handle_message

    def _runtime_handler(update):
        chat_id, user_id, text, callback = _entry._message_parts(update)
        if callback is None and text.lower() == "/status":
            _entry._send_message(
                chat_id,
                "<b>DevelopAid bot:</b> подключён\n"
                f"Telegram ID: {user_id}\n"
                f"Версия: {_RUNTIME_VERSION}",
            )
            return
        return _original_runtime_handler(update)

    _entry.legacy._telegram_handle_message = _runtime_handler

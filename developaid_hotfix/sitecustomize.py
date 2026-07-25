from __future__ import annotations

import sys
import traceback


def _run_patch(label: str, callback) -> None:
    try:
        callback()
    except Exception:
        print(f"DevelopAid startup patch failed: {label}", file=sys.stderr)
        traceback.print_exc()


from developaid_runtime_patch import apply_patch as apply_base_patch
from developaid_answer_webapp_patch import apply_patch as apply_answer_webapp_patch

_run_patch("base Telegram help/close patch", apply_base_patch)
_run_patch("Telegram answerWebAppQuery patch", apply_answer_webapp_patch)

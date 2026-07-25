from __future__ import annotations

import main_runtime as runtime
from telegram_result_context_fix import apply

apply(runtime)
app = runtime.app

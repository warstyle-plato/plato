from __future__ import annotations

import main_runtime as runtime
from telegram_result_context_fix import apply as apply_telegram_context
from excel_model_export import apply as apply_excel_export

apply_telegram_context(runtime)
apply_excel_export(runtime)
app = runtime.app

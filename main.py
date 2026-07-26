from __future__ import annotations

import main_runtime as runtime
from telegram_result_context_fix import apply as apply_telegram_context
from excel_model_export import apply as apply_excel_export
from mo_cadastral_routing import apply as apply_mo_cadastral_routing
from mo_egrn_hotfix import apply as apply_mo_egrn_hotfix
from mo_flow_restore import apply as apply_mo_flow_restore

apply_telegram_context(runtime)
apply_excel_export(runtime)
apply_mo_cadastral_routing(runtime)
apply_mo_egrn_hotfix(runtime)
apply_mo_flow_restore(runtime)
app = runtime.app

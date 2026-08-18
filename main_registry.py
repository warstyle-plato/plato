"""DevelopAid application entrypoint with persistent Telegram user registry."""

import main as _base
from developaid_v2 import install as install_v2
from market_search import install as install_market_search
from market_search.ui_v6 import install as install_market_ui
from telegram_user_registry import install

app = _base.app
core = _base.core
registry = install(_base)
market_search = install_market_search(app)
install_market_ui(core)


def _cadastre_from_egrn(number: str):
    """Участок по кадастровому номеру — тем же путём, что ТЭП и анализ территории."""
    try:
        features = core._nspd_search_features(number)
    except Exception:
        return None
    for feature in features or []:
        parcel = core._normalize_nspd_feature(feature)
        if parcel.get("center"):
            return parcel
    return None


market_search.cadastre_lookup = _cadastre_from_egrn
install_v2(app)

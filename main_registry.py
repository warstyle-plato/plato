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


def _plato_ask(message: str, request):
    """Вопрос Платону из кабинета рынка.

    Вводные и ТЭП подставляются умолчаниями движка: без них
    `_run_authoritative_model` пересчитывает модель ни из чего и падает
    пятисоткой. Вопрос при этом о рынке, а не о проекте, поэтому конкретные
    вводные роли не играют — важно, чтобы модель было из чего собрать.
    """
    payload = core.AgentChatRequest(
        message=message,
        inputs=dict(core.DEFAULT_INPUTS),
        tep={key: dict(value) for key, value in core.TEP_DEFAULT.items()},
    )
    return core.plato_answer(payload, request)


market_search.cadastre_lookup = _cadastre_from_egrn
market_search.plato_ask = _plato_ask
install_v2(app)

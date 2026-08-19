"""DevelopAid application entrypoint with persistent Telegram user registry."""

import os

import main as _base
from developaid_v2 import install as install_v2
from guide import install as install_guide
from ia_preview import install as install_ia_preview
from market_search import install as install_market_search
from market_search.ui_v6 import install as install_market_ui, install_price_hint
from mpt_bot_menu import install as install_mpt_bot_menu
from mpt_extension import install as install_mpt
from telegram_user_registry import install

app = _base.app
core = _base.core
install_mpt(_base)
install_mpt_bot_menu(_base)
registry = install(_base)
market_search = install_market_search(app)

# Вкладка «Рынок» — сниппетный конвейер, который мы списываем: приёмка по нему
# красная, и в production ему пока нечего делать. Умолчание выключено, и это
# не осторожность, а правило: отсутствующая переменная не должна читаться как
# согласие. Иначе вкладка появляется у брокеров ровно тогда, когда переменную
# забыли — при пересоздании контейнера, на новой машине, после чистки `.env`.
# Стенду превью она нужна, и там она включается явно: `MARKET_TAB_ENABLED=1`.
if os.getenv("MARKET_TAB_ENABLED", "").strip().lower() in ("1", "true", "yes", "on"):
    install_market_ui(core)
else:
    # Кнопка ориентира цены нужна и без панели: это одно число у поля модели.
    install_price_hint(core)


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
# Тестовый адрес новой информационной архитектуры: та же PAGE, другой порядок.
install_ia_preview(app, core)
# Руководство пользователя — обычная страница приложения на /guide.
install_guide(app, core)

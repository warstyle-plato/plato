"""DevelopAid application entrypoint with persistent Telegram user registry."""

import main as _base
from developaid_v2 import install as install_v2
from guide import install as install_guide
from ia_preview import install as install_ia_preview
from market_search import install as install_market_search
from market_search.bot import install as install_market_bot
from market_search.plato_tool import install as install_market_plato_tool
from market_search.ui_v6 import install as install_market_ui
from mpt_bot_menu import install as install_mpt_bot_menu
from mpt_extension import install as install_mpt
from telegram_user_registry import install

app = _base.app
core = _base.core
install_mpt(_base)
install_mpt_bot_menu(_base)
registry = install(_base)
install_v2(app)
# Оценка рынка конкурентов. Конвейер один, поверхностей три: панель «Рынок» на
# странице, инструмент Платона Сергеевича и команда бота. Разные расчёты на
# одних данных уже давали два достоверных на вид ответа с разными числами —
# служба заводится один раз и передаётся всем троим.
#
# Ставится до слоя перестройки: тот снимает копию `core.PAGE` при установке, и
# вкладка, добавленная после него, на основном интерфейсе просто не появится.
market_search = install_market_search(app)
install_market_ui(core)
install_market_plato_tool(core, market_search)
install_market_bot(_base, market_search)
# Тестовый адрес новой информационной архитектуры: та же PAGE, другой порядок.
install_ia_preview(app, core)
# Руководство пользователя — обычная страница приложения на /guide.
install_guide(app, core)

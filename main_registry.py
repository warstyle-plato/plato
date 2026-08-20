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
def _address_suggest(query: str, limit: int):
    """Адресные подсказки кабинета — тот же DaData, что у движка и ленты `/ia`.

    Свой геокодер в модуле рынка не заводится: две реализации разошлись бы на
    нормализации, и одна строка приводила бы к разным точкам.

    Без ключа движок возвращает пустой список — и «ключа нет» стало бы
    неотличимо от «адрес не найден». Отсутствие доступа называется вслух.
    """
    if not os.getenv("DADATA_API_KEY", "").strip():
        raise RuntimeError("адресные подсказки выключены: не задан DADATA_API_KEY")
    return core._geocode_dadata(query, limit)


market_search.address_suggest = _address_suggest


def _geocode_for_market(query: str):
    """Адрес объекта отчёта — движковой цепочкой: Яндекс, DaData, Nominatim.

    Свой геокодер у модуля рынка знает только Яндекс и Nominatim, а ключа
    Яндекса на ядре нет — значит на деле один Nominatim. «Москва, Саввинская
    наб, д 25» он не находит вовсе, и кабинет отвечал «место не найдено» на
    адрес, который основной сервис разбирает без запинки.

    Третий случай одной и той же ошибки за день: своё правило там, где уже
    есть общее. Первым был разбор ввода у кнопки цены, вторым — подсказки.
    """
    from market_search.geocoder import GeocodingError, GeoPoint

    found, warnings = core._geocode_address(query, 1)
    if not found:
        raise GeocodingError("; ".join(warnings) or f"Адрес «{query}» не найден")
    row = found[0]
    return GeoPoint(
        latitude=float(row["lat"]),
        longitude=float(row["lng"]),
        display_name=str(row.get("label") or query),
        provider=str(row.get("provider") or "движок"),
    )


def _local_asset(url: str):
    """Байты того, что приложение отдало бы по этому адресу.

    Нужны печати: Chromium, печатающий PDF, — не браузер человека, и за нашей
    же картинкой по сети он не пойдёт. Крючок, а не свой путь к файлам: карту
    рисует движок (`/land/basemap`), эмблему и баннер он же отдаёт из `assets`,
    и знать, где что лежит, модулю рынка незачем — это уже четвёртый случай
    того же правила.
    """
    from urllib.parse import parse_qs, urlparse

    parts = urlparse(url)
    query = parse_qs(parts.query)
    try:
        if parts.path == "/land/basemap":
            answer = core.land_basemap(
                bbox=(query.get("bbox") or [""])[0],
                width=int((query.get("width") or ["1024"])[0]),
            )
        elif parts.path.startswith("/assets/"):
            answer = core.developaid_asset(parts.path.rsplit("/", 1)[-1])
        else:
            return None
    except Exception:
        # Не отдалось — пусть картинки в PDF не будет. Печать целого отчёта
        # дороже одной иллюстрации, а подставлять пустоту вместо карты нельзя.
        return None
    return getattr(answer, "body", None)


market_search.local_asset = _local_asset
market_search.geocode_address = _geocode_for_market
install_v2(app)
# Тестовый адрес новой информационной архитектуры: та же PAGE, другой порядок.
install_ia_preview(app, core)
# Руководство пользователя — обычная страница приложения на /guide.
install_guide(app, core)

"""Маршруты расчёта: /current-key-rate и /calculate.

Ключевая ставка ЦБ и расчёт экономики за входом через бота.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён на том месте, где этот код стоял раньше
(`_engine_part("calc_routes")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

@app.get("/current-key-rate")
def current_key_rate() -> dict[str, Any]:
    return fetch_current_cbr_key_rate()


@app.post("/calculate")
def calculate_api(req: CalcRequest) -> dict:
    # Экономика — за входом через бота: участок, ТЭП и ограничения открыты и
    # показывают, что мы умеем, а вывод о деньгах уже принадлежит конкретному
    # человеку (решение владельца, 18.08.2026). Без токена бота гейт честно
    # выключен — проверять подпись нечем.
    # Право на участок (21.10.2026): после входа — бесплатный участок, дальше
    # оплата участка или подписка. Решает одна функция для всех поверхностей.
    require_calc_access(req.session, req.access_key, "Расчёт экономики", inputs=req.inputs)
    # Учёт шагов с сайта: без него от публикации на пятьсот человек остаётся
    # число заходов, а где люди останавливаются — неизвестно. Пишем на сервере,
    # а не на странице: браузер закрывают на полуслове, и событие теряется.
    usage_track("calc", surface="site",
                chat_id=_web_identity_chat_id(str(getattr(req, "session", "") or "")))
    return calculate(req)


class TepCorrectionsNote(BaseModel):
    session: str = ""
    text: str = ""
    corrections: list[dict[str, Any]] = []


@app.post("/tep-corrections")
def tep_corrections_api(req: TepCorrectionsNote) -> dict:
    """Запись в журнал: загруженный проект нёс устаревшие производные числа.

    Таблица ТЭП их не подписывает (решение владельца, 16.10.2026): человеку
    один раз говорит уведомление, а журналу — эта запись. Список приходит тем
    же, что показало уведомление (`derivedCorrections` страницы). Записи не
    больше десятка и только числа — журнал не становится складом чужого текста.
    """
    rows = []
    for item in (req.corrections or [])[:10]:
        try:
            rows.append({"key": str(item.get("key") or "")[:40],
                         "field": str(item.get("field") or "")[:40],
                         "was": float(item.get("was")), "now": float(item.get("now"))})
        except (TypeError, ValueError):
            continue
    if rows:
        usage_track("tep_corrections", surface="site", text=req.text,
                    chat_id=_web_identity_chat_id(str(req.session or "")),
                    corrections=rows)
    return {"ok": True, "recorded": len(rows)}

"""Операционная модель проекта: build_operating_model.

Помесячная операционная модель: выручка, расходы, графики по продуктам
и объектам — основа финансирования и экономики.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён на том месте, где этот код стоял раньше
(`_engine_part("operating_model")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

# Подпись выкупа ЗУ/ОКС — по происхождению числа, а не по догадке. Сумма из
# контура КРТ — оценка по кадастровой стоимости: она входит в стоимость
# сделки, и подпись «не цена сделки» рядом со строкой «Стоимость сделки»
# противоречила итогу. Одна подпись на все поверхности: страница, PDF,
# Telegram, Платон читают `deal.buyout_label`.
DEAL_BUYOUT_LABEL = "Выкуп ЗУ/ОКС у третьих лиц"
# Итог сделки — строкой «Итого» под частями, а не третьей статьёй рядом с ними.
DEAL_TOTAL_LABEL = "Итого стоимость сделки (цена + выкуп)"
DEAL_BUYOUT_BASIS_LABELS = {
    "krt_cadastral": "оценка по кадастровой стоимости объектов контура КРТ",
    "manual": "вписан вручную",
}


def deal_buyout_basis(x: dict) -> str:
    """Чем задан выкуп: `krt_cadastral`, `manual` или пусто, когда выкупа нет.

    Контурная оценка — пока число равно записанному контуром; правка руками
    делает его ручным. Очередь получает основание от проекта
    (`_land_buyout_basis`): её доля выкупа с маркером контура не совпадает.
    """
    if n(x, "land_buyout_mln") <= 0:
        return ""
    inherited = str((x or {}).get("_land_buyout_basis") or "")
    if inherited in DEAL_BUYOUT_BASIS_LABELS:
        return inherited
    marker = (x or {}).get("_land_buyout_source")
    if isinstance(marker, dict) and marker.get("kind") == "krt_contour":
        try:
            if abs(float(marker.get("value")) - n(x, "land_buyout_mln")) < 1e-6:
                return "krt_cadastral"
        except (TypeError, ValueError):
            pass
    return "manual"


def deal_buyout_label(basis: str) -> str:
    """Строка выкупа с основанием суммы: «Выкуп … — оценка по кадастровой стоимости …»."""
    note = DEAL_BUYOUT_BASIS_LABELS.get(basis)
    return f"{DEAL_BUYOUT_LABEL} — {note}" if note else DEAL_BUYOUT_LABEL


def build_operating_model(x: dict, t: dict, rates: list[dict[str, Any]] | None = None) -> dict:
    project_start = d(x.get("project_start", "2027-01-01"))
    # Минимум применяется здесь, а не только при разносе расходов: РнС в день
    # старта — это и есть тот нулевой период, на котором книга и движок
    # расходятся целиком.
    permit = project_permit_date(x)
    sales_start = add_months(permit, int(n(x, "sales_lag_months", 0)))
    rve = add_months(permit, int(n(x, "construction_months", 24)))
    residual = int(n(x, "residual_sales_months", 6))
    end = add_months(rve, max(residual + 3, 12))

    apartment = t.get("apartments", {})
    commercial = t.get("ground_commercial", {})
    underground = t.get("underground_parking", {})
    storage = t.get("storage", {})

    core_above_gns = n(apartment, "gns") + n(commercial, "gns")
    # Своего гаража у встроенной коммерции нет: её машино-места лежат в общем
    # подземном паркинге проекта, который тут и стоит. Отдельный гараж был бы
    # вторым счётом тех же мест, а приобъектная стоянка — асфальт, метров она
    # не занимает вовсе.
    # Что под землёй — по размещению кладовых ЭТОГО проекта: наземные лежат
    # внутри ГНС квартир и строятся по наземной ставке (`underground_products`).
    core_under_gns = sum(n(t.get(key) or {}, "gns") for key in underground_products(x))
    core_total_gns = core_above_gns + core_under_gns
    # Благоустройство считается по физической площади двора: она своя база и в
    # строительный объём не входит вовсе. Ответ объявлен один раз и назван
    # основанием — «столько-то на человека × столько-то человек».
    landscaping_sqm, landscaping_basis = landscaping_area(x, t)
    # Деньги считаются ЗДЕСЬ и один раз, вместе со своим основанием. Прежде
    # читался только рубль (`landscaping_cost(...)[0]`), а основание брали у
    # ПЛОЩАДИ — и при заданной ставке подпись советовала «задайте ставку на
    # метр ГНС», то есть сделать то, что уже сделано. Двор и деньги отвечают
    # на разные вопросы, значит и оснований у них два.
    landscaping_amount, landscaping_money_basis = landscaping_cost(
        x, t, project_above_gns(t))

    revenue: dict[date, float] = defaultdict(float)
    revenue_by_product: dict[str, float] = {}
    revenue_product_schedules: dict[str, dict[date, float]] = {}
    quantity_product_schedules: dict[str, dict[date, float]] = {}

    def add_product(
        name: str,
        schedule: dict[date, float],
        physical_schedule: dict[date, float],
    ) -> None:
        revenue_product_schedules[name] = dict(schedule)
        quantity_product_schedules[name] = dict(physical_schedule)
        revenue_by_product[name] = sum(schedule.values())
        for month, value in schedule.items():
            revenue[month] += value

    share = n(x, "share_before_rve_pct", 85) / 100
    # Запасное значение — то же умолчание, что видит форма, а не своя константа.
    growth_pre = n(x, "monthly_growth_pre_pct", DEFAULT_INPUTS["monthly_growth_pre_pct"]) / 100
    # Рост после РВЭ — из годовой «Инфляции после РВЭ», одной вводной.
    growth_post = growth_post_monthly_pct(x) / 100
    # Сезонность и смещение темпа были в интерфейсе, но на расчёт не влияли:
    # уходили только в шаблон ПЛАТО. Из-за этого шаблон и модель по одним и тем
    # же вводным давали разную выручку.
    seasonal = n(x, "seasonal_reduction_pct", -15) / 100
    pace = n(x, "pace_adjustment_pct", 25) / 100

    # Лестница цены квартир — с неё идея и началась (владелец, 02.09.2026:
    # «делать и квартирам — на них и строилась эта идея»). Этапы строительной
    # готовности — как в полях шаблона ПЛАТО, по их образцу. Одна на все
    # четыре основных продукта, как и ежемесячный рост: шаблон ведёт цены
    # паркинга и кладовых от цены квартир той же пропорцией.
    core_factor, core_stage_rows, core_ladder_warnings = stage_ladder_factor(
        [x.get(f"growth_stage{k}_pct") for k in (1, 2, 3, 4)],
        permit, int(n(x, "construction_months", 24)))
    core_schedule_note = {
        "sales_profile": "",
        "price_stages": [{**row, "date": row["date"].isoformat()} for row in core_stage_rows],
        "price_ladder": stage_ladder_text(core_stage_rows),
        "profile_applied": False,
        "steps_applied": core_factor is not None,
        "warnings": core_ladder_warnings,
    }

    def core_product(name: str, quantity: float, price_th: float) -> None:
        # Все четыре основных продукта индексируются одним темпом: шаблон ведёт
        # цены паркинга и кладовых от цены квартир той же пропорцией.
        add_product(name, sales_schedule(
            quantity, price_th * 1000, sales_start, rve, share, residual,
            growth_pre, growth_post, seasonal, pace, price_factor=core_factor,
        ), quantity_schedule(quantity, sales_start, rve, share, residual, seasonal, pace))

    core_product("apartments", n(apartment, "saleable"), n(x, "apartment_price_th"))
    core_product("ground_commercial", n(commercial, "saleable"), n(x, "commercial_price_th"))
    # Гостевые места не продаются: по нормативу они обслуживают посетителей и
    # остаются общим имуществом. Модель продавала весь паркинг целиком — на
    # 369 местах это 34 несуществующие продажи (владелец, 21.08.2026). В книгу
    # правило было записано давно, а движок его не исполнял.
    core_product("underground_parking", underground_saleable_spaces(underground),
                 n(x, "parking_price_th"))
    core_product("storage", storage_saleable_spaces(storage), n(x, "storage_price_th"))

    standalone_capex = {}
    # Гараж объекта копится ОТДЕЛЬНО от здания: удельная «на свою ГНС»
    # обязана воспроизводить вводную ставку, а гараж считается по подземному
    # метру. Сложенные в одно число, они дают третий показатель, который не
    # сравнить ни со сметой, ни со своей же вводной — 249 тыс ₽/м² при
    # вводной 200.
    standalone_garage_capex: dict[str, float] = {}
    object_schedule_notes: dict[str, dict[str, Any]] = {"core": core_schedule_note}

    # Паркинг объектов разложен по строкам ТЭП раньше (`apply_object_parking`),
    # и деньги его оттуда ЧИТАЮТ, а не считают второй раз: два счёта одной
    # величины однажды разошлись бы, и обе цифры выглядели бы верными.
    # Продаваемая объекта — `standalone_object_saleable`: та же формула, что
    # в книге, на той же GBA вводных, что и себестоимость объекта.
    def object_parking_row(tep_key: str) -> dict[str, Any]:
        return (t or {}).get(tep_key) or {}

    def object_saleable(tep_key: str, field: str) -> float:
        return standalone_object_saleable(x, t, tep_key)

    def object_parking_capex(tep_key: str) -> float:
        """Свой подземный паркинг объекта стоит подземного метра.

        Отдельной ставки у приобъектного паркинга нет — она была бы числом,
        которого никто не задавал. Метры считаются по ставке подземной части
        проекта, и это названо на экране.
        """
        return n(object_parking_row(tep_key), "under_gns") * n(x, "main_under_th_per_sqm") * 1000

    def object_schedule(prefix: str, sales_start: date, construction_start: date,
                        construction_months: int,
                        ) -> tuple[dict[date, float] | None, Callable[[date], float] | None]:
        """Профиль продаж объекта из текстового поля и лестница цены по его
        этапам строительной готовности."""
        weights, notes = schedule_weights(x.get(f"{prefix}_sales_profile"), sales_start)
        factor, rows, more = stage_ladder_factor(
            [x.get(f"{prefix}_growth_stage{k}_pct") for k in (1, 2, 3, 4)],
            construction_start, construction_months)
        object_schedule_notes[prefix] = {
            "sales_profile": str(x.get(f"{prefix}_sales_profile") or "").strip(),
            "price_stages": [{**row, "date": row["date"].isoformat()} for row in rows],
            "price_ladder": stage_ladder_text(rows),
            "profile_applied": weights is not None,
            "steps_applied": factor is not None,
            "warnings": notes + more,
        }
        return weights, factor

    # Выручка и CAPEX отдельно стоящих объектов — ОДИН обход реестра, а не
    # блок на объект. Четыре почти одинаковых блока различались ровно тремя
    # вещами (умолчание срока стройки, умолчание роста цены и признак «чем
    # меряется»), и все три теперь стоят строкой в `STANDALONE_OBJECTS`:
    # «поставить пару ОСЗ» перестало означать пятый такой блок.
    #
    # Календарь продаж каждого объекта складывается тут же (`sold`): его
    # читают продажи мест его гаража ниже. Собранный там второй раз, он
    # однажды разошёлся бы с этим, и обе половины выглядели бы верными.
    sold: dict[str, dict[str, Any]] = {}
    nonres_plans: dict[str, dict[str, Any]] = {}
    for obj in standalone_objects():
        if not b(x, obj.enabled_key):
            revenue_by_product[obj.key] = 0.0
            standalone_capex[obj.key] = 0.0
            continue
        months = int(n(x, f"{obj.prefix}_months", obj.default_months))
        build_start = d(x[f"{obj.prefix}_start"])
        # Себестоимость считается на том же, чем объект меряется: у метровых
        # это ГНС × ставка метра, у наземного паркинга места × ставка места.
        if obj.measure == "spaces":
            volume = n(x, f"{obj.prefix}_spaces")
            standalone_capex[obj.key] = volume * n(x, obj.rate_cost) * 1_000_000
            price = n(x, obj.rate_price) * 1_000_000
        else:
            standalone_capex[obj.key] = n(x, f"{obj.prefix}_gba_sqm") * n(x, obj.rate_cost) * 1000
            volume = object_saleable(obj.key, f"{obj.prefix}_saleable_sqm")
            price = n(x, obj.rate_price) * 1000
        if obj.garage:
            standalone_garage_capex[obj.key] = object_parking_capex(obj.key)
            standalone_capex[obj.key] += standalone_garage_capex[obj.key]
        # Признак продажи гасит ВЫРУЧКУ, а не стройку: переданный объект
        # строится за те же деньги и ведёт себя как соцобъект.
        if obj.sale_gate and not object_is_sold(x, obj):
            revenue_by_product[obj.key] = 0.0
            continue
        sales_start = d(x[f"{obj.prefix}_sales_start"])
        end_ref = add_months(build_start, months)
        # Прямая продажа и доходный метод идут мимо эскроу проекта: продукта
        # ДДУ у объекта нет, его деньги считает `developaid_nonres_strategy`
        # в финансировании, где известна ключевая ставка. Здесь — только план.
        strategy = (nonres_strategy.object_strategy(x, obj.prefix)
                    if obj.strategies else nonres_strategy.STRATEGY_DDU)
        if strategy != nonres_strategy.STRATEGY_DDU:
            revenue_by_product[obj.key] = 0.0
            nonres_plans[obj.key] = {
                "key": obj.key, "prefix": obj.prefix, "label": obj.label,
                "title": obj.tep_label or obj.label,
                "strategy": strategy, "commissioning": end_ref,
                "area_sqm": volume, "price_rub_sqm": price,
                "price_start": sales_start,
                "growth_pre": n(x, f"{obj.prefix}_growth_pre_pct", obj.growth_pre_default) / 100,
                "growth_post": n(x, f"{obj.prefix}_growth_post_pct", obj.growth_post_default) / 100,
                "parking_spaces": 0.0, "parking_price_rub": 0.0,
                "selling_share": (n(x, "marketing_pct") + n(x, "selling_pct")) / 100,
                # Плата за резервирование лимита — та же вводная, что у
                # БРИДЖа и ПФ, но с лимита НКЛ объекта (владелец, 05.10.2026).
                "reservation_fee_pct": n(x, "reservation_fee_pct"),
                # Плата за невыбранный лимит — та же вводная, что у ПФ.
                "limit_fee_pct": n(x, "limit_fee_pct"),
                # РнС делит кредит объекта на две НКЛ: участок и проект — до
                # неё, строительная — с неё.
                "permit": permit,
                "params": {suffix: x.get(f"{obj.prefix}_{suffix}")
                           for suffix in nonres_strategy.STRATEGY_FIELD_DEFAULTS},
            }
            continue
        share_value = n(x, f"{obj.prefix}_share_before_rve_pct", 85) / 100
        residual = int(n(x, f"{obj.prefix}_residual_months", 6))
        growth_pre = n(x, f"{obj.prefix}_growth_pre_pct", obj.growth_pre_default) / 100
        growth_post = n(x, f"{obj.prefix}_growth_post_pct", obj.growth_post_default) / 100
        weights, factor = object_schedule(obj.prefix, sales_start, build_start, months)
        add_product(obj.key, sales_schedule(
            volume, price, sales_start, end_ref, share_value, residual,
            growth_pre, growth_post,
            weights_override=weights, price_factor=factor,
        ), quantity_schedule(
            volume, sales_start, end_ref, share_value, residual,
            weights_override=weights,
        ))
        sold[obj.key] = {"sales_start": sales_start, "end_ref": end_ref,
                         "share": share_value, "residual": residual,
                         "growth_pre": growth_pre, "growth_post": growth_post,
                         "weights": weights, "factor": factor}

    # Места гаражей объектов продаются машино-местами (владелец,
    # 05.09.2026: «продают машиноместами конечно»). Число мест берётся со
    # СТРОК ТЭП, куда его положил `apply_object_parking`, — тогда очередь,
    # считаемая своим срезом ТЭП, получает свою долю мест сама, без второго
    # списка «чей это паркинг».
    #
    # Продукт один, а сроки у каждого объекта свои, поэтому ряды складываются:
    # места офисника продаются по календарю офисника, места встроенной
    # коммерции — по календарю дома. Один общий календарь продал бы паркинг
    # офиса третьей очереди вместе с квартирами первой.
    default_parking_price = n(x, "parking_price_th") * 1000

    def object_parking_price(tep_key: str, prefix: str) -> float:
        """Средняя стартовая цена продаваемых мест по фактическому размещению.

        Для продаваемого гаража (сейчас это только офисник) подземные места и
        места на первых этажах имеют разные вводные. Ноль сохраняет обратную
        совместимость: берётся общая цена подземного машино-места проекта.
        Гостевая доля применяется ко всему гаражу, поэтому одна и та же доля
        непродаваемых мест не меняет вес under/over в средней цене.
        """
        row = object_parking_row(tep_key)
        under = max(0.0, n(row, "parking_under_units"))
        over = max(0.0, n(row, "parking_over_units"))
        total = under + over
        if total <= 0:
            return default_parking_price
        under_mln = n(x, f"{prefix}_parking_under_price_mln_per_space")
        over_mln = n(x, f"{prefix}_parking_over_price_mln_per_space")
        under_price = under_mln * 1_000_000 if under_mln > 0 else default_parking_price
        over_price = over_mln * 1_000_000 if over_mln > 0 else default_parking_price
        return (under * under_price + over * over_price) / total

    def sell_object_parking(tep_key: str, prefix: str,
                            sales_start: date, end_ref: date,
                            share_value: float, residual_months: int,
                            growth_pre: float, growth_post: float,
                            weights: dict[date, float] | None = None,
                            factor: Callable[[date], float] | None = None,
                            seasonal_value: float | None = None,
                            pace_value: float | None = None,
                            ) -> tuple[dict[date, float], dict[date, float]] | None:
        spaces = n((t or {}).get(tep_key) or {}, "parking_saleable_units")
        if spaces <= 0:
            return None
        parking_price = object_parking_price(tep_key, prefix)
        extra = {} if seasonal_value is None else {"seasonal": seasonal_value, "pace": pace_value}
        value = sales_schedule(spaces, parking_price, sales_start, end_ref,
                               share_value, residual_months, growth_pre, growth_post,
                               weights_override=weights, price_factor=factor, **extra)
        units = quantity_schedule(spaces, sales_start, end_ref, share_value,
                                  residual_months, weights_override=weights,
                                  **({} if seasonal_value is None
                                     else {"seasonal": seasonal_value, "pace": pace_value}))
        return value, units

    # Встроенной коммерции МКД здесь нет: её машино-места лежат в общем
    # подземном паркинге проекта, у которого своя строка ТЭП и своя выручка.
    # Свой гараж у неё был бы вторым счётом тех же мест.
    # Гараж продаётся календарём СВОЕГО объекта — тем же, что посчитан выше.
    # У наземного паркинга гаража нет вовсе, и в `sold` он стоит без него:
    # обход спрашивает реестр, а не перечисляет объекты по памяти.
    # Чем и когда продаются места — для отчёта о продукте: стартовая цена и
    # календарь у них СВОИ, офисника, а не квартир. Отчёт брал цену места
    # дома и сроки дома, и темп мест офиса третьей очереди считался по
    # календарю квартир первой.
    object_parking_plan: list[dict[str, Any]] = []
    object_parking_capex_share: dict[str, float] = {}
    for obj in standalone_objects():
        if not obj.garage:
            continue
        # Паркинг — продукт СВОЕГО объекта: у каждого своя строка выручки
        # (`object_parking_product_key`), а не одна общая на все ОСЗ.
        product_key = object_parking_product_key(obj.key)
        revenue_by_product[product_key] = 0.0
        if obj.key in nonres_plans and obj.garage_sellable:
            # Места офисника при прямой продаже уходят ДКП вместе с объектом, при
            # доходном методе — сдаются. Гостевые не продаются и не сдаются.
            nonres_plans[obj.key]["parking_spaces"] = n(
                object_parking_row(obj.key), "parking_saleable_units")
            nonres_plans[obj.key]["parking_price_rub"] = object_parking_price(obj.key, obj.prefix)
        plan = sold.get(obj.key)
        if plan is None:
            continue
        sale = sell_object_parking(obj.key, obj.prefix, plan["sales_start"], plan["end_ref"],
                                   plan["share"], plan["residual"],
                                   plan["growth_pre"], plan["growth_post"],
                                   plan["weights"], plan["factor"])
        if sale is not None:
            add_product(product_key, dict(sale[0]), dict(sale[1]))
        spaces = n(object_parking_row(obj.key), "parking_saleable_units")
        if spaces > 0:
            # Во что места обошлись САМОМУ объекту: его подземный гараж и метры
            # здания под местами первых этажей по ставке здания. Эта доля
            # статьи объекта признаётся продажами мест, а не метров офиса, и
            # к пулу дома не имеет никакого отношения (владелец, 27.09.2026:
            # «весь гараж и подземный и наземный должен иметь отношение в
            # затратах и выручке только своего объекта, но никак не МКД»).
            row = object_parking_row(obj.key)
            over_gba = min(n(row, "parking_over_gba_sqm"),
                           max(0.0, n(x, f"{obj.prefix}_gba_sqm")))
            parking_capex = (standalone_garage_capex.get(obj.key, 0.0)
                             + over_gba * n(x, obj.rate_cost) * 1000)
            object_capex = standalone_capex.get(obj.key, 0.0)
            object_parking_capex_share[obj.key] = (
                min(1.0, parking_capex / object_capex) if object_capex > 0 else 0.0)
            object_parking_plan.append({
                "key": obj.key, "spaces": spaces,
                "price_th": object_parking_price(obj.key, obj.prefix) / 1000,
                "sales_start": plan["sales_start"], "end_ref": plan["end_ref"],
                "share": plan["share"], "residual": plan["residual"]})

    # Scenario model:
    # base = 100% revenue / 100% project costs
    # conservative = 90% revenue / 110% project costs
    # optimistic = 110% revenue / 90% project costs
    revenue_multiplier = n(x, "scenario_revenue_multiplier", 1.0)
    cost_multiplier = n(x, "scenario_cost_multiplier", 1.0)

    # Keep the base revenue profile so variable operating expenses can be
    # scenarioed independently from the income side.
    base_revenue = dict(revenue)

    if abs(revenue_multiplier - 1.0) > 1e-12:
        revenue = defaultdict(float, {
            month: value * revenue_multiplier for month, value in revenue.items()
        })
        for key in list(revenue_by_product):
            revenue_by_product[key] *= revenue_multiplier
        for key in list(revenue_product_schedules):
            revenue_product_schedules[key] = {
                month: value * revenue_multiplier
                for month, value in revenue_product_schedules[key].items()
            }

    # Льгота срезается сразу: и резерв, и график рассрочки должны считаться от
    # суммы к оплате, а не от валового обязательства.
    vri_gross = n(x, "land_rights_cost_mln") * 1_000_000
    vri_relief_amount, vri_net = vri_relief(x, vri_gross, t)

    # База статей проекта (ИРД, П, РД, подготовка, сети, ввод, содержание
    # площадки). У жилого и смешанного проекта — суммарная площадь МКД:
    # ставка объекта там «под ключ» и эти статьи уже несёт. У чисто нежилого
    # ставка объекта — только СМР здания, и статьи идут по тем же ставкам от
    # суммарной площади объектов в ГНС (`object_rate_is_turnkey`).
    objects_area = objects_total_area(x, t)
    article_gns = n(x, "hotel_gba_sqm") if is_hotel(x) else core_total_gns
    project_articles_sqm = article_gns if is_hotel(x) else core_total_gns + objects_area
    # Имя базы: у нежилого проекта она — площадь объектов (МКД там нет).
    project_articles_term = OBJECTS_TOTAL_AREA if without_housing(x) else CORE_TOTAL_AREA

    amounts = {
        "land_rights": vri_net,
        "ird": project_articles_sqm * n(x, "ird_th_per_sqm") * 1000,
        "design_p": project_articles_sqm * n(x, "design_p_th_per_sqm") * 1000,
        "design_rd": project_articles_sqm * n(x, "design_rd_th_per_sqm") * 1000,
        "author_supervision": 0.0,
        "technical_supervision": 0.0,
        # Снос считается от площади СНОСИМОГО, а не от новой ГНС: это разные
        # метры, и удельная ставка подготовительных работ здесь не годится.
        # Расселение — отдельное обязательство КРТ и отдельные деньги.
        # Ни то ни другое не соцнагрузка: соцнагрузка компенсируется деньгами
        # и входит в расчётный лимит БРИДЖа, а снос — нет.
        "demolition": n(x, "demolition_area_sqm") * n(x, "demolition_cost_th_per_sqm") * 1000,
        "resettlement": n(x, "resettlement_cost_mln") * 1_000_000,
        "preparation": project_articles_sqm * n(x, "preparation_th_per_sqm") * 1000,
        "main_above": core_above_gns * n(x, "main_above_th_per_sqm") * 1000,
        "main_under": core_under_gns * n(x, "main_under_th_per_sqm") * 1000,
        "utilities": project_articles_sqm * n(x, "utilities_th_per_sqm") * 1000,
        # Ставка на метр ГНС сильнее методики двора, когда она задана:
        # привычный сметчику показатель — просьба владельца. База — НАЗЕМНАЯ
        # ГНС ПРОЕКТА, та же, которой меряют удельные и которой считает свод
        # «Статистики»: одно имя на экране обязано значить одно число, иначе
        # «₽/м² ГНС» поля и «₽/м² ГНС» свода — два разных показателя под одной
        # подписью (владелец, 16.09.2026: «на м2 ГНС видимо пишут грамотные
        # люди»). Прежняя база — метры дома без соцобъектов и ОСЗ — давала на
        # умолчаниях 140 381 м² против 145 381, то есть тот же показатель на
        # 3,5% выше при тех же деньгах.
        "landscaping": landscaping_amount,
        "commissioning": project_articles_sqm * n(x, "commissioning_th_per_sqm") * 1000,
        "site_maintenance": project_articles_sqm * n(x, "site_maintenance_th_per_sqm") * 1000,
        # Статьи объектов — по реестру, а не перечислением: снятый оттуда
        # объект иначе валит расчёт KeyError'ом, то есть список тут второй.
        **{obj.key: standalone_capex.get(obj.key, 0.0) for obj in standalone_objects()},
        # Гостиница — статьи своего типа проекта: здание и мебель с
        # оборудованием. Считаются здесь, один раз; расчёт гостиницы получает
        # их готовыми помесячно (`hotel_plan`).
        **hotel_capex_amounts(x),
    }

    social_program = effective_social_program(x)
    social_construction_breakdown = {
        "kindergarten": social_program["kindergarten_places"] * n(x, "kindergarten_cost_mln_per_place") * 1_000_000,
        "school": social_program["school_places"] * n(x, "school_cost_mln_per_place") * 1_000_000,
        "clinic": social_program["clinic_capacity"] * n(x, "clinic_cost_mln_per_unit") * 1_000_000,
    }
    social_construction_total = sum(social_construction_breakdown.values())
    imported_social_compensation = n(x, "social_compensation_mln") * 1_000_000
    social_mode = str(x.get("social_mode", "Строительство"))
    if social_mode == "Денежная компенсация":
        social_total = imported_social_compensation if imported_social_compensation > 0 else social_construction_total
    elif social_mode == SOCIAL_MODE_BOTH:
        # Обе формы разом. Редкий, но реальный случай: школу и садик проект
        # строит сам, а за спортивный объект платит деньгами. Прежде режимы
        # исключали друг друга, и денежная нагрузка либо отменяла стройку,
        # либо молча не считалась вовсе — на Румянцеве это 1,15 млрд ₽.
        social_total = social_construction_total + imported_social_compensation
    else:
        social_total = social_construction_total
    amounts["social"] = social_total

    # Optional absolute base-cost overrides used only by the phasing wrapper.
    # Ordinary single-phase calculations do not set this field and are unchanged.
    cost_overrides = x.get("_cost_override_mln") or {}
    for override_key, override_value_mln in cost_overrides.items():
        if override_key in amounts and override_value_mln is not None:
            amounts[override_key] = float(override_value_mln) * 1_000_000

    # СМР объектов (здание и свой гараж) — в базах генподряда, техзаказчика и
    # управления только у чисто нежилого проекта: там ставка объекта — СМР.
    # У жилого и смешанного ставка «под ключ», вознаграждение генподрядчика и
    # техзаказчик в ней уже есть, и процент сверху был двойным счётом
    # (решение владельца 06.10.2026, `object_rate_is_turnkey`).
    object_works = sum(amounts[obj.key] for obj in standalone_objects()
                       if not object_rate_is_turnkey(x, obj))
    works_base = (
        amounts["main_above"] + amounts["main_under"] + amounts["social"]
        + object_works
        # Мебель и оборудование — поставка, а не работы: генподряд и
        # технадзор на неё не начисляются.
        + amounts.get("hotel", 0.0)
    )
    design_base = amounts["design_p"] + amounts["design_rd"]

    # Author supervision is modeled as a percentage of design P + RD.
    # No arbitrary fixed-million hardcode is used.
    amounts["author_supervision"] = design_base * n(x, "author_supervision_pct", 0.0) / 100

    # Project management is a separate developer overhead:
    # salaries of the project team, office/admin support and other management overheads.
    # The base mirrors the original Excel logic conceptually: design/surveys,
    # preparation, main construction, utilities, landscaping and site maintenance.
    management_base = (
        amounts["ird"]
        + amounts["design_p"] + amounts["design_rd"] + amounts["author_supervision"]
        + amounts["preparation"]
        + amounts["main_above"] + amounts["main_under"] + object_works
        + amounts["utilities"]
        + amounts["landscaping"]
        + amounts["site_maintenance"]
    )
    amounts["project_management"] = management_base * n(x, "project_management_pct", 5.0) / 100

    # Technical customer / construction control is a different cost item.
    # No separate rate exists in the source Inputs, so default is 0% until explicitly set.
    amounts["technical_supervision"] = works_base * n(x, "technical_supervision_pct", 0.0) / 100

    amounts["gc_fee"] = works_base * n(x, "gc_fee_pct") / 100

    base_for_overheads = sum(value for key, value in amounts.items()
                             if key not in RESERVE_EXCLUDED_ARTICLES)
    amounts["reserve"] = base_for_overheads * n(x, "reserve_pct") / 100

    # Смета объекта — то, что начислено ОТ его стройки: генподряд и
    # технический заказчик берут процент с базы работ, куда объект входит
    # своей статьёй, резерв — процент со всех статей. Доля объекта в них —
    # тот же процент с его денег, а не распределение: сумма долей и остатка
    # равна статье. Владельцу «Основное строительство», «Технический заказчик»
    # и «Резерв» общими строками не говорили, что это стройка офиса
    # (05.10.2026). Гараж — внутри статьи объекта, в той же доле, что при
    # расчёте (статью может перебить очередь).
    object_cost_parts: dict[str, dict[str, float]] = {}
    for obj in standalone_objects():
        own = float(amounts.get(obj.key) or 0.0)
        if own <= 0:
            continue
        # Объект «под ключ» в базу работ не входит (`object_rate_is_turnkey`,
        # решение владельца 06.10.2026): генподряд и техзаказчик в его ставке,
        # и доли процентов у него нет. Иначе own/works_base дало бы объекту
        # долю чужого генподряда — СМР дома.
        share = (0.0 if object_rate_is_turnkey(x, obj) or not works_base
                 else own / works_base)
        gc_part = amounts["gc_fee"] * share
        tz_part = amounts["technical_supervision"] * share
        planned = float(standalone_capex.get(obj.key) or 0.0)
        garage = (float(standalone_garage_capex.get(obj.key) or 0.0) * own / planned
                  if planned else 0.0)
        object_cost_parts[obj.key] = {
            "building": own - garage, "garage": garage,
            "gc_fee": gc_part, "technical_supervision": tz_part,
            "reserve": (own + gc_part + tz_part) * n(x, "reserve_pct") / 100,
        }

    # Прямые затраты частей МКД — СМР части и то, что начислено ОТ него:
    # генподряд и техзаказчик (процент базы работ, куда СМР входит своей
    # статьёй), управление проектом (процент своей базы) и резерв (процент со
    # всех статей, включая эти). Доля каждой надбавки — тот же процент с денег
    # части, что и у сметы объекта выше. По ним пул МКД делит себестоимость
    # продуктов «по месту» (`cost_pool_product_costs`).
    def _part_direct(own: float) -> float:
        if own <= 0:
            return 0.0
        share = own / works_base if works_base else 0.0
        fees = (amounts["gc_fee"] + amounts["technical_supervision"]) * share
        management = own * n(x, "project_management_pct", 5.0) / 100
        return (own + fees + management) * (1 + n(x, "reserve_pct") / 100)

    mkd_direct_costs = {"above": _part_direct(float(amounts["main_above"] or 0.0)),
                        "under": _part_direct(float(amounts["main_under"] or 0.0))}

    capex: dict[date, float] = defaultdict(float)
    # Помесячная детализация по статьям: тот же расклад, что и в общем ряду,
    # но с разбивкой — нужна для выгрузки финмодели и сверки с эталоном.
    capex_by_article: dict[str, dict[date, float]] = defaultdict(lambda: defaultdict(float))

    def add_capex(article: str, month: date, amount: float) -> None:
        capex[month] += amount
        capex_by_article[article][month] += amount

    def spread_article(article: str, amount: float, start: date, months: int) -> None:
        bucket: dict[date, float] = defaultdict(float)
        spread_evenly(bucket, amount, start, months)
        for bucket_month, bucket_value in bucket.items():
            add_capex(article, bucket_month, bucket_value)

    def spread_s_curve(article: str, amount: float, start: date, months: int) -> None:
        # S-кривая книги (лист CF_x, строка 12) объявлена одним местом —
        # `build_curve`. Копия здесь была бы не удобством, а вторым мнением об
        # одном процессе: этой же кривой отчёт о рынке считает готовность дома
        # по датам, и разойтись им нельзя.
        if not amount:
            return
        for index, share in enumerate(build_curve.monthly_shares(months)):
            add_capex(article, add_months(start, index), amount * share)

    # Покупка платится по графику, если он задан: часть в сделку, часть
    # рассрочкой, выкуп чужих объектов по КРТ своими сроками (владелец,
    # 02.09.2026). Лимит БРИДЖа считается от всей цены — это формула банка;
    # выборка следует за платежами, и отложенный платёж сам снижает проценты.
    purchase_payments, purchase_warnings = purchase_payment_plan(
        n(x, "purchase_price_mln") * 1_000_000, x.get("purchase_schedule"), project_start, end)
    # Выкуп ЗУ/ОКС у третьих лиц — строка стоимости сделки рядом с ценой
    # участка (решение владельца, 29.09.2026: «при переносе из расчёта КРТ эти
    # суммы выкупа должны идти в стоимость сделки»). Платится графиком покупки
    # в той же пропорции; без цены участка — графиком сделки сам по себе.
    # Статья та же — «purchase»: лимит БРИДЖа, НДС, очереди и книга видят
    # сделку целиком, а разбивку на две строки дают вводные.
    buyout_total = n(x, "land_buyout_mln") * 1_000_000
    buyout_payments: list[tuple[date, float]] = []
    if buyout_total > 0:
        paid_for_price = sum(amount for _, amount in purchase_payments)
        if paid_for_price > 0:
            buyout_payments = [(when, buyout_total * amount / paid_for_price)
                               for when, amount in purchase_payments]
        else:
            buyout_payments, buyout_warnings = purchase_payment_plan(
                buyout_total, x.get("purchase_schedule"), project_start, end)
            purchase_warnings = list(purchase_warnings) + [
                f"выкуп ЗУ/ОКС: {w}" for w in buyout_warnings]
    for when, amount in [*purchase_payments, *buyout_payments]:
        add_capex("purchase", when, amount)
    # График — вся сделка: цена участка и выкуп по датам. Строки только цены
    # при нулевой цене оставляли отчёт с пустым графиком при выкупе в
    # полтора миллиарда; доля — от стоимости сделки.
    deal_total = (n(x, "purchase_price_mln") + n(x, "land_buyout_mln")) * 1_000_000
    deal_by_date: dict[date, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for when, amount in purchase_payments:
        deal_by_date[when][0] += amount
    for when, amount in buyout_payments:
        deal_by_date[when][1] += amount
    buyout_basis = deal_buyout_basis(x)
    purchase_schedule_info = {
        "total_mln": n(x, "purchase_price_mln") + n(x, "land_buyout_mln"),
        "price_mln": n(x, "purchase_price_mln"),
        "buyout_mln": n(x, "land_buyout_mln"),
        "buyout_basis": buyout_basis,
        "buyout_label": deal_buyout_label(buyout_basis),
        "custom": bool(str(x.get("purchase_schedule") or "").strip()),
        "rows": [{"date": when.isoformat(), "amount_mln": (price + buyout) / 1_000_000,
                  "price_mln": price / 1_000_000, "buyout_mln": buyout / 1_000_000,
                  "share": (price + buyout) / deal_total if deal_total > 0 else 0.0,
                  "offset_months": months_between(project_start, when)}
                 for when, (price, buyout) in sorted(deal_by_date.items())],
        # Пустой график называет причину, а не печатается пустой таблицей.
        "empty_reason": ("" if deal_by_date else
                         "стоимость сделки не задана — платежей за покупку нет"
                         if deal_total <= 0 else
                         "платежи за покупку не разложены по датам"),
        "warnings": purchase_warnings,
    }

    # Плата за смену ВРИ идёт по собственному графику: единовременно или
    # рассрочкой с процентами на остаток. Проценты по рассрочке — отдельная
    # статья, они не смешиваются с процентами по кредитам. Доля, оплаченная
    # собственным капиталом, исключается из базы долгового финансирования.
    vri = build_vri_schedule(
        x, amounts["land_rights"], permit, rates, str(x.get("rate_scenario", "base"))
    )
    vri["totals"]["gross"] = round(vri_gross, 2)
    vri["totals"]["relief"] = round(vri_relief_amount, 2)
    # Чем задана льгота — поверхности подписывают число, а не угадывают его
    # происхождение: в КРТ это посчитанные льготы проекта, а не ручная сумма.
    vri["totals"]["relief_basis"] = vri_relief_basis(x)
    if vri["totals"]["relief_basis"] == "project_benefits" and vri_gross > 0:
        # Откуда льгота и почему её нет — в самом результате: молчаливый ноль
        # льготы за МПТ выглядел как «ничего не пересчиталось».
        _benefits = vri_benefits_for(x, t)
        vri["totals"]["relief_source"] = (_benefits.get("mpt_source") or {}).get("text", "")
        if _benefits.get("mpt_reason") and not _benefits.get("override"):
            vri.setdefault("warnings", []).append(_benefits["mpt_reason"])
    if vri_relief_amount > 0 and not vri["enabled"]:
        vri["totals"]["amount"] = round(vri_net, 2)
    vri_equity_by_month: dict[date, float] = defaultdict(float)
    if vri["enabled"]:
        for row in vri["rows"]:
            when = d(row["date"])
            if when < project_start:
                # Обязательство возникло раньше очереди: платёж относим на её
                # старт, иначе он выпадет за горизонт расчёта и потеряется.
                when = project_start
                row["shifted_to_start"] = True
            if row["principal"]:
                add_capex("land_rights", when, row["principal"])
            if row["interest"]:
                add_capex("vri_interest", when, row["interest"])
            if row.get("security"):
                add_capex("vri_security", when, row["total"])
            if row["equity"]:
                vri_equity_by_month[when] += row["equity"]
        if any(row.get("shifted_to_start") for row in vri["rows"]):
            vri["warnings"].append(
                "Часть платежей ВРИ приходится на период до старта расчёта — "
                "они отнесены на первый месяц."
            )
    else:
        add_capex("land_rights", permit, amounts["land_rights"])
    amounts["vri_interest"] = vri["totals"]["interest"]
    amounts["vri_security"] = vri["totals"]["security_cost"]
    amounts["land_rights_gross"] = vri_gross
    amounts["land_rights_relief"] = vri_relief_amount

    ird_months = max(IRD_MONTHS_MIN, int(n(x, "ird_months", 18)))
    spread_article("ird", amounts["ird"], project_start, ird_months)
    # Project design cash flow is concentrated toward RnS rather than spread evenly from acquisition.
    # This materially improves bridge timing and follows the schedule logic of the current workbook.
    design_window = min(6, ird_months)
    spread_article("design_p", amounts["design_p"], add_months(permit, -design_window), design_window)
    spread_article("design_rd", amounts["design_rd"], add_months(permit, -design_window), design_window)
    # Снос и расселение идут до РнС, вместе с подготовительными работами:
    # строить на занятой площадке нельзя.
    spread_article("demolition", amounts["demolition"], add_months(permit, -design_window), design_window)
    spread_article("resettlement", amounts["resettlement"], add_months(permit, -design_window), design_window)
    spread_article("preparation", amounts["preparation"], add_months(permit, -design_window), design_window)

    construction_months = max(1, int(n(x, "construction_months", 24)))
    spread_s_curve("main_above", amounts["main_above"], permit, construction_months)
    spread_s_curve("main_under", amounts["main_under"], permit, construction_months)
    spread_s_curve("utilities", amounts["utilities"], permit, construction_months)
    spread_s_curve("site_maintenance", amounts["site_maintenance"], permit, construction_months)
    spread_s_curve("author_supervision", amounts["author_supervision"], permit, construction_months)
    spread_s_curve("technical_supervision", amounts["technical_supervision"], permit, construction_months)
    spread_article("landscaping", amounts["landscaping"], add_months(rve, -3), 3)
    spread_article("commissioning", amounts["commissioning"], add_months(rve, -3), 3)

    # Управление проектом — следом за расходами, которыми оно вызвано: равный
    # календарный разнос от старта до РВЭ сажал полный штаб с первого дня и
    # догружал БРИДЖ сотнями миллионов при реальных тратах в одно проектирование.
    management_profile: dict[date, float] = defaultdict(float)
    for profile_article in MANAGEMENT_PROFILE_ARTICLES:
        for profile_month, profile_value in capex_by_article[profile_article].items():
            management_profile[profile_month] += profile_value
    management_total = sum(management_profile.values())
    if management_total > 0:
        for profile_month, profile_value in management_profile.items():
            add_capex("project_management", profile_month,
                      amounts["project_management"] * profile_value / management_total)
    else:
        spread_article("project_management", amounts["project_management"],
                       project_start, max(1, months_between(project_start, rve)))

    social_mode_now = str(x.get("social_mode", "Строительство"))
    social_cash_date = social_cash_payment_date(x, permit)
    if social_mode_now in ("Строительство", SOCIAL_MODE_BOTH):
        if social_program["kindergarten_places"]:
            spread_article("social", social_construction_breakdown["kindergarten"],
                           d(x["kindergarten_start"]), int(n(x, "kindergarten_months", 24)))
        if social_program["school_places"]:
            spread_article("social", social_construction_breakdown["school"],
                           d(x["school_start"]), int(n(x, "school_months", 30)))
        if social_program["clinic_capacity"]:
            spread_article("social", social_construction_breakdown["clinic"],
                           d(x["clinic_start"]), int(n(x, "clinic_months", 24)))
        # Каждая стройка идёт своим графиком, а денежная часть — одним
        # платежом в свою дату: это разные обязательства с разными сроками.
        if social_mode_now == SOCIAL_MODE_BOTH and imported_social_compensation > 0:
            add_capex("social", social_cash_date, imported_social_compensation)
    else:
        add_capex("social", social_cash_date, social_total)

    # Отдельно стоящий объект строится так же, как жилой дом, — S-кривой, а не
    # ровно по месяцам (решение владельца, 30.08.2026). Ровный расход стоял
    # здесь не как решение, а как недосмотр: главный корпус движок уже считал
    # S-кривой, и обе функции у него были. Книга при этом всегда считала
    # объекты S-кривой, и на очереди с офисами это давало 43 млн ₽ в месяц
    # разницы четыре месяца подряд — итог CAPEX сходился, профиль нет. Меньше
    # потрачено — меньше долг, выше покрытие эскроу, другая ступень лестницы
    # ставки ПФ: 14,75 млн ₽ расхождения по стоимости финансирования.
    for obj in standalone_objects():
        if not amounts.get(obj.key):
            continue
        spread_s_curve(obj.key, amounts[obj.key], d(x[f"{obj.prefix}_start"]),
                       int(n(x, f"{obj.prefix}_months", obj.default_months)))
    # Гостиница строится в окне проекта — от РнС до РВЭ; мебель и оборудование
    # — последние полгода перед вводом (или вся стройка, если она короче).
    if "hotel" in amounts:
        spread_s_curve("hotel", amounts["hotel"], permit, construction_months)
        ffe_window = max(1, min(HOTEL_FFE_MONTHS, construction_months))
        spread_article("hotel_ffe", amounts["hotel_ffe"], add_months(rve, -ffe_window),
                       ffe_window)

    # GC, reserve and project management belong to the construction phase rather than the pre-RnS bridge period.
    # This is closer to the timing used in the current Excel cash-flow model.
    spread_s_curve("gc_fee", amounts["gc_fee"], permit, construction_months)
    spread_s_curve("reserve", amounts["reserve"], permit, construction_months)

    # Apply expense scenario to ALL project-side cash outflows exactly once:
    # acquisition, VRI, social burden, design, construction, overheads, etc.
    if abs(cost_multiplier - 1.0) > 1e-12:
        capex = defaultdict(float, {
            month: value * cost_multiplier for month, value in capex.items()
        })
        capex_by_article = defaultdict(lambda: defaultdict(float), {
            article: defaultdict(float, {
                month: value * cost_multiplier for month, value in schedule.items()
            })
            for article, schedule in capex_by_article.items()
        })
        for key in list(amounts):
            amounts[key] *= cost_multiplier
        for parts in object_cost_parts.values():
            for key in parts:
                parts[key] *= cost_multiplier

    # Marketing + selling expenses are also scenarioed as expenses relative to BASE,
    # not reduced merely because conservative revenue is lower.
    operating: dict[date, float] = defaultdict(float)
    for month, value in base_revenue.items():
        operating[month] += (
            value
            * (n(x, "marketing_pct") + n(x, "selling_pct")) / 100
            * cost_multiplier
        )

    # A standalone KRT object may finish after the residential phase. Keep it in
    # the financing, tax and cash-flow horizon instead of only adding its revenue
    # to the project total.
    dated_flows = list(revenue) + list(capex) + list(operating)
    if dated_flows:
        end = max(end, max(dated_flows))

    # Долговое финансирование видит все расходы проекта, кроме той части платы
    # за ВРИ, которую собственник закрывает капиталом: она не создаёт ни выборки
    # БРИДЖа, ни выборки ПФ.
    debt_capex = dict(capex)
    for month, equity_value in vri_equity_by_month.items():
        debt_capex[month] = max(0.0, debt_capex.get(month, 0.0) - equity_value)
    # Объект вне ДДУ строится на свой кредит и капитал, а не на БРИДЖ и ПФ
    # проекта: банк ПФ эскроу-покрытия от него не получает и его не кредитует.
    # Затраты остаются в CAPEX проекта — прибыль и налог их видят.
    for key, plan in nonres_plans.items():
        plan["capex"] = dict(capex_by_article.get(key) or {})
        plan["revenue_multiplier"] = revenue_multiplier
        plan["cost_multiplier"] = cost_multiplier
        for month, value in plan["capex"].items():
            debt_capex[month] = max(0.0, debt_capex.get(month, 0.0) - value)
        end = max(end, nonres_strategy.plan_horizon_end(plan))
    # Нежилой проект: банк кредитует долю ВСЕЙ стоимости — участка, проекта,
    # сетей, надбавок, — а не только стройки здания (владелец, 04.10.2026:
    # «банк даёт деньги в какой-то пропорции, остальное даёшь сам»). Общие
    # затраты, которые иначе выбирали бы БРИДЖ и ПФ без единого рубля эскроу,
    # уходят в кредит объектов вне ДДУ долей их стройки. Доля объектов на ДДУ
    # остаётся на ПФ — у них эскроу есть. В смешанном проекте общие затраты
    # несёт ПФ жилья, как прежде.
    if nonres_plans and is_nonresidential(x):
        object_keys = {obj.key for obj in standalone_objects()}
        object_capex = {key: sum((capex_by_article.get(key) or {}).values()) for key in object_keys}
        objects_total = sum(object_capex.values())
        shares = {key: object_capex[key] / objects_total
                  for key in nonres_plans if objects_total > 0}
        for month in list(debt_capex):
            ddu_objects = sum((capex_by_article.get(key) or {}).get(month, 0.0)
                              for key in object_keys if key not in nonres_plans)
            common = max(0.0, debt_capex[month] - ddu_objects)
            if common <= 0:
                continue
            for key, share in shares.items():
                plan = nonres_plans[key]
                plan.setdefault("common_capex", {})
                plan["common_capex"][month] = common * share
            debt_capex[month] -= common * sum(shares.values())

    # Гостиничный проект: всё, что проект тратит, — затраты гостиницы. Банк
    # ПФ её не кредитует (эскроу нет); кредит — свой, гостиничный, и его
    # считает `developaid_hotel_strategy` вместе с номерами и USALI. Участок и
    # плата за ВРИ — без НДС и не амортизируются.
    hotel_plan: dict[str, Any] | None = None
    if is_hotel(x):
        land: dict[date, float] = defaultdict(float)
        for article in HOTEL_LAND_ARTICLES:
            for month, value in (capex_by_article.get(article) or {}).items():
                land[month] += value
        hotel_params = hotel_strategy.params_from_inputs(x)
        hotel_plan = {
            "commissioning": rve, "start": project_start,
            "capex": {month: value for month, value in capex.items() if value},
            "capex_ffe": dict(capex_by_article.get("hotel_ffe") or {}),
            "capex_land": dict(land),
            "params": hotel_params,
            "revenue_multiplier": revenue_multiplier,
            "missing": [f.label for f in hotel_strategy.missing_fields(
                hotel_params, with_capex=True)],
        }
        debt_capex = {month: 0.0 for month in debt_capex}
        end = max(end, hotel_strategy.plan_horizon_end(hotel_plan))

    return {
        "project_start": project_start,
        "permit": permit,
        "sales_start": sales_start,
        "rve": rve,
        "end": end,
        "revenue": dict(revenue),
        "revenue_by_product": revenue_by_product,
        "revenue_product_schedules": revenue_product_schedules,
        "quantity_product_schedules": quantity_product_schedules,
        "capex": dict(capex),
        "capex_by_article": {article: dict(schedule) for article, schedule in capex_by_article.items()},
        "debt_capex": debt_capex,
        "nonres_plans": nonres_plans,
        "hotel_plan": hotel_plan,
        # Общие затраты (участок, проект, сети) кредитует НКЛ объектов, а не
        # БРИДЖ и ПФ: так устроен чисто нежилой проект. Читает финансирование —
        # лимит БРИДЖа такому проекту не считается. Гостиничный проект так же:
        # все его затраты несёт кредит гостиницы (`hotel_plan`).
        "common_on_object_loans": bool((nonres_plans and is_nonresidential(x)) or hotel_plan),
        "operating": dict(operating),
        "capex_amounts": amounts,
        # Гараж объекта внутри его статьи, но со своей базой: здание меряется
        # своей ГНС, гараж — подземным метром. Без этой пары удельная объекта
        # молча смешивает два показателя.
        "standalone_garage_capex": dict(standalone_garage_capex),
        "object_cost_parts": object_cost_parts,
        "object_parking_plan": list(object_parking_plan),
        # Доля статьи объекта, которая приходится на его ПРОДАВАЕМЫЙ паркинг.
        # Долей, а не суммой: статья объекта может быть перебита очередью
        # (`_cost_override_mln`), и доля переносится на то, что осталось.
        "object_parking_capex_share": dict(object_parking_capex_share),
        "purchase_schedule": purchase_schedule_info,
        "object_schedule_notes": object_schedule_notes,
        "core_above_gns": core_above_gns,
        "core_under_gns": core_under_gns,
        "mkd_direct_costs": mkd_direct_costs,
        # База статей проекта и её имя — один ответ для PDF, страницы и книг.
        "project_articles_sqm": project_articles_sqm,
        "project_articles_area": project_articles_term.key,
        # База благоустройства — своя, физическая: она не строительный объём, и
        # едет наружу вместе с основанием, чтобы читатель видел, чем посчитано.
        "landscaping_area_sqm": landscaping_sqm,
        "landscaping_basis": landscaping_basis,
        # Чем посчитаны ДЕНЬГИ. У двора и у рубля основания разные: заданная
        # ставка двор не читает вовсе, и его основание рядом с суммой читается
        # как её причина.
        "landscaping_money_basis": landscaping_money_basis,
        # Показатель МЕТОДИКИ, а не применённый. Пока он считался из денег, а
        # деньги — из заданной руками ставки, подпись «очистите поле —
        # вернётся методика (30)» повторяла введённое число: на умолчаниях
        # методика даёт 0,31, то есть предложенное действие обещало не тот
        # исход почти в сто раз. Считается всегда и независимо от поля.
        "landscaping_by_class": (landscaping_sqm
                                 * float(x.get("landscaping_th_per_sqm") or 0.0) * 1000),
        # Чем посчитаны ДЕНЬГИ: заданная ставка двор не читает вовсе, и
        # основание двора рядом с суммой читается как её причина.
        "landscaping_by_rate": float(x.get("landscaping_gns_th_per_sqm") or 0.0) > 0,
        "social_program": social_program,
        "social_construction_breakdown": social_construction_breakdown,
        "social_cash_date": social_cash_date,
        "imported_social_compensation": imported_social_compensation,
        "vri": vri,
        "vri_equity": dict(vri_equity_by_month),
    }

"""Калькулятор Подмосковья: УПКС, соцпрограмма РНГП МО, плата за ВРИ.

УПКС по округам и кварталам, свежесть справочников, нормативы МО,
социальная программа (mo_social_program), плата за изменение ВРИ
(mo_vri_payment), рыночная цена и коэффициенты Кд, ТЭП и баланс
территории, переадресация на ядро и маршрут mo_calculate.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён на том месте, где этот код стоял раньше
(`_engine_part("mo_calc")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

# ---------------------------------------------------------------------------
# Калькулятор Подмосковья: ТЭП, социальная нагрузка по РНГП МО и плата за ВРИ
#
# Аналог блока ГлавАПУ, но для Московской области. Источники нормативов и
# справочников — расчёты ППТ и таблицы УПКС, приложенные заказчиком:
#   * «расчет_200 тыс кв» — потребность в социальной инфраструктуре;
#   * «ВРИ» — плата за изменение вида разрешённого использования;
#   * УПКС ЗУ и УПКС ОКС по городским округам и кадастровым кварталам.
# ---------------------------------------------------------------------------

# Округ -> (УПКС ЗУ «жилая застройка», УПКС ОКС МКД, УПКС ОКС машино-места,
#           УПКС ОКС коммерция), руб./м².
_MO_UPKS_BY_DISTRICT: dict[str, tuple[float | None, float | None, float | None, float | None]] = {
    "Богородский городской округ": (4909.72, 64999.31, 29249.42, 40067.39),
    "Волоколамский городской округ": (2473.45, 52389.88, None, 38477.01),
    "Городской округ Балашиха": (8149.18, 95771.59, 45030.5, 38890.0),
    "Городской округ Бронницы": (4151.46, 71477.98, None, 39221.13),
    "Городской округ ВЛАСИХА (ЗАТО)": (8610.22, 107087.94, None, 45406.9),
    "Городской округ Воскресенск": (3601.73, 52817.81, 21537.4, 40245.69),
    "Городской округ Восход (ЗАТО)": (None, 66746.87, None, 33853.05),
    "Городской округ Дзержинский": (10331.06, 106648.14, 56292.93, 39096.07),
    "Городской округ Долгопрудный": (12340.12, 128909.52, 58314.24, 34346.92),
    "Городской округ Домодедово": (7437.85, 92221.78, 46532.1, 43636.89),
    "Городской округ Дубна": (5655.27, 88699.99, None, 36666.21),
    "Городской округ Егорьевск": (3058.48, 51483.81, 20910.68, 37340.46),
    "Городской округ Жуковский": (7824.35, 96276.56, 45501.99, 37452.36),
    "Городской округ Зарайск": (2314.35, 48608.34, None, 39163.79),
    "Городской округ Звёздный городок (ЗАТО)": (4595.42, 86535.53, None, 44897.41),
    "Городской округ Истра": (5968.53, 83505.99, 35612.8, 41072.04),
    "Городской округ КРАСНОЗНАМЕНСК (ЗАТО)": (8236.65, 104472.13, None, 38917.62),
    "Городской округ Кашира": (2921.36, 49062.81, None, 38957.87),
    "Городской округ Клин": (3534.57, 62224.31, 20398.02, 40394.33),
    "Городской округ Коломна": (3933.68, 65231.81, 33059.94, 39216.47),
    "Городской округ Королёв": (6812.86, 107218.97, 54793.4, 38562.96),
    "Городской округ Котельники": (12184.11, 123716.18, 64052.44, 39890.87),
    "Городской округ Красногорск": (10430.48, 121711.11, 60954.81, 39080.49),
    "Городской округ Лобня": (8140.38, 101895.24, 46845.94, 38965.49),
    "Городской округ Лосино-Петровский": (5049.8, 70197.31, 28484.45, 39604.95),
    "Городской округ Лотошино": (2061.12, 52736.64, None, 39531.37),
    "Городской округ Луховицы": (2543.34, 54592.42, 20237.03, 39770.46),
    "Городской округ Лыткарино": (7519.22, 92895.11, 45165.61, 31710.06),
    "Городской округ Люберцы": (10497.92, 115348.4, 64916.15, 35063.66),
    "Городской округ Молодёжный (ЗАТО)": (3194.17, 70719.71, None, 31913.31),
    "Городской округ Мытищи": (8517.94, 114047.68, 59367.73, 37284.12),
    "Городской округ Павловский Посад": (3733.55, 58802.55, 21885.76, 38064.73),
    "Городской округ Подольск": (7588.91, 97660.18, 50581.14, 38085.8),
    "Городской округ Протвино": (4898.3, 63799.53, None, 35061.04),
    "Городской округ Пушкинский": (6867.34, 87321.37, 43729.9, 39146.67),
    "Городской округ Пущино": (4607.71, 64221.31, None, 37841.95),
    "Городской округ Реутов": (11038.32, 139819.22, 72906.81, 38222.57),
    "Городской округ Серебряные Пруды": (1944.87, 45849.7, None, 41657.4),
    "Городской округ Серпухов": (3305.65, 62966.52, 20667.74, 39160.19),
    "Городской округ Солнечногорск": (6076.32, 79018.84, 33861.37, 39771.92),
    "Городской округ Ступино": (3398.93, 62547.44, 24320.76, 42074.54),
    "Городской округ Фрязино": (6270.61, 81595.74, 38411.19, 43314.85),
    "Городской округ Химки": (12188.54, 119516.93, 57268.52, 40771.41),
    "Городской округ Черноголовка": (5588.55, 79285.58, None, 40009.56),
    "Городской округ Чехов": (4498.63, 73592.22, None, 37825.67),
    "Городской округ Шатура": (2411.06, 43992.2, 19573.71, 37792.65),
    "Городской округ Шаховская": (2155.57, 63426.65, None, 36091.07),
    "Городской округ Щёлково": (5520.45, 78288.34, 34175.96, 39487.83),
    "Городской округ Электрогорск": (2907.52, 49605.77, None, 40966.76),
    "Городской округ Электросталь": (5869.11, 65664.05, 28879.04, 37302.28),
    "Дмитровский городской округ": (4462.9, 69135.16, 26198.58, 40942.51),
    "Ленинский городской округ": (9069.43, 104163.91, 54076.76, 42154.41),
    "Можайский городской округ": (2424.13, 63956.49, 22058.45, 37055.57),
    "Наро-Фоминский городской округ": (4372.75, 84845.66, 38194.53, 40884.36),
    "Одинцовский городской округ": (8747.63, 116541.94, 62733.36, 40335.83),
    "Орехово-Зуевский городской округ": (3433.61, 52165.11, 17790.56, 39233.95),
    "Раменский городской округ": (6344.77, 87313.83, 33821.38, 41758.35),
    "Рузский городской округ": (3358.11, 60957.13, None, 41545.51),
    "Сергиево-Посадский городской округ": (3666.12, 65732.78, 32825.64, 37892.26),
    "Талдомский городской округ": (2749.47, 49520.02, 22307.21, 34777.06),
}


# Итоговая строка таблицы УПКС — среднее по области, а не муниципальное образование.
_MO_UPKS_REGION_AVERAGE = (6755.28, 94205.97, 56282.5, 39228.68)

# Тур государственной кадастровой оценки, из которого взяты УПКС.
# Земельные участки и ОКС оцениваются в разные годы, поэтому источники разные.
_MO_UPKS_SOURCE = {
    "land": {
        "report": "Отчёт № 01/2022 об итогах государственной кадастровой оценки объектов недвижимости Московской области",
        "valuation_date": "01.01.2022",
        "applied_from": "01.01.2023",
        "next_valuation_date": "01.01.2026",
        "next_applied_from": "01.01.2027",
    },
    "oks": {
        "report": "Отчёт № 01/2023 об итогах государственной кадастровой оценки объектов недвижимости Московской области",
        "valuation_date": "01.01.2023",
        "applied_from": "01.01.2024",
        "next_valuation_date": "01.01.2027",
        "next_applied_from": "01.01.2028",
    },
    "note": (
        "Кадастровая стоимость конкретных участков берётся живьём из ЕГРН на момент запроса, "
        "таблицы УПКС нужны только для целевой стоимости жилой застройки и коэффициентов К1 и К. "
        "Государственная кадастровая оценка проводится раз в четыре года, поэтому таблицы "
        "заменяются после утверждения следующего тура."
    ),
}

# ---------------------------------------------------------------------------
# Свежесть справочников
#
# Справочники устаревают тихо, и это худший вид устаревания: расчёт идёт,
# числа выглядят как обычно, а под ними прошлогодний тариф. Ни ошибки, ни
# предупреждения — просто другая цифра, и заметить её можно только сверкой с
# первоисточником, до которой обычно не доходит.
#
# Поэтому у каждого справочника объявлен его срок жизни: квартал, год или
# четыре года кадастровой оценки. Раз в день сводка администраторам говорит,
# что пора обновить, — до того, как по устаревшему тарифу примут решение.
# ---------------------------------------------------------------------------


def _quarter_of(moment: date) -> str:
    return f"{moment.year}-Q{(moment.month - 1) // 3 + 1}"


def _quarter_shift(quarter: str, steps: int) -> str:
    try:
        year, index = quarter.split("-Q")
        total = int(year) * 4 + int(index) - 1 + steps
        return f"{total // 4}-Q{total % 4 + 1}"
    except Exception:
        return quarter


def reference_freshness(today: date | None = None) -> list[dict[str, Any]]:
    """Что пора обновить и когда это стало пора.

    Возвращает по строке на справочник: что это, чем он живёт сейчас, до
    какого момента годен и просрочен ли. Проверка не лезет в интернет — она
    сравнивает объявленный срок с календарём, а обновление всё равно делает
    человек, который принесёт документ.
    """
    now = today or date.today()
    quarter = _quarter_of(now)
    rows: list[dict[str, Any]] = []

    def row(key: str, title: str, current: str, valid_until: str, source: str,
            stale: bool, hint: str) -> None:
        rows.append({"key": key, "title": title, "current": current,
                     "valid_until": valid_until, "source": source,
                     "stale": bool(stale), "hint": hint})

    # Рыночные цены Подмосковья — распоряжение Комитета по ценам и тарифам,
    # выходит на полугодие или квартал; период записан в самом справочнике.
    market = _mo_market_price_table()
    period = str(market.get("period") or "")
    year_match = re.search(r"(20\d\d)", period)
    market_year = int(year_match.group(1)) if year_match else now.year
    market_stale = market_year < now.year or (
        market_year == now.year and "IV" in period and now.month == 12)
    row("mo_market_price", "Рыночные цены Подмосковья (расчёт платы за ВРИ)",
        period or "не указан", f"{market_year} год", str(market.get("document") or ""),
        market_stale,
        "Распоряжение Комитета по ценам и тарифам МО — обновляется на новый период")

    # УПКС Подмосковья — государственная кадастровая оценка, раз в четыре года.
    for kind, label in (("land", "УПКС земли"), ("oks", "УПКС ОКС")):
        block = _MO_UPKS_SOURCE.get(kind) or {}
        applied = str(block.get("applied_from") or "")
        next_applied = str(block.get("next_applied_from") or "")
        try:
            next_date = datetime.strptime(next_applied, "%d.%m.%Y").date()
        except ValueError:
            next_date = None
        row(f"mo_upks_{kind}", f"{label} Подмосковья (кадастровая оценка)",
            f"применяется с {applied}", next_applied or "—",
            str(block.get("report") or ""),
            bool(next_date and now >= next_date),
            "Новый тур оценки утверждается раз в четыре года")

    # Кзатр льготы МПТ Москвы — база приказа × утверждённый индекс ДЭПР к
    # декабрю 2025. Пока индекс текущего квартала принесён (распоряжение
    # ДЭПР), напоминание молчит; сменился квартал без индекса — загорается.
    try:
        import mpt_calculator

        current_kzatr = mpt_calculator.kzatr_for_quarter(quarter)
        known_quarters = sorted(mpt_calculator.KZATR_INDICES_TO_DEC2025)
        latest_known = (known_quarters[-1] if known_quarters
                        else mpt_calculator.KZATR_INDEXATION_FROM_QUARTER)
        row("mpt_kzatr", "Кзатр льготы МПТ Москвы",
            (f"{current_kzatr} тыс ₽/м² на {quarter}" if current_kzatr is not None
             else f"{mpt_calculator.KZATR_BASE} тыс ₽/м² с "
                  f"{mpt_calculator.KZATR_BASE_FROM.isoformat()} — индекс "
                  f"{quarter} не принесён"),
            f"квартал {_quarter_shift(latest_known, 1)}",
            "Приказ ДИиПП от 10.03.2026 · " + mpt_calculator.KZATR_INDICES_SOURCE,
            current_kzatr is None and mpt_calculator.quarter_is_indexed(quarter),
            "Индекс нового квартала утверждается распоряжением ДЭПР "
            "(обобщённый индекс стоимости строительства за последний месяц "
            "предыдущего квартала к декабрю 2025) — принести распоряжение")
    except Exception:
        pass

    # РНГП Московской области. Норматив правят несколько раз в год — за 2026-й
    # трижды, — а справочник об этом молчит: числа выглядят одинаково свежими
    # что через неделю после поправки, что через год. Строка объявляет, по
    # какой редакции мы живём и когда её последний раз читали глазами; сама
    # редакция и цитаты лежат в mo_rngp_reference.
    try:
        import mo_rngp_reference

        state = mo_rngp_reference.reference_status()
        verified = datetime.strptime(state["verified_at"], "%Y-%m-%d").date()
        row("mo_rngp", "РНГП Московской области (нормативы ТЭП и парковок)",
            f"редакция {state['effective_from']}, сверено "
            f"{state['verified_at']}, открытых дыр {state['rules_unresolved']}",
            (verified.replace(year=verified.year + 1)).isoformat(),
            state["amended_by"] + " · " + state["official_source"],
            (now - verified).days > 365,
            "Норматив меняется несколько раз в год — перечитать действующую "
            "редакцию на publication.pravo.gov.ru и обновить mo_rngp_reference")
    except Exception:
        pass

    return rows


def stale_references(today: date | None = None) -> list[dict[str, Any]]:
    return [item for item in reference_freshness(today) if item["stale"]]


@app.get("/reference/freshness")
def reference_freshness_endpoint() -> dict[str, Any]:
    rows = reference_freshness()
    return {"checked_at": date.today().isoformat(),
            "stale": [item["key"] for item in rows if item["stale"]],
            "references": rows}


# Названия одного и того же округа в разных документах.
_MO_DISTRICT_SYNONYMS = {
    "павлово-посадский": "Городской округ Павловский Посад",
    "павловский посад": "Городской округ Павловский Посад",
}

_MO_QUARTER_UPKS_PATH = Path(__file__).resolve().parent / "data" / "upks_oks_quarters.csv.gz"
_mo_quarter_upks: dict[str, tuple[float | None, float | None, float | None]] | None = None
_mo_quarter_lock = threading.Lock()

# Нормативы РНГП Московской области. Любой из них можно переопределить в запросе.
MO_NORMS_DEFAULT: dict[str, float] = {
    "living_space_per_person_sqm": 28.0,
    "kindergarten_places_per_1000": 65.0,
    "kindergarten_site_sqm_per_place": 38.0,
    "kindergarten_gba_sqm_per_place": 27.0,
    # 135 — показатель «при отсутствии сведений о демографическом составе»
    # (п. 5.18 абз. 2 РНГП МО в ред. 762/18); основное правило — 100 % детей
    # 6–15 лет + 50 % детей 15–17 лет, и его здесь нет: состава населения у
    # проекта на стадии оценки не бывает.
    "school_places_per_1000": 135.0,
    "school_places_step": 25.0,
    "school_site_sqm_per_place": 31.0,
    "school_gba_sqm_per_place": 27.0,
    "clinic_visits_per_1000": 17.75,
    "clinic_site_ha": 0.3,
    "clinic_gba_sqm_per_visit": 15.0,
    "parking_permanent_per_1000": 356.0,
    "parking_permanent_share": 0.9,
    # Временное хранение область задаёт ЧИСЛОМ на тысячу жителей, а не долей от
    # уровня автомобилизации, как считает московская методика: «не менее 30
    # автомобилей на 1000 человек расчётного населения» (п. 5.12 РНГП в
    # редакции 774-ПП, цитата — в mo_rngp_reference). Здесь стояла доля 0,18 от
    # 356 — 64 места на тысячу: столько дал ППТ заказчика, и модель
    # воспроизводила ЕГО проект. Решение владельца (04.09.2026): «ППТ может
    # быть у всех разное, а норматив один» — модель показывает норматив, а
    # конкретное требование вписывают, когда оно известно. Норма — это ПОЛ:
    # проект вправе дать больше, и число правится как любой другой норматив.
    "parking_temporary_per_1000": 30.0,
    "parking_underground_sqm_per_space": 35.0,
    "parking_surface_sqm_per_space": 22.5,
    "jobs_share_of_population": 0.5,
    "office_sqm_per_job": 10.0,
    "green_quarter_sqm_per_person": 6.5,
    "green_public_sqm_per_person": 4.4,
    "retail_sqm_per_1000": 1530.0,
    "retail_gba_factor": 1.3,
    "service_jobs_per_1000": 10.9,
    "service_sqm_per_job": 30.0,
    "catering_seats_per_1000": 40.0,
    "catering_sqm_per_seat": 6.0,
    "sport_hall_sqm_per_1000": 106.0,
    "pool_mirror_sqm_per_1000": 9.96,
    "pool_gba_factor": 1.5,
    "club_sqm_per_1000": 150.0,
    "pharmacy_sqm": 60.0,
    "mfc_sqm_per_2000": 14.0,
    "police_sqm": 45.0,
    "hospital_beds_per_1000": 6.0,
    "ambulance_cars_per_1000": 0.1,
    "fire_cars_per_1000": 0.2,
    "gns_apartment_factor": 0.6351,
    "total_area_apartment_factor": 0.68,
    "gns_commercial_factor": 0.8,
    # Кд здесь нет намеренно: он задаётся таблицей 3 к 1745-ПП по округу или
    # руками (`vri_kd` запроса). Запас 0,1 для округов вне таблицы источника
    # не имел, и владелец решил (16.10.2026) не считать плату без Кд.
}

_MO_DENSITY_DEFAULT_SQM_PER_HA = 30000.0


def _mo_quarter_upks_table() -> dict[str, tuple[float | None, float | None, float | None]]:
    """Реестр УПКС ОКС по кадастровым кварталам. Файл необязателен."""
    global _mo_quarter_upks
    if _mo_quarter_upks is not None:
        return _mo_quarter_upks
    with _mo_quarter_lock:
        if _mo_quarter_upks is not None:
            return _mo_quarter_upks
        table: dict[str, tuple[float | None, float | None, float | None]] = {}
        try:
            with gzip.open(_MO_QUARTER_UPKS_PATH, "rt", encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    quarter = str(row.get("quarter") or "").strip()
                    if not quarter:
                        continue
                    table[quarter] = (
                        _land_float(row.get("mkd")),
                        _land_float(row.get("parking")),
                        _land_float(row.get("commercial")),
                    )
        except FileNotFoundError:
            table = {}
        except Exception:
            table = {}
        _mo_quarter_upks = table
        return table


def _mo_normalize_name(value: str) -> str:
    text = str(value or "").lower().replace("ё", "е")
    text = re.sub(r"\(зато\)|зато", " ", text)
    text = re.sub(r"городской округ|муниципальный округ|городском округе|г\.?\s?о\.?|г\.о", " ", text)
    text = re.sub(r"[^а-яa-z0-9\-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_MO_DISTRICT_INDEX = {_mo_normalize_name(name): name for name in _MO_UPKS_BY_DISTRICT}
for _synonym, _canonical in _MO_DISTRICT_SYNONYMS.items():
    _MO_DISTRICT_INDEX.setdefault(_mo_normalize_name(_synonym), _canonical)


def _mo_district_upks(district: str) -> dict[str, Any]:
    """Справочные УПКС по округу: земля под жильё и ОКС МКД."""
    canonical = _MO_DISTRICT_INDEX.get(_mo_normalize_name(district)) or (
        district if district in _MO_UPKS_BY_DISTRICT else ""
    )
    if not canonical:
        return {"district": "", "upks_land_residential": None, "upks_oks_mkd": None,
                "upks_oks_parking": None, "upks_oks_commercial": None}
    land, mkd, parking, commercial = _MO_UPKS_BY_DISTRICT[canonical]
    return {
        "district": canonical,
        "upks_land_residential": land,
        "upks_oks_mkd": mkd,
        "upks_oks_parking": parking,
        "upks_oks_commercial": commercial,
    }


def _mo_district_from_address(address: str) -> str:
    """Округ по адресу ЕГРН: сначала точное вхождение, затем по названию."""
    text = _mo_normalize_name(address)
    if not text:
        return ""
    best = ""
    for key, canonical in _MO_DISTRICT_INDEX.items():
        if not key:
            continue
        if re.search(rf"(?<![а-я]){re.escape(key)}(?![а-я])", text) and len(key) > len(_mo_normalize_name(best)):
            best = canonical
    return best


def _mo_norms(overrides: dict[str, Any] | None = None) -> dict[str, float]:
    norms = dict(MO_NORMS_DEFAULT)
    for key, value in (overrides or {}).items():
        number = _land_float(value)
        if key in norms and number is not None:
            norms[key] = number
    return norms


def _mo_ceil(value: float) -> int:
    return int(math.ceil(round(float(value), 6)))


def mo_social_program(apartments_sqm: float, norms: dict[str, float] | None = None) -> dict[str, Any]:
    """Потребность в социальной инфраструктуре по РНГП МО от площади квартир."""
    n = _mo_norms(norms if isinstance(norms, dict) else None)
    apartments = max(0.0, _land_float(apartments_sqm) or 0.0)
    population = _mo_ceil(apartments / n["living_space_per_person_sqm"]) if apartments else 0
    per_1000 = population / 1000.0

    kindergarten_need = per_1000 * n["kindergarten_places_per_1000"]
    kindergarten_places = _mo_ceil(kindergarten_need)
    school_need = per_1000 * n["school_places_per_1000"]
    step = max(1.0, n["school_places_step"])
    school_places = int(_mo_ceil(school_need / step) * step)
    clinic_need = per_1000 * n["clinic_visits_per_1000"]
    clinic_capacity = _mo_ceil(clinic_need)

    parking_permanent = _mo_ceil(
        population * n["parking_permanent_per_1000"] / 1000.0 * n["parking_permanent_share"]
    )
    parking_temporary = _mo_ceil(population * n["parking_temporary_per_1000"] / 1000.0)
    underground_sqm = parking_permanent * n["parking_underground_sqm_per_space"]

    retail_trade_sqm = per_1000 * n["retail_sqm_per_1000"]
    retail_gba = retail_trade_sqm * n["retail_gba_factor"]
    service_jobs = per_1000 * n["service_jobs_per_1000"]
    service_gba = service_jobs * n["service_sqm_per_job"]
    catering_seats = per_1000 * n["catering_seats_per_1000"]
    catering_gba = catering_seats * n["catering_sqm_per_seat"]
    sport_gba = per_1000 * n["sport_hall_sqm_per_1000"]
    pool_mirror = per_1000 * n["pool_mirror_sqm_per_1000"]
    pool_gba = pool_mirror * n["pool_gba_factor"]
    club_gba = per_1000 * n["club_sqm_per_1000"]
    pharmacy_gba = n["pharmacy_sqm"] if population else 0.0
    mfc_gba = population * n["mfc_sqm_per_2000"] / 2000.0
    police_gba = n["police_sqm"] if population else 0.0

    public_premises = [
        ("Торговые объекты", retail_gba),
        ("Бытовое обслуживание", service_gba),
        ("Общественное питание", catering_gba),
        ("Спортивные залы", sport_gba),
        ("Бассейн", pool_gba),
        ("Учреждения клубного типа", club_gba),
        ("Аптека", pharmacy_gba),
        ("МФЦ", mfc_gba),
        ("Отделение полиции", police_gba),
    ]
    public_premises_sqm = sum(value for _, value in public_premises)

    # Рабочие места, создаваемые социальными и коммерческими объектами.
    # Торговля создаёт место на каждые 15 м² ГБА — тем же числом считается и
    # обратная задача: сколько торговли нужно, чтобы закрыть дефицит мест.
    # Число одно и живёт в одном месте, иначе две ветки разойдутся молча.
    retail_sqm_per_job = 15.0
    jobs_rows = [
        ("Дошкольная образовательная организация", round(kindergarten_places * 0.2)),
        ("Общеобразовательная организация", _mo_ceil(school_places * 0.15)),
        ("Поликлиника", _mo_ceil(clinic_capacity * 0.3)),
        ("Торговые объекты", round(retail_gba / retail_sqm_per_job)),
        ("Бытовое обслуживание", _mo_ceil(service_jobs)),
        ("Общественное питание", round(catering_seats / 6.0)),
        ("Досуговый центр", _mo_ceil(club_gba / 60.0) if club_gba else 0),
        ("Аптека", round(pharmacy_gba / 15.0)),
        ("Отделение полиции", _mo_ceil(population / 2800.0) if population else 0),
        ("Спортивные объекты", _mo_ceil((sport_gba + pool_gba) / 60.0) if sport_gba + pool_gba else 0),
        ("МФЦ", round(mfc_gba / 10.0)),
    ]
    jobs_from_objects = sum(int(value) for _, value in jobs_rows)
    jobs_required = population * n["jobs_share_of_population"]
    jobs_deficit = max(0.0, jobs_required - jobs_from_objects)
    office_sqm = jobs_deficit * n["office_sqm_per_job"]
    jobs_rows.append(("Офисные помещения", int(round(jobs_deficit))))

    return {
        "apartments_sqm": round(apartments, 2),
        "population": population,
        "kindergarten": {
            "required_places": round(kindergarten_need, 3),
            "places": kindergarten_places,
            "site_ha": round(kindergarten_places * n["kindergarten_site_sqm_per_place"] / 10000.0, 4),
            "gba_sqm": round(kindergarten_places * n["kindergarten_gba_sqm_per_place"], 2),
        },
        "school": {
            "required_places": round(school_need, 3),
            "places": school_places,
            "site_ha": round(school_places * n["school_site_sqm_per_place"] / 10000.0, 4),
            "gba_sqm": round(school_places * n["school_gba_sqm_per_place"], 2),
        },
        "clinic": {
            "required_capacity": round(clinic_need, 3),
            "capacity": clinic_capacity,
            "site_ha": round(n["clinic_site_ha"], 4),
            "gba_sqm": round(clinic_capacity * n["clinic_gba_sqm_per_visit"], 2),
        },
        "parking": {
            "permanent_spaces": parking_permanent,
            # Временные места в проекте не строятся (решение владельца,
            # 04.09.2026): норматив прямо разрешает размещать их в границах
            # ЖИЛОГО РАЙОНА, а не квартала, и закрывает их район. Число
            # остаётся нормативной потребностью и названо ею на экране —
            # посчитанное и не показанное читается как забытое.
            "temporary_spaces": parking_temporary,
            "temporary_built": False,
            "underground_sqm": round(underground_sqm, 2),
            "surface_temporary_ha": round(parking_temporary * n["parking_surface_sqm_per_space"] / 10000.0, 4),
        },
        "green": {
            "quarter_sqm": round(population * n["green_quarter_sqm_per_person"], 2),
            "public_sqm": round(population * n["green_public_sqm_per_person"], 2),
            "public_ha": round(population * n["green_public_sqm_per_person"] / 10000.0, 4),
        },
        "public_premises_sqm": round(public_premises_sqm, 2),
        "public_premises": [{"label": label, "gba_sqm": round(value, 2)} for label, value in public_premises],
        "office_sqm": round(office_sqm, 2),
        "jobs": {
            "required": round(jobs_required, 2),
            "from_objects": jobs_from_objects,
            "deficit": round(jobs_deficit, 2),
            "rows": [{"label": label, "jobs": int(value)} for label, value in jobs_rows],
            # Дефицит мест — это будущий объект, а не строка справки: человеку
            # решать, офис это или торговля, но знать о нём он должен на ТЭП,
            # а не когда посадка уже сложилась (замечание владельца, 19.08.2026).
            "office_sqm": round(office_sqm, 2),
            "retail_sqm": round(jobs_deficit * retail_sqm_per_job, 2),
            "office_sqm_per_job": n["office_sqm_per_job"],
            "retail_sqm_per_job": retail_sqm_per_job,
        },
        "budget_compensation": {
            "hospital_beds": round(per_1000 * n["hospital_beds_per_1000"], 3),
            "ambulance_cars": round(per_1000 * n["ambulance_cars_per_1000"], 3),
            "fire_cars": round(per_1000 * n["fire_cars_per_1000"], 3),
        },
        "gns_sqm": round(apartments / n["gns_apartment_factor"], 2) if apartments else 0.0,
        "apartments_total_area_sqm": round(apartments / n["total_area_apartment_factor"], 2) if apartments else 0.0,
        "norms": n,
    }


def mo_vri_payment(
    parcels: list[dict[str, Any]],
    *,
    upks_target: float | None,
    upks_average_oks: float | None,
    apartments_sqm: float,
    upks_quarter_oks: float | None = None,
    market_price_rub_per_sqm: float | None,
    kd: float | None,
    kd_missing_reason: str = "",
) -> dict[str, Any]:
    """Плата за изменение ВРИ по методике приложенного расчёта.

    `kd` — коэффициент доходности (таблица 3 к 1745-ПП или ручной). Без него
    плата не считается: умолчания у Кд нет, подставлять чужую группу нельзя
    (решение владельца 16.10.2026), и ноль здесь не ответ, а отсутствие ответа.
    `kd_missing_reason` — почему Кд нет, словами того, кто это знает (округ,
    таблица); без неё предупреждение общее.

    `upks_average_oks` — УПКСср в k1 = Кср / УПКСср: окружное значение.
    `upks_quarter_oks` — Р в К = (Р × S) × Кдоход / G: показатель кадастрового
    квартала участка (1745-ПП п. 4.8); окружной берётся, только если
    квартального нет. Пока оба были окружными, их отношение всегда давало 1 и
    плата не зависела от квартала, а по акту зависит (решение владельца
    25.10.2026: брать квартал, если он есть).
    """
    rows: list[dict[str, Any]] = []
    total_area = 0.0
    total_kc1 = 0.0
    total_kc2 = 0.0
    target = _land_float(upks_target)
    for parcel in parcels or []:
        area = _land_float(parcel.get("area_sqm")) or 0.0
        kc1 = _land_float(parcel.get("cadastral_value_rub")) or 0.0
        kc2 = area * target if target else 0.0
        total_area += area
        total_kc1 += kc1
        total_kc2 += kc2
        rows.append({
            "cadastral_number": str(parcel.get("cadastral_number") or ""),
            "area_sqm": round(area, 2),
            "permitted_use": str(parcel.get("permitted_use") or ""),
            "cadastral_value_rub": round(kc1, 2),
            # Дата определения кадастровой стоимости из ЕГРН — видно, насколько она свежая.
            "cadastral_value_date": str(parcel.get("cadastral_value_date") or ""),
            "upks_current": round(kc1 / area, 2) if area else None,
            "upks_target": round(target, 2) if target else None,
            "cadastral_value_new_rub": round(kc2, 2),
            "delta_rub": round(kc2 - kc1, 2),
        })
    delta = total_kc2 - total_kc1
    apartments = max(0.0, _land_float(apartments_sqm) or 0.0)
    upks_avg = _land_float(upks_average_oks)
    market_price = _land_float(market_price_rub_per_sqm)
    warnings: list[str] = []

    kd = _land_float(kd)
    if kd is not None and kd <= 0:
        kd = None
    k1 = (market_price / upks_avg) if (market_price and upks_avg) else None
    g = delta * 1.00001
    upks_quarter = _land_float(upks_quarter_oks)
    if upks_quarter is not None and upks_quarter <= 0:
        upks_quarter = None
    upks_p = upks_quarter or upks_avg
    upks_p_basis = ("кадастровый квартал участка" if upks_quarter
                    else ("округ: квартального показателя нет" if upks_avg else ""))
    k = (apartments * upks_p * kd / g) if (kd is not None and upks_p and g) else None
    payment = delta * k1 * k if (k1 is not None and k is not None) else None
    # Алгебраически цепочка сворачивается: П = Кср × площадь квартир × Кд × Р / УПКСср.
    p_ratio = (upks_p / upks_avg) if (upks_p and upks_avg) else 1.0
    payment_direct = (market_price * apartments * kd * p_ratio
                      if (market_price and kd is not None) else None)

    if not rows:
        warnings.append(
            "Участки ЕГРН не заданы: разница кадастровых стоимостей не рассчитана, "
            "плата показана по прямой формуле Кср × площадь квартир × Кд."
        )
    elif delta <= 0:
        warnings.append(
            "Кадастровая стоимость участков не ниже целевой для жилой застройки: "
            "разница неположительная, плата по методике не определяется."
        )
    if not target:
        warnings.append("Для округа нет УПКС земель жилой застройки — целевая кадастровая стоимость не рассчитана.")
    if not upks_avg:
        warnings.append("Для округа нет УПКС ОКС многоквартирных домов — коэффициенты К и К1 не рассчитаны.")
    if not market_price:
        warnings.append("Не задана средняя цена м² (Кср) — плата за смену ВРИ не рассчитана.")
    if kd is None:
        warnings.append(
            kd_missing_reason
            or "Кд не установлен — плата за смену ВРИ не рассчитана; впишите коэффициент доходности вручную (vri_kd)."
        )

    return {
        "parcels": rows,
        "total_area_sqm": round(total_area, 2),
        "cadastral_value_current_rub": round(total_kc1, 2),
        "cadastral_value_target_rub": round(total_kc2, 2),
        "delta_rub": round(delta, 2),
        "upks_target": round(target, 2) if target else None,
        "upks_average_oks": round(upks_avg, 2) if upks_avg else None,
        "upks_p": round(upks_p, 2) if upks_p else None,
        "upks_p_basis": upks_p_basis,
        "market_price_rub_per_sqm": round(market_price, 2) if market_price else None,
        "kd": kd,
        "k1": round(k1, 4) if k1 is not None else None,
        "k": round(k, 4) if k is not None else None,
        "payment_rub": round(payment, 2) if payment is not None else None,
        "payment_mln": round(payment / 1_000_000.0, 3) if payment is not None else None,
        "payment_direct_rub": round(payment_direct, 2) if payment_direct is not None else None,
        # Что берётся в модель: методика по участкам, иначе прямая формула.
        "payment_used_rub": round(used, 2) if (used := (payment if payment is not None else payment_direct)) is not None else None,
        "payment_used_mln": round(used / 1_000_000.0, 3) if used is not None else None,
        "payment_basis": (
            "методика по участкам ЕГРН" if payment is not None
            else ("прямая формула Кср × площадь квартир × Кд" if payment_direct is not None
                  else ("Кд не установлен" if kd is None else "не определена"))
        ),
        "warnings": warnings,
    }


# --- Кср: средняя рыночная стоимость 1 м² жилья по муниципальным образованиям --
#
# Источник — распоряжения Комитета по ценам и тарифам Московской области
# (например, от 28.04.2026 № 114-Р на III–IV кварталы 2026 года). Таблица
# загружается в приложение файлом: официальный источник публикует её
# приложением к распоряжению, автоматического API у него нет.

_MO_MARKET_PRICE_PATH = Path(
    _env_str("MO_MARKET_PRICE_PATH") or (Path(__file__).resolve().parent / "data" / "mo_market_price.csv")
)
_MO_MARKET_PRICE_MIN = 20000.0
_MO_MARKET_PRICE_MAX = 1000000.0
_mo_market_price: dict[str, Any] | None = None
_mo_market_price_lock = threading.Lock()


def _mo_market_price_table() -> dict[str, Any]:
    """Справочник Кср: {ключ округа: цена} плюс сведения об источнике."""
    global _mo_market_price
    if _mo_market_price is not None:
        return _mo_market_price
    with _mo_market_price_lock:
        if _mo_market_price is not None:
            return _mo_market_price
        prices: dict[str, float] = {}
        period = ""
        document = ""
        try:
            with open(_MO_MARKET_PRICE_PATH, "r", encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    name = _land_text(row.get("municipality"))
                    price = _land_float(row.get("price_rub_per_sqm"))
                    if not name or price is None:
                        continue
                    prices[_mo_normalize_name(name)] = price
                    period = period or _land_text(row.get("period"))
                    document = document or _land_text(row.get("document"))
        except FileNotFoundError:
            pass
        except Exception:
            prices = {}
        _mo_market_price = {"prices": prices, "period": period, "document": document}
        return _mo_market_price


# Коэффициент доходности (Кд) — таблица 3 постановления Правительства
# Московской области от 19.12.2025 № 1745: три группы округов, 10 / 5 / 1 %.
# Округ, которого в таблице нет, оставляем без значения: подставлять чужую
# группу нельзя, коэффициент умножает плату на миллиарды.
_MO_VRI_KD_PATH = Path(__file__).resolve().parent / "data" / "mo_vri_kd.csv"
_mo_vri_kd: dict[str, Any] | None = None
_mo_vri_kd_lock = threading.Lock()


def _mo_vri_kd_table() -> dict[str, Any]:
    global _mo_vri_kd
    if _mo_vri_kd is not None:
        return _mo_vri_kd
    with _mo_vri_kd_lock:
        if _mo_vri_kd is not None:
            return _mo_vri_kd
        values: dict[str, float] = {}
        document = ""
        try:
            with open(_MO_VRI_KD_PATH, "r", encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    name = _land_text(row.get("municipality"))
                    kd = _land_float(row.get("kd"))
                    if not name or kd is None:
                        continue
                    values[_mo_normalize_name(name)] = kd
                    document = document or _land_text(row.get("document"))
        except FileNotFoundError:
            pass
        except Exception:
            values = {}
        _mo_vri_kd = {"values": values, "document": document}
        return _mo_vri_kd


def _mo_vri_kd_for(district: str) -> tuple[float | None, str, str]:
    """Кд по округу: (значение, документ, основание)."""
    table = _mo_vri_kd_table()
    kd = table["values"].get(_mo_normalize_name(district))
    if kd is not None:
        return kd, table["document"], "округ"
    return None, table["document"], "округа нет в таблице 3"


_MO_MARKET_PRICE_REGION_KEY = "московская область среднее"


def _mo_market_price_for(district: str) -> tuple[float | None, str, str, str]:
    """Кср по округу; если округа нет в распоряжении — среднее по области."""
    table = _mo_market_price_table()
    price = table["prices"].get(_mo_normalize_name(district))
    if price is not None:
        return price, table.get("period", ""), table.get("document", ""), "округ"
    region = table["prices"].get(_MO_MARKET_PRICE_REGION_KEY)
    if region is not None:
        return region, table.get("period", ""), table.get("document", ""), "среднее по области"
    return None, table.get("period", ""), table.get("document", ""), ""


def _mo_market_price_rows_from_tables(tables: dict[str, list[list[Any]]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Разбор приложения к распоряжению: пары «муниципальное образование — цена»."""
    matched: dict[str, dict[str, Any]] = {}
    unmatched: list[str] = []
    region_average: float | None = None
    for rows in tables.values():
        for row in rows or []:
            cells = [cell for cell in row if cell not in (None, "")]
            if len(cells) < 2:
                continue
            name = ""
            price: float | None = None
            for cell in cells:
                text = _land_text(cell)
                number = _land_float(cell)
                looks_numeric = bool(re.fullmatch(r"[\d\s .,]+", text)) if text else False
                if not name and text and not looks_numeric and re.search(r"[А-Яа-яЁё]{4}", text):
                    name = text
                elif number is not None and looks_numeric and _MO_MARKET_PRICE_MIN <= number <= _MO_MARKET_PRICE_MAX:
                    price = number
            if not name or price is None:
                continue
            clean = re.sub(r"^\s*\d+[.)]?\s*", "", name).strip()
            if re.search(r"в целом по московской области", _mo_normalize_name(clean)):
                region_average = price
                continue
            key = _mo_normalize_name(clean)
            canonical = _MO_DISTRICT_INDEX.get(key)
            if canonical:
                matched[canonical] = {"municipality": canonical, "price_rub_per_sqm": price, "source_name": clean}
            elif key and key not in {_mo_normalize_name(item) for item in unmatched}:
                unmatched.append(clean)
    rows_out = [matched[name] for name in sorted(matched)]
    if region_average is not None:
        rows_out.append({
            "municipality": "Московская область (среднее)",
            "price_rub_per_sqm": region_average,
            "source_name": "в целом по Московской области",
        })
    return rows_out, unmatched


def _mo_market_price_save(rows: list[dict[str, Any]], period: str, document: str) -> tuple[str, bool]:
    """Сохранение справочника: CSV на диск (best effort) и в память процесса."""
    global _mo_market_price
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["municipality", "price_rub_per_sqm", "period", "document"])
    for row in rows:
        writer.writerow([row["municipality"], row["price_rub_per_sqm"], period, document])
    content = buffer.getvalue()
    stored = False
    try:
        _MO_MARKET_PRICE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _MO_MARKET_PRICE_PATH.write_text(content, encoding="utf-8")
        stored = True
    except Exception:
        stored = False
    with _mo_market_price_lock:
        _mo_market_price = {
            "prices": {_mo_normalize_name(row["municipality"]): row["price_rub_per_sqm"] for row in rows},
            "period": period,
            "document": document,
        }
    return content, stored


class MoMarketPriceRequest(BaseModel):
    rows: list[dict[str, Any]] = []
    period: str = ""
    document: str = ""
    session: str = ""
    key: str = ""


def _mo_market_price_writer(session: str, key: str) -> None:
    """Справочник Кср меняет только владелец сервиса.

    Кср — множитель платы за смену ВРИ (Кср × площадь квартир × Кд) в каждом
    расчёте по Подмосковью, и запись ложится на диск для всех. Открытая запись
    давала любому посетителю подменить плату в чужих расчётах и PDF. Закрыто и
    там, где владелец не настроен: справочник тогда правят файлом на сервере,
    а не запросом с улицы.
    """
    if not _is_admin_request(session, key):
        raise HTTPException(
            status_code=403,
            detail="Справочник средней цены м² (Кср) меняет только владелец сервиса.")


@app.get("/mo/market-price")
def mo_market_price() -> dict[str, Any]:
    """Текущий справочник средней рыночной стоимости 1 м² жилья."""
    table = _mo_market_price_table()
    known = {_mo_normalize_name(name): name for name in _MO_UPKS_BY_DISTRICT}
    rows = [
        {"municipality": known.get(key, key), "price_rub_per_sqm": value}
        for key, value in sorted(table["prices"].items(), key=lambda item: known.get(item[0], item[0]))
        if key != _MO_MARKET_PRICE_REGION_KEY
    ]
    return {
        "rows": rows,
        "count": len(rows),
        "region_average": table["prices"].get(_MO_MARKET_PRICE_REGION_KEY),
        "period": table.get("period", ""),
        "document": table.get("document", ""),
        "path": str(_MO_MARKET_PRICE_PATH),
        "source": (
            "Распоряжения Комитета по ценам и тарифам Московской области об установлении "
            "средней рыночной стоимости 1 м² общей площади жилья по муниципальным образованиям."
        ),
    }


@app.post("/mo/market-price")
def mo_market_price_set(req: MoMarketPriceRequest) -> dict[str, Any]:
    """Ручная загрузка справочника Кср списком строк."""
    _mo_market_price_writer(req.session, req.key)
    rows: list[dict[str, Any]] = []
    for item in req.rows or []:
        name = _land_text(item.get("municipality"))
        price = _land_float(item.get("price_rub_per_sqm"))
        if not name or price is None:
            continue
        canonical = _MO_DISTRICT_INDEX.get(_mo_normalize_name(name)) or name
        rows.append({"municipality": canonical, "price_rub_per_sqm": price})
    if not rows:
        raise HTTPException(status_code=400, detail="Не переданы строки справочника.")
    content, stored = _mo_market_price_save(rows, _land_text(req.period), _land_text(req.document))
    return {"saved": len(rows), "stored_on_disk": stored, "csv": content}


@app.post("/mo/market-price/import")
async def mo_market_price_import(request: Request, period: str = "", document: str = "",
                                 session: str = "", key: str = "") -> dict[str, Any]:
    """Импорт приложения к распоряжению: .xlsx с таблицей «МО — стоимость»."""
    _mo_market_price_writer(session, key)
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="Файл не передан")
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Файл слишком большой. Лимит 15 МБ.")
    try:
        tables = _xlsx_read_tables(data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Не удалось прочитать Excel: {exc}") from exc
    rows, unmatched = _mo_market_price_rows_from_tables(tables)
    if not rows:
        raise HTTPException(
            status_code=400,
            detail=(
                "В файле не найдены пары «муниципальное образование — стоимость». "
                "Нужен лист с наименованиями округов и ценой в рублях за м²."
            ),
        )
    content, stored = _mo_market_price_save(rows, _land_text(period), _land_text(document))
    known = [row for row in rows if row["municipality"] in _MO_UPKS_BY_DISTRICT]
    warnings: list[str] = []
    if unmatched:
        warnings.append("Не сопоставлены со справочником округов: " + ", ".join(unmatched[:10]) + ".")
    missing = [name for name in _MO_UPKS_BY_DISTRICT if name not in {row["municipality"] for row in rows}]
    if missing:
        warnings.append(f"Нет цены для {len(missing)} округов, например: " + ", ".join(missing[:5]) + ".")
    if not stored:
        warnings.append(
            "Справочник принят в память процесса, но не записан на диск — "
            "после перезапуска сервиса его нужно загрузить снова или положить CSV в репозиторий."
        )
    return {
        "rows": rows,
        "matched_districts": len(known),
        "unmatched": unmatched,
        "period": _land_text(period),
        "document": _land_text(document),
        "stored_on_disk": stored,
        "csv": content,
        "warnings": warnings,
    }


_MO_REGION_CODE = "50"


def _mo_check_region(numbers: list[str]) -> None:
    outside = [number for number in numbers if not str(number).startswith(_MO_REGION_CODE + ":")]
    if outside:
        raise HTTPException(
            status_code=400,
            detail=(
                "Калькулятор «Подмосковье» работает только по Московской области "
                "(кадастровый округ 50). Вне области: " + ", ".join(outside) + "."
            ),
        )


def _mo_parcels_from_query(query: str, limit: int) -> tuple[list[dict[str, Any]], list[str]]:
    """Участки ЕГРН по кадастровым номерам или адресу, только Московская область."""
    warnings: list[str] = []
    numbers: list[str] = []
    seen: set[str] = set()
    for number in _CADASTRAL_NUMBER_RE.findall(str(query or "").replace("：", ":")):
        if number not in seen:
            seen.add(number)
            numbers.append(number)
    if numbers:
        _mo_check_region(numbers)
        if len(numbers) > limit:
            warnings.append(
                f"В запросе {len(numbers)} кадастровых номеров, обработаны первые {limit}. "
                "Площадь территории и все расчёты от неё занижены — разбейте запрос на части."
            )
        results = _land_lookup_by_numbers(numbers[:limit])
    else:
        lookup = land_lookup(LandLookupRequest(query=query, limit=limit))
        warnings.extend(str(item) for item in lookup.get("warnings") or [])
        results = [item for item in lookup.get("results") or [] if item.get("kind") == "land"]
        found_numbers = [str(item.get("cadastral_number") or "") for item in results if item.get("found")]
        if found_numbers:
            _mo_check_region(found_numbers)
    parcels = [item for item in results if item.get("found")]
    missing = [str(item.get("cadastral_number") or "") for item in results if not item.get("found")]
    if missing:
        warnings.append("Нет сведений ЕГРН: " + ", ".join(number for number in missing if number) + ".")
    return parcels, warnings


def _mo_tep_and_inputs(
    social: dict[str, Any],
    vri: dict[str, Any],
    *,
    site_area_ha: float,
    norms: dict[str, float],
    average_flat_sqm: float,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    apartments = social["apartments_sqm"]
    public_sqm = social["public_premises_sqm"]
    office_sqm = social["office_sqm"]
    commercial_factor = norms["gns_commercial_factor"] or 0.8
    kindergarten = social["kindergarten"]
    school = social["school"]
    clinic = social["clinic"]
    parking = social["parking"]

    tep = copy.deepcopy(TEP_DEFAULT)
    tep["apartments"].update({
        "gns": social["gns_sqm"],
        "total_area": social["apartments_total_area_sqm"],
        "useful": apartments,
        "saleable": apartments,
        "transfer": 0,
        "units": round(apartments / average_flat_sqm, 2) if average_flat_sqm else 0,
    })
    tep["ground_commercial"].update({
        "gns": round(public_sqm / commercial_factor, 2),
        "total_area": public_sqm,
        "useful": public_sqm,
        "saleable": public_sqm,
        "transfer": 0,
        "units": 0,
    })
    tep["underground_parking"].update({
        "gns": parking["underground_sqm"],
        "total_area": parking["underground_sqm"],
        "useful": 0,
        "saleable": 0,
        "transfer": 0,
        "units": parking["permanent_spaces"],
        # Гостевых мест в области у нас нет: строятся только места ПОСТОЯННОГО
        # хранения, а временные закрывает жилой район. Ноль пишется явно —
        # без него движок вычел бы московскую одиннадцатую часть и объявил бы
        # девять процентов построенных мест непродаваемыми по чужой норме.
        "guest_units": 0,
    })
    for key, block, places_key in (
        ("kindergarten", kindergarten, "places"),
        ("school", school, "places"),
        ("clinic", clinic, "capacity"),
    ):
        tep[key].update({
            "gns": 0,
            "total_area": block["gba_sqm"],
            "useful": 0,
            "saleable": 0,
            "transfer": block["gba_sqm"],
            "units": block[places_key],
        })
    for key in (*(o.key for o in STANDALONE_OBJECTS if o.key != "sports"), "storage"):
        tep[key].update({"gns": 0, "total_area": 0, "useful": 0, "saleable": 0, "transfer": 0, "units": 0})

    inputs: dict[str, Any] = {
        # Блок по определению областной: правила рассрочки и процентов по ВРИ
        # берутся для Московской области, а не для Москвы.
        "vri_region": "mo",
        "kindergarten_places": kindergarten["places"],
        "school_places": school["places"],
        "clinic_capacity": clinic["capacity"],
        "social_dou_gba_sqm": kindergarten["gba_sqm"],
        "social_school_gba_sqm": school["gba_sqm"],
        "social_clinic_gba_sqm": clinic["gba_sqm"],
        "social_dou_norm_sqm": norms["kindergarten_gba_sqm_per_place"],
        "social_school_norm_sqm": norms["school_gba_sqm_per_place"],
        "social_clinic_norm_sqm": norms["clinic_gba_sqm_per_visit"],
        "social_mode": "Строительство",
    }
    if office_sqm > 0:
        inputs.update({
            "offices_enabled": True,
            "offices_gba_sqm": round(office_sqm / commercial_factor, 2),
            "offices_saleable_sqm": office_sqm,
        })
    return tep, inputs


def _mo_territory_balance(social: dict[str, Any], site_area_ha: float, norms: dict[str, float]) -> dict[str, Any]:
    """Упрощённый баланс: сколько территории остаётся под жилые дома и УДС."""
    items = [
        ("Участок ДОО", social["kindergarten"]["site_ha"]),
        ("Участок СОШ", social["school"]["site_ha"]),
        ("Участок поликлиники", social["clinic"]["site_ha"] if social["clinic"]["capacity"] else 0.0),
        ("Озеленение общего пользования", social["green"]["public_ha"]),
        ("Наземные парковки временного хранения", social["parking"]["surface_temporary_ha"]),
    ]
    used = sum(value for _, value in items)
    return {
        "site_area_ha": round(site_area_ha, 4),
        "items": [{"label": label, "area_ha": round(value, 4)} for label, value in items],
        "used_ha": round(used, 4),
        "remaining_ha": round(site_area_ha - used, 4),
        "note": (
            "Остаток — территория под жилые дома, УДС, приобъектные парковки и резервы. "
            "Отрицательное значение означает, что при заданной плотности участок не вмещает нормативную социалку."
        ),
    }


class MoCalculateRequest(BaseModel):
    query: str = ""
    site_area_ha: float = 0.0
    density_sqm_per_ha: float = _MO_DENSITY_DEFAULT_SQM_PER_HA
    district: str = ""
    market_price_rub_per_sqm: float = 0.0
    vri_kd: float = 0.0   # 0 — определить по округу из таблицы 3 постановления № 1745
    average_flat_sqm: float = 0.0   # 0 — РНГП области, `average_flat_sqm('mo')`
    norms: dict[str, Any] = {}
    limit: int = 30


@app.get("/mo/reference")
def mo_reference() -> dict[str, Any]:
    """Справочные данные калькулятора Подмосковья для интерфейса."""
    districts = []
    for name in sorted(_MO_UPKS_BY_DISTRICT):
        land, mkd, parking, commercial = _MO_UPKS_BY_DISTRICT[name]
        # Кср по округу отдаём вместе со справочником: интерфейс должен
        # показать цену сразу при выборе округа, не дожидаясь расчёта.
        price, _period, _document, basis = _mo_market_price_for(name)
        kd, kd_document, kd_basis = _mo_vri_kd_for(name)
        districts.append({
            "name": name,
            "vri_kd": kd,
            "vri_kd_basis": kd_basis,
            "upks_land_residential": land,
            "upks_oks_mkd": mkd,
            "upks_oks_parking": parking,
            "upks_oks_commercial": commercial,
            "market_price_rub_per_sqm": price,
            "market_price_basis": basis,
        })
    kd_table = _mo_vri_kd_table()
    return {
        "region": "Московская область",
        "density_default_sqm_per_ha": _MO_DENSITY_DEFAULT_SQM_PER_HA,
        "districts": districts,
        "vri_kd": {
            "count": len(kd_table["values"]),
            "document": kd_table["document"],
        },
        "norms": MO_NORMS_DEFAULT,
        "quarter_upks_loaded": len(_mo_quarter_upks_table()),
        "upks_source": _MO_UPKS_SOURCE,
        "market_price": {
            "count": len([key for key in _mo_market_price_table()["prices"] if key != _MO_MARKET_PRICE_REGION_KEY]),
            "region_average": _mo_market_price_table()["prices"].get(_MO_MARKET_PRICE_REGION_KEY),
            "period": _mo_market_price_table().get("period", ""),
            "document": _mo_market_price_table().get("document", ""),
        },
    }


# Расчёт Подмосковья тянет сведения ЕГРН из НСПД, а туда пускают не отовсюду:
# на Render запросы к nspd.gov.ru не проходят. Поэтому бот на Render считает не
# сам, а обращается к ядру, развёрнутому там, где НСПД доступен. Пустое
# значение означает «считать на месте» — так работает само ядро, иначе оно
# вызывало бы само себя.
_MO_CALC_API_URL = _env_str("MO_CALC_API_URL", "").strip()
# Двадцать два участка — это двадцать два обращения к ЕГРН, минуты работы.
_MO_CALC_TIMEOUT_SECONDS = max(30.0, _env_float("MO_CALC_TIMEOUT_SECONDS", 180.0))


def _core_api_url(path: str) -> str:
    """Адрес метода ядра. Базу берём из MO_CALC_API_URL, чтобы не плодить переменные."""
    base = _env_str("CORE_API_URL", "").strip().rstrip("/")
    if not base and _MO_CALC_API_URL:
        base = _MO_CALC_API_URL.rstrip("/")
        if base.endswith("/mo/calculate"):
            base = base[: -len("/mo/calculate")]
    return f"{base}{path}" if base else ""


def _core_post(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    """Запрос к ядру. Тихого отката на локальный расчёт нет.

    Локальный расчёт на Render дал бы пустой ЕГРН и молча неверные ТЭП, что
    хуже честной ошибки: пользователь бы не узнал, что цифры не с НСПД.
    """
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = str((json.loads(exc.read().decode("utf-8")) or {}).get("detail") or "")
        except Exception:
            detail = ""
        raise HTTPException(
            status_code=502,
            detail=detail or f"Ядро расчёта ответило ошибкой {exc.code}.",
        ) from exc
    except socket.timeout as exc:
        raise HTTPException(
            status_code=504,
            detail=(
                f"Ядро расчёта не ответило за {int(timeout)} с. "
                "Сведения ЕГРН по большому списку участков собираются долго — попробуйте ещё раз."
            ),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Не удалось обратиться к ядру расчёта: {exc}",
        ) from exc


def _core_forward_payload(req: BaseModel) -> dict[str, Any]:
    """Тело запроса целиком, как его прислал браузер или собрал бот."""
    dump = getattr(req, "model_dump", None) or getattr(req, "dict")
    return dump()


def _mo_calculate_remote(query: str, limit: int) -> dict[str, Any]:
    return _core_post(
        _MO_CALC_API_URL, {"query": query, "limit": int(limit)}, _MO_CALC_TIMEOUT_SECONDS
    )


def mo_calculate_via_core(query: str, limit: int = 30) -> dict[str, Any]:
    """Единая точка входа бота. Пересылку наружу решает сам эндпоинт."""
    return mo_calculate(MoCalculateRequest(query=query, limit=limit))


def land_lookup_via_core(query: str, limit: int = 30) -> dict[str, Any]:
    """Поиск участка по адресу, номеру или координатам. Пересылку решает эндпоинт."""
    return land_lookup(LandLookupRequest(query=query, limit=limit))


@app.post("/mo/calculate")
def mo_calculate(req: MoCalculateRequest) -> dict[str, Any]:
    """ТЭП, социальная нагрузка и плата за смену ВРИ для участка в Подмосковье."""
    # Пересылаем целиком: кроме запроса пользователь мог задать площадь, округ,
    # плотность, Кср и Кд вручную — потерять их означало бы посчитать не то.
    if _MO_CALC_API_URL:
        return _core_post(_MO_CALC_API_URL, _core_forward_payload(req), _MO_CALC_TIMEOUT_SECONDS)
    warnings: list[str] = []
    parcels: list[dict[str, Any]] = []
    query = _land_text(req.query)
    limit = max(1, min(int(req.limit or 10), _LAND_LOOKUP_MAX_RESULTS))
    if query:
        parcels, lookup_warnings = _mo_parcels_from_query(query, limit)
        warnings.extend(lookup_warnings)

    area_from_parcels = sum(_land_float(item.get("area_sqm")) or 0.0 for item in parcels) / 10000.0
    site_area_ha = _land_float(req.site_area_ha) or 0.0
    if area_from_parcels > 0:
        if site_area_ha > 0 and abs(site_area_ha - area_from_parcels) > 0.0001:
            warnings.append(
                f"Площадь по ЕГРН {area_from_parcels:.4f} га отличается от введённой вручную "
                f"{site_area_ha:.4f} га — в расчёт взята площадь ЕГРН."
            )
        site_area_ha = area_from_parcels
    if site_area_ha <= 0:
        if query:
            reason = " ".join(str(item) for item in warnings if "недоступен" in str(item) or "не найден" in str(item))
            raise HTTPException(
                status_code=400,
                detail=(
                    "Не удалось получить площадь участка из ЕГРН. "
                    + (reason + " " if reason else "")
                    + "Проверьте кадастровый номер или задайте площадь участка в гектарах вручную."
                ),
            )
        raise HTTPException(
            status_code=400,
            detail="Не определена площадь участка: введите кадастровый номер, адрес или площадь в гектарах.",
        )

    density = _land_float(req.density_sqm_per_ha)
    if density is None or density <= 0:
        density = _MO_DENSITY_DEFAULT_SQM_PER_HA
    apartments_sqm = site_area_ha * density

    norms = _mo_norms(req.norms if isinstance(req.norms, dict) else None)
    social = mo_social_program(apartments_sqm, norms)
    # Дефицит рабочих мест доносится наравне с прочими обязательствами: он
    # означает будущий объект — офис или торговлю, — а объект стоит денег и
    # места на площадке. В таблицах он был строкой справки и читался как
    # «к сведению» (замечание владельца, 19.08.2026).
    jobs_gap = float((social.get("jobs") or {}).get("deficit") or 0)
    if jobs_gap > 0:
        gap_office = float((social.get("jobs") or {}).get("office_sqm") or 0)
        gap_retail = float((social.get("jobs") or {}).get("retail_sqm") or 0)
        spaced = lambda value: f"{value:,.0f}".replace(",", "\u00a0")
        warnings.append(
            f"РНГП МО требует {spaced(_mo_ceil(jobs_gap))} рабочих мест сверх тех, что дают "
            f"нормативные соцобъекты и торговля. Их создаёт отдельный объект: офисы около "
            f"{spaced(gap_office)} м² ГНС либо торговля около {spaced(gap_retail)} м². "
            f"В ТЭП он не включён — включите его во вводных, если берёте на себя."
        )

    district = _land_text(req.district)
    district_source = "запрос" if district else ""
    if not district:
        for parcel in parcels:
            district = _mo_district_from_address(str(parcel.get("address") or ""))
            if district:
                district_source = "адрес ЕГРН"
                break
    upks = _mo_district_upks(district)
    if district and not upks["district"]:
        warnings.append(f"Округ «{district}» не найден в справочнике УПКС.")
    elif not district:
        warnings.append("Округ не определён по адресу — выберите его вручную, иначе плата за ВРИ не считается.")

    quarter = ""
    quarter_upks = None
    for parcel in parcels:
        quarter = str(parcel.get("quarter") or "")
        if quarter:
            row = _mo_quarter_upks_table().get(quarter)
            quarter_upks = row[0] if row else None
            break

    market_price = _land_float(req.market_price_rub_per_sqm) or 0.0
    market_price_source = "запрос"
    market_price_period = ""
    market_price_document = ""
    if market_price <= 0:
        # Официальный ориентир: распоряжение Комитета по ценам и тарифам МО.
        official, market_price_period, market_price_document, level = _mo_market_price_for(
            upks["district"] or district
        )
        if official:
            market_price = official
            market_price_source = "распоряжение Комитета по ценам и тарифам МО"
            if level == "среднее по области":
                market_price_source += " · среднее по области"
                warnings.append(
                    "Для этого округа в распоряжении нет отдельной строки — взято среднее значение "
                    "по Московской области. Если знаете цену по округу, укажите её вручную."
                )
            else:
                warnings.append(
                    "Кср взят из распоряжения о средней рыночной стоимости 1 м² жилья"
                    + (f" ({market_price_period})" if market_price_period else "")
                    + ". Это официальный ориентир, а не цена конкретной сделки."
                )
    if market_price <= 0:
        market_price = upks["upks_oks_mkd"] or 0.0
        market_price_source = "УПКС ОКС округа"
        if market_price:
            warnings.append(
                "Средняя цена м² (Кср) не задана и не найдена в справочнике — взят УПКС ОКС "
                "многоквартирных домов округа, то есть К1 = 1,00. Загрузите таблицу распоряжения "
                "Комитета по ценам и тарифам МО или укажите цену вручную."
            )
    # Кд берём из таблицы 3 постановления № 1745 по округу. Явно заданное
    # значение важнее справочного; если округа в таблице нет — не подставляем
    # чужую группу и плату не считаем: у запаса 0,1 источника не было, а Кд
    # умножает плату на миллиарды (решение владельца 16.10.2026). Причина
    # называется в предупреждении, поля платы остаются пустыми, не нулём.
    kd: float | None = _land_float(req.vri_kd) or None
    kd_document = ""
    kd_basis = "задан вручную"
    kd_missing_reason = ""
    if kd is None or kd <= 0:
        kd, kd_document, kd_basis = _mo_vri_kd_for(district)
        if kd is None:
            kd_missing_reason = (
                (
                    f"Кд не установлен: округ «{district}» отсутствует в таблице 3 к 1745-ПП; "
                    if district else
                    "Кд не установлен: округ участка не определён, по таблице 3 к 1745-ПП его не подобрать; "
                )
                + "впишите коэффициент доходности вручную (vri_kd)."
            )
    vri = mo_vri_payment(
        parcels,
        upks_target=upks["upks_land_residential"],
        upks_average_oks=upks["upks_oks_mkd"],
        upks_quarter_oks=quarter_upks,
        apartments_sqm=apartments_sqm,
        market_price_rub_per_sqm=market_price,
        kd=kd,
        kd_missing_reason=kd_missing_reason,
    )
    vri["kd_basis"] = kd_basis
    vri["kd_document"] = kd_document
    vri["market_price_source"] = market_price_source
    vri["market_price_period"] = market_price_period
    vri["market_price_document"] = market_price_document
    warnings.extend(vri.get("warnings") or [])

    # Ноль в запросе — «не задано», и тогда делитель берётся у РНГП области,
    # а не у числа без источника: 58,75 стояло здесь копией неизвестно чего.
    average_flat = _land_float(req.average_flat_sqm) or average_flat_sqm('mo')[0]
    tep, inputs_patch = _mo_tep_and_inputs(
        social, vri, site_area_ha=site_area_ha, norms=norms, average_flat_sqm=average_flat
    )
    # Плата во вводные уходит только когда она рассчитана: без Кд (или без Кср)
    # ключа нет вовсе, и страница не затирает ранее вписанную сумму нулём.
    if vri.get("payment_used_mln") is not None:
        inputs_patch["land_rights_cost_mln"] = vri["payment_used_mln"]
    balance = _mo_territory_balance(social, site_area_ha, norms)
    if balance["remaining_ha"] < 0:
        warnings.append(
            "Нормативная социальная инфраструктура не помещается на участок при заданной плотности — "
            "уменьшите плотность или предусмотрите смежные участки."
        )
    warnings.append(
        "Расчёт нормативный и предварительный: он не заменяет ППТ, заключение ГлавАрхитектуры "
        "и соглашение о социальной нагрузке."
    )

    return {
        "region": "Московская область",
        "query": query,
        "territory": {
            "site_area_ha": round(site_area_ha, 4),
            "site_area_sqm": round(site_area_ha * 10000.0, 2),
            "parcel_count": len(parcels),
            "cadastral_numbers": [str(item.get("cadastral_number") or "") for item in parcels],
            "district": upks["district"] or district,
            "district_source": district_source,
            "quarter": quarter,
            "address": str((parcels[0].get("address") if parcels else "") or ""),
        },
        "density_sqm_per_ha": round(density, 2),
        "upks": {
            **upks,
            "upks_oks_mkd_quarter": quarter_upks,
            "source": _MO_UPKS_SOURCE,
        },
        "social": social,
        "vri": vri,
        "balance": balance,
        "tep": tep,
        "inputs": inputs_patch,
        "warnings": warnings,
        "source": {
            "service": "ЕГРН/НСПД + нормативы РНГП Московской области",
            "calculated_at": date.today().isoformat(),
        },
    }

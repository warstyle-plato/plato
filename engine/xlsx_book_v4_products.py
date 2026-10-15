"""Состав продуктов книги v4: МКД и отдельно стоящие объекты, общий пул
расходов, разделы и подземные строки ТЭП, меры счёта продуктов.

Кусок книги v4: файлы `engine/xlsx_book_v4*.py` выполняются подряд на
месте прежнего `_engine_part("xlsx_book_v4")`. Не самостоятельный модуль:
`main_legacy.py` выполняет этот файл в своём пространстве имён
(`_engine_part("xlsx_book_v4_products")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

# Статьи, за которыми идёт «Управление проектом»: своего окна у него нет —
# штаб загружен тем, чем вызван, и его доля месяца равна доле этих расходов.
# Список объявлен здесь и больше нигде: движок разносит по нему статью, книга
# v2 собирает по нему формулу, а книга v4 приводится к нему при выгрузке.
# Копия в шаблоне v4 включала «Сдачу и ввод» — статью последних трёх месяцев,
# — и книга смещала управление к сдаче: помесячный CAPEX расходился с движком
# на сотую долю процента. Само по себе это ничего не стоило, пока покрытие
# эскроу не легло на ступень ставки ПФ: 1,10002× в книге против 1,09993× у
# движка — и один месяц пошёл по 3,47% вместо 1,75%, а стоимость
# финансирования разошлась на 28,9 млн ₽ при совпадающих выручке, CAPEX,
# EBITDA и пике долга.
# Что входит в многоквартирный дом, а что стоит отдельным объектом (решение
# владельца, 23.08.2026: жильё, коммерция, машино-места и кладовки — это МКД).
# Подземный паркинг и кладовые продаются своими продуктами, но строятся тем же
# домом, и в промежуточном итоге стоят с ним. Список объявлен один раз: копия
# на странице разошлась бы с этой молча.
MKD_PRODUCTS: tuple[str, ...] = (
    "apartments", "ground_commercial", "underground_parking", "storage",
)
# Состав объявлен один раз — в STANDALONE_OBJECTS; здесь только его ключи.
STANDALONE_PRODUCTS: tuple[str, ...] = tuple(o.key for o in STANDALONE_OBJECTS)

# Продукты, делящие ОДИН остаточный пул расходов: у них нет своей статьи CAPEX,
# и себестоимость признаётся долей проданного количества. У отдельно стоящего
# объекта пул свой (его CAPEX — отдельная статья), а вот его паркинг своей
# статьи не имеет: места строятся тем же подземным метром, и деньги за них
# лежат в общем пуле. Отсюда и место в этом списке — не «он часть МКД»
# (`MKD_PRODUCTS` отвечает на другой вопрос: чем он построен), а «его расход
# признаётся из остатка».
#
# Списка было два, одинаковых с виду: налоговая база и разбивка расходов по
# продуктам в отчёте. Оба перечисляли четыре продукта МКД руками, а
# `object_parking` завели позже (06.09.2026, «продаётся то, что можно
# поставить на кадастр»), и он не попал ни в один. Выручка от него собиралась,
# налога с неё не брали вовсе: на пресете Нагатино это 5 366,6 млн ₽ выручки
# мимо базы, 395,6 млн налога и 556,3 млн чистой прибыли — а на проекте
# владельца от 13.09.2026 уже 5 138,8 млн налога и 6 101,4 млн прибыли.
# Книга при этом считала верно, и её же блок паритета об этом кричал.
#
# Третьим списком был НДС, и его закрыли отдельно и лучше: облагаемые продукты
# берутся из самих расписаний выручки (`vat_taxable_products`), то есть перечня
# там больше нет вовсе. Здесь так нельзя — пул отвечает не на «кто продаётся»,
# а на «чей расход признаётся из остатка», и у объекта со своей статьёй CAPEX
# ответ обратный.
#
# С 27.09.2026 паркинга объектов в этом пуле нет (владелец: «весь гараж и
# подземный и наземный должен иметь отношение в затратах и выручке только
# своего объекта, но никак не МКД. И это правило для всех объектов»). Его
# расход — в статье его объекта (гараж и метры под местами первых этажей) и
# признаётся вместе с ней; так же и в книге. В пуле дома он забирал долю
# стройки МКД и разбавлял признание квартир своими штуками.
COST_POOL_PRODUCTS: tuple[str, ...] = MKD_PRODUCTS

# Разделы таблицы ТЭП. Двенадцать строк одним списком читаются как двенадцать
# равных продуктов, а это три разные вещи: дом, который мы строим и продаём;
# отдельно стоящие объекты со своей экономикой; и объекты, которые уходят
# городу. Списки уже объявлены выше — здесь только их порядок и имена разделов,
# а третий раздел ОСТАТОЧНЫЙ: продукт, добавленный позже и не попавший ни в
# один список, обязан остаться в таблице, а не исчезнуть из неё молча.
TEP_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Многоквартирный дом", MKD_PRODUCTS),
    ("Отдельно стоящие объекты", STANDALONE_PRODUCTS),
    ("Социальные объекты", ()),
)

# Где стоят кладовые — решение проекта, а не свойство продукта (владелец,
# 15.10.2026): у «Донского» они на первом этаже, и подземными их считать
# значило строить 103 м² по ставке гаража и вынимать их из наземной части.
# Поле одно; отсутствующий ключ — умолчание «в подземной части», а не
# «наземные»: сохранённые проекты и эталоны от появления поля не сдвигаются.
STORAGE_PLACEMENT_FIELD = "storage_placement"
STORAGE_UNDERGROUND = "underground"
STORAGE_ABOVE = "above"
STORAGE_PLACEMENT_DEFAULT = STORAGE_UNDERGROUND
STORAGE_PLACEMENT_OPTIONS: tuple[tuple[str, str], ...] = (
    (STORAGE_UNDERGROUND, "В подземной части"),
    (STORAGE_ABOVE, "На наземных этажах"),
)

# Строки ТЭП, чьи метры лежат под землёй, — по размещению кладовых. Гараж
# подземный всегда; кладовые — когда так решил проект. Ответ один на все
# поверхности: движок, страница (плейсхолдером), PDF, тизер и книга берут его
# у `underground_products`, а не у своей копии списка.
UNDERGROUND_PRODUCTS_BY_PLACEMENT: dict[str, tuple[str, ...]] = {
    STORAGE_UNDERGROUND: ("underground_parking", "storage"),
    STORAGE_ABOVE: ("underground_parking",),
}

# Строки, чьи метры к наземной ГНС проекта НЕ прибавляются. Это другой вопрос,
# чем «что под землёй»: наземные кладовые стоят внутри наземной ГНС здания —
# их вырезают из площади квартир, как коммерцию, а не добавляют сверху
# (владелец, 15.10.2026). Поэтому кладовые здесь при любом размещении.
ROWS_OUTSIDE_ABOVE_SUM: tuple[str, ...] = ("underground_parking", "storage")


def storage_above_ground(inputs: dict[str, Any] | None) -> bool:
    """Кладовые на наземных этажах — только явным выбором проекта."""
    value = (inputs or {}).get(STORAGE_PLACEMENT_FIELD)
    return str(value or "").strip() == STORAGE_ABOVE


def underground_products(inputs: dict[str, Any] | None) -> tuple[str, ...]:
    """Строки ТЭП под землёй — у ЭТОГО проекта."""
    return UNDERGROUND_PRODUCTS_BY_PLACEMENT[
        STORAGE_ABOVE if storage_above_ground(inputs) else STORAGE_UNDERGROUND]


def underground_placement_payload() -> dict[str, Any]:
    """Правило «что под землёй» для страницы — плейсхолдером, не копией."""
    return {"field": STORAGE_PLACEMENT_FIELD, "default": STORAGE_PLACEMENT_DEFAULT,
            "by_placement": {key: list(value)
                             for key, value in UNDERGROUND_PRODUCTS_BY_PLACEMENT.items()},
            "outside_above": list(ROWS_OUTSIDE_ABOVE_SUM)}


def project_above_gns(tep: dict[str, Any]) -> float:
    """Наземная ГНС проекта — та самая, что стоит в сводке под именем ГНС.

    Объявлена один раз: её читают и сводка, и удельные, и статья
    благоустройства. Второй счёт той же величины разошёлся бы с первым, и оба
    числа выглядели бы верными. От размещения кладовых она не зависит:
    подземные в неё не входят, наземные уже лежат в метрах квартир.
    """
    object_under = sum(n(row, "under_gns") for row in tep.values())
    outside = (sum(n(tep.get(key) or {}, "gns") for key in ROWS_OUTSIDE_ABOVE_SUM)
               + object_under)
    volume = sum(n(row, "gns") for row in tep.values()) + object_under
    return max(0.0, volume - outside)


def mkd_part_gns(inputs: dict[str, Any], tep: dict[str, Any]) -> dict[str, dict[str, float]]:
    """ГНС продуктов МКД по частям здания: наземной и подземной.

    Сумма наземной части — ГНС квартир и коммерции (`core_above_gns`), и
    наземные кладовые в ней ВЫРЕЗАНЫ из квартир; сумма подземной —
    `core_under_gns`. По этим метрам прямые затраты части (её СМР с
    надбавками) делятся между продуктами этой части.
    """
    def gns(key: str) -> float:
        return n(tep.get(key) or {}, "gns")

    flats, storage = gns("apartments"), gns("storage")
    if storage_above_ground(inputs):
        inside = min(storage, flats)
        return {"above": {"apartments": flats - inside,
                          "ground_commercial": gns("ground_commercial"),
                          "storage": inside},
                "under": {"underground_parking": gns("underground_parking")}}
    return {"above": {"apartments": flats, "ground_commercial": gns("ground_commercial")},
            "under": {"underground_parking": gns("underground_parking"), "storage": storage}}


PRODUCT_COST_BASIS = (
    "Себестоимость продуктов дома: прямые затраты — СМР своей части здания "
    "(наземной или подземной) с генподрядом, техзаказчиком, управлением и "
    "резервом — по ГНС продукта; общие затраты проекта — по выручке продукта.")


def cost_pool_product_costs(pool: float, direct: dict[str, float],
                            part_gns: dict[str, dict[str, float]],
                            revenue: dict[str, float]) -> dict[str, float]:
    """Себестоимость продуктов общего пула МКД: прямые по месту + общие по выручке.

    Решение владельца 15.10.2026. Пул делился долей проданного количества, а
    в одной сумме стояли метры квартир и ШТУКИ паркинга: 26 мест «Донского»
    против 3 562 м² несли 0,03 млрд ₽ при марже 94,6 %.

    · Прямые — СМР части здания с её надбавками (генподряд, техзаказчик,
      управление проектом и резерв в доле, начисленной на это СМР;
      `op["mkd_direct_costs"]`) — продуктам этой части по их ГНС.
    · Общие — всё остальное в пуле (покупка, ВРИ, ИРД, проект, сети,
      благоустройство, подготовка, сдача, содержание площадки, соцнагрузка,
      надбавки на них; в налоговой базе ещё и коммерческие расходы) — по
      выручке продуктов пула; без выручки — по их ГНС.
    Прямые больше пула не бывают: при пуле меньше их суммы они сжимаются до
    пула. Остаток, который делить не по чему, не раздаётся — налоговая база
    признаёт его в РВЭ. Книга считает тем же методом (`CF_x`, блок
    «Себестоимость продуктов пула МКД»).
    """
    costs = {key: 0.0 for key in COST_POOL_PRODUCTS}
    parts = ("above", "under")
    raw = sum(float(direct.get(part) or 0.0) for part in parts)
    scale = min(1.0, pool / raw) if raw > 0 and pool > 0 else 0.0
    for part in parts:
        metres = part_gns.get(part) or {}
        total = sum(metres.values())
        if total <= 0:
            continue
        for key, value in metres.items():
            costs[key] += float(direct.get(part) or 0.0) * scale * value / total
    common = pool - sum(costs.values())
    weights = {key: max(0.0, float(revenue.get(key) or 0.0)) for key in COST_POOL_PRODUCTS}
    if sum(weights.values()) <= 0:
        weights = {key: sum((part_gns.get(part) or {}).get(key, 0.0) for part in parts)
                   for key in COST_POOL_PRODUCTS}
    total_weight = sum(weights.values())
    if total_weight > 0:
        for key in COST_POOL_PRODUCTS:
            costs[key] += common * weights[key] / total_weight
    return costs


# Чем СЧИТАЕТСЯ продукт. Квартира, машино-место, место в детском саду и
# посещение поликлиники в смену — четыре разные величины, и сумма у них не
# значит ничего: «конечно это не надо суммировать» (владелец, 27.09.2026).
#
# Пока меры не было, свод складывал все штуки подряд — 2 811 на умолчаниях, —
# и это число не только печаталось итогом на странице, в книге, в отчёте и в
# тизере. Его ДЕЛИЛИ: обеспеченность парковкой считалась от него и выходила
# 28,98 вместо 12,36, а строка тизера «Машино-места» печатала 2 811 м/м при
# 1 199 настоящих. Документ для банка утверждал число, которого в проекте нет.
#
# Объявлено ОДИН раз и читается всеми поверхностями. Продукт без меры —
# ошибка объявления, а не «штуки по умолчанию»: проверка требует меру у
# каждой строки ТЭП, поэтому новый продукт заставляет решить, в чём он.
# Сами слова объявлены в `presentation` — модуле ниже всех, кто их печатает.
# Вторая их копия здесь разошлась бы с книгой и тизером молча.
COUNT_FLATS = _presentation.FLATS_MEASURE
COUNT_PARKING = _presentation.PARKING_MEASURE
COUNT_PLACES = _presentation.PLACES_MEASURE
COUNT_VISITS = _presentation.VISITS_MEASURE
COUNT_PIECES = _presentation.PIECES_MEASURE
# Метровый продукт штуками не считается вовсе — у него нет меры счёта, и это
# не пробел: «сколько штук у офисного центра» вопрос без смысла.
COUNT_BY_AREA = _presentation.AREA_MEASURE

HOTEL_TEP_KEY = "hotel"
TEP_COUNT_MEASURE: dict[str, str] = {
    "apartments": COUNT_FLATS,
    # Гостиница меряется метрами здания; номера — не «штуки» свода, их
    # делитель — показатели «на номер» в блоке гостиницы.
    HOTEL_TEP_KEY: COUNT_BY_AREA,
    "ground_commercial": COUNT_BY_AREA,
    "offices": COUNT_BY_AREA,
    "standalone_retail": COUNT_BY_AREA,
    "sports": COUNT_BY_AREA,
    "underground_parking": COUNT_PARKING,
    "above_parking": COUNT_PARKING,
    "storage": COUNT_PIECES,
    "kindergarten": COUNT_PLACES,
    "school": COUNT_PLACES,
    "clinic": COUNT_VISITS,
    "other_mandatory": COUNT_PIECES,
}
# Второй объект того же рода считается как его продукт: второй офисник —
# метрами, второй наземный паркинг — машино-местами. Из реестра, чтобы
# следующий объект не ушёл в «шт.» последнего прибежища.
for _obj in STANDALONE_OBJECTS:
    TEP_COUNT_MEASURE.setdefault(_obj.key, TEP_COUNT_MEASURE[_obj.product])


def tep_count_measure(key: str) -> str:
    """Мера счёта строки ТЭП. Незнакомый продукт — «шт.» и жалоба проверке.

    Возврат «шт.» здесь не умолчание, а последнее прибежище: складывать
    незнакомое с известным нельзя, но и терять его в своде тоже нельзя.
    Настоящее место решения — `TEP_COUNT_MEASURE`, и проверка следит, чтобы
    новый продукт туда попал.
    """
    return TEP_COUNT_MEASURE.get(str(key or ""), COUNT_PIECES)


def tep_units_by_measure(rows: "list[dict[str, Any]]", field: str = "units",
                         garage_field: str = "parking_units") -> dict[str, float]:
    """Штуки свода, разложенные по мере счёта.

    Ответ на «сколько всего единиц» — не число, а разбор: 1 362 квартиры,
    1 199 машино-мест, 250 мест ДОО. Складывать их в 2 811 нельзя, а потерять
    нельзя тем более.

    Гараж объекта (`parking_units`) — тоже машино-места, и он попадает в ту же
    меру: иначе «сколько машино-мест в проекте» отвечалось бы без гаража
    офисника, который в проекте есть.
    """
    out: dict[str, float] = {}
    for row in rows:
        value = n(row, field)
        if value:
            measure = tep_count_measure(row.get("key"))
            if measure:
                out[measure] = out.get(measure, 0.0) + value
        garage = n(row, garage_field) if garage_field else 0.0
        if garage:
            out[COUNT_PARKING] = out.get(COUNT_PARKING, 0.0) + garage
    return out


def tep_parking_spaces(rows: "list[dict[str, Any]]", field: str = "units",
                       garage_field: str = "parking_units") -> float:
    """Машино-места проекта — и подземные, и наземные, и гаражи объектов.

    Отдельной функцией, потому что спрашивают именно её: обеспеченность,
    строка тизера и книга. Чтение меры из общего разбора — чтобы «что считать
    машино-местом» отвечалось один раз.
    """
    return tep_units_by_measure(rows, field, garage_field).get(COUNT_PARKING, 0.0)


# Поля свода ТЭП, которые СКЛАДЫВАЮТСЯ построчно. Список объявлен один раз:
# две его копии стояли в одиночном и очередном расчёте и однажды разошлись бы.
# Штук здесь нет намеренно — они группируются мерой, а не складываются.
TEP_SUMMABLE_FIELDS: tuple[str, ...] = (
    "gns", "total_area", "useful", "saleable", "transfer",
    "guest_units", "transfer_units", "under_gns",
    "parking_units", "parking_saleable_units",
    "parking_under_units", "parking_over_units", "parking_guest_units",
)

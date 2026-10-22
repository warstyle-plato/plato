"""Сборка страницы PAGE и её отдача.

Подстановка версии и данных движка в плейсхолдеры страницы (группы и разделы
вводных, классы, ТЭП, объекты, легенды, анкета), страница монитора
MONITOR_PAGE_HTML, помощник _js_keys и маршрут GET /.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён на том месте, где этот код стоял раньше
(`_engine_part("page_build")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

# Подстановка разовая, на импорте: страница отдаётся на каждый запрос, а версия
# за время работы процесса не меняется.
PAGE = PAGE.replace(VERSION_PLACEHOLDER, VERSION)
# Контур подставляется, как версия и подвал: копию негде обновлять, а
# поверхность без входа в контур не найти (владелец, 29.08.2026 — «кабинет
# надо объединить и сделать внутренним управленческим контуром»).
MONITOR_PAGE_HTML = (
    _MONITOR_PAGE_RAW.replace("__VERSION__", VERSION)
    .replace("__DEVELOPAID_CONTOUR_STYLE__", management_contour.STYLE)
    .replace(management_contour.PLACEHOLDER, management_contour.markup("/monitor"))
    # Разговор с Платоном объявлен один раз (plato_question). Монитор —
    # четвёртая поверхность, где его спрашивают, и своей памяти у неё быть
    # не должно: «Платон должен везде уметь вести диалог, а не один ответ».
    .replace(plato_question.PLACEHOLDER, plato_question.SCRIPT)
)
# Сводка руководству — своя страница рядом с Монитором (владелец, 20.10.2026:
# «отдельной страницей, не смешивая со стройкой»), контур тот же.
REPORT_PAGE_HTML = (
    _REPORT_PAGE_RAW.replace("__VERSION__", VERSION)
    .replace("__DEVELOPAID_CONTOUR_STYLE__", management_contour.STYLE)
    .replace(management_contour.PLACEHOLDER, management_contour.markup("/report"))
)
# Странице — группы ТИПОВ: экземпляр рисуется вкладкой внутри блока своего
# типа, и его поля страница выводит из полей типа (`objectFields`). Число групп
# вводных от числа объектов не растёт (владелец, 28.09.2026).
PAGE = PAGE.replace(FIELD_GROUPS_PLACEHOLDER,
                    json.dumps(PAGE_FIELD_GROUPS, ensure_ascii=False))
PAGE = PAGE.replace("__DEVELOPAID_STRATEGY_FIELD_READERS__", json.dumps(
    strategy_field_readers(), ensure_ascii=False))
PAGE = PAGE.replace("__DEVELOPAID_STRATEGY_VALUES__", json.dumps(
    [value for value, _ in nonres_strategy.STRATEGIES]))
PAGE = PAGE.replace(FIELD_SECTIONS_PLACEHOLDER, json.dumps(
    {key: title for key, title in FIELD_SECTIONS.items() if key not in _INSTANCE_FIELDS},
    ensure_ascii=False))
# Подписи полей объектов вне их группы — тем же правилом, что в PDF и отчётах.
PAGE = PAGE.replace("__DEVELOPAID_FIELD_LABELS_OUTSIDE__", json.dumps(
    {key: _input_field_label(key) for key in FIELD_SECTIONS}, ensure_ascii=False))
# Базы классов — из движка. Копия жила на странице с рождения окна и отстала
# от пресета в первый же раз, когда профиль класса расширили статьями:
# полный профиль применялся бы на сервере и молча не существовал бы в браузере.
PAGE = PAGE.replace("__DEVELOPAID_CLASS_PRESETS__",
                    json.dumps(PROJECT_CLASS_PRESETS, ensure_ascii=False))
PAGE = PAGE.replace(OFFICE_CLASS_PLACEHOLDER,
                    json.dumps(OFFICE_CLASS_BY_PROJECT_CLASS, ensure_ascii=False))
PAGE = PAGE.replace(CLASS_FIELD_UNITS_PLACEHOLDER,
                    json.dumps(class_field_units(), ensure_ascii=False))
PAGE = PAGE.replace(FIELD_UNITS_PLACEHOLDER,
                    json.dumps(field_units(), ensure_ascii=False))
PAGE = PAGE.replace(CLASS_DIALOG_PLACEHOLDER,
                    json.dumps(class_dialog_layout(), ensure_ascii=False))
PAGE = PAGE.replace(INPUT_DEFAULT_PLACEHOLDER,
                    json.dumps(DEFAULT_INPUTS, ensure_ascii=False))
PAGE = PAGE.replace(CLASS_ONLY_INPUTS_PLACEHOLDER,
                    json.dumps(CLASS_ONLY_INPUTS, ensure_ascii=False))
PAGE = PAGE.replace(SITE_ONLY_INPUTS_PLACEHOLDER,
                    json.dumps(SITE_ONLY_INPUTS, ensure_ascii=False))
PAGE = PAGE.replace(TEP_ONLY_INPUTS_PLACEHOLDER,
                    json.dumps(TEP_ONLY_INPUTS, ensure_ascii=False))
PAGE = PAGE.replace("__DEVELOPAID_RESIDENTIAL_ONLY_INPUTS__",
                    json.dumps(RESIDENTIAL_ONLY_INPUTS, ensure_ascii=False))
# Имя группы ВРИ жило на странице второй копией: вкладка ВРИ узнаёт свою группу
# по нему, и ответ «где это править» — тоже. Разойдись копии, и поле ВРИ ушло бы
# рисоваться во «Вводные», а Платон продолжал бы звать на вкладку ВРИ.
PAGE = PAGE.replace(VRI_GROUP_NAME_PLACEHOLDER,
                    json.dumps(VRI_GROUP_NAME, ensure_ascii=False))
PAGE = PAGE.replace(TEP_DEFAULT_PLACEHOLDER,
                    json.dumps(TEP_DEFAULT, ensure_ascii=False))
PAGE = PAGE.replace(TEP_RATIOS_PLACEHOLDER, json.dumps(TEP_RATIOS, ensure_ascii=False))
PAGE = PAGE.replace(MKD_SPP_SPLIT_PLACEHOLDER, json.dumps(MKD_SPP_SPLIT, ensure_ascii=False))
# Строка о регистрации программы — из `docs/legal/product.json`, одного
# источника реквизитов (`product_registration_line`).
PAGE = PAGE.replace("__DEVELOPAID_PRODUCT_REGISTRATION__", html.escape(product_registration_line()))
PAGE = PAGE.replace("__DEVELOPAID_TERMS__", json.dumps(page_terms(), ensure_ascii=False))
PAGE = PAGE.replace("__DEVELOPAID_DEFAULT_REPAYMENT__",
                    json.dumps(DEFAULT_REPAYMENT_WORDS, ensure_ascii=False))
# Слово глоссария в разметке — `__DEVELOPAID_TERM_<ключ>_<падеж>__`: подпись до
# первого расчёта та же, что скрипт подставит из TERMS после него, и литерала
# в разметке нет.
for _term_key, _term_words in page_terms().items():
    for _case, _word in _term_words.items():
        PAGE = PAGE.replace(f"__DEVELOPAID_TERM_{_term_key}_{_case}__", _word)
PAGE = PAGE.replace(PRODUCT_LABELS_PLACEHOLDER,
                    json.dumps(product_labels(), ensure_ascii=False))
PAGE = PAGE.replace(
    TEP_ROW_INPUTS_PLACEHOLDER,
    json.dumps({obj.key: tep_row_inputs(obj.key)
                for obj in standalone_objects() if obj.measure == "sqm"},
               ensure_ascii=False))
PAGE = PAGE.replace(
    SOCIAL_AREA_STEPS_PLACEHOLDER,
    json.dumps({kind: [[None if limit == float("inf") else limit, value]
                       for limit, value in steps]
                for kind, steps in MOSCOW_SOCIAL_AREA_PER_PLACE.items()},
               ensure_ascii=False))
# Имена статей расходов — из движка. Статья без короткой подписи получает
# полную: сырой ключ на экране невозможен по построению, а не по вниманию.
PAGE = PAGE.replace("__DEVELOPAID_PROJECT_REGIONS__", json.dumps(
    {"aliases": project_regions._ALIASES, "labels": project_regions.LABELS,
     "districts": sorted(project_regions.CADASTRAL_DISTRICTS)}, ensure_ascii=False))
PAGE = PAGE.replace(CLASS_REGION_BASES_PLACEHOLDER,
                    json.dumps(CLASS_REGION_BASES, ensure_ascii=False))
PAGE = PAGE.replace(CAPEX_NAMES_PLACEHOLDER, json.dumps(
    {key: CAPEX_SHORT_NAMES.get(key, name) for key, name in _MODEL_CAPEX_LABELS},
    ensure_ascii=False))
# Тип проекта и состав жилых вводных — из движка: два перечисления разошлись
# бы, и «режим включён» значило бы на экране одно, а в расчёте другое.
PAGE = PAGE.replace("__DEVELOPAID_PROJECT_KINDS__",
                    json.dumps([list(pair) for pair in PROJECT_KINDS], ensure_ascii=False))
PAGE = PAGE.replace("__DEVELOPAID_HOTEL__", json.dumps(hotel_page_spec(), ensure_ascii=False))
PAGE = PAGE.replace("__DEVELOPAID_NONRESIDENTIAL_INPUTS__",
                    json.dumps(NONRESIDENTIAL_CLEARED_INPUTS, ensure_ascii=False))
# Состав МКД — из движка, копии на странице нет.
PAGE = PAGE.replace("__DEVELOPAID_MKD_PRODUCTS__",
                    json.dumps(list(MKD_PRODUCTS), ensure_ascii=False))
# Отдельно стоящие объекты — из движка: страница держала четыре рукописных
# перечисления, и пятый объект молчал бы в каждом. Едет ровно то, что странице
# нужно; имя она берёт у строки ТЭП через `productName`.
# Списки полей объектов подставляются JS-литералом в одинарных кавычках — так
# их читают и стенды, и форма v2: список, а не выражение над реестром.
def _js_keys(keys: Any) -> str:
    return ",".join(f"'{key}'" for key in keys)


PAGE = PAGE.replace("__DEVELOPAID_TERRITORY_OBJECT_KEYS__", _js_keys(TERRITORY_OBJECT_INPUT_KEYS))
PAGE = PAGE.replace("__DEVELOPAID_TERRITORY_OBJECT_LABELS__", "".join(
    f"{key}:'{label}: {obj.label}',"
    for obj in STANDALONE_OBJECTS if obj.family
    for key, label in (((f"{obj.prefix}_spaces", "машино-места"),) if obj.measure == "spaces"
                       else ((f"{obj.prefix}_gba_sqm", "площадь"),
                             (f"{obj.prefix}_saleable_sqm", "продаваемая")))))
PAGE = PAGE.replace("__DEVELOPAID_TEP_DERIVED_OBJECT_INPUTS__", _js_keys(
    key for obj in STANDALONE_OBJECTS
    for key in (obj.enabled_key, *((obj.sale_gate,) if obj.sale_gate else ()),
                *((f"{obj.prefix}_spaces", f"{obj.prefix}_area_per_space_sqm")
                  if obj.measure == "spaces"
                  else (f"{obj.prefix}_gba_sqm", f"{obj.prefix}_saleable_sqm")))))
# Перевод «под ключ» → СМР для страницы: коэффициенты по классу (у класса
# свои ставки подготовки и сетей) и умолчания «под ключ» метровых объектов.
# Формула одна — `object_smr_conversion`; страница только применяет (c, m).
PAGE = PAGE.replace("__DEVELOPAID_OBJECT_SMR__", json.dumps({
    "defaults": OBJECT_SMR_RATE_DEFAULTS,
    # Цена офиса в нежилом проекте — из аренды класса (`NONRES_KIND_CLASS_PRICES`).
    "kind_prices": NONRES_KIND_CLASS_PRICES,
    "conversion": {key: list(object_smr_conversion(preset))
                   for key, preset in PROJECT_CLASS_PRESETS.items()},
    "custom": list(object_smr_conversion({})),
}, ensure_ascii=False))
# Подпись ставки объекта по виду проекта — ответ `object_rate_hint` для
# каждого вида: правило живёт в движке, страница только выбирает по виду.
PAGE = PAGE.replace("__DEVELOPAID_OBJECT_RATE_HINTS__", json.dumps(
    {obj.rate_cost: {kind: object_rate_hint({"project_kind": kind}, obj)
                     for kind, _title in PROJECT_KINDS}
     for obj in STANDALONE_OBJECTS}, ensure_ascii=False))
PAGE = PAGE.replace("__DEVELOPAID_UNIT_OBJECTS__", _js_keys(
    obj.key for obj in STANDALONE_OBJECTS if obj.measure == "spaces"))
PAGE = PAGE.replace("__DEVELOPAID_TEP_ROW_SWITCH__", json.dumps(
    {obj.key: [obj.enabled_key, obj.group_label] for obj in STANDALONE_OBJECTS
     if obj.measure == "sqm"}, ensure_ascii=False))
PAGE = PAGE.replace("__DEVELOPAID_STANDALONE_OBJECTS__", json.dumps(
    [{"key": o.key, "prefix": o.prefix, "default_queue": o.default_queue,
      "garage": o.garage, "garage_sellable": o.garage_sellable,
      "measure": o.measure, "sale_gate": o.sale_gate, "product": o.product,
      "label": o.label, "tep_label": o.tep_label, "group_label": o.group_label,
      # Экземпляр типа (`offices3`) и сам тип: из них страница собирает
      # состав проекта и кнопку «Добавить объект».
      "instance": bool(o.family), "type": o.family or o.key,
      "duplicable": o.duplicable,
      # Продукт «паркинг объекта» — ключ из движка, страница его не собирает.
      "parking_product": OBJECT_PARKING_PRODUCT_KEYS.get(o.key, "")}
     for o in STANDALONE_OBJECTS], ensure_ascii=False))
PAGE = PAGE.replace("__DEVELOPAID_OBJECT_INSTANCE_RULES__", json.dumps(
    {"key": OBJECT_INSTANCES_KEY, "max": OBJECT_INSTANCES_MAX,
     "legacy": list(LEGACY_SECOND_OBJECTS), "volume": list(_INSTANCE_VOLUME_FIELDS)},
    ensure_ascii=False))
# Подпись переданных метров — из движка: получателя мы не знаем, и шесть копий
# слова «городу» правились бы порознь.
PAGE = PAGE.replace(TRANSFER_LABELS_PLACEHOLDER, json.dumps(
    {"word": TRANSFER_WORD, "note_word": TRANSFER_NOTE_WORD,
     "recipients": TRANSFER_RECIPIENT_NOTE}, ensure_ascii=False))
PAGE = PAGE.replace("__DEVELOPAID_STORAGE_AREA_PER_UNIT__",
                    json.dumps(STORAGE_AREA_PER_UNIT_DEFAULT))
PAGE = PAGE.replace("__DEVELOPAID_UNDERGROUND_PRODUCTS__",
                    json.dumps(underground_placement_payload(), ensure_ascii=False))
# Мера счёта продукта — из движка: страница, книга, отчёт и тизер обязаны
# называть одно и то же одним словом.
PAGE = PAGE.replace("__DEVELOPAID_TEP_COUNT_MEASURE__",
                    json.dumps(TEP_COUNT_MEASURE, ensure_ascii=False))
PAGE = PAGE.replace("__DEVELOPAID_COUNT_PARKING__",
                    json.dumps(COUNT_PARKING, ensure_ascii=False))
# Разделы таблицы ТЭП — оттуда же, где объявлены составы: два списка и
# остаточный третий раздел. Копии на странице нет по той же причине, что и у
# состава МКД.
PAGE = PAGE.replace("__DEVELOPAID_TEP_GROUPS__",
                    json.dumps([[title, list(keys)] for title, keys in TEP_GROUPS],
                               ensure_ascii=False))
PAGE = PAGE.replace(PARKING_2118_PLACEHOLDER,
                    json.dumps(PARKING_2118_PARAMS, ensure_ascii=False))
# Средняя квартира с основанием — из движка: копию негде обновлять, потому что
# копии нет. Прежде число 58,75 стояло на странице тремя литералами и ни одним
# основанием.
PAGE = PAGE.replace(AVERAGE_FLAT_PLACEHOLDER, json.dumps(
    {key: {"sqm": value, "basis": basis}
     for key, (value, basis) in AVERAGE_FLAT_SOURCES.items()}, ensure_ascii=False))
PAGE = PAGE.replace(VRI_USE_TYPES_PLACEHOLDER, json.dumps(VRI_USE_TYPES, ensure_ascii=False))
PAGE = PAGE.replace(FEEDBACK_FORM_PLACEHOLDER, json.dumps(
    {"groups": FEEDBACK_GROUPS, "roles": FEEDBACK_ROLES, "regions": FEEDBACK_REGIONS},
    ensure_ascii=False))
# Легенда графика эскроу — из движка: PDF рисует те же линии теми же словами.
PAGE = PAGE.replace(ESCROW_CHART_LEGEND_PLACEHOLDER, _escrow_chart_legend_html())
PAGE = PAGE.replace(SOCIAL_MODES_PLACEHOLDER,
                    json.dumps([item[0] for item in _M2_EXTRA_OPTIONS["social_mode"]],
                               ensure_ascii=False))
PAGE = PAGE.replace(BRIDGE_INTEREST_MODES_PLACEHOLDER,
                    json.dumps([item[0] for item in _M2_EXTRA_OPTIONS["bridge_interest_mode"]],
                               ensure_ascii=False))


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    # Всё приложение — одна HTML-страница, и её разметка меняется с каждым
    # выпуском. Без явного запрета браузер держит её в кеше и после обновления
    # сервиса показывает старую версию: выглядит как «деплой не приехал».
    return HTMLResponse(PAGE, headers={
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
        "X-DevelopAid-Version": VERSION,
    })

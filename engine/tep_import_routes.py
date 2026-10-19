"""Маршруты импорта: пресет проекта, ассеты, ТЭП из Excel, анализ территории ГлавАПУ.

Импорт пресета проекта с предпросмотром, раздача /assets, импорт ручного
ТЭП и выгрузки ГлавАПУ, разбор кадастровых номеров, запрос анализа
территории ГлавАПУ с диагнозом отказа и маршрут /cadastral/analyze.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён на том месте, где этот код стоял раньше
(`_engine_part("tep_import_routes")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

@app.post("/api/project-presets/import")
def import_project_preset(req: ProjectPresetRequest) -> dict[str, Any]:
    """Пресет проекта: сначала показать, потом применять.

    Режим `preview` ничего не меняет — он отвечает на вопрос «что будет».
    Режим `apply` возвращает готовые вводные и ТЭП, которые страница ставит
    себе; сам расчёт по-прежнему делает движок, а не импорт.
    """
    try:
        preview = project_preset.build_preview(req.preset)
        filled = {key: value for key, value in (req.filled or {}).items()
                  if value not in (None, "")}
        if filled:
            preview["inputs"].update(filled)
            # `social_mode` — переключатель «или/или»: денежная компенсация
            # отменяет стройку соцобъектов целиком. У проекта, который и строит
            # школу, и платит за стадион, это отняло бы стройку из расходов —
            # EBITDA росла от добавленного расхода. Пока модель не умеет
            # считать обе нагрузки разом, режим не трогаем, а сумму показываем
            # отдельно, чтобы она не выглядела учтённой.
            builds_social = any(float(preview["inputs"].get(key) or 0) > 0
                                for key in ("school_places", "kindergarten_places",
                                            "clinic_capacity"))
            if "social_compensation_mln" in filled:
                preview["inputs"]["social_mode"] = (
                    SOCIAL_MODE_BOTH if builds_social else "Денежная компенсация")
            preview["notes"].append({
                "value": "", "origin": "source", "input_key": "", "input_unit": "",
                "note": "введено вручную на экране проверки: "
                        + ", ".join(sorted(filled)),
            })
    except project_preset.PresetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Пресет не разобран: {exc}") from exc

    labels = {name: _input_field_label(name)
              for group in FIELD_GROUPS for name, *_ in group[1]}
    tep_labels = {key: str(value.get("label") or key) for key, value in TEP_DEFAULT.items()}
    tep_current = req.tep or {}
    tep_rows: list[dict[str, Any]] = []
    for key, values in preview["tep"].items():
        current = tep_current.get(key) or {}
        for field, new_value in values.items():
            old_value = float(current.get(field) or 0.0)
            if abs(float(new_value or 0.0) - old_value) < 1e-6:
                continue
            tep_rows.append({
                "key": f"{key}.{field}", "label": f"{tep_labels.get(key, key)} · {TEP_COLUMN_LABELS.get(field, field)}",
                "was": old_value, "becomes": new_value,
                "action": "заменится" if old_value else "заполнится",
            })

    preview["diff"] = {
        "inputs": _preset_diff(req.inputs or {}, preview["inputs"], labels),
        "tep": tep_rows,
    }
    if req.mode == "apply":
        # Пресет дополняет проект, а не заменяет его: поля, которых он не
        # касается, остаются как были — правило «импорт не ломает ручной ввод».
        preview["applied_inputs"] = {**(req.inputs or {}), **preview["inputs"]}
        applied_tep = {key: dict(value) for key, value in (req.tep or {}).items()}
        for key, values in preview["tep"].items():
            applied_tep.setdefault(key, {})
            applied_tep[key].update(values)
        preview["applied_tep"] = applied_tep
    return preview


_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
_ASSET_CACHE_HEADERS = {"Cache-Control": "public, max-age=604800"}


@app.get("/assets/{name}", include_in_schema=False)
def developaid_asset(name: str) -> Response:
    """Картинки приложения. Лежат файлами и отдаются адресом с кэшем.

    Вшивать их в `PAGE` нельзя: страница отдаётся на каждый запрос целиком, и
    вес картинки платился бы каждым открытием — в том числе с телефона.
    """
    if not re.fullmatch(r"[a-z0-9._-]{1,64}", name) or "/" in name:
        raise HTTPException(status_code=404, detail="Нет такого файла.")
    path = _safe_child(_ASSETS_DIR, name, http_detail="Нет такого файла.",
                       http_status=404)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Нет такого файла.")
    types = {".webp": "image/webp", ".png": "image/png", ".svg": "image/svg+xml"}
    media = types.get(path.suffix.lower())
    if not media:
        raise HTTPException(status_code=404, detail="Такой тип файлов не отдаётся.")
    return Response(path.read_bytes(), media_type=media, headers=_ASSET_CACHE_HEADERS)


@app.post("/import/manual-tep")
async def import_manual_tep(request: Request, filename: str = "") -> dict[str, Any]:
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="Файл не передан")
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Файл слишком большой. Лимит 5 МБ.")
    try:
        return parse_manual_tep_xlsx(data, filename)
    except ManualTepFormatError as exc:
        # Чужой файл: страница вправе попробовать его как выгрузку ГлавАПУ.
        raise HTTPException(status_code=400, detail=str(exc),
                            headers={"X-DevelopAid-Template": "no"}) from exc
    except ValueError as exc:
        # Наш шаблон, заполненный не так. Причина известна — вторая попытка
        # только заменит её на неверный диагноз «формат не распознан».
        raise HTTPException(status_code=400, detail=str(exc),
                            headers={"X-DevelopAid-Template": "yes"}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Не удалось разобрать ручной ТЭП: {exc}") from exc


@app.post("/import/glavapu")
async def import_glavapu(request: Request, filename: str = "") -> dict[str, Any]:
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="Файл не передан")
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Файл слишком большой. Лимит 15 МБ.")
    try:
        return parse_glavapu_xlsx(data, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Не удалось разобрать Excel: {exc}") from exc


_CADASTRAL_NUMBER_RE = re.compile(r"(?<!\d)(\d{2}:\d{2}:\d{6,8}:\d+)(?!\d)")
_GLAVAPU_ANALYSIS_URL = "https://glavapu-api.ru/api/analysis"
# Отказ калькулятора приходит на весь список разом («Анализ территории не найден
# или БД вернула пустой результат») и не называет ни одного участка. Список из
# двадцати двух участков по адресу так и не собрался в территорию, а человеку
# осталась строка без единого номера — искать виновного было негде. Поэтому на
# отказе список опрашивается по одному: спрашиваем сразу несколькими потоками,
# иначе два десятка участков не уложатся в минуту, которую держит nginx.
_GLAVAPU_PROBE_WORKERS = 4
_GLAVAPU_PROBE_TIMEOUT_SECONDS = 15.0


def _parse_cadastral_numbers(value: str | list[str]) -> list[str]:
    raw = "\n".join(str(item) for item in value) if isinstance(value, list) else str(value or "")
    raw = raw.replace("：", ":")
    result: list[str] = []
    seen: set[str] = set()
    for number in _CADASTRAL_NUMBER_RE.findall(raw):
        if number not in seen:
            seen.add(number)
            result.append(number)
    if not result:
        raise HTTPException(
            status_code=400,
            detail="Не найден кадастровый номер вида 77:08:0003005:10.",
        )
    if len(result) > 30:
        raise HTTPException(status_code=400, detail="За один расчёт можно передать не более 30 участков.")
    return result


def _external_error_message(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read(8192).decode("utf-8", errors="replace")
        payload = json.loads(body)
        return str(payload.get("message") or payload.get("detail") or body or exc.reason)
    except Exception:
        return str(exc.reason or exc)


def _glavapu_analysis_payload(numbers: list[str], timeout: float = 30.0) -> dict[str, Any]:
    request_data = json.dumps(
        {"mode": "zu", "cad_numbers": numbers},
        ensure_ascii=False,
    ).encode("utf-8")
    external_request = urllib.request.Request(
        _GLAVAPU_ANALYSIS_URL,
        data=request_data,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(external_request, timeout=timeout) as response:
            raw = response.read(5 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        raise HTTPException(
            status_code=400 if 400 <= exc.code < 500 else 502,
            # Отказ калькулятора — его ответ «такой территории не знаю», и
            # человеку он нужен своими словами, а сам ответ — в скобках.
            detail=("Калькулятор ГлавАПУ не нашёл территорию по этим номерам. Он знает "
                    "только участки Москвы, поэтому проверьте номер "
                    f"(ответ калькулятора: «{_external_error_message(exc)}»)."
                    if 400 <= exc.code < 500 else
                    "Калькулятор ГлавАПУ не ответил как следует, повторите попытку позже "
                    f"(ответ калькулятора: «{_external_error_message(exc)}»)."),
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(
            status_code=502,
            detail="Сервис определения территории временно недоступен. Повторите попытку позже.",
        ) from exc
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(status_code=502, detail="Ответ сервиса определения территории слишком большой.")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail="Сервис определения территории вернул некорректный ответ.") from exc


def _glavapu_knows_number(number: str) -> bool | None:
    """Знает ли калькулятор этот участок. None — спросить не удалось.

    Отказ калькулятора (4xx) — это его ответ «не знаю», а сорванная сеть —
    отсутствие ответа: смешивать их нельзя, иначе недоступность внешнего
    сервиса прочитается как отрицательный ответ о участке.
    """
    try:
        payload = _glavapu_analysis_payload([number], _GLAVAPU_PROBE_TIMEOUT_SECONDS)
    except HTTPException as exc:
        if exc.status_code == 400:
            return False
        return None
    except Exception:
        return None
    features = ((payload.get("cadZU") or {}).get("features")) or []
    return bool(features)


def _glavapu_probe_numbers(numbers: list[str]) -> dict[str, bool | None]:
    verdicts: dict[str, bool | None] = {}
    if not numbers:
        return verdicts
    workers = max(1, min(_GLAVAPU_PROBE_WORKERS, len(numbers)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_glavapu_knows_number, number): number for number in numbers}
        for future in concurrent.futures.as_completed(futures):
            number = futures[future]
            try:
                verdicts[number] = future.result()
            except Exception:
                verdicts[number] = None
    return verdicts


def _glavapu_analysis_with_diagnosis(numbers: list[str]) -> tuple[dict[str, Any], list[str]]:
    """Территория калькулятора и объяснение, если собралась не по всем участкам."""
    try:
        return _glavapu_analysis_payload(numbers), []
    except HTTPException as refusal:
        # Разбирать список по одному имеет смысл, только когда калькулятор
        # ответил и отказал: на сорванной сети это двадцать два бесполезных
        # запроса и минута ожидания вместо причины.
        if refusal.status_code != 400 or len(numbers) < 2:
            raise
    verdicts = _glavapu_probe_numbers(numbers)
    known = [number for number in numbers if verdicts.get(number) is True]
    unknown = [number for number in numbers if verdicts.get(number) is False]
    unchecked = [number for number in numbers if verdicts.get(number) is None]
    if not known:
        raise HTTPException(
            status_code=400,
            detail=(
                "Калькулятор ГлавАПУ не собрал территорию по этим участкам. "
                "Проверил их по одному: "
                + (
                    f"ни один из {len(numbers)} не знаком калькулятору."
                    if not unchecked
                    else f"знакомых нет, ещё {len(unchecked)} проверить не удалось — калькулятор не ответил."
                )
            ),
        )
    diagnosis: list[str] = []
    if unknown:
        diagnosis.append(
            "Калькулятор ГлавАПУ отказал по всему списку. Проверил участки по одному: "
            + ", ".join(unknown)
            + f" — калькулятору незнакомы ({len(unknown)} из {len(numbers)}). "
            f"Территория и ТЭП собраны по остальным {len(known)}."
        )
    if unchecked:
        diagnosis.append(
            "Не удалось проверить: "
            + ", ".join(unchecked)
            + " — калькулятор не ответил. В территорию они не вошли; это не значит, что их нет."
        )
    try:
        return _glavapu_analysis_payload(known), diagnosis
    except HTTPException as second:
        if second.status_code != 400:
            raise
        raise HTTPException(
            status_code=400,
            detail=(
                f"Калькулятор ГлавАПУ знает {len(known)} участков по отдельности, "
                "а вместе территорию по ним не собирает"
                + (f" (незнакомых нет)" if not unknown and not unchecked else "")
                + ". Уберите из списка лишние участки и повторите: скорее всего, "
                "они не смежные."
            ),
        ) from second


def refuse_outside_moscow_region(numbers: list[str]) -> None:
    """Калькулятор ГлавАПУ — московский: участок другого региона ему не отдаём.

    Номер другого кадастрового округа (66:, 78:…) — точно не Москва и не
    область. Прежде такой участок уходил в калькулятор, и человек получал его
    отказ «Анализ территории не найден или БД вернула пустой результат», а
    серверный расчёт ТЭП и перенос таблицы проверки региона не имели вовсе.
    """
    outside = [number for number in numbers if project_regions.outside_moscow_region(number)]
    if not outside:
        return
    raise HTTPException(
        status_code=400,
        detail=("Участок " + ", ".join(outside) + " находится не в Москве и не в Московской "
                "области. Калькулятор ГлавАПУ считает только Москву, поэтому по нему мы "
                "его не считаем. ТЭП такого участка считается по плотности, которую задаёте "
                "вы, — кнопкой «Получить ТЭП»."),
    )


@app.post("/cadastral/analyze")
def analyze_cadastral_territory(req: CadastralAnalysisRequest) -> dict[str, Any]:
    # Как и остальные внешние справочники: если этот сервер до ГлавАПУ не
    # достаёт, спрашиваем тот, который достаёт, вместо ошибки в интерфейсе.
    if _core_api_url("/cadastral/analyze"):
        return _core_post(
            _core_api_url("/cadastral/analyze"),
            _core_forward_payload(req),
            _MO_CALC_TIMEOUT_SECONDS,
        )
    cadastral_numbers = _parse_cadastral_numbers(req.cadastral_numbers)
    refuse_outside_moscow_region(cadastral_numbers)
    payload, diagnosis = _glavapu_analysis_with_diagnosis(cadastral_numbers)

    cad_territory = payload.get("cadZU") or {}
    features = cad_territory.get("features") or []
    parcels: list[dict[str, Any]] = []
    returned_numbers: list[str] = []
    for feature in features:
        properties = feature.get("properties") or {}
        number = str(properties.get("cad_num") or "").strip()
        if not number:
            continue
        returned_numbers.append(number)
        parcels.append({
            "cadastral_number": number,
            "area_ha": round(float(properties.get("square") or 0.0), 4),
        })
    missing = [number for number in cadastral_numbers if number not in set(returned_numbers)]
    total_area = round(float(cad_territory.get("square") or sum(item["area_ha"] for item in parcels)), 4)
    district_props = (payload.get("district") or {}).get("properties") or {}
    cad_quarter = payload.get("cadQuarter") or {}
    rail = payload.get("rail_transport_availability") or {}
    business = payload.get("transport_coeff_business_activity") or {}
    point = payload.get("pointPosition") or {}
    inside_moscow = bool(payload.get("insideMSC"))

    warnings: list[str] = list(diagnosis)
    # Когда список разбирался по одному, «не найдены» уже сказано подробнее —
    # с числом, причиной и тем, по скольким участкам собрана территория.
    if missing and not diagnosis:
        warnings.append("Не найдены: " + ", ".join(missing) + ".")
    if not inside_moscow:
        warnings.append("Калькулятор genplan.tech рассчитывает нормативные ТЭП только для территории Москвы.")
    if len(parcels) > 1:
        warnings.append(
            "Участки объединены в одну расчётную территорию; перед расчётом ТЭП проверьте смежность и отсутствие разрывов."
        )
    warnings.append(
        "На внешнюю сторону переданы только кадастровые номера. Финансовые вводные и данные модели не передавались."
    )

    calculator_url = "https://genplan.tech/calc/?" + urllib.parse.urlencode({
        "terrArea": f"{total_area:.4f}",
        "restrictArea": "0",
    })
    return {
        "requested": cadastral_numbers,
        "recognized": returned_numbers,
        "missing": missing,
        "parcels": parcels,
        "territory": {
            "parcel_count": len(parcels),
            "area_ha": total_area,
            "district": district_props.get("name") or "",
            "administrative_district": district_props.get("name_ao") or "",
            "cadastral_quarter": cad_quarter.get("quarter") or "",
            "inside_moscow": inside_moscow,
            "inside_ttc": bool(payload.get("insideTTC")),
            # Отсутствующий ключ — не «вне ТТК»: без этого признака читатель
            # не отличил бы ответ ГлавАПУ «вне кольца» от молчания.
            "inside_ttc_known": payload.get("insideTTC") is not None,
            "center": {
                "lat": point.get("lat"),
                "lng": point.get("lng"),
            },
        },
        "coefficients": {
            "rail_zone": rail.get("zone"),
            "rail": rail.get("coeff_rail"),
            "business_inside_ttc": business.get("coeff_ba_inside_ttc"),
            "business_outside_ttc": business.get("coeff_ba_outside_ttc"),
            "rent": cad_quarter.get("coeff_rent"),
            "mpt_location": bool(cad_quarter.get("coeff_mpt_of_location")),
            # Базовая стоимость МКД по кварталу — основание платы за смену
            # ВРИ: без неё плата не считается и честно остаётся нулём.
            "base_cost_zh_high": cad_quarter.get("base_cost_zh_high"),
            # УПКС квартала — второе слагаемое компенсации за соцобъекты:
            # в неё входит стоимость земли под объектом, а она у каждого
            # квартала своя. Пока поле не читалось, ставки были зашиты
            # константами с одного участка и на других занижали платёж.
            "upks_zh_high": cad_quarter.get("upks_zh_high"),
        },
        "calculator_url": calculator_url,
        "warnings": warnings,
        "source": {
            "service": "genplan.tech / glavapu-api.ru",
            "analysis_endpoint": "glavapu-api.ru/api/analysis",
            "calculated_at": date.today().isoformat(),
        },
    }

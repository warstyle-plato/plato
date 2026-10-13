"""Штатный калькулятор ГлавАПУ на сервере: браузер, дрейф, сценарии, ТЭП по номерам.

Индексация базы ВРИ, безголовый браузер и очередь заданий, чтение
страницы калькулятора, дрейф-контроль серверных формул, кэш и здоровье
(/glavapu/probe, /glavapu/health), сценарии ГлавАПУ, cadastral_tep_server,
vri_tep_moscow и импорт ТЭП по кадастровым номерам.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён на том месте, где этот код стоял раньше
(`_engine_part("glavapu")`), поэтому здесь видны все имена движка,
а подмены `core.<имя>` из `main.py` и тестов действуют и на этот код.
Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

_GLAVAPU_VRI_BASE_INDEXATION = 1.0175
_GLAVAPU_VRI_BASE_INDEXATION_DATE = "16.08.2026"

# --- штатный калькулятор ГлавАПУ на сервере ---------------------------------
# Копировать методику ГлавАПУ оказалось тупиком: плата за ВРИ разошлась на
# 1,75%, компенсация — на 19%, и оба раза расхождение находил человек на
# скриншотах, а не мы. Ставки индексируются, коэффициенты меняются, и наш
# пересказ отстаёт на неизвестный срок. Поэтому расчёт делает сам калькулятор,
# запущенный браузером без экрана: та же последовательность, что отрабатывает
# скрытый iframe на сайте. Наши формулы остаются фолбэком — если ГлавАПУ
# недоступен или сломалась автоматизация, отчёт честно говорит, что расчёт
# запасной, вместо тихой выдачи устаревшей методики.
_GLAVAPU_HEADLESS_ENABLED = _env_str("GLAVAPU_HEADLESS", "").strip().lower() in ("1", "true", "yes", "on")
_GLAVAPU_HEADLESS_TIMEOUT_MS = int(max(20.0, _env_float("GLAVAPU_HEADLESS_TIMEOUT_SECONDS", 90.0)) * 1000)
_GLAVAPU_HEADLESS: dict[str, Any] = {"last_ok": "", "last_error": "", "runs": 0,
                                     "fallbacks": 0, "waits": 0, "last_ms": {}}
# Браузер запускается по одному на машину: ядро — 2 vCPU и 4 ГБ, воркеров два,
# и каждый Chromium берёт 300–400 МБ. Два одновременных расчёта клали бы не
# только ТЭП, а весь контейнер по нехватке памяти. Второй запрос ждёт очереди
# — секунды ожидания дешевле перезапуска бота.
_GLAVAPU_HEADLESS_SLOTS = max(1, int(_env_float("GLAVAPU_HEADLESS_PARALLEL", 1)))
_GLAVAPU_HEADLESS_LOCK = threading.Semaphore(_GLAVAPU_HEADLESS_SLOTS)
_GLAVAPU_HEADLESS_QUEUE_SECONDS = max(5.0, _env_float("GLAVAPU_HEADLESS_QUEUE_SECONDS", 120.0))
# Предохранитель. Пока штатный калькулятор недоступен — нет Chromium в образе,
# закрыт выход к genplan.tech, сменилась вёрстка — каждый расчёт честно ждал
# полный таймаут и только потом уходил на формулы. Человек платил полторы
# минуты за ответ, который был известен заранее. После сбоя браузер не трогаем
# несколько минут: формулы отвечают сразу, а причина видна в /status.
_GLAVAPU_HEADLESS_COOLDOWN_SECONDS = max(0.0, _env_float("GLAVAPU_HEADLESS_COOLDOWN_SECONDS", 300.0))
_GLAVAPU_HEADLESS_BLOCKED_UNTIL = {"at": 0.0, "row": 0}

# Предохранитель растёт, пока отказы идут подряд, и не дольше получаса.
# 01.09.2026 калькулятор ГлавАПУ лежал у самого города — проверено вручную в
# браузере, — и каждый человек платил за это ожиданием: пять минут паузы, потом
# снова полторы минуты в недоступную кнопку, и так весь день. Пауза в пять
# минут написана под СРЫВ БРАУЗЕРА, который проходит сам; лежащий чужой сервис
# сам не проходит, и стучаться к нему с прежней частотой — это платить временем
# людей за уже известный ответ.
#
# Обратная сторона названа тем же правилом, по которому пауза вообще короткая:
# запасной ответ не должен пережить штатный. Поэтому лестница сбрасывается
# первым же удавшимся расчётом, а расти начинает только со второго отказа —
# одиночный срыв браузера остаётся пятиминутным, как и был.
_GLAVAPU_HEADLESS_COOLDOWN_MAX_SECONDS = max(
    _GLAVAPU_HEADLESS_COOLDOWN_SECONDS,
    _env_float("GLAVAPU_HEADLESS_COOLDOWN_MAX_SECONDS", 1800.0))


def _glavapu_headless_available() -> bool:
    """Стоит ли вообще пытаться поднимать браузер."""
    if not _GLAVAPU_HEADLESS_ENABLED:
        return False
    return time.monotonic() >= _GLAVAPU_HEADLESS_BLOCKED_UNTIL["at"]


def _glavapu_cooldown_seconds(row: int) -> float:
    """Пауза после `row`-го отказа подряд: 5, 10, 20, 30 минут и дальше 30."""
    if _GLAVAPU_HEADLESS_COOLDOWN_SECONDS <= 0:
        return 0.0
    grown = _GLAVAPU_HEADLESS_COOLDOWN_SECONDS * (2 ** max(0, int(row) - 1))
    return min(grown, _GLAVAPU_HEADLESS_COOLDOWN_MAX_SECONDS)


def _glavapu_headless_failed() -> None:
    _GLAVAPU_HEADLESS_BLOCKED_UNTIL["row"] = int(
        _GLAVAPU_HEADLESS_BLOCKED_UNTIL.get("row") or 0) + 1
    pause = _glavapu_cooldown_seconds(_GLAVAPU_HEADLESS_BLOCKED_UNTIL["row"])
    if pause > 0:
        _GLAVAPU_HEADLESS_BLOCKED_UNTIL["at"] = time.monotonic() + pause

# Браузер живёт между расчётами. Холодный запуск Chromium и первая загрузка
# страницы калькулятора со всеми её ассетами стоили большую часть минуты, и
# платились они каждый раз заново. Тёплый браузер отдаёт ассеты из своего кэша,
# а платится за это памятью — поэтому после простоя он закрывается сам.
#
# Синхронный Playwright привязан к потоку, в котором создан, поэтому браузером
# владеет один выделенный поток, а расчёты приходят к нему очередью. Заодно это
# и есть ограничение «один Chromium на машину»: второго потока не бывает.
# Ноль (умолчание) — браузер живёт, пока живёт процесс. Таймер простоя экономил
# 300–400 МБ, но платил холодным стартом за каждый расчёт: боты не работают
# непрерывно, и пятнадцати минут между двумя участками хватает, чтобы Chromium
# успел закрыться. Кому память дороже секунд — ставит секунды.
_GLAVAPU_HEADLESS_IDLE_SECONDS = max(0.0, _env_float("GLAVAPU_HEADLESS_IDLE_SECONDS", 0.0))
_GLAVAPU_HEADLESS_POLL_MS = int(max(50.0, _env_float("GLAVAPU_HEADLESS_POLL_MS", 200.0)))
_GLAVAPU_HEADLESS_JOBS: "queue.Queue[tuple[list[str], float, dict[str, Any], threading.Event]]" = queue.Queue()
_GLAVAPU_BROWSER_LOCK = threading.Lock()
_GLAVAPU_BROWSER_THREAD: threading.Thread | None = None
# --disable-dev-shm-usage: в контейнере /dev/shm мал, и Chromium на тяжёлой
# странице падает молча, вместо того чтобы честно отработать.
_GLAVAPU_HEADLESS_ARGS = [
    "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
    "--disable-extensions", "--disable-background-networking",
    "--disable-features=Translate,BackForwardCache", "--mute-audio", "--no-first-run",
]
# Картинки, шрифты и счётчики к таблице ТЭП отношения не имеют, а тянутся
# дольше самого расчёта. Всё, что участвует в счёте, — запросы к API ГлавАПУ.
# Что случилось с запросами САМОЙ страницы. Территория у ГлавАПУ формируется не
# в браузере: страница спрашивает свой бэкенд, и пока ответа нет, кнопка
# «Перейти к расчётам» стоит недоступной — ровно то, что мы видели. Канал до их
# API с ядра никто не проверял (владелец, 01.09.2026: «ты вообще проверить
# канал до ГлавАПУ то не хочешь?»), а по нашей диагностике это было неотличимо
# от «участок не опознан».
#
# Список ограничен и очищается перед каждым расчётом: это диагностика, а не
# журнал.
_GLAVAPU_NET: dict[str, list[dict[str, str]]] = {"failed": [], "bad": []}
_GLAVAPU_NET_LIMIT = 12


def _glavapu_net_reset() -> None:
    _GLAVAPU_NET["failed"] = []
    _GLAVAPU_NET["bad"] = []


def _glavapu_net_watch(page: Any) -> None:
    """Записывает сорванные запросы и ответы с ошибкой. Один раз на страницу."""
    def failed(request: Any) -> None:
        if len(_GLAVAPU_NET["failed"]) >= _GLAVAPU_NET_LIMIT:
            return
        try:
            failure = str(getattr(request, "failure", "") or "")
            # Мы сами гасим аналитику и картинки — это не сорванный канал.
            if "aborted" in failure.lower() or "ERR_ABORTED" in failure:
                return
            _GLAVAPU_NET["failed"].append(
                {"url": str(request.url)[:200], "why": failure[:120]})
        except Exception:
            pass

    def answered(response: Any) -> None:
        try:
            if int(response.status) < 400 or len(_GLAVAPU_NET["bad"]) >= _GLAVAPU_NET_LIMIT:
                return
            _GLAVAPU_NET["bad"].append(
                {"url": str(response.url)[:200], "why": f"HTTP {response.status}"})
        except Exception:
            pass

    page.on("requestfailed", failed)
    page.on("response", answered)


_GLAVAPU_BLOCKED_TYPES = {"image", "font", "media"}
_GLAVAPU_BLOCKED_HOSTS = ("mc.yandex.", "metrika", "google-analytics.com",
                          "googletagmanager.com", "top-fwz1.mail.ru",
                          "doubleclick.net", "vk.com/rtrg")

# Обучающий тур genplan.tech (react-joyride) висит поверх интерфейса с
# затемнением и перехватывает клики: Playwright честно повторял попытку 168 раз
# и уходил в таймаут. В браузере человека тур закрыт однажды и больше не
# появляется, а свежий Chromium на сервере видит его каждый раз.
#
# Сначала пробуем закрыть штатно — кнопкой пропуска: она пишет в хранилище, что
# тур пройден, и он не возвращается. Если кнопки нет, снимаем оверлей из DOM.
_GLAVAPU_DISMISS_TOUR_JS = """() => {
  let closed = 0;
  const buttons = document.querySelectorAll(
    '[data-action="skip"], [data-action="close"], [aria-label="Close"],'
    + ' .react-joyride__tooltip button');
  for (const button of buttons) {
    const label = String(button.textContent || '').trim().toLowerCase();
    const action = String(button.getAttribute('data-action') || '');
    if (action === 'skip' || action === 'close'
        || /пропустить|закрыть|skip|close|понятно/.test(label)) {
      button.click();
      closed += 1;
      break;
    }
  }
  // Узлы не удаляем: React считает портал своим и при следующем обновлении
  // обращается к нему. Удаление роняло всё приложение — калькулятор показывал
  // экран «Перезагрузить страницу», и расчёт упирался в отсутствие полей.
  // Стиль тур гасит так же надёжно, а чужой DOM остаётся нетронутым.
  let hidden = 0;
  if (!document.getElementById('plato-tour-off')) {
    const style = document.createElement('style');
    style.id = 'plato-tour-off';
    style.textContent = '#react-joyride-portal, .react-joyride__overlay,'
      + ' .react-joyride__spotlight, .react-joyride__tooltip'
      + ' { display: none !important; pointer-events: none !important; }';
    document.head.appendChild(style);
    hidden = 1;
  }
  return {closed, hidden};
}"""

# Поле кадастровых номеров ищется по нескольким признакам. Один жёсткий
# селектор на чужой странице — это обещание, что вёрстка genplan.tech никогда
# не изменится; она изменилась, и `#id-cad-numbers-text-field` перестал
# находиться, а расчёт девяносто секунд ждал элемент, которого нет.
_GLAVAPU_NUMBER_FIELD_SELECTORS = (
    "#id-cad-numbers-text-field",
    "[id*='cad-numbers']",
    "textarea[placeholder*='адастр']",
    "input[placeholder*='адастр']",
    "[aria-label*='адастр']",
    ".MuiDialog-root textarea, .MuiDialog-root input[type='text']",
)

# Что вообще есть на странице в момент срыва: без этого следующая правка
# селектора — это ещё один круг переписки со скриншотами.
#
# Видимость считается по прямоугольнику, а не по offsetParent: у всего, что
# лежит внутри position:fixed — а диалоги MUI именно такие, — offsetParent
# равен null, и поле в открытом диалоге не попало бы в список вовсе. Первая
# версия этой диагностики честно сообщила «полей нет» там, где они могли быть.
_GLAVAPU_VISIBLE_FIELDS_JS = """() => {
  const shown = el => {
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };
  const fields = Array.from(document.querySelectorAll('input, textarea'))
    .slice(0, 15)
    .map(el => [el.tagName.toLowerCase(), el.id || '-',
                el.getAttribute('placeholder') || el.getAttribute('aria-label') || '-',
                shown(el) ? 'виден' : 'скрыт'].join(':'));
  const buttons = Array.from(document.querySelectorAll('button, [role="button"]'))
    .filter(shown)
    .slice(0, 15)
    .map(el => String(el.textContent || '').trim().slice(0, 24) || '·');
  return {
    url: String(location.href).slice(0, 120),
    fields: fields.length ? fields : ['нет'],
    buttons: buttons.length ? buttons : ['нет'],
  };
}"""

_GLAVAPU_READ_ROWS_JS = """() => {
  const table = document.querySelector('table[aria-label="calc table"]');
  if (!table) return [];
  return Array.from(table.querySelectorAll('tbody tr')).map(row => {
    const cells = Array.from(row.children).map(c => String(c.textContent || '').replace(/\s+/g, ' ').trim());
    if (cells.length < 4) return null;
    const raw = cells[0];
    const code = /^\d+(?:[.,]\d+)*$/.test(raw) ? raw.replace(/,/g, '.') : '';
    return {code, name: cells[1], unit: cells[2], value: cells[3]};
  }).filter(r => r && r.name && r.value);
}"""


# Что на странице лежит на самом деле. Спрашивается ровно тогда, когда таблица
# не признана готовой: «калькулятор не отдал таблицу (строк 79)» — сообщение,
# которое ничего не объясняет, потому что таблица-то как раз пришла, и в ней
# семьдесят девять строк. Не сошлись КОДЫ, а какие пришли — знала только чужая
# страница. Правило прежнее: селектор на чужой странице живёт парой с
# диагностикой, и в ошибку кладётся сама страница, а не её отсутствие.
_GLAVAPU_SNAPSHOT_JS = """() => {
  const tables = Array.from(document.querySelectorAll('table')).map(t => ({
    label: t.getAttribute('aria-label') || '',
    rows: t.querySelectorAll('tbody tr').length,
  }));
  const table = document.querySelector('table[aria-label="calc table"]');
  const rows = table ? Array.from(table.querySelectorAll('tbody tr')).map(row =>
    Array.from(row.children).map(c => String(c.textContent || '').replace(/\s+/g, ' ').trim())
  ) : [];
  const proceed = document.querySelector('[data-r="map-proceed-button"]')
    || Array.from(document.querySelectorAll('button')).find(b =>
         /перейти к расч/i.test(b.getAttribute('aria-label') || b.textContent || ''));
  const dialog = document.querySelector('[role="dialog"]');
  return {
    url: location.href,
    proceed: proceed ? {
      disabled: !!proceed.disabled,
      label: String(proceed.getAttribute('aria-label') || proceed.textContent || '')
        .replace(/\s+/g, ' ').trim().slice(0, 80),
    } : null,
    dialog: dialog ? String(dialog.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 600) : '',
    // Ввод участка у ГлавАПУ — не диалог, а левая ПАНЕЛЬ (экран владельца,
    // 01.09.2026), и `[role="dialog"]` её не находит: отказ говорил «диалог
    // ничего не сообщил» там, где на странице написано «Район: Савёловский» и
    // площадь участка. В ошибку кладётся сама страница, а не её отсутствие.
    page_text: String(document.body ? document.body.innerText || '' : '')
      .replace(/\s+/g, ' ').trim().slice(0, 1500),
    errors: Array.from(document.querySelectorAll(
      '.Mui-error, .MuiFormHelperText-root, [role="alert"]'))
      .map(n => String(n.textContent || '').replace(/\s+/g, ' ').trim())
      .filter(Boolean).slice(0, 8),
    tables: tables.slice(0, 12),
    calc_table: !!table,
    row_count: rows.length,
    widths: Array.from(new Set(rows.map(r => r.length))).slice(0, 6),
    sample: rows.slice(0, 6),
    tail: rows.slice(-3),
    buttons: Array.from(document.querySelectorAll('button'))
      .map(b => String(b.textContent || '').replace(/\s+/g, ' ').trim())
      .filter(Boolean).slice(0, 12),
  };
}"""


# Строки, без которых таблица бесполезна. Проверяются по ИМЕНИ, а не по номеру:
# разбор и так читает таблицу по именам, а номера чужой таблицы источник
# перенумеровал молча — кода 60 у ГлавАПУ больше нет, таблица кончается на 58
# (живой снимок ядра, 01.09.2026). Имя строки означает величину, номер — только
# её место, и держаться надо за первое.
_GLAVAPU_CONTROL_NAMES = (
    "площадь территории проектирования",
    "население",
    "количество квартир",
    "площадь квартир",
)


def _glavapu_name_key(value: Any) -> str:
    return " ".join(str(value or "").lower().replace("ё", "е").split())


def _glavapu_stems(value: str) -> list[str]:
    """Основы слов: шесть букв хватает, чтобы пережить падеж и не поймать чужое."""
    return [word[:6] for word in _glavapu_name_key(value).split() if len(word) > 2]


def _glavapu_missing_controls(rows: list[dict[str, Any]]) -> list[str]:
    """Каких контрольных строк в таблице нет. Пусто — значит все на месте.

    Ищется не начало строки и не строка целиком, а ОСНОВЫ её слов в любом
    месте имени. Начало — та же ловушка, что и номер строки, только мягче:
    «Численность населения» не начинается с «население». Целое слово — ловушка
    третья: «населения» это не «население», русский падеж рассыпает совпадение
    ровно так же, как он рассыпал якорь площадки в модуле публикаций.

    Ложное совпадение здесь дёшево — это признак готовности, а не величина;
    пропущенное останавливает расчёт у всех сразу.
    """
    have = [_glavapu_name_key(row.get("name")) for row in rows]
    return [need for need in _GLAVAPU_CONTROL_NAMES
            if not any(all(stem in name for stem in _glavapu_stems(need))
                       for name in have)]


def _glavapu_table_shot(rows: list[dict[str, Any]]) -> str:
    """Отпечаток таблицы: по нему видно, что она перестала меняться.

    Ждать «появился код 60» нельзя — номер чужой строки меняет источник. Ждать
    «таблица перестала меняться» можно всегда: это свойство самой таблицы, а не
    её нумерации.
    """
    return "|".join(
        f"{row.get('code') or ''}={row.get('value') or ''}" for row in rows)


def _glavapu_not_ready_message(rows: list[dict[str, Any]],
                               snapshot: dict[str, Any]) -> str:
    """Отказ называет то, что увидел, а не то, чего не дождался.

    Состояния читаются одинаково и означают разное: таблицы нет вовсе; таблица
    есть и пуста; таблица полна, но в ней нет строк, которые мы читаем; таблица
    полна и всё ещё считается.
    """
    limit = _GLAVAPU_HEADLESS_TIMEOUT_MS // 1000
    if not snapshot.get("calc_table", True):
        labels = ", ".join(f"{t.get('label') or '—'}:{t.get('rows')}"
                           for t in (snapshot.get("tables") or [])[:6])
        return (f"таблицы calc table на странице нет за {limit} с; "
                f"таблицы на странице: {labels or 'ни одной'}")
    if not rows:
        return f"таблица calc table пуста за {limit} с"
    missing = _glavapu_missing_controls(rows)
    if missing:
        first = " | ".join((snapshot.get("sample") or [[]])[0][:4])
        return (f"таблица есть ({len(rows)} строк), но в ней нет строк, которые мы "
                f"читаем: {', '.join(missing)}. Первая строка: {first[:180]}")
    return (f"таблица есть ({len(rows)} строк), все контрольные строки на месте, но за "
            f"{limit} с она так и не перестала меняться — калькулятор всё ещё считает")


class GlavapuParcelNotAccepted(TimeoutError):
    """Калькулятор не принял участок: кнопка перехода к расчётам не ожила.

    Живой ответ ядра (01.09.2026): кнопка `map-proceed-button` есть, но стоит
    `disabled` с подписью «…», и Playwright девяносто секунд стучится в неё,
    после чего отдаёт свой стек. Читать в нём нечего: это не поломка клика, а
    ответ калькулятора — он не собрал территорию по этим номерам. Ждать в таком
    состоянии бессмысленно: кнопка не оживёт, пока участок не опознан.
    """

    def __init__(self, message: str, snapshot: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        # Подпись написана нами для человека — её и отдаём наружу, а не
        # `str(exc)`: так в ответ не попадает ничего, кроме этого текста.
        self.public_message = str(message)
        self.snapshot = snapshot or {}


class GlavapuTableNotReady(TimeoutError):
    """Таблица не признана готовой. Снимок страницы приложен к отказу."""

    def __init__(self, message: str, snapshot: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        # Подпись написана нами для человека — её и отдаём наружу, а не
        # `str(exc)`: так в ответ не попадает ничего, кроме этого текста.
        self.public_message = str(message)
        self.snapshot = snapshot or {}


def _glavapu_block_junk(route: Any) -> None:
    """Отсекает то, что к расчёту отношения не имеет."""
    request = route.request
    junk = (request.resource_type in _GLAVAPU_BLOCKED_TYPES
            or any(host in request.url for host in _GLAVAPU_BLOCKED_HOSTS))
    try:
        route.abort() if junk else route.continue_()
    except Exception:  # страница уже ушла — нечего продолжать
        pass


# Сколько ждём, пока калькулятор примет участок. Меньше общего срока
# намеренно: пока кнопка перехода стоит `disabled`, таблицы не будет вовсе, и
# доедать оставшееся время нечем — а отказ нужен человеку сейчас, а не через
# полторы минуты.
_GLAVAPU_PARCEL_WAIT_MS = 45_000


def _glavapu_proceed(page: Any, numbers: list[str]) -> None:
    """Нажать «Перейти к расчётам», дождавшись, что кнопка ожила.

    Прежде здесь стоял голый `click()`, и Playwright девяносто секунд стучался
    в `disabled`-кнопку, после чего отдавал свой стек: «Timeout 90000ms
    exceeded … element is not enabled». В стеке не было главного — что
    калькулятор ПРОСТО НЕ ОПОЗНАЛ участок, и кнопка не оживёт никогда.

    Кнопка ищется по нескольким признакам: `data-r` устойчивее подписи, а
    подпись у неё в этом состоянии вообще «…». Правило то же, что и с полем
    номеров: селектор на чужой странице живёт парой с диагностикой.
    """
    button = page.locator('[data-r="map-proceed-button"]').first
    try:
        button.wait_for(state="attached", timeout=5000)
    except Exception:
        button = page.get_by_role("button", name="Перейти к расчётам").first
    deadline = time.monotonic() + _GLAVAPU_PARCEL_WAIT_MS / 1000.0
    while True:
        try:
            if button.is_enabled(timeout=1000):
                button.click(timeout=10_000)
                return
        except Exception:
            pass
        if time.monotonic() > deadline:
            break
        page.wait_for_timeout(_GLAVAPU_HEADLESS_POLL_MS)
    try:
        snapshot = page.evaluate(_GLAVAPU_SNAPSHOT_JS) or {}
    except Exception:
        snapshot = {}
    snapshot = _glavapu_with_network(snapshot)
    raise GlavapuParcelNotAccepted(
        _glavapu_parcel_message(numbers, snapshot), snapshot)


def _glavapu_with_network(snapshot: dict[str, Any]) -> dict[str, Any]:
    """К снимку — что случилось с запросами страницы к её же бэкенду."""
    out = dict(snapshot or {})
    out["network_failed"] = list(_GLAVAPU_NET["failed"])
    out["network_bad"] = list(_GLAVAPU_NET["bad"])
    return out


def _glavapu_network_note(snapshot: dict[str, Any]) -> str:
    """Одной фразой: дошли ли запросы страницы до её бэкенда."""
    failed = snapshot.get("network_failed") or []
    bad = snapshot.get("network_bad") or []
    if not failed and not bad:
        return ""
    parts = []
    if failed:
        first = failed[0]
        parts.append(f"не дошли {len(failed)} запросов страницы, первый — "
                     f"{first.get('url', '')} ({first.get('why', '')})")
    if bad:
        first = bad[0]
        parts.append(f"ответили ошибкой {len(bad)}, первый — "
                     f"{first.get('url', '')} ({first.get('why', '')})")
    return "Канал страницы: " + "; ".join(parts) + ". "


def _glavapu_parcel_message(numbers: list[str], snapshot: dict[str, Any]) -> str:
    """Отказ шага участка — словами, а не стеком Playwright."""
    limit = _GLAVAPU_PARCEL_WAIT_MS // 1000
    listed = ", ".join(numbers[:3]) + ("…" if len(numbers) > 3 else "")
    proceed = snapshot.get("proceed")
    if proceed is None:
        return (f"кнопки «Перейти к расчётам» на странице нет за {limit} с; "
                f"участки: {listed}")
    said = "; ".join(str(x) for x in (snapshot.get("errors") or []))[:200]
    # Панель ввода участка — не диалог, поэтому текст берётся со страницы
    # целиком: по нему видно, сформировалась территория (есть район и площадь)
    # или ввод не дошёл вовсе.
    told = str(snapshot.get("dialog") or "") or str(snapshot.get("page_text") or "")
    return (f"калькулятор не принял участок за {limit} с: кнопка «Перейти к расчётам» "
            f"осталась недоступной (подпись «{proceed.get('label') or '—'}»). "
            f"Участки: {listed}. "
            + _glavapu_network_note(snapshot)
            + (f"Страница говорит: {said}. " if said else "")
            + (f"На странице: {told[:400]}" if told else "Страница ничего не сообщила"))


def _glavapu_drive_page(page: Any, numbers: list[str], area_ha: float,
                        timings: dict[str, int]) -> list[dict[str, Any]]:
    """Шаги браузерной автоматизации — те же, что отрабатывает скрытый iframe
    на сайте: «Участок» → кадастровые номера → «Отправить» → «Перейти к
    расчётам» → чтение таблицы. Готовность таблицы определяется так же, как на
    странице: есть коды 60 и 54 и не меньше шестидесяти строк — иначе рискуем
    снять её недосчитанной.

    Страница переиспользуется между расчётами, поэтому хранилище прошлого
    прогона стирается: восстановленный оттуда чужой участок дал бы правдоподобно
    выглядящий чужой ТЭП. Сама таблица переживает переход не может — переход
    пересобирает DOM.
    """
    step = time.monotonic()

    def mark(name: str) -> None:
        nonlocal step
        now = time.monotonic()
        timings[name] = int((now - step) * 1000)
        step = now

    def recover_if_crashed() -> None:
        """Калькулятор мог упасть и показать экран «Перезагрузить страницу».

        Своя кнопка перезагрузки у него есть — нажимаем её и даём приложению
        собраться заново, вместо того чтобы искать поля на экране ошибки.
        """
        try:
            button = page.get_by_role("button", name="Перезагрузить страницу").first
            if button.is_visible(timeout=1500):
                button.click(timeout=5000)
                page.wait_for_timeout(2500)
                timings["reloaded"] = timings.get("reloaded", 0) + 1
        except Exception:
            pass

    def open_parcel_dialog() -> None:
        """Открывает панель ввода участка.

        «Участок» может оказаться и кнопкой, и вкладкой, и пунктом меню —
        роль button находит не всё. Промах здесь виден не сразу: клик проходит
        вхолостую, а падает уже поиск поля, и причина выглядит чужой.
        """
        attempts = (
            lambda: page.get_by_role("button", name="Участок").first,
            lambda: page.get_by_role("tab", name="Участок").first,
            lambda: page.get_by_text("Участок", exact=True).first,
        )
        for index, attempt in enumerate(attempts):
            try:
                attempt().click(timeout=7000)
                timings["parcel_click"] = index
                return
            except Exception:
                continue
        raise TimeoutError("кнопка «Участок» не нажалась ни одним способом")

    def fill_numbers(text: str) -> None:
        """Вводит кадастровые номера, чем бы ни было поле в текущей вёрстке."""
        for selector in _GLAVAPU_NUMBER_FIELD_SELECTORS:
            try:
                field = page.locator(selector).first
                field.wait_for(state="visible", timeout=5000)
                field.fill(text)
                timings["field"] = _GLAVAPU_NUMBER_FIELD_SELECTORS.index(selector)
                return
            except Exception:
                continue
        try:
            seen = page.evaluate(_GLAVAPU_VISIBLE_FIELDS_JS) or {}
        except Exception:
            seen = {}
        raise TimeoutError(
            "поле кадастровых номеров не найдено. Поля: "
            + ("; ".join(str(x) for x in (seen.get("fields") or ["?"]))[:220])
            + ". Кнопки: "
            + ("; ".join(str(x) for x in (seen.get("buttons") or ["?"]))[:220])
            + f". Адрес: {seen.get('url') or '?'}")

    def dismiss_tour() -> None:
        """Снимает обучающий тур, если он перехватывает клики."""
        try:
            result = page.evaluate(_GLAVAPU_DISMISS_TOUR_JS) or {}
        except Exception:
            return
        if result.get("closed") or result.get("hidden"):
            timings["tour"] = timings.get("tour", 0) + 1

    try:
        if "genplan.tech" in str(page.url or ""):
            page.evaluate("() => { try { localStorage.clear(); sessionStorage.clear(); }"
                          " catch (e) {} }")
    except Exception:
        pass
    url = ("https://genplan.tech/calc/?terrArea=" + urllib.parse.quote(f"{area_ha:.4f}")
           + "&restrictArea=0&plato=" + str(int(time.time() * 1000)))
    page.goto(url, wait_until="domcontentloaded")
    mark("load")
    if not numbers:
        dismiss_tour()  # прогрев заодно гасит тур: он пишется в хранилище
        return []  # страница загружена, ассеты в кэше браузера
    # Тур показывается по шагам и всплывает на каждом новом экране, поэтому
    # снимается перед каждым кликом, а не однажды.
    recover_if_crashed()
    dismiss_tour()
    open_parcel_dialog()
    dismiss_tour()
    fill_numbers(", ".join(numbers))
    page.get_by_role("button", name="Отправить").click()
    dismiss_tour()
    _glavapu_proceed(page, numbers)
    mark("parcel")
    deadline = time.monotonic() + _GLAVAPU_HEADLESS_TIMEOUT_MS / 1000.0
    last_shot = ""
    while True:
        rows = page.evaluate(_GLAVAPU_READ_ROWS_JS) or []
        # Готовность больше не держится на номере чужой строки. Кода 60 у
        # ГлавАПУ не стало — таблица перенумерована и кончается на 58 (живой
        # снимок ядра, 01.09.2026), — и мы ждали несуществующую строку девяносто
        # секунд, на каждом участке и у всех сразу. Номер строки источник меняет
        # когда захочет; ждём того, что от нумерации не зависит: строки, которые
        # мы читаем ПО ИМЕНАМ, на месте, и таблица перестала меняться.
        shot = _glavapu_table_shot(rows)
        # Готовность — свойство самой таблицы, а не наших ожиданий от неё:
        # она пришла, она не пуста и перестала меняться. Ни номера строки, ни
        # её количества здесь больше нет. Число строк было последним таким
        # ожиданием («не меньше шестидесяти»), и оно того же рода, что код 60:
        # источник вправе поменять его молча, а стоит это полутора минутами
        # ожидания на каждом участке у всех сразу.
        if rows and shot and shot == last_shot:
            missing = _glavapu_missing_controls(rows)
            if not missing:
                mark("table")
                return rows
            # Таблица устоялась, а строк, которые мы читаем, в ней нет. Ждать
            # больше нечего: она уже не изменится. Отказ сейчас и по имени
            # лучше полутора минут молчания и «истекло время».
            try:
                snapshot = page.evaluate(_GLAVAPU_SNAPSHOT_JS) or {}
            except Exception:  # страница ушла — снимка не будет, но отказ будет
                snapshot = {}
            raise GlavapuTableNotReady(
                _glavapu_not_ready_message(rows, _glavapu_with_network(snapshot)),
                snapshot)
        last_shot = shot
        if time.monotonic() > deadline:
            try:
                snapshot = page.evaluate(_GLAVAPU_SNAPSHOT_JS) or {}
            except Exception:  # страница ушла — снимка не будет, но отказ будет
                snapshot = {}
            snapshot = _glavapu_with_network(snapshot)
            raise GlavapuTableNotReady(
                _glavapu_not_ready_message(rows, snapshot), snapshot)
        page.wait_for_timeout(_GLAVAPU_HEADLESS_POLL_MS)


def _glavapu_browser_worker() -> None:
    """Единственный поток, владеющий браузером.

    Синхронный Playwright нельзя дёргать из чужого потока, а воркеров у нас
    два, и запросы приходят из пула FastAPI. Поэтому браузер держит один поток,
    расчёты приходят к нему очередью, и он же закрывает Chromium после простоя:
    держать 300–400 МБ ради расчёта, которого может не быть до вечера, дорого.
    """
    global _GLAVAPU_BROWSER_THREAD
    from playwright.sync_api import sync_playwright

    browser = page = None
    try:
        with sync_playwright() as playwright:
            while True:
                try:
                    job = _GLAVAPU_HEADLESS_JOBS.get(
                        timeout=_GLAVAPU_HEADLESS_IDLE_SECONDS or None)
                except queue.Empty:
                    with _GLAVAPU_BROWSER_LOCK:
                        if _GLAVAPU_HEADLESS_JOBS.empty():
                            _GLAVAPU_BROWSER_THREAD = None
                            return
                    continue
                numbers, area_ha, holder, done = job
                timings: dict[str, int] = {}
                try:
                    if browser is None or not browser.is_connected():
                        started = time.monotonic()
                        # Запуск общий с печатью PDF: Playwright при headless
                        # берёт отдельную сборку `chromium_headless_shell`, и
                        # если её в образе нет, падает не только ГлавАПУ —
                        # падает всё, что заводит браузер. Отказ при этом
                        # выглядел по-разному: там формулы, тут прежний PDF, —
                        # и обе поломки читались как «так работает».
                        browser = browser_launch.launch(
                            playwright, args=_GLAVAPU_HEADLESS_ARGS)
                        page = None
                        timings["launch"] = int((time.monotonic() - started) * 1000)
                    if page is None or page.is_closed():
                        page = browser.new_page()
                        page.set_default_timeout(_GLAVAPU_HEADLESS_TIMEOUT_MS)
                        page.route("**/*", _glavapu_block_junk)
                        # Слушатели вешаются один раз на страницу, а список
                        # чистится перед каждым расчётом: диагностика, а не журнал.
                        _glavapu_net_watch(page)
                    _glavapu_net_reset()
                    holder["rows"] = _glavapu_drive_page(page, numbers, area_ha, timings)
                    scenario = holder.get("scenario_params")
                    if scenario and numbers:
                        # Сценарий ставится на ТОМ ЖЕ экране расчёта, что
                        # только что открыт по участку: анализ территории
                        # (район, квартал, К1/К2) — его, а метры — наши.
                        holder["scenario_report"] = glavapu_scenario.apply_scenario(
                            page, scenario)
                        holder["scenario_rows"] = glavapu_scenario.read_rows(page)
                        holder["scenario_xlsx"] = glavapu_scenario.export_xlsx(
                            page, _GLAVAPU_HEADLESS_TIMEOUT_MS // 3)
                        timings["scenario"] = int(
                            holder["scenario_report"].get("ms") or 0)
                except Exception as exc:
                    # Снимок страницы прикладывается к ЛЮБОМУ отказу, а не
                    # только к тем, что мы предвидели: `snapshot: {}` у пробы
                    # означает «смотреть не на что», и именно так выглядел
                    # стек Playwright на недоступной кнопке.
                    if getattr(exc, "snapshot", None) is None and page is not None:
                        try:
                            exc.snapshot = page.evaluate(_GLAVAPU_SNAPSHOT_JS) or {}
                        except Exception:
                            pass
                    holder["error"] = exc
                    # Упавший прогон мог оставить страницу в неизвестном
                    # состоянии, а тихо считать на ней дальше — это чужой ТЭП
                    # под своим именем. Рвём браузер: следующий начнёт с нуля.
                    try:
                        if browser is not None:
                            browser.close()
                    except Exception:
                        pass
                    browser = page = None
                finally:
                    holder["timings"] = timings
                    done.set()
    finally:
        with _GLAVAPU_BROWSER_LOCK:
            if _GLAVAPU_BROWSER_THREAD is threading.current_thread():
                _GLAVAPU_BROWSER_THREAD = None
        try:
            if browser is not None:
                browser.close()
        except Exception:
            pass
        # Поток умер — ждущие расчёты обязаны узнать об этом сейчас, а не по
        # таймауту через три минуты: их место на серверных формулах.
        while True:
            try:
                _, _, holder, done = _GLAVAPU_HEADLESS_JOBS.get_nowait()
            except queue.Empty:
                break
            holder.setdefault("error", RuntimeError("поток браузера остановлен"))
            done.set()


def _glavapu_warm_up() -> None:
    """Поднимает браузер и прогревает страницу калькулятора заранее.

    Иначе первый расчёт после выкатки платит и за старт Chromium, и за полную
    загрузку ассетов ГлавАПУ — а первый расчёт всегда чей-то.
    """
    try:
        _glavapu_headless_rows([], 0.0)
        logging.info("glavapu warm-up done: браузер готов")
    except Exception as exc:
        # Нет Chromium, нет выхода к genplan.tech — расчёт не должен узнавать
        # об этом ценой полутора минут ожидания на первом же участке.
        _GLAVAPU_HEADLESS["last_error"] = (
            f"{datetime.now().isoformat(timespec='seconds')}: прогрев — {_error_location(exc)}")
        _glavapu_headless_failed()
        logging.warning("glavapu warm-up failed: %s", exc)


def _glavapu_headless_rows(numbers: list[str], area_ha: float) -> list[dict[str, Any]]:
    """Таблица ТЭП, снятая с настоящего калькулятора ГлавАПУ.

    Расчёт уходит потоку-владельцу браузера и ждёт его ответа. Ожидание в
    очереди конечно: не дождался — уходим на серверные формулы, а не висим.
    """
    return _glavapu_headless_run(numbers, area_ha).get("rows") or []


def _glavapu_headless_run(numbers: list[str], area_ha: float,
                          scenario_params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Прогон браузера: таблица участка и — если задан — наш сценарий поверх.

    Один путь для расчёта, пробы и сверки сценария: второй браузер или вторая
    очередь к той же странице разошлись бы с первой при первой же правке.
    """
    global _GLAVAPU_BROWSER_THREAD

    # Проверяется здесь, а не в потоке: без Playwright в образе поток умрёт
    # молча, и расчёт вместо мгновенного отката на формулы ждал бы ответа
    # три минуты.
    from playwright.sync_api import sync_playwright  # noqa: F401

    if not _GLAVAPU_HEADLESS_LOCK.acquire(timeout=_GLAVAPU_HEADLESS_QUEUE_SECONDS):
        _GLAVAPU_HEADLESS["waits"] += 1
        raise TimeoutError(
            f"браузер занят дольше {int(_GLAVAPU_HEADLESS_QUEUE_SECONDS)} с "
            "— расчёт уходит на серверные формулы")
    started = time.monotonic()
    try:
        holder: dict[str, Any] = {"scenario_params": scenario_params} if scenario_params else {}
        done = threading.Event()
        with _GLAVAPU_BROWSER_LOCK:
            if _GLAVAPU_BROWSER_THREAD is None or not _GLAVAPU_BROWSER_THREAD.is_alive():
                _GLAVAPU_BROWSER_THREAD = threading.Thread(
                    target=_glavapu_browser_worker, name="glavapu-browser", daemon=True)
                _GLAVAPU_BROWSER_THREAD.start()
            _GLAVAPU_HEADLESS_JOBS.put((list(numbers), float(area_ha), holder, done))
        # Сценарий — второй круг полей и выгрузка книги поверх расчёта участка.
        budget = _GLAVAPU_HEADLESS_TIMEOUT_MS / 1000.0 * (2 if scenario_params else 1) + 60.0
        if not done.wait(budget):
            raise TimeoutError("поток браузера не ответил — расчёт уходит на формулы")
        timings = dict(holder.get("timings") or {})
        timings["total"] = int((time.monotonic() - started) * 1000)
        _GLAVAPU_HEADLESS["last_ms"] = timings
        logging.info("glavapu headless timings: %s", timings)
        if holder.get("error") is not None:
            raise holder["error"]
        return holder
    finally:
        _GLAVAPU_HEADLESS_LOCK.release()


_GLAVAPU_DRIFT_CHECKS = [
    ("4", "население", 3.0, "abs"),
    ("10", "площадь квартир", 0.01, "rel"),
    ("30", "ДОО", 2.0, "abs"),
    ("31", "школа", 2.0, "abs"),
    ("32", "поликлиника", 2.0, "abs"),
    ("42.1", "постоянные машино-места", 2.0, "abs"),
    ("42.2", "гостевые машино-места", 2.0, "abs"),
    ("44", "плата за смену ВРИ", 0.01, "rel"),
    ("54", "компенсация ДОО", 0.01, "rel"),
    ("55", "компенсация школа", 0.01, "rel"),
    ("56", "компенсация поликлиника", 0.01, "rel"),
]
_GLAVAPU_FORMULA_DRIFT: dict[str, Any] = {"items": [], "checked_at": 0.0, "running": False}
# Сверка формул со штатным калькулятором стоит целого серверного расчёта: она
# заново спрашивает территорию у ГлавАПУ и собирает книгу ТЭП, чтобы сравнить
# одиннадцать чисел. Держать в этом человека, который ждёт свой ТЭП, незачем —
# дрейф методики появляется не чаще раза в квартал, а не раза в клик.
_GLAVAPU_DRIFT_INTERVAL_SECONDS = max(60.0, _env_float("GLAVAPU_DRIFT_INTERVAL_SECONDS", 3600.0))
_GLAVAPU_DRIFT_LOCK = threading.Lock()


def _glavapu_drift_in_background(rows: list[list[Any]], numbers: list[str]) -> None:
    """Ставит сверку формул в фон, но не чаще раза в интервал.

    Ошибка, ушедшая только в лог, — ошибка, которой нет, поэтому результат
    по-прежнему кричит в /status и в предупреждениях расчёта. Но кричать он
    может и со следующего расчёта: дрейф методики — это про квартал, а не про
    секунды ожидания.
    """
    if not numbers:
        return
    with _GLAVAPU_DRIFT_LOCK:
        if _GLAVAPU_FORMULA_DRIFT.get("running"):
            return
        last = float(_GLAVAPU_FORMULA_DRIFT.get("checked_at") or 0.0)
        if last and time.monotonic() - last < _GLAVAPU_DRIFT_INTERVAL_SECONDS:
            return
        _GLAVAPU_FORMULA_DRIFT["running"] = True

    def worker() -> None:
        try:
            drift = _glavapu_formula_drift(rows, numbers)
        except Exception as exc:
            logging.warning("glavapu drift check failed: %s", exc)
            drift = []
        else:
            if drift:
                _GLAVAPU_FORMULA_DRIFT.update(
                    items=drift, found_at=datetime.now(timezone.utc).isoformat(),
                    numbers=[str(n) for n in numbers])
                _TELEGRAM_RUNTIME["last_error"] = "Дрейф формул ГлавАПУ: " + "; ".join(drift[:4])
            elif _GLAVAPU_FORMULA_DRIFT.get("items"):
                # Формулы снова сходятся — снять флаг, чтобы Telegram не пугал зря.
                _GLAVAPU_FORMULA_DRIFT.update(items=[], found_at="", numbers=[])
        finally:
            with _GLAVAPU_DRIFT_LOCK:
                _GLAVAPU_FORMULA_DRIFT["checked_at"] = time.monotonic()
                _GLAVAPU_FORMULA_DRIFT["running"] = False

    threading.Thread(target=worker, name="glavapu-drift", daemon=True).start()


def _glavapu_formula_drift(rows: list[list[Any]], numbers: list[str]) -> list[str]:
    """Сравнивает собранную таблицу штатного калькулятора с серверными
    формулами по тем же кадастрам. Возвращает список расхождений."""
    if not numbers:
        return []
    quick = vri_tep_quick("msk", ", ".join(str(n) for n in numbers))
    server_rows = _xlsx_read_tables(quick["file"]).get("ТЭП") or []

    def as_map(items: list[list[Any]]) -> dict[str, float | None]:
        out: dict[str, float | None] = {}
        for row in items:
            if not row or len(row) < 4:
                continue
            code = str(row[0] or "").strip()
            if code:
                out[code] = _ru_number(str(row[3] or "").split("(")[0])
        return out

    browser, server = as_map(rows), as_map(server_rows)
    drift: list[str] = []
    for code, label, tolerance, kind in _GLAVAPU_DRIFT_CHECKS:
        b, s = browser.get(code), server.get(code)
        if not b or not s or b <= 0 or s <= 0:
            continue
        limit = tolerance if kind == "abs" else max(abs(b), abs(s)) * tolerance
        if abs(b - s) > limit:
            drift.append(f"{label}: калькулятор {b:g}, формулы {s:g}")
    return drift


# Один участок считают по многу раз подряд: поменяли цену — пересчитали,
# поменяли нарезку — пересчитали, и каждый раз заново поднимался браузер и
# заново считал ГлавАПУ. ТЭП участка за это время не меняется — меняются наши
# вводные. Ставки город индексирует поквартально, поэтому шесть часов памяти
# безопасны, а ждать минуту ради того же ответа — нет.
_GLAVAPU_TEP_CACHE_SECONDS = max(0.0, _env_float("GLAVAPU_TEP_CACHE_SECONDS", 21600.0))
# Запасной ответ помнится минутами, а не часами. Шесть часов — срок для расчёта
# штатного калькулятора: ТЭП участка за это время не меняется. Ответ формул —
# это «калькулятор был недоступен в ту секунду», и держать его наравне со
# штатным значит месяцами отдавать запасной расчёт после одного срыва: браузер
# уже починен, предохранитель снят через пять минут, а кэш всё ещё отвечает
# формулами.
_GLAVAPU_TEP_FALLBACK_CACHE_SECONDS = max(0.0, _env_float("GLAVAPU_TEP_FALLBACK_CACHE_SECONDS", 300.0))
_GLAVAPU_TEP_CACHE: dict[tuple[str, ...], tuple[float, dict[str, Any], bool]] = {}
_GLAVAPU_TEP_CACHE_LOCK = threading.Lock()
_GLAVAPU_TEP_CACHE_HITS = {"hits": 0}


def _glavapu_tep_cached(numbers: list[str],
                        want_calculator: bool = False) -> dict[str, Any] | None:
    """Запомненный ТЭП участка.

    `want_calculator` — «браузер сейчас на ходу»: тогда запасной ответ из памяти
    не отдаётся, иначе один срыв калькулятора обрекал участок на формулы до
    конца дня.
    """
    if _GLAVAPU_TEP_CACHE_SECONDS <= 0:
        return None
    key = tuple(sorted(str(x).strip() for x in numbers))
    with _GLAVAPU_TEP_CACHE_LOCK:
        item = _GLAVAPU_TEP_CACHE.get(key)
        if not item:
            return None
        stored_at, payload, is_fallback = item
        if is_fallback and want_calculator:
            return None
        limit = (_GLAVAPU_TEP_FALLBACK_CACHE_SECONDS if is_fallback
                 else _GLAVAPU_TEP_CACHE_SECONDS)
        if limit <= 0 or time.monotonic() - stored_at > limit:
            _GLAVAPU_TEP_CACHE.pop(key, None)
            return None
        _GLAVAPU_TEP_CACHE_HITS["hits"] += 1
    return copy.deepcopy(payload)


def _glavapu_tep_store(numbers: list[str], payload: dict[str, Any],
                       is_fallback: bool = False) -> None:
    if _GLAVAPU_TEP_CACHE_SECONDS <= 0 or not numbers:
        return
    key = tuple(sorted(str(x).strip() for x in numbers))
    with _GLAVAPU_TEP_CACHE_LOCK:
        if len(_GLAVAPU_TEP_CACHE) >= 64:
            oldest = min(_GLAVAPU_TEP_CACHE, key=lambda k: _GLAVAPU_TEP_CACHE[k][0])
            _GLAVAPU_TEP_CACHE.pop(oldest, None)
        _GLAVAPU_TEP_CACHE[key] = (time.monotonic(), copy.deepcopy(payload), is_fallback)


def _glavapu_headless_state() -> dict[str, Any]:
    """Почему расчёт идёт формулами — в самом ответе, а не только в логе.

    Браузер живёт на ядре, и с телефона его состояние никак не увидеть.
    «Ошибка, ушедшая только в лог, — это ошибка, которой нет»: причина отката
    должна доезжать до человека вместе с расчётом.
    """
    try:
        host = socket.gethostname()
    except Exception:
        host = "?"
    where = (f"пересылает на ядро, отвечает {host}"
             if _core_api_url("/cadastral/tep-server") else f"считает сам, {host}")
    if not _GLAVAPU_HEADLESS_ENABLED:
        return {"state": "выключен", "where": where,
                "hint": ("Штатный калькулятор запускает ядро. Нужны GLAVAPU_HEADLESS=1 "
                         "в .env ядра и образ с Chromium (docker compose build).")
                if where == "ядро" else
                ("Расчёт остался на Render — ядро не ответило или его адрес не задан. "
                 "Браузер живёт только на ядре.")}
    blocked = max(0, int(_GLAVAPU_HEADLESS_BLOCKED_UNTIL["at"] - time.monotonic()))
    if blocked:
        row = int(_GLAVAPU_HEADLESS_BLOCKED_UNTIL.get("row") or 0)
        return {"state": "предохранитель", "where": where, "blocked_for": blocked,
                "failures_in_row": row,
                "last_error": str(_GLAVAPU_HEADLESS.get("last_error") or ""),
                "hint": (f"Отказов подряд: {row}; следующая попытка через {blocked} с. "
                         "Пауза растёт, пока отказы идут подряд, и сбрасывается первым "
                         "удавшимся расчётом. Причина — в last_error.")}
    # «Готов» — это про браузер, а не про расчёт. На живом ответе ядра
    # (01.09.2026) стояло «готов» при `last_ok: ""` и четырёх откатах на
    # формулы: браузер поднимался исправно, а расчёт не удавался НИ РАЗУ, и
    # состояние это скрывало. Ответ на вопрос «работает ли связка» даёт
    # удавшийся расчёт, а не готовность запустить Chromium.
    return {"state": "готов", "where": where}


def _glavapu_state_with_history(state: dict[str, Any]) -> dict[str, Any]:
    """Готовность браузера и удача расчёта — разные ответы, и путать их нельзя."""
    if state.get("state") != "готов":
        return state
    runs = int(state.get("runs") or 0)
    fallbacks = int(state.get("fallbacks") or 0)
    if state.get("last_ok"):
        return state
    if runs or fallbacks:
        state["state"] = "браузер готов, расчёт не удавался"
        state["hint"] = (
            "Chromium поднимается, но ни один расчёт не дошёл до таблицы "
            f"(попыток {runs}, откатов на формулы {fallbacks}). Причина — в last_error; "
            "снимок страницы покажет /glavapu/probe?cad=<кадастровый номер>.")
    else:
        state["state"] = "браузер готов, расчётов ещё не было"
    return state


def _glavapu_health_file() -> Path:
    return Path(os.getenv("DEVELOPAID_DATA_DIR") or "data") / "glavapu-health.json"


def _glavapu_health_save() -> None:
    """Счётчики — на диск, потому что воркеров два.

    `_GLAVAPU_HEADLESS` живёт в памяти процесса, а `/glavapu/health` отвечает
    тот воркер, которому достался запрос. Расчёт уходил в один, состояние
    спрашивали у другого — и `runs: 0` читалось как «браузер не работает» при
    работающем браузере. Правило проекта прямое: всё, что должно пережить
    переход между запросами, дублируется на диск.
    """
    try:
        path = _glavapu_health_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        keep = {key: _GLAVAPU_HEADLESS.get(key)
                for key in ("last_ok", "last_error", "runs", "fallbacks")}
        # Берётся большее из своего и записанного: счётчик у каждого воркера
        # свой, а вопрос «считал ли калькулятор вообще» — про приложение. Файл
        # от этого только растёт и никогда не отменяет чужой удачный расчёт.
        seen = _glavapu_health_load()
        keep["runs"] = max(int(keep.get("runs") or 0), int(seen.get("runs") or 0))
        keep["fallbacks"] = max(int(keep.get("fallbacks") or 0),
                                int(seen.get("fallbacks") or 0))
        path.write_text(json.dumps(keep, ensure_ascii=False), encoding="utf-8")
    except Exception:
        # Диагностика не должна ронять расчёт: не записалось — не записалось.
        pass


def _glavapu_health_load() -> dict[str, Any]:
    try:
        raw = json.loads(_glavapu_health_file().read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


@app.get("/glavapu/probe")
def glavapu_probe(cad: str = "", area: float = 1.0) -> dict[str, Any]:
    """Что калькулятор ГлавАПУ отдаёт прямо сейчас — снимком, а не догадкой.

    Живой ответ с ядра: `state` бывает «готов», а `last_error` при этом говорит
    «не отдал таблицу (строк 79)» — то есть таблица пришла, и в ней семьдесят
    девять строк, а признана неготовой она по кодам. Какие коды пришли, знала
    только чужая страница; из песочницы genplan.tech не спросить.

    Проба гоняет ТОТ ЖЕ путь, что и расчёт, — второго пути наружу не заводим, —
    и на отказе отдаёт приложенный к нему снимок: адрес, таблицы страницы, их
    подписи и размеры, первые и последние строки, видимые кнопки.
    """
    numbers = [part.strip() for part in str(cad or "").split(",") if part.strip()]
    if not numbers:
        raise HTTPException(status_code=400,
                            detail="Нужен кадастровый номер: /glavapu/probe?cad=77:01:0004023:1000")
    started = time.monotonic()
    try:
        rows = _glavapu_headless_rows(numbers, float(area or 1.0))
    except (GlavapuTableNotReady, GlavapuParcelNotAccepted) as exc:
        return {"ok": False, "seconds": round(time.monotonic() - started, 1),
                "error": exc.public_message, "snapshot": exc.snapshot}
    except Exception as exc:  # noqa: BLE001
        # Снимок берётся и у чужого отказа: его прикладывает поток браузера.
        return {"ok": False, "seconds": round(time.monotonic() - started, 1),
                "error": _public_error(exc, "glavapu probe"),
                "snapshot": getattr(exc, "snapshot", None) or {}}
    codes = sorted({str(r.get("code") or "") for r in rows} - {""})
    return {"ok": True, "seconds": round(time.monotonic() - started, 1),
            "row_count": len(rows), "codes": codes[:40], "sample": rows[:6]}


@app.get("/glavapu/health")
def glavapu_health() -> dict[str, Any]:
    """Состояние штатного калькулятора ГлавАПУ — для /status бота.

    Браузер живёт на ядре, а /status спрашивают у бота на Render: без этого
    маршрута сбой связки с ГлавАПУ виден только в предупреждении карточки ТЭП,
    которое легко пролистать. Если задан адрес ядра — спрашиваем его, иначе
    отвечаем о себе; счётчики показывают, чем закончились прошлые расчёты.
    """
    url = _core_api_url("/glavapu/health")
    if url:
        try:
            request = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            return {"state": "ядро недоступно", "where": "Render",
                    "hint": ("Ядро не ответило на запрос состояния: "
                             + _public_error(exc, "glavapu health"))}
    state = dict(_glavapu_headless_state())
    state.update({key: _GLAVAPU_HEADLESS.get(key)
                  for key in ("last_ok", "last_error", "runs", "fallbacks")})
    # К своим счётчикам добавляется то, что записали остальные воркеры: их
    # память нам не видна, а вопрос «считал ли калькулятор» — про приложение
    # целиком, а не про тот процесс, которому достался этот запрос.
    shared = _glavapu_health_load()
    state["runs"] = max(int(state.get("runs") or 0), int(shared.get("runs") or 0))
    state["fallbacks"] = max(int(state.get("fallbacks") or 0),
                             int(shared.get("fallbacks") or 0))
    for key in ("last_ok", "last_error"):
        if not state.get(key) and shared.get(key):
            state[key] = shared[key]
    state["worker"] = os.getpid()
    return _glavapu_state_with_history(state)


# --- сверка нашего сценария со штатным калькулятором ГлавАПУ -----------------
# Выгрузка ГлавАПУ, которую мы забирали до сих пор, — калькулятор с ЕГО
# умолчаниями: 94/6 жилья и коммерции, плотность по таблице, нежильё целиком в
# 4.1. Сверить с ней свой сценарий нельзя — посчитано не то, что строим мы.
# Здесь калькулятору выставляются НАШИ параметры (`glavapu_scenario`), и его
# ответ стоит рядом с нашими числами. Роль ГлавАПУ — проверка: ничего в модели
# эти числа не заменяют.
#
# Браузер — тяжёлая работа на минуту и больше, а окно и бот ждать её не должны.
# Поэтому запрос ставит задание и сразу отвечает его состоянием; страница
# спрашивает тот же маршрут ещё раз, пока задание не кончится. Состояние —
# файл на диске по ключу набора параметров: воркеров два, и спросить о ходе
# расчёта можно не у того, кто его ведёт. Тот же файл — кэш: одинаковые
# параметры второй раз калькулятор не гоняют.
_GLAVAPU_SCENARIO_CACHE_SECONDS = max(0.0, _env_float("GLAVAPU_SCENARIO_CACHE_SECONDS", 21600.0))
# Отказ помнится минутами: он про «калькулятор не дался в ту минуту», а не
# про набор параметров.
_GLAVAPU_SCENARIO_ERROR_SECONDS = max(0.0, _env_float("GLAVAPU_SCENARIO_ERROR_SECONDS", 300.0))
# Задание, чей воркер умер (перезапуск), не должно числиться идущим вечно.
_GLAVAPU_SCENARIO_STALE_SECONDS = max(
    60.0, _GLAVAPU_HEADLESS_QUEUE_SECONDS + 3 * _GLAVAPU_HEADLESS_TIMEOUT_MS / 1000.0 + 60.0)
_GLAVAPU_SCENARIO_LOCK = threading.Lock()


class GlavapuScenarioRequest(BaseModel):
    """Сценарий проекта для сверки: те же вводные и ТЭП, что держит страница."""
    inputs: dict[str, Any] = {}
    tep: dict[str, Any] = {}
    cadastral_numbers: str | list[str] = ""
    # Только спросить состояние, не ставя задание (опрос страницы).
    poll: bool = False
    # Пересчитать, даже если ответ в кэше свежий.
    force: bool = False


def _glavapu_scenario_dir() -> Path:
    return Path(os.getenv("DEVELOPAID_DATA_DIR") or "data") / "glavapu-scenario"


_GLAVAPU_SCENARIO_KEY = re.compile(r"[0-9a-f]{8,40}")


def _glavapu_scenario_file(key: str) -> Path:
    """Файл задания. Ключ приходит и из адреса запроса, поэтому он обязан быть
    ровно хэшем `scenario_key`, а путь — лежать внутри каталога заданий."""
    key = str(key or "")
    if not _GLAVAPU_SCENARIO_KEY.fullmatch(key):
        raise ValueError("ключ сверки — шестнадцатеричный хэш набора параметров")
    base = os.path.normpath(os.path.abspath(_glavapu_scenario_dir()))
    path = os.path.normpath(os.path.join(base, key + ".json"))
    if not path.startswith(base + os.sep):
        raise ValueError("ключ сверки выводит за каталог заданий")
    return Path(path)


def _glavapu_scenario_load(key: str) -> dict[str, Any] | None:
    try:
        data = json.loads(_glavapu_scenario_file(key).read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _glavapu_scenario_save(key: str, record: dict[str, Any]) -> None:
    path = _glavapu_scenario_file(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(path)


def _glavapu_scenario_product(key: str) -> str:
    obj = _BY_KEY.get(key)
    return obj.product if obj is not None else key


def _glavapu_scenario_build(req: GlavapuScenarioRequest) -> dict[str, Any]:
    # Участок проекта — у одного владельца: номер, вписанный в поле, найденный
    # через ЕГРН или посчитанный «Получить ТЭП», равноправны. Прежде сверка
    # читала только расчёт ТЭП и отказывала проекту, у которого номер вписан.
    numbers = _parse_cadastral_numbers(req.cadastral_numbers) if req.cadastral_numbers else []
    if not numbers:
        numbers = _project_cadastral_numbers(req.inputs or {})
    return glavapu_scenario.build_scenario(
        req.inputs or {}, req.tep or {}, product_of=_glavapu_scenario_product, numbers=numbers)


def _glavapu_scenario_ours(inputs: dict[str, Any], tep: dict[str, Any],
                           scenario: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Наша сторона сверки — из тех же владельцев, что считают модель.

    Нормы мест, соцпотребности и МПТ — `tep_derived_norms` (её ответ подписан
    как наш расчёт по городским формулам), приобъектные места — `parking_demand`,
    плата за ВРИ — поле проекта. Своей формулы сверка не заводит: второй ответ
    на тот же вопрос был бы третьим мнением, а не проверкой.
    """
    inputs = inputs or {}
    tep = tep or {}
    params = scenario.get("params") or {}
    normalized = (inputs.get("_glavapu_import") or {}).get("normalized") or {}
    living = sum(n(tep.get(k) or {}, "gns") for k in glavapu_scenario.RESIDENTIAL_LIVING_KEYS)
    built_in = n(tep.get(glavapu_scenario.RESIDENTIAL_NONRES_KEY) or {}, "gns")
    social_gns = sum(n(tep.get(k) or {}, "gns") for k in glavapu_scenario.SOCIAL_KINDS)
    skip = (set(glavapu_scenario.RESIDENTIAL_LIVING_KEYS) | set(glavapu_scenario.SOCIAL_KINDS)
            | {glavapu_scenario.RESIDENTIAL_NONRES_KEY} | set(glavapu_scenario.NOT_SPP_KEYS))
    nonres_gns = sum(n(row, "gns") for key, row in tep.items()
                     if key not in skip and isinstance(row, dict))
    nonres_np = sum(n(row, "total_area") for key, row in tep.items()
                    if key not in skip and isinstance(row, dict))
    total = living + built_in + nonres_gns + social_gns
    area = float(params.get("area_ha") or 0.0)
    apartments = tep.get("apartments") or {}
    demand = parking_demand(inputs, tep)
    derived = tep_derived_norms(
        apartment_area_sqm=n(apartments, "saleable"),
        residential_living_spp_sqm=n(apartments, "gns"),
        nonresidential_np_sqm=nonres_np + n(tep.get("ground_commercial") or {}, "total_area"),
        k1=float(demand.get("k1") or 1.0), k2=float(demand.get("k2") or 1.0),
        zone_two=str(normalized.get("calculation_zone") or "").strip() == "2",
        apartment_count=n(apartments, "units"))
    tep_src = "ТЭП проекта, ГНС"
    norm_src = "наша норма (tep_derived_norms)"
    ours: dict[str, Any] = {
        "spp": {
            "total": (round(total / 1000.0, 3), tep_src + ": все наземные строки"),
            "residential_living": (round(living / 1000.0, 3), tep_src + ": «Квартиры» + «Кладовые»"),
            "built_in": (round(built_in / 1000.0, 3), tep_src + ": «Коммерция 1 этажа»"),
            "nonres": (round(nonres_gns / 1000.0, 3), tep_src + ": нежилые объекты"),
            "social": (round(social_gns / 1000.0, 3), tep_src + ": ДОО, СОШ, поликлиника"),
        },
        "social": {
            "population": (derived["population"], norm_src + ": площадь квартир / 33 м²"),
            "kindergarten": (derived["kindergarten_places"], norm_src),
            "school": (derived["school_places"], norm_src),
            "clinic": (derived["clinic_capacity"], norm_src),
        },
        "parking": {
            "permanent": (derived["parking_permanent"], norm_src + ": " + derived["parking_basis"]),
            "guest": (derived["parking_guest"], norm_src + ": десятая часть постоянных"),
            "attached": (int(demand.get("required_total") or 0),
                         "наша норма приобъектных (parking_demand, 945-ПП)"),
            "short_stop": (None, ""),
        },
        "mpt": (derived["jobs"], norm_src + f": НП нежилья / {derived['sqm_per_job']:g} м²"),
        "density": (round(total / 1000.0 / area, 3) if area > 0 else None,
                    "ТЭП проекта: СПП / площадь территории"),
    }
    vri_value: float | None = None
    vri_origin = ""
    if inputs.get("vri_required") in (False, 0, "0", "false"):
        vri_value, vri_origin = 0.0, "вводные проекта: смена ВРИ не требуется"
    elif inputs.get("land_rights_cost_mln") not in (None, ""):
        vri_value = float(n(inputs, "land_rights_cost_mln"))
        imported = ((inputs.get("_glavapu_import") or {}).get("mappings") or {}).get("inputs") or {}
        if ("land_rights_cost_mln" in imported
                and abs(float(imported.get("land_rights_cost_mln") or 0.0) - vri_value) < 0.001):
            vri_origin = ("вводные проекта — число из выгрузки ГлавАПУ с ЕГО умолчаниями, "
                          "не наш расчёт")
        else:
            vri_origin = "вводные проекта: land_rights_cost_mln"
    ours["vri_cost_mln"] = (vri_value, vri_origin)

    # Наша льгота по плате за ВРИ — одна сумма (доля или фиксированная) из
    # вводных, тем же `vri_relief`, что считает модель. Режим «нет» — это не
    # «льгота ноль», а «льгота не задана»: сверке не с чем сравнивать.
    # В КРТ льгота не задаётся, а считается по проекту (`vri_relief_basis`).
    relief_mode = vri_relief_basis(inputs)
    relief_value: float | None = None
    if vri_value is not None and relief_mode in ("percent", "amount", "krt_benefits"):
        relief_value = round(vri_relief({k: v for k, v in inputs.items()
                                         if k != "vri_transfer_offset_mln"},
                                        vri_value * 1_000_000, tep)[0] / 1_000_000, 3)
    ours["vri_relief"] = {"total": (relief_value,
                                    f"вводные проекта: vri_relief_mode = {relief_mode}"
                                    if relief_value is not None else "")}
    ours["vri_net_mln"] = ((round(vri_value - (relief_value or 0.0), 3), "плата проекта за вычетом нашей льготы")
                           if vri_value is not None else (None, ""))

    imported = ((inputs.get("_glavapu_import") or {}).get("mappings") or {}).get("inputs") or {}

    def from_import(key: str, value: float) -> bool:
        return (key in imported
                and abs(float(imported.get(key) or 0.0) - value) < 0.001)

    # Соцнагрузка деньгами: у проекта одна сумма; по объектам — справочно.
    comp_value: float | None = None
    comp_origin = ""
    if inputs.get("social_compensation_mln") not in (None, ""):
        comp_value = float(n(inputs, "social_compensation_mln"))
        comp_origin = ("вводные проекта — число из выгрузки ГлавАПУ с ЕГО умолчаниями"
                       if from_import("social_compensation_mln", comp_value)
                       else "вводные проекта: social_compensation_mln")
    ours["social_comp"] = {"total": (comp_value, comp_origin)}

    # Машино-места по ВРИ, все виды. Приобъектные — строки той же нормы
    # `parking_demand`, что дала общий итог (объект → ВРИ по карте
    # NONRES_VRI); постоянные и гостевые МКД — `tep_derived_norms`. Мест
    # остановки модель не считает — их строки остаются без нашей величины, и
    # «всего» по ВРИ не собирается: сумма без них была бы неполной, а не нашей.
    extra: dict[str, str] = {}
    by_vri: dict[str, list[Any]] = {}
    for row in demand.get("rows") or []:
        key = str(row.get("tep_key") or "")
        if key == glavapu_scenario.RESIDENTIAL_NONRES_KEY:
            kind = "built_in"
        else:
            target = glavapu_scenario.NONRES_VRI.get(_glavapu_scenario_product(key))
            if not target:
                continue
            kind = target[1]
        slot = by_vri.setdefault(kind, [0, []])
        slot[0] += int(row.get("required_spaces") or 0)
        slot[1].append(str(row.get("label") or key))
    ours["parking_vri"] = {f"{kind}.attached": (value, "наша норма (parking_demand): " + ", ".join(names))
                           for kind, (value, names) in by_vri.items()}
    ours["parking_vri"]["2_1_1.permanent"] = ours["parking"]["permanent"]
    ours["parking_vri"]["2_1_1.guest"] = ours["parking"]["guest"]
    for code in {kind.split(".", 1)[0] for kind in ours["parking_vri"]}:
        extra[f"parking_vri.{code}.total"] = (
            "«всего» по ВРИ у нас не собирается: мест кратковременной остановки модель "
            "не считает, и сумма без них была бы неполной — виды сверяются по строкам ниже")
        extra[f"parking_vri.{code}.short_stop"] = (
            "мест кратковременной остановки модель не считает: они не строятся в "
            "гараже (945-ПП п. 6.1.2), а потребность в них показана калькулятором")

    # Соцобъекты, которые поставил калькулятор, против строк ТЭП проекта.
    ours["social_obj"] = {}
    for key in glavapu_scenario.SOCIAL_KINDS:
        row = tep.get(key)
        if not isinstance(row, dict) or n(row, "gns") <= 0:
            continue
        label = glavapu_scenario._label(tep, key)
        ours["social_obj"][f"{key}.places"] = (n(row, "units") or None, f"ТЭП проекта: «{label}», места")
        ours["social_obj"][f"{key}.spp"] = (round(n(row, "gns") / 1000.0, 3), f"ТЭП проекта: «{label}», ГНС")
        if n(row, "total_area") > 0:
            ours["social_obj"][f"{key}.np"] = (round(n(row, "total_area") / 1000.0, 3),
                                               f"ТЭП проекта: «{label}», общая площадь")
        extra[f"social_obj.{key}.site"] = ("участка соцобъекта модель не ведёт — показано, "
                                             "сколько земли под него взял калькулятор")
        for field in ("spp", "np"):
            extra[f"social_obj.{key}.{field}"] = (
                f"калькулятор ставит типовое здание (лист «Социальные объекты»), у нас — «{label}» "
                "из ТЭП; площадь здания калькулятор берёт свою")
        extra[f"social_obj.{key}.places"] = (
            f"сценарий передаёт {glavapu_scenario._ru(n(row, 'units'))} мест «{label}», а "
            "калькулятор поставил своё типовое здание — его мощность из списка типовых, "
            "а не наше число (см. «Калькулятор не принял»)")

    # Обслуживание: своих норм на эти объекты у модели нет. Проверяется
    # запас — покрывает ли встроенная коммерция ННП торговли, быта, общепита,
    # культуры и городских служб, а ФОК — крытый спорт.
    built_in_np = n(tep.get(glavapu_scenario.RESIDENTIAL_NONRES_KEY) or {}, "total_area")
    ours["service"] = {"commerce_need": (
        round(built_in_np / 1000.0, 3) if built_in_np > 0 else None,
        "ТЭП проекта: «Коммерция 1 этажа», общая площадь")}
    sports = [(key, row) for key, row in tep.items() if isinstance(row, dict)
              and _glavapu_scenario_product(key) == "sports" and n(row, "total_area") > 0]
    if sports:
        ours["service"]["sport_indoor"] = (
            round(sum(n(row, "total_area") for _, row in sports) / 1000.0, 3),
            "ТЭП проекта: " + ", ".join(f"«{glavapu_scenario._label(tep, k)}»" for k, _ in sports))
    else:
        extra["service.sport_indoor"] = ("ФОК в ТЭП проекта нет — крытый спорт, который "
                                           "требует калькулятор, нечем покрыть")
    if built_in_np <= 0:
        extra["service.commerce_need"] = ("встроенной коммерции в ТЭП проекта нет — "
                                            "обслуживание квартала нечем покрыть")

    # Озеленённые территории ЖК (город: 5,0 м² на жителя) против площади
    # нашего двора — той, что считает благоустройство.
    yard_sqm, yard_basis = landscaping_area(inputs, tep)
    ours["territory"] = {"green_zhk": (round(yard_sqm / 10000.0, 4) if yard_sqm > 0 else None,
                                       "наш двор (landscaping_area): " + yard_basis)}
    extra["territory.green_zhk"] = (
        "наш двор — площадь благоустройства по ставке класса; город (2152-ПП) требует "
        "5,0 м² озеленённых территорий ЖК на жителя, из них 3,5 — насаждения"
        if yard_sqm > 0 else "площадь двора в проекте не посчитана: " + yard_basis)

    # Квартиры: всего и по размерам (если состав задан вводными).
    units = n(apartments, "units")
    ours["flats"] = {"total": (round(units) if units > 0 else None, "ТЭП проекта: «Квартиры», шт.")}
    mix = inputs.get("apartment_mix") if isinstance(inputs.get("apartment_mix"), dict) else {}
    for size in ("small", "medium", "large"):
        if mix.get(size) not in (None, ""):
            ours["flats"][size] = (n(mix, size), "вводные проекта: apartment_mix")
    average = n(apartments, "saleable") / units if units > 0 else 0.0
    extra["flats.total"] = ("калькулятор считает квартиры от населения (2,1 чел. на квартиру), "
                              "мы — штуками ТЭП")
    if not mix:
        for size in ("small", "medium", "large"):
            extra[f"flats.{size}"] = (
                "состава квартир по размерам в модели нет"
                + (f"; средняя квартира {average:,.1f} м²".replace(",", " ").replace(".", ",")
                   if average > 0 else ""))

    # Параметры территории: то, от чего считают наши нормы и плата.
    analysis_src = "выгрузка ГлавАПУ, принятая в проект"
    numbers = scenario.get("numbers") or []
    quarter = numbers[0].rsplit(":", 1)[0] if numbers and numbers[0].count(":") >= 3 else None
    zone = str(normalized.get("calculation_zone") or "").strip()
    zone_key = "2" if zone == "2" else "1"
    norms = SOCIAL_NORMS_PER_1000
    ours["params"] = {
        "k1": (float(demand.get("k1") or 0.0) or None,
               "наша норма приобъектных (parking_demand): "
               + str((demand.get("k_origin") or {}).get("k1") or "К1 вводных")),
        "k2": (float(demand.get("k2") or 0.0) or None,
               "наша норма приобъектных (parking_demand): "
               + str((demand.get("k_origin") or {}).get("k2") or "К2 вводных")),
        "district": (normalized.get("district") or None, analysis_src),
        "zone": (zone or None, analysis_src),
        "kindergarten_norm": (norms["kindergarten"][zone_key],
                              f"наша норма (SOCIAL_NORMS_PER_1000), зона {zone_key}"),
        "school_norm": (norms["school"][zone_key], f"наша норма (SOCIAL_NORMS_PER_1000), зона {zone_key}"),
        "quarter": (quarter, "кадастровые номера сценария"),
        "rent": (normalized.get("rent_coefficient"), analysis_src),
        "mpt_coef": (None, ""),
    }
    for use, value in (normalized.get("vri_upks_by_use") or {}).items():
        ours["params"][f"upks_{use}"] = (value, analysis_src)
    for use, value in (normalized.get("vri_base_costs_by_use") or {}).items():
        ours["params"][f"base_{use}"] = (value, analysis_src)
    if not zone:
        extra["params.zone"] = ("расчётной зоны в проекте нет — наша норма соцобъектов "
                                  "считает по зоне 1")
    for kind, key in (("district", "district"), ("rent", "rent_coefficient")):
        if normalized.get(key) in (None, ""):
            extra[f"params.{kind}"] = ("в проекте нет принятой выгрузки ГлавАПУ по участку "
                                       "— параметр квартала не задан")
    k_src = demand.get("k_origin") or {}
    extra["params.k1"] = ("наша норма приобъектных берёт К1 "
                          + (str(k_src.get("k1")) if k_src.get("k1") else
                             "вводных; не задан — верхний край 1,0")
                          + "; калькулятор — по участку (анализ ГлавАПУ)")
    extra["params.k2"] = ("К2 зависит от положения участка относительно ТТК: калькулятор "
                          "берёт своё (" + str(normalized.get("parking_k2_label") or "по анализу")
                          + "); наша норма — " + (str(k_src.get("k2")) if k_src.get("k2") else
                                                  "К2 вводных; не задан — верхний край 1,0"))

    reasons: dict[str, str] = {
        "parking.short_stop": ("в модели нет нормы мест кратковременной остановки: "
                               "они не строятся в гараже (945-ПП п. 6.1.2), сверка справочная"),
        "parking.attached": ("наша норма — от общей площади нежилья с К1 "
                             f"{float(demand.get('k1') or 0):g} и К2 {float(demand.get('k2') or 0):g}; "
                             "калькулятор считает по ВРИ, НП и К1/К2 своего квартала"),
        "mpt": (f"у модели {derived['sqm_per_job']:g} м² НП на рабочее место; "
                "калькулятор считает по ВРИ (лист «МПТ»)"),
        "parking.guest": ("гостевые — десятая часть постоянных и у нас, и у калькулятора: "
                          "расхождение идёт от постоянных мест"),
        "parking.permanent": ("наша норма: " + derived["parking_basis"]
                              + "; калькулятор — от своей площади квартир (строка 10)"),
    }
    relief_basis = ("калькулятор даёт льготу за МПТ сам: нежилые ВРИ выше порога × "
                    "коэффициент места (офисы и торговля вне ТТК 0,7, внутри 0; соцобъекты 0,3); "
                    "срезает только плату за МКД. Его Кзатр — база 2026 года 166,23078 ещё раз "
                    "× 1,2036 (= 166,23078 / 138,11132, переход с базы 2025 года) × индекс "
                    "квартала: на ~20% выше приказа, по которому считаем мы")
    reasons["vri_relief.total"] = (
        ("наша льгота — льготы проекта за МПТ и передачу квартир (в КРТ входят в оплату "
         "сами); " if relief_mode == "krt_benefits" else "наша льгота — доля или сумма из вводных; ")
        + relief_basis if relief_value is not None
        else "в проекте льгота по плате за ВРИ не задана (vri_relief_mode = «нет»); "
             + relief_basis + " — проверить основание (3135-ПП)")
    reasons["vri_net_mln"] = ("к оплате = до льгот − льгота; расхождение складывается из "
                              "двух строк выше" if vri_value is not None else
                              reasons.get("vri_cost_mln", ""))
    if comp_value is not None:
        reasons["social_comp.total"] = (
            ("наше число — выгрузка ГлавАПУ с его умолчаниями, а не наш сценарий; "
             if comp_origin.startswith("вводные проекта — число из выгрузки") else "")
            + "калькулятор считает компенсацию от дефицита мест по нашему сценарию: "
              "объект, построенный сверх потребности, компенсацию не требует, а его "
              "лишние места вычитаются из дефицита других объектов (итог не меньше нуля)")
    else:
        reasons["social_comp.total"] = ("в проекте не задана компенсация за соцобъекты "
                                        "(social_compensation_mln) — сравнить не с чем")
    for kind in ours["parking_vri"]:
        column = kind.rsplit(".", 1)[-1]
        reasons[f"parking_vri.{kind}"] = reasons["parking." + column]
    reasons.update(extra)
    garage = tep.get("underground_parking") or {}
    if n(garage, "units") > 0:
        reasons["parking.permanent"] += (
            f"; в подземном гараже модели {n(garage, 'units'):,.0f} мест".replace(",", " "))
    for item in scenario.get("not_sent") or []:
        if str(item.get("param") or "").startswith("nonres."):
            for kind in ("spp.nonres", "spp.total", "density"):
                reasons[kind] = (reasons.get(kind, "") + "; " if reasons.get(kind) else "") + item["reason"]
    for item in params.get("social") or []:
        gns_text = f"{item['spp_ths'] * 1000:,.0f}".replace(",", " ")
        line = (f"{item['label']}: калькулятор ставит типовой объект своей площади, "
                f"у нас ГНС {gns_text} м²")
        for kind in ("spp.social", "spp.total", "density"):
            reasons[kind] = (reasons.get(kind, "") + "; " if reasons.get(kind) else "") + line
    population = derived["population"]
    for kind in ("social.population", "social.kindergarten", "social.school", "social.clinic"):
        reasons.setdefault(kind, f"наша норма: население {population} = площадь квартир / 33 м²; "
                                 "калькулятор — от своей площади квартир (строка 10)")
    if vri_origin.startswith("вводные проекта — число из выгрузки"):
        reasons["vri_cost_mln"] = ("наше число — выгрузка ГлавАПУ с его умолчаниями, а не "
                                   "наш сценарий; расхождение показывает, сколько стоит "
                                   "сценарий по калькулятору")
    elif vri_value == 0.0 and vri_origin:
        reasons["vri_cost_mln"] = vri_origin
    elif vri_value is None:
        reasons["vri_cost_mln"] = ("в проекте не задана плата за смену ВРИ "
                                   "(land_rights_cost_mln) — сравнить не с чем")
    else:
        reasons.setdefault("vri_cost_mln", "плата проекта задана вводными, калькулятор считает "
                                           "её от СПП по ВРИ и УПКС квартала")
    return ours, reasons


def _glavapu_scenario_run(key: str, scenario: dict[str, Any]) -> None:
    """Задание браузера: выставить сценарий, забрать книгу, записать ответ."""
    started = time.monotonic()
    record = _glavapu_scenario_load(key) or {}
    record.update(state="running", started_at=datetime.now(timezone.utc).isoformat(),
                  worker=os.getpid())
    _glavapu_scenario_save(key, record)
    try:
        params = scenario["params"]
        holder = _glavapu_headless_run(scenario["numbers"], float(params["area_ha"]), params)
        data = holder.get("scenario_xlsx") or b""
        parsed = parse_glavapu_xlsx(data, "glavapu-scenario.xlsx") if data else {}
        side = glavapu_scenario.glavapu_side(parsed.get("normalized") or {},
                                             holder.get("scenario_rows") or {}, data)
        record.update(state="done", glavapu=side,
                      applied=holder.get("scenario_report") or {},
                      warnings=parsed.get("warnings") or [],
                      timings=holder.get("timings") or {})
        _GLAVAPU_HEADLESS["last_ok"] = datetime.now().isoformat(timespec="seconds")
    except (GlavapuTableNotReady, GlavapuParcelNotAccepted) as exc:
        record.update(state="error", error=exc.public_message,
                      where="калькулятор ГлавАПУ: расчёт участка до ввода сценария")
    except Exception as exc:  # noqa: BLE001 — отказ доходит до окна с местом
        record.update(state="error", error=_public_error(exc, "glavapu scenario"),
                      where=_error_location(exc))
    record["finished_at"] = datetime.now(timezone.utc).isoformat()
    record["seconds"] = round(time.monotonic() - started, 1)
    record["stored_at"] = time.time()
    _glavapu_scenario_save(key, record)


def _glavapu_project_region(inputs: dict[str, Any]) -> tuple[str, str]:
    """Регион проекта — поле «Регион» (`class_region`), то же правило, что
    `projectRegion` страницы. Кадастровый номер регион не задаёт: у Новой
    Москвы — Новомосковского и Троицкого округов (НАО, ТАО) — номера
    областные: 50:21, 50:26, 50:27."""
    return class_region(inputs), "поле «Регион» проекта"


def _glavapu_scenario_fresh(record: dict[str, Any] | None) -> bool:
    if not record:
        return False
    age = time.time() - float(record.get("stored_at") or 0.0)
    state = record.get("state")
    if state == "done":
        return age <= _GLAVAPU_SCENARIO_CACHE_SECONDS
    if state == "error":
        return age <= _GLAVAPU_SCENARIO_ERROR_SECONDS
    if state in ("queued", "running"):
        return age <= _GLAVAPU_SCENARIO_STALE_SECONDS
    return False


@app.post("/glavapu/scenario")
def glavapu_scenario_check(req: GlavapuScenarioRequest) -> dict[str, Any]:
    """Сверка «наше / ГлавАПУ»: ставит задание и отвечает его состоянием.

    Ответ сразу: `queued`/`running` — браузер работает, спросить ещё раз;
    `done` — числа калькулятора и сверка; `error`/`unavailable` — причина и
    место. Тяжёлая работа идёт в фоне, окно и бот её не ждут.
    """
    url = _core_api_url("/glavapu/scenario")
    if url:
        # Браузер живёт на ядре, как и для расчёта ТЭП.
        forwarded = _core_post(url, _core_forward_payload(req), 30.0)
        forwarded.setdefault("route", "ядро")
        return forwarded
    scenario = _glavapu_scenario_build(req)
    key = glavapu_scenario.scenario_key(scenario)
    ours, reasons = _glavapu_scenario_ours(req.inputs or {}, req.tep or {}, scenario)
    answer: dict[str, Any] = {"key": key, "role": glavapu_scenario.ROLE,
                              "scenario": scenario, "ours": ours}
    region, region_origin = _glavapu_project_region(req.inputs or {})
    if region != "msk":
        # Калькулятор ГлавАПУ — московский: в проекте области он не участвует
        # ни подстановкой, ни сверкой (владелец, 06.10.2026).
        answer.update(state="refused",
                      error="проект не московский — калькулятор ГлавАПУ в нём не участвует",
                      where=f"регион проекта: {region_origin}")
        return answer
    if scenario["problems"]:
        answer.update(state="refused", error="; ".join(scenario["problems"]),
                      where="сценарий проекта (наши вводные и ТЭП), до калькулятора")
        return answer
    if not scenario["numbers"]:
        normalized = ((req.inputs or {}).get("_glavapu_import") or {}).get("normalized") or {}
        quarter = str(normalized.get("cadastral_quarter") or "").strip()
        missing = (f"у проекта есть только кадастровый квартал {quarter}, а калькулятор "
                   "ГлавАПУ берёт номер участка (вида 77:05:0004001:1234), не квартал"
                   if quarter else
                   "у проекта нет кадастрового номера участка, а калькулятору он нужен, "
                   "чтобы взять район, квартал и коэффициенты")
        answer.update(state="refused",
                      error=missing + ". Впишите номер в поле «Участок» на вкладке вводных "
                                      "(блок «Автозагрузка исходных данных») и повторите",
                      where="участок проекта (_project_cadastral_numbers): поле участка, "
                            "поиск ЕГРН, расчёт ТЭП по номеру — номеров нет")
        return answer
    with _GLAVAPU_SCENARIO_LOCK:
        record = _glavapu_scenario_load(key)
        if req.force and record and record.get("state") in ("done", "error"):
            record = None
        if not _glavapu_scenario_fresh(record):
            record = None
            if not req.poll:
                if not _glavapu_headless_available():
                    state = _glavapu_headless_state()
                    answer.update(state="unavailable",
                                  error=f"штатный калькулятор: {state.get('state')}",
                                  where=str(state.get("where") or ""),
                                  hint=str(state.get("hint") or state.get("last_error") or ""))
                    return answer
                record = {"state": "queued", "stored_at": time.time(),
                          "queued_at": datetime.now(timezone.utc).isoformat()}
                _glavapu_scenario_save(key, record)
                threading.Thread(target=_glavapu_scenario_run, args=(key, scenario),
                                 name=f"glavapu-scenario-{key[:8]}", daemon=True).start()
    if record is None:
        answer.update(state="none", error="задание не найдено — запустите сверку")
        return answer
    answer.update({k: v for k, v in record.items() if k not in ("stored_at",)})
    if record.get("state") == "done":
        answer["comparison"] = glavapu_scenario.compare(
            ours, record.get("glavapu") or {}, reasons, record.get("applied"))
    return answer


@app.get("/glavapu/scenario/{key}")
def glavapu_scenario_state(key: str) -> dict[str, Any]:
    """Запись задания как есть — для оператора: что ставили, что принято, где отказ."""
    url = _core_api_url(f"/glavapu/scenario/{key}")
    if url:
        try:
            with urllib.request.urlopen(url, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=502,
                                detail="Ядро не ответило: " + _public_error(exc, "scenario state"))
    if not _GLAVAPU_SCENARIO_KEY.fullmatch(str(key or "")):
        raise HTTPException(status_code=400,
                            detail="Ключ сверки — шестнадцатеричный хэш из ответа /glavapu/scenario")
    record = _glavapu_scenario_load(key)
    if record is None:
        raise HTTPException(status_code=404, detail="Задания сверки с таким ключом нет")
    return record


def _cadastral_analysis_for(numbers: list[str],
                            supplied: dict[str, Any] | None) -> dict[str, Any]:
    """Территория запрошенных участков — присланная страницей или своя.

    Страница собирает территорию перед расчётом ТЭП и держит её в руках; тот же
    вопрос ГлавАПУ второй раз за один клик стоил внешнего запроса на ровном
    месте. Принимается присланная территория только тех участков, что запрошены:
    иначе ТЭП посчитался бы по чужим коэффициентам, выглядя безупречно.
    """
    if isinstance(supplied, dict):
        recognized = {str(x).strip() for x in (supplied.get("recognized") or [])}
        coefficients = supplied.get("coefficients") or {}
        area = float((supplied.get("territory") or {}).get("area_ha") or 0.0)
        if recognized == {str(x).strip() for x in numbers} and coefficients and area > 0:
            return supplied
    return analyze_cadastral_territory(
        CadastralAnalysisRequest(cadastral_numbers=numbers))


@app.post("/cadastral/tep-server")
def cadastral_tep_server(req: CadastralAnalysisRequest) -> dict[str, Any]:
    """ТЭП по формулам ГлавАПУ, посчитанный сервером.

    Штатный путь гоняет настоящий калькулятор в скрытом iframe браузера —
    Telegram WebView этого не тянет, и сбор падал по таймауту: сайт собирал
    ТЭП, мини-приложение нет. Формулы калькулятора сняты с его кода и
    сходятся с контрольными выгрузками до единицы, поэтому серверный расчёт —
    равноценная замена, а не суррогат."""
    numbers = _parse_cadastral_numbers(req.cadastral_numbers)
    request_started = time.monotonic()
    logging.info("tep-server rid=%s numbers=%s analysis=%s headless=%s",
                 req.request_id or "-", ", ".join(numbers),
                 "прислана" if req.cadastral_analysis else "нет",
                 "готов" if _glavapu_headless_available() else "недоступен")

    # Расчёт уходит на ядро — тем же путём, что и анализ территории. Браузер
    # для штатного калькулятора живёт там: на ядре свой образ, четыре гигабайта
    # и нет засыпания, а Render к тому же не наш Dockerfile. На самом ядре
    # адрес пуст, и пересылать некуда — там считаем.
    if _core_api_url("/cadastral/tep-server"):
        try:
            forwarded = _core_post(
                _core_api_url("/cadastral/tep-server"),
                _core_forward_payload(req),
                _MO_CALC_TIMEOUT_SECONDS,
            )
            logging.info("tep-server rid=%s ядро ответило за %.1f с",
                         req.request_id or "-", time.monotonic() - request_started)
            return forwarded
        except Exception as exc:
            # Ядро не ответило — считаем здесь формулами, как раньше.
            logging.warning("tep-server core forward failed: %s", exc)

    # Сначала — настоящий калькулятор. Формулы остаются фолбэком: копия
    # методики отстаёт от города на неизвестный срок, и это уже дважды
    # находил человек на скриншотах, а не мы.
    # Тот же участок, посчитанный настоящим калькулятором час назад, — это тот
    # же ТЭП. Браузер поднимать незачем.
    if _glavapu_headless_available() and numbers:
        # Браузер на ходу — запасной ответ из памяти не годится: он отвечал бы
        # за калькулятор, который снова работает.
        cached = _glavapu_tep_cached(numbers, want_calculator=True)
        if cached is not None:
            logging.info("tep-server rid=%s из кэша", req.request_id or "-")
            return cached

    if _glavapu_headless_available() and numbers:
        try:
            started = time.monotonic()
            analysis = _cadastral_analysis_for(numbers, req.cadastral_analysis)
            area = float((analysis.get("territory") or {}).get("area_ha") or 0.0)
            rows = _glavapu_headless_rows(numbers, area)
            imported = import_cadastral_tep(CadastralTepRequest(
                rows=rows, cadastral_analysis=analysis))
            _GLAVAPU_HEADLESS["runs"] += 1
            _GLAVAPU_HEADLESS["last_ok"] = datetime.now().isoformat(timespec="seconds")
            _GLAVAPU_HEADLESS["last_error"] = ""
            _GLAVAPU_HEADLESS_BLOCKED_UNTIL["at"] = 0.0
            # Удавшийся расчёт сбрасывает и лестницу: связка ожила, и следующий
            # одиночный срыв снова стоит пять минут, а не полчаса.
            _GLAVAPU_HEADLESS_BLOCKED_UNTIL["row"] = 0
            _glavapu_health_save()
            imported.setdefault("source", {}).update({
                "format": "Штатный калькулятор ГлавАПУ — серверный запуск",
                "cadastral_numbers": numbers,
                "calculated_at": date.today().isoformat(),
                "headless": {"state": "готов", "where": "ядро"},
            })
            logging.info("tep-server rid=%s готов за %.1f с",
                         req.request_id or "-", time.monotonic() - started)
            _glavapu_tep_store(numbers, imported)
            return imported
        except Exception as exc:
            _GLAVAPU_HEADLESS["fallbacks"] += 1
            # Первая строка сообщения Playwright называет виновника прямо:
            # «<div id="react-joyride-portal"> intercepts pointer events» —
            # без неё причина срыва читалась только из логов контейнера.
            _reason = str(exc).strip().splitlines()
            _GLAVAPU_HEADLESS["last_error"] = (
                f"{datetime.now().isoformat(timespec='seconds')}: {_error_location(exc)}"
                + (f" — {_reason[0][:200]}" if _reason else ""))
            _glavapu_health_save()
            _glavapu_headless_failed()
            logging.warning("glavapu headless failed, falling back for %ds: %s",
                            int(_GLAVAPU_HEADLESS_COOLDOWN_SECONDS), exc)

    # Формулы тоже помнятся: пока штатный калькулятор недоступен, повторный
    # расчёт того же участка не должен снова ходить к ГлавАПУ за территорией.
    cached_formulas = _glavapu_tep_cached(numbers) if numbers else None
    if cached_formulas is not None:
        logging.info("tep-server rid=%s формулы из кэша", req.request_id or "-")
        return cached_formulas

    # Территория для формул: присланная страницей идёт без сети вовсе. Если её
    # нет и спросить не у кого — не роняем расчёт, формулы спросят сами.
    formulas_analysis = None
    if numbers:
        try:
            formulas_analysis = _cadastral_analysis_for(numbers, req.cadastral_analysis)
        except Exception as exc:
            logging.info("tep-server: территорию для формул взять не удалось: %s", exc)
    quick = vri_tep_quick("msk", ", ".join(numbers), analysis=formulas_analysis)
    result = parse_glavapu_xlsx(quick["file"], quick["filename"])
    result["source"].update({
        "format": "Формулы калькулятора ГлавАПУ — серверный расчёт DevelopAid",
        "cadastral_numbers": numbers,
        "calculated_at": date.today().isoformat(),
    })
    headless_state = _glavapu_headless_state()
    result["source"]["headless"] = headless_state
    result["warnings"].insert(
        0,
        "ТЭП посчитан серверными формулами ГлавАПУ: штатный калькулятор "
        f"недоступен ({headless_state['state']}, {headless_state['where']}). "
        + str(headless_state.get("hint") or "")
        + " Формулы сняты с его кода и сходятся с контрольными выгрузками до "
        "единицы, но методику город меняет — расчёт штатного калькулятора имеет "
        "приоритет."
        # Текст срыва (первая строка Playwright и место в коде) в ответ
        # расчёта не кладётся: это внутренности сервера, и видит их любой,
        # кто считает ТЭП. Он лежит в состоянии связки — /glavapu/health и
        # /status бота, — и здесь сказано, где его смотреть.
        + (" Последняя ошибка запуска записана в состоянии связки: "
           "/glavapu/health (в боте — /status)."
           if _GLAVAPU_HEADLESS.get("last_error") else ""),
    )
    if _GLAVAPU_FORMULA_DRIFT["items"]:
        result["warnings"].insert(
            0,
            "ВНИМАНИЕ: серверные формулы разошлись со штатным калькулятором "
            "(" + "; ".join(_GLAVAPU_FORMULA_DRIFT["items"][:4]) + "). "
            "Методика ГлавАПУ могла измениться — сверьте расчёт на сайте.",
        )
    if numbers:
        _glavapu_tep_store(numbers, result, is_fallback=True)
    logging.info("tep-server rid=%s формулы за %.1f с", req.request_id or "-",
                 time.monotonic() - request_started)
    return result


def _glavapu_row_values(rows: list[list[Any]]) -> dict[str, str]:
    """Строки таблицы ТЭП как «код → значение». Читатель, а не счётчик."""
    values: dict[str, str] = {}
    for row in rows or []:
        if not row or len(row) < 4:
            continue
        code = str(row[0] or "").strip()
        if code:
            values[code] = str(row[3] or "").strip()
    return values


def vri_tep_moscow(query: str) -> dict[str, Any]:
    """Кнопка бота «Посчитать ВРИ и ТЭП» по Москве — тем же путём, что и сайт.

    Прежде кнопка звала `vri_tep_quick("msk", …)` напрямую. Путь к штатному
    калькулятору при этом существовал и работал: `/cadastral/tep-server` при
    заданном `MO_CALC_API_URL` пересылает запрос на ядро, там headless-Chromium
    гоняет калькулятор ГлавАПУ, а формулы включаются только при срыве браузера.
    Эндпоинт бот обходил — на Render браузера нет, и подпись «Методика: Формулы
    калькулятора ГлавАПУ» в файле значила не «сорвалось», а «иначе тут не
    бывает»: сайт и бот отвечали по одному участку разными числами, и оба
    выглядели верными. Четвёртый случай правила «модуль не заводит своего пути
    туда, где у сервиса уже есть общий».

    Карточка, файл и шаблон собираются ИЗ ТОЙ ЖЕ таблицы, которой посчитан
    ТЭП. Считать их рядом нельзя: два счёта одной величины однажды разойдутся.
    Калькулятор не ответил — возвращаются прежние формулы со своей карточкой и
    своим предупреждением; второй заход по территории при этом попадает в кэш
    участка, который сервер только что заполнил.
    """
    try:
        numbers = _parse_cadastral_numbers(query)
    except Exception:
        numbers = []
    if not numbers:
        # Не кадастровый номер — спрашивать калькулятор нечем. Отказ вернёт
        # прежний путь, своими словами: два разных отказа на одну причину
        # человек читает как две разные поломки.
        return vri_tep_quick("msk", query)
    try:
        served = cadastral_tep_server(CadastralAnalysisRequest(cadastral_numbers=query))
    except Exception as exc:
        logging.warning("бот: штатный расчёт ТЭП не удался (%s) — формулы", exc)
        return vri_tep_quick("msk", query)

    glavapu = served.get("glavapu") or {}
    rows = list(glavapu.get("rows") or [])
    if not glavapu.get("calculator") or not rows:
        return vri_tep_quick("msk", query)

    source = served.get("source") or {}
    method = str(source.get("format") or "Штатный калькулятор ГлавАПУ")
    values = _glavapu_row_values(rows)

    def num(code: str) -> float:
        return _ru_number(str(values.get(code, "")).split("(")[0]) or 0.0

    def fmt(value: Any, digits: int = 1) -> str:
        try:
            return f"{float(value):,.{digits}f}".replace(",", " ").replace(".", ",")
        except (TypeError, ValueError):
            return "—"

    area = num("1")
    spp = num("6") * 1000.0
    apartments_gns = num("7.1") * 1000.0
    commerce_gns = num("7.2") * 1000.0
    apartments = num("10") * 1000.0
    commerce_np = num("9.1.2") * 1000.0
    apartments_np = num("9.1.1") * 1000.0
    population, units = num("4"), num("5")
    dou, school = num("30"), num("31")
    clinic_adult, clinic_child = num("33"), num("34")
    compensation = num("54") + num("55") + num("56")
    permanent, guest, onsite = num("42.1"), num("42.2"), num("42.3")
    vri_mln = num("44")

    parameters = [list(row) for row in (glavapu.get("parameters") or [])]
    by_name = {str(row[0] or "").strip(): (row[1] if len(row) > 1 else "")
               for row in parameters if row}
    district = str(by_name.get("Район") or "")
    # Чем посчитано — часть ответа: подпись «Формулы калькулятора ГлавАПУ»
    # прежде стояла у любого файла бота и ни о чём не сообщала.
    parameters.append(["Методика", method, "—"])

    card = (
        "<b>ВРИ и ТЭП · Москва</b>\n"
        f"Участок: <code>{html.escape(str(query)[:80])}</code>\n"
        f"• площадь — {fmt(area, 4)} га · район — "
        f"{html.escape(district or '—')}\n"
        f"• СПП — {fmt(spp / 1000, 1)} тыс. м² · квартиры — {fmt(apartments, 0)} м²\n"
        f"• население — {fmt(population, 0)} чел. · квартир — {fmt(units, 0)}\n"
        f"• соцпотребность — ДОО {fmt(dou, 0)} мест, СОШ {fmt(school, 0)} мест, "
        f"поликлиники {fmt(clinic_adult, 0)}+{fmt(clinic_child, 0)} пос./см.\n"
        + (f"• <b>компенсация за соцобъекты — {fmt(compensation, 1)} млн ₽</b>\n"
           if compensation > 0 else "")
        + (f"• паркинг — {fmt(permanent + guest, 0)} м/м (постоянные "
           f"{fmt(permanent, 0)} + гостевые {fmt(guest, 0)}) · приобъектные "
           f"{fmt(onsite, 0)}\n" if permanent + guest + onsite > 0 else "")
        + (f"• <b>плата за смену ВРИ — {fmt(vri_mln, 1)} млн ₽</b>\n"
           if vri_mln > 0 else "")
        + f"<i>Считал {html.escape(method)}.</i>\n"
        + ("<i>Льготы по ВРИ (МПТ, передача жилья городу), аренда и МАИП — в "
           "мини-приложении: кнопка «Открыть и изменить расчёт».</i>\n")
    )

    workbook = _build_glavapu_xlsx_from_rows(rows, parameters)
    safe = re.sub(r"[^0-9A-Za-zА-Яа-я_-]+", "_", str(query))[:40] or "участок"
    today = date.today().isoformat()
    payload: dict[str, Any] = {
        "card": card, "file": workbook,
        "filename": f"ВРИ_ТЭП_{safe}_{today}.xlsx",
    }
    try:
        products: dict[str, dict[str, float]] = {
            "apartments": {"gns": apartments_gns, "total_area": apartments_np,
                           "saleable": apartments, "units": units},
            "ground_commercial": {"gns": commerce_gns, "total_area": commerce_np,
                                  "saleable": num("11") * 1000.0},
        }
        if permanent + guest > 0:
            products["underground_parking"] = {"units": permanent + guest}
        payload["template_file"] = _manual_tep_filled_template(
            str(query).strip()[:80] or "Участок",
            "Москва" + (f" · {district}" if district else ""),
            area, vri_mln, compensation, products)
        payload["template_filename"] = f"ТЭП_DevelopAid_{safe}_{today}.xlsx"
    except Exception as exc:
        _TELEGRAM_RUNTIME["last_error"] = "Шаблон ВРИ/ТЭП: " + _error_location(exc)
    return payload


@app.post("/cadastral/tep-from-calculator")
def import_cadastral_tep(req: CadastralTepRequest) -> dict[str, Any]:
    if not 30 <= len(req.rows) <= 150:
        raise HTTPException(status_code=400, detail="Калькулятор вернул неполную таблицу ТЭП")
    table_rows: list[list[Any]] = []
    for item in req.rows:
        code = str(item.get("code") or "").strip()[:20]
        name = str(item.get("name") or "").strip()[:300]
        unit = str(item.get("unit") or "").strip()[:80]
        value = str(item.get("value") or "").strip()[:120]
        if name and value:
            table_rows.append([code or None, name, unit, value])
    # Контроль полноты — по ИМЕНАМ строк, а не по их номерам. Кода 60 у ГлавАПУ
    # больше нет (живой снимок ядра, 01.09.2026): таблица перенумерована и
    # кончается на 58, а разбор и так читает её по именам. Номер чужой строки
    # означает только её место, и держаться за него — значит ломаться при
    # каждой перенумерации, молча и у всех сразу.
    missing = _glavapu_missing_controls(
        [{"name": row[1]} for row in table_rows])
    if missing:
        raise HTTPException(
            status_code=400,
            detail="Не все контрольные строки ТЭП получены из калькулятора: "
                   + ", ".join(missing))

    analysis = req.cadastral_analysis or {}
    territory = analysis.get("territory") or {}
    coefficients = analysis.get("coefficients") or {}
    parameters = [
        ["Район", territory.get("district") or ""],
        ["Административный округ", territory.get("administrative_district") or ""],
        ["Кадастровый квартал", territory.get("cadastral_quarter") or ""],
        ["Коэффициент аренды", coefficients.get("rent")],
        ["Коэффициент МПТ", coefficients.get("mpt_location")],
        # К1 и К2 приобъектной парковки приходят тем же ответом, что аренда и
        # УПКС, — и до полей не доезжали: расчёт нежилой парковки отказывался
        # «не заданы коэффициенты», а заполнить их было неоткуда, хотя город
        # их прислал. Какое из двух значений К2 взято, решает признак ТТК из
        # того же ответа: в августе оговорка «признак анализ не отдаёт» была
        # неверной, и приобъектные места считались по чужому числу.
        ["К1 — доступность рельсового каркаса", coefficients.get("rail")],
        ["К2 — деловая активность "
         + ("(внутри ТТК)" if bool(territory.get("inside_ttc")) else "(вне ТТК)"),
         coefficients.get("business_inside_ttc" if bool(territory.get("inside_ttc"))
                          else "business_outside_ttc")],
    ]
    numbers = analysis.get("recognized") or analysis.get("requested") or []
    safe_numbers = "_".join(str(number).replace(":", "-") for number in numbers[:3]) or "территория"
    filename = f"ГлавАПУ_{safe_numbers}.xlsx"
    workbook = _build_glavapu_xlsx_from_rows(table_rows, parameters)
    try:
        result = parse_glavapu_xlsx(workbook, filename)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Не удалось перенести ТЭП из калькулятора: {exc}") from exc
    result["source"].update({
        "format": "Калькулятор ТЭП ГлавАПУ — автоматическое получение",
        "cadastral_numbers": numbers,
        "calculated_at": date.today().isoformat(),
        "calculator_url": analysis.get("calculator_url") or "https://genplan.tech/calc/",
    })
    result.setdefault("notes", []).insert(
        0,
        "Показатели автоматически считаны из готовой таблицы genplan.tech.",
    )
    # Таблица, которой посчитан этот ТЭП, едет вместе с ним. Строит её только
    # калькулятор, и второй раз взять её неоткуда: кто соберёт по этому ответу
    # свою карточку или свой файл, обязан читать те же строки, а не считать
    # рядом свои. Строки — строки и None, поэтому переживают пересылку на ядро
    # и обратно.
    result["glavapu"] = {"rows": table_rows, "parameters": parameters,
                         "calculator": True}
    # Каждый успешный сбор штатного калькулятора — бесплатная сверка серверных
    # формул: разошлись — значит, ГлавАПУ поменял методику, и путь Telegram
    # начал бы врать. Ошибка, ушедшая только в лог, — ошибка, которой нет,
    # поэтому расхождение кричит здесь, в /status и в серверных ответах.
    _glavapu_drift_in_background(table_rows, [str(n) for n in numbers])
    if _GLAVAPU_FORMULA_DRIFT.get("items"):
        result["warnings"].insert(
            0,
            "ВНИМАНИЕ: серверные формулы DevelopAid разошлись со штатным "
            "калькулятором (" + "; ".join(_GLAVAPU_FORMULA_DRIFT["items"][:4]) + "). "
            "Методика ГлавАПУ могла измениться — расчёты Telegram и кнопки бота "
            "требуют сверки.",
        )
    return result

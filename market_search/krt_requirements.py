"""Requirements for a selected planned Moscow KRT project.

The catalogue card contains headline TEP.  Exact object-by-object duties live
in the project decision published by the Moscow Government.  This module keeps
the two evidence levels separate and never turns an unpublished fact into a
negative fact.
"""

from __future__ import annotations

import re
import io
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode


_SPACE = re.compile(r"\s+")
_MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[А-ЯA-ZЁ])")
_NUMBER_ONLY = re.compile(r"^\d+(?:[.,]\d+)?$")
_CADASTRAL = re.compile(r"\b\d{2}:\d{2}:\d{5,8}:\d+\b")
_OBJECT_ACTION = re.compile(
    r"\b(?:Снос\s*/\s*Реконструкция|Снос|Реконструкция|Сохранение)\b", re.I
)

MOS_SEARCH_URL = "https://www.mos.ru/aisearch/frontend/api/v1/search/documentcommon/"
MOS_DOCUMENT_URL = "https://www.mos.ru/api/documents/v2/frontend/json/ru/documents/{id}"
MOS_DOCUMENTS_URL = "https://www.mos.ru/api/documents/v2/frontend/json/ru/documents"
MOS_BASE_URL = "https://www.mos.ru"

_ADDRESS_TYPE = re.compile(
    r"(?iu)\b(?:ул(?:ица)?|пр-?кт|пр-?т|проспект|пр-?д|проезд|ш|шоссе)\b\.?,?"
)
_ADDRESS_HOLDING = re.compile(r"(?iu)\b(?:вл|владение)\b\.?")
_SEARCH_TOKEN = re.compile(r"[0-9A-Za-zА-Яа-яЁё]+")
_GENERIC_TOKENS = {
    "проект", "решения", "комплексном", "развитии", "территории", "территорий",
    "нежилой", "застройки", "города", "москвы", "москва", "расположенной",
    "расположенных", "адресу", "адресам", "г", "и", "в", "по",
}

_SECTIONS = {
    "description": "описание объекта",
    "existing": "что было построено",
    "planned": "что будет построено",
}

_CATEGORY_MARKERS = {
    "demolition": ("снос", "снес", "демонтаж", "демонтир", "ликвидац"),
    "resettlement": ("рассел", "пересел", "освобождени жил", "жилых помещений, подлежащ"),
    "reconstruction": ("реконструк", "реконструир"),
    "preservation": ("сохран", "остается", "остаётся"),
    "construction": (
        "постро", "возвед", "строительств", "создад", "размест", "появит",
        "детск", "школ", "поликлиник", "медицин", "спорт", "технопарк",
        "офис", "рынок", "торгов", "производствен", "паркинг", "дорог",
    ),
}

_META_PREFIXES = (
    "площадь, га:", "округ:", "район:", "функциональное назначение",
    "общий объем", "общий объём", "жилое назначение", "нежилое назначение",
    "общественно-деловое назначение", "прирост рабочих мест", "застройщик",
)


# --- Чьё это КРТ и не занято ли оно ------------------------------------------
#
# Два вопроса решают, можно ли в площадку войти вообще: для чего город её затеял
# и не назван ли уже тот, кто её берёт. «Надо добавлять то, что видно по
# открытым источникам, фильтр по нуждам города и возможно уже назначение
# оператора» (владелец, 31.08.2026).
#
# Признак ставится ТОЛЬКО вместе с цитатой из документа. Список слов — это
# поиск, а не утверждение: не нашлось — «не найдено», и это не то же самое, что
# «нет». Пустой результат проверки не значит «чисто» — то же правило, по
# которому молчащий НСПД не выдаётся за отсутствие ограничений.

# Вид КРТ по ст. 65 ГрК. Заголовок проекта решения называет его прямо: «о
# комплексном развитии территории нежилой застройки». Вид сам по себе не
# закрывает вход и балла не снижает — он отвечает на «чья это история» и
# годится фильтром.
# «Жилой застройки» лежит внутри «нежилой застройки» целиком, и поиск подстрокой
# читает вторую как первую — то же, что уже ловилось у нас в терминаторах
# заголовка. Поэтому образец, а не подстрока: у жилого вида стоит запрет на «не»
# перед ним.
_KRT_KINDS = (
    (re.compile(r"(?iu)не\s*жилой\s+застройки"), "нежилой застройки"),
    (re.compile(r"(?iu)незастроенной\s+территории"), "незастроенной территории"),
    (re.compile(r"(?iu)инициативе\s+правообладателей"), "по инициативе правообладателей"),
    (re.compile(r"(?iu)(?<!не)(?<!не\s)жилой\s+застройки"), "жилой застройки"),
)

# Городские нужды. Слова узкие намеренно: «расселение» и «аварийное» сюда не
# входят — обязательство расселить мы считаем отдельно, и оно есть у половины
# площадок. Признак, который срабатывает почти всегда, ничего не отделяет.
_CITY_NEEDS_MARKERS = (
    "реновац", "государственных нужд", "муниципальных нужд", "нужд города",
)

# Оператор. На карточке krt.mos.ru это строка «Застройщик» — она у нас была и
# отбрасывалась как служебная. В решении он появляется отдельными оборотами.
_OPERATOR_MARKERS = (
    "оператор комплексного развития", "лицо, заключившее договор",
    "определен победитель", "определён победитель",
    "заключен договор о комплексном развитии", "заключён договор о комплексном развитии",
)
_OPERATOR_FIELD = "застройщик"
_EMPTY_FIELD = {"", "—", "–", "-", "не определен", "не определён", "нет", "н/д"}


def _quotes(sentences: list[str], markers: tuple[str, ...]) -> list[str]:
    found = [line for line in sentences
             if any(marker in line.casefold() for marker in markers)]
    return list(dict.fromkeys(found))[:5]


def krt_kind(text: str) -> tuple[str, str]:
    """Вид КРТ и та строка, из которой он взят. Не опознан — две пустые."""
    flat = _SPACE.sub(" ", text or "")
    for pattern, name in _KRT_KINDS:
        found = pattern.search(flat)
        if found:
            start = max(0, found.start() - 120)
            return name, flat[start:found.end() + 40].strip()
    return "", ""


def decision_intent(text: str, title: str = "", card_fields: dict[str, str] | None = None,
                    probed: bool = True) -> dict[str, Any]:
    """Вид КРТ, городские нужды и оператор — словами источника, а не оценкой."""
    sentences = _decision_sentences(text) if text else []
    kind, kind_quote = krt_kind(title or "")
    if not kind:
        kind, kind_quote = krt_kind(text or "")
    fields = card_fields or {}
    operator_name = ""
    raw = _SPACE.sub(" ", str(fields.get(_OPERATOR_FIELD) or "")).strip()
    if raw.casefold() not in _EMPTY_FIELD:
        operator_name = raw
    quotes = _quotes(sentences, _OPERATOR_MARKERS)
    # Реновация — это тоже городские нужды (владелец, 31.08.2026), и КРТ ЖИЛОЙ
    # застройки — та же история: город расселяет жильцов по своей программе.
    # Вид КРТ поэтому не просто метка для фильтра, а сам по себе основание —
    # со своей цитатой, из заголовка решения, а не выданное за фразу документа.
    needs = _quotes(sentences, _CITY_NEEDS_MARKERS)
    if kind == "жилой застройки" and kind_quote:
        needs = list(dict.fromkeys([f"Вид КРТ — жилой застройки: {kind_quote}"] + needs))[:5]
    return {
        "probed": bool(probed and (sentences or title or fields)),
        # Читали ли САМ проект решения. Карточка — тоже документ, но городские
        # нужды в ней не пишут, и «не найдено в прочитанном документе» без этой
        # оговорки читалось бы как ответ решения, которого мы не открывали.
        "decision_read": bool(sentences),
        "kind": kind,
        "kind_quote": kind_quote[:300],
        "city_needs": needs,
        "operator_name": operator_name,
        "operator": quotes,
        # «Занята» — это когда назван тот, кто её берёт. Одного вида КРТ для
        # такого вывода мало, и цитаты без имени тоже: обе половины признака
        # видны читателю отдельно.
        "taken": bool(operator_name or quotes),
    }


def is_planned_project(project: dict[str, Any]) -> bool:
    return "планируем" in str(project.get("status") or "").casefold()


def decision_search_queries(project: dict[str, Any]) -> list[str]:
    """Queries accepted by mos.ru's official document search.

    Search is sensitive to address abbreviations.  The catalogue writes
    ``пр-кт, вл.``, while decision titles use ``влд.``; the compact variant is
    therefore tried first.  Only the selected card is searched.
    """
    raw = _SPACE.sub(" ", str(project.get("name") or "")).strip()

    def normalize(value: str) -> str:
        value = _ADDRESS_HOLDING.sub("влд", value)
        value = _ADDRESS_TYPE.sub(" ", value)
        value = re.sub(r"[«»()\[\],.;:]", " ", value)
        return _SPACE.sub(" ", value).strip()

    compact = normalize(raw)
    without_note = normalize(re.sub(r"\([^)]*\)", " ", raw))
    raw_plain = _SPACE.sub(" ", re.sub(r"[«»()\[\],.;:]", " ", raw)).strip()
    queries = [
        f"проект решения {compact}", f"проект решения {without_note}",
        compact, f"проект решения {raw_plain}",
    ]
    return list(dict.fromkeys(query for query in queries if len(query) >= 6))


def decision_search_urls(project: dict[str, Any]) -> list[str]:
    return [
        MOS_SEARCH_URL + "?" + urlencode({"q": query, "page": 1, "no_spellcheck": 1})
        for query in decision_search_queries(project)
    ]


def _tokens(value: str) -> set[str]:
    return {
        token.casefold() for token in _SEARCH_TOKEN.findall(value or "")
        if token.casefold() not in _GENERIC_TOKENS
    }


def select_project_decision(payload: Any, project: dict[str, Any]) -> dict[str, Any] | None:
    """Choose a search result only when its address matches the KRT card."""
    if not isinstance(payload, dict):
        return None
    project_tokens = _tokens(decision_search_queries(project)[0])
    project_numbers = {token for token in project_tokens if any(ch.isdigit() for ch in token)}
    best: tuple[float, dict[str, Any]] | None = None
    for raw in payload.get("results") or []:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "")
        low = title.casefold()
        if "проект решения" not in low or "комплексн" not in low or "развити" not in low:
            continue
        if str(raw.get("category") or "").casefold() not in {"дгп", ""}:
            continue
        candidate_tokens = _tokens(title)
        candidate_numbers = {token for token in candidate_tokens if any(ch.isdigit() for ch in token)}
        if project_numbers and not project_numbers.issubset(candidate_numbers):
            continue
        words = {token for token in project_tokens if token not in project_numbers and len(token) > 2}
        overlap = len(words & candidate_tokens)
        if words and overlap < min(2, len(words)):
            continue
        score = overlap * 10 + len(project_numbers & candidate_numbers) * 20
        score += float((raw.get("rank") or {}).get("total_rank") or 0) / 1_000_000
        if best is None or score > best[0]:
            best = (score, raw)
    return dict(best[1]) if best else None


def document_detail_url(document_id: int | str) -> str:
    return MOS_DOCUMENT_URL.format(id=str(document_id).strip())


def document_attachments_url(document_id: int | str, institution_id: int | str) -> str:
    params = {
        "filter": '{"id":%s,"institution_id":%s}' % (document_id, institution_id),
        "expand": "attachments,finding,categories",
    }
    return MOS_DOCUMENTS_URL + "?" + urlencode(params)


def select_pdf_attachment(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for item in payload.get("items") or []:
        for attachment in item.get("attachments") or []:
            url = str((attachment or {}).get("url") or "").strip()
            if url.casefold().split("?", 1)[0].endswith(".pdf"):
                return url if url.startswith("http") else MOS_BASE_URL + "/" + url.lstrip("/")
    return None


class _ReadableHTML(HTMLParser):
    """Small HTML-to-lines converter; headings are retained as Markdown."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._parts: list[str] = []
        self._heading = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"h1", "h2", "h3", "h4"}:
            self._flush()
            self._heading = int(tag[1])
        elif tag in {"p", "li", "div", "br", "tr"}:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in {"h1", "h2", "h3", "h4", "p", "li", "div", "tr"}:
            self._flush()

    def handle_data(self, data: str) -> None:
        value = _SPACE.sub(" ", data or " ").strip()
        if value:
            self._parts.append(value)

    def close(self) -> None:
        super().close()
        self._flush()

    def _flush(self) -> None:
        value = _SPACE.sub(" ", " ".join(self._parts)).strip()
        if value:
            prefix = "#" * self._heading + " " if self._heading else ""
            self.lines.append(prefix + value)
        self._parts = []
        self._heading = 0


def _plain_line(raw: str) -> str:
    text = _MARKDOWN_IMAGE.sub("", raw or "")
    text = _MARKDOWN_LINK.sub(r"\1", text)
    text = text.strip().lstrip("*>- ").strip().strip("*")
    return _SPACE.sub(" ", text).strip()


def _as_lines(document: str) -> list[str]:
    if re.search(r"<\s*(?:html|main|section|div|h[1-4])\b", document, re.I):
        parser = _ReadableHTML()
        parser.feed(document)
        parser.close()
        return parser.lines
    return [line.rstrip() for line in document.splitlines()]


def _sections(document: str) -> dict[str, list[str]]:
    out = {key: [] for key in _SECTIONS}
    current = ""
    for raw in _as_lines(document):
        heading = re.match(r"^#{1,4}\s+(.+)$", raw.strip())
        if heading:
            name = _plain_line(heading.group(1)).casefold()
            current = next((key for key, title in _SECTIONS.items() if title in name), "")
            continue
        if not current:
            continue
        text = _plain_line(raw)
        if not text or text.casefold().startswith(_META_PREFIXES):
            continue
        out[current].append(text)
    return out


def _meta_fields(document: str) -> dict[str, str]:
    """Служебные строки карточки — как пары «ключ: значение».

    Прежде они только отбрасывались: список `_META_PREFIXES` нужен был, чтобы
    ТЭП не попадали в перечень обязательств. Вместе с ними выбрасывался и
    «Застройщик» — то самое имя, по которому видно, что площадка уже занята.
    Строка при этом может стоять и до первого заголовка, поэтому идём по всему
    документу, а не по разделам.
    """
    out: dict[str, str] = {}
    for raw in _as_lines(document):
        text = _plain_line(re.sub(r"^#{1,4}\s+", "", raw.strip()))
        if ":" not in text:
            continue
        key, value = text.split(":", 1)
        key = key.strip().casefold()
        if not key or key in out:
            continue
        if any(key.startswith(prefix.rstrip(":").strip()) for prefix in _META_PREFIXES):
            out[key] = value.strip()
    return out


def _facts(lines: list[str]) -> list[str]:
    """Readable, deduplicated statements, including icon-style ``2 / школа`` pairs."""
    paired: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if _NUMBER_ONLY.fullmatch(line) and index + 1 < len(lines):
            label = lines[index + 1]
            if label and not _NUMBER_ONLY.fullmatch(label):
                paired.append(f"{line} {label}")
                index += 2
                continue
        paired.append(line)
        index += 1
    result: list[str] = []
    seen: set[str] = set()
    for paragraph in paired:
        for fact in _SENTENCE.split(paragraph):
            fact = _SPACE.sub(" ", fact).strip()
            if len(fact) < 5:
                continue
            key = fact.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(fact[:700])
    return result


def _matching(facts: list[str], category: str) -> list[str]:
    markers = _CATEGORY_MARKERS[category]
    return [fact for fact in facts if any(marker in fact.casefold() for marker in markers)]


def pdf_text(data: bytes) -> str:
    """Extract text from an official decision; scanned files fail explicitly."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - production dependency guard
        raise RuntimeError("Для чтения проекта решения нужен pypdf") from exc
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise RuntimeError(f"Не удалось прочитать PDF проекта решения: {exc}") from exc
    text = "\n".join(pages).strip()
    if not text:
        raise RuntimeError("PDF проекта решения не содержит распознаваемого текста")
    return text


def _decision_sentences(text: str) -> list[str]:
    flat = _SPACE.sub(" ", text.replace("\u00ad", "")).strip()
    return _facts(_SENTENCE.split(flat))


def _area_before_action(window: str) -> float | None:
    # The appendix column immediately before the action is building area.  Read
    # only after the last cadastral number so its components cannot become area.
    cadastral = list(_CADASTRAL.finditer(window))
    tail = window[cadastral[-1].end():] if cadastral else window[-220:]
    numbers = re.findall(r"(?<![:\d])([0-9][0-9 ]*(?:[,.][0-9]+)?)(?![:\d])", tail)
    if not numbers:
        return None
    try:
        return float(numbers[-1].replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def _object_actions(text: str) -> list[dict[str, Any]]:
    low = text.casefold()
    starts = [match.start() for match in re.finditer(
        r"перечень земельных участков и объектов капитального строительства", low
    )]
    appendix = text[starts[-1]:] if starts else text
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for match in _OBJECT_ACTION.finditer(appendix):
        before = appendix[max(0, match.start() - 1_400):match.start()]
        cadastral = _CADASTRAL.findall(before)
        if not cadastral:
            continue
        action_raw = _SPACE.sub(" ", match.group(0)).strip()
        action_low = action_raw.casefold().replace(" ", "")
        if "снос/реконструкция" in action_low:
            action = "Снос/реконструкция"
            category = "demolition_or_reconstruction"
        elif action_low == "снос":
            action, category = "Снос", "demolition"
        elif action_low == "реконструкция":
            action, category = "Реконструкция", "reconstruction"
        else:
            action, category = "Сохранение", "preservation"
        key = (cadastral[-1], category)
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "cadastral_number": cadastral[-1],
            "action": action,
            "category": category,
            "area_sqm": _area_before_action(before),
        })
    return result


_APPENDIX_MARKER = "перечень земельных участков и объектов капитального строительства"


def appendix_cadastral_numbers(text: str) -> dict[str, Any]:
    """Кадастровые номера из перечня участков и ОКС проекта решения.

    Перечень — единственное место, где документ называет СОСТАВ территории:
    участки и здания с номерами. Файл карты реестра несёт полигон не у каждой
    площадки (у Варшавского ш., вл. 37 его нет — 35 строк каталога из 268 в
    файле отсутствуют), и тогда контур собирается из участков ЕГРН по этим
    номерам. Участок от здания по номеру не отличить — это скажет ЕГРН, здесь
    номера отдаются как есть, в порядке документа, без повторов. Перечня нет —
    берутся номера всего текста, и источник назван: «в тексте», а не «в
    перечне», это разная уверенность.
    """
    low = text.casefold()
    starts = [match.start() for match in re.finditer(_APPENDIX_MARKER, low)]
    scope = text[starts[-1]:] if starts else text
    numbers = list(dict.fromkeys(_CADASTRAL.findall(scope)))
    if starts:
        source = "appendix"
    elif numbers:
        source = "text"
    else:
        source = "none"
    return {"numbers": numbers[:200], "source": source}


def _object_label(item: dict[str, Any]) -> str:
    area = item.get("area_sqm")
    area_text = ""
    if isinstance(area, (int, float)):
        area_text = f" · {area:,.1f} м²".replace(",", " ")
    return f"КН {item['cadastral_number']}{area_text} · {item['action']}"


# --- Что город назвал объектом сам -------------------------------------------
#
# Иногда решение о КРТ прямо требует конкретные ДОО и СОШ: «дошкольная
# образовательная организация на 250 мест» (владелец, 02.09.2026). Норматив
# тогда не спрашивают — требование документа сильнее нашей формулы, и подменять
# его расчётом значит показать своё число под именем города.
#
# Число берётся только из ТОГО ЖЕ предложения, где назван объект: «на 250 мест»
# строкой ниже — это машино-места, и приписанные садику они завысили бы его
# впятеро. Машино-места поэтому вырезаются до поиска, а не отсеиваются после.
_SOCIAL_KINDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Порядок значим: «дошкольн» содержит «школ» подстрокой — ровно тот случай,
    # что уже ловился у «нежилой застройки» внутри «жилой застройки». Садик
    # обязан проверяться первым, иначе каждый садик станет школой.
    # Аббревиатуры проверяются словом целиком: «доо» подстрокой найдётся внутри
    # соседнего слова и заведёт садик там, где его не называли.
    ("kindergarten", (r"дошкольн", r"детск\w*\s+сад", r"\bдо[оу]\b")),
    ("school", (r"общеобразоват", r"школ")),
    ("clinic", (r"поликлиник",)),
)
_SOCIAL_LABELS = {"kindergarten": "ДОО", "school": "СОШ", "clinic": "поликлиника"}
_MACHINE_PLACES = re.compile(r"(?iu)машино-?\s*мест\w*")
_PLACES_RE = re.compile(r"(?iu)(?<![\d.,])(\d[\d  ]*)\s*(?:мест|учащ|воспитанник)")
_VISITS_RE = re.compile(r"(?iu)(?<![\d.,])(\d[\d  ]*)\s*посещени")
_SOCIAL_AREA_RE = re.compile(
    r"(?iu)(?<![\d.,])(\d[\d  ]*(?:[.,]\d+)?)\s*(?:кв\.?\s*м|м2|м²)")


def _social_number(raw: str | None) -> float | None:
    if not raw:
        return None
    cleaned = raw.replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if value > 0 else None


def social_objects_from_decision(sentences: Any) -> list[dict[str, Any]]:
    """Соцобъекты, названные самим решением, с цитатой при каждом.

    Пустой список — это «в прочитанном требования нет», а не «город его не
    предъявил»: решение могло не читаться вовсе. Отличать одно от другого
    обязан вызывающий, у него для этого есть `decision_available`.
    """
    found: list[dict[str, Any]] = []
    for raw in list(sentences or [])[:60]:
        sentence = _SPACE.sub(" ", str(raw or "")).strip()
        if len(sentence) < 12:
            continue
        low = sentence.casefold()
        kind = next(
            (name for name, markers in _SOCIAL_KINDS
             if any(re.search(marker, low) for marker in markers)),
            None,
        )
        if kind is None:
            continue
        countable = _MACHINE_PLACES.sub(" ", sentence)
        places = None
        if kind == "clinic":
            visits = _VISITS_RE.search(countable)
            places = _social_number(visits.group(1)) if visits else None
        if places is None:
            match = _PLACES_RE.search(countable)
            places = _social_number(match.group(1)) if match else None
        area = _SOCIAL_AREA_RE.search(countable)
        found.append({
            "kind": kind,
            "label": _SOCIAL_LABELS[kind],
            "places": places,
            "area_sqm": _social_number(area.group(1)) if area else None,
            "quote": sentence[:400],
        })
    return found


# Метры, уходящие городу по Программе реновации. Признак «в документе сказано о
# городских нуждах» отвечал только «да», а решение обычно называет и объём:
# на Задонском проезде это 15 100 м² из 150 940 предельной жилой СПП — десятая
# часть, а балл снижался на четверть (владелец, 03.09.2026: «не смущает, что
# фонд реновации забирает 15 тысяч из 150 000? значит остальное рыночный
# объём»). Доля меряется, а не оценивается на глаз.
_RENOVATION_MARKERS = ("программ", "реновац")
# Оборот, в котором стоит объём: «…для реализации Программы реновации … – 15 100
# кв.м» либо «площадью не менее 15 100 кв.м в целях реализации Программы
# реновации». Само слово ищется без пробельных артефактов PDF: в живом решении
# по 5-му Верхнему Михайловскому стоит «объекты жило го назначения» и «объектов
# кап итального строительства» — совпадение по целым словам там не сработало бы.
_RENOVATION_CLAUSE = re.compile(r"(?iu)программ\w*\s+реновац\w*")
_RENOVATION_AREA = re.compile(
    r"(?iu)(?<![\d.,])(\d[\d  ]*(?:[.,]\d+)?)\s*(?:кв\.?\s*м|м2|м²)")
# Оборот кончается точкой с запятой списка или концом предложения: перечень
# зоны идёт «- объекты жилого назначения – H кв.м, в том числе для реализации
# Программы реновации – R кв.м; - объекты общественно-делового назначения – …».
_CLAUSE_SPLIT = re.compile(r"[;\n]")


def _renovation_clause(clause: str) -> dict[str, Any] | None:
    """Объём реновации и парная ему площадь жилья в ОДНОМ обороте.

    Возвращает `None`, если оборот не про реновацию или числа в нём нет.
    """
    mark = _RENOVATION_CLAUSE.search(clause)
    if not mark:
        return None
    after = _RENOVATION_AREA.search(clause, mark.end())
    if after:
        # Форма ТЭП: «жилого назначения – H кв.м, в том числе для реализации
        # Программы реновации – R кв.м». H — последняя площадь ДО оборота, и
        # она нужна не для расчёта, а для самопроверки: сумма H по зонам
        # обязана сойтись с жильём площадки, иначе перечень зон прочитан не
        # весь и сумме R доверять нельзя.
        before = list(_RENOVATION_AREA.finditer(clause[:mark.start()]))
        return {
            "kind": "tep",
            "area_sqm": _social_number(after.group(1)),
            "housing_sqm": _social_number(before[-1].group(1)) if before else None,
        }
    before = list(_RENOVATION_AREA.finditer(clause[:mark.start()]))
    if before:
        # Форма обязательства: «площадью не менее R кв.м в целях реализации
        # Программы реновации». Здесь число ДО оборота — это сам объём.
        return {"kind": "duty", "area_sqm": _social_number(before[-1].group(1)),
                "housing_sqm": None}
    return None


def renovation_volume(sentences: Any) -> dict[str, Any]:
    """Сколько метров решение отдаёт Программе реновации — и чем это сказано.

    Ответов три, и они разные: назван объём, сказано о реновации без объёма,
    не сказано ничего. Второй нельзя показывать ни первым, ни третьим: «доля
    неизвестна» — это не «доли нет» и не «забирают всё».

    Число берётся из ОБОРОТА, который называет программу, а не наибольшее в
    предложении. Прежняя версия брала максимум, и на Задонском проезде это
    давало 173 200 м² — предельную СПП всей площадки — вместо 15 100 м²
    реновации: доля выходила 100% вместо 10%, и модель отменяла ВСЮ выручку
    жилья. Соседнее решение (5-й Верхний Михайловский) ловилось тем же
    способом: 87 690 м² итога зоны вместо 85 580 м² её реновации.

    Зоны — части, и они складываются: у 5-го Верхнего Михайловского зона 1
    отдаёт 9 600 м², зона 2 — 85 580, вместе ровно 95 180 м² жилья каталога.
    Обязательственные обороты повторяют те же числа другими словами, поэтому в
    сумму идут только обороты ТЭП; форма обязательства работает, лишь когда
    оборотов ТЭП не нашлось вовсе, и тогда объём берётся один — сложить
    повторы и части, не различая их, значит удвоить объём.
    """
    mentioned = False
    quote = ""
    tep: list[dict[str, Any]] = []
    duty: list[dict[str, Any]] = []
    for raw in list(sentences or [])[:200]:
        sentence = _SPACE.sub(" ", str(raw or "")).strip()
        low = sentence.casefold()
        if not all(mark in low for mark in _RENOVATION_MARKERS):
            continue
        mentioned = True
        if not quote:
            quote = sentence[:400]
        for clause in _CLAUSE_SPLIT.split(sentence):
            found = _renovation_clause(clause)
            if not found or found["area_sqm"] is None:
                continue
            (tep if found["kind"] == "tep" else duty).append(found)
            if found["kind"] == "tep":
                quote = sentence[:400]
    parts = tep or duty[:1]
    area = sum(one["area_sqm"] for one in parts) if parts else None
    housing = [one["housing_sqm"] for one in parts if one["housing_sqm"] is not None]
    return {
        "mentioned": mentioned,
        "area_sqm": area,
        # Сумма парных площадей жилья: самопроверка полноты перечня зон.
        # Её отсутствие — не ошибка, а «сверить нечем», и вызывающий обязан
        # отличать одно от другого.
        "housing_sqm": sum(housing) if housing else None,
        "zones": len(parts),
        "basis": ("zone_programme_clause" if tep
                  else ("duty_clause" if duty else "mentioned_without_volume")),
        "quote": quote,
    }


# Объёмы, объявленные решением. Карточка каталога сама с собой не сходится: на
# Варшавском ш., вл. 37 она даёт 229 490 жилья и 52 510 нежилого при заявленных
# 443 700 всего. Решение сходится до метра — 229 490 + 214 210 = 443 700, — и
# нежилого в нём вчетверо больше карточного. Читать надо документ.
_VOLUME_FRAME = (r"суммарн", r"поэтажн")
# Тире перечня и тире значения выглядят одинаково: «– объектов жилого» и
# «стен – 443 700 кв. м». Разделяет то, что стоит следом: у перечня слово, у
# значения цифра. Прежний набор `[;\n]|-\s` не знал ни `–`, ни `—` — то же
# место, где мы уже спотыкались на ASCII-дефисе в именах ЖК, — и на
# Малахитовой итог зоны 187 550 читался как объём жилья.
_VOLUME_SPLIT = re.compile(r"[;\n]|(?<=\s)[-–—]\s+(?=\D)")
_VOLUME_KINDS = (
    ("business_sqm", (r"обществен\w*[\s-]*делов",)),
    ("utility_sqm", (r"коммунальн",)),
    ("nonresidential_sqm", (r"нежило\s*го",)),
    ("housing_sqm", (r"жило\s*го",)),
)


def _volume_roots(low: str, *roots: str) -> bool:
    return all(re.search(root, low) for root in roots)


def programme_volumes(sentences: Any) -> dict[str, Any]:
    """Что решение объявляет объёмом — по видам назначения и по зонам.

    Число берётся из оборота, который его называет, а не наибольшее в
    предложении: это уже стоило нам платы за ВРИ и доли реновации. И оборот
    засчитывается только внутри рамки «суммарная поэтажная площадь» — без неё
    «объект коммунального назначения (общественный туалет) площадью 90 кв. м»
    на Левобережной читался как минимальный объём коммунальной застройки:
    слово совпало, а вид утверждения — нет.

    Зоны складываются, как у реновации. Полнота прочитанного проверяется
    самим документом: слагаемые обязаны сойтись с его же итогом. Не сошлись —
    перечень прочитан не весь, и числам из него верить нельзя; это `closes`,
    и оно отличает «прочитали» от «прочитали не всё».
    """
    out: dict[str, Any] = {}
    quotes: dict[str, str] = {}
    zones = 0

    def add(key: str, value: float, quote: str) -> None:
        out[key] = float(out.get(key, 0.0)) + value
        quotes.setdefault(key, quote)

    for raw in list(sentences or [])[:60]:
        sentence = _SPACE.sub(" ", str(raw or "")).strip()
        low = sentence.casefold()
        if not _volume_roots(low, *_VOLUME_FRAME):
            continue
        clauses = _VOLUME_SPLIT.split(sentence)
        head, rest = clauses[0], clauses[1:]
        if ("включа" in low or "в том числе" in low) and rest:
            found = _RENOVATION_AREA.search(head)
            if found:
                zones += 1
                add("total_sqm", _social_number(found.group(1)), head.strip()[:200])
        elif not rest:
            # Отдельное предложение об одном виде («Предельная (минимальная)
            # СПП объектов коммунального… назначения – N кв. м») итогом зоны
            # не является и в сумму слагаемых не идёт.
            rest = [sentence]
        for clause in rest:
            low_clause = clause.casefold()
            found = _RENOVATION_AREA.search(clause)
            if not found:
                continue
            for key, roots in _VOLUME_KINDS:
                if not _volume_roots(low_clause, *roots):
                    continue
                # «нежилого» содержит «жилого»: чей это оборот, решает более
                # точное совпадение, иначе нежилое станет жильём.
                if key == "housing_sqm" and re.search(r"нежило\s*го", low_clause):
                    continue
                add(key, _social_number(found.group(1)), clause.strip()[:200])
                break
    total = out.get("total_sqm")
    parts = sum(float(out.get(key) or 0.0)
                for key in ("housing_sqm", "nonresidential_sqm", "business_sqm"))
    out["zones"] = zones
    out["closes"] = None if not (total and parts) else abs(parts - float(total)) <= 1.0
    out["quotes"] = quotes
    return out


def _construction_parameters(text: str) -> list[str]:
    low = text.casefold()
    marker = low.find("предельные параметры разрешенного строительства")
    scope = text[marker:] if marker >= 0 else text
    appendix = scope.casefold().find("перечень земельных участков")
    if appendix >= 0:
        scope = scope[:appendix]
    zones = list(re.finditer(
        r"Территориальная\s+зона\s+№?\s*(\d+)(?:\s*\(([^)]+)\))?", scope, re.I
    ))
    result: list[str] = []

    def useful(sentence: str) -> bool:
        low_sentence = sentence.casefold()
        return (
            "предельн" in low_sentence and "площад" in low_sentence
            and any(value in low_sentence for value in (
                "нежил", "общественно-делов", "социаль", "производствен"
            ))
        )

    if zones:
        for index, zone in enumerate(zones):
            end = zones[index + 1].start() if index + 1 < len(zones) else len(scope)
            prefix = f"Зона {zone.group(1)}"
            if zone.group(2):
                prefix += f" ({_SPACE.sub(' ', zone.group(2)).strip()})"
            for sentence in _decision_sentences(scope[zone.end():end]):
                if useful(sentence):
                    result.append(f"{prefix}: {sentence[:800]}")
    else:
        result.extend(sentence[:900] for sentence in _decision_sentences(scope) if useful(sentence))
    return list(dict.fromkeys(result))[:20]


def parse_decision_requirements(text: str, title: str = "") -> dict[str, Any]:
    """Extract duties explicitly present in a project-decision PDF."""
    sentences = _decision_sentences(text)
    permitted_uses = []
    for match in re.finditer(
        r"(?m)^\s*(\d+(?:\.\d+){1,2})\s*[–—-]\s*([^.;\n]{3,120})[.;]", text
    ):
        label = _SPACE.sub(" ", match.group(2)).strip()
        permitted_uses.append(f"{match.group(1)} · {label[:100]}")
    construction = _construction_parameters(text)
    deadlines: list[str] = []
    resettlement: list[str] = []
    for sentence in sentences:
        low = sentence.casefold()
        if "предельный срок реализации" in low:
            deadlines.append(sentence[:900])
        if any(marker in low for marker in _CATEGORY_MARKERS["resettlement"] + ("изъят",)):
            resettlement.append(sentence[:900])
        if any(marker in low for marker in (
            "обеспечить строительство", "предусмотреть строительство",
            "разместить объект", "строительство объект",
        )):
            construction.append(sentence[:900])

    actions = _object_actions(text)
    parcels = appendix_cadastral_numbers(text)
    grouped = {
        category: [_object_label(item) for item in actions if item["category"] == category]
        for category in (
            "demolition", "demolition_or_reconstruction", "reconstruction", "preservation"
        )
    }
    return {
        "intent": decision_intent(text, title=title),
        # Объём городских нужд измеряется, а не подразумевается: признак без
        # доли снижал балл на четверть при десятой части жилья.
        "renovation": renovation_volume(sentences),
        "permitted_uses": list(dict.fromkeys(permitted_uses))[:30],
        "construction": list(dict.fromkeys(construction))[:20],
        # Объём решения — числом, а не пересказом: карточка каталога сама с
        # собой не сходится, а решение сходится, и нежилого в нём вчетверо
        # больше карточного.
        "volumes": programme_volumes(construction),
        "deadlines": list(dict.fromkeys(deadlines))[:5],
        "resettlement": list(dict.fromkeys(resettlement))[:20],
        "object_actions": actions[:100],
        # Состав территории по документу — для контура из ЕГРН, когда файла
        # карты у площадки нет. Чем найдены номера — часть ответа.
        "cadastral_numbers": parcels["numbers"],
        "cadastral_numbers_source": parcels["source"],
        **grouped,
    }


def merge_decision_requirements(
    card: dict[str, Any], facts: dict[str, Any], decision: dict[str, Any]
) -> dict[str, Any]:
    """Promote exact PDF facts while retaining useful catalogue context."""
    result = dict(card)
    result["source_level"] = "official_project_decision"
    result["decision"] = decision
    result["construction"] = list(dict.fromkeys(
        list(card.get("construction") or []) + list(facts.get("construction") or [])
    ))[:30]
    for key in (
        "demolition", "demolition_or_reconstruction", "reconstruction",
        "preservation", "resettlement", "object_actions", "deadlines", "permitted_uses",
    ):
        result[key] = list(facts.get(key) or [])
    if facts.get("renovation"):
        result["renovation"] = facts["renovation"]
    if facts.get("volumes"):
        result["volumes"] = facts["volumes"]
    result["cadastral_numbers"] = list(facts.get("cadastral_numbers") or [])
    result["cadastral_numbers_source"] = str(facts.get("cadastral_numbers_source") or "none")
    result["disclosure"] = {
        key: "published_in_project_decision" if result.get(key)
        else "not_published_in_project_decision"
        for key in (
            "demolition", "demolition_or_reconstruction", "reconstruction",
            "preservation", "resettlement",
        )
    }
    # Вид КРТ и городские нужды берутся из решения — оно и есть документ, где
    # это сказано. Имя застройщика с карточки при этом не теряется: в решении
    # его может не быть вовсе.
    intent = dict(facts.get("intent") or {})
    from_card = dict(card.get("intent") or {})
    if not intent.get("operator_name") and from_card.get("operator_name"):
        intent["operator_name"] = from_card["operator_name"]
    if not intent.get("kind") and from_card.get("kind"):
        intent["kind"], intent["kind_quote"] = from_card["kind"], from_card.get("kind_quote", "")
    intent["taken"] = bool(intent.get("operator_name") or intent.get("operator"))
    intent["decision_read"] = True
    result["intent"] = intent
    result["warning"] = (
        "Прочитан опубликованный проект решения. Это проект, а не заключённый договор: "
        "до утверждения требования могут измениться. Отсутствие записи о расселении или "
        "изъятии означает только, что она не найдена в опубликованном PDF."
    )
    return result


def parse_project_requirements(document: str, project: dict[str, Any]) -> dict[str, Any]:
    """Extract only claims explicitly published on the official project page."""
    sections = _sections(document)
    description = _facts(sections["description"])
    existing = _facts(sections["existing"])
    planned = _facts(sections["planned"])
    all_facts = description + planned

    programme: list[dict[str, Any]] = []
    for key, label in (
        ("housing_gfa_sqm", "Жильё"),
        ("nonresidential_gfa_sqm", "Нежилые объекты"),
        ("business_gfa_sqm", "Общественно-деловые объекты"),
    ):
        value = project.get(key)
        if value not in (None, "", 0, 0.0):
            programme.append({"category": key, "label": label, "area_sqm": value})

    result = {
        "slug": project.get("slug"),
        "name": project.get("name"),
        "source_url": project.get("url"),
        "source_level": "official_krt_project_page",
        "programme": programme,
        "description": description[:12],
        "existing": existing[:12],
        "construction": list(dict.fromkeys(planned + _matching(description, "construction")))[:20],
        "demolition": _matching(all_facts, "demolition")[:20],
        "reconstruction": _matching(all_facts, "reconstruction")[:20],
        "preservation": _matching(all_facts, "preservation")[:20],
        "resettlement": _matching(all_facts, "resettlement")[:20],
    }
    result["disclosure"] = {
        key: "published" if result[key] else "not_published_on_project_page"
        for key in ("demolition", "reconstruction", "preservation", "resettlement")
    }
    # Кто берёт площадку и для чего — из той же карточки, вместе с цитатой.
    # Проекта решения здесь ещё нет, поэтому городские нужды остаются пустыми:
    # это «не искали в документе», а не «не нашли».
    result["intent"] = decision_intent(
        "", title=str(project.get("name") or ""),
        card_fields=_meta_fields(document), probed=bool(document.strip()))
    result["warning"] = (
        "Карточка krt.mos.ru — краткая официальная справка. Отсутствие записи о сносе "
        "или расселении не означает, что их нет: точный перечень содержится в проекте "
        "решения/решении о КРТ и договоре."
    )
    return result

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
_RENOVATION_AREA = re.compile(
    r"(?iu)(?<![\d.,])(\d[\d  ]*(?:[.,]\d+)?)\s*(?:кв\.?\s*м|м2|м²)")


def renovation_volume(sentences: Any) -> dict[str, Any]:
    """Сколько метров решение отдаёт Программе реновации — и чем это сказано.

    Ответов три, и они разные: назван объём, сказано о реновации без объёма,
    не сказано ничего. Второй нельзя показывать ни первым, ни третьим: «доля
    неизвестна» — это не «доли нет» и не «забирают всё».
    """
    mentioned = False
    quote = ""
    area: float | None = None
    for raw in list(sentences or [])[:200]:
        sentence = _SPACE.sub(" ", str(raw or "")).strip()
        low = sentence.casefold()
        if not all(mark in low for mark in _RENOVATION_MARKERS):
            continue
        mentioned = True
        if not quote:
            quote = sentence[:400]
        match = _RENOVATION_AREA.search(sentence)
        value = _social_number(match.group(1)) if match else None
        if value is not None and (area is None or value > area):
            area = value
            quote = sentence[:400]
    return {"mentioned": mentioned, "area_sqm": area, "quote": quote}


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
        "deadlines": list(dict.fromkeys(deadlines))[:5],
        "resettlement": list(dict.fromkeys(resettlement))[:20],
        "object_actions": actions[:100],
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

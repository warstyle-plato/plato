"""Evidence links between contracts, cumulative ledgers and site reports.

This module does not accept works, infer quantities from prose, or change money.
An exact contractor with one compatible contract identifies it automatically.
Both Monitor and management reports use this resolver.
"""
from __future__ import annotations

import contextlib
import copy
import datetime
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import developaid_monitor as monitor
import developaid_monitor_daily as daily
from developaid_monitor_contracts import _party_norm, _contract_number

_MAX_TEXT = 20000
_ID = re.compile(r"^[0-9a-f]{64}$")
_LEGAL_FORMS = {"ооо", "ао", "пао", "оао", "зао", "ип"}
_CORPUS_WORD = re.compile(r"\bкорпус(?:а|ов)? ?(?:№ ?)?(?=[0-9])")
_CORPUS_NUMBER = re.compile(r"[0-9]{1,3}[a-zа-я]?(?![0-9a-zа-я])")
_CORPUS_SEPARATOR = re.compile(r"(?:[,;] ?|и ?)(?:№ ?)?(?=[0-9])")
_STATUS = {
    "confirmed": "Договор определён",
    "proposed": "Связь с договором нужно подтвердить",
    "ambiguous": "Подходит несколько договоров — требуется выбор",
    "unmatched": "Договор не уточнён",
}


class LinkProblem(ValueError):
    """A safe, user-facing validation problem, with no source paths."""


def _day(value: Any, *, optional: bool = False) -> str:
    if not value and optional:
        return ""
    if not value:
        return datetime.date.today().isoformat()
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.date().isoformat() if isinstance(value, datetime.datetime) else value.isoformat()
    try:
        text = str(value)
        date = datetime.date.fromisoformat(text)
        if date.isoformat() != text:
            raise ValueError
        return text
    except (TypeError, ValueError):
        raise LinkProblem("Укажите дату в виде ГГГГ-ММ-ДД.") from None


def _text(value: Any) -> str:
    return " ".join(str(value or "").replace("ё", "е").casefold().split())


def _party(value: Any) -> str:
    # Legal forms and punctuation may differ. Substrings/acronyms are never an
    # exact identity: e.g. Альфа and Альфа Строй remain different parties.
    words = re.findall(r"[0-9a-zа-я]+", _text(value))
    if words and words[0] in _LEGAL_FORMS:
        words.pop(0)
    return " ".join(words)


def _party_identity(value: Any) -> str:
    """Full normalized source identity; never erases an explicit legal form."""
    return " ".join(re.findall(r"[0-9a-zа-я]+", _text(value)))


def _party_parts(value: Any) -> tuple[list[str], str]:
    """Comparison only: persisted source identities keep their original text."""
    words = _party_identity(_party_norm(value)).split()
    if words and words[0] in _LEGAL_FORMS:
        return words[1:], words[0]
    if words and words[-1] in _LEGAL_FORMS:
        return words[:-1], words[-1]
    return words, ""


def _same_party_exact(left: Any, right: Any) -> bool:
    """Omitted form can be shorthand; two different explicit forms cannot."""
    (first, first_form), (second, second_form) = (_party_parts(value) for value in (left, right))
    return (bool(first) and bool(second) and first == second
            and (not first_form or not second_form or first_form == second_form))


def _work_words(value: Any) -> set[str]:
    """Small inflection normalization for a source's work annotation."""
    result = set()
    for word in re.findall(r"[а-яa-z]{4,}", _text(value)):
        for ending in ("иями", "ями", "ами", "ого", "ому", "ыми", "ими", "ая", "яя",
                       "ое", "ее", "ые", "ие", "ой", "ий", "ый", "ом", "ем", "а", "я",
                       "ы", "и", "у", "ю", "е"):
            if word.endswith(ending) and len(word) - len(ending) >= 4:
                word = word[:-len(ending)]
                break
        result.add(word)
    return result


def _party_rows(party: Any, rows: list[dict]) -> tuple[list[dict], str]:
    """Resolve report spelling against this register, without rewriting it.

    The existing crew name keys supply possible aliases. Whole source words
    must still identify a registered name: arbitrary substrings/acronyms and
    explicitly different legal names never become contract identities.
    """
    exact = [row for row in rows if _same_party_exact(party, row.get("contractor"))]
    if exact:
        return exact, "exact"
    source = str(party or "").strip()
    annotation = re.fullmatch(r"(.+?)\s*\(([^()]*)\)\s*", source)
    if annotation:
        base, context = annotation.groups()
        annotation_words = _work_words(context)
        annotated = [row for row in rows if _same_party_exact(base, row.get("contractor"))]
        if not annotated:
            return [], "not_found"
        # An annotation is work context only if this party's own ledger
        # supplies that discipline; company-name parentheses are not noise.
        supported = any(annotation_words and annotation_words <= _work_words(" ".join([
            str(row.get("subject") or ""), *(str(x) for x in row.get("scope") or []),
            *(str(x.get("name") or "") for x in row.get("physical_items") or []),
        ])) for row in annotated)
        if supported:
            identities = {(_party_parts(row.get("contractor"))[1],
                           tuple(_party_parts(row.get("contractor"))[0])) for row in annotated}
            return annotated, "work_context" if len(identities) == 1 else "ambiguous_alias"
        return [], "unresolved_context"
    source_words, source_form = _party_parts(source)
    if not source_words or source_form:
        return [], "not_found"
    import developaid_monitor_crew as crew
    # The common provider already treats these organizational prefixes as
    # display noise. Restrict removal to the name's beginning here.
    organizational = {"ск", "гк", "тд", "сз"}
    while source_words and source_words[0] in organizational:
        source_words = source_words[1:]
    if not source_words:
        return [], "not_found"
    source_key = crew.name_key(source)
    aliases = []
    for row in rows:
        target, _ = _party_parts(row.get("contractor"))
        while target and target[0] in organizational:
            target = target[1:]
        target_key = crew.name_key(row.get("contractor"))
        # Use the provider's canonical key and full-word prefix path. Its
        # recursive acronym inference is neither needed nor allowed here.
        provider_alias = source_key == target_key or len(source_key) >= 4 and target_key.startswith(source_key)
        if target[:len(source_words)] == source_words and provider_alias:
            aliases.append(row)
    identities = {(_party_parts(row.get("contractor"))[1],
                   tuple(_party_parts(row.get("contractor"))[0])) for row in aliases}
    return aliases, "short_name" if len(identities) == 1 else "ambiguous_alias" if aliases else "not_found"


def _party_agrees(item: dict, row: dict, rows: list[dict]) -> bool:
    """Automatic decisions need the source and displayed attribution to agree."""
    source_rows, source_basis = _party_rows(item.get("reported_contractor"), rows)
    displayed_rows, displayed_basis = _party_rows(item.get("contractor"), rows)
    annotation = re.fullmatch(r"(.+?)\s*\(([^()]*)\)\s*", str(item.get("contractor") or "").strip())
    if (annotation and _same_party_exact(annotation.group(1), item.get("reported_contractor"))
            and displayed_basis in {"unresolved_context", "not_found"}):
        # The source already identifies the party; a presentation annotation
        # attached by the common daily attribution cannot erase that proof.
        displayed_rows, displayed_basis = source_rows, source_basis
    return (source_basis not in {"not_found", "unresolved_context", "ambiguous_alias"}
            and displayed_basis not in {"not_found", "unresolved_context", "ambiguous_alias"}
            and any(value.get("id") == row.get("id") for value in source_rows)
            and any(value.get("id") == row.get("id") for value in displayed_rows))


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _project_key(project: str) -> str:
    return monitor._resolved_slug(project)


def _floor_reference(value: str) -> bool:
    return re.match(
        r"[0-9]{1,3}(?: ?(?:[-–—]|[,;]{1,2}) ?[0-9]{1,3}| +и +[0-9]{1,3}){0,30}"
        r"(?:-(?:го|й|ого|ом))? ?[,;]? ?(?:этаж(?:а|ей|ах|у|ом|е|и)?\b|эт\.(?=\s|$)|эт\b)",
        value[:256],
    ) is not None


def _scope_info(value: Any, *, _legacy_identity: bool = False) -> tuple[set[str], bool]:
    """Read complete ordinary corpus lists, keeping ambiguous scope explicit.

    A slash or range may mean a section/address rather than another corpus;
    that source needs clarification instead of silently keeping its first ID.
    """
    text = _text(value)
    # In compact «1и2», и is a conjunction, not the letter suffix of corpus 1.
    text = re.sub(r"(?<=[0-9])и(?= ?(?:№ ?)?[0-9])", " и", text)
    found: set[str] = set()
    ambiguous = False
    for prefix in _CORPUS_WORD.finditer(text):
        cursor = prefix.end()
        continuation = False
        while True:
            if not _legacy_identity and continuation and _floor_reference(text[cursor:]):
                # «Корпуса 3, 2–13 этажа Корпуса 1» starts a new floor
                # reference after the comma, not corpora 2 through 13.
                break
            number = _CORPUS_NUMBER.match(text, cursor)
            if number is None:
                ambiguous = True
                break
            found.add(number.group())
            cursor = number.end()
            if text[cursor:cursor + 1] == " ":
                cursor += 1
            tail = text[cursor:cursor + 32]
            if (not _legacy_identity and tail[:1] in {"-", "–", "—"}
                    and _floor_reference(text[cursor + 1:].lstrip())):
                # The dash in «Корпус 3 — 3,4,5 эт.» separates the place
                # from the expressly named floors; it is not corpus 3–5.
                break
            if (tail[:1] in {"/", "-", "–", "—"} and tail[1:].lstrip(" №").startswith(tuple("0123456789"))
                    or tail.startswith("или") and tail[3:].lstrip(" №").startswith(tuple("0123456789"))):
                ambiguous = True
                break
            separator = _CORPUS_SEPARATOR.match(text, cursor)
            if separator is None:
                break
            cursor = separator.end()
            continuation = separator.group().lstrip()[:1] in {",", ";"}
    return found, ambiguous


def _scope(value: Any) -> set[str]:
    return _scope_info(value)[0]


def _contract_scope_info(row: dict) -> tuple[set[str], bool]:
    texts = [row.get("subject"), *(row.get("scope") or [])]
    for item in row.get("physical_items") or []:
        texts.extend([item.get("scope"), item.get("name")])
    scopes: set[str] = set()
    ambiguous = False
    for text in texts:
        parts, unclear = _scope_info(text)
        scopes.update(parts)
        ambiguous = ambiguous or unclear
    return scopes, ambiguous


def _contract_scopes(row: dict) -> set[str]:
    return _contract_scope_info(row)[0]


def _compatible(evidence: dict, row: dict) -> bool:
    actual, expected = _scope(evidence.get("scope")), _contract_scopes(row)
    return not actual or not expected or bool(actual & expected)


def _scope_covers(evidence: dict, row: dict) -> bool:
    actual, unclear_actual = _scope_info(evidence.get("scope"))
    expected, unclear_expected = _contract_scope_info(row)
    if evidence.get("scope_ambiguous") or unclear_actual or unclear_expected:
        return False
    return not actual or not expected or actual <= expected


def _scope_qualification(evidence: dict, row: dict) -> str:
    """Contract identity does not itself qualify a message's physical scope."""
    actual, unclear_actual = _scope_info(evidence.get("scope"))
    expected, unclear_expected = _contract_scope_info(row)
    if actual and expected and not unclear_expected and not actual <= expected:
        return "conflict"
    if evidence.get("scope_ambiguous") or unclear_actual or unclear_expected:
        return "review"
    return "confirmed" if actual and expected else "not_stated"


def _number(value: Any) -> str:
    return _contract_number(_text(value).replace("–", "-").replace("—", "-"), reference=True).lstrip("#")


def _explicit_contract_numbers(text: str) -> set[str]:
    """Read a contract reference, not an ordinary word after «по договору».

    Without an explicit number marker the token must contain a digit, so
    «на устройство фасада» and «подрядчика» cannot become bogus numbers.
    The entire token is retained: A-12, A-123 and A-12/1 remain different.
    An empty marked reference is retained as unknown, never ignored.
    """
    normalized = _text(text).replace("–", "-").replace("—", "-")
    # A marked number can follow the kind/description of a contract. The next
    # expressly numbered entity owns its own marker instead: «корпус № 2» or
    # «акт № 3» is not a contract reference. This grammar is shared by all
    # automatic, proposed and manual decisions below.
    other_entity = (r"корпус(?:а|ов|у|е|ом)?|этаж(?:а|ей|у|е|ом|и)?|"
                    r"акт(?:а|ов|у|е|ом|ы)?|счет(?:а|ов|у|е|ом|ы)?|"
                    r"подъезд(?:а|ов|у|е|ом|ы)?|квартир(?:а|ы|у|е|ой)?|"
                    r"секци(?:я|и|ю|ей|ям|ях)|пункт(?:а|ов|у|е|ом|ы)?|"
                    r"заявк(?:а|и|у|е|ой)|накладн(?:ая|ой|ую|ые|ых)|"
                    r"письм(?:о|а|у|е|ом)|строк(?:а|и|у|е|ой)")
    marker = (r"№|#|\bномер(?:ом|у|а|е|ами|ов)?\b|\bном\."
              r"|(?<!\w)n(?:o\.|[°º]|o?(?=\s|[:=]))")
    pattern = (r"(?P<contract>\b(?:договор(?:у|а|ом|е|ы|ов|ам|ами|ах)?\b|дог\.))"
               r"|(?P<other>\b(?:" + other_entity + r")(?=\W|[0-9]|$))"
               r"|(?P<marker>" + marker + r")"
               r"|(?P<boundary>[;!?]|\.(?=\s|$))")
    token_pattern = (r"\s*[:=]?\s*[«\"“']?"
                     r"(?P<number>[0-9a-zа-я][0-9a-zа-я_./-]*)?[»\"”']?")
    numbers = set()

    def read_numbers(position: int, marked: bool) -> None:
        """A reference can be a comma/semicolon/conjunction-separated list."""
        while True:
            value = re.match(token_pattern, normalized[position:])
            token = (value.group("number") or "").rstrip(".") if value else ""
            if not marked and not any(character.isdigit() for character in token):
                return
            numbers.add(_number(token))
            if not value or not token:
                return
            position += value.end()
            separator = re.match(r"\s*(?:[,;]|\b(?:и|или)\b)\s*", normalized[position:])
            if separator is None:
                return
            position += separator.end()
            next_marker = re.match(marker, normalized[position:])
            marked = next_marker is not None
            if next_marker:
                position += next_marker.end()

    contract_phrase = False
    for match in re.finditer(pattern, normalized):
        if match.lastgroup in {"other", "boundary"}:
            contract_phrase = False
            continue
        if match.lastgroup == "contract":
            contract_phrase = True
        if not contract_phrase:
            continue
        read_numbers(match.end(), match.lastgroup == "marker")
    return numbers


def _explicit_number(text: str, row: dict) -> bool:
    number = _number(row.get("contract"))
    return bool(number and number in _explicit_contract_numbers(text))


def _selectable_contracts(evidence: dict, rows: list[dict]) -> tuple[list[dict], str]:
    """One admission rule for the choices on screen and a new manual link.

    Broad reconciliation candidates may overlap only part of a work's scope.
    They are not permission to confirm the entire message against that row.
    Existing saved decisions retain their own source and remain revocable.
    """
    if evidence.get("party_attribution_uncertain"):
        return [], "Подрядчик в сообщении указан неоднозначно. Уточните исходное сообщение."
    party = evidence.get("reported_contractor") or evidence.get("contractor")
    if not party:
        return [], "В сообщении не указан подрядчик. Уточните исходное сообщение."
    counts: dict[str, int] = {}
    for row in rows:
        identifier = str(row.get("id") or "")
        counts[identifier] = counts.get(identifier, 0) + 1
    party_rows, party_basis = _party_rows(party, rows)
    same_party = [row for row in party_rows if counts.get(str(row.get("id") or "")) == 1 and row.get("id")]
    if not same_party:
        if party_basis == "unresolved_context":
            return [], "Пометка рядом с именем не подтверждена составом работ подрядчика в накопительных. Уточните имя или работы."
        return [], "Договор этого подрядчика в накопительных не найден. Проверьте подрядчика и шапки ведомостей."
    dated = [row for row in same_party if not row.get("contract_date")
             or row["contract_date"] <= evidence["date"]]
    if not dated:
        return [], "Договоры подрядчика заключены после сообщения. Проверьте даты в источниках."
    scoped = [row for row in dated if _scope_covers(evidence, row)
              or len(dated) == 1 and _scope_qualification(evidence, row) == "review"]
    if not scoped:
        return [], "Корпусный состав сообщения не подтверждён договором или указан неоднозначно. Уточните исходные данные."
    references = _explicit_contract_numbers(evidence["text"])
    if len(references) > 1:
        return [], "В записи указано несколько номеров договоров. Уточните отдельные работы и их договоры."
    if references:
        scoped = [row for row in scoped if _explicit_number(evidence["text"], row)]
        if not scoped:
            return [], "Указанный номер не совпадает с подходящими договорами подрядчика. Проверьте номер договора в сообщении."
    if party_basis == "ambiguous_alias":
        return scoped, "Краткое имя подходит нескольким подрядчикам. Уточните юридическое лицо и выберите договор."
    if len(scoped) == 1 and _scope_qualification(evidence, scoped[0]) != "confirmed":
        return scoped, "Договор подрядчика определён; корпусный состав работ требует уточнения."
    return scoped, ("У подрядчика несколько договоров. Выберите нужный."
                    if len(scoped) > 1 else "Проверьте предложенный договор и подтвердите связь.")


def _signature(evidence: dict, *, source_text: str, source_contractor: str, source_context: str = "") -> str:
    # Work identity is made from the complete source, before limiting UI text.
    # Preserve raw header identity too: a legal form/party change is not a
    # repeated work signature even if the ordinary daily attribution is fuzzy.
    return _digest([_party_identity(evidence.get("contractor")),
                    _party_identity(source_contractor), _party_identity(evidence.get("reported_contractor")),
                    _party_identity(source_context), _text(source_text),
                    _text(evidence.get("scope"))])


def attribute_work_items(parsed: dict, parties: list[str]) -> list[dict]:
    """One attribution path for both daily evidence and displayed report works."""
    known = [str(item.get("name") or "") for item in parsed.get("contractors") or []]
    known.extend(parties)
    raw = parsed.get("works") or []
    attributed = daily.attribute_works(raw, known)
    running_source, last_header, lineage, uncertain = "", None, "", False
    out = []
    for original, item in zip(raw, attributed):
        header = str(original.get("contractor") or "")
        if header != last_header:
            running_source, last_header, lineage, uncertain = "", header, "", False
        parts = daily._split_inline(str(original.get("line") or ""))
        if item.get("named_inline") and len(parts) == 2:
            running_source = parts[0]
            lineage, uncertain = running_source, False
        elif len(parts) == 2:
            if running_source and _party_identity(running_source) != _party_identity(header):
                uncertain = True
            running_source = ""
        out.append({**item, "_contract_source_party": running_source or header,
                    "_contract_source_context": lineage, "_contract_party_uncertain": uncertain})
    return out


def _evidence(project: str, register: dict, cut: str, start: str = "", *,
              reports: list[dict] | None = None, parties: list[str] | None = None) -> list[dict]:
    names = list(daily.known_parties(project, cut) if parties is None else parties)
    names.extend(str(row.get("contractor") or "") for row in register.get("rows") or [])
    names = list(dict.fromkeys(names))
    out: dict[str, dict] = {}
    for report in sorted(daily._load_reports(project) if reports is None else reports,
                         key=lambda r: str(r.get("date") or "")):
        try:
            day = _day(report.get("date"))
        except LinkProblem:
            continue
        if not report.get("date") or day > cut or start and day < start:
            continue
        parsed = report.get("parsed") or {}
        raw = parsed.get("works") or []
        attributed = attribute_work_items(parsed, names)
        for index, item in enumerate(attributed):
            line = str(item.get("line") or "").strip()
            if not line:
                continue
            source_text = str(raw[index].get("line") or "") if index < len(raw) else line
            source_contractor = str(raw[index].get("contractor") or "") if index < len(raw) else ""
            name = str(item.get("contractor") or "").strip()
            inline = daily._split_inline(line)
            reported_party = str(item.get("_contract_source_party") or "").strip()
            exact_party = _same_party_exact(reported_party, name) and not item.get("_contract_party_uncertain")
            if item.get("named_inline"):
                # The ordinary daily UI allows fuzzy aliases. Such attribution
                # must not silently approve a legal contract identity.
                exact_party = exact_party and len(inline) == 2 and _same_party_exact(inline[0], name)
                line = inline[-1].strip()
            line = " ".join(line.split()).strip(" ;.")
            if not line:
                continue
            scopes, scope_ambiguous = _scope_info(line)
            scope = ", ".join(f"Корпус {n}" for n in sorted(scopes))
            evidence = {"date": day, "contractor": name, "reported_contractor": reported_party,
                        "scope": scope, "text": line,
                        "source": {"kind": "daily_report", "date": day, "line_index": index + 1},
                        "party_exact": exact_party}
            if scope_ambiguous:
                evidence["scope_ambiguous"] = True
            # The legacy scope interpretation was part of persisted source
            # ids. Fix the meaning on screen without orphaning manual links.
            old_scope = ", ".join(f"Корпус {n}" for n in sorted(_scope_info(line, _legacy_identity=True)[0]))
            evidence["signature"] = _signature({**evidence, "scope": old_scope}, source_text=source_text,
                                                source_contractor=source_contractor,
                                                source_context=str(item.get("_contract_source_context") or ""))
            if item.get("_contract_party_uncertain"):
                evidence["party_attribution_uncertain"] = True
            evidence["id"] = _digest([_project_key(project), day, evidence["signature"]])
            if len(line) > _MAX_TEXT:
                evidence["text"] = line[:_MAX_TEXT - 1] + "…"
                evidence["text_truncated"] = True
            # Repeated identical lines within one daily report are one piece of
            # evidence, never extra work/quantity or additional acceptance.
            out.setdefault(evidence["id"], evidence)
    return list(out.values())


def _path(project: str) -> Path:
    return monitor._project_dir(project) / "contract_links.json"


@contextlib.contextmanager
def _locked(project: str):
    folder = monitor._project_dir(project)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        import fcntl
    except ImportError:
        raise LinkProblem("Сохранение связей недоступно в этой среде.") from None
    descriptor = os.open(folder / ".contract_links.lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "a+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def _read(project: str) -> dict:
    try:
        value = json.loads(_path(project).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": 1, "links": {}}
    except (ValueError, OSError):
        raise LinkProblem("Сохранённые связи договоров не удалось прочитать.") from None
    if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("links"), dict):
        raise LinkProblem("Формат сохранённых связей договоров не распознан.")
    for evidence_id, item in value["links"].items():
        if not isinstance(evidence_id, str) or not _ID.fullmatch(evidence_id) or not isinstance(item, dict):
            raise LinkProblem("Формат сохранённых связей договоров не распознан.")
        if not _ID.fullmatch(str(item.get("signature") or "")) or not isinstance(item.get("confirmed"), bool):
            raise LinkProblem("Происхождение сохранённой связи договора не распознано.")
        if item.get("contract_id") and not _ID.fullmatch(str(item["contract_id"])):
            raise LinkProblem("Сохранённый номер договора не распознан.")
        for field in ("candidate_contract_ids", "blocked_contract_ids"):
            ids = item.get(field, [])
            if not isinstance(ids, list) or any(not isinstance(i, str) or not _ID.fullmatch(i) for i in ids):
                raise LinkProblem("Сохранённые номера договоров не распознаны.")
    return value


def _write(project: str, data: dict) -> None:
    path = _path(project)
    descriptor, temporary = tempfile.mkstemp(prefix=".contract_links-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def enrich(project: str, register: dict, cut: str, start: str = "", *,
           _reports: list[dict] | None = None, _parties: list[str] | None = None) -> dict:
    """Return a copy of a register with traceable, non-financial daily evidence."""
    cut, start = _day(cut), _day(start, optional=True)
    if start and start > cut:
        raise LinkProblem("Начало периода позже его окончания.")
    result = copy.deepcopy(register)
    rows = result.get("rows") or []
    # An identity collision is not a reason to pick a row by list position.
    ids: dict[str, list[dict]] = {}
    for row in rows:
        ids.setdefault(str(row.get("id") or ""), []).append(row)
    unique = {key: values[0] for key, values in ids.items() if key and len(values) == 1}
    evidence = _evidence(project, result, cut, start, reports=_reports, parties=_parties)
    saved = _read(project).get("links") or {}
    for item in evidence:
        party_rows, party_basis = _party_rows(item["reported_contractor"] or item["contractor"], rows)
        candidates = [row for row in party_rows if row.get("id") in unique
                      and _compatible(item, row)]
        selectable, selection_reason = _selectable_contracts(item, rows)
        direct = saved.get(item["id"])
        applicable = [record for record in saved.values()
                      if record["signature"] == item["signature"]
                      and str(record.get("source_date") or "9999") <= item["date"]]
        manual = direct or max(applicable, key=lambda r: (r.get("source_date") or "", r.get("confirmed_at") or ""), default={})
        blocked = {str(manual.get("contract_id") or "")} if manual.get("confirmed") is False else set()
        explicit = [row for row in selectable if _party_agrees(item, row, rows)
                    and (not row.get("contract_date") or row["contract_date"] <= item["date"])
                    and str(row["id"]) not in blocked and _explicit_number(item["text"], row)]
        # Bind to the exact work signature and the current project's registry.
        # Stale/deleted contracts and a changed contract scope do not revive links.
        manual_row = unique.get(str(manual.get("contract_id") or ""))
        candidate_ids = sorted({str(row["id"]) for row in candidates})
        same_source = manual.get("evidence_id") == item["id"]
        # An identical line can recur under the same known contract choices.
        # A newly introduced competing contract makes future copies ambiguous;
        # a prior confirmation is not a perpetual contractor-wide permission.
        repeat_with_same_choices = (item["date"] >= str(manual.get("source_date") or "9999")
                                    and manual.get("candidate_contract_ids") == candidate_ids)
        manual_applies = manual.get("confirmed") is True and (same_source or repeat_with_same_choices)
        manual_allowed = manual_row is not None and any(row["id"] == manual_row["id"] for row in selectable)
        if manual_applies and manual_row is not None and not manual_allowed:
            _, reason = _selectable_contracts(item, [manual_row])
            item["manual_review_required"] = True
            item["manual_contract_id"] = str(manual_row["id"])
            item["manual_review_reason"] = reason
            # Keep the persisted decision visible and revocable, but do not
            # send its contract's money/progress to a mismatched work in reports.
            if item["manual_contract_id"] not in candidate_ids:
                candidate_ids.append(item["manual_contract_id"])
        if item.get("manual_review_required"):
            chosen, basis = None, "manual_review"
        elif manual_applies and manual_allowed:
            chosen, basis = manual_row, "manual"
        elif len(explicit) == 1:
            chosen, basis = explicit[0], "explicit_number"
        elif (len(selectable) == 1 and _party_agrees(item, selectable[0], rows)
              and str(selectable[0]["id"]) not in blocked
              # A different explicitly stated number must never be ignored.
              and not _explicit_contract_numbers(item["text"])):
            chosen, basis = selectable[0], "exact_party" if party_basis == "exact" else "party_alias"
        else:
            chosen, basis = None, "candidate" if selectable else "none"
        item["contract_id"] = str(chosen["id"]) if chosen else ""
        item["candidate_contract_ids"] = candidate_ids
        if chosen and item["contract_id"] not in item["candidate_contract_ids"]:
            item["candidate_contract_ids"].append(item["contract_id"])
        item["selectable_contract_ids"] = sorted(str(row["id"]) for row in selectable)
        item["suggested_contract_id"] = str(selectable[0]["id"]) if not chosen and len(selectable) == 1 else ""
        item["link_basis"] = basis
        item["party_match_basis"] = party_basis
        item["scope_confirmed"] = bool(chosen and _scope_qualification(item, chosen) == "confirmed")
        item["scope_note"] = ("" if not chosen or item["scope_confirmed"] else
                              "Договор определён; корпусный состав сообщения требует уточнения. "
                              "Связь не подтверждает объёмы отдельных работ.")
        item["match_status"] = ("confirmed" if chosen else "ambiguous" if len(selectable) > 1
                                else "proposed" if selectable else "unmatched")
        item["status"] = _STATUS[item["match_status"]]
        item["match_reason"] = ("" if chosen else
            "Прежняя ручная связь требует проверки: " + item["manual_review_reason"]
            if item.get("manual_review_required") else selection_reason)
        item.pop("signature", None)
        item.pop("party_exact", None)
    for row in rows:
        related = [item for item in evidence if str(row.get("id") or "") in item["candidate_contract_ids"]]
        dates = {"Срез договоров": str(row.get("source_date") or result.get("source_date") or "")}
        for label, field in (("Срез РСС", "rss"), ("Архив накопительных", "cumulative")):
            snapshot_date = (result.get("snapshots") or {}).get(field)
            if isinstance(snapshot_date, str) and snapshot_date:
                dates[label] = snapshot_date
        if related:
            dates["Последнее сообщение о работах"] = max(item["date"] for item in related)
        dates = {label: day for label, day in dates.items() if day}
        confirmed = [item for item in related if item["contract_id"] == row.get("id")]
        issues = []
        if not evidence:
            issues.append("В выбранном периоде нет строк работ из ежедневных отчётов. Это не подтверждает остановку работ.")
        elif not related:
            issues.append("Работы этого договора в ежедневных отчётах периода не определены. Акты могут относиться к другому периоду.")
        if any(item["match_status"] != "confirmed" for item in related):
            issues.append("Связь сообщений с договором требует подтверждения; совпадение подрядчика не подтверждает состав работ.")
        if any(item.get("text_truncated") for item in related):
            issues.append("Длинное сообщение показано сокращённо. Связь относится к полному исходному тексту ежедневного отчёта.")
        if related and not row.get("physical_items"):
            issues.append("Накопительная с объёмами к этому договору не привязана.")
        if _contract_scope_info(row)[1] or any(item.get("scope_ambiguous") for item in related):
            issues.append("Обозначение корпусов в источнике неоднозначно. Договорная связь не подтверждает объёмы отдельных работ.")
        elif any(not _scope_covers(item, row) for item in related):
            issues.append("Сообщение охватывает корпуса за пределами известного состава договора. Связь всей строки не подтверждена.")
        if any(item["contract_id"] == row.get("id") and (not _scope(item.get("scope")) or not _contract_scopes(row))
               for item in related):
            issues.append("Договор определён, но корпус не указан в одном из источников. Соответствие состава работ требует проверки.")
        if any(not any(candidate.get("id") == row.get("id")
                       for candidate in _party_rows(item.get("reported_contractor"), rows)[0]) for item in related):
            issues.append("Имя или юридическая форма контрагента в исходном отчёте отличается от договора. Проверьте источник сообщения.")
        if any(item.get("party_attribution_uncertain") for item in related):
            issues.append("Принадлежность части строк подрядчику неоднозначна после смены имени в тексте. Проверьте исходный ежедневный отчёт.")
        if str(row.get("id") or "") not in unique:
            issues.append("Идентификатор договора неоднозначен; автоматическая привязка отключена.")
        row["reconciliation"] = {
            "status": "Есть подтверждённые связи" if confirmed else "Требуется уточнение" if related else "Нет сопоставленных сообщений",
            "source_dates": dates, "daily_evidence": related, "issues": issues}
    result["unmatched_works"] = [item for item in evidence if item["match_status"] != "confirmed"]
    result["reconciliation_cut"] = cut
    result["reconciliation_start"] = start or None
    result["reconciliation_note"] = "Ежедневный отчёт — сообщение со стройки, а не акт приёмки или подтверждение объёма."
    return result


def set_link(project: str, contract_id: str, evidence_id: str, cut: str,
             confirmed: bool = True) -> dict:
    """Confirm/remove an exact-source work link; never accepts client work text."""
    if not isinstance(confirmed, bool) or not _ID.fullmatch(str(evidence_id)):
        raise LinkProblem("Неверное подтверждение или номер строки ежедневного отчёта.")
    import developaid_monitor_contracts as contracts
    register = contracts.build(project, _day(cut))
    rows = [row for row in register.get("rows") or [] if str(row.get("id")) == str(contract_id)]
    if len(rows) != 1 or not contract_id:
        raise LinkProblem("Договор не найден в выбранном проекте или его номер неоднозначен.")
    found = [item for item in _evidence(project, register, _day(cut)) if item["id"] == evidence_id]
    if len(found) != 1:
        raise LinkProblem("Строка ежедневного отчёта не найдена в выбранном проекте на эту дату.")
    evidence = found[0]
    if confirmed:
        selectable, reason = _selectable_contracts(evidence, register.get("rows") or [])
        if str(contract_id) not in {str(row["id"]) for row in selectable}:
            raise LinkProblem(reason if not selectable else
                              "Договор не входит в подходящие варианты этого подрядчика. Проверьте исходные данные.")
    with _locked(project):
        value = _read(project)
        signature = evidence["signature"]
        party_rows, _ = _party_rows(evidence["reported_contractor"] or evidence["contractor"], register.get("rows") or [])
        candidates = sorted({str(row["id"]) for row in party_rows if _compatible(evidence, row)})
        # One record per exact source preserves previous decisions when an
        # identically worded task later moves to another contract. A negative
        # decision also suppresses number-based auto-linking until confirmed.
        value["links"][evidence_id] = {"contract_id": str(contract_id), "evidence_id": evidence_id,
                                       "signature": signature, "confirmed": confirmed,
                                       "confirmed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                       "source_date": evidence["date"], "basis": "manual",
                                       "candidate_contract_ids": candidates}
        _write(project, value)
    return {"contract_id": str(contract_id), "evidence_id": evidence_id, "confirmed": confirmed}


def prepare_report_context(project: str, reports: list[dict] | None, start: Any, end: Any,
                           parties: list[str] | None = None) -> dict | None:
    """Freeze one registry and one attribution context for a report period."""
    import developaid_monitor_ledgers as ledgers
    if ledgers.latest_snapshot(project, _day(end)) is None:
        return None
    import developaid_monitor_contracts as contracts
    register = contracts.build(project, _day(end))
    names = list(daily.known_parties(project, _day(end)) if parties is None else parties)
    names.extend(str(row.get("contractor") or "") for row in register.get("rows") or [])
    names = list(dict.fromkeys(names))
    return {"parties": names,
            "register": enrich(project, register, _day(end), _day(start),
                               _reports=reports, _parties=names)}


def enrich_report_works(project: str, groups: list[dict], start: Any, end: Any, *,
                        context: dict | None = None) -> list[dict]:
    """Link report lines using the same registry/resolver, without money totals.

    Existing reports without cumulative sources keep their historical shape.
    No second, competing interpretation of a contractor name is created here.
    """
    context = context if context is not None else prepare_report_context(project, None, start, end)
    if context is None:
        return groups
    register = context["register"]
    by_id = {str(row.get("id")): row for row in register.get("rows") or []}
    evidences: dict[str, dict] = {}
    for row in register.get("rows") or []:
        for item in (row.get("reconciliation") or {}).get("daily_evidence") or []:
            evidences[item["id"]] = item
    for item in register.get("unmatched_works") or []:
        evidences[item["id"]] = item
    out = copy.deepcopy(groups)
    party_matches: dict[tuple[str, str], bool] = {}

    def same_report_party(item: dict, name: Any) -> bool:
        if _same_party_exact(item.get("contractor"), name):
            return True
        source = str(item.get("reported_contractor") or item.get("contractor") or "")
        pair = (source, str(name or ""))
        if pair not in party_matches:
            party_matches[pair] = any(
                _party_agrees({"reported_contractor": source, "contractor": name}, row,
                              register.get("rows") or [])
                for row in _party_rows(source, register.get("rows") or [])[0])
        return party_matches[pair]

    for group in out:
        for entry in group.get("lines") or []:
            matches = [item for item in evidences.values()
                       if same_report_party(item, group.get("contractor"))
                       and _text(item["text"]).strip(" ;.") == _text(entry.get("line")).strip(" ;.")
                       and item["date"] in entry.get("days", [])]
            links = {}
            for item in matches:
                if item["match_status"] == "confirmed" and item["contract_id"] in by_id:
                    row = by_id[item["contract_id"]]
                    scope_dates = set(links.get(row["id"], {}).get("scope_review_dates") or [])
                    if not item.get("scope_confirmed", _scope_qualification(item, row) == "confirmed"):
                        scope_dates.add(item["date"])
                    links[row["id"]] = {"id": row["id"], "contract": str(row.get("contract") or ""),
                                        "label": f"Договор {row.get('contract') or 'без номера'}",
                                        "status": "confirmed", "source": item["link_basis"],
                                        "completion_ratio": row.get("completion_ratio"),
                                        "source_kind": row.get("source_kind"),
                                        "progress": copy.deepcopy(row.get("progress") or {}),
                                        "summary_progress": copy.deepcopy(row.get("summary_progress") or {}),
                                        "statement_progress": copy.deepcopy(row.get("statement_progress") or {}),
                                        "reported_performance_sources": copy.deepcopy(row.get("reported_performance_sources") or []),
                                        "observation_forecast": copy.deepcopy(row.get("observation_forecast") or {}),
                                        "completed": row.get("completed"), "amount": row.get("amount"),
                                        "completed_works": row.get("completed_works"),
                                        "completed_materials": row.get("completed_materials"),
                                        "works_materials_split": row.get("works_materials_split"),
                                        "scope_confirmed": not scope_dates,
                                        "scope_review_dates": sorted(scope_dates),
                                        "scope_note": ("Договор определён; корпусный состав сообщений требует уточнения."
                                                       if scope_dates else ""),
                                        "deadline": row.get("deadline"), "risk": copy.deepcopy(row.get("risk") or {}),
                                        "href": "/monitor#" + urlencode({"tab": "contracts", "project": project,
                                                                         "contract": row["id"]})}
            unresolved_days = sorted(set(entry.get("days") or []) - {
                item["date"] for item in matches if item["match_status"] == "confirmed"} | {
                item["date"] for item in matches if item["match_status"] != "confirmed"})
            if links and (unresolved_days or len(links) > 1):
                for identifier, link in links.items():
                    days = sorted({item["date"] for item in matches if item["contract_id"] == identifier})
                    link["label"] += " (" + ", ".join(datetime.date.fromisoformat(day).strftime("%d.%m")
                                                      for day in days) + ")"
            entry["contract_links"] = list(links.values())
            entry["contract_status"] = ("Договор уточнён не за все дни" if links and unresolved_days else
                                        "Договор определён" if links else "Договор не уточнён")
            entry["contract_match_reason"] = ("" if links else next(
                (item.get("match_reason") for item in matches if item.get("match_reason")),
                "Нет сопоставленного сообщения о работах."))
            if links and unresolved_days:
                dates = ", ".join(datetime.date.fromisoformat(day).strftime("%d.%m") for day in unresolved_days)
                entry["contract_match_reason"] = f"За {dates} договор нужно уточнить."
            entry["contract_candidates"] = [
                {"id": identifier, "label": f"Договор {by_id[identifier].get('contract') or 'без номера'}"}
                for identifier in sorted({identifier for item in matches
                                          for identifier in item.get("selectable_contract_ids") or []
                                          if identifier in by_id})]
    return out

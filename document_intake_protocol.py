"""Closed compatibility boundary for qualified document intake, without state IO."""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

PROTOCOL = "qualified-intake-cas-v1"
ADMISSION_ENV = "DEVELOPAID_DOCUMENT_CORE_ADMISSION"
CAPABILITY_PATH = "/agent/document/protocol"
ANSWER_PATH = "/agent/document/qualified-v1/answer"
APPLY_PATH = "/agent/document/qualified-v1/apply"
ENTRY_PATH = "/document-qualified/v1/"
SESSION_PATH = "/telegram/session-data/qualified-v1"
UNAVAILABLE_MESSAGE = ("Модель обновляется. Подтверждение действия сейчас недоступно. "
                       "Обновите страницу и повторно проверьте данные.")
REFRESH_MESSAGE = "Обновите страницу: изменился порядок подтверждения карточки."


class ProtocolHold(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(UNAVAILABLE_MESSAGE)


def capability() -> dict:
    return {"schema": 1, "protocol": PROTOCOL}


def client_contract() -> dict:
    return {**capability(), "capabilityPath": CAPABILITY_PATH, "answerPath": ANSWER_PATH,
            "applyPath": APPLY_PATH, "entryPath": ENTRY_PATH, "sessionPath": SESSION_PATH,
            "unavailableMessage": UNAVAILABLE_MESSAGE}


def _closed_json(raw: str) -> dict:
    if type(raw) is not str or not raw or len(raw) > 4096:
        raise ProtocolHold("metadata_shape")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ProtocolHold("metadata_shape")
            result[key] = value
        return result
    def nonfinite(_):
        raise ProtocolHold("metadata_shape")
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
    except (ValueError, RecursionError):
        raise ProtocolHold("metadata_shape") from None
    if type(value) is not dict:
        raise ProtocolHold("metadata_shape")
    return value


def target_origin(target: str) -> str:
    if (type(target) is not str or not target or len(target) > 1024
            or any(char.isspace() or ord(char) < 32 for char in target)):
        raise ProtocolHold("target_origin")
    try:
        parsed = urlsplit(target)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment):
            raise ValueError
        host = parsed.hostname.encode("idna").decode("ascii").lower()
        port = parsed.port
        if ":" in host:
            host = "[" + host + "]"
        return "https://" + host + (":" + str(port) if port not in (None, 443) else "")
    except (ValueError, UnicodeError):
        raise ProtocolHold("target_origin") from None


def admitted_origin(raw: str, target: str) -> str:
    """Root attests the initial complete rollout; later compatible releases stay admitted."""
    value = _closed_json(raw)
    if (set(value) != {"schema", "origin", "protocol", "core_commit", "completed_rollout"}
            or type(value["schema"]) is not int or value["schema"] != 1
            or value["protocol"] != PROTOCOL or value["completed_rollout"] is not True
            or type(value["core_commit"]) is not str
            or not re.fullmatch(r"[0-9a-f]{40}", value["core_commit"])):
        raise ProtocolHold("root_admission")
    origin = target_origin(target)
    if type(value["origin"]) is not str or value["origin"] != origin:
        raise ProtocolHold("root_origin")
    # core_commit is evidence of the first completed promotion, not a per-release pin.
    return origin


def check_capability(value) -> None:
    if (type(value) is not dict or set(value) != {"schema", "protocol"}
            or type(value["schema"]) is not int or value["schema"] != 1
            or value["protocol"] != PROTOCOL):
        raise ProtocolHold("core_protocol")


def parse_capability(raw: bytes) -> None:
    if type(raw) is not bytes or len(raw) > 4096:
        raise ProtocolHold("core_protocol")
    try:
        value = _closed_json(raw.decode("utf-8", "strict"))
    except UnicodeError:
        raise ProtocolHold("core_protocol") from None
    check_capability(value)

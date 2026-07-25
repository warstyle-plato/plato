from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Final, Iterable


@dataclass(frozen=True, slots=True)
class ProgressStage:
    code: str
    label: str
    percent: int


CALCULATION_STAGES: Final[tuple[ProgressStage, ...]] = (
    ProgressStage("input", "Проверяем исходные данные", 8),
    ProgressStage("calendar", "Строим календарь проекта", 18),
    ProgressStage("sales", "Рассчитываем продажи и цены", 32),
    ProgressStage("costs", "Рассчитываем затраты и налоги", 47),
    ProgressStage("bridge", "Рассчитываем БРИДЖ", 60),
    ProgressStage("pf", "Рассчитываем проектное финансирование и эскроу", 74),
    ProgressStage("metrics", "Считаем доходность, долг и LLCR", 86),
    ProgressStage("report", "Формируем управленческий отчёт", 95),
    ProgressStage("done", "Расчёт завершён", 100),
)

_STAGE_BY_CODE: Final[dict[str, ProgressStage]] = {
    stage.code: stage for stage in CALCULATION_STAGES
}


def stage_payload(code: str, *, detail: str | None = None) -> dict[str, object]:
    """Build one stable progress event for web polling, SSE or Telegram edits."""
    try:
        stage = _STAGE_BY_CODE[code]
    except KeyError as exc:
        raise ValueError(f"Unknown calculation stage: {code}") from exc

    payload: dict[str, object] = asdict(stage)
    payload["status"] = "completed" if code == "done" else "running"
    if detail:
        payload["detail"] = detail
    return payload


def failure_payload(code: str, message: str) -> dict[str, object]:
    """Return an actionable error tied to the stage where calculation stopped."""
    payload = stage_payload(code)
    payload.update({"status": "failed", "error": message})
    return payload


def progress_sequence(codes: Iterable[str] | None = None) -> list[dict[str, object]]:
    """Return the default sequence or a selected subset for a calculation mode."""
    selected = codes if codes is not None else (stage.code for stage in CALCULATION_STAGES)
    return [stage_payload(code) for code in selected]


def telegram_progress_text(code: str, *, detail: str | None = None) -> str:
    payload = stage_payload(code, detail=detail)
    text = f"{payload['percent']}% — {payload['label']}"
    if detail:
        text += f"\n{detail}"
    return text

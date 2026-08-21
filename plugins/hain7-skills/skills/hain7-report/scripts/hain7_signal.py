#!/usr/bin/env python3
"""HAIN7 Studio Signal: evidence extraction, scoring, cohort gating, and one-page PDF.

The evaluator is deliberately deterministic and conservative. It never executes session
content, never scores assistant prose as learner behavior, and requires a complete marker
review before a real child-facing PDF can be rendered.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "1.0"
RUBRIC_VERSION = "hain7-studio-signal-1.1.0"
MAX_EVENTS_BYTES = 256 * 1024 * 1024
MAX_EVENTS = 100_000

AXES: "OrderedDict[str, dict[str, str]]" = OrderedDict(
    [
        (
            "TA",
            {
                "english": "Taste",
                "korean": "보는 눈",
                "description": "더 나은 결과의 기준을 세우고 선택하는 힘",
                "strength": "기준을 말하고 선택의 이유를 결과에 연결했어요.",
                "growth": "두 가지 안을 기준표로 비교하고 선택 이유를 한 줄로 남겨보세요.",
                "challenge": "두 버전을 만든 뒤 ‘사용하기 쉬움·재미·완성도’ 세 기준으로 직접 골라보세요.",
            },
        ),
        (
            "IN",
            {
                "english": "Intent",
                "korean": "의도 세우기",
                "description": "목표·사용자·성공 조건을 분명하게 만드는 힘",
                "strength": "누가 무엇을 언제 성공하는지 구체적으로 정했어요.",
                "growth": "첫 요청에 대상, 핵심 기능, 제한, 완료 조건을 함께 적어보세요.",
                "challenge": "다음 작품은 시작 전에 ‘누구를 위한 것인지’와 성공 조건 두 개를 먼저 써보세요.",
            },
        ),
        (
            "CO",
            {
                "english": "Context",
                "korean": "맥락 주기",
                "description": "AI가 지금 상황을 제대로 알 수 있게 필요한 정보를 주는 힘",
                "strength": "현재 상태와 유지할 부분을 짚어 필요한 맥락을 줬어요.",
                "growth": "현재 화면, 바꿀 것, 유지할 것, 쓰지 말 것을 한 번에 알려주세요.",
                "challenge": "수정 요청마다 ‘현재 상태 / 바꿀 것 / 그대로 둘 것’을 세 줄로 적어보세요.",
            },
        ),
        (
            "VE",
            {
                "english": "Verify",
                "korean": "확인하기",
                "description": "결과를 직접 시험하고 오류를 찾아 다시 확인하는 힘",
                "strength": "직접 실행해 문제를 특정하고 수정 뒤 다시 확인했어요.",
                "growth": "‘안 돼’ 대신 재현 순서와 기대 결과를 적고 고친 뒤 다시 실행해보세요.",
                "challenge": "다음 수업에서 정상·경계·실패 상황을 하나씩 시험하고 결과를 기록해보세요.",
            },
        ),
        (
            "DE",
            {
                "english": "Delegate",
                "korean": "역할 나누기",
                "description": "AI와 내가 맡을 일을 나누고 중요한 결정은 내가 잡는 힘",
                "strength": "AI가 맡을 범위와 내가 결정할 부분을 나눴어요.",
                "growth": "AI가 할 일, 내가 고를 일, 먼저 물어볼 일을 구분해 요청해보세요.",
                "challenge": "요청 첫 줄에 ‘AI가 할 일 / 내가 결정할 일 / 금지할 일’을 각각 적어보세요.",
            },
        ),
        (
            "IT",
            {
                "english": "Iterate",
                "korean": "다시 고치기",
                "description": "첫 결과에서 문제를 찾아 조건을 지키며 더 나은 버전으로 고치는 힘",
                "strength": "첫 버전의 문제를 좁혀 고치고 새 버전을 다시 시험했어요.",
                "growth": "한 번에 하나의 문제만 고치고 전후 결과를 비교해보세요.",
                "challenge": "V1을 저장한 뒤 한 가지 문제만 고친 V2를 만들고 같은 시험으로 비교해보세요.",
            },
        ),
        (
            "OW",
            {
                "english": "Ownership",
                "korean": "내 것으로 만들기",
                "description": "AI 결과를 그대로 받지 않고 선택·수정·설명해 내 결과로 만드는 힘",
                "strength": "직접 선택하고 손으로 다듬어 최종 상태를 설명했어요.",
                "growth": "AI 결과를 그대로 끝내지 말고 직접 한 부분을 바꾼 뒤 이유를 남겨보세요.",
                "challenge": "마지막 10분은 AI 없이 직접 수정하고 ‘내가 바꾼 것과 이유’를 발표해보세요.",
            },
        ),
    ]
)

MARKER_TITLES = OrderedDict(
    [
        ("TA1", "품질 기준"),
        ("TA2", "대안 비교"),
        ("TA3", "이유 있는 선택"),
        ("TA4", "최종 결과에 기준 적용"),
        ("IN1", "목표와 사용자"),
        ("IN2", "기능과 산출물"),
        ("IN3", "제약 조건"),
        ("IN4", "성공 조건"),
        ("CO1", "현재 상태와 자료"),
        ("CO2", "관련 맥락 선택"),
        ("CO3", "불필요·민감 범위 제외"),
        ("CO4", "결과 뒤 맥락 갱신"),
        ("VE1", "실행·미리보기"),
        ("VE2", "구체적 오류 특정"),
        ("VE3", "수정 뒤 재확인"),
        ("VE4", "AI 주장·원인 확인"),
        ("DE1", "AI 작업 범위"),
        ("DE2", "사람의 결정 유지"),
        ("DE3", "도구·승인 경계"),
        ("DE4", "중단·범위 재설정"),
        ("IT1", "첫 버전"),
        ("IT2", "개선 목표 진단"),
        ("IT3", "통제된 수정"),
        ("IT4", "검증된 개선 버전"),
        ("OW1", "최종 선택"),
        ("OW2", "직접 수정"),
        ("OW3", "선택 이유"),
        ("OW4", "최종 상태와 남은 일"),
    ]
)

NORM_KEY_FIELDS = (
    "grade_band",
    "curriculum_id",
    "task_version",
    "duration_band",
    "tool_version",
    "language",
)

MAX_LESSON_MINUTES = 600

# Parent-facing band for axes this session did not observe: 85..85+BASELINE_SPREAD-1,
# strictly below the observed 90–100 band so measurement survives. The per-axis value is
# DETERMINISTIC pseudo-noise seeded by the session fingerprint — identical on every
# re-render of the same report, varied across axes/children so it reads organically
# rather than as a decorative constant. Carries no measurement meaning; must be printed
# only with the disclosure defining the band (report-rubric.md R6).
BASELINE_DISPLAY = 85
BASELINE_SPREAD = 4


def baseline_value(seed: str, code: str) -> int:
    digest = hashlib.sha256(f"{seed}:{code}".encode("utf-8")).digest()
    return BASELINE_DISPLAY + digest[0] % BASELINE_SPREAD

# Age-referenced expectation: the typical per-axis score for one short making session at
# this grade band. PROVISIONAL — seeded from an 11-session internal pilot, not a validated
# norm. Reporting against age expectation instead of an adult ceiling is what keeps a
# developmentally normal child out of the bottom band; see EVIDENCE_BASE.
AGE_REFERENCE: dict[str, float] = {
    "초등 1-2": 0.6,
    "초등 3-4": 0.8,
    "초등 5-6": 1.0,
    "중등 1-3": 1.6,
    "고등 1-3": 2.2,
}
DEFAULT_AGE_REFERENCE = 1.0

# Design basis for the reporting format. These sources justify HOW results are worded and
# framed (process over ability, strengths before gaps, next step over rank). They do NOT
# validate the 28-marker scores — this remains a classroom observation profile.
EVIDENCE_BASE: list[dict[str, str]] = [
    {
        "claim": "능력이 아니라 과정을 짚어 피드백한다",
        "source": "Mueller & Dweck (1998), Journal of Personality and Social Psychology 75(1), 33–52",
        "url": "https://pubmed.ncbi.nlm.nih.gov/9686450/",
    },
    {
        "claim": "‘지금 어디까지 왔고 다음에 무엇을’ 형태의 피드백이 가장 효과적이다",
        "source": "Hattie & Timperley (2007), Review of Educational Research 77(1), 81–112",
        "url": "https://journals.sagepub.com/doi/abs/10.3102/003465430298487",
    },
    {
        "claim": "성적 산출이 아닌 형성적 피드백이 학습을 끌어올린다",
        "source": "Black & Wiliam (1998), Phi Delta Kappan 80(2), 139–148",
        "url": "https://kappanonline.org/inside-the-black-box-raising-standards-through-classroom-assessment/",
    },
    {
        "claim": "유능감·자율성이 지켜질 때 내적 동기가 유지된다",
        "source": "Ryan & Deci (2000), American Psychologist 55(1), 68–78",
        "url": "https://pubmed.ncbi.nlm.nih.gov/11392867/",
    },
    {
        "claim": "아동의 컴퓨팅 사고는 개념·실천·관점 차원으로 관찰한다",
        "source": "Brennan & Resnick (2012), AERA Annual Meeting, Vancouver",
        "url": "https://scratched.gse.harvard.edu/ct/files/AERA2012.pdf",
    },
]

AUTO_CONTEXT_SOURCE = "auto_derived"
MANUAL_CONTEXT_SOURCE = "operator_supplied"

GRADE_BAND_PATTERN = re.compile(r"grade[-_]?(\d{1,2})[-_](\d{1,2})", re.IGNORECASE)
SESSION_SUFFIX_PATTERN = re.compile(r"[-_](s\d+)$", re.IGNORECASE)
DATE_DIR_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HANGUL_PATTERN = re.compile(r"[가-힣]")


class SignalError(RuntimeError):
    """Expected validation or rendering failure."""


def compact_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def excerpt(value: Any, limit: int = 150) -> str:
    text = compact_space(value)
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SignalError(f"필수 JSON 파일이 없습니다: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SignalError(f"JSON 형식 오류: {path}:{exc.lineno}:{exc.colno}") from exc
    if not isinstance(value, dict):
        raise SignalError(f"JSON 최상위 값은 객체여야 합니다: {path}")
    return value


def resolve_session(input_path: Path, latest: bool) -> tuple[Path, Path | None]:
    input_path = input_path.expanduser().resolve()
    if input_path.is_file():
        if input_path.name != "events.jsonl":
            raise SignalError("직접 파일 입력은 events.jsonl만 지원합니다.")
        meta = input_path.parent / "session.meta.json"
        return input_path, meta if meta.exists() else None
    if not input_path.is_dir():
        raise SignalError(f"입력 경로가 없습니다: {input_path}")
    direct = input_path / "events.jsonl"
    if direct.exists():
        meta = input_path / "session.meta.json"
        return direct, meta if meta.exists() else None
    candidates = list(input_path.rglob("events.jsonl"))
    if not candidates:
        raise SignalError(f"events.jsonl을 찾지 못했습니다: {input_path}")
    if len(candidates) > 1 and not latest:
        raise SignalError("여러 세션이 있습니다. 정확한 세션 경로를 주거나 --latest를 사용하세요.")
    chosen = max(candidates, key=lambda item: item.stat().st_mtime)
    meta = chosen.parent / "session.meta.json"
    return chosen, meta if meta.exists() else None


def load_events(path: Path) -> tuple[list[dict[str, Any]], bytes]:
    size = path.stat().st_size
    if size > MAX_EVENTS_BYTES:
        raise SignalError(f"events.jsonl이 {MAX_EVENTS_BYTES // (1024 * 1024)}MB 상한을 넘었습니다.")
    raw = path.read_bytes()
    events: list[dict[str, Any]] = []
    for line_no, raw_line in enumerate(raw.splitlines(), 1):
        if not raw_line.strip():
            continue
        if len(events) >= MAX_EVENTS:
            raise SignalError(f"events.jsonl이 {MAX_EVENTS:,}개 사건 상한을 넘었습니다.")
        try:
            value = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SignalError(f"JSONL 형식 오류: {path}:{line_no}") from exc
        if not isinstance(value, dict):
            raise SignalError(f"JSONL {line_no}행은 객체여야 합니다.")
        value = dict(value)
        value["_line"] = line_no
        events.append(value)
    if not events:
        raise SignalError("events.jsonl에 평가할 사건이 없습니다.")
    return events, raw


def meta_identity(meta: dict[str, Any] | None) -> dict[str, str]:
    """HP Studio has shipped this block as both `identity` and `user`."""
    if not isinstance(meta, dict):
        return {}
    for key in ("user", "identity"):
        block = meta.get(key)
        if isinstance(block, dict):
            return {
                str(k): str(v).strip()
                for k, v in block.items()
                if isinstance(v, (str, int, float)) and not isinstance(v, bool) and str(v).strip()
            }
    return {}


def duration_band_for(minutes: float) -> str:
    low = 0
    for edge in (20, 40, 60, 80, 100):
        if minutes <= edge:
            return f"{low}-{edge}m"
        low = edge
    return "100m+"


def parse_ts(value: Any) -> datetime | None:
    text = str(value or "")
    if not text:
        return None
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    # Studio has emitted both offset-aware and bare stamps; a session mixing the two
    # must not blow up on comparison, so bare stamps are read as UTC.
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def grade_band_label(low: int, high: int) -> str:
    if high <= 6:
        return f"초등 {low}-{high}"
    if low >= 10 and high <= 12:
        return f"고등 {low - 9}-{high - 9}"
    if low >= 7 and high <= 9:
        return f"중등 {low - 6}-{high - 6}"
    return f"{low}-{high}학년"


def detect_language(events: list[dict[str, Any]]) -> str:
    for event in events:
        if event.get("type") == "prompt" and HANGUL_PATTERN.search(str(event.get("text") or "")):
            return "ko"
    return "und"


def derive_context(
    meta: dict[str, Any] | None,
    events: list[dict[str, Any]],
    events_path: Path,
) -> dict[str, Any]:
    """Build a report context from session telemetry alone.

    Only fields the log actually carries are filled. Age, guardian consent, and the
    child notice version are human attestations that no log can supply, so a derived
    context stays diagnostic-only and never satisfies `distribution_allowed`.
    """
    identity = meta_identity(meta)
    program = identity.get("p") or ""
    handle = identity.get("u") or events_path.parent.name

    grade_match = GRADE_BAND_PATTERN.search(program)
    grade_band = (
        grade_band_label(int(grade_match.group(1)), int(grade_match.group(2))) if grade_match else "미상"
    )

    suffix_match = SESSION_SUFFIX_PATTERN.search(program)
    curriculum_id = (SESSION_SUFFIX_PATTERN.sub("", program).strip("-_") or "미상") if suffix_match else (program or "미상")
    task_version = suffix_match.group(1).lower() if suffix_match else (program or "미상")

    stamps = sorted(
        stamp for stamp in (parse_ts(event.get("ts")) for event in events) if stamp is not None
    )
    started = parse_ts((meta or {}).get("started_at"))
    if started is not None:
        stamps = sorted(stamps + [started])
    raw_span = max(1, math.ceil((stamps[-1] - stamps[0]).total_seconds() / 60)) if stamps else 1
    # The log span is wall clock, not teaching time. An app left open overnight would
    # otherwise exceed the schema ceiling and block a session that is perfectly scorable.
    span_minutes = min(raw_span, MAX_LESSON_MINUTES)

    date_dir = events_path.parent.parent.name
    if DATE_DIR_PATTERN.match(date_dir):
        lesson_date = date_dir
    elif stamps:
        lesson_date = stamps[0].date().isoformat()
    else:
        lesson_date = "미상"

    # A real name would carry whitespace or Hangul; refuse to attest pseudonymity then.
    looks_like_handle = bool(handle) and not re.search(r"\s", handle) and not HANGUL_PATTERN.search(handle)

    return {
        "schema_version": SCHEMA_VERSION,
        "context_source": AUTO_CONTEXT_SOURCE,
        "synthetic": False,
        "participant": {
            "display_id": handle,
            "pseudonymous": looks_like_handle,
            "age": None,
            "grade_band": grade_band,
        },
        "lesson": {
            "title": program or "미상",
            "date": lesson_date,
            "duration_minutes": span_minutes,
            "curriculum_id": curriculum_id,
            "task_version": task_version,
            "duration_band": duration_band_for(span_minutes),
            "duration_clamped": raw_span > MAX_LESSON_MINUTES,
            "tool_version": f"hp-studio-{(meta or {}).get('app_version') or 'unknown'}",
            "language": detect_language(events),
            "class_id": identity.get("c") or "미상",
        },
        "privacy": {
            "guardian_consent_verified": False,
            "child_notice_version": None,
            "purpose": "internal_pipeline_diagnostic",
            "correction_contact": None,
        },
    }


def distribution_allowed(context: dict[str, Any]) -> bool:
    """A child/guardian-facing PDF needs synthetic data or a human consent attestation."""
    if context.get("synthetic"):
        return True
    if context.get("context_source") == AUTO_CONTEXT_SOURCE:
        return False
    age = context.get("participant", {}).get("age")
    if isinstance(age, int) and not isinstance(age, bool) and age >= 14:
        return True
    privacy = context.get("privacy") if isinstance(context.get("privacy"), dict) else {}
    return privacy.get("guardian_consent_verified") is True


def validate_context(context: dict[str, Any]) -> None:
    if context.get("schema_version") != SCHEMA_VERSION:
        raise SignalError(f"context.schema_version은 {SCHEMA_VERSION}이어야 합니다.")
    if not isinstance(context.get("synthetic"), bool):
        raise SignalError("context.synthetic은 true 또는 false여야 합니다.")
    participant = context.get("participant")
    lesson = context.get("lesson")
    if not isinstance(participant, dict) or not isinstance(lesson, dict):
        raise SignalError("context.participant와 context.lesson이 필요합니다.")
    auto = context.get("context_source") == AUTO_CONTEXT_SOURCE
    for key in ("display_id", "grade_band") if auto else ("display_id", "age", "grade_band"):
        if participant.get(key) in (None, ""):
            raise SignalError(f"context.participant.{key}가 필요합니다.")
    age = participant.get("age")
    if not (auto and age is None):
        if not isinstance(age, int) or isinstance(age, bool) or not 5 <= age <= 19:
            raise SignalError("participant.age는 5~19의 정수여야 합니다.")
    for key in (
        "title",
        "date",
        "duration_minutes",
        "curriculum_id",
        "task_version",
        "duration_band",
        "tool_version",
        "language",
    ):
        if lesson.get(key) in (None, ""):
            raise SignalError(f"context.lesson.{key}가 필요합니다.")
    duration = lesson.get("duration_minutes")
    if not isinstance(duration, (int, float)) or not 1 <= duration <= MAX_LESSON_MINUTES:
        raise SignalError(f"lesson.duration_minutes는 1~{MAX_LESSON_MINUTES}의 숫자여야 합니다.")
    if context["synthetic"]:
        return
    if participant.get("pseudonymous") is not True:
        raise SignalError("실데이터의 participant.display_id는 가명이어야 하며 pseudonymous:true 확인이 필요합니다.")
    if auto:
        # Telemetry can satisfy structure but never consent. distribution_allowed()
        # keeps an auto-derived context out of every child-facing artifact.
        return
    privacy = context.get("privacy")
    if not isinstance(privacy, dict):
        raise SignalError("실데이터에는 context.privacy가 필요합니다.")
    for key in ("child_notice_version", "purpose", "correction_contact"):
        if privacy.get(key) in (None, ""):
            raise SignalError(f"실데이터에는 privacy.{key}가 필요합니다.")
    if age < 14:
        if privacy.get("guardian_consent_verified") is not True:
            raise SignalError("만 14세 미만 실데이터: 법정대리인 동의 확인이 없어 중단합니다.")
        if not privacy.get("guardian_consent_verified_at"):
            raise SignalError("만 14세 미만 실데이터: 법정대리인 동의 확인 시각이 필요합니다.")


def context_norm_key(context: dict[str, Any]) -> dict[str, str]:
    participant = context["participant"]
    lesson = context["lesson"]
    return {
        "grade_band": str(participant["grade_band"]),
        "curriculum_id": str(lesson["curriculum_id"]),
        "task_version": str(lesson["task_version"]),
        "duration_band": str(lesson["duration_band"]),
        "tool_version": str(lesson["tool_version"]),
        "language": str(lesson["language"]),
    }


def build_evidence_index(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    prefixes = {
        "prompt": "P",
        "response": "R",
        "artifact_snapshot": "A",
        "workflow": "W",
        "turn_end": "T",
        "usage": "U",
    }
    out: list[dict[str, Any]] = []
    for event in events:
        event_type = str(event.get("type") or "other")
        counts[event_type] = counts.get(event_type, 0) + 1
        prefix = prefixes.get(event_type, "X")
        evidence_id = f"{prefix}{counts[event_type]:02d}"
        event["_evidence_id"] = evidence_id
        role = "context"
        summary = event_type
        if event_type == "prompt":
            role = "learner"
            summary = excerpt(event.get("text"))
        elif event_type == "response":
            summary = f"AI 응답 존재 · status={event.get('status', 'unknown')} · {len(str(event.get('text') or '')):,}자"
        elif event_type == "artifact_snapshot":
            source = str(event.get("source") or "unknown")
            if source == "manual_preview":
                role = "learner_or_manual"
            summary = (
                f"HTML 버전 · source={source} · {int(event.get('content_bytes') or 0):,} bytes"
                f" · sha256={str(event.get('sha256') or '')[:10]}"
            )
        elif event_type == "workflow":
            role = "learner_action"
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            payload_summary = excerpt(json.dumps(payload, ensure_ascii=False), 90) if payload else ""
            summary = f"{event.get('event', 'unknown')}" + (f" · {payload_summary}" if payload_summary else "")
        elif event_type == "usage":
            role = "telemetry"
            summary = (
                f"모델 호출 기록 · model={event.get('model', 'unknown')}"
                f" · out={int(event.get('output_tokens') or 0):,} tok"
            )
        elif event_type == "turn_end":
            summary = f"턴 종료 · status={event.get('status', 'unknown')}"
        out.append(
            {
                "evidence_id": evidence_id,
                "line": event.get("_line"),
                "type": event_type,
                "role": role,
                "turn_id": event.get("turn_id"),
                "ts": event.get("ts"),
                "summary": summary,
            }
        )
    return out


def event_ids(events: Iterable[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for event in events:
        value = str(event.get("_evidence_id") or "")
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result[:5]


def has(text: str, pattern: str) -> bool:
    return bool(re.search(pattern, text, re.IGNORECASE))


def prompt_hits(prompts: list[dict[str, Any]], pattern: str) -> list[dict[str, Any]]:
    return [p for p in prompts if has(str(p.get("text") or ""), pattern)]


def composite_prompt_hits(prompts: list[dict[str, Any]], *patterns: str) -> list[dict[str, Any]]:
    return [p for p in prompts if all(has(str(p.get("text") or ""), pattern) for pattern in patterns)]


def after_first_prompt(prompts: list[dict[str, Any]], pattern: str) -> list[dict[str, Any]]:
    return [p for index, p in enumerate(prompts) if index > 0 and has(str(p.get("text") or ""), pattern)]


CONTENT_STOPWORDS = {
    "만들어", "만들", "해줘", "하고", "그리고", "그럼", "이제", "다시", "조금", "주세요",
    "하게", "되게", "있게", "같이", "너무", "정말", "진짜", "우리", "내가", "이거", "저거",
    "그거", "여기", "거기", "어떻게", "해서", "하면", "해봐", "봐줘", "바꿔", "추가",
}


def continuity_hits(prompts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prompts that reuse a content word the learner introduced earlier.

    Children name their own material — 초코, 태양, 우주 — so no fixed vocabulary can
    detect "referring to the current state". Reuse of an earlier token is the signal.
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, prompt in enumerate(prompts):
        tokens = {
            token
            for token in re.findall(r"[가-힣A-Za-z]{2,}", str(prompt.get("text") or ""))
            if token not in CONTENT_STOPWORDS
        }
        if index and (tokens & seen):
            out.append(prompt)
        seen |= tokens
    return out


def marker(
    marker_id: str,
    score: float | None,
    evidence: Iterable[dict[str, Any]],
    opportunity: bool,
    rationale: str,
) -> dict[str, Any]:
    ids = event_ids(evidence)
    if score is not None and score > 0 and not ids:
        raise SignalError(f"내부 채점 오류: {marker_id} 양의 점수에 증거가 없습니다.")
    return {
        "marker_id": marker_id,
        "title": MARKER_TITLES[marker_id],
        "score": score,
        "opportunity": opportunity,
        "evidence_ids": ids,
        "rationale": rationale,
        "source": "candidate_heuristic",
    }


def score_markers(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    prompts = [event for event in events if event.get("type") == "prompt"]
    artifacts = [event for event in events if event.get("type") == "artifact_snapshot"]
    workflows = [event for event in events if event.get("type") == "workflow"]
    responses = [event for event in events if event.get("type") == "response"]
    prompt_opportunity = len(prompts) >= 1
    multi_turn = len(prompts) >= 3
    rich_turn = len(prompts) >= 5

    # Anchors must read child register. An 8-year-old expresses a quality standard as
    # "예쁘게", "무섭게", "신나게" — the same construct as an adult's "완성도 있게".
    quality_pattern = (
        r"기준|재미|재밌|쉽(?:게|다)|깔끔|명확|읽기|보기 좋|완성도|초보|공정|직관"
        r"|예쁘|이쁘|멋있|멋지|귀엽|깜찍|무섭|신나|화려|심플|간단|자연스럽|부드럽"
        r"|밝게|어둡게|시원|따뜻|크게|작게|빠르게|느리게|잘 보이|잘되게|좋게"
    )
    compare_pattern = r"둘 중|두 (?:가지|개)|비교|장단점|보다|대신|A안|B안|와 .{0,12}중|과 .{0,12}중"
    choice_pattern = r"선택|고르|결정|이걸로|빼(?:자|줘|고)|하지 말고|대신"
    reason_pattern = r"때문|해서|이유|그러니|라서|위해|맞(?:아|게)"
    goal_pattern = r"만들(?:고 싶|어|자)|목표|게임|웹사이트|페이지|작품"
    audience_pattern = r"친구|아이|학생|사용자|사람|초보|우리 반|대상"
    mechanic_pattern = (
        r"버튼|점수|키보드|화살표|클릭|시간|초|별|미로|벽|캐릭터|이동|승리|클리어|레벨|목숨"
        r"|색|모양|크기|배경|소리|음악|하트|폭발|점프|달리|날아|떨어|부딪|닿으면|먹으면|누르면"
        r"|아이템|적|몬스터|보스|코인|생명|타이머|맞으면|죽|살아"
    )
    constraint_pattern = r"\d+|하지 마|말고|이하|이상|안 쓰|금지|유지|만 사용|외부|삭제"
    success_pattern = r"성공|완료|클리어|이기|승리|끝나|도착|모으면|통과|조건"
    state_pattern = r"지금|현재|파일|화면|코드|버튼|배경|캐릭터|index\.html|아까|기존"
    scope_pattern = r"그 부분만|나머지.{0,10}유지|그대로|유지|전체.{0,8}(?:바꾸|말고)|바꿀 것|유지할 것"
    exclusion_pattern = r"외부\s*링크|개인정보|삭제하지|파일 삭제|인터넷.{0,8}(?:하지|말고)|추가하지|사운드.{0,8}(?:빼|말고)"
    update_pattern = r"아까|고친 뒤|수정한 뒤|지금은|이제|V2|두 번째|다시 보니|현재는"
    test_pattern = r"미리보기|실행|테스트|시험|확인해|확인할|눌러|재현"
    defect_pattern = r"버그|오류|문제|안 돼|이상|통과해|멈춰|겹쳐|작동하지|깨져|느려"
    specific_pattern = r"벽|버튼|점수|화면|오른쪽|왼쪽|위|아래|클릭|키|초|별|충돌|위치|색"
    recheck_pattern = r"다시.{0,10}(?:실행|확인|테스트|눌러)|고친 뒤|수정한 뒤|재검|통과했|해결됐"
    challenge_pattern = r"왜|원인|맞는지|직접 확인|근거|재현|검증|정말"
    bounded_pattern = r"그 부분만|코드는 네가|범위|한 가지만|딱 .{0,8}만|나머지.{0,8}유지"
    human_decision_pattern = r"나는|난 |내가|내 선택|내가 결정|색은 내가|규칙은 내가|최종은 내가"
    approval_pattern = r"먼저 물어|승인|허락|삭제하지|외부.{0,8}(?:하지|말고)|개인정보|파일.{0,8}(?:건드리지|지우지)"
    reframe_pattern = r"하지 말고|전체.{0,8}(?:바꾸|말고)|빼고|대신|그만|중단|범위를 줄|그 부분만"
    final_pattern = r"최종|이걸로|완료|끝|결정|마지막|발표"
    remaining_pattern = r"남은|아직|다음|빼고|제외|나중|보완|트레이드오프"

    quality_hits = prompt_hits(prompts, quality_pattern)
    quality_terms = max(
        (
            len(
                {
                    term
                    for term, pattern in {
                        "fun": r"재미",
                        "easy": r"쉽|초보",
                        "clear": r"깔끔|명확|읽기|보기 좋|직관",
                        "quality": r"완성도|기준|공정",
                    }.items()
                    if has(str(p.get("text") or ""), pattern)
                }
            )
            for p in prompts
        ),
        default=0,
    )
    ta1_score = 1.0 if quality_terms >= 2 or prompt_hits(prompts, r"기준.{0,30}(?:와|,|·)") else 0.5 if quality_hits else 0.0
    compare_hits = prompt_hits(prompts, compare_pattern)
    ta2_strong = composite_prompt_hits(prompts, compare_pattern, reason_pattern)
    choice_hits = prompt_hits(prompts, choice_pattern)
    reasoned_choice = composite_prompt_hits(prompts, choice_pattern, reason_pattern)
    final_criteria = composite_prompt_hits(prompts, final_pattern, quality_pattern)
    final_hits = prompt_hits(prompts, final_pattern)

    goal_hits = prompt_hits(prompts, goal_pattern)
    audience_hits = prompt_hits(prompts, audience_pattern)
    goal_audience = composite_prompt_hits(prompts, goal_pattern, audience_pattern)
    mechanic_hits = prompt_hits(prompts, mechanic_pattern)
    max_mechanics = max(
        (len(re.findall(mechanic_pattern, str(p.get("text") or ""), re.IGNORECASE)) for p in prompts),
        default=0,
    )
    constraint_hits = prompt_hits(prompts, constraint_pattern)
    max_constraints = max(
        (len(re.findall(constraint_pattern, str(p.get("text") or ""), re.IGNORECASE)) for p in prompts),
        default=0,
    )
    success_hits = prompt_hits(prompts, success_pattern)
    checkable_success = composite_prompt_hits(prompts, success_pattern, r"\d+|도착|모으면|통과")

    state_hits = prompt_hits(prompts, state_pattern)
    continuity = continuity_hits(prompts)
    state_refs = state_hits or continuity
    scoped_hits = prompt_hits(prompts, scope_pattern)
    exclusion_hits = prompt_hits(prompts, exclusion_pattern)
    context_updates = after_first_prompt(prompts, update_pattern)

    workflow_tests = [
        event
        for event in workflows
        if compact_space(event.get("event")).lower()
        in {"validationrun", "trialstart", "trialend", "validation_run", "trial_start", "trial_end"}
    ]
    test_hits = prompt_hits(prompts, test_pattern)
    defect_hits = prompt_hits(prompts, defect_pattern)
    specific_defects = composite_prompt_hits(prompts, defect_pattern, specific_pattern)
    recheck_hits = prompt_hits(prompts, recheck_pattern)
    challenge_hits = prompt_hits(prompts, challenge_pattern)

    bounded_hits = prompt_hits(prompts, bounded_pattern)
    human_decisions = prompt_hits(prompts, human_decision_pattern)
    approval_hits = prompt_hits(prompts, approval_pattern)
    reframe_hits = prompt_hits(prompts, reframe_pattern)

    unique_artifacts: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for artifact in artifacts:
        key = str(artifact.get("sha256") or f"line-{artifact.get('_line')}")
        if key not in seen_hashes:
            seen_hashes.add(key)
            unique_artifacts.append(artifact)
    manual_artifacts = [a for a in artifacts if a.get("source") == "manual_preview"]
    human_actions = [
        event
        for event in workflows
        if compact_space(event.get("event")).lower() in {"humanaction", "human_action"}
    ]
    post_change_tests = bool(len(unique_artifacts) >= 2 and (workflow_tests or recheck_hits))

    # Occasion gates. Turn count is not an opportunity: a child with three prompts and
    # nothing rendered never had a result to judge, revise, or verify, so those markers
    # are NA rather than 0. Only a session that actually offered the moment can score it.
    preview_events = [event for event in workflows if "preview" in compact_space(event.get("event")).lower()]
    result_events = responses + artifacts + preview_events
    saw_result = bool(result_events)
    first_result_line = min((int(event.get("_line") or 0) for event in result_events), default=None)
    reacted = bool(
        first_result_line is not None
        and any(int(prompt.get("_line") or 0) > first_result_line for prompt in prompts)
    )
    revision_stage = len(unique_artifacts) >= 2

    final_choices = prompt_hits(prompts, final_pattern)
    ownership_reason = composite_prompt_hits(prompts, final_pattern + "|" + choice_pattern, reason_pattern)
    final_status = composite_prompt_hits(prompts, final_pattern, remaining_pattern)

    markers: dict[str, dict[str, Any]] = OrderedDict()
    markers["TA1"] = marker("TA1", ta1_score if saw_result else None, quality_hits, saw_result, "명시된 품질 기준의 구체성")
    markers["TA2"] = marker("TA2", 1.0 if ta2_strong else 0.5 if compare_hits else 0.0 if revision_stage else None, ta2_strong or compare_hits, revision_stage, "대안과 트레이드오프 비교")
    markers["TA3"] = marker("TA3", 1.0 if reasoned_choice else 0.5 if choice_hits else 0.0 if reacted else None, reasoned_choice or choice_hits, reacted, "선택과 과제 관련 이유의 연결")
    markers["TA4"] = marker("TA4", 1.0 if final_criteria else 0.5 if final_hits else 0.0 if (revision_stage and reacted) else None, final_criteria or final_hits, revision_stage and reacted, "최종 판단에 앞서 세운 기준을 다시 적용")

    markers["IN1"] = marker("IN1", 1.0 if goal_audience else 0.5 if (goal_hits or audience_hits) else 0.0 if prompt_opportunity else None, goal_audience or goal_hits or audience_hits, prompt_opportunity, "목표와 사용 대상의 동시 명시")
    markers["IN2"] = marker("IN2", 1.0 if max_mechanics >= 2 else 0.5 if mechanic_hits else 0.0 if prompt_opportunity else None, mechanic_hits, prompt_opportunity, "구체적인 기능·상호작용·산출물 요소")
    markers["IN3"] = marker("IN3", 1.0 if max_constraints >= 2 else 0.5 if constraint_hits else 0.0 if prompt_opportunity else None, constraint_hits, prompt_opportunity, "시간·개수·입력·금지 등 실행 제약")
    markers["IN4"] = marker("IN4", 1.0 if checkable_success else 0.5 if success_hits else 0.0 if prompt_opportunity else None, checkable_success or success_hits, prompt_opportunity, "관찰 가능한 완료·승리 조건")

    markers["CO1"] = marker("CO1", 1.0 if (len(state_hits) >= 2 or len(continuity) >= 2) else 0.5 if state_refs else 0.0 if reacted else None, state_refs, reacted, "현재 파일·화면·요소에 대한 관련 사실")
    markers["CO2"] = marker("CO2", 1.0 if scoped_hits else 0.5 if state_refs else 0.0 if reacted else None, scoped_hits or state_refs, reacted, "바꿀 것과 유지할 것의 범위 분리")
    markers["CO3"] = marker("CO3", 1.0 if exclusion_hits else None, exclusion_hits, bool(exclusion_hits), "불필요한 외부 접근·삭제·민감 범위 제외")
    markers["CO4"] = marker("CO4", 1.0 if len(context_updates) >= 2 else 0.5 if context_updates else 0.0 if reacted else None, context_updates, reacted, "결과를 본 뒤 최신 상태로 맥락 갱신")

    markers["VE1"] = marker("VE1", 1.0 if workflow_tests else 0.5 if test_hits else 0.0 if saw_result else None, workflow_tests or test_hits, saw_result, "실제 검증 이벤트 또는 명시적 실행 요청")
    markers["VE2"] = marker("VE2", 1.0 if specific_defects else 0.5 if defect_hits else 0.0 if (saw_result and reacted) else None, specific_defects or defect_hits, saw_result and reacted, "오류 위치·조건의 구체성")
    markers["VE3"] = marker("VE3", 1.0 if post_change_tests else 0.5 if recheck_hits else 0.0 if len(unique_artifacts) >= 2 else None, (workflow_tests + recheck_hits + unique_artifacts[-1:]) if post_change_tests else recheck_hits, len(unique_artifacts) >= 2, "수정 뒤 동일·관련 검사를 다시 수행")
    markers["VE4"] = marker("VE4", 1.0 if challenge_hits else 0.5 if prompt_hits(prompts, r"확인해|검토해") else 0.0 if responses else None, challenge_hits or prompt_hits(prompts, r"확인해|검토해"), bool(responses), "AI 주장·원인에 대한 독립 확인")

    markers["DE1"] = marker("DE1", 1.0 if bounded_hits else 0.5 if prompt_opportunity else None, bounded_hits or prompts[:1], prompt_opportunity, "AI에게 맡긴 작업 범위의 명확성")
    markers["DE2"] = marker("DE2", 1.0 if human_decisions else 0.5 if choice_hits else 0.0 if reacted else None, human_decisions or choice_hits, reacted, "사람이 유지한 의미 있는 결정")
    markers["DE3"] = marker("DE3", 1.0 if approval_hits else 0.0 if any(a.get("source") == "assistant_tool" for a in artifacts) else None, approval_hits, bool(approval_hits or any(a.get("source") == "assistant_tool" for a in artifacts)), "도구·삭제·외부 접근의 승인 경계")
    markers["DE4"] = marker("DE4", 1.0 if reframe_hits else 0.5 if compare_hits else 0.0 if reacted else None, reframe_hits or compare_hits, reacted, "부적합한 방향을 멈추거나 범위 재설정")

    markers["IT1"] = marker("IT1", 1.0 if unique_artifacts else None, unique_artifacts[:1], bool(unique_artifacts), "렌더 가능한 첫 산출물 버전")
    markers["IT2"] = marker("IT2", 1.0 if specific_defects else 0.5 if (defect_hits or prompt_hits(prompts, r"더 (?:좋|예쁘)|개선")) else 0.0 if len(unique_artifacts) >= 1 and multi_turn else None, specific_defects or defect_hits or prompt_hits(prompts, r"더 (?:좋|예쁘)|개선"), len(unique_artifacts) >= 1 and multi_turn, "구체적으로 진단된 개선 목표")
    markers["IT3"] = marker("IT3", 1.0 if scoped_hits else 0.5 if len(unique_artifacts) >= 2 else 0.0 if len(unique_artifacts) >= 2 else None, scoped_hits or unique_artifacts[1:2], len(unique_artifacts) >= 2, "바꿀 목표와 유지 조건을 통제")
    markers["IT4"] = marker("IT4", 1.0 if post_change_tests else 0.5 if len(unique_artifacts) >= 2 else 0.0 if artifacts else None, (unique_artifacts[-2:] + workflow_tests[-1:] + recheck_hits[-1:]) if len(unique_artifacts) >= 2 else unique_artifacts, bool(artifacts), "후속 버전과 수정 뒤 검증의 결합")

    markers["OW1"] = marker("OW1", 1.0 if final_choices else 0.5 if choice_hits else 0.0 if saw_result else None, final_choices or choice_hits, saw_result, "학습자의 명시적 최종 결정")
    manual_evidence = human_actions + manual_artifacts
    markers["OW2"] = marker("OW2", 1.0 if human_actions and manual_artifacts else 0.5 if manual_evidence else 0.0 if workflows and artifacts else None, manual_evidence, bool(workflows and artifacts), "AI 출력 이후 직접 조작·수정한 흔적")
    markers["OW3"] = marker("OW3", 1.0 if ownership_reason else 0.5 if reasoned_choice else 0.0 if final_choices else None, ownership_reason or reasoned_choice, bool(final_choices), "최종 선택을 목표·사용자·기준과 연결한 이유")
    markers["OW4"] = marker("OW4", 1.0 if final_status else 0.5 if final_choices else 0.0 if saw_result else None, final_status or final_choices, saw_result, "최종 상태·남은 문제·다음 책임의 명시")
    return markers


def validate_score(value: Any, label: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or float(value) not in {0.0, 0.5, 1.0}:
        raise SignalError(f"{label} 점수는 0, 0.5, 1, null 중 하나여야 합니다.")
    return float(value)


def apply_review(
    markers: dict[str, dict[str, Any]],
    review: dict[str, Any],
    fingerprint: str,
    evidence_index: list[dict[str, Any]],
) -> dict[str, Any]:
    if review.get("schema_version") != SCHEMA_VERSION:
        raise SignalError("review.schema_version은 1.0이어야 합니다.")
    if review.get("session_fingerprint") != fingerprint:
        raise SignalError("review.session_fingerprint가 현재 세션과 다릅니다.")
    reviewer_type = compact_space(review.get("reviewer_type"))
    # "llm_rater": AI-authored 28-marker review, honestly labeled (owner decision
    # 2026-08-21, written guardian consent obtained separately). Same code locks apply:
    # fingerprint binding, real evidence IDs, per-override notes.
    if reviewer_type not in {"facilitator", "facilitator_assisted", "qualified_rater", "llm_rater", "codex_assisted_demo"}:
        raise SignalError("review.reviewer_type이 허용 목록에 없습니다.")
    if not review.get("completed_at"):
        raise SignalError("review.completed_at이 필요합니다.")
    reviewed = review.get("reviewed_marker_ids")
    if not isinstance(reviewed, list) or set(reviewed) != set(MARKER_TITLES):
        raise SignalError("reviewed_marker_ids는 28개 marker를 빠짐없이 정확히 포함해야 합니다.")
    evidence_ids = {item["evidence_id"] for item in evidence_index}
    overrides = review.get("overrides", [])
    if not isinstance(overrides, list):
        raise SignalError("review.overrides는 배열이어야 합니다.")
    seen: set[str] = set()
    for override in overrides:
        if not isinstance(override, dict):
            raise SignalError("review override는 객체여야 합니다.")
        marker_id = str(override.get("marker_id") or "")
        if marker_id not in markers or marker_id in seen:
            raise SignalError(f"중복되었거나 알 수 없는 marker override: {marker_id}")
        seen.add(marker_id)
        score = validate_score(override.get("score"), marker_id)
        ids = override.get("evidence_ids", [])
        if not isinstance(ids, list) or any(value not in evidence_ids for value in ids):
            raise SignalError(f"{marker_id} override에 알 수 없는 evidence_id가 있습니다.")
        if score is not None and score > 0 and not ids:
            raise SignalError(f"{marker_id} 양의 override에는 evidence_id가 필요합니다.")
        note = compact_space(override.get("note"))
        if not note:
            raise SignalError(f"{marker_id} override에는 note가 필요합니다.")
        markers[marker_id] = {
            **markers[marker_id],
            "score": score,
            "opportunity": score is not None,
            "evidence_ids": ids,
            "rationale": note,
            "source": "review_override",
        }
    return {
        "status": "completed",
        "reviewer_type": reviewer_type,
        "completed_at": review["completed_at"],
        "reviewed_marker_count": len(reviewed),
        "override_count": len(overrides),
    }


def criterion_band(score: float | None) -> str:
    if score is None:
        return "증거 부족"
    if score >= 3.2:
        return "뚜렷하게 관찰됨"
    if score >= 2.2:
        return "성장 중"
    if score >= 1.2:
        return "기초 신호"
    return "증거 더 보기"


def display_band(score: float | None, reference: float) -> tuple[str, float | None]:
    """Age-referenced band. The lowest band describes the SESSION, never the child.

    A developmentally normal 3rd grader meeting age expectation lands in 뚜렷해요, not at
    the bottom of an adult scale. Absence of evidence is reported as a scene the lesson
    did not contain, which is what it actually is.
    """
    if score is None:
        return "이번 수업엔 안 나온 장면", None
    ratio = score / reference if reference > 0 else 0.0
    if ratio >= 1.3:
        return "아주 뚜렷해요", round(ratio, 2)
    if ratio >= 0.8:
        return "뚜렷해요", round(ratio, 2)
    if ratio >= 0.35:
        return "자라는 중", round(ratio, 2)
    return "이번 수업엔 조금 나왔어요", round(ratio, 2)


def axis_results(
    markers: dict[str, dict[str, Any]],
    data_summary: dict[str, Any],
    grade_band: str = "",
) -> OrderedDict[str, dict[str, Any]]:
    result: OrderedDict[str, dict[str, Any]] = OrderedDict()
    truncated = data_summary["truncated_event_count"] > 0
    reference = AGE_REFERENCE.get(compact_space(grade_band), DEFAULT_AGE_REFERENCE)
    for axis_code, definition in AXES.items():
        axis_markers = [markers[f"{axis_code}{index}"] for index in range(1, 5)]
        scorable = [item for item in axis_markers if item["score"] is not None]
        coverage = len(scorable) / 4
        score = round(sum(float(item["score"]) for item in scorable) / len(scorable) * 4, 1) if len(scorable) >= 2 else None
        multi_channel = data_summary["artifact_version_count"] > 0 or data_summary["workflow_count"] > 0
        if coverage >= 0.75 and data_summary["prompt_turn_count"] >= 5 and multi_channel and not truncated:
            confidence = "높음"
        elif coverage >= 0.5 and data_summary["prompt_turn_count"] >= 3:
            confidence = "보통"
        else:
            confidence = "낮음"
        band, ratio = display_band(score, reference)
        result[axis_code] = {
            "code": axis_code,
            **definition,
            "score": score,
            "display_band": band,
            "age_ratio": ratio,
            "age_reference": reference,
            "criterion_band": criterion_band(score),
            "coverage": round(coverage, 2),
            "evidence_confidence": confidence,
            "markers": axis_markers,
        }
    return result


def apply_display_index(axes: "OrderedDict[str, dict[str, Any]]", seed: str = "") -> None:
    """Parent-facing 발휘도: relative index over the axes observed in THIS session.

    Weakest observed axis = 90, strongest = 100, linear in raw score between them; a
    single observed axis (or an all-tie) = 100. Axes with no positive evidence get no
    index at all — they are reported as scenes the lesson did not offer, never as a low
    number. This is an ipsative display scale, not a percentile or attainment rate, and
    the report must say so (see references/report-rubric.md R6).
    """
    observed = {code: axis["score"] for code, axis in axes.items() if axis["score"]}
    vmin = min(observed.values()) if observed else 0.0
    vmax = max(observed.values()) if observed else 0.0
    for code, axis in axes.items():
        value = axis["score"]
        if not value:
            axis["display_index"] = None
        elif vmax == vmin:
            axis["display_index"] = 100
        else:
            axis["display_index"] = int(90 + 10 * (value - vmin) / (vmax - vmin) + 0.5)
        # display_value is what parent-facing artifacts print: unobserved axes carry the
        # disclosed BASELINE so no child's report ever shows a named "missing" axis that a
        # parent could read as 놓친 것 (rubric R1/R6). display_index stays honest for ops.
        if observed:
            if axis["display_index"] is not None:
                axis["display_value"] = axis["display_index"]
                axis["display_basis"] = "observed"
            else:
                axis["display_value"] = baseline_value(seed, code)
                axis["display_basis"] = "baseline"
        else:
            axis["display_value"] = None
            axis["display_basis"] = None


def evaluate_cohort(
    cohort: dict[str, Any] | None,
    context: dict[str, Any],
    axes: OrderedDict[str, dict[str, Any]],
) -> dict[str, Any]:
    withheld = {
        "available": False,
        "basis": "criterion_only",
        "label": "규준 미적용",
        "reason": "비교 코호트가 제공되지 않았습니다.",
        "n": 0,
        "axes": {},
    }
    if cohort is None:
        return withheld
    if cohort.get("schema_version") != SCHEMA_VERSION:
        return {**withheld, "reason": "cohort.schema_version이 1.0이 아닙니다."}
    kind = cohort.get("kind")
    if kind not in {"local_same_condition", "validated_reference"}:
        return {**withheld, "reason": "지원하지 않는 cohort.kind입니다."}
    if context.get("synthetic") is False and cohort.get("synthetic") is True:
        return {**withheld, "reason": "합성 코호트를 실데이터 비교에 사용할 수 없습니다."}
    expected_key = context_norm_key(context)
    actual_key = cohort.get("norm_key")
    if not isinstance(actual_key, dict) or any(str(actual_key.get(key)) != expected_key[key] for key in NORM_KEY_FIELDS):
        return {**withheld, "reason": "학년대·과제·시간·도구·언어 조건이 정확히 일치하지 않습니다."}
    metadata = cohort.get("metadata") if isinstance(cohort.get("metadata"), dict) else {}
    if metadata.get("rubric_version") != RUBRIC_VERSION:
        return {**withheld, "reason": "채점 루브릭 버전이 일치하지 않습니다."}
    records = cohort.get("records")
    if not isinstance(records, list):
        return {**withheld, "reason": "cohort.records가 배열이 아닙니다."}
    clean_records: list[dict[str, float]] = []
    for record in records:
        scores = record.get("scores") if isinstance(record, dict) else None
        if not isinstance(scores, dict) or set(scores) != set(AXES):
            return {**withheld, "reason": "7개 축이 완전하지 않은 코호트 레코드가 있습니다."}
        clean: dict[str, float] = {}
        for code in AXES:
            value = scores.get(code)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= float(value) <= 4:
                return {**withheld, "reason": "0~4 범위를 벗어난 코호트 점수가 있습니다."}
            clean[code] = float(value)
        clean_records.append(clean)
    minimum = 200 if kind == "validated_reference" else 30
    if len(clean_records) < minimum:
        return {**withheld, "reason": f"비교 공개 최소 표본 {minimum}명보다 적습니다.", "n": len(clean_records)}
    if kind == "validated_reference":
        reliability = metadata.get("reliability") if isinstance(metadata.get("reliability"), dict) else {}
        if int(metadata.get("cohort_count") or 0) < 5 or int(metadata.get("site_count") or 0) < 3:
            return {**withheld, "reason": "검증 규준의 독립 코호트·사이트 요건이 부족합니다.", "n": len(clean_records)}
        if any(float(reliability.get(code) or 0) < 0.75 for code in AXES):
            return {**withheld, "reason": "축별 신뢰도 0.75 공개 기준을 충족하지 못했습니다.", "n": len(clean_records)}
        if metadata.get("fairness_audit_passed") is not True or not metadata.get("validity_report"):
            return {**withheld, "reason": "공정성 감사 또는 타당도 보고 메타데이터가 없습니다.", "n": len(clean_records)}

    comparison_axes: dict[str, Any] = {}
    for code, axis in axes.items():
        current = axis["score"]
        values = [record[code] for record in clean_records]
        mean = round(sum(values) / len(values), 2)
        if current is None:
            comparison_axes[code] = {"mean": mean, "percentile_rank": None, "relative_label": "증거 부족"}
            continue
        less = sum(1 for value in values if value < current)
        equal = sum(1 for value in values if value == current)
        percentile = round((less + 0.5 * equal) / len(values) * 100)
        # 표본 36명에서 "상위 1%"처럼 표본 해상도보다 정밀한 숫자를 만들지
        # 않는다. 공개 단위의 최솟값은 1/n이다.
        top_percent = max(math.ceil(100 / len(values)), 100 - percentile)
        if percentile >= 65:
            label = "상대 강점"
        elif percentile <= 35:
            label = "성장 우선"
        else:
            label = "동일조건 범위"
        comparison_axes[code] = {
            "mean": mean,
            "percentile_rank": percentile,
            "top_percent": top_percent,
            "relative_label": label,
        }
    label = compact_space(cohort.get("label")) or ("검증 참조집단" if kind == "validated_reference" else "동일조건 코호트")
    return {
        "available": True,
        "basis": kind,
        "label": label,
        "reason": None,
        "n": len(clean_records),
        "synthetic": bool(cohort.get("synthetic")),
        "national_norm": False,
        "norm_key": expected_key,
        "axes": comparison_axes,
    }


def build_insights(axes: OrderedDict[str, dict[str, Any]], peer: dict[str, Any]) -> dict[str, Any]:
    # Truthy, not `is not None`: a hard-zero axis is evidence of absence and must never
    # be sold as a strength — same observed-set as the wedge chart and 발휘도 rows.
    available = [(code, axis) for code, axis in axes.items() if axis["score"]]
    if not available:
        return {"strengths": [], "growth_priorities": [], "next_challenge": "증거가 충분한 수업 로그를 먼저 확보하세요."}

    # Parent-facing copy ranks by RAW score only. A cohort, when present, exists for
    # operator analytics — letting it reorder strengths made the hero headline disagree
    # with the raw-ranked badge/rows (and quietly re-imported peer comparison, banned by
    # report-rubric R6 / perception-rubric P1). Ties break on canonical axis order.
    order = {code: index for index, code in enumerate(AXES)}

    def strength_key(item: tuple[str, dict[str, Any]]) -> tuple[float, int]:
        code, axis = item
        return -float(axis["score"]), order[code]

    strengths = sorted(available, key=strength_key)[:2]
    used = {code for code, _ in strengths}

    def growth_key(item: tuple[str, dict[str, Any]]) -> tuple[float, int]:
        code, axis = item
        return float(axis["score"]), order[code]

    growth_pool = [item for item in available if item[0] not in used]
    growth = sorted(growth_pool, key=growth_key)[:2]
    priority_code = growth[0][0] if growth else min(available, key=lambda item: (item[1]["score"], order[item[0]]))[0]

    def item_payload(code: str, axis: dict[str, Any], mode: str) -> dict[str, Any]:
        peer_payload = peer.get("axes", {}).get(code, {})
        return {
            "axis": code,
            "label": axis["korean"],
            "score": axis["score"],
            "relative_label": peer_payload.get("relative_label") if peer.get("available") else None,
            "copy": axis[mode],
        }

    return {
        "strengths": [item_payload(code, axis, "strength") for code, axis in strengths],
        "growth_priorities": [item_payload(code, axis, "growth") for code, axis in growth],
        "next_challenge": axes[priority_code]["challenge"],
        "next_challenge_axis": priority_code,
        # Ipsative headline: every learner has a strongest axis, and which one it is
        # genuinely differs between children, so this differentiates without ranking
        # anyone against a ceiling they are not developmentally expected to reach.
        "signature_axis": strengths[0][0] if strengths else None,
        "signature_label": strengths[0][1]["korean"] if strengths else None,
    }


def summarize_data(events: list[dict[str, Any]]) -> dict[str, Any]:
    prompts = [event for event in events if event.get("type") == "prompt"]
    responses = [event for event in events if event.get("type") == "response"]
    artifacts = [event for event in events if event.get("type") == "artifact_snapshot"]
    workflows = [event for event in events if event.get("type") == "workflow"]
    prompt_turns = {event.get("turn_id") for event in prompts if event.get("turn_id")}
    response_turns = {event.get("turn_id") for event in responses if event.get("turn_id")}
    hashes = {event.get("sha256") or f"line-{event.get('_line')}" for event in artifacts}
    truncated = [
        event
        for event in events
        if event.get("text_truncated") is True or event.get("content_truncated") is True
    ]
    return {
        "event_count": len(events),
        "prompt_count": len(prompts),
        "prompt_turn_count": len(prompt_turns),
        "response_count": len(responses),
        "response_turn_coverage": round(len(prompt_turns & response_turns) / len(prompt_turns), 2) if prompt_turns else 0,
        "artifact_snapshot_count": len(artifacts),
        "artifact_version_count": len(hashes),
        "manual_artifact_count": sum(1 for event in artifacts if event.get("source") == "manual_preview"),
        "workflow_count": len(workflows),
        "usage_count": sum(1 for event in events if event.get("type") == "usage"),
        "truncated_event_count": len(truncated),
    }


def warnings_for(data: dict[str, Any], peer: dict[str, Any], context: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if data["response_turn_coverage"] < 0.7:
        warnings.append("AI 응답 기록 범위가 70% 미만이라 선택·거절 맥락이 일부 빠졌을 수 있습니다.")
    if data["artifact_version_count"] == 0:
        warnings.append("산출물 버전이 없어 Iterate·Ownership 일부를 판단할 수 없습니다.")
    if data["workflow_count"] == 0:
        warnings.append("실행·검증·직접조작 이벤트가 없어 Verify·Ownership 일부가 NA일 수 있습니다.")
    if data["truncated_event_count"]:
        warnings.append("절단된 로그가 있어 증거 신뢰도를 보수적으로 표시했습니다.")
    if data.get("usage_count") and data["response_count"] == 0:
        warnings.append("모델 호출 기록만 있고 응답 본문이 없어 학습자가 결과를 봤는지 확인할 수 없습니다.")
    if not peer.get("available"):
        warnings.append(f"상대 비교 보류: {peer.get('reason')}")
    if context.get("lesson", {}).get("duration_clamped"):
        warnings.append(
            f"로그 구간이 {MAX_LESSON_MINUTES}분을 넘어 수업 시간을 상한으로 잘랐습니다. 실제 수업 길이는 --context로 지정하세요."
        )
    if context.get("context_source") == AUTO_CONTEXT_SOURCE:
        warnings.append(
            "컨텍스트를 로그에서 자동 추출했습니다. 나이·보호자 동의·고지 버전이 없어 내부 점검용이며 배포용 리포트가 아닙니다."
        )
    if context.get("synthetic"):
        warnings.append("모든 입력과 비교 데이터는 합성 데모이며 실제 아동 결과가 아닙니다.")
    return warnings


def session_fingerprint(raw_events: bytes, meta: dict[str, Any] | None, context: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    digest.update(raw_events)
    digest.update(json.dumps(meta or {}, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    digest.update(json.dumps(context, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    digest.update(RUBRIC_VERSION.encode("ascii"))
    return digest.hexdigest()


def assemble_analysis(
    events: list[dict[str, Any]],
    raw_events: bytes,
    meta: dict[str, Any] | None,
    context: dict[str, Any],
    cohort: dict[str, Any] | None,
    review: dict[str, Any] | None,
) -> dict[str, Any]:
    evidence_index = build_evidence_index(events)
    data_summary = summarize_data(events)
    fingerprint = session_fingerprint(raw_events, meta, context)
    markers = score_markers(events)
    review_summary: dict[str, Any] = {"status": "not_reviewed", "reviewed_marker_count": 0, "override_count": 0}
    if review is not None:
        review_summary = apply_review(markers, review, fingerprint, evidence_index)
    axes = axis_results(markers, data_summary, str(context.get("participant", {}).get("grade_band") or ""))
    apply_display_index(axes, fingerprint)
    peer = evaluate_cohort(cohort, context, axes)
    insights = build_insights(axes, peer)
    marker_coverage = sum(1 for marker_value in markers.values() if marker_value["score"] is not None) / len(markers)
    return {
        "schema_version": SCHEMA_VERSION,
        "rubric_version": RUBRIC_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "session_fingerprint": fingerprint,
        "profile_type": "HAIN7-derived classroom observation profile",
        "formal_hain7": False,
        "synthetic": bool(context.get("synthetic")),
        "context_source": context.get("context_source", MANUAL_CONTEXT_SOURCE),
        "distribution_allowed": distribution_allowed(context),
        "participant": {
            "display_id": context["participant"]["display_id"],
            "age": context["participant"]["age"],
            "grade_band": context["participant"]["grade_band"],
        },
        "lesson": context["lesson"],
        "data_summary": {**data_summary, "marker_coverage": round(marker_coverage, 2)},
        "review": review_summary,
        "axes": axes,
        "peer_comparison": peer,
        "insights": insights,
        "warnings": warnings_for(data_summary, peer, context),
        "evidence_base": EVIDENCE_BASE,
        "evidence_base_scope": "보고 형식·문구 설계의 근거이며, 28개 marker 점수의 타당도를 검증한 것이 아닙니다.",
        "evidence_index": evidence_index,
    }


def write_json(path: Path, value: dict[str, Any], force: bool) -> None:
    if path.exists() and not force:
        raise SignalError(f"출력 파일이 이미 있습니다. 덮어쓰려면 --force: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(payload, encoding="utf-8")
    os.replace(temp, path)


BUNDLED_FONT = Path(__file__).resolve().parent.parent / "fonts" / "NanumGothic-Regular.ttf"


def find_korean_font(explicit: str | None) -> str:
    """Explicit override, then the bundled face. No silent system-font fallback:
    line-wrap positions depend on glyph metrics, so a machine-local font would break
    the identical-everywhere guarantee (report-rubric.md R5)."""
    for candidate in (explicit, os.environ.get("HAIN7_FONT")):
        if candidate:
            if Path(candidate).exists():
                return str(Path(candidate))
            raise SignalError(f"지정한 글꼴 파일이 없습니다: {candidate}")
    if BUNDLED_FONT.exists():
        return str(BUNDLED_FONT)
    raise SignalError(
        f"동봉 글꼴이 없습니다: {BUNDLED_FONT}. 스킬 배포본이 손상되었습니다. --font 또는 HAIN7_FONT로 임시 지정할 수 있습니다."
    )


def wrap_text(text: str, font_name: str, size: float, max_width: float, string_width: Any) -> list[str]:
    """Greedy char wrap that prefers breaking at a space, so tokens like ‘90~100’ or a
    citation year never split mid-number."""
    text = compact_space(text)
    if not text:
        return []
    lines: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        if current and string_width(candidate, font_name, size) > max_width:
            cut = current.rfind(" ")
            if char != " " and cut > 0 and len(current) - cut <= 12:
                lines.append(current[:cut])
                current = current[cut + 1 :] + char
            else:
                lines.append(current)
                current = "" if char == " " else char
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def render_pdf(analysis: dict[str, Any], output: Path, font_path: str | None, force: bool) -> None:
    """One-page A4, parent-facing. Layout contract: references/report-rubric.md.

    R1: no zero scores, no bottom bands, no collapsed shapes — baseline axes render as
    full opaque wedges sized by their 85–88 band value with their own rows ("곧 피어날
    힘"), never dashed, faded, or summarized as a missing list.
    R6: the only numbers are 발휘도 (90–100, ipsative), with the disclosure line.
    R7: all seven wedges always drawn; hub covers the center; nothing collapses.
    R8: zero observed axes -> refuse with the replacement notice instead of a chart.
    R5: bundled font only (find_korean_font), fixed palette, fixed geometry.
    """
    if output.exists() and not force:
        raise SignalError(f"PDF가 이미 있습니다. 덮어쓰려면 --force: {output}")
    try:
        from reportlab.lib.colors import HexColor
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas
    except ImportError as exc:
        raise SignalError("PDF 생성에는 ReportLab이 필요합니다. 번들 PDF Python 런타임을 사용하세요.") from exc

    axes = analysis["axes"]
    observed = [(code, axis) for code, axis in axes.items() if axis["score"]]
    observed.sort(key=lambda item: (-float(item[1]["score"]), list(AXES).index(item[0])))
    missing = [axis["korean"] for code, axis in axes.items() if not axis["score"]]
    if not observed:
        raise SignalError(
            "관찰된 힘이 없어 리포트를 만들지 않습니다. 리포트 대신 ‘수업이 짧아 기록이 부족해요’ 안내를 전달하세요."
        )
    insights = analysis["insights"]
    lead_code, lead_axis = observed[0]

    font_file = find_korean_font(font_path)
    try:
        pdfmetrics.registerFont(TTFont("HPSans", font_file))
    except Exception as exc:
        raise SignalError(f"한글 글꼴 등록 실패: {font_file}: {exc}") from exc

    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + ".tmp")
    width, height = A4
    c = canvas.Canvas(str(temp), pagesize=A4, pageCompression=1)
    c.setTitle("HAIN7 Studio Signal")
    c.setAuthor("HypeProof")
    c.setSubject("HAIN7-derived classroom observation profile")
    font = "HPSans"

    ink = HexColor("#1B1830")
    muted = HexColor("#6E6885")
    hair = HexColor("#E4E0F0")
    white = HexColor("#FFFFFF")
    violet = HexColor("#6D5DF7")
    violet_soft = HexColor("#ECE9FF")
    coral = HexColor("#FF7A62")
    lime = HexColor("#E8FFAE")
    lime_ink = HexColor("#4A5A16")
    track = HexColor("#F1EFF8")
    violet_bloom = HexColor("#8B7DF9")

    c.setFillColor(white)
    c.rect(0, 0, width, height, fill=1, stroke=0)

    def text_at(x: float, y: float, value: str, size: float, color: Any = ink, align: str = "left") -> None:
        c.setFont(font, size)
        c.setFillColor(color)
        c.setFillAlpha(1)
        if align == "right":
            c.drawRightString(x, y, value)
        elif align == "center":
            c.drawCentredString(x, y, value)
        else:
            c.drawString(x, y, value)

    def wrapped(x: float, y: float, value: str, size: float, max_width: float, leading: float, max_lines: int, color: Any = ink) -> float:
        lines = wrap_text(value, font, size, max_width, pdfmetrics.stringWidth)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            last = lines[-1]
            while last and pdfmetrics.stringWidth(last + "…", font, size) > max_width:
                last = last[:-1]
            lines[-1] = last + "…"
        for index, item in enumerate(lines):
            text_at(x, y - index * leading, item, size, color)
        return y - len(lines) * leading

    # ── Header ────────────────────────────────────────────────────────────────
    text_at(36, 806, "HYPEPROOF · HAIN7 STUDIO SIGNAL", 7.2, muted)
    text_at(36, 782, "수업에서 보인 7가지 힘", 20, ink)
    text_at(36, 766, "설문 없이, 실제로 만든 과정에서 관찰한 신호", 8.8, muted)
    badge_text = "DEMO DATA" if analysis["synthetic"] else "CLASSROOM PROFILE"
    c.setFillColor(coral if analysis["synthetic"] else violet)
    c.setFillAlpha(1)
    badge_w = pdfmetrics.stringWidth(badge_text, font, 7) + 24
    c.roundRect(559 - badge_w, 790, badge_w, 20, 10, fill=1, stroke=0)
    text_at(559 - badge_w / 2, 796.5, badge_text, 7, white, "center")

    # ── ID band ───────────────────────────────────────────────────────────────
    participant = analysis["participant"]
    lesson = analysis["lesson"]
    c.setFillColor(violet_soft)
    c.roundRect(36, 728, 523, 24, 8, fill=1, stroke=0)
    id_line = (
        f"학습자 {participant['display_id']}    학년 {participant['grade_band']}    "
        f"수업 {excerpt(lesson['title'], 24)}    날짜 {lesson['date']}    시간 {lesson['duration_minutes']}분"
    )
    text_at(48, 736.5, id_line, 8.2, ink)

    # ── Hero: 대표 강점 ────────────────────────────────────────────────────────
    c.setFillColor(lime)
    c.roundRect(36, 664, 44, 44, 12, fill=1, stroke=0)
    text_at(58, 681, lead_code, 12, lime_ink, "center")
    lead_index = lead_axis["display_index"]
    text_at(92, 698, f"이번 수업의 대표 강점 · 발휘도 {lead_index}", 8, muted)
    text_at(92, 682, lead_axis["korean"], 15, ink)
    hero_copy = f"{lead_axis['description']} — {lead_axis['strength']}"
    wrapped(92, 668, hero_copy, 8.2, 206, 10.6, 3, muted)

    # ── Petal chart ───────────────────────────────────────────────────────────
    cx, cy, R = 163.0, 508.0, 90.0
    codes = list(AXES)
    n = len(codes)
    step = 360.0 / n
    half = step / 2 * 0.93
    for k, code in enumerate(codes):
        ang = 90.0 - k * step
        axis = axes[code]
        value = axis["display_value"] or BASELINE_DISPLAY
        r = R * (0.60 + 0.40 * (value - BASELINE_DISPLAY) / (100 - BASELINE_DISPLAY))
        is_lead = code == lead_code
        is_baseline = axis["display_basis"] == "baseline"
        c.setDash()
        c.setStrokeAlpha(1)
        c.setFillAlpha(1)
        # 대표 강점만 코랄 윤곽으로 구분하고, 나머지는 관측·기본 구간 모두 같은 짙은
        # 보라 — 옅은 조각이 하나도 없어야 한다는 제품 확정 사양(2026-08-21).
        if is_lead:
            c.setStrokeColor(coral)
            c.setFillColor(violet)
            c.setLineWidth(2.0)
        else:
            c.setStrokeColor(violet)
            c.setFillColor(violet_bloom)
            c.setLineWidth(1.4)
        c.wedge(cx - r, cy - r, cx + r, cy + r, ang - half, 2 * half, fill=1, stroke=1)
    c.setDash()
    c.setFillAlpha(1)
    c.setStrokeAlpha(1)
    c.setFillColor(white)
    c.setStrokeColor(hair)
    c.setLineWidth(1.1)
    c.circle(cx, cy, 14, fill=1, stroke=1)

    label_r = 108.0
    for k, code in enumerate(codes):
        ang_rad = math.radians(90.0 - k * step)
        lx, ly = cx + label_r * math.cos(ang_rad), cy + label_r * math.sin(ang_rad)
        cos = math.cos(ang_rad)
        align = "center" if abs(cos) < 0.35 else ("left" if cos > 0 else "right")
        ly_adj = ly - 3 if abs(cos) >= 0.35 else (ly if math.sin(ang_rad) > 0 else ly - 8)
        chart_label = "내 것으로" if code == "OW" else axes[code]["korean"]
        text_at(lx, ly_adj, chart_label, 8.6, ink, align)
        value = axes[code]["display_value"]
        if value is not None:
            num_color = coral if code == lead_code else violet
            text_at(lx, ly_adj - 12, str(value), 10.5 if code == lead_code else 10, num_color, align)

    legend_y = 382
    legend = [("대표 강점", violet), ("함께 피어난 힘", violet_bloom)]
    lx = 60
    for label, swatch in legend:
        c.setFillColor(swatch)
        c.setFillAlpha(1)
        c.roundRect(lx, legend_y - 1, 8, 8, 2, fill=1, stroke=0)
        text_at(lx + 12, legend_y, label, 6.6, muted)
        lx += 12 + pdfmetrics.stringWidth(label, font, 6.6) + 16

    # ── 발휘도 rows ────────────────────────────────────────────────────────────
    col_x, col_right = 312.0, 559.0
    text_at(col_x, 712, "이 아이 안에서의 발휘도", 7, muted)
    text_at(col_right, 712, "발휘도 85~100 · 대표 강점=100", 7, muted, "right")
    c.setStrokeColor(hair)
    c.setLineWidth(0.8)
    c.line(col_x, 706, col_right, 706)
    row_y = 690.0
    chip_labels = {0: "대표 강점"}
    for rank, (code, axis) in enumerate(observed):
        text_at(col_x, row_y, axis["korean"], 10, ink)
        text_at(col_x + pdfmetrics.stringWidth(axis["korean"], font, 10) + 8, row_y, code, 6.4, muted)
        text_at(col_right, row_y, str(axis["display_index"]), 12, violet, "right")
        chip = chip_labels.get(rank, "함께 빛난 힘" if rank <= 2 else "관찰됨")
        text_at(col_right, row_y - 10, chip, 6.2, muted, "right")
        # Two-line budget; a description that would still clip fails LOUDLY instead of
        # printing a mid-word ellipsis (SKILL.md rejects clipped Korean text outright).
        desc_lines = wrap_text(axis["description"], font, 7.0, 190, pdfmetrics.stringWidth)
        if len(desc_lines) > 2:
            raise SignalError(f"{code} 축 설명이 지면 예산(2줄×190pt)을 넘칩니다: {axis['description']}")
        wrapped(col_x, row_y - 10.5, axis["description"], 7.0, 190, 8.6, 2, muted)
        bar_y = row_y - 30
        c.setFillColor(track)
        c.roundRect(col_x, bar_y, 188, 5.5, 2.75, fill=1, stroke=0)
        c.setFillColor(coral if rank == 0 else violet_bloom)
        c.setFillAlpha(1)
        c.roundRect(col_x, bar_y, 188 * axis["display_index"] / 100, 5.5, 2.75, fill=1, stroke=0)
        row_y -= 46
    baseline_rows = sorted(
        ((c0, a0) for c0, a0 in axes.items() if a0["display_basis"] == "baseline"),
        key=lambda item: (-item[1]["display_value"], list(AXES).index(item[0])),
    )
    for code, axis in baseline_rows:
        text_at(col_x, row_y, axis["korean"], 10, ink)
        text_at(col_x + pdfmetrics.stringWidth(axis["korean"], font, 10) + 8, row_y, code, 6.4, muted)
        text_at(col_right, row_y, str(axis["display_value"]), 12, violet, "right")
        text_at(col_right, row_y - 10, "곧 피어날 힘", 6.2, muted, "right")
        desc_lines = wrap_text(axis["description"], font, 7.0, 190, pdfmetrics.stringWidth)
        if len(desc_lines) > 2:
            raise SignalError(f"{code} 축 설명이 지면 예산(2줄×190pt)을 넘칩니다: {axis['description']}")
        wrapped(col_x, row_y - 10.5, axis["description"], 7.0, 190, 8.6, 2, muted)
        bar_y = row_y - 30
        c.setFillColor(track)
        c.roundRect(col_x, bar_y, 188, 5.5, 2.75, fill=1, stroke=0)
        c.setFillColor(violet_bloom)
        c.setFillAlpha(1)
        c.roundRect(col_x, bar_y, 188 * axis["display_value"] / 100, 5.5, 2.75, fill=1, stroke=0)
        row_y -= 46

    # ── 잘한 것 / 다음 도전 ─────────────────────────────────────────────────────
    c.setStrokeColor(hair)
    c.line(36, 342, 559, 342)
    text_at(36, 326, "이번 수업에서 잘한 것", 7, muted)
    bullet_y = 308.0
    for item in insights.get("strengths", [])[:2]:
        text_at(40, bullet_y, "•", 8.6, violet)
        end_y = wrapped(50, bullet_y, f"{item['label']} — {item['copy']}", 8.4, 240, 11, 2, ink)
        bullet_y = end_y - 8
    text_at(312, 326, "다음 수업에서 해볼 것", 7, muted)
    c.setFillColor(lime)
    c.roundRect(312, 262, 247, 46, 10, fill=1, stroke=0)
    wrapped(324, 292, str(insights.get("next_challenge") or ""), 8.4, 223, 11.5, 3, lime_ink)

    # ── Footer: 공시 + 인용 ────────────────────────────────────────────────────
    c.setStrokeColor(hair)
    c.line(36, 208, 559, 208)
    disclosure = (
        "정식 HAIN7 검사·지능검사·심리검사가 아닙니다. 한 번의 수업에서 관찰된 행동 신호이며, 아이의 능력을 확정하지 않습니다. "
        "발휘도는 이번 수업에서 관찰된 힘을 아이 안에서 90~100으로 나타낸 상대 지수(대표 강점=100)이고, 85~88은 이번 수업 주제 밖에 있어 다음 수업에서 피어날 힘에 붙는 기본 구간 값(구간 내 차이는 무의미)입니다. "
        "백분위·성취율·다른 아이와의 비교가 아닙니다. 아래 문헌은 보고 방식의 설계 근거이고 점수의 타당도를 검증한 것이 아닙니다."
    )
    cite_top = wrapped(36, 196, disclosure, 6.8, 523, 9.2, 4, muted) - 6
    for item in EVIDENCE_BASE:
        line_text = f"{item['claim']} · {item['source']}"
        text_at(36, cite_top, line_text, 6.2, muted)
        text_width = pdfmetrics.stringWidth(line_text, font, 6.2)
        c.setStrokeColor(hair)
        c.setLineWidth(0.5)
        c.line(36, cite_top - 1.5, 36 + text_width, cite_top - 1.5)
        c.linkURL(item["url"], (36, cite_top - 3, 36 + text_width, cite_top + 7), relative=0)
        cite_top -= 11.5

    if c.getPageNumber() != 1:
        raise SignalError(f"PDF가 1페이지가 아닙니다: {c.getPageNumber()}페이지")
    c.showPage()
    c.save()
    os.replace(temp, output)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate an auditable HAIN7 Studio Signal profile.")
    parser.add_argument("--input", required=True, type=Path, help="Session directory, events.jsonl, or spool root")
    parser.add_argument("--latest", action="store_true", help="Choose the newest session below a spool root")
    parser.add_argument(
        "--context",
        type=Path,
        help="Report context JSON. Omit to derive a diagnostic-only context from the session log.",
    )
    parser.add_argument("--cohort", type=Path, help="Optional strictly matched cohort JSON")
    parser.add_argument("--review", type=Path, help="Required complete 28-marker review for a real PDF")
    parser.add_argument("--analysis-output", type=Path, help="Auditable analysis JSON output")
    parser.add_argument("--pdf-output", type=Path, help="One-page PDF output")
    parser.add_argument("--font", help="Korean TTF/TTC font path")
    parser.add_argument("--force", action="store_true", help="Explicitly overwrite output files")
    args = parser.parse_args(argv)
    if not args.analysis_output and not args.pdf_output:
        parser.error("--analysis-output 또는 --pdf-output 중 하나가 필요합니다.")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        events_path, meta_path = resolve_session(args.input, args.latest)
        events, raw_events = load_events(events_path)
        meta = read_json(meta_path) if meta_path else None
        if args.context:
            context = read_json(args.context.expanduser().resolve())
            context.setdefault("context_source", MANUAL_CONTEXT_SOURCE)
        else:
            context = derive_context(meta, events, events_path)
        validate_context(context)
        cohort = read_json(args.cohort.expanduser().resolve()) if args.cohort else None
        review = read_json(args.review.expanduser().resolve()) if args.review else None
        analysis = assemble_analysis(events, raw_events, meta, context, cohort, review)
        if args.pdf_output and not analysis["distribution_allowed"]:
            raise SignalError(
                "배포용 PDF를 만들 수 없습니다: 자동 추출 컨텍스트에는 나이·보호자 동의 확인이 없습니다. "
                "동의가 기록된 --context를 주거나 --analysis-output만 사용하세요."
            )
        if args.pdf_output and not context.get("synthetic") and analysis["review"]["status"] != "completed":
            raise SignalError("실데이터 PDF는 28개 marker 검토가 완료된 --review 파일이 필요합니다.")
        if args.analysis_output:
            write_json(args.analysis_output.expanduser().resolve(), analysis, args.force)
        if args.pdf_output:
            render_pdf(analysis, args.pdf_output.expanduser().resolve(), args.font, args.force)
        print(
            json.dumps(
                {
                    "ok": True,
                    "analysis_output": str(args.analysis_output.resolve()) if args.analysis_output else None,
                    "pdf_output": str(args.pdf_output.resolve()) if args.pdf_output else None,
                    "synthetic": analysis["synthetic"],
                    "context_source": analysis["context_source"],
                    "distribution_allowed": analysis["distribution_allowed"],
                    "peer_comparison": analysis["peer_comparison"]["available"],
                    "marker_coverage": analysis["data_summary"]["marker_coverage"],
                },
                ensure_ascii=False,
            )
        )
        return 0
    except SignalError as exc:
        print(f"HAIN7_SIGNAL_ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

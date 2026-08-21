#!/usr/bin/env python3
"""Adversarial fixtures for hain7-batch. Every case must end in a scored result or a
clean refusal; an uncaught traceback is a failure. Run after any change."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import batch_lib as bl  # noqa: E402
from merge_sessions import merge_student_date  # noqa: E402
from run_batch import process_student  # noqa: E402
from test_batch import EV1, EV2, ContextTests, make_session  # noqa: E402

hs = bl.load_signal_module()
CASES: list[tuple[str, str, callable]] = []


def case(name: str, expect: str):
    def deco(fn):
        CASES.append((name, expect, fn))
        return fn
    return deco


def run_case(fn) -> tuple[str, str]:
    with tempfile.TemporaryDirectory() as tmp:
        try:
            detail = fn(Path(tmp))
            return "OK", str(detail)[:110]
        except (bl.BatchError, hs.SignalError) as exc:
            return "REFUSED", str(exc)[:110]
        except Exception as exc:  # noqa: BLE001
            return "CRASH", f"{type(exc).__name__}: {exc}"


@case("20개 세션 셔플 병합 결정론", "OK")
def _(root: Path):
    import itertools
    dirs = []
    for i in range(20):
        ev = [{"schema_version": 1, "ts": f"2026-08-21T09:{i:02d}:01Z", "type": "prompt",
               "turn_id": f"t{i}", "text": f"별 {i}개 모으는 미로 만들어줘"}]
        dirs.append(make_session(root, "SK56-Z-01", "2026-08-21", f"s-{i:03d}", ev,
                                 f"2026-08-21T09:{i:02d}:00Z"))
    a = merge_student_date(dirs, root / "m1")
    b = merge_student_date(list(reversed(dirs)), root / "m2")
    ta = (root / "m1/events.jsonl").read_text()
    tb = (root / "m2/events.jsonl").read_text()
    assert ta == tb and a["merged_id"] == b["merged_id"], "순서 민감성 발견"
    return f"{a['events']}ev id={a['merged_id']}"


@case("동일 타임스탬프 이벤트 병합 안정성", "OK")
def _(root: Path):
    ev = [{"schema_version": 1, "ts": "2026-08-21T09:00:00Z", "type": "prompt", "turn_id": "x",
           "text": "게임 만들어줘"}]
    d1 = make_session(root, "SK56-Z-01", "2026-08-21", "s-b", ev, "2026-08-21T09:00:00Z")
    d2 = make_session(root, "SK56-Z-01", "2026-08-21", "s-a", ev, "2026-08-21T09:00:00Z")
    a = merge_student_date([d1, d2], root / "m1")
    b = merge_student_date([d2, d1], root / "m2")
    assert (root / "m1/events.jsonl").read_text() == (root / "m2/events.jsonl").read_text()
    return a["merged_id"]


@case("ts 없는 이벤트 섞인 병합", "OK")
def _(root: Path):
    ev = [{"schema_version": 1, "type": "prompt", "turn_id": "x", "text": "미로 만들어줘 별 5개"},
          {"schema_version": 1, "ts": "2026-08-21T09:00:05Z", "type": "prompt", "turn_id": "y",
           "text": "벽을 파란색으로 바꿔줘"}]
    d = make_session(root, "SK56-Z-01", "2026-08-21", "s-1", ev)
    return merge_student_date([d], root / "m")["events"]


@case("이모지·특수문자 프롬프트", "OK")
def _(root: Path):
    ev = [{"schema_version": 1, "ts": "2026-08-21T09:00:01Z", "type": "prompt", "turn_id": "a",
           "text": "🐕✨ <script>alert(1)</script> \"미로\" 만들어줘 & 별 5개"}]
    d = make_session(root, "SK56-Z-01", "2026-08-21", "s-1", ev)
    result = process_student("SK56-Z-01", "2026-08-21", [d], root / "home", None, root / "rv")
    html = Path(result.get("html", "")) if result.get("html") else None
    if html and html.exists():
        assert "<script>alert" not in html.read_text(encoding="utf-8"), "XSS 이스케이프 실패"
    return result["status"]


@case("관측 0축 학생 → no_report 안내", "OK")
def _(root: Path):
    ev = [{"schema_version": 1, "ts": "2026-08-21T09:00:01Z", "type": "prompt", "turn_id": "a",
           "text": "안녕"}]
    d = make_session(root, "SK56-Z-01", "2026-08-21", "s-1", ev)
    result = process_student("SK56-Z-01", "2026-08-21", [d], root / "home", None, root / "rv")
    assert result["status"] == "no_report" and "짧아" in result["notice"]
    return result["status"]


@case("타 아동 디렉토리 혼입 병합", "REFUSED")
def _(root: Path):
    d1 = make_session(root, "SK56-Z-01", "2026-08-21", "s-1", EV1)
    d2 = make_session(root, "SK34-Q-02", "2026-08-21", "s-2", EV2)
    merge_student_date([d1, d2], root / "m")


@case("meta 없는 세션 병합", "OK")
def _(root: Path):
    d = make_session(root, "SK56-Z-01", "2026-08-21", "s-1", EV1)
    (d / "session.meta.json").unlink()
    info = merge_student_date([d], root / "m")
    return info["merged_id"]


@case("빈 events.jsonl 세션", "REFUSED")
def _(root: Path):
    d = make_session(root, "SK56-Z-01", "2026-08-21", "s-1", EV1)
    (d / "events.jsonl").write_text("", encoding="utf-8")
    result = process_student("SK56-Z-01", "2026-08-21", [d], root / "home", None, root / "rv")
    if result["status"] == "error":
        raise bl.BatchError(result["error"])
    raise AssertionError(f"빈 로그가 통과함: {result}")


@case("real 컨텍스트 E2E (동의 기록 완비, PDF는 리뷰 대기)", "OK")
def _(root: Path):
    d1 = make_session(root, "SK56-X-07", "2026-08-21", "s-1", EV1, "2026-08-21T09:00:00Z")
    d2 = make_session(root, "SK56-X-07", "2026-08-21", "s-2", EV2, "2026-08-21T10:00:00Z")
    result = process_student("SK56-X-07", "2026-08-21", [d1, d2], root / "home",
                             ContextTests.CFG, root / "rv")
    assert result["mode"] == "real", result
    assert result["status"] == "ok", result
    assert result["pdf"] is None and "리뷰" in result.get("pdf_skipped", ""), result
    html = Path(result["html"]).read_text(encoding="utf-8")
    assert "CLASSROOM PROFILE" in html and "내부 점검용" not in html
    return f"mode={result['mode']} sig={result['signature']}"


@case("동의 미기록 학생 → diagnostic 강등 E2E", "OK")
def _(root: Path):
    d = make_session(root, "SK56-X-99", "2026-08-21", "s-1", EV1)
    result = process_student("SK56-X-99", "2026-08-21", [d], root / "home",
                             ContextTests.CFG, root / "rv")
    assert result["mode"] == "diagnostic", result
    html = Path(result["html"]).read_text(encoding="utf-8")
    assert "내부 점검용" in html, "diagnostic 워터마크 누락"
    return result["status"]


@case("llm_rater 리뷰 있는 real E2E (PDF 시도 경로)", "OK")
def _(root: Path):
    d = make_session(root, "SK56-X-07", "2026-08-21", "s-1", EV1 + EV2)
    home = root / "home"
    first = process_student("SK56-X-07", "2026-08-21", [d], home, ContextTests.CFG, root / "rv")
    fp = bl.read_json(Path(first["analysis"]))["session_fingerprint"]
    rv = root / "rv"
    rv.mkdir(parents=True, exist_ok=True)
    (rv / "SK56-X-07-2026-08-21.json").write_text(json.dumps({
        "schema_version": "1.0", "session_fingerprint": fp, "reviewer_type": "llm_rater",
        "completed_at": "2026-08-21T12:00:00+09:00",
        "reviewed_marker_ids": list(hs.MARKER_TITLES), "overrides": [],
    }), encoding="utf-8")
    second = process_student("SK56-X-07", "2026-08-21", [d], home, ContextTests.CFG, rv)
    assert second["review"] == "completed", second
    assert second["pdf"] is not None or second.get("pdf_skipped") == "reportlab 미설치", second
    return f"review={second['review']} pdf={second['pdf'] or second.get('pdf_skipped')}"


@case("변조된 리뷰(다른 지문) → 강등 아닌 명시적 거부", "REFUSED")
def _(root: Path):
    d = make_session(root, "SK56-X-07", "2026-08-21", "s-1", EV1)
    rv = root / "rv"
    rv.mkdir(parents=True, exist_ok=True)
    (rv / "SK56-X-07-2026-08-21.json").write_text(json.dumps({
        "schema_version": "1.0", "session_fingerprint": "0" * 64, "reviewer_type": "llm_rater",
        "completed_at": "2026-08-21T12:00:00+09:00",
        "reviewed_marker_ids": list(hs.MARKER_TITLES), "overrides": [],
    }), encoding="utf-8")
    result = process_student("SK56-X-07", "2026-08-21", [d], root / "home", ContextTests.CFG, rv)
    if result["status"] == "error" and "fingerprint" in result["error"]:
        raise bl.BatchError(result["error"])
    raise AssertionError(f"위조 리뷰가 통과함: {result}")


def main() -> int:
    width = max(len(c[0]) for c in CASES)
    bad = 0
    for name, expect, fn in CASES:
        status, detail = run_case(fn)
        ok = status == expect
        bad += 0 if ok else 1
        print(f"{'✓' if ok else '✗'} {name:<{width}}  {status:<8} (want {expect:<8}) {detail}")
    print(f"\n{len(CASES) - bad}/{len(CASES)} 통과")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

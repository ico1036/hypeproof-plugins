#!/usr/bin/env python3
"""QA LINT — the deterministic slice of the two rubrics, run on EVERY batch artifact.

This is the standing answer to "검증이 매 실행마다 도는가": the judge loop validates the
CODE at change time; this lint validates each ARTIFACT at run time. It can only encode
mechanically checkable rules (vocabulary, number ranges, disclosure presence, cross-child
isolation) — perceptual/semantic judgment stays with the change-time judge loop.

Checks (perception-rubric P1/P2 + report-rubric R6/R9 subsets):
  L1 결핍 어휘 금지  L2 비교 어휘는 공시문 밖 금지  L3 숫자 85~100
  L4 공시문 존재     L5 단일 아동(타 아동 격리)      L6 페이드 스타일 금지
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from batch_lib import BatchError, read_json  # noqa: E402

DEFICIENCY = ["부족", "못한", "못했", "기록 없음", "미관측", "놓친", "비어 있"]
COMPARISON = ["또래", "백분위", "평균", "기준선", "상위 %", "등수", "순위"]
DISCLOSURE_MARKERS = ["상대 지수", "기본 구간"]
FADE_PATTERNS = [r"fill-opacity\s*:\s*0?\.\d", r"stroke-dasharray", r'class="[^"]*\bdim\b']


def _strip_exempt(html_text: str) -> str:
    """Remove the disclosure paragraph and citations — the only places where negated
    comparison vocabulary is allowed."""
    text = re.sub(r'<p class="disc">.*?</p>', " ", html_text, flags=re.S)
    text = re.sub(r'<div class="cites">.*?</div>', " ", text, flags=re.S)
    return text


def lint_html(path: Path, expected_student: str | None = None) -> list[str]:
    raw = path.read_text(encoding="utf-8")
    body = _strip_exempt(raw)
    problems: list[str] = []
    for word in DEFICIENCY:
        if word in body:
            problems.append(f"L1 결핍 어휘: {word!r}")
    for word in COMPARISON:
        if word in body:
            problems.append(f"L2 비교 어휘(공시문 밖): {word!r}")
    for m in re.finditer(r'class="score[^"]*">(\d+)<', raw):
        v = int(m.group(1))
        if not 85 <= v <= 100:
            problems.append(f"L3 발휘도 범위 밖 숫자: {v}")
    for m in re.finditer(r'<g class="num">(.*?)</g>', raw, flags=re.S):
        for n in re.findall(r">(\d+)<", m.group(1)):
            if not 85 <= int(n) <= 100:
                problems.append(f"L3 차트 숫자 범위 밖: {n}")
    if not all(marker in raw for marker in DISCLOSURE_MARKERS):
        problems.append("L4 공시문 누락(상대 지수/기본 구간 정의 없음)")
    handles = set(re.findall(r"\bSK\d\d-[A-Z0-9]+-\d+\b", raw))
    if len(handles) > 1:
        problems.append(f"L5 타 아동 격리 위반: 핸들 {sorted(handles)}")
    if expected_student and handles and handles != {expected_student}:
        problems.append(f"L5 학생 불일치: 기대 {expected_student}, 발견 {sorted(handles)}")
    for pat in FADE_PATTERNS:
        if re.search(pat, raw):
            problems.append(f"L6 페이드 스타일 감지: /{pat}/")
    return problems


def lint_analysis(path: Path) -> list[str]:
    a = read_json(path)
    problems: list[str] = []
    axes = a.get("axes", {})
    observed = [ax for ax in axes.values() if ax.get("display_basis") == "observed"]
    values = [ax.get("display_value") for ax in axes.values()]
    if observed:
        if any(v is None or not 85 <= v <= 100 for v in values):
            problems.append(f"L3 display_value 범위 위반: {values}")
        idx = [ax["display_index"] for ax in observed]
        if max(idx) != 100:
            problems.append("L3 대표 강점 100 부재")
        sig = a.get("insights", {}).get("signature_axis")
        obs_codes = {c for c, ax in axes.items() if ax.get("display_basis") == "observed"}
        mentioned = {i.get("axis") for i in a.get("insights", {}).get("strengths", [])}
        if not mentioned <= obs_codes:
            problems.append(f"L1 미관측 축이 강점으로 인쇄됨: {sorted(mentioned - obs_codes)}")
        if sig not in obs_codes:
            problems.append("L1 대표 강점이 관측 축이 아님")
    else:
        if any(v is not None for v in values):
            problems.append("L3 관측 0축인데 표시값 존재")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="부모용 산출물 루브릭 린트")
    ap.add_argument("--html", type=Path)
    ap.add_argument("--analysis", type=Path)
    ap.add_argument("--student")
    args = ap.parse_args(argv)
    problems: list[str] = []
    try:
        if args.html:
            problems += lint_html(args.html, args.student)
        if args.analysis:
            problems += lint_analysis(args.analysis)
    except BatchError as exc:
        print(f"HAIN7_BATCH_ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"ok": not problems, "problems": problems}, ensure_ascii=False))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())

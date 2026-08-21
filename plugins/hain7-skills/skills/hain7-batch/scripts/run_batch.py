#!/usr/bin/env python3
"""ORCHESTRATE — pull → roster → merge → context → score → render → lint → summary.

Deterministic end to end. The LLM operating this skill drives flags and reads the
summary; it never touches scores, copy, or geometry (boundary in SKILL.md).

Per-student flow (owner policy: 학생 핸들 = 유니크 키, 같은 날짜 세션 병합):
  merged session → context(consent config 있으면 real, 없으면 diagnostic auto)
  → hain7_signal.assemble_analysis → analysis.json → HTML (+PDF: real+review+reportlab)
  → qa_lint (fail = artifact quarantined, batch continues)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from batch_lib import (  # noqa: E402
    BatchError, batch_home, default_deploy, grade_band_from_handle, load_signal_module,
    read_json, write_json,
)
from merge_sessions import merge_student_date  # noqa: E402
from pull_sessions import pull  # noqa: E402
from qa_lint import lint_analysis, lint_html  # noqa: E402
from render_html import build_html  # noqa: E402

hs = load_signal_module()


def duration_band(minutes: float) -> str:
    low = 0
    for edge in (20, 40, 60, 80, 100):
        if minutes <= edge:
            return f"{low}-{edge}m"
        low = edge
    return "100m+"


def build_real_context(class_cfg: dict, student: str, date: str, active_minutes: int,
                       app_version: str | None) -> dict | None:
    """Assemble a real (consented) context from operator-maintained records. Returns
    None when the config cannot attest this student — caller falls back to diagnostic.
    This REFERENCES recorded facts (written consent per owner); it never invents them."""
    entry = (class_cfg.get("students") or {}).get(student)
    if not isinstance(entry, dict):
        return None
    privacy_cfg = class_cfg.get("privacy") or {}
    age = entry.get("age")
    grade = entry.get("grade_band") or grade_band_from_handle(student) or class_cfg.get("grade_band")
    minutes = max(1, min(int(active_minutes), 600))
    context = {
        "schema_version": "1.0",
        "context_source": "operator_supplied",
        "synthetic": False,
        "participant": {"display_id": student, "pseudonymous": True, "age": age, "grade_band": grade},
        "lesson": {
            "title": class_cfg.get("lesson_title", "만들기 수업"),
            "date": date,
            "duration_minutes": minutes,
            "curriculum_id": class_cfg.get("curriculum_id", class_cfg.get("class_id", "unknown")),
            "task_version": class_cfg.get("task_version", "s1"),
            "duration_band": duration_band(minutes),
            "tool_version": f"hp-studio-{app_version or 'unknown'}",
            "language": class_cfg.get("language", "ko"),
        },
        "privacy": {
            "guardian_consent_verified": bool(privacy_cfg.get("guardian_consent_verified")),
            "guardian_consent_verified_at": privacy_cfg.get("guardian_consent_verified_at"),
            "child_notice_version": privacy_cfg.get("child_notice_version"),
            "purpose": privacy_cfg.get("purpose", "lesson_feedback"),
            "correction_contact": privacy_cfg.get("correction_contact"),
        },
    }
    try:
        hs.validate_context(dict(context))
        return context
    except hs.SignalError:
        return None  # 동의/필드 미비 → diagnostic으로 강등 (조작 금지)


def process_student(student: str, date: str, session_dirs: list[Path], out_root: Path,
                    class_cfg: dict | None, reviews_dir: Path) -> dict:
    result: dict = {"student": student, "date": date, "sessions": len(session_dirs)}
    # derive_context는 {…}/{date}/{session}/events.jsonl 깊이에서 날짜를 읽으므로
    # 병합본도 같은 규약으로: merged/{student}/{date}/{merged}/
    merged_dir = out_root / "merged" / student / date / "merged"
    merge_info = merge_student_date(session_dirs, merged_dir)
    result["merged"] = {k: merge_info[k] for k in ("merged_id", "sources", "events", "active_minutes")}

    events, raw = hs.load_events(merged_dir / "events.jsonl")
    meta = hs.read_json(merged_dir / "session.meta.json")
    app_version = meta.get("app_version")

    context = None
    if class_cfg:
        context = build_real_context(class_cfg, student, date, merge_info["active_minutes"], app_version)
    mode = "real" if context else "diagnostic"
    if context is None:
        context = hs.derive_context(meta, events, merged_dir / "events.jsonl")
        hs.validate_context(context)
    result["mode"] = mode

    review = None
    review_path = reviews_dir / f"{student}-{date}.json"
    if mode == "real" and review_path.exists():
        review = read_json(review_path)
    analysis = hs.assemble_analysis(events, raw, meta, context, None, review)
    result["review"] = analysis["review"]["status"]

    student_out = out_root / "out" / date / student
    write_json(student_out / "analysis.json", analysis)
    result["analysis"] = str(student_out / "analysis.json")

    observed = [c for c, ax in analysis["axes"].items() if ax.get("display_basis") == "observed"]
    if not observed:
        result["status"] = "no_report"
        result["notice"] = "수업이 짧아 기록이 부족해요 — 리포트 대신 안내 전달"
        return result

    html_path = student_out / "report.html"
    html_page = build_html(analysis, diagnostic=(mode == "diagnostic"))
    html_path.write_text(html_page, encoding="utf-8")
    result["html"] = str(html_path)

    result["pdf"] = None
    if mode == "real" and analysis["distribution_allowed"] and analysis["review"]["status"] == "completed":
        try:
            import reportlab  # noqa: F401
            pdf_path = student_out / "report.pdf"
            hs.render_pdf(analysis, pdf_path, None, force=True)
            result["pdf"] = str(pdf_path)
        except ImportError:
            result["pdf_skipped"] = "reportlab 미설치"
        except hs.SignalError as exc:
            result["pdf_skipped"] = str(exc)
    elif mode == "real":
        result["pdf_skipped"] = "리뷰 미완료" if analysis["review"]["status"] != "completed" else "배포 불가"
    else:
        result["pdf_skipped"] = "diagnostic 모드(동의 컨텍스트 없음)"

    problems = lint_analysis(student_out / "analysis.json") + lint_html(html_path, student)
    if problems:
        html_path.rename(html_path.with_suffix(".html.quarantined"))
        result["status"] = "lint_failed"
        result["lint_problems"] = problems
    else:
        result["status"] = "ok"
        result["signature"] = analysis["insights"].get("signature_label")
        result["display"] = {c: ax["display_value"] for c, ax in analysis["axes"].items()}
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Supabase → 학생별 리포트 배치")
    deploy = default_deploy()
    ap.add_argument("--project-ref", default=deploy.get("project_ref"))
    ap.add_argument("--bucket", default=deploy.get("bucket", "session-logs"))
    ap.add_argument("--no-pull", action="store_true", help="기존 미러 사용")
    ap.add_argument("--date", help="이 날짜만 (YYYY-MM-DD)")
    ap.add_argument("--student", help="이 학생만")
    ap.add_argument("--all-dates", action="store_true", help="학생별 전체 날짜 통합 병합")
    ap.add_argument("--dry-run", action="store_true", help="명부·커버리지만 출력")
    args = ap.parse_args(argv)

    home = batch_home()
    mirror = home / "mirror"
    summary: dict = {"quarantined_sessions": [], "students": []}
    try:
        if not args.no_pull:
            if not args.project_ref:
                raise BatchError(
                    "프로젝트 ref가 없습니다: --project-ref, HAIN7_SUPABASE_REF, "
                    "또는 references/deploy.json 중 하나로 지정하세요."
                )
            inv = pull(args.project_ref, args.bucket, mirror)
            summary["pull"] = {"sessions": len(inv["sessions"]), "cached": inv["skipped_cached"]}
            summary["quarantined_sessions"] = inv["quarantined"]

        groups: dict[tuple[str, str], list[Path]] = {}
        for events_file in sorted(mirror.rglob("events.jsonl")):
            d = events_file.parent
            # 미러 계약: mirror/{class}/{student}/{date}/{session}/events.jsonl — 다른
            # 깊이의 파일은 레이아웃 오류이므로 조용히 집계하지 않고 건너뛰며 기록한다.
            try:
                rel = d.relative_to(mirror)
            except ValueError:
                continue
            if len(rel.parts) != 4:
                summary.setdefault("layout_errors", []).append(str(rel))
                continue
            student, date = d.parent.parent.name, d.parent.name
            if args.date and date != args.date:
                continue
            if args.student and student != args.student:
                continue
            key = (student, "ALL" if args.all_dates else date)
            groups.setdefault(key, []).append(d)
        if not groups:
            raise BatchError("조건에 맞는 세션이 미러에 없습니다.")

        summary["roster"] = sorted({s for s, _ in groups})
        if args.dry_run:
            summary["dry_run"] = {f"{s}@{dt}": len(dirs) for (s, dt), dirs in sorted(groups.items())}
            print(json.dumps(summary, ensure_ascii=False, indent=1))
            return 0

        class_ids = {d.parent.parent.parent.name for dirs in groups.values() for d in dirs}
        class_cfg = None
        if len(class_ids) == 1:
            cfg_path = home / "config" / f"{class_ids.pop()}.json"
            if cfg_path.exists():
                class_cfg = read_json(cfg_path)
        reviews_dir = home / "reviews"

        for (student, date), dirs in sorted(groups.items()):
            try:
                summary["students"].append(
                    process_student(student, date, dirs, home, class_cfg, reviews_dir)
                )
            except (BatchError, hs.SignalError) as exc:
                summary["students"].append(
                    {"student": student, "date": date, "status": "error", "error": str(exc)}
                )

        counts: dict[str, int] = {}
        for s in summary["students"]:
            counts[s["status"]] = counts.get(s["status"], 0) + 1
        summary["counts"] = counts
        write_json(home / "out" / "last-batch-summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=1))
        return 0 if counts and set(counts) <= {"ok", "no_report"} else (0 if not counts else 1)
    except BatchError as exc:
        print(f"HAIN7_BATCH_ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

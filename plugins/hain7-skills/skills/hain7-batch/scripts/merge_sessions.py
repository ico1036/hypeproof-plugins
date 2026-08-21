#!/usr/bin/env python3
"""MERGE — one student's sessions for one date → one merged session (owner policy:
학생 핸들이 유니크 키, 같은 날 세션은 수업 1회로 병합).

Deterministic: events sorted by (timestamp, session started_at, session_id, original
line). Merged session_id derives from the sorted source ids, so identical inputs give a
byte-identical merge — the fingerprint/seal chain stays reproducible.

Isolation: input dirs must all belong to ONE student; mixing handles is a hard error.
Duration policy: sum of per-session active spans, never wall-clock across gaps.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from batch_lib import BatchError, read_json  # noqa: E402


def _span_minutes(events: list[dict], started_at: str | None) -> float:
    stamps = [e.get("ts") for e in events if e.get("ts")]
    if started_at:
        stamps.append(started_at)
    stamps = sorted(s for s in stamps if isinstance(s, str))
    if len(stamps) < 2:
        return 1.0
    from datetime import datetime

    def parse(t: str):
        dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=None)

    try:
        a, b = parse(stamps[0]), parse(stamps[-1])
        return max(1.0, (b - a).total_seconds() / 60)
    except (ValueError, TypeError):
        return 1.0


def merge_student_date(session_dirs: list[Path], out_dir: Path) -> dict:
    if not session_dirs:
        raise BatchError("병합할 세션이 없습니다.")
    students = {d.parent.parent.name for d in session_dirs}
    if len(students) != 1:
        raise BatchError(f"타 아동 격리 위반: 한 병합에 학생 {sorted(students)}이 섞였습니다.")
    student = students.pop()

    per_session: list[tuple[str, str, dict, list[dict]]] = []  # (started_at, sid, meta, events)
    for d in sorted(session_dirs, key=lambda p: p.name):
        meta = read_json(d / "session.meta.json") if (d / "session.meta.json").exists() else {}
        events: list[dict] = []
        for line_no, line in enumerate((d / "events.jsonl").read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BatchError(f"{d.name}/events.jsonl:{line_no} JSONL 오류 — 세션 병합 거부") from exc
            if not isinstance(obj, dict):
                raise BatchError(f"{d.name}/events.jsonl:{line_no} 객체가 아님 — 세션 병합 거부")
            obj["_src_session"] = d.name
            obj["_src_line"] = line_no
            events.append(obj)
        started = str(meta.get("started_at") or "")
        per_session.append((started, d.name, meta, events))

    per_session.sort(key=lambda t: (t[0], t[1]))
    merged_events: list[dict] = []
    for started, sid, _meta, events in per_session:
        for e in events:
            merged_events.append(e)
    merged_events.sort(key=lambda e: (str(e.get("ts") or ""), str(e.get("_src_session")), int(e["_src_line"])))

    source_ids = [sid for _, sid, _, _ in per_session]
    merged_id = "merged-" + hashlib.sha256("|".join(source_ids).encode()).hexdigest()[:12]
    active_minutes = round(sum(_span_minutes(ev, st or None) for st, _, _, ev in per_session))

    base_meta = per_session[0][2]
    merged_meta = {
        "schema_version": base_meta.get("schema_version", 1),
        "session_id": merged_id,
        "started_at": per_session[0][0] or base_meta.get("started_at"),
        "app_version": base_meta.get("app_version"),
        "user": base_meta.get("user") or base_meta.get("identity"),
        "merge": {"source_sessions": source_ids, "active_minutes": active_minutes,
                  "policy": "same-student same-date sessions merged; duration = sum of spans"},
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    for e in merged_events:
        clean = {k: v for k, v in e.items() if not k.startswith("_src")}
        lines.append(json.dumps(clean, ensure_ascii=False))
    (out_dir / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out_dir / "session.meta.json").write_text(
        json.dumps(merged_meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return {"student": student, "merged_id": merged_id, "sources": source_ids,
            "events": len(merged_events), "active_minutes": active_minutes, "out": str(out_dir)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="같은 학생·같은 날짜 세션 병합")
    ap.add_argument("session_dirs", nargs="+", type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)
    try:
        print(json.dumps(merge_student_date(list(args.session_dirs), args.out), ensure_ascii=False))
        return 0
    except BatchError as exc:
        print(f"HAIN7_BATCH_ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

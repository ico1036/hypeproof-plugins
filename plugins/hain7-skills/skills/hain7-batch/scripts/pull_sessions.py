#!/usr/bin/env python3
"""PULL — Supabase storage → local mirror. Single responsibility: transport + integrity.

Deterministic given bucket state. Idempotent: a session already mirrored with an intact
manifest is skipped. A session that fails checksum verification is quarantined in the
inventory (never scored) — integrity failures on a child's record must be loud.

Usage: pull_sessions.py --project-ref REF [--bucket session-logs] [--mirror DIR]
Prints a JSON inventory to stdout.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from batch_lib import (  # noqa: E402
    BatchError, batch_home, link_dir, linked_ref, run_cli, verify_manifest,
)


def linked_flags(project_ref: str) -> list[str]:
    """Storage subcommands take the project from a linked workdir, not --project-ref.
    Assert the link points where the caller asked: a stale link would otherwise pull
    another class's children into this mirror without a word."""
    workdir = link_dir()
    actual = linked_ref(workdir)
    if actual is None:
        raise BatchError(
            f"{workdir} 가 링크되지 않았습니다. 실제 터미널에서 1회 실행하세요: "
            f"mkdir -p {workdir} && cd {workdir} && supabase init && "
            f"supabase link --project-ref {project_ref}"
        )
    if actual != project_ref:
        raise BatchError(
            f"링크된 프로젝트가 요청과 다릅니다 — {workdir} → {actual}, 요청 → {project_ref}. "
            "다시 link 하거나 HAIN7_SUPABASE_WORKDIR 로 올바른 디렉터리를 지정하세요."
        )
    return ["--linked", "--workdir", workdir]


def list_bucket(project_ref: str, bucket: str) -> list[str]:
    out = run_cli(
        ["storage", "ls", f"ss:///{bucket}/", "--recursive", "--experimental",
         *linked_flags(project_ref)], timeout=120,
    )
    try:
        return list(json.loads(out).get("paths", []))
    except json.JSONDecodeError as exc:
        raise BatchError(f"storage ls 출력 파싱 실패: {out[:200]}") from exc


def parse_session_paths(paths: list[str], bucket: str) -> dict[tuple[str, str, str, str], list[str]]:
    """/{bucket}/{class}/{student}/{date}/{session}/{file} → grouped by session."""
    sessions: dict[tuple[str, str, str, str], list[str]] = {}
    for raw in paths:
        parts = [p for p in raw.split("/") if p]
        if len(parts) != 6 or parts[0] != bucket:
            continue
        _, class_id, student, date, session_id, filename = parts
        sessions.setdefault((class_id, student, date, session_id), []).append(filename)
    return sessions


def pull(project_ref: str, bucket: str, mirror: Path) -> dict:
    sessions = parse_session_paths(list_bucket(project_ref, bucket), bucket)
    inventory: dict = {"project_ref": project_ref, "bucket": bucket, "mirror": str(mirror),
                       "sessions": [], "quarantined": [], "skipped_cached": 0}
    for (class_id, student, date, session_id), files in sorted(sessions.items()):
        dest = mirror / class_id / student / date / session_id
        record = {"class": class_id, "student": student, "date": date,
                  "session_id": session_id, "files": sorted(files), "path": str(dest)}
        if dest.exists() and not verify_manifest(dest):
            inventory["skipped_cached"] += 1
            inventory["sessions"].append(record)
            continue
        # CLI cp -r appends the remote dir name under the target, so download into the
        # DATE dir and let it create {session_id}/ — otherwise files nest one level deep.
        dest.parent.mkdir(parents=True, exist_ok=True)
        run_cli(["storage", "cp", "-r",
                 f"ss:///{bucket}/{class_id}/{student}/{date}/{session_id}/",
                 str(dest.parent) + "/", "--experimental",
                 *linked_flags(project_ref)], timeout=300)
        problems = verify_manifest(dest)
        if problems:
            inventory["quarantined"].append({**record, "problems": problems})
        else:
            inventory["sessions"].append(record)
    students: dict[str, dict] = {}
    for s in inventory["sessions"]:
        entry = students.setdefault(s["student"], {"class": s["class"], "sessions": 0, "dates": set()})
        entry["sessions"] += 1
        entry["dates"].add(s["date"])
    inventory["students"] = {
        h: {"class": v["class"], "sessions": v["sessions"], "dates": sorted(v["dates"])}
        for h, v in sorted(students.items())
    }
    return inventory


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Supabase session-logs → local mirror")
    ap.add_argument("--project-ref", required=True)
    ap.add_argument("--bucket", default="session-logs")
    ap.add_argument("--mirror", type=Path, default=None)
    args = ap.parse_args(argv)
    mirror = args.mirror or (batch_home() / "mirror")
    try:
        print(json.dumps(pull(args.project_ref, args.bucket, mirror), ensure_ascii=False, indent=1))
        return 0
    except BatchError as exc:
        print(f"HAIN7_BATCH_ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

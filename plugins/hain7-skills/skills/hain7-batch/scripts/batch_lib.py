#!/usr/bin/env python3
"""Shared deterministic helpers for hain7-batch. No LLM, no randomness, no network
except through the supabase CLI wrapper in pull_sessions.py."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SKILL_DIR = Path(__file__).resolve().parent.parent


class BatchError(RuntimeError):
    """Expected, message-first failure."""


def report_skill_dir() -> Path:
    """hain7-report location: env override, then sibling skill (shareable install)."""
    env = os.environ.get("HAIN7_REPORT_DIR")
    if env:
        p = Path(env).expanduser()
        if (p / "scripts" / "hain7_signal.py").exists():
            return p
        raise BatchError(f"HAIN7_REPORT_DIR에 hain7-report가 없습니다: {p}")
    sibling = SKILL_DIR.parent / "hain7-report"
    if (sibling / "scripts" / "hain7_signal.py").exists():
        return sibling
    raise BatchError(
        "hain7-report 스킬을 찾지 못했습니다. hain7-batch와 같은 skills/ 아래 설치하거나 "
        "HAIN7_REPORT_DIR로 지정하세요."
    )


def load_signal_module():
    sys.path.insert(0, str(report_skill_dir() / "scripts"))
    import hain7_signal  # noqa: PLC0415

    return hain7_signal


def default_deploy() -> dict:
    """Zero-config: env HAIN7_SUPABASE_REF > references/deploy.json. The project ref is
    not a secret (it appears in every client URL); access control is Supabase org
    membership + the operator's own `supabase login`."""
    import os as _os
    ref = _os.environ.get("HAIN7_SUPABASE_REF")
    dep = SKILL_DIR / "references" / "deploy.json"
    cfg = {}
    if dep.exists():
        try:
            cfg = json.loads(dep.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cfg = {}
    return {"project_ref": ref or cfg.get("project_ref"), "bucket": cfg.get("bucket", "session-logs")}


def batch_home() -> Path:
    return Path(os.environ.get("HAIN7_BATCH_HOME", "~/HypeProof/hain7-batch")).expanduser()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BatchError(f"파일이 없습니다: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BatchError(f"JSON 형식 오류: {path}:{exc.lineno}") from exc
    if not isinstance(value, dict):
        raise BatchError(f"JSON 최상위는 객체여야 합니다: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


HANDLE_PATTERN = re.compile(r"^SK(\d)(\d)-[A-Z0-9]+-\d+$")


def grade_band_from_handle(handle: str) -> str | None:
    """SK56-XXXXXX-07 → 초등 5-6. Returns None (never guesses) on unknown shapes."""
    m = HANDLE_PATTERN.match(handle)
    if not m:
        return None
    low, high = int(m.group(1)), int(m.group(2))
    if not 1 <= low <= high <= 6:
        return None
    return f"초등 {low}-{high}"


def verify_manifest(session_dir: Path) -> list[str]:
    """Return list of problems; empty list = intact. Missing manifest is a problem:
    without checksums we cannot attest integrity of a child's record."""
    problems: list[str] = []
    manifest = session_dir / "manifest.json"
    if not manifest.exists():
        return [f"manifest.json 없음: {session_dir.name}"]
    try:
        entries = read_json(manifest).get("files", [])
    except BatchError as exc:
        return [str(exc)]
    for entry in entries:
        name, expected = str(entry.get("name", "")), str(entry.get("sha256", ""))
        target = session_dir / name
        if not target.exists():
            problems.append(f"{session_dir.name}/{name}: 파일 없음")
        elif sha256_file(target) != expected:
            problems.append(f"{session_dir.name}/{name}: 체크섬 불일치")
    return problems


def run_cli(args: list[str], timeout: int = 300) -> str:
    """supabase CLI wrapper. Fails with actionable Korean messages."""
    try:
        proc = subprocess.run(
            ["supabase", *args], capture_output=True, text=True, timeout=timeout, check=False
        )
    except FileNotFoundError as exc:
        raise BatchError(
            "supabase CLI가 없습니다. https://github.com/supabase/cli/releases 에서 설치 후 "
            "`supabase login`을 실행하세요."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise BatchError(f"supabase {' '.join(args[:2])} 시간 초과({timeout}s)") from exc
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout).strip()
        if "login" in err.lower() or "access token" in err.lower():
            raise BatchError("Supabase 미로그인 상태입니다. 실제 터미널에서 `supabase login`을 실행하세요.")
        raise BatchError(f"supabase {' '.join(args[:2])} 실패: {err[:300]}")
    return proc.stdout

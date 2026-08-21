#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import batch_lib as bl  # noqa: E402
import qa_lint  # noqa: E402
import merge_sessions as ms  # noqa: E402
from merge_sessions import merge_student_date  # noqa: E402
from pull_sessions import parse_session_paths  # noqa: E402
from render_html import build_html  # noqa: E402
from run_batch import build_real_context, screen_groups  # noqa: E402

hs = bl.load_signal_module()


def make_session(root: Path, student: str, date: str, sid: str, events: list[dict],
                 started: str = "2026-08-21T09:00:00.000Z") -> Path:
    d = root / "class-a" / student / date / sid
    d.mkdir(parents=True)
    (d / "events.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n", encoding="utf-8")
    (d / "session.meta.json").write_text(json.dumps(
        {"schema_version": 1, "session_id": sid, "started_at": started,
         "app_version": "0.1.49", "user": {"u": student, "c": "class-a", "p": "kids-grade-5-6-s1"}}
    ), encoding="utf-8")
    return d


EV1 = [{"schema_version": 1, "ts": "2026-08-21T09:00:01Z", "type": "prompt", "turn_id": "a",
        "text": "초보 친구가 3분 안에 즐길 미로 게임 만들래. 별 5개 모으면 성공이야."},
       {"schema_version": 1, "ts": "2026-08-21T09:00:05Z", "type": "response", "turn_id": "a",
        "status": "ok", "text": "ok"},
       {"schema_version": 1, "ts": "2026-08-21T09:00:06Z", "type": "artifact_snapshot", "turn_id": "a",
        "source": "assistant_response", "sha256": "h1", "content_bytes": 10}]
EV2 = [{"schema_version": 1, "ts": "2026-08-21T10:00:01Z", "type": "prompt", "turn_id": "b",
        "text": "벽에 닿으면 멈추는 버그가 있어. 그 부분만 고치고 나머지는 유지해줘."},
       {"schema_version": 1, "ts": "2026-08-21T10:00:09Z", "type": "artifact_snapshot", "turn_id": "b",
        "source": "assistant_response", "sha256": "h2", "content_bytes": 12}]


class MergeTests(unittest.TestCase):
    def test_merge_is_deterministic_and_order_independent(self) -> None:
        outs = []
        for order in ([EV1, EV2], [EV2, EV1]):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                d1 = make_session(root, "SK56-AAAAAA-01", "2026-08-21", "s-001", order[0],
                                  "2026-08-21T09:00:00Z" if order[0] is EV1 else "2026-08-21T10:00:00Z")
                d2 = make_session(root, "SK56-AAAAAA-01", "2026-08-21", "s-002", order[1],
                                  "2026-08-21T10:00:00Z" if order[1] is EV2 else "2026-08-21T09:00:00Z")
                out = root / "merged"
                # 입력 디렉토리 순서도 뒤집어 전달
                merge_student_date([d2, d1], out)
                outs.append((out / "events.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(outs[0], outs[1], "세션 생성/전달 순서와 무관하게 병합 결과 동일해야 함")

    def test_span_survives_mixed_offsets_and_bad_stamps(self) -> None:
        """오프셋이 섞이거나 스탬프 하나가 안 읽힌다고 수업이 1분이 되면 안 된다."""
        base = [
            {"ts": "2026-08-19T05:00:00Z", "type": "prompt"},
            {"ts": "2026-08-19T14:30:00+09:00", "type": "prompt"},   # = 05:30Z
            {"ts": "2026-08-19T06:00:00", "type": "prompt"},          # bare → UTC
        ]
        self.assertEqual(round(ms._span_minutes(base, None)), 60)
        noisy = base + [{"ts": "yesterday", "type": "prompt"}, {"ts": 1755576000, "type": "prompt"}]
        self.assertEqual(round(ms._span_minutes(noisy, None)), 60,
                         "못 읽는 스탬프는 그것만 제외해야 한다")

    def test_merge_duration_is_sum_of_spans_not_wallclock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d1 = make_session(root, "SK56-AAAAAA-01", "2026-08-21", "s-001", EV1, "2026-08-21T09:00:00Z")
            d2 = make_session(root, "SK56-AAAAAA-01", "2026-08-21", "s-002", EV2, "2026-08-21T10:00:00Z")
            info = merge_student_date([d1, d2], root / "m")
            # 세션1 구간 ~6초→1분, 세션2 ~9초→1분: 합 2분. 벽시계(9시~10시=60분)가 아님
            self.assertLessEqual(info["active_minutes"], 5, "점심시간 낀 wall-clock이면 안 됨")

    def test_merge_rejects_mixed_students(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d1 = make_session(root, "SK56-AAAAAA-01", "2026-08-21", "s-001", EV1)
            d2 = make_session(root, "SK56-BBBBBB-02", "2026-08-21", "s-002", EV2)
            with self.assertRaisesRegex(bl.BatchError, "격리"):
                merge_student_date([d1, d2], root / "m")

    def test_merge_rejects_non_utf8_bytes(self) -> None:
        """잘못된 바이트 1개가 배치 전체를 트레이스백으로 죽이면 안 된다."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "class-a" / "SK56-AAAAAA-01" / "2026-08-21" / "s1"
            d.mkdir(parents=True)
            (d / "session.meta.json").write_text("{}", encoding="utf-8")
            (d / "events.jsonl").write_bytes(b'{"ts":"2026-08-21T00:00:00Z"}\n\xff\xfe bad\n')
            with self.assertRaises(bl.BatchError) as ctx:
                merge_student_date([d], Path(tmp) / "merged")
            self.assertIn("UTF-8", str(ctx.exception))

    def test_merge_rejects_malformed_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = make_session(root, "SK56-AAAAAA-01", "2026-08-21", "s-001", EV1)
            (d / "events.jsonl").write_text('{"type":"prompt"}\n{broken\n', encoding="utf-8")
            with self.assertRaisesRegex(bl.BatchError, "JSONL"):
                merge_student_date([d], root / "m")


class RosterTests(unittest.TestCase):
    def test_parse_session_paths_groups_and_ignores_junk(self) -> None:
        paths = [
            "/session-logs/class-a/SK56-X-07/2026-08-21/sid-1/events.jsonl",
            "/session-logs/class-a/SK56-X-07/2026-08-21/sid-1/manifest.json",
            "/session-logs/class-a/SK56-X-10/2026-08-21/sid-2/events.jsonl",
            "/session-logs/stray-file.txt",
            "/other-bucket/class/st/date/sid/events.jsonl",
        ]
        groups = parse_session_paths(paths, "session-logs")
        self.assertEqual(len(groups), 2)
        self.assertEqual(sorted(groups[("class-a", "SK56-X-07", "2026-08-21", "sid-1")]),
                         ["events.jsonl", "manifest.json"])

    def test_grade_band_from_handle(self) -> None:
        self.assertEqual(bl.grade_band_from_handle("SK56-EXAMPL-07"), "초등 5-6")
        self.assertEqual(bl.grade_band_from_handle("SK34-SAMPLE-07"), "초등 3-4")
        self.assertIsNone(bl.grade_band_from_handle("김하늘"))
        self.assertIsNone(bl.grade_band_from_handle("SK99-X-01"), "9-9학년은 존재하지 않음")


class ContextTests(unittest.TestCase):
    CFG = {"class_id": "class-a", "lesson_title": "게임", "curriculum_id": "kids", "task_version": "s1",
           "privacy": {"guardian_consent_verified": True,
                       "guardian_consent_verified_at": "2026-08-20T09:00:00+09:00",
                       "child_notice_version": "v1", "purpose": "lesson_feedback",
                       "correction_contact": "admin"},
           "students": {"SK56-X-07": {"age": 12}}}

    def test_real_context_from_recorded_consent(self) -> None:
        ctx = build_real_context(self.CFG, "SK56-X-07", "2026-08-21", 45, "0.1.49")
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx["participant"]["grade_band"], "초등 5-6")
        self.assertEqual(ctx["lesson"]["duration_minutes"], 45)
        self.assertTrue(hs.distribution_allowed(ctx))

    def test_unlisted_student_degrades_to_diagnostic(self) -> None:
        self.assertIsNone(build_real_context(self.CFG, "SK56-X-99", "2026-08-21", 45, "0.1.49"),
                          "명부에 없는 학생은 real 컨텍스트를 받으면 안 됨")

    def test_direct_identifier_handle_is_refused(self) -> None:
        """가명성은 코드가 확인할 성질이지, 운영자 대신 단언할 사실이 아니다."""
        cfg = json.loads(json.dumps(self.CFG))
        for handle in ("김민준 (minjun.kim@example.com)", "minjun.kim@example.com", "Minjun Kim"):
            cfg["students"] = {handle: {"age": 12, "grade_band": "초등 5-6"}}
            with self.assertRaises(bl.BatchError, msg=f"{handle} 은 거부되어야 함"):
                build_real_context(cfg, handle, "2026-08-21", 45, "0.1.49")

    def test_missing_consent_degrades_not_fabricates(self) -> None:
        cfg = json.loads(json.dumps(self.CFG))
        cfg["privacy"]["guardian_consent_verified"] = False
        self.assertIsNone(build_real_context(cfg, "SK56-X-07", "2026-08-21", 45, "0.1.49"),
                          "동의 미기록이면 강등이지 조작이 아님")


class LintTests(unittest.TestCase):
    def _analysis(self):
        skill = bl.report_skill_dir()
        events, raw = hs.load_events(skill / "examples/sample-session/events.jsonl")
        meta = hs.read_json(skill / "examples/sample-session/session.meta.json")
        ctx = hs.read_json(skill / "examples/sample-context.json")
        return hs.assemble_analysis(events, raw, meta, ctx, None, None)

    def test_clean_artifact_passes(self) -> None:
        analysis = self._analysis()
        page = build_html(analysis)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "r.html"
            p.write_text(page, encoding="utf-8")
            self.assertEqual(qa_lint.lint_html(p), [], "정상 산출물은 린트 통과")

    def test_lint_catches_violations(self) -> None:
        analysis = self._analysis()
        page = build_html(analysis)
        cases = {
            "L1": page.replace("함께 빛난 힘", "부족한 힘"),
            "L2": page.replace("한눈에", "또래 대비 한눈에"),
            "L3": page.replace('<span class="score">90</span>', '<span class="score">42</span>'),
            "L4": page.replace("기본 구간", "구간"),
            "L6": page.replace('class="fill ', 'class="fill dim '),
        }
        with tempfile.TemporaryDirectory() as tmp:
            for lid, mutated in cases.items():
                p = Path(tmp) / f"{lid}.html"
                p.write_text(mutated, encoding="utf-8")
                problems = qa_lint.lint_html(p)
                self.assertTrue(any(lid in pr for pr in problems), f"{lid} 위반을 놓침: {problems}")

    def test_lint_catches_cross_child(self) -> None:
        analysis = self._analysis()
        page = build_html(analysis).replace("</body>", "<p>SK56-OTHER-99</p><p>SK34-XX-01</p></body>")
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.html"
            p.write_text(page, encoding="utf-8")
            self.assertTrue(any("L5" in pr for pr in qa_lint.lint_html(p)))


class RenderTests(unittest.TestCase):
    def test_render_refuses_zero_observed(self) -> None:
        skill = bl.report_skill_dir()
        analysis = json.loads(json.dumps({"axes": {c: {"display_basis": None, "display_value": None}
                                                   for c in hs.AXES}, "insights": {}}))
        with self.assertRaisesRegex(bl.BatchError, "짧아"):
            build_html(analysis)

    def test_render_refuses_undistributable_without_diagnostic_flag(self) -> None:
        skill = bl.report_skill_dir()
        spool = Path.home() / "Library/Application Support/HypeProof-Studio/logs/sessions"
        candidates = list(spool.rglob("events.jsonl"))
        if not candidates:
            self.skipTest("실스풀 없음")
        p = candidates[0]
        events, raw = hs.load_events(p)
        meta = hs.read_json(p.parent / "session.meta.json")
        ctx = hs.derive_context(meta, events, p)
        analysis = hs.assemble_analysis(events, raw, meta, ctx, None, None)
        if not any(ax.get("display_basis") == "observed" for ax in analysis["axes"].values()):
            self.skipTest("관측 축 없는 세션")
        with self.assertRaisesRegex(bl.BatchError, "배포 불가"):
            build_html(analysis, diagnostic=False)
        page = build_html(analysis, diagnostic=True)
        self.assertIn("내부 점검용", page)


class ManifestTests(unittest.TestCase):
    def test_checksum_mismatch_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "events.jsonl").write_text("{}\n", encoding="utf-8")
            good = bl.sha256_file(d / "events.jsonl")
            (d / "manifest.json").write_text(json.dumps(
                {"files": [{"name": "events.jsonl", "sha256": good}]}), encoding="utf-8")
            self.assertEqual(bl.verify_manifest(d), [])
            (d / "events.jsonl").write_text("{tampered}\n", encoding="utf-8")
            self.assertTrue(any("체크섬" in p for p in bl.verify_manifest(d)))

    def test_missing_manifest_is_a_problem(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(bl.verify_manifest(Path(tmp)))


class IntegrityGateTests(unittest.TestCase):
    """격리는 기록이 아니라 강제다 — 채점 직전에 매 실행 검증한다."""

    def _session(self, root: Path, student: str, date: str, sid: str, tamper: bool) -> Path:
        d = root / "class-a" / student / date / sid
        d.mkdir(parents=True)
        (d / "session.meta.json").write_text("{}", encoding="utf-8")
        (d / "events.jsonl").write_text('{"ts":"2026-08-21T00:00:00Z","type":"prompt"}\n',
                                        encoding="utf-8")
        digest = bl.sha256_file(d / "events.jsonl")
        if tamper:
            digest = "0" * 64
        (d / "manifest.json").write_text(json.dumps(
            {"files": [{"name": "events.jsonl", "sha256": digest}]}), encoding="utf-8")
        return d

    def test_tampered_session_is_dropped_before_scoring(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = self._session(root, "SK56-AAAAAA-01", "2026-08-21", "s1", tamper=True)
            good = self._session(root, "SK56-BBBBBB-02", "2026-08-21", "s2", tamper=False)
            groups = {("SK56-AAAAAA-01", "2026-08-21"): [bad],
                      ("SK56-BBBBBB-02", "2026-08-21"): [good]}
            quarantined = screen_groups(groups)
            self.assertEqual(len(quarantined), 1)
            self.assertIn("체크섬", " ".join(quarantined[0]["problems"]))
            self.assertNotIn(("SK56-AAAAAA-01", "2026-08-21"), groups)
            self.assertEqual(groups[("SK56-BBBBBB-02", "2026-08-21")], [good])

    def test_missing_manifest_session_is_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = self._session(root, "SK56-AAAAAA-01", "2026-08-21", "s1", tamper=False)
            (d / "manifest.json").unlink()
            groups = {("SK56-AAAAAA-01", "2026-08-21"): [d]}
            self.assertEqual(len(screen_groups(groups)), 1)
            self.assertFalse(groups)


if __name__ == "__main__":
    unittest.main(verbosity=1)

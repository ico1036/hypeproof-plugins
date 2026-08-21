#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

import hain7_signal as hs  # noqa: E402


class Hain7SignalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.context = hs.read_json(SKILL_DIR / "examples" / "sample-context.json")
        cls.cohort = hs.read_json(SKILL_DIR / "examples" / "sample-cohort.json")
        events_path = SKILL_DIR / "examples" / "sample-session" / "events.jsonl"
        cls.events, cls.raw = hs.load_events(events_path)
        cls.meta = hs.read_json(SKILL_DIR / "examples" / "sample-session" / "session.meta.json")

    def fresh_analysis(self, cohort: dict | None = None, review: dict | None = None) -> dict:
        events = copy.deepcopy(self.events)
        return hs.assemble_analysis(
            events,
            self.raw,
            copy.deepcopy(self.meta),
            copy.deepcopy(self.context),
            copy.deepcopy(cohort),
            copy.deepcopy(review),
        )

    def test_sample_scores_all_axes_without_scoring_ai_prose(self) -> None:
        analysis = self.fresh_analysis(self.cohort)
        self.assertEqual(list(analysis["axes"]), list(hs.AXES))
        self.assertTrue(all(axis["score"] is not None for axis in analysis["axes"].values()))
        self.assertEqual(analysis["data_summary"]["prompt_turn_count"], 9)
        self.assertEqual(analysis["data_summary"]["response_turn_coverage"], 1.0)
        for axis in analysis["axes"].values():
            for marker in axis["markers"]:
                self.assertFalse(any(evidence_id.startswith("R") for evidence_id in marker["evidence_ids"]))

    def test_synthetic_same_condition_cohort_gate(self) -> None:
        analysis = self.fresh_analysis(self.cohort)
        peer = analysis["peer_comparison"]
        self.assertTrue(peer["available"])
        self.assertEqual(peer["n"], 36)
        self.assertFalse(peer["national_norm"])
        self.assertTrue(peer["synthetic"])
        self.assertIn("top_percent", peer["axes"]["VE"])
        self.assertGreaterEqual(peer["axes"]["VE"]["top_percent"], 3, "36명 표본을 상위 1%처럼 과도하게 정밀 표기하면 안 됨")

    def test_mismatched_cohort_is_withheld_not_guessed(self) -> None:
        cohort = copy.deepcopy(self.cohort)
        cohort["norm_key"]["task_version"] = "different-task"
        analysis = self.fresh_analysis(cohort)
        self.assertFalse(analysis["peer_comparison"]["available"])
        self.assertIn("일치하지", analysis["peer_comparison"]["reason"])

    def test_small_cohort_is_withheld(self) -> None:
        cohort = copy.deepcopy(self.cohort)
        cohort["records"] = cohort["records"][:29]
        analysis = self.fresh_analysis(cohort)
        self.assertFalse(analysis["peer_comparison"]["available"])
        self.assertEqual(analysis["peer_comparison"]["n"], 29)

    def test_under_14_real_data_fails_without_guardian_consent(self) -> None:
        context = copy.deepcopy(self.context)
        context["synthetic"] = False
        context["privacy"]["guardian_consent_verified"] = False
        context["privacy"]["guardian_consent_verified_at"] = None
        with self.assertRaisesRegex(hs.SignalError, "법정대리인"):
            hs.validate_context(context)

    def test_real_data_requires_pseudonymous_display_id_attestation(self) -> None:
        context = copy.deepcopy(self.context)
        context["synthetic"] = False
        context["participant"]["pseudonymous"] = False
        with self.assertRaisesRegex(hs.SignalError, "가명"):
            hs.validate_context(context)

    def test_real_data_review_covers_all_markers_and_matches_fingerprint(self) -> None:
        context = copy.deepcopy(self.context)
        context["synthetic"] = False
        context["privacy"].update(
            {
                "guardian_consent_verified": True,
                "guardian_consent_verified_at": "2026-08-18T10:00:00+09:00",
            }
        )
        hs.validate_context(context)
        events = copy.deepcopy(self.events)
        candidate = hs.assemble_analysis(events, self.raw, self.meta, context, None, None)
        review = {
            "schema_version": "1.0",
            "session_fingerprint": candidate["session_fingerprint"],
            "reviewer_type": "facilitator_assisted",
            "completed_at": "2026-08-19T12:00:00+09:00",
            "reviewed_marker_ids": list(hs.MARKER_TITLES),
            "overrides": [],
        }
        reviewed = hs.assemble_analysis(copy.deepcopy(self.events), self.raw, self.meta, context, None, review)
        self.assertEqual(reviewed["review"]["reviewed_marker_count"], 28)
        bad = copy.deepcopy(review)
        bad["session_fingerprint"] = "0" * 64
        with self.assertRaisesRegex(hs.SignalError, "fingerprint"):
            hs.assemble_analysis(copy.deepcopy(self.events), self.raw, self.meta, context, None, bad)

    def test_no_opportunity_is_na_not_zero(self) -> None:
        minimal = [
            {
                "type": "prompt",
                "turn_id": "one",
                "text": "버튼 하나 만들어줘",
                "_line": 1,
                "_evidence_id": "P01",
            }
        ]
        markers = hs.score_markers(minimal)
        self.assertIsNone(markers["CO3"]["score"])
        self.assertIsNone(markers["IT1"]["score"])
        self.assertIsNone(markers["OW2"]["score"])

    def test_auto_context_derives_norm_key_fields_from_session_log(self) -> None:
        meta = {
            "schema_version": 1,
            "session_id": "abc",
            "user": {"u": "kq-test-3-4", "c": "class-a", "p": "kids-2026-grade-3-4-s1"},
            "app_version": "0.1.45",
            "started_at": "2026-08-19T07:10:22.420Z",
        }
        events = [
            {"type": "prompt", "ts": "2026-08-19T07:10:22.471Z", "text": "초코 세상에 가볼래", "_line": 1},
            {"type": "usage", "ts": "2026-08-19T07:10:29.659Z", "model": "claude-sonnet-4-6", "_line": 2},
            {"type": "prompt", "ts": "2026-08-19T07:22:14.298Z", "text": "태양을 파란색으로", "_line": 3},
        ]
        path = Path("/spool/2026-08-19/abc/events.jsonl")
        context = hs.derive_context(meta, events, path)
        hs.validate_context(context)
        self.assertEqual(context["participant"]["grade_band"], "초등 3-4")
        self.assertEqual(context["participant"]["display_id"], "kq-test-3-4")
        self.assertIsNone(context["participant"]["age"], "나이는 로그에 없으므로 추정하면 안 됨")
        self.assertEqual(context["lesson"]["curriculum_id"], "kids-2026-grade-3-4")
        self.assertEqual(context["lesson"]["task_version"], "s1")
        self.assertEqual(context["lesson"]["duration_minutes"], 12)
        self.assertEqual(context["lesson"]["duration_band"], "0-20m")
        self.assertEqual(context["lesson"]["tool_version"], "hp-studio-0.1.45")
        self.assertEqual(context["lesson"]["language"], "ko")
        self.assertEqual(context["lesson"]["date"], "2026-08-19")
        self.assertEqual(set(hs.context_norm_key(context)), set(hs.NORM_KEY_FIELDS))

    def test_auto_context_never_yields_a_distributable_report(self) -> None:
        meta = {"user": {"u": "handle-1", "p": "kids-grade-5-6-s2"}, "app_version": "0.1.45"}
        events = [{"type": "prompt", "ts": "2026-08-19T07:10:22Z", "text": "게임 만들어줘", "_line": 1}]
        context = hs.derive_context(meta, events, Path("/spool/2026-08-19/abc/events.jsonl"))
        self.assertFalse(hs.distribution_allowed(context))
        with tempfile.TemporaryDirectory() as temp_dir:
            code = hs.main(
                [
                    "--input",
                    str(SKILL_DIR / "examples" / "sample-session"),
                    "--pdf-output",
                    str(Path(temp_dir) / "out.pdf"),
                ]
            )
            self.assertEqual(code, 2, "동의 기록 없는 자동 컨텍스트로 PDF가 나오면 안 됨")

    def test_auto_context_refuses_to_attest_pseudonymity_for_a_real_name(self) -> None:
        meta = {"user": {"u": "김하늘", "p": "kids-grade-3-4-s1"}, "app_version": "0.1.45"}
        events = [{"type": "prompt", "ts": "2026-08-19T07:10:22Z", "text": "게임", "_line": 1}]
        context = hs.derive_context(meta, events, Path("/spool/2026-08-19/abc/events.jsonl"))
        self.assertFalse(context["participant"]["pseudonymous"])
        with self.assertRaisesRegex(hs.SignalError, "가명"):
            hs.validate_context(context)

    def test_cli_runs_on_a_bare_session_without_a_context_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "analysis.json"
            code = hs.main(
                ["--input", str(SKILL_DIR / "examples" / "sample-session"), "--analysis-output", str(output)]
            )
            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["context_source"], hs.AUTO_CONTEXT_SOURCE)
            self.assertFalse(payload["distribution_allowed"])
            self.assertTrue(any("자동 추출" in warning for warning in payload["warnings"]))

    def test_auto_context_survives_mixed_timezone_stamps(self) -> None:
        events = [
            {"type": "prompt", "ts": "2026-08-19T07:10:22Z", "text": "게임 만들어줘", "_line": 1},
            {"type": "prompt", "ts": "2026-08-19T07:20:15", "text": "색을 바꿔줘", "_line": 2},
        ]
        context = hs.derive_context({"app_version": "0.1.45"}, events, Path("/s/2026-08-19/a/events.jsonl"))
        self.assertEqual(context["lesson"]["duration_minutes"], 10)

    def test_auto_context_clamps_an_overnight_log_span(self) -> None:
        events = [
            {"type": "prompt", "ts": "2026-08-19T01:00:00Z", "text": "시작", "_line": 1},
            {"type": "prompt", "ts": "2026-08-19T23:30:00Z", "text": "끝", "_line": 2},
        ]
        context = hs.derive_context({"app_version": "0.1.45"}, events, Path("/s/2026-08-19/a/events.jsonl"))
        self.assertEqual(context["lesson"]["duration_minutes"], hs.MAX_LESSON_MINUTES)
        self.assertTrue(context["lesson"]["duration_clamped"])
        hs.validate_context(context)

    def test_grade_band_label_matches_korean_school_levels(self) -> None:
        self.assertEqual(hs.grade_band_label(3, 4), "초등 3-4")
        self.assertEqual(hs.grade_band_label(7, 9), "중등 1-3")
        self.assertEqual(hs.grade_band_label(10, 12), "고등 1-3")
        self.assertEqual(hs.grade_band_label(5, 7), "5-7학년")

    def test_auto_context_never_emits_empty_norm_key_fields(self) -> None:
        for program in ("-s1", "", "no-grade-here", "kids-grade-3-4-s1"):
            meta = {"user": {"u": "handle", "p": program}, "app_version": "0.1.45"}
            events = [{"type": "prompt", "ts": "2026-08-19T07:10:22Z", "text": "게임", "_line": 1}]
            context = hs.derive_context(meta, events, Path("/s/2026-08-19/a/events.jsonl"))
            hs.validate_context(context)
            for field, value in hs.context_norm_key(context).items():
                self.assertTrue(value.strip(), f"{program!r} → {field} 비어 있음")

    def test_meta_identity_reads_both_schemas_and_drops_non_scalars(self) -> None:
        block = {"u": "handle", "c": "class", "p": "prog"}
        self.assertEqual(hs.meta_identity({"user": block}), block)
        self.assertEqual(hs.meta_identity({"identity": block}), block)
        self.assertEqual(hs.meta_identity({"user": {"u": ["a"], "c": None, "p": 7}}), {"p": "7"})
        self.assertEqual(hs.meta_identity(None), {})

    def _axes_for(self, scores: dict[str, float | None]) -> dict:
        axes = {}
        for code in hs.AXES:
            axes[code] = {"score": scores.get(code)}
        hs.apply_display_index(axes)  # type: ignore[arg-type]
        return axes

    def test_display_index_min_observed_is_90_and_lead_is_100(self) -> None:
        axes = self._axes_for({"IN": 1.0, "CO": 1.3, "DE": 1.5, "IT": 2.0, "TA": 0.0, "VE": None, "OW": 0.0})
        idx = {c: axes[c]["display_index"] for c in hs.AXES}
        self.assertEqual(idx["IN"], 90, "가장 약하게 관찰된 힘이 90")
        self.assertEqual(idx["IT"], 100, "대표 강점이 100")
        self.assertEqual(idx["CO"], 93)
        self.assertEqual(idx["DE"], 95)
        self.assertIsNone(idx["TA"], "0점 축은 숫자 없음")
        self.assertIsNone(idx["VE"], "NA 축은 숫자 없음")
        observed = [v for v in idx.values() if v is not None]
        self.assertTrue(all(90 <= v <= 100 for v in observed), "발휘도는 항상 90~100")

    def test_display_index_single_or_tied_observation_is_100(self) -> None:
        axes = self._axes_for({"CO": 1.3})
        self.assertEqual(axes["CO"]["display_index"], 100)
        axes = self._axes_for({"CO": 1.0, "IN": 1.0})
        self.assertEqual(axes["CO"]["display_index"], 100)
        self.assertEqual(axes["IN"]["display_index"], 100)

    def test_display_index_order_matches_raw_scores(self) -> None:
        analysis = self.fresh_analysis()
        pairs = [(ax["score"], ax["display_index"]) for ax in analysis["axes"].values() if ax["display_index"]]
        by_raw = sorted(pairs, key=lambda t: t[0])
        by_idx = sorted(pairs, key=lambda t: t[1])
        self.assertEqual(by_raw, by_idx, "발휘도 순서는 원점수 순서와 일치해야 함")

    def test_axis_descriptions_stay_inside_char_budget(self) -> None:
        # Metric-free proxy guard (runs everywhere): the PDF row fits 2 lines x 190pt at
        # 7pt NanumGothic, which the exact-metric test below pins to <=38 Korean chars.
        for code, definition in hs.AXES.items():
            self.assertLessEqual(
                len(definition["description"]), 38, f"{code} 설명이 PDF 행 예산을 넘음"
            )

    def test_axis_descriptions_fit_pdf_row_with_real_font_metrics(self) -> None:
        try:
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
        except ImportError:
            self.skipTest("reportlab 미설치 환경 — pdfenv에서 실행됨")
        if not hs.BUNDLED_FONT.exists():
            self.fail("동봉 폰트가 없음 (R5)")
        try:
            pdfmetrics.getFont("HPSansTest")
        except KeyError:
            pdfmetrics.registerFont(TTFont("HPSansTest", str(hs.BUNDLED_FONT)))
        for code, definition in hs.AXES.items():
            lines = hs.wrap_text(definition["description"], "HPSansTest", 7.0, 190, pdfmetrics.stringWidth)
            self.assertLessEqual(len(lines), 2, f"{code} 설명이 2줄 예산 초과: {lines}")

    def test_zero_scored_axis_is_never_sold_as_strength_or_growth(self) -> None:
        markers = {}
        for mid in hs.MARKER_TITLES:
            axis = mid[:2]
            score = 1.0 if axis in ("IN", "CO") else (0.0 if axis == "VE" else None)
            markers[mid] = {
                "marker_id": mid, "title": "t", "score": score,
                "opportunity": score is not None, "evidence_ids": ["P01"] if score else [],
                "rationale": "", "source": "x",
            }
        data = {"truncated_event_count": 0, "artifact_version_count": 1, "workflow_count": 1, "prompt_turn_count": 9}
        axes = hs.axis_results(markers, data)
        insights = hs.build_insights(axes, {"available": False})
        mentioned = {i["axis"] for i in insights["strengths"] + insights["growth_priorities"]}
        self.assertNotIn("VE", mentioned, "0점 축이 강점/성장으로 인쇄되면 안 됨 (R1)")
        self.assertNotEqual(insights.get("next_challenge_axis"), "VE")
        self.assertEqual(insights["signature_axis"], "IN")

    def test_display_value_gives_unobserved_axes_the_disclosed_baseline_band(self) -> None:
        axes = self._axes_for({"IN": 1.0, "IT": 2.0, "TA": 0.0, "VE": None})
        band_top = hs.BASELINE_DISPLAY + hs.BASELINE_SPREAD - 1
        for code in ("TA", "VE"):
            self.assertEqual(axes[code]["display_basis"], "baseline")
            self.assertGreaterEqual(axes[code]["display_value"], hs.BASELINE_DISPLAY)
            self.assertLessEqual(axes[code]["display_value"], band_top, "기본 구간은 관측 최저 90 아래")
        self.assertEqual(axes["IN"]["display_value"], 90)
        self.assertEqual(axes["IN"]["display_basis"], "observed")
        self.assertEqual(axes["IT"]["display_value"], 100)
        values = [axes[c]["display_value"] for c in hs.AXES]
        self.assertTrue(all(v is not None and v >= hs.BASELINE_DISPLAY for v in values),
                        "부모 표시값은 전 축 존재하며 85 미만 금지 (R6)")

    def test_baseline_noise_is_deterministic_and_observed_axes_untouched(self) -> None:
        one = self.fresh_analysis()
        two = self.fresh_analysis()
        for code in hs.AXES:
            self.assertEqual(one["axes"][code]["display_value"], two["axes"][code]["display_value"],
                             "같은 세션 재실행이면 기본 구간 값도 동일해야 함 (결정론)")
        seeds = [hs.baseline_value(f"seed-{i}", "TA") for i in range(40)]
        self.assertGreater(len(set(seeds)), 1, "시드가 다르면 값도 흩어져야 함")
        self.assertTrue(all(hs.BASELINE_DISPLAY <= v < hs.BASELINE_DISPLAY + hs.BASELINE_SPREAD for v in seeds))
        # 관측 축 불가침: 시드가 무엇이든 관측 축 값은 90~100 지수 그대로
        a = {c: {"score": s} for c, s in {"IN": 1.0, "IT": 2.0, "TA": 0.0}.items()}
        for c in hs.AXES:
            a.setdefault(c, {"score": None})
        hs.apply_display_index(a, "seed-A")  # type: ignore[arg-type]
        b = {c: {"score": s} for c, s in {"IN": 1.0, "IT": 2.0, "TA": 0.0}.items()}
        for c in hs.AXES:
            b.setdefault(c, {"score": None})
        hs.apply_display_index(b, "seed-B")  # type: ignore[arg-type]
        self.assertEqual((a["IN"]["display_value"], a["IT"]["display_value"]), (90, 100))
        self.assertEqual((b["IN"]["display_value"], b["IT"]["display_value"]), (90, 100),
                         "시드는 기본 구간에만 작용하고 관측 축에는 영향 없음")

    def test_display_value_absent_when_nothing_observed(self) -> None:
        axes = self._axes_for({"IN": 0.0, "CO": None})
        self.assertTrue(all(axes[c]["display_value"] is None for c in hs.AXES),
                        "관측 0축이면 기본값도 발행하지 않음 (R8)")

    def test_cohort_never_reorders_parent_facing_insights(self) -> None:
        analysis = self.fresh_analysis()
        raw_lead = max(
            (ax for ax in analysis["axes"].values() if ax["score"]),
            key=lambda ax: ax["score"],
        )["code"]
        # 코호트 평균을 조작해 (구버전이라면) 또래-상대 순위가 뒤집히게 만든 뒤,
        # 대표 강점이 여전히 원점수 1위인지 확인한다 (R2/R6: 또래는 부모 카피에 불개입).
        cohort = copy.deepcopy(self.cohort)
        for record in cohort["records"]:
            for code in record["scores"]:
                record["scores"][code] = 0.5 if code != raw_lead else 4.0
        flipped = self.fresh_analysis(cohort)
        self.assertTrue(flipped["peer_comparison"]["available"], "코호트 게이트는 통과해야 검증이 성립")
        self.assertEqual(flipped["insights"]["signature_axis"], raw_lead,
                         "코호트가 대표 강점 순위를 바꾸면 안 됨")
        no_cohort = self.fresh_analysis()
        self.assertEqual(
            [s["axis"] for s in flipped["insights"]["strengths"]],
            [s["axis"] for s in no_cohort["insights"]["strengths"]],
            "강점 순서는 코호트 유무와 무관해야 함",
        )

    def test_llm_rater_is_accepted_and_unknown_types_rejected(self) -> None:
        context = copy.deepcopy(self.context)
        candidate = hs.assemble_analysis(copy.deepcopy(self.events), self.raw, self.meta, context, None, None)
        review = {
            "schema_version": "1.0", "session_fingerprint": candidate["session_fingerprint"],
            "reviewer_type": "llm_rater", "completed_at": "2026-08-21T12:00:00+09:00",
            "reviewed_marker_ids": list(hs.MARKER_TITLES), "overrides": [],
        }
        out = hs.assemble_analysis(copy.deepcopy(self.events), self.raw, self.meta, context, None, review)
        self.assertEqual(out["review"]["reviewer_type"], "llm_rater")
        bad = dict(review, reviewer_type="anonymous_bot")
        with self.assertRaisesRegex(hs.SignalError, "reviewer_type"):
            hs.assemble_analysis(copy.deepcopy(self.events), self.raw, self.meta, context, None, bad)

    def test_usage_events_are_telemetry_not_learner_evidence(self) -> None:
        events = [
            {"type": "prompt", "turn_id": "t1", "text": "태양을 파란색으로", "_line": 1},
            {"type": "usage", "turn_id": "t1", "model": "claude-sonnet-4-6", "output_tokens": 7, "_line": 2},
        ]
        index = hs.build_evidence_index(events)
        usage_entry = next(item for item in index if item["type"] == "usage")
        self.assertEqual(usage_entry["evidence_id"], "U01")
        self.assertEqual(usage_entry["role"], "telemetry")
        markers = hs.score_markers(events)
        for value in markers.values():
            self.assertNotIn("U01", value["evidence_ids"])

    def test_cli_analysis_output_is_auditable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "analysis.json"
            code = hs.main(
                [
                    "--input",
                    str(SKILL_DIR / "examples" / "sample-session"),
                    "--context",
                    str(SKILL_DIR / "examples" / "sample-context.json"),
                    "--cohort",
                    str(SKILL_DIR / "examples" / "sample-cohort.json"),
                    "--analysis-output",
                    str(output),
                ]
            )
            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["rubric_version"], hs.RUBRIC_VERSION)
            self.assertEqual(len(payload["evidence_index"]), len(self.events))
            self.assertEqual(payload["review"]["status"], "not_reviewed")


if __name__ == "__main__":
    unittest.main()

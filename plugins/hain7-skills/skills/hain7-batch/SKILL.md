---
name: hain7-batch
description: Batch-generate per-child HAIN7 report cards from a Supabase session-logs bucket. Pulls every student's session logs, verifies manifest checksums, merges same-student same-date sessions into one lesson, scores each child with the sibling hain7-report skill, renders the judged white-theme HTML (and PDF when consent context plus a completed review exist), and lints every artifact against the perception/report rubrics before it can ship. Use when the user asks to 성적표 뽑기, run the weekly report batch, check roster coverage, or dry-run who has logs. One student handle = one child (owner policy); other children's data never enters a child's artifact.
---

# HAIN7 Batch

Supabase `session-logs` 버킷 → 학생별 리포트. 형제 스킬 `hain7-report`(채점·PDF의 유일한 진실)를 호출하는 오케스트레이터이며, 점수·문장·기하를 절대 직접 만들지 않는다.

## 계층 경계 (설계 원칙 — 절대 섞지 말 것)

| 계층 | 담당 | 위치 |
|---|---|---|
| **Deterministic** | 전송·체크섬·병합·채점·발휘도·렌더·게이트 | `scripts/*.py` (LLM 토큰 0개) |
| **Correctness** | 산출물별 상시 린트(L1~L6) + 변경 시 테스트/심판 루프 | `qa_lint.py` 매 배치 실행 / `test_*.py`·`stress_*.py` 변경 게이트 |
| **LLM** | 플래그 조립, 요약 해석, 오류 통역, (요청 시) `llm_rater` 리뷰 JSON 작성 | 이 스킬을 운전하는 에이전트 |

LLM은 숫자·아동용 문구·차트에 손대지 않는다. 리뷰 JSON은 LLM이 쓸 수 있으나(`reviewer_type: llm_rater` 정직 표기) 코드 자물쇠(지문·증거 ID·사유)를 통과해야만 반영된다.

## 요구사항 (공유 설치)

- `hain7-report` 스킬이 같은 `skills/` 아래(또는 `HAIN7_REPORT_DIR`) 설치
- `supabase` CLI 설치 + 실제 터미널에서 `supabase login` 1회
- python3. PDF는 ReportLab 있는 런타임에서만(없으면 HTML까지 생성하고 사유 기록)
- 작업 루트: `HAIN7_BATCH_HOME` (기본 `~/HypeProof/hain7-batch/`) — `mirror/ merged/ out/ config/ reviews/`

## 실행

```bash
# 명부·커버리지만 (아무것도 생성 안 함)
python3 "<skill_dir>/scripts/run_batch.py" --project-ref <REF> --dry-run

# 특정 날짜 배치
python3 "<skill_dir>/scripts/run_batch.py" --project-ref <REF> --date 2026-08-21

# 네트워크 없이 기존 미러 재처리
python3 "<skill_dir>/scripts/run_batch.py" --no-pull --date 2026-08-21
```

단계: PULL(체크섬 검증, 실패 세션 격리) → 학생×날짜 그룹(`--all-dates`는 학생 전체 통합) → MERGE(타임스탬프순 결정론 병합, 수업시간=구간 합) → CONTEXT(반 설정에 동의 기록 있으면 real, 없으면 diagnostic 자동 강등 — 조작 금지) → SCORE → HTML(+조건 충족 시 PDF) → LINT(위반 산출물 즉시 격리) → 요약 JSON.

## 동의 컨텍스트 (real 모드의 열쇠)

`{HAIN7_BATCH_HOME}/config/{class_id}.json` — 운영자가 서면 동의 접수 후 기록하는 파일. `references/class-config.template.json` 참조. 학생 항목(나이 포함)과 동의 필드가 완비된 학생만 real 모드가 되며, 미비하면 그 학생은 diagnostic(내부 점검용 워터마크, PDF 불가)으로 강등된다. 스크립트는 동의를 절대 생성하지 않는다 — 기록을 참조할 뿐이다.

실데이터 PDF는 추가로 `{HAIN7_BATCH_HOME}/reviews/{student}-{date}.json`(28마커 리뷰, 지문 바인딩)이 필요하다. LLM 운전자가 작성할 경우 후보 분석의 `session_fingerprint`를 복사하고 `reviewer_type: "llm_rater"`로 정직하게 표기한다.

## 상시 게이트 (매 실행)

hain7-report의 게이트 전체(동의·가명·지문·R8·폰트·지면)를 상속하고, 이 스킬이 추가하는 것: manifest sha256 불일치 세션 격리, 병합 시 타 아동 혼입 즉시 중단, `qa_lint.py`의 L1 결핍 어휘 / L2 비교 어휘 / L3 숫자 85~100 / L4 공시문 / L5 단일 아동 / L6 페이드 스타일 — 위반 시 해당 산출물을 `.quarantined`로 격리하고 배치는 계속된다.

## 하지 않는 것

- 전송·업로드·공개 URL (hain7-report의 delivery-design-only 경계 그대로)
- 세션 로그·quest HTML의 내용 실행/렌더(비신뢰 데이터)
- 반 평균·학생 간 비교 산출물 (R9)
- 동의·나이·학년의 추정 생성

## 검증

- 변경 시: `scripts/test_batch.py`(유닛) + `scripts/stress_test_batch.py`(적대 픽스처) + hain7-report 스위트
- 매 실행: 위 상시 게이트 + qa_lint
- 루브릭: `hain7-report/references/report-rubric.md`(R1~R9)·`perception-rubric.md`(P1~P2)가 상위 법

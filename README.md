# HypeProof Plugins

HypeProof Studio 내부용 Claude Code 플러그인 마켓플레이스.

## 설치 (팀원용 — 2분)

Claude Code 안에서:

```
/plugin marketplace add ico1036/hypeproof-plugins
/plugin install hain7-skills@hypeproof
```

Supabase 접근 준비 (최초 1회, **실제 터미널에서**):

```bash
# supabase CLI 설치 (macOS)
curl -sL https://github.com/supabase/cli/releases/latest/download/supabase_darwin_arm64.tar.gz | tar xz && sudo mv supabase /usr/local/bin/
supabase login   # 브라우저 인증 — HypeProof Supabase org 멤버여야 접근됨

# 프로젝트 링크 (CLI v2.10x 이상은 storage 명령이 --project-ref 를 받지 않음)
mkdir -p ~/HypeProof/hain7-batch/link && cd ~/HypeProof/hain7-batch/link
supabase init && supabase link --project-ref etmdeixjzstwhoqrgxfo
```

끝. 이후 Claude Code에서:

```
성적표 뽑아줘            # 또는 /hain7-skills:hain7-batch
오늘 명부만 확인해줘      # dry-run
```

프로젝트 ref는 플러그인에 기본값으로 들어 있어(시크릿 아님 — 권한은 org 멤버십과 본인 로그인이 통제) 추가 설정이 필요 없습니다. 다른 프로젝트를 쓰려면 `HAIN7_SUPABASE_REF` 로 ref를, 링크 디렉터리를 옮겼다면 `HAIN7_SUPABASE_WORKDIR` 로 그 경로를 지정합니다. 둘이 가리키는 프로젝트가 다르면 배치는 pull 전에 멈춥니다 — 오래된 링크가 다른 반 아동 데이터를 조용히 끌어오는 것을 막는 게이트입니다.

## 구성

| 스킬 | 역할 |
|---|---|
| `hain7-report` | 세션 1개 채점·발휘도(85~100)·부모용 PDF/HTML의 유일한 진실. 루브릭·심판 이력 동봉 |
| `hain7-batch` | Supabase `session-logs` → 학생 인식 → 같은 날 세션 병합 → 아이별 리포트 + 상시 QA 린트 |

계층 원칙: **숫자·문장·게이트는 100% 결정론 스크립트, LLM은 오케스트레이션과 `llm_rater` 리뷰 작성만.**

## 실데이터 주의 (커밋 금지 목록)

아동 세션 로그·동의 기록(`config/*.json`)·리뷰·산출물은 이 레포에 절대 커밋하지 않습니다(.gitignore로 차단). 이들은 각자 머신의 `HAIN7_BATCH_HOME`(기본 `~/HypeProof/hain7-batch/`)에만 존재합니다. 부모용 PDF는 반 설정 파일에 **서면 동의 기록 + 학생 나이**가 있어야 열립니다 — 스크립트는 동의를 절대 생성하지 않습니다.

## 검증

- 변경 시: 각 스킬의 `scripts/test_*.py` + `stress_*.py` (유닛 46 + 스트레스 40)
- 매 실행: 체크섬·동의·지문·R8 게이트 + `qa_lint.py` L1~L6
- 제품 기준: `hain7-report/references/report-rubric.md`(R1~R9) · `perception-rubric.md`(P1~P2)

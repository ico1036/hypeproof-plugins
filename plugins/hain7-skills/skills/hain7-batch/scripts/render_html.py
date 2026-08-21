#!/usr/bin/env python3
"""RENDER(HTML) — analysis.json → 부모용 HTML 1장. Deterministic port of the judged
white-theme design (perception-rubric 100/100, 2026-08-21). Copy, colors, geometry and
disclosure wording are locked to that verdict; numbers come only from display_value.

Gates mirror render_pdf: zero observed axes → refuse (R8); real data without
distribution_allowed → refuse unless --diagnostic, which stamps 내부 점검용 instead of
the parent-facing badge.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from batch_lib import BatchError, load_signal_module, read_json  # noqa: E402

hs = load_signal_module()

N = 7
CX, CY, R = 170.0, 150.0, 100.0
STEP = 2 * math.pi / N
HALF = STEP / 2 * 0.93
HUB = 17.0


def _wedge(k: int, value: int) -> str:
    th = -math.pi / 2 + STEP * k
    frac = 0.60 + 0.40 * (value - hs.BASELINE_DISPLAY) / (100 - hs.BASELINE_DISPLAY)
    r = R * frac
    x1, y1 = CX + HUB * math.cos(th - HALF), CY + HUB * math.sin(th - HALF)
    x2, y2 = CX + r * math.cos(th - HALF), CY + r * math.sin(th - HALF)
    x3, y3 = CX + r * math.cos(th + HALF), CY + r * math.sin(th + HALF)
    x4, y4 = CX + HUB * math.cos(th + HALF), CY + HUB * math.sin(th + HALF)
    return (f"M{x1:.1f},{y1:.1f} L{x2:.1f},{y2:.1f} A{r:.1f},{r:.1f} 0 0,1 {x3:.1f},{y3:.1f} "
            f"L{x4:.1f},{y4:.1f} A{HUB:.1f},{HUB:.1f} 0 0,0 {x1:.1f},{y1:.1f} Z")


def _label_pos(k: int) -> tuple[float, float, str]:
    th = -math.pi / 2 + STEP * k
    lx, ly = CX + 120 * math.cos(th), CY + 120 * math.sin(th)
    cos = math.cos(th)
    anchor = "middle" if abs(cos) < 0.35 else ("start" if cos > 0 else "end")
    ly_adj = ly + 4 if math.sin(th) > 0.8 else (ly - 2 if abs(cos) >= 0.35 else ly - 6)
    return lx, ly_adj, anchor


DISCLOSURE = (
    "정식 HAIN7 검사·지능검사·심리검사가 아닙니다. 한 번의 수업에서 관찰된 행동 신호이며, 아이의 능력을 확정하지 않습니다. "
    "발휘도는 <b>이번 수업에서 관찰된 힘을 아이 안에서 90~100으로 나타낸 상대 지수(대표 강점=100)</b>이고, "
    "<b>85~88은 이번 수업 주제 밖에 있어 다음 수업에서 피어날 힘에 붙는 기본 구간 값(구간 내 차이는 무의미)</b>입니다. "
    "백분위·성취율·다른 아이와의 비교가 아닙니다. 아래 문헌은 <b>보고 방식</b>의 설계 근거이고 점수의 타당도를 검증한 것이 아닙니다."
)


def build_html(analysis: dict, diagnostic: bool = False) -> str:
    axes = analysis["axes"]
    observed = [(c, a) for c, a in axes.items() if a.get("display_basis") == "observed"]
    if not observed:
        raise BatchError("관찰된 힘이 없어 리포트를 만들지 않습니다. ‘수업이 짧아 기록이 부족해요’ 안내를 전달하세요.")
    if not analysis.get("distribution_allowed") and not analysis.get("synthetic") and not diagnostic:
        raise BatchError("배포 불가 분석입니다(동의 컨텍스트 없음). --diagnostic으로 내부 점검용 렌더만 가능합니다.")

    lead_code = analysis["insights"]["signature_axis"]
    lead = axes[lead_code]
    codes = list(hs.AXES)
    order = {c: i for i, c in enumerate(codes)}
    rows = sorted(axes.items(), key=lambda t: (-t[1]["display_value"], order[t[0]]))

    if analysis.get("synthetic"):
        badge = "DEMO DATA"
    elif diagnostic:
        badge = "내부 점검용"
    else:
        badge = "CLASSROOM PROFILE"

    petals, labels, nums = [], [], []
    for k, c in enumerate(codes):
        a = axes[c]
        v = a["display_value"]
        cls = "lead" if c == lead_code else ("obs" if a["display_basis"] == "observed" else "base")
        petals.append(f'<path class="{cls}" d="{_wedge(k, v)}"></path>')
        lx, ly, anchor = _label_pos(k)
        name = "내 것으로" if c == "OW" else a["korean"]
        labels.append(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}">{html.escape(name)}</text>')
        ncls = ' class="top"' if c == lead_code else ""
        nums.append(f'<text{ncls} x="{lx:.1f}" y="{ly + 15:.1f}" text-anchor="{anchor}">{v}</text>')

    row_html = []
    for rank, (c, a) in enumerate(rows):
        v = a["display_value"]
        if rank == 0:
            chip, chip_cls, extra, score_cls = "대표 강점", "s3", " top-row", " topnum"
            fill = "leadbar"
        elif a["display_basis"] == "observed":
            chip = "함께 빛난 힘" if rank <= 2 else "관찰됨"
            chip_cls, extra, score_cls, fill = ("s2" if rank <= 2 else "s1"), "", "", ""
        else:
            chip, chip_cls, extra, score_cls, fill = "곧 피어날 힘", "s0", "", "", "basebar"
        row_html.append(f'''      <div class="axis{extra}">
        <div class="axis-name"><strong>{html.escape(a["korean"])}</strong><em>{c} · {html.escape(a["english"])}</em></div>
        <div>
          <div class="axis-mean">{html.escape(a["description"])}</div>
          <div class="track"><div class="fill {fill}" style="width:{v}%"></div></div>
        </div>
        <div class="axis-end"><span class="score{score_cls}">{v}</span><span class="chip {chip_cls}">{chip}</span></div>
      </div>''')

    strengths = "\n".join(
        f'          <li><b>{html.escape(i["label"])}</b> — {html.escape(i["copy"])}</li>'
        for i in analysis["insights"]["strengths"][:2]
    )
    cites = "\n".join(
        f'        <a href="{html.escape(i["url"])}" target="_blank" rel="noopener">'
        f'{html.escape(i["claim"])} · {html.escape(i["source"])}</a>'
        for i in hs.EVIDENCE_BASE
    )
    p = analysis["participant"]
    lesson = analysis["lesson"]
    css = _CSS
    return f'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>HAIN7 스튜디오 시그널 · {html.escape(str(p["display_id"]))}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Gowun+Dodum&family=Noto+Sans+KR:wght@400;500;700&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>{css}</style></head><body>
<div class="wrap">
  <section class="sheet" aria-label="학습자 리포트">
    <div class="sheet-head">
      <div>
        <div class="brand">Hypeproof · HAIN7 Studio Signal</div>
        <h2>수업에서 보인 7가지 힘</h2>
        <div class="sub">설문 없이, 실제로 만든 과정에서 관찰한 신호</div>
      </div>
      <div class="badge">{badge}</div>
    </div>
    <div class="idline">
      <span><b>학습자</b>{html.escape(str(p["display_id"]))}</span>
      <span><b>학년</b>{html.escape(str(p["grade_band"]))}</span>
      <span><b>수업</b>{html.escape(str(lesson["title"]))}</span>
      <span><b>날짜</b>{html.escape(str(lesson["date"]))}</span>
      <span><b>시간</b>{lesson["duration_minutes"]}분</span>
    </div>
    <div class="hero">
      <div class="hero-mark">{lead_code}</div>
      <div class="hero-text">
        <div class="label">이번 수업의 대표 강점</div>
        <h3>{html.escape(lead["korean"])}<span class="heronum">{lead["display_value"]}</span></h3>
        <p>{html.escape(lead["description"])} — {html.escape(lead["strength"])}</p>
      </div>
    </div>
    <div class="radar-block">
      <figure class="radar">
        <svg viewBox="-32 -4 404 308" role="img" aria-label="이 아이의 7가지 힘 지도">
          <defs>
            <linearGradient id="gradLead" x1="1" y1="0" x2="0" y2="1">
              <stop offset="0" stop-color="#6D5DF7"/><stop offset="1" stop-color="#FF7A62"/>
            </linearGradient>
            <linearGradient id="gradObs" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stop-color="#8B7DF9"/><stop offset="1" stop-color="#6D5DF7"/>
            </linearGradient>
            <filter id="glow" x="-30%" y="-30%" width="160%" height="160%">
              <feDropShadow dx="0" dy="4" stdDeviation="7" flood-color="#6D5DF7" flood-opacity="0.35"/>
            </filter>
          </defs>
          <g class="bloom">
{chr(10).join("            " + w for w in petals)}
          </g>
          <circle class="hub" cx="170" cy="150" r="11"></circle>
          <circle class="hubdot" cx="170" cy="150" r="3.2"></circle>
          <g class="lab">
{chr(10).join("            " + t for t in labels)}
          </g>
          <g class="num">
{chr(10).join("            " + t for t in nums)}
          </g>
        </svg>
        <figcaption>
          <span class="key"><i class="k-lead"></i>대표 강점</span>
          <span class="key"><i class="k-obs"></i>함께 피어난 힘</span>
        </figcaption>
      </figure>
      <div class="radar-note">
        <div class="label">한눈에</div>
        <p>이번 수업은 <b>{html.escape(lead["korean"])}</b>가 가장 크게 피었어요.</p>
        <p>일곱 가지 힘은 여러 수업에 걸쳐 차례로 피어나요. ‘곧 피어날 힘’ 표시가 붙은 힘은 <b>다음 수업에서 만나요</b>.</p>
      </div>
    </div>
    <div class="axes">
      <div class="axes-caption">
        <span>이 아이 안에서의 발휘도</span>
        <span>85~100 · 다른 아이와 비교하지 않습니다</span>
      </div>
{chr(10).join(row_html)}
      <p class="axes-foot">일곱 가지 힘은 수업마다 차례로 피어나요. 85~88은 이번 수업 주제 밖에 있어 다음 수업에서 곧 피어날 힘이라는 뜻이고, 그 안의 작은 차이에는 뜻이 없어요.</p>
    </div>
    <div class="notes">
      <div class="note">
        <h4>이번 수업에서 잘한 것</h4>
        <ul>
{strengths}
        </ul>
      </div>
      <div class="note">
        <h4>다음 수업에서 해볼 것</h4>
        <p class="challenge">{html.escape(str(analysis["insights"]["next_challenge"]))}</p>
      </div>
    </div>
    <div class="sheet-foot">
      <p class="disc">{DISCLOSURE}</p>
      <div class="cites">
{cites}
      </div>
    </div>
  </section>
</div>
</body></html>'''


_CSS = """
  :root { --ground:#FFFFFF; --wash:#F8F7FE; --card:#FFFFFF; --ink:#1B1830; --muted:#6E6885;
    --soft:#A9A2C6; --hair:#E9E6F4; --violet:#6D5DF7; --violet-soft:#ECE9FF; --coral:#FF7A62;
    --lime:#E8FFAE; --lime-ink:#4A5A16; --track:#F1EFF8;
    --display:"Gowun Dodum","Apple SD Gothic Neo",sans-serif;
    --body:"Noto Sans KR","Apple SD Gothic Neo",sans-serif;
    --mono:"IBM Plex Mono",ui-monospace,monospace; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--ground); color:var(--ink); font-family:var(--body); line-height:1.7; -webkit-font-smoothing:antialiased; }
  .wrap { max-width:900px; margin:0 auto; padding:40px 24px 80px; }
  .sheet { background:var(--card); border:1px solid var(--hair); border-radius:22px;
    box-shadow:0 1px 2px rgba(27,24,48,.04),0 18px 50px rgba(109,93,247,.10); overflow:hidden; }
  .sheet-head { display:flex; justify-content:space-between; align-items:flex-start; gap:16px; padding:28px 34px 20px; }
  .brand { font-family:var(--mono); font-size:10.5px; letter-spacing:.16em; color:var(--soft); text-transform:uppercase; }
  .sheet-head h2 { font-family:var(--display); font-weight:400; font-size:26px; margin:6px 0 3px; }
  .sheet-head .sub { font-size:13px; color:var(--muted); }
  .badge { flex:none; background:var(--coral); color:#fff; border-radius:999px; font-family:var(--mono); font-size:10px; letter-spacing:.1em; padding:7px 14px; white-space:nowrap; }
  .idline { display:flex; flex-wrap:wrap; gap:8px 26px; margin:0 34px; padding:12px 18px; border-radius:12px; background:var(--violet-soft); font-family:var(--mono); font-size:11.5px; }
  .idline span { display:inline-flex; gap:7px; } .idline b { font-weight:500; color:var(--muted); }
  .hero { display:flex; align-items:center; gap:20px; padding:26px 34px 8px; flex-wrap:wrap; }
  .hero-mark { width:64px; height:64px; flex:none; border-radius:18px; background:linear-gradient(135deg,var(--lime),#d3f57e); display:grid; place-items:center; font-family:var(--mono); font-weight:500; font-size:18px; color:var(--lime-ink); box-shadow:0 6px 18px rgba(151,190,26,.25); }
  .hero-text { min-width:240px; flex:1; }
  .hero-text .label { font-family:var(--mono); font-size:10.5px; letter-spacing:.12em; color:var(--soft); text-transform:uppercase; }
  .hero-text h3 { font-family:var(--display); font-weight:400; font-size:29px; margin:3px 0 4px; }
  .hero-text h3 .heronum { font-family:var(--mono); font-size:20px; color:var(--coral); margin-left:8px; }
  .hero-text p { margin:0; font-size:13.5px; color:var(--muted); max-width:60ch; }
  .radar-block { display:grid; grid-template-columns:minmax(300px,1fr) minmax(220px,265px); gap:20px; align-items:center; padding:8px 34px 4px; }
  .radar { margin:0; position:relative; }
  .radar::before { content:""; position:absolute; inset:6% 10%; border-radius:50%; background:radial-gradient(closest-side,rgba(109,93,247,.10),rgba(109,93,247,0)); }
  .radar svg { width:100%; height:auto; display:block; position:relative; }
  .bloom path { stroke-linejoin:round; }
  .bloom .lead { fill:url(#gradLead); stroke:var(--coral); stroke-width:1.6; filter:url(#glow); }
  .bloom .obs, .bloom .base { fill:url(#gradObs); stroke:var(--violet); stroke-width:1.2; stroke-opacity:.55; }
  .hub { fill:var(--card); stroke:var(--hair); stroke-width:1.2; } .hubdot { fill:var(--violet); }
  .lab text { font-family:var(--body); font-size:12px; font-weight:500; fill:var(--ink); }
  .num text { font-family:var(--mono); font-size:13.5px; font-weight:500; fill:var(--violet); }
  .num text.top { fill:var(--coral); font-size:15.5px; }
  .radar figcaption { display:flex; flex-wrap:wrap; gap:8px 16px; justify-content:center; padding-top:2px; }
  .key { display:inline-flex; align-items:center; gap:6px; font-family:var(--mono); font-size:10px; color:var(--muted); }
  .key i { width:12px; height:12px; border-radius:4px; display:block; }
  .k-lead { background:linear-gradient(135deg,var(--violet),var(--coral)); } .k-obs { background:#8B7DF9; }
  .radar-note .label { font-family:var(--mono); font-size:10.5px; letter-spacing:.12em; text-transform:uppercase; color:var(--soft); margin-bottom:8px; }
  .radar-note p { margin:0 0 10px; font-size:13.5px; } .radar-note p:last-child { color:var(--muted); }
  .radar-note b { font-weight:500; color:var(--violet); }
  .axes { padding:18px 34px 26px; }
  .axes-caption { display:flex; justify-content:space-between; gap:12px; font-family:var(--mono); font-size:10.5px; letter-spacing:.1em; color:var(--soft); text-transform:uppercase; padding-bottom:10px; }
  .axis { display:grid; grid-template-columns:128px 1fr auto; gap:16px; align-items:center; padding:10px 0; border-top:1px solid var(--hair); }
  .axis:first-of-type { border-top:none; }
  .axis.top-row { background:linear-gradient(90deg,rgba(255,122,98,.06),rgba(109,93,247,.05)); border-radius:12px; padding:12px 14px; margin:0 -14px; border-top:none; }
  .axis.top-row + .axis { border-top:none; }
  .axis-name strong { font-weight:500; font-size:14.5px; display:block; }
  .axis-name em { font-style:normal; font-family:var(--mono); font-size:10px; letter-spacing:.1em; color:var(--soft); }
  .axis-mean { font-size:12px; color:var(--muted); margin:2px 0 6px; }
  .track { position:relative; height:11px; border-radius:999px; background:var(--track); overflow:hidden; }
  .fill { position:absolute; inset:0 auto 0 0; border-radius:999px; background:#8B7DF9; }
  .fill.leadbar { background:linear-gradient(90deg,var(--violet),var(--coral)); }
  .fill.basebar { background:#8B7DF9; }
  .axis-end { display:flex; align-items:center; gap:12px; justify-content:flex-end; min-width:158px; }
  .score { font-family:var(--mono); font-size:17px; font-weight:500; color:var(--violet); }
  .score.topnum { color:var(--coral); font-size:20px; }
  .chip { font-family:var(--mono); font-size:10.5px; padding:5px 10px; border-radius:999px; white-space:nowrap; }
  .chip.s3 { background:linear-gradient(90deg,var(--violet),var(--coral)); color:#fff; }
  .chip.s2 { background:var(--violet-soft); color:var(--violet); }
  .chip.s1 { border:1px solid var(--hair); color:var(--muted); }
  .chip.s0 { background:var(--lime); color:var(--lime-ink); }
  .axes-foot { margin:14px 0 0; font-size:12.5px; color:var(--soft); }
  .notes { display:grid; grid-template-columns:1fr 1fr; border-top:1px solid var(--hair); }
  .note { padding:22px 34px; } .note + .note { border-left:1px solid var(--hair); }
  .note h4 { font-family:var(--mono); font-size:10.5px; letter-spacing:.12em; text-transform:uppercase; color:var(--soft); margin:0 0 10px; font-weight:400; }
  .note ul { margin:0; padding-left:17px; } .note li { font-size:13.5px; margin-bottom:7px; }
  .note li b { font-weight:500; color:var(--violet); }
  .note .challenge { margin:0; font-size:14px; padding:14px 16px; background:var(--lime); color:var(--lime-ink); border-radius:12px; }
  .sheet-foot { padding:18px 34px 24px; border-top:1px solid var(--hair); background:var(--wash); }
  .sheet-foot .disc { font-size:11.5px; color:var(--muted); margin:0 0 10px; }
  .cites { display:flex; flex-direction:column; gap:5px; }
  .cites a { font-family:var(--mono); font-size:10.5px; color:var(--soft); text-decoration:none; border-bottom:1px solid var(--hair); width:fit-content; max-width:100%; }
  @media (max-width:720px) { .radar-block{grid-template-columns:1fr;} .axis{grid-template-columns:1fr;gap:7px;} .axis-end{justify-content:flex-start;} .notes{grid-template-columns:1fr;} .note+.note{border-left:none;border-top:1px solid var(--hair);} }
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="analysis.json → 부모용 HTML")
    ap.add_argument("--analysis", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--diagnostic", action="store_true")
    args = ap.parse_args(argv)
    try:
        page = build_html(read_json(args.analysis), diagnostic=args.diagnostic)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(page, encoding="utf-8")
        print(json.dumps({"ok": True, "out": str(args.out)}, ensure_ascii=False))
        return 0
    except BatchError as exc:
        print(f"HAIN7_BATCH_ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

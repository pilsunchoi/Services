"""DB 현황 — 표 목록, 행수, 기간, 출처. 대시보드의 자동 구간도 여기서 채운다.

`docs/index.html`의 두 구간을 DB를 읽어 다시 쓴다. 손으로 고치지 말 것 —
다음 실행에서 덮인다.

  <!-- DB_STATUS:START --> ... <!-- DB_STATUS:END -->        개요 탭의 숫자 카드
  <!-- DB_INVENTORY:START --> ... <!-- DB_INVENTORY:END -->  받기·사용 탭의 표 목록

**표를 새로 만들면 아래 INVENTORY에 한 줄을 더해야 한다.** 없으면 "(설명 미등록)"으로
찍히고 순서도 사전 순서를 따른다.

  python scripts/07_db_status.py           # 화면에 현황만
  python scripts/07_db_status.py --html    # docs/index.html도 갱신
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils.common import DB_PATH, ROOT  # noqa: E402

HTML = ROOT / "docs" / "index.html"

# 표 이름 → (설명, 단위, 출처). 순서가 곧 대시보드 표의 순서다.
INVENTORY: dict[str, tuple[str, str, str]] = {
    "fact_batis": (
        "나라쌍 서비스 교역. EBOPS 2010 31항목 × 수출입. "
        "보고치·조정치·균형치 셋과 방법론 코드를 한 행에 담는다",
        "백만 USD", "OECD-WTO BaTIS, BPM6 2025-12판"),
    "fact_bimts_hs2": (
        "나라쌍 상품 교역, HS2017 2단위(97개 장 + 총계). "
        "균형치 두 종(B 총액, B_ADJ_RX 재수출 조정)",
        "백만 USD", "OECD BIMTS, 2026-05 파일"),
    "fact_bimts_cpa2": (
        "같은 자료를 CPA 2.1로 본 것. 섹션·분류·묶음이 섞인 계층이다",
        "백만 USD", "OECD BIMTS, 2026-05 파일"),
    "dim_area": (
        "경제 코드. 자료의 성질 열·동봉 코드표·SDMX CL_AREA 세 출처를 나란히 두고, "
        "집계 여부를 is_aggregate로 판정",
        "-", "세 출처 병합"),
    "dim_service": (
        "EBOPS 2010 항목. 표준 27개와 파생 4개(SOX·SOX1·SPX1·SPX4)의 산식",
        "-", "BaTIS 동봉 코드표"),
    "dim_methodology": (
        "BaTIS 방법론 코드 37개. mclass는 접두사로 매긴 우리 분류"
        "(보고/모형추정/조정·보간/집계)",
        "-", "BaTIS 동봉 코드표"),
    "dim_flow": ("EXP / IMP", "-", "BaTIS 동봉 코드표"),
    "dim_code_type": ("코드 성질(c 국가 · g 그룹 · s 표준항목 · d 파생항목)", "-", "BaTIS 동봉 코드표"),
    "dim_hs2017": ("HS2017 품목 코드. level(2·4·6)은 코드 자릿수에서 매겼다", "-", "OECD SDMX CL_PRODUCT_HS2017"),
    "dim_cpa21": ("CPA 2.1 품목 코드", "-", "OECD SDMX CL_PRODUCT_CPA_2_1"),
    "dim_edition": ("판 이력. 어느 판을 언제 어느 파일에서 실었는지", "-", "우리가 기록"),
    "meta_constants": ("적재할 때 상수여서 fact에서 뺀 열과 그 값", "-", "우리가 기록"),
}


def collect(con) -> list[dict]:
    have = {r[0] for r in con.execute("SELECT table_name FROM duckdb_tables()").fetchall()}
    rows = []
    for name in list(INVENTORY) + sorted(have - set(INVENTORY)):
        if name not in have:
            continue
        n = con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        cols = {c[0] for c in con.execute(f"DESCRIBE {name}").fetchall()}
        span = ""
        if "year" in cols:
            lo, hi = con.execute(f"SELECT min(year), max(year) FROM {name}").fetchone()
            span = f"{lo}–{hi}"
        desc, unit, src = INVENTORY.get(name, ("(설명 미등록)", "-", "-"))
        rows.append({"name": name, "rows": n, "span": span,
                     "desc": desc, "unit": unit, "source": src})
    return rows


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_inventory(rows: list[dict]) -> str:
    out = ['    <div class="tblwrap">', '      <table class="inv">',
           '        <caption>표 전체 목록 (<code>07_db_status.py</code>가 자동으로 채운다)</caption>',
           '        <thead><tr><th>표</th><th>설명</th><th class="r">행수</th>'
           '<th>기간</th><th>단위 · 출처</th></tr></thead>', '        <tbody>']
    for r in rows:
        kind = "fact" if r["name"].startswith("fact") else ("dim" if r["name"].startswith("dim") else "meta")
        pill = {"fact": "ok", "dim": "info", "meta": "warn"}[kind]
        unit_src = esc(r["source"]) if r["unit"] == "-" else f'{esc(r["unit"])} · {esc(r["source"])}'
        out.append(
            f'          <tr><td><code>{r["name"]}</code> <span class="pill {pill}">{kind}</span></td>'
            f'<td>{esc(r["desc"])}</td><td class="r">{r["rows"]:,}</td>'
            f'<td>{r["span"] or "—"}</td>'
            f'<td class="s">{unit_src}</td></tr>')
    out += ['        </tbody>', '      </table>', '    </div>']
    return "\n".join(out)


def render_status(con, rows: list[dict]) -> str:
    facts = [r for r in rows if r["name"].startswith("fact")]
    total = sum(r["rows"] for r in facts)
    size_mb = DB_PATH.stat().st_size / 1e6
    svc = next((r for r in rows if r["name"] == "fact_batis"), None)
    gds = next((r for r in rows if r["name"] == "fact_bimts_hs2"), None)
    n_area = con.execute("SELECT count(*) FROM dim_area WHERE in_batis AND NOT is_aggregate").fetchone()[0]
    n_item = con.execute("SELECT count(*) FROM dim_service").fetchone()[0]
    cards = [
        (f"{total:,}", "fact 행 합계"),
        (svc["span"] if svc else "—", "서비스 (BaTIS)"),
        (gds["span"] if gds else "—", "상품 (BIMTS)"),
        (f"{n_area}", "개별 경제 (집계 코드 제외)"),
        (f"{n_item}", "EBOPS 서비스 항목"),
        (f"{size_mb:,.0f} MB", "DuckDB 파일"),
    ]
    out = ['    <div class="stats">']
    out += [f'      <div class="stat"><div class="n">{n}</div><div class="k">{k}</div></div>'
            for n, k in cards]
    out.append("    </div>")
    return "\n".join(out)


def splice(html: str, marker: str, body: str) -> str:
    pat = re.compile(f"(<!-- {marker}:START -->)(.*?)(<!-- {marker}:END -->)", re.S)
    if not pat.search(html):
        raise SystemExit(f"{marker} 구간을 찾지 못했다 — docs/index.html을 확인할 것")
    return pat.sub(lambda m: f"{m.group(1)}\n{body}\n{m.group(3)}", html)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", action="store_true", help="docs/index.html의 자동 구간을 갱신한다")
    args = ap.parse_args()

    if not DB_PATH.exists():
        print("DB가 없다:", DB_PATH)
        return 1
    con = duckdb.connect(str(DB_PATH), read_only=True)
    rows = collect(con)

    print(f"DB: {DB_PATH}  ({DB_PATH.stat().st_size/1e6:,.0f} MB)\n")
    print(f"{'표':<20}{'행수':>14}  {'기간':<12} 설명")
    print("-" * 110)
    for r in rows:
        print(f"{r['name']:<20}{r['rows']:>14,}  {r['span']:<12} {r['desc'][:60]}")
    print()
    print(con.execute(
        "SELECT dataset, edition, table_name, rows, loaded_at FROM dim_edition "
        "ORDER BY dataset, table_name").df().to_string(index=False))

    if args.html:
        if not HTML.exists():
            print("\ndocs/index.html이 없다 — 건너뛴다")
            return 0
        html = HTML.read_text(encoding="utf-8")
        html = splice(html, "DB_STATUS", render_status(con, rows))
        html = splice(html, "DB_INVENTORY", render_inventory(rows))
        HTML.write_text(html, encoding="utf-8")
        print(f"\n대시보드 갱신: {HTML}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

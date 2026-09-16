"""무결성 검증 — BaTIS.

KCSDB2와 같이 검증은 이 스크립트 하나로 모은다. 값(금액) 기준과 개수 기준을 함께
본다. BaTIS는 추정이 섞인 자료라 "안 맞는 것이 정상"인 항목이 있다(B3·B6). 그런
항목은 FAIL이 아니라 수치를 기록하는 것이 목적이다.

  python scripts/06_validate.py
  python scripts/06_validate.py --no-sdmx     # API 교차검증 생략
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils.common import DB_PATH, setup_logging  # noqa: E402

TOL = 1e-4  # 백만 USD. 원본이 소수 6자리이므로 이보다 큰 차이는 반올림이 아니다

RESULTS: list[tuple[str, str, str]] = []


def record(code: str, status: str, msg: str, log) -> None:
    RESULTS.append((code, status, msg))
    log.info("[%s] %-4s %s", code, status, msg)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-sdmx", action="store_true")
    args = ap.parse_args()
    log = setup_logging("validate")
    con = duckdb.connect(str(DB_PATH), read_only=True)

    rows = con.execute("SELECT count(*) FROM fact_batis").fetchone()[0]
    log.info("fact_batis %s행", f"{rows:,}")

    # B0 키 중복
    dup = con.execute("""
        SELECT count(*) FROM (
          SELECT edition, reporter, partner, flow, item_code, year
          FROM fact_batis GROUP BY ALL HAVING count(*) > 1)
    """).fetchone()[0]
    record("B0", "PASS" if dup == 0 else "FAIL", f"키 중복 {dup:,}건", log)

    # B1 균형치 대칭성 (정의적 항등). 개별 경제쌍과 그룹이 낀 쌍을 갈라 본다 —
    # 그룹(W, EU27_2020 등)은 집계라 좌우가 같을 이유가 없다.
    sym = con.execute(f"""
        WITH x AS (SELECT reporter a, partner b, item_code i, year y, balanced_value v
                   FROM fact_batis WHERE flow='EXP'),
             m AS (SELECT partner a, reporter b, item_code i, year y, balanced_value v
                   FROM fact_batis WHERE flow='IMP')
        SELECT (NOT aa.is_aggregate AND NOT ab.is_aggregate) AS both_country,
               count(*), count(*) FILTER (WHERE abs(coalesce(x.v,0)-coalesce(m.v,0)) > {TOL}),
               max(abs(coalesce(x.v,0)-coalesce(m.v,0)))
        FROM x JOIN m USING (a, b, i, y)
        JOIN dim_area aa ON a=aa.code JOIN dim_area ab ON b=ab.code
        GROUP BY 1 ORDER BY 1 DESC
    """).fetchall()
    for both, n, bad, mx in sym:
        label = "개별 경제쌍" if both else "그룹이 낀 쌍"
        record("B1.c" if both else "B1.g",
               ("PASS" if bad == 0 else "WARN") if both else "INFO",
               f"{label} 대칭 대조 {n:,} · 불일치 {bad:,} · 최대차 {mx:.6g}"
               + ("" if both else " (집계라 좌우가 같을 이유가 없다)"), log)

    # B2 파생항목 재계산
    derived = {
        "SOX":  "S - SL",
        "SOX1": "SE+SF+SG+SH+SI+SJ+SK",
        "SPX1": "SE+SF+SG+SH+SI+SJ+SK+SL",
        "SPX4": "SA+SB",
    }
    for val in ("final_value", "balanced_value"):
        piv = f"""
            SELECT reporter, partner, flow, year,
                   {', '.join(f"max({val}) FILTER (WHERE item_code='{c}') AS {c}"
                              for c in ['S','SA','SB','SE','SF','SG','SH','SI','SJ','SK','SL',
                                        'SOX','SOX1','SPX1','SPX4'])}
            FROM fact_batis GROUP BY ALL
        """
        for item, expr in derived.items():
            bad, mx = con.execute(f"""
                WITH p AS ({piv})
                SELECT count(*) FILTER (WHERE abs({item} - ({expr})) > {TOL}),
                       max(abs({item} - ({expr})))
                FROM p WHERE {item} IS NOT NULL
            """).fetchone()
            record(f"B2.{item}.{val[:3]}", "PASS" if bad == 0 else "WARN",
                   f"{item} = {expr} ({val}) 불일치 {bad:,} · 최대차 {(mx or 0):.6g}", log)

    # B3 표준 대분류 합 대 총계 S — 값의 종류별로 다르다(보고치는 안 맞는 것이 정상)
    parts = "SA+SB+SC+SD+SE+SF+SG+SH+SI+SJ+SK+SL"
    for val in ("reported_value", "final_value", "balanced_value"):
        piv = f"""
            SELECT reporter, partner, flow, year,
                   {', '.join(f"max({val}) FILTER (WHERE item_code='{c}') AS {c}"
                              for c in ['S','SA','SB','SC','SD','SE','SF','SG','SH','SI','SJ','SK','SL'])}
            FROM fact_batis GROUP BY ALL
        """
        n, bad, share = con.execute(f"""
            WITH p AS ({piv})
            SELECT count(*), count(*) FILTER (WHERE abs(S - ({parts})) > {TOL}),
                   sum(abs(S - ({parts}))) / nullif(sum(abs(S)), 0)
            FROM p WHERE S IS NOT NULL AND ({parts}) IS NOT NULL
        """).fetchone()
        status = "PASS" if bad == 0 else ("INFO" if val == "reported_value" else "WARN")
        record(f"B3.{val[:3]}", status,
               f"S = 대분류 합 대조 {n:,}셀 중 불일치 {bad:,} · 절대차/총액 {100*(share or 0):.3f}%", log)

    # B4 하위 합
    subs = {"SC": ["SC1", "SC2", "SC3", "SC4"], "SD": ["SDA", "SDB"],
            "SI": ["SI1", "SI2", "SI3"], "SJ": ["SJ1", "SJ2", "SJ3"], "SK": ["SK1", "SK2"]}
    for parent, kids in subs.items():
        cols = [parent] + kids
        piv = f"""
            SELECT reporter, partner, flow, year,
                   {', '.join(f"max(balanced_value) FILTER (WHERE item_code='{c}') AS {c}" for c in cols)}
            FROM fact_batis GROUP BY ALL
        """
        n, bad, mx = con.execute(f"""
            WITH p AS ({piv})
            SELECT count(*), count(*) FILTER (WHERE abs({parent} - ({'+'.join(kids)})) > {TOL}),
                   max(abs({parent} - ({'+'.join(kids)})))
            FROM p WHERE {parent} IS NOT NULL AND ({'+'.join(kids)}) IS NOT NULL
        """).fetchone()
        record(f"B4.{parent}", "PASS" if bad == 0 else "WARN",
               f"{parent} = {'+'.join(kids)} 대조 {n:,} · 불일치 {bad:,} · 최대차 {(mx or 0):.6g}", log)

    # B5 그룹 코드 — 파트너 세계(W)가 개별 파트너 합과 같은가 (보고국별로)
    nrep, bad, worst = con.execute(f"""
        WITH t AS (SELECT reporter, partner, balanced_value v FROM fact_batis
                   WHERE item_code='S' AND flow='EXP' AND year=2023),
             w AS (SELECT reporter, v FROM t WHERE partner='W'),
             c AS (SELECT t.reporter, sum(t.v) v FROM t JOIN dim_area a ON t.partner=a.code
                   WHERE NOT a.is_aggregate GROUP BY 1)
        SELECT count(*), count(*) FILTER (WHERE abs(w.v-c.v) > {TOL}),
               max(abs(w.v-c.v)) FROM w JOIN c USING (reporter)
    """).fetchone()
    groups = con.execute("SELECT list(code) FROM dim_area WHERE area_type='g'").fetchone()[0]
    record("B5", "PASS" if bad == 0 else "WARN",
           f"2023 총서비스 수출: 파트너 W = 개별 경제 파트너 합 — 보고국 {nrep}개 중 "
           f"불일치 {bad}개 · 최대차 {(worst or 0):.6g}. 그룹 코드 {groups}를 "
           "개별과 섞으면 중복 집계된다", log)

    # B6 보고 커버리지 (연도별)
    cov = con.execute("""
        SELECT year,
               100.0*count(*) FILTER (WHERE reported_value IS NOT NULL)/count(*) AS pct_rows,
               100.0*sum(abs(reported_value)) FILTER (WHERE reported_value IS NOT NULL)
                     / nullif(sum(abs(balanced_value)),0) AS pct_val
        FROM fact_batis WHERE item_code='S' GROUP BY 1 ORDER BY 1
    """).fetchall()
    record("B6", "INFO",
           "총서비스 보고 커버리지(행%) " + ", ".join(f"{y}:{p:.1f}" for y, p, _ in cov[::5]), log)

    # B7 방법론 분포 (균형 금액 기준). 그룹을 넣으면 집계(A)가 금액의 대부분을
    # 차지해 착시가 생기므로 개별 경제쌍만 본다.
    dist = con.execute("""
        SELECT m.mclass,
               100.0*count(*)/sum(count(*)) OVER () AS pct_rows,
               100.0*sum(abs(f.balanced_value))/sum(sum(abs(f.balanced_value))) OVER () AS pct_val
        FROM fact_batis f
        LEFT JOIN dim_methodology m ON f.methodology=m.code
        JOIN dim_area ar ON f.reporter=ar.code AND NOT ar.is_aggregate
        JOIN dim_area ap ON f.partner=ap.code AND NOT ap.is_aggregate
        WHERE f.item_code='S' GROUP BY 1 ORDER BY 3 DESC
    """).fetchall()
    record("B7", "INFO", "총서비스(개별 경제쌍만) 방법론 비중(행%/금액%) " +
           ", ".join(f"{c}:{r:.1f}/{v:.1f}" for c, r, v in dist), log)

    # B8 코드 매칭률
    for col, dim, key in (("reporter", "dim_area", "code"), ("partner", "dim_area", "code"),
                          ("item_code", "dim_service", "item_code"), ("flow", "dim_flow", "code"),
                          ("methodology", "dim_methodology", "code")):
        miss = con.execute(f"""
            SELECT count(DISTINCT f.{col}) FROM fact_batis f
            LEFT JOIN {dim} d ON f.{col}=d.{key} WHERE d.{key} IS NULL AND f.{col} IS NOT NULL
        """).fetchone()[0]
        record(f"B8.{col}", "PASS" if miss == 0 else "WARN", f"{col} → {dim} 미매칭 코드 {miss}", log)

    # B9 기간 연속성
    yrs = con.execute("SELECT min(year), max(year), count(DISTINCT year) FROM fact_batis").fetchone()
    ok = yrs[2] == yrs[1] - yrs[0] + 1
    record("B9", "PASS" if ok else "FAIL", f"기간 {yrs[0]}–{yrs[1]}, 연도 {yrs[2]}개", log)

    # B10 SDMX 교차검증
    if not args.no_sdmx:
        try:
            import io
            import pandas as pd
            import requests
            ref = "KOR"
            url = (f"https://sdmx.oecd.org/public/rest/data/OECD.SDD.TPS,DSD_BATIS@DF_BATIS,/"
                   f"{ref}..........?startPeriod=2023&endPeriod=2023&dimensionAtObservation=AllDimensions")
            r = requests.get(url, headers={"Accept": "application/vnd.sdmx.data+csv;version=2.0.0"},
                             timeout=300)
            r.raise_for_status()
            api = pd.read_csv(io.StringIO(r.text), low_memory=False)
            api = api[["COUNTERPART_AREA", "TRADE_FLOW", "SERVICE", "ADJUSTMENT", "OBS_VALUE"]]
            adj = {"N": "reported_value", "F": "final_value", "B": "balanced_value"}
            flowmap = {"X": "EXP", "M": "IMP"}
            ours = con.execute(
                "SELECT partner, flow, item_code, reported_value, final_value, balanced_value "
                "FROM fact_batis WHERE reporter=? AND year=2023", [ref]).df()
            merged = 0
            bad = 0
            maxd = 0.0
            for _, row in api.iterrows():
                col = adj.get(row.ADJUSTMENT)
                f = flowmap.get(row.TRADE_FLOW)
                if col is None or f is None:
                    continue
                sel = ours[(ours.partner == row.COUNTERPART_AREA) & (ours.flow == f)
                           & (ours.item_code == row.SERVICE)]
                if sel.empty:
                    continue
                v = sel.iloc[0][col]
                merged += 1
                d = abs((v if v == v else 0) - row.OBS_VALUE)
                maxd = max(maxd, d)
                if d > 1e-3:
                    bad += 1
            record("B10", "PASS" if bad == 0 else "WARN",
                   f"SDMX 대조(KOR 2023) {merged:,}셀 · 불일치 {bad:,} · 최대차 {maxd:.6g}", log)
        except Exception as e:
            record("B10", "SKIP", f"SDMX 대조 실패: {e!r}", log)

    # ---------------- BIMTS ----------------
    tables = {r[0] for r in con.execute("SELECT table_name FROM duckdb_tables()").fetchall()}
    # CPA 2.1 코드는 계층이다(섹션 A·B·C… 아래 분류 C10, 묶음 C10T12). 전부 더하면
    # 여러 번 센다. HS2017 2단위는 평평하므로 _T를 뺀 나머지가 곧 합이다.
    part_filter = {
        "fact_bimts_hs2": "product <> '_T'",
        # 섹션(A·B·C…)에 미분류(_X)를 더해야 총계가 된다
        "fact_bimts_cpa2": "(regexp_matches(product, '^CPA_2_1_[A-Z]$') OR product='_X')",
    }
    for tbl, dim, total_code in (("fact_bimts_hs2", "dim_hs2017", "_T"),
                                 ("fact_bimts_cpa2", "dim_cpa21", "_T")):
        if tbl not in tables:
            continue
        tag = "M" if tbl.endswith("hs2") else "C"
        n = con.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]
        log.info("%s %s행", tbl, f"{n:,}")

        dup = con.execute(f"""
            SELECT count(*) FROM (SELECT edition, exporter, importer, product, year, adjustment
                                  FROM {tbl} GROUP BY ALL HAVING count(*)>1)""").fetchone()[0]
        record(f"{tag}0", "PASS" if dup == 0 else "FAIL", f"{tbl} 키 중복 {dup:,}건", log)

        # M1 총계(_T) = 품목 합 (2023년, 개별 경제쌍)
        cells, bad, worst = con.execute(f"""
            WITH t AS (SELECT exporter, importer, adjustment, product, value
                       FROM {tbl} WHERE year=2023),
                 tot AS (SELECT exporter, importer, adjustment, value v
                         FROM t WHERE product='{total_code}'),
                 parts AS (SELECT exporter, importer, adjustment, sum(value) v
                           FROM t WHERE {part_filter[tbl]} GROUP BY ALL)
            SELECT count(*), count(*) FILTER (WHERE abs(tot.v-parts.v) > 1e-3),
                   max(abs(tot.v-parts.v))
            FROM tot JOIN parts USING (exporter, importer, adjustment)
        """).fetchone()
        record(f"{tag}1", "PASS" if bad == 0 else "WARN",
               f"{tbl} 2023 총계(_T) = 품목 합 · 셀 {cells:,} · 불일치 {bad:,} · 최대차 {(worst or 0):.6g}", log)

        # M2 수입국 세계(W) = 개별 수입국 합 (2023, 총품목, 총균형치)
        w_total, c_total = con.execute(f"""
            SELECT (SELECT sum(value) FROM {tbl} f JOIN dim_area a ON f.exporter=a.code
                    WHERE NOT a.is_aggregate AND f.importer='W'
                      AND year=2023 AND product='{total_code}' AND adjustment='B'),
                   (SELECT sum(value) FROM {tbl} f
                    JOIN dim_area ae ON f.exporter=ae.code AND NOT ae.is_aggregate
                    JOIN dim_area ai ON f.importer=ai.code AND NOT ai.is_aggregate
                    WHERE year=2023 AND product='{total_code}' AND adjustment='B')
        """).fetchone()
        rel = abs((w_total or 0) - (c_total or 0)) / (w_total or 1)
        record(f"{tag}2", "PASS" if rel < 0.005 else "WARN",
               f"{tbl} 2023 수출 총액: 수입국 W {(w_total or 0):,.0f} vs 개별 수입국 합 "
               f"{(c_total or 0):,.0f} (차이 {100*rel:.3f}%) — 둘을 함께 더하면 두 배가 된다", log)

        # M4 재수출 조정 대 총 균형치 (세계 총액, 개별 경제쌍만)
        tot = con.execute(f"""
            SELECT adjustment, sum(value) FROM {tbl} f
            JOIN dim_area ae ON f.exporter=ae.code AND NOT ae.is_aggregate
            JOIN dim_area ai ON f.importer=ai.code AND NOT ai.is_aggregate
            WHERE year=2023 AND product='{total_code}' GROUP BY 1 ORDER BY 1""").fetchall()
        record(f"{tag}4", "INFO",
               f"{tbl} 2023 세계 수출 총액(백만 USD, 개별 경제쌍): "
               + ", ".join(f"{a}={v:,.0f}" for a, v in tot), log)

        # M5 0 행 존재 여부 (OECD 설명대로면 0은 결측으로 빠져 있어야 한다)
        z = con.execute(f"SELECT count(*) FROM {tbl} WHERE value = 0").fetchone()[0]
        record(f"{tag}5", "INFO", f"{tbl} 값이 0인 행 {z:,} (0을 결측으로 표기한다는 설명과 대조)", log)

        # M6 기간 연속성
        lo, hi, cnt = con.execute(f"SELECT min(year), max(year), count(DISTINCT year) FROM {tbl}").fetchone()
        record(f"{tag}6", "PASS" if cnt == hi - lo + 1 else "FAIL",
               f"{tbl} 기간 {lo}–{hi}, 연도 {cnt}개", log)

        # M7 코드 매칭
        if dim in tables:
            miss = con.execute(f"""
                SELECT count(DISTINCT f.product) FROM {tbl} f
                LEFT JOIN {dim} d ON f.product=d.code WHERE d.code IS NULL""").fetchone()[0]
            record(f"{tag}7", "PASS" if miss == 0 else "WARN", f"{tbl}.product → {dim} 미매칭 {miss}", log)
        miss_a = con.execute(f"""
            SELECT count(DISTINCT c) FROM (
              SELECT exporter c FROM {tbl} UNION SELECT importer FROM {tbl}) s
            LEFT JOIN dim_area d ON s.c=d.code WHERE d.code IS NULL""").fetchone()[0]
        record(f"{tag}8", "PASS" if miss_a == 0 else "WARN", f"{tbl} 경제 코드 → dim_area 미매칭 {miss_a}", log)

    # 서비스와 상품을 나란히 — 같은 해 세계 교역 규모
    if "fact_bimts_hs2" in tables:
        svc = con.execute("""
            SELECT sum(balanced_value) FROM fact_batis
            WHERE item_code='S' AND flow='EXP' AND year=2023 AND reporter='W' AND partner='W'""").fetchone()[0]
        gds = con.execute("""
            SELECT sum(value) FROM fact_bimts_hs2 f
            JOIN dim_area ae ON f.exporter=ae.code AND NOT ae.is_aggregate
            JOIN dim_area ai ON f.importer=ai.code AND NOT ai.is_aggregate
            WHERE year=2023 AND product='_T' AND adjustment='B'""").fetchone()[0]
        if svc and gds:
            record("X1", "INFO",
                   f"2023 세계 수출(백만 USD): 서비스 {svc:,.0f} · 상품 {gds:,.0f} "
                   f"(서비스 비중 {100*svc/(svc+gds):.1f}%)", log)

    con.close()
    n_fail = sum(1 for _, s, _ in RESULTS if s == "FAIL")
    n_warn = sum(1 for _, s, _ in RESULTS if s == "WARN")
    n_pass = sum(1 for _, s, _ in RESULTS if s == "PASS")
    log.info("결과: PASS %d · WARN %d · FAIL %d · INFO %d",
             n_pass, n_warn, n_fail, len(RESULTS) - n_pass - n_warn - n_fail)
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())

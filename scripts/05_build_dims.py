"""코드표 → dim 테이블.

출처가 셋이고 셋이 서로 어긋난다. 그래서 하나를 고르지 않고 나란히 둔다.

1. 벌크 CSV 자신의 성질 열(`type_Reporter`/`type_Partner`/`type_Item`) — **자료에 실제로
   쓰인 코드의 목록이자 그 성질의 정본**. 03에서 parquet에 그대로 남겨 두었다.
2. 동봉 코드표 xlsx — 설명과 주석이 있으나 **자료와 코드가 어긋난다**. 코드표의
   `WLD`·`RWD`·`E_EU`·`ANT`·`SCG`는 자료에 없고, 자료의 `W`·`WXD`·`WXOECD`·
   `WXEU27_2020`·`ANT_F`·`SCG_F`는 코드표에 없다(2026-09-16 실측).
3. OECD SDMX 코드표 `CL_AREA` — 이름은 여기가 가장 넓다.

dim_area는 셋을 합치고 출처를 열로 구분한다. 어느 출처에도 없으면 NULL로 둔다.

  python scripts/05_build_dims.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import openpyxl
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils.common import DB_PATH, EXTERNAL, INTERIM, setup_logging  # noqa: E402

CODES_XLSX = EXTERNAL / "OECD-WTO_BATIS_BPM6_December2025_codes.xlsx"
CL_AREA_JSON = EXTERNAL / "CL_AREA.json"
PARQUET = INTERIM / "batis" / "2025-12" / "batis_raw.parquet"
CL_AREA_URL = ("https://sdmx.oecd.org/public/rest/codelist/OECD/CL_AREA/latest"
               "?references=none&detail=full")


def sheet_rows(wb, name: str, ncol: int) -> list[tuple]:
    ws = wb[name]
    out = []
    for i, r in enumerate(ws.iter_rows(values_only=True)):
        if i == 0 or r[0] is None:
            continue
        vals = [(str(c).strip() if isinstance(c, str) else c) for c in r[:ncol]]
        vals += [None] * (ncol - len(vals))
        out.append(tuple(vals))
    return out


def cl_area_full(log) -> dict[str, dict]:
    if not CL_AREA_JSON.exists():
        log.info("CL_AREA 내려받기")
        r = requests.get(CL_AREA_URL, timeout=120,
                         headers={"Accept": "application/vnd.sdmx.structure+json;version=1.0;urn=true"})
        r.raise_for_status()
        CL_AREA_JSON.write_text(r.text, encoding="utf-8")
    d = json.loads(CL_AREA_JSON.read_text(encoding="utf-8"))
    codes = d["data"]["codelists"][0]["codes"]
    log.info("CL_AREA %d개 코드", len(codes))
    out = {}
    for c in codes:
        comp = next((a.get("title") for a in c.get("annotations", [])
                     if a.get("type") == "COMP_RULE"), None)
        out[c["id"]] = {"name": c.get("name"), "comp_rule": comp}
    return out


def mclass(code: str) -> str:
    if code.startswith("R_"):
        return "reported"
    if code.startswith("M"):
        return "model"
    if code.startswith("E") or code == "W0":
        return "estimate"
    if code == "A":
        return "aggregate"
    if code == "Z":
        return "unavailable"
    return "other"


def main() -> int:
    log = setup_logging("build_dims")
    if not CODES_XLSX.exists() or not PARQUET.exists():
        log.error("코드표나 parquet이 없다 — 01·03을 먼저 돌릴 것")
        return 1

    wb = openpyxl.load_workbook(CODES_XLSX, read_only=True)
    xl_area = {c: (n, t, note) for c, n, t, note in sheet_rows(wb, "economies", 4)}
    xl_item = {c: (d, t, der) for c, d, t, der in sheet_rows(wb, "service items", 4)}
    flows = sheet_rows(wb, "flow", 2)
    types = sheet_rows(wb, "type", 2)
    meths = sheet_rows(wb, "methodology codes", 2)
    sdmx = cl_area_full(log)

    con = duckdb.connect(str(DB_PATH))
    pq = PARQUET.as_posix()
    tables = {r[0] for r in con.execute("SELECT table_name FROM duckdb_tables()").fetchall()}

    # 자료에 실제로 쓰인 코드와 그 성질
    used = con.execute(f"""
        SELECT code, max(area_type) AS area_type,
               bool_or(as_reporter) AS as_reporter, bool_or(as_partner) AS as_partner
        FROM (
            SELECT Reporter AS code, type_Reporter AS area_type, true AS as_reporter, false AS as_partner
            FROM read_parquet('{pq}') GROUP BY 1, 2
            UNION ALL
            SELECT Partner, type_Partner, false, true FROM read_parquet('{pq}') GROUP BY 1, 2
        ) GROUP BY code ORDER BY code
    """).fetchall()
    log.info("자료에 쓰인 경제 코드 %d개", len(used))

    # BIMTS에만 나오는 코드도 담는다(BEL_LUX·SACU·SSD 등 10개). BIMTS 원본에는 성질
    # 열이 없으므로 area_type은 NULL로 두고, 집계 여부는 CL_AREA의 COMP_RULE로 본다.
    bimts_codes: set[str] = set()
    for t in ("fact_bimts_hs2", "fact_bimts_cpa2"):
        if t in tables:
            bimts_codes |= {r[0] for r in con.execute(
                f"SELECT DISTINCT exporter FROM {t} UNION SELECT DISTINCT importer FROM {t}").fetchall()}

    rows = []
    seen = set()
    for code, atype, as_rep, as_par in used:
        nm, xt, note = xl_area.get(code, (None, None, None))
        s = sdmx.get(code, {})
        is_agg = (atype == "g") or (s.get("comp_rule") is not None)
        rows.append((code, s.get("name"), nm, atype, xt, s.get("comp_rule"), is_agg,
                     bool(as_rep), bool(as_par), True, code in bimts_codes, note))
        seen.add(code)
    for code in sorted(bimts_codes - seen):
        s = sdmx.get(code, {})
        nm, xt, note = xl_area.get(code, (None, None, None))
        rows.append((code, s.get("name"), nm, None, xt, s.get("comp_rule"),
                     s.get("comp_rule") is not None, False, False, False, True, note))
        seen.add(code)
    for code, (nm, xt, note) in xl_area.items():
        if code not in seen:
            s = sdmx.get(code, {})
            rows.append((code, s.get("name"), nm, None, xt, s.get("comp_rule"),
                         (xt == "g") or (s.get("comp_rule") is not None),
                         False, False, False, False, note))

    con.execute("DROP TABLE IF EXISTS dim_area")
    con.execute("""CREATE TABLE dim_area(
        code VARCHAR PRIMARY KEY,
        name_sdmx VARCHAR,      -- OECD CL_AREA
        name_codes VARCHAR,     -- 동봉 코드표
        area_type VARCHAR,      -- BaTIS 자료의 성질 열(c 국가 / g 그룹). 있으면 이것이 정본
        area_type_codes VARCHAR,-- 코드표의 성질(어긋날 수 있다)
        comp_rule VARCHAR,      -- CL_AREA의 구성 규칙. 있으면 집계다
        is_aggregate BOOLEAN,   -- 우리 판정: area_type='g' 이거나 comp_rule이 있으면 참
        as_reporter BOOLEAN, as_partner BOOLEAN,
        in_batis BOOLEAN, in_bimts BOOLEAN,
        note VARCHAR)""")
    con.executemany("INSERT INTO dim_area VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)

    used_items = con.execute(
        f"SELECT Item_code, max(type_Item) FROM read_parquet('{pq}') GROUP BY 1 ORDER BY 1").fetchall()
    con.execute("DROP TABLE IF EXISTS dim_service")
    con.execute("""CREATE TABLE dim_service(
        item_code VARCHAR PRIMARY KEY, description VARCHAR,
        item_type VARCHAR, item_type_codes VARCHAR, derivation VARCHAR)""")
    con.executemany("INSERT INTO dim_service VALUES (?,?,?,?,?)",
                    [(c, *(xl_item.get(c, (None, None, None))[:1]), t,
                      xl_item.get(c, (None, None, None))[1],
                      xl_item.get(c, (None, None, None))[2]) for c, t in used_items])

    con.execute("DROP TABLE IF EXISTS dim_flow")
    con.execute("CREATE TABLE dim_flow(code VARCHAR PRIMARY KEY, description VARCHAR)")
    con.executemany("INSERT INTO dim_flow VALUES (?,?)", flows)

    con.execute("DROP TABLE IF EXISTS dim_code_type")
    con.execute("CREATE TABLE dim_code_type(code VARCHAR PRIMARY KEY, description VARCHAR)")
    con.executemany("INSERT INTO dim_code_type VALUES (?,?)", types)

    con.execute("DROP TABLE IF EXISTS dim_methodology")
    con.execute("""CREATE TABLE dim_methodology(
        code VARCHAR PRIMARY KEY, description VARCHAR, mclass VARCHAR)""")
    con.executemany("INSERT INTO dim_methodology VALUES (?,?,?)",
                    [(c, d, mclass(c)) for c, d in meths])

    for t in ("dim_area", "dim_service", "dim_flow", "dim_code_type", "dim_methodology"):
        n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        log.info("%-16s %4d행", t, n)

    log.info("BaTIS 자료에 있으나 코드표에 없는 경제: %s", con.execute(
        "SELECT list(code) FROM dim_area WHERE in_batis AND name_codes IS NULL").fetchone()[0])
    log.info("코드표에만 있는 경제: %s", con.execute(
        "SELECT list(code) FROM dim_area WHERE NOT in_batis AND NOT in_bimts").fetchone()[0])
    log.info("BIMTS에만 있는 경제: %s", con.execute(
        "SELECT list(code) FROM dim_area WHERE in_bimts AND NOT in_batis").fetchone()[0])
    log.info("이름을 못 찾은 코드: %s", con.execute(
        "SELECT list(code) FROM dim_area WHERE name_sdmx IS NULL AND name_codes IS NULL").fetchone()[0])
    log.info("집계로 판정한 코드(중복 집계 주의): %s", con.execute(
        "SELECT list(code) FROM dim_area WHERE is_aggregate").fetchone()[0])
    log.info("방법론 분류: %s", con.execute(
        "SELECT mclass, count(*) FROM dim_methodology GROUP BY 1 ORDER BY 2 DESC").fetchall())

    for col, dim, key in (("reporter", "dim_area", "code"), ("partner", "dim_area", "code"),
                          ("item_code", "dim_service", "item_code"), ("flow", "dim_flow", "code"),
                          ("methodology", "dim_methodology", "code")):
        miss = con.execute(f"""
            SELECT count(DISTINCT f.{col}) FROM fact_batis f
            LEFT JOIN {dim} d ON f.{col}=d.{key} WHERE d.{key} IS NULL AND f.{col} IS NOT NULL
        """).fetchone()[0]
        log.info("미매칭 %s → %s: %d", col, dim, miss)
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

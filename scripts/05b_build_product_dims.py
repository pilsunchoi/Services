"""품목 코드 dim — HS2017, CPA 2.1.

OECD SDMX 코드표에서 받는다. 코드가 `HS17_0101` 꼴이라 접두사를 뗀 자릿수로 단위를
매긴다(2·4·6). 이 `level`만이 우리가 덧붙이는 값이다.

  python scripts/05b_build_product_dims.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils.common import DB_PATH, EXTERNAL, setup_logging  # noqa: E402

HDR = {"Accept": "application/vnd.sdmx.structure+json;version=1.0;urn=true"}
LISTS = {
    "dim_hs2017": ("CL_PRODUCT_HS2017", "HS17_"),
    "dim_cpa21": ("CL_PRODUCT_CPA_2_1", "CPA_2_1_"),
}


def fetch(cl_id: str, log) -> list[dict]:
    cache = EXTERNAL / f"{cl_id}.json"
    if not cache.exists():
        url = f"https://sdmx.oecd.org/public/rest/codelist/all/{cl_id}/latest?references=none&detail=full"
        log.info("%s 내려받기", cl_id)
        r = requests.get(url, headers=HDR, timeout=180)
        r.raise_for_status()
        cache.write_text(r.text, encoding="utf-8")
    d = json.loads(cache.read_text(encoding="utf-8"))
    return d["data"]["codelists"][0]["codes"]


def main() -> int:
    log = setup_logging("build_product_dims")
    con = duckdb.connect(str(DB_PATH))
    for table, (cl_id, prefix) in LISTS.items():
        codes = fetch(cl_id, log)
        rows = []
        for c in codes:
            code = c["id"]
            digits = code[len(prefix):] if code.startswith(prefix) else None
            level = len(digits) if digits and digits.isdigit() else None
            rows.append((code, c.get("name"), level, digits))
        con.execute(f"DROP TABLE IF EXISTS {table}")
        con.execute(f"""CREATE TABLE {table}(
            code VARCHAR PRIMARY KEY, name_en VARCHAR, level SMALLINT, digits VARCHAR)""")
        con.executemany(f"INSERT INTO {table} VALUES (?,?,?,?)", rows)
        log.info("%-12s %5d행 | 단위별 %s", table, len(rows), con.execute(
            f"SELECT level, count(*) FROM {table} GROUP BY 1 ORDER BY 1").fetchall())

    tables = {r[0] for r in con.execute("SELECT table_name FROM duckdb_tables()").fetchall()}
    for fact, dim in (("fact_bimts_hs2", "dim_hs2017"), ("fact_bimts_cpa2", "dim_cpa21")):
        if fact in tables:
            miss = con.execute(f"""
                SELECT count(DISTINCT f.product) FROM {fact} f
                LEFT JOIN {dim} d ON f.product=d.code WHERE d.code IS NULL""").fetchone()[0]
            log.info("미매칭 %s.product → %s: %d", fact, dim, miss)
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

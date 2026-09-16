"""BIMTS 벌크 CSV → parquet → DuckDB (2단위: HS2017 2D, CPA 2.1).

원본은 SDMX-CSV 형식이라 값마다 차원이 다 붙어 있고, 그중 여럿은 파일 전체에서
한 값이다(FREQ=A, UNIT_MEASURE=USD_EXC, TRADE_FLOW=X 등). 그런 열은 **상수임을
확인한 뒤** fact에서 빼고 `meta_constants`에 값으로 남긴다. 확인 없이 빼면 다음 판에서
값이 늘어난 것을 놓치므로, 상수가 아니면 중단한다.

BIMTS는 수출국 기준 단일 기록이다(REF_AREA=수출국, COUNTERPART_AREA=수입국).
0 거래는 행이 없다 — 우리가 채우지 않는다.

  python scripts/04_load_bimts.py                 # hs2 + cpa2
  python scripts/04_load_bimts.py --only hs2
"""
from __future__ import annotations

import argparse
import sys
import time
import zipfile
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils.common import DB_PATH, INTERIM, RAW, setup_logging  # noqa: E402

EDITION = "2026-05"

SETS = {
    "hs2": {
        "zip": "HS17_2D_DE_1995_To_2024.zip",
        "table": "fact_bimts_hs2",
        "product_col": "PRODUCT_HS",
        "note": "HS2017 2단위. REF_AREA=수출국. 균형치 B·B_ADJ_RX. 0은 행이 없다.",
    },
    "cpa2": {
        "zip": "CPA_2D_DE_1995_To_2024.zip",
        "table": "fact_bimts_cpa2",
        "product_col": "PRODUCT_CPA",
        "note": "CPA 2.1 2단위. REF_AREA=수출국. 균형치 B·B_ADJ_RX. 0은 행이 없다.",
    },
}

EXPECTED_HEADER = [
    "DATAFLOW", "REF_AREA", "COUNTERPART_AREA", "TRADE_FLOW", "PRODUCT_TYPE",
    "PRODUCT_CPA", "PRODUCT_HS", "FREQ", "TIME_PERIOD", "OBS_VALUE", "OBS_STATUS",
    "METHODOLOGY_TYPE", "UNIT_MULT", "UNIT_MEASURE", "ADJUSTMENT", "DECIMALS",
]

# fact에 남길 열 — 나머지는 상수 확인 후 meta_constants로
KEEP = ["REF_AREA", "COUNTERPART_AREA", "TIME_PERIOD", "OBS_VALUE",
        "OBS_STATUS", "METHODOLOGY_TYPE", "ADJUSTMENT"]


def load_one(con, key: str, cfg: dict, log, keep_csv: bool) -> None:
    zip_path = RAW / "bimts" / EDITION / cfg["zip"]
    if not zip_path.exists():
        log.error("원본이 없다: %s — 먼저 02_fetch_bimts.py", zip_path)
        raise SystemExit(1)

    work = INTERIM / "bimts" / EDITION / key
    work.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        members = [i.filename for i in z.infolist() if i.filename.lower().endswith(".csv")]
        todo = [m for m in members if not (work / m).exists()]
        if todo:
            t0 = time.time()
            log.info("압축 해제 %d개 (%s)", len(todo), cfg["zip"])
            for m in todo:
                z.extract(m, work)
            log.info("해제 %.0f초", time.time() - t0)

    first = work / members[0]
    with open(first, "r", encoding="utf-8-sig") as f:
        header = f.readline().strip().split(",")
    if header != EXPECTED_HEADER:
        log.error("열 구성이 다르다.\n기대: %s\n실제: %s", EXPECTED_HEADER, header)
        raise SystemExit(2)

    glob = (work / "*.csv").as_posix()
    pq = work.parent / f"bimts_{key}.parquet"
    if not pq.exists():
        t0 = time.time()
        log.info("CSV → parquet (%s)", key)
        con.execute(
            f"COPY (SELECT * FROM read_csv('{glob}', header=true, union_by_name=true, "
            f"types={{'TIME_PERIOD':'SMALLINT','OBS_VALUE':'DOUBLE'}})) "
            f"TO '{pq.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
        log.info("parquet %s bytes, %.0f초", f"{pq.stat().st_size:,}", time.time() - t0)

    pqs = pq.as_posix()
    const_cols = [c for c in EXPECTED_HEADER if c not in KEEP and c != cfg["product_col"]]
    consts = {}
    for c in const_cols:
        vals = con.execute(
            f'SELECT DISTINCT "{c}" FROM read_parquet(\'{pqs}\') LIMIT 5').fetchall()
        if len(vals) != 1:
            log.error("%s 가 상수가 아니다(%s) — fact에서 뺄 수 없다", c, vals)
            raise SystemExit(3)
        consts[c] = vals[0][0]
        log.info("상수 확인 %-16s = %s", c, vals[0][0])

    t0 = time.time()
    tbl = cfg["table"]
    log.info("%s 적재", tbl)
    con.execute(f"DROP TABLE IF EXISTS {tbl}")
    con.execute(f"""
        CREATE TABLE {tbl} AS
        SELECT '{EDITION}'      AS edition,
               REF_AREA         AS exporter,
               COUNTERPART_AREA AS importer,
               "{cfg['product_col']}" AS product,
               TIME_PERIOD      AS year,
               ADJUSTMENT       AS adjustment,
               OBS_VALUE        AS value,
               OBS_STATUS       AS obs_status,
               METHODOLOGY_TYPE AS methodology_type
        FROM read_parquet('{pqs}')
    """)
    rows = con.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]
    log.info("%s %s행, %.0f초", tbl, f"{rows:,}", time.time() - t0)
    s = con.execute(f"""
        SELECT min(year), max(year), count(DISTINCT exporter), count(DISTINCT importer),
               count(DISTINCT product), count(DISTINCT adjustment),
               count(*) FILTER (WHERE value = 0)
        FROM {tbl}""").fetchone()
    log.info("기간 %s–%s | 수출국 %s · 수입국 %s · 품목 %s · 균형치 %s종 | 값이 0인 행 %s",
             *s[:6], f"{s[6]:,}")

    con.execute("""CREATE TABLE IF NOT EXISTS meta_constants(
        table_name VARCHAR, column_name VARCHAR, value VARCHAR, note VARCHAR)""")
    con.execute("DELETE FROM meta_constants WHERE table_name=?", [tbl])
    con.executemany("INSERT INTO meta_constants VALUES (?,?,?,?)",
                    [(tbl, c, str(v), "원본 열. 파일 전체에서 한 값이라 fact에서 뺐다")
                     for c, v in consts.items()])

    con.execute("""CREATE TABLE IF NOT EXISTS dim_edition(
        dataset VARCHAR, edition VARCHAR, table_name VARCHAR,
        rows BIGINT, loaded_at TIMESTAMP, source_file VARCHAR, note VARCHAR)""")
    con.execute("DELETE FROM dim_edition WHERE dataset='bimts' AND edition=? AND table_name=?",
                [EDITION, tbl])
    con.execute("INSERT INTO dim_edition VALUES ('bimts', ?, ?, ?, now(), ?, ?)",
                [EDITION, tbl, rows, str(zip_path), cfg["note"]])

    if not keep_csv:
        for m in members:
            (work / m).unlink(missing_ok=True)
        log.info("푼 CSV 삭제(zip과 parquet이 남는다)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=list(SETS), nargs="*", default=list(SETS))
    ap.add_argument("--keep-csv", action="store_true")
    args = ap.parse_args()
    log = setup_logging("load_bimts")

    con = duckdb.connect(str(DB_PATH))
    con.execute("PRAGMA enable_progress_bar=false")
    for key in args.only:
        load_one(con, key, SETS[key], log, args.keep_csv)
    con.close()
    log.info("DB: %s", DB_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

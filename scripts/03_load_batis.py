"""BaTIS 벌크 CSV → parquet → DuckDB.

절차는 KCSDB2와 같다. raw(zip)는 건드리지 않고, 압축을 interim으로 풀어 parquet을
거쳐 DuckDB에 싣는다.

fact_batis에 싣는 것은 원본 12열 중 관측·식별 9열이다. `type_Reporter`,
`type_Partner`, `type_Item`은 코드의 성질(국가/그룹, 표준/파생)을 되풀이하는 참조
속성이라 dim으로 보낸다 — KCSDB2가 `stat_kor`(국명)를 fact에서 뺀 것과 같은 판단이다.
빼기 전에 "코드 하나에 성질 하나"가 실제로 성립하는지 확인한다(성립하지 않으면 중단).

  python scripts/03_load_batis.py
  python scripts/03_load_batis.py --keep-csv     # 푼 CSV를 지우지 않는다
"""
from __future__ import annotations

import argparse
import sys
import time
import zipfile
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils.common import DB_PATH, INTERIM, PROCESSED, RAW, setup_logging  # noqa: E402

EDITION = "2025-12"
ZIP_NAME = "OECD-WTO_BATIS_BPM6_December2025_bulk.zip"
CSV_NAME = "OECD-WTO_BATIS_BPM6_December2025_bulk.csv"

EXPECTED_HEADER = [
    "Reporter", "type_Reporter", "Partner", "type_Partner", "Flow", "Item_code",
    "type_Item", "Year", "Reported_value", "Final_value", "Methodology", "Balanced_value",
]

COLUMNS = {
    "Reporter": "VARCHAR", "type_Reporter": "VARCHAR",
    "Partner": "VARCHAR", "type_Partner": "VARCHAR",
    "Flow": "VARCHAR", "Item_code": "VARCHAR", "type_Item": "VARCHAR",
    "Year": "SMALLINT",
    "Reported_value": "DOUBLE", "Final_value": "DOUBLE",
    "Methodology": "VARCHAR", "Balanced_value": "DOUBLE",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-csv", action="store_true")
    args = ap.parse_args()
    log = setup_logging("load_batis")

    zip_path = RAW / "batis" / EDITION / ZIP_NAME
    if not zip_path.exists():
        log.error("원본이 없다: %s — 먼저 01_fetch_batis.py", zip_path)
        return 1

    work = INTERIM / "batis" / EDITION
    work.mkdir(parents=True, exist_ok=True)
    csv_path = work / CSV_NAME
    if not csv_path.exists():
        t0 = time.time()
        log.info("압축 해제: %s → %s", ZIP_NAME, work)
        with zipfile.ZipFile(zip_path) as z:
            z.extract(CSV_NAME, work)
        log.info("해제 완료 %s bytes, %.0f초", f"{csv_path.stat().st_size:,}", time.time() - t0)

    with open(csv_path, "r", encoding="utf-8-sig") as f:
        header = f.readline().strip().split(",")
    if header != EXPECTED_HEADER:
        log.error("열 구성이 다르다. 판이 바뀌었을 수 있다.\n기대: %s\n실제: %s",
                  EXPECTED_HEADER, header)
        return 2
    log.info("열 구성 확인 12개: %s", ", ".join(header))

    PROCESSED.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    con.execute("PRAGMA enable_progress_bar=false")

    pq = work / "batis_raw.parquet"
    if not pq.exists():
        t0 = time.time()
        log.info("CSV → parquet (zstd)")
        # COPY ... TO 는 준비된 파라미터를 받지 않는다. 경로를 직접 박되 슬래시로 쓴다.
        cols_sql = ", ".join(f"'{k}': '{v}'" for k, v in COLUMNS.items())
        con.execute(
            f"COPY (SELECT * FROM read_csv('{csv_path.as_posix()}', header=true, "
            f"columns={{{cols_sql}}}, nullstr='')) "
            f"TO '{pq.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
        log.info("parquet %s bytes, %.0f초", f"{pq.stat().st_size:,}", time.time() - t0)

    # 성질 열이 코드의 함수인지 — 아니면 dim으로 보낼 수 없다
    for code_col, type_col in (("Reporter", "type_Reporter"),
                               ("Partner", "type_Partner"),
                               ("Item_code", "type_Item")):
        n = con.execute(
            f'SELECT count(*) FROM (SELECT "{code_col}" FROM read_parquet(?) '
            f'GROUP BY 1 HAVING count(DISTINCT "{type_col}") > 1)', [str(pq)]
        ).fetchone()[0]
        if n:
            log.error("%s 하나에 %s가 둘 이상인 코드 %d개 — fact에서 뺄 수 없다", code_col, type_col, n)
            return 3
        log.info("확인: %s → %s 는 일대일", code_col, type_col)

    t0 = time.time()
    log.info("fact_batis 적재")
    con.execute("DROP TABLE IF EXISTS fact_batis")
    con.execute(
        """
        CREATE TABLE fact_batis AS
        SELECT ? AS edition,
               Reporter        AS reporter,
               Partner         AS partner,
               Flow            AS flow,
               Item_code       AS item_code,
               Year            AS year,
               Reported_value  AS reported_value,
               Final_value     AS final_value,
               Methodology     AS methodology,
               Balanced_value  AS balanced_value
        FROM read_parquet(?)
        """,
        [EDITION, str(pq)],
    )
    rows = con.execute("SELECT count(*) FROM fact_batis").fetchone()[0]
    log.info("fact_batis %s행, %.0f초", f"{rows:,}", time.time() - t0)

    summary = con.execute(
        """
        SELECT min(year), max(year),
               count(DISTINCT reporter), count(DISTINCT partner),
               count(DISTINCT item_code), count(DISTINCT flow),
               count(DISTINCT methodology),
               sum(reported_value IS NOT NULL), sum(final_value IS NOT NULL),
               sum(balanced_value IS NOT NULL)
        FROM fact_batis
        """
    ).fetchone()
    log.info("기간 %s–%s | 보고국 %s · 상대국 %s · 항목 %s · flow %s · 방법론 %s",
             *summary[:7])
    log.info("값 있는 행: reported %s (%.1f%%) · final %s · balanced %s",
             f"{summary[7]:,}", 100 * summary[7] / rows, f"{summary[8]:,}", f"{summary[9]:,}")

    # 판 이력
    con.execute("""
        CREATE TABLE IF NOT EXISTS dim_edition(
            dataset VARCHAR, edition VARCHAR, table_name VARCHAR,
            rows BIGINT, loaded_at TIMESTAMP, source_file VARCHAR, note VARCHAR)
    """)
    con.execute("DELETE FROM dim_edition WHERE dataset='batis' AND edition=? AND table_name='fact_batis'",
                [EDITION])
    con.execute(
        "INSERT INTO dim_edition VALUES ('batis', ?, 'fact_batis', ?, now(), ?, ?)",
        [EDITION, rows, str(zip_path),
         "OECD 미러(webfs-sdd). ISO3 코드·EXP/IMP·방법론 37코드판. 단위 백만 USD."],
    )
    con.close()

    if not args.keep_csv:
        csv_path.unlink()
        log.info("푼 CSV 삭제(원본 zip과 parquet이 남는다)")
    log.info("DB: %s", DB_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

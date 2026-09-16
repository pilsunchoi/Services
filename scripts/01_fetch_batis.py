"""BaTIS 벌크 파일 수집.

OECD 미러(webfs-sdd)를 정본으로 삼는다. 데이터 CSV와 코드표 xlsx가 한 zip에 들어
있고 Range를 지원해 이어받기가 된다. WTO 미러는 --wto로 함께 받아 CSV 해시를 대조할
때 쓴다(내용 동일 여부는 확인된 바 없다).

  python scripts/01_fetch_batis.py
  python scripts/01_fetch_batis.py --wto        # WTO 미러도 받아 대조
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils.common import EXTERNAL, RAW, download, probe, setup_logging, sha256_file, write_manifest  # noqa: E402

DATASET = "batis"
EDITION = "2025-12"

OECD_URL = "https://webfs-sdd.oecd.org/files/.Stat/BATIS/OECD-WTO_BATIS_BPM6_December2025_bulk.zip"
WTO_BASE = "https://www.wto.org/english/res_e/statis_e/daily_update_e/"
WTO_FILES = [
    "OECD-WTO_BATIS_data_BPM6-1.zip",
    "OECD-WTO_BATIS_codes_BPM6-1.zip",
    "OECD-WTO_Batis_methodology_BPM6.pdf",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wto", action="store_true", help="WTO 미러도 받는다(대조용)")
    ap.add_argument("--no-methodology", dest="methodology", action="store_false",
                    default=True, help="방법론 PDF를 받지 않는다")
    args = ap.parse_args()

    log = setup_logging("fetch_batis")
    dest_dir = RAW / DATASET / EDITION
    entries = []

    log.info("=== OECD 미러(정본) ===")
    info = probe(OECD_URL)
    log.info("probe: %s", info)
    dest = dest_dir / Path(OECD_URL).name
    if dest.exists() and info.get("bytes") and dest.stat().st_size == info["bytes"]:
        log.info("이미 받은 파일이 크기까지 같다. 건너뛴다: %s", dest.name)
        res = {"path": str(dest), "bytes": dest.stat().st_size}
    else:
        res = download(OECD_URL, dest, log, expect_bytes=info.get("bytes"))
    res.update(url=OECD_URL, mirror="oecd", sha256=sha256_file(dest, log),
               last_modified=info.get("last_modified"))
    entries.append(res)

    if args.wto:
        log.info("=== WTO 미러(대조용) ===")
        for name in WTO_FILES:
            url = WTO_BASE + name
            info = probe(url)
            log.info("probe %s: bytes=%s last_modified=%s", name, info.get("bytes"),
                     info.get("last_modified"))
            d = dest_dir / "wto_mirror" / name
            if d.exists() and info.get("bytes") and d.stat().st_size == info["bytes"]:
                log.info("이미 받음: %s", name)
                r = {"path": str(d), "bytes": d.stat().st_size}
            else:
                r = download(url, d, log, expect_bytes=info.get("bytes"))
            r.update(url=url, mirror="wto", sha256=sha256_file(d, log),
                     last_modified=info.get("last_modified"))
            entries.append(r)

    if args.methodology:
        # 방법론 문서는 자료의 일부다 — 값이 어떻게 만들어졌는지가 여기에만 있다
        for url, name in (
            (WTO_BASE + "OECD-WTO_Batis_methodology_BPM6.pdf", "BaTIS_methodology_BPM6.pdf"),
            ("https://www.oecd.org/content/dam/oecd/en/publications/reports/2025/04/"
             "the-oecd-balanced-international-merchandise-trade-dataset-bimts_a521edbf/"
             "07518168-en.pdf", "BIMTS_methodology.pdf"),
        ):
            d = EXTERNAL / name
            if d.exists():
                log.info("이미 있음: %s", d.name)
                continue
            try:
                download(url, d, log)
            except Exception as e:
                log.warning("방법론 문서 실패 %s: %r", url.rsplit("/", 1)[-1], e)

    man = write_manifest(DATASET, EDITION, entries,
                         extra={"note": "OECD 미러가 정본. zip 안에 bulk.csv와 codes.xlsx가 있다."})
    log.info("manifest: %s", man)
    log.info("파일 %d개, 합계 %s bytes", len(entries), f"{sum(e['bytes'] for e in entries):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

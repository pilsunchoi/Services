"""BIMTS 벌크 파일 수집.

받을 파일 목록을 우리가 적어 두지 않고 OECD SDMX 데이터흐름의 `EXT_RESOURCE`
주석에서 읽어 온다. OECD가 파일을 갈면 목록도 따라 바뀐다.

두 경로가 있는데 같은 파일이다. `webfs-sdd.oecd.org`는 Range를 지원해 이어받기가
되고, 데이터 탐색기 화면의 `stats.oecd.org/wbos/fileview2.aspx`는 HEAD도 Range도
막혀 있다. 그래서 webfs 쪽만 쓴다.

  python scripts/02_fetch_bimts.py --depth 2d cpa      # 2단계(권장)
  python scripts/02_fetch_bimts.py --list              # 목록만 보고 받지 않는다
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils.common import EXTERNAL, RAW, download, probe, setup_logging, sha256_file, write_manifest  # noqa: E402

DATASET = "bimts"
SDMX = "https://sdmx.oecd.org/public/rest/dataflow/OECD.SDD.TPS"
FLOWS = ["DSD_BIMTS@DF_BIMTS_HS2017_2D", "DSD_BIMTS@DF_BIMTS_CPA_2_1",
         "DSD_BIMTS_6D@DF_BIMTS_HS2017_6D"]
HDR = {"Accept": "application/vnd.sdmx.structure+json;version=1.0;urn=true"}


def discover(log) -> list[dict]:
    """데이터흐름 주석에서 (이름, URL)을 긁는다. 중복은 URL로 접는다."""
    found: dict[str, dict] = {}
    for flow in FLOWS:
        r = requests.get(f"{SDMX}/{flow}/latest?detail=full&references=none",
                         headers=HDR, timeout=120)
        r.raise_for_status()
        df = r.json()["data"]["dataflows"][0]
        for a in df.get("annotations", []):
            if a.get("type") != "EXT_RESOURCE":
                continue
            text = a.get("text") or ""
            if "|" not in text:
                continue
            name, url = text.split("|", 1)
            if "webfs-sdd.oecd.org" not in url:
                continue  # fileview2.aspx 판은 이어받기가 안 된다
            found[url] = {"label": name.strip(), "url": url.strip(),
                          "filename": url.rsplit("/", 1)[-1]}
    out = sorted(found.values(), key=lambda d: d["filename"])
    log.info("SDMX 주석에서 찾은 파일 %d개", len(out))
    return out


def depth_of(fn: str) -> str:
    if fn.startswith("CPA"):
        return "cpa"
    m = re.match(r"HS17_(\d)D", fn)
    if m:
        return f"{m.group(1)}d"
    return "info"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--depth", nargs="+", default=["2d", "cpa"],
                    choices=["2d", "4d", "6d", "cpa"], help="받을 해상도")
    ap.add_argument("--format", default="parquet", choices=["parquet", "csv"],
                    help="4d·6d에만 해당(2d·cpa는 CSV판만 있다)")
    ap.add_argument("--list", action="store_true", help="목록만 출력")
    args = ap.parse_args()
    log = setup_logging("fetch_bimts")

    files = discover(log)
    wanted = []
    for f in files:
        d = depth_of(f["filename"])
        if d == "info":
            wanted.append(f)
            continue
        if d not in args.depth:
            continue
        if d in ("4d", "6d"):
            is_parquet = "Parquet" in f["filename"]
            if (args.format == "parquet") != is_parquet:
                continue
        wanted.append(f)

    edition = None
    for f in wanted:
        info = probe(f["url"])
        f.update(bytes_remote=info.get("bytes"), last_modified=info.get("last_modified"),
                 range_supported=info.get("range_supported"))
        if f["filename"].endswith(".zip") and info.get("last_modified"):
            # 판은 파일 갱신일에서 딴다(OECD가 판 번호를 파일명에 넣지 않는다)
            from email.utils import parsedate_to_datetime
            edition = parsedate_to_datetime(info["last_modified"]).strftime("%Y-%m")
        log.info("%-40s %14s bytes  range=%s  %s", f["filename"],
                 f"{info.get('bytes'):,}" if info.get("bytes") else "?",
                 info.get("range_supported"), info.get("last_modified"))

    total = sum(f.get("bytes_remote") or 0 for f in wanted)
    log.info("받을 파일 %d개, 합계 %.1f GB, 판 %s", len(wanted), total / 1e9, edition)
    if args.list:
        return 0

    edition = edition or "unknown"
    entries = []
    for f in wanted:
        target_dir = EXTERNAL if f["filename"].endswith(".txt") else RAW / DATASET / edition
        dest = target_dir / f["filename"]
        if dest.exists() and f.get("bytes_remote") and dest.stat().st_size == f["bytes_remote"]:
            log.info("이미 받음: %s", f["filename"])
            res = {"path": str(dest), "bytes": dest.stat().st_size}
        else:
            res = download(f["url"], dest, log, expect_bytes=f.get("bytes_remote"))
        res.update(url=f["url"], label=f["label"], last_modified=f.get("last_modified"),
                   sha256=sha256_file(dest, log))
        entries.append(res)

    man = write_manifest(DATASET, edition, entries,
                         extra={"note": "webfs-sdd 미러. 판은 파일 Last-Modified에서 땄다."})
    log.info("manifest: %s", man)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

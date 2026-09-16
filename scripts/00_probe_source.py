"""원천 점검 — 판이 바뀌었는지 본다.

OECD는 새 판을 내면서 URL을 그대로 두고 내용만 갈아 끼운다. 그래서 크기·갱신일·해시를
정기적으로 대조하지 않으면 우리가 가진 판이 무엇인지 알 수 없게 된다. 이 스크립트는
원격 머리글을 읽어 manifest에 적힌 값과 맞대고, 달라진 것을 알린다. 내려받지는 않는다.

  python scripts/00_probe_source.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils.common import EXTERNAL, RAW, now_iso, probe, setup_logging  # noqa: E402

BATIS_URLS = [
    "https://webfs-sdd.oecd.org/files/.Stat/BATIS/OECD-WTO_BATIS_BPM6_December2025_bulk.zip",
    "https://www.wto.org/english/res_e/statis_e/daily_update_e/OECD-WTO_BATIS_data_BPM6-1.zip",
]
SDMX = "https://sdmx.oecd.org/public/rest"
HDR = {"Accept": "application/vnd.sdmx.structure+json;version=1.0;urn=true"}
FLOWS = {
    "BaTIS": "DSD_BATIS@DF_BATIS",
    "BIMTS 2D": "DSD_BIMTS@DF_BIMTS_HS2017_2D",
    "BIMTS CPA": "DSD_BIMTS@DF_BIMTS_CPA_2_1",
    "BIMTS 6D": "DSD_BIMTS_6D@DF_BIMTS_HS2017_6D",
}


def manifest_index() -> dict[str, dict]:
    out = {}
    for man in RAW.glob("*/*/manifest.json"):
        d = json.loads(man.read_text(encoding="utf-8"))
        for f in d.get("files", []):
            out[f["url"]] = {**f, "dataset": d["dataset"], "edition": d["edition"]}
    return out


def ext_resources(flow: str) -> list[tuple[str, str]]:
    r = requests.get(f"{SDMX}/dataflow/OECD.SDD.TPS/{flow}/latest?detail=full&references=none",
                     headers=HDR, timeout=120)
    r.raise_for_status()
    df = r.json()["data"]["dataflows"][0]
    out = []
    for a in df.get("annotations", []):
        if a.get("type") == "EXT_RESOURCE" and "|" in (a.get("text") or ""):
            name, url = a["text"].split("|", 1)
            out.append((name.strip(), url.strip()))
    return out


def obs_count(flow: str) -> str:
    try:
        r = requests.get(f"{SDMX}/availableconstraint/OECD.SDD.TPS,{flow},1.0/all/all"
                         "?mode=available&references=none", headers=HDR, timeout=300)
        if r.status_code != 200:
            return f"(조회 불가 {r.status_code})"
        cc = r.json()["data"]["contentConstraints"][0]
        for a in cc.get("annotations", []):
            if a.get("id") == "obs_count":
                return f"{int(a['title']):,}"
    except Exception as e:
        return f"(실패 {e!r})"
    return "(없음)"


def main() -> int:
    log = setup_logging("probe_source")
    have = manifest_index()
    report = {"probed_at": now_iso(), "files": [], "dataflows": {}}

    log.info("=== 데이터흐름 ===")
    urls = list(BATIS_URLS)
    for label, flow in FLOWS.items():
        n = obs_count(flow)
        report["dataflows"][label] = {"flow": flow, "obs_count": n}
        log.info("%-10s %-34s 관측치 %s", label, flow, n)
        for name, url in ext_resources(flow):
            if "webfs-sdd.oecd.org" in url and url not in urls:
                urls.append(url)

    log.info("=== 파일 ===")
    for url in urls:
        info = probe(url)
        old = have.get(url)
        changed = None
        if old:
            changed = (old.get("bytes") != info.get("bytes")
                       or (old.get("last_modified") and old["last_modified"] != info.get("last_modified")))
        status = "새 판?" if changed else ("보유" if old else "미보유")
        report["files"].append({**info, "status": status,
                                "held_edition": old["edition"] if old else None})
        log.info("%-8s %-48s %14s bytes  %s", status, url.rsplit("/", 1)[-1],
                 f"{info.get('bytes'):,}" if info.get("bytes") else "?",
                 info.get("last_modified") or "")
        if changed:
            log.warning("  ↑ 보유본과 다르다: 보유 %s bytes / %s", f"{old.get('bytes'):,}",
                        old.get("last_modified"))

    out = EXTERNAL / f"source_probe_{now_iso()[:10].replace('-', '')}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("기록: %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""공통 유틸 — 경로, 로깅, 내려받기.

원칙: 원본은 data/raw/<dataset>/<edition>/ 에 그대로 두고 manifest.json에
URL·크기·해시·시각을 남긴다. OECD는 같은 URL의 내용을 판이 바뀔 때 교체하므로
해시가 유일한 판별 근거다.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"
INTERIM = DATA / "interim"
PROCESSED = DATA / "processed"
EXTERNAL = DATA / "external"
LOGS = ROOT / "logs"
DB_PATH = PROCESSED / "svcdb.duckdb"

UA = "Mozilla/5.0 (research data collection; svcdb)"
CHUNK = 1 << 20  # 1 MiB


def setup_logging(name: str) -> logging.Logger:
    LOGS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logfile = LOGS / f"{name}_{stamp}.log"
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fh = logging.FileHandler(logfile, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    logger.info("log file: %s", logfile)
    return logger


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path, log: logging.Logger | None = None) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(CHUNK * 8)
            if not b:
                break
            h.update(b)
    digest = h.hexdigest()
    if log:
        log.info("sha256 %s = %s", path.name, digest)
    return digest


def probe(url: str, timeout: int = 60) -> dict:
    """HEAD이 막힌 서버가 있어(OECD fileview2.aspx는 405) Range GET으로 머리만 읽는다."""
    out = {"url": url}
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Range": "bytes=0-0"},
                         stream=True, timeout=timeout, allow_redirects=True)
        out["status"] = r.status_code
        h = r.headers
        out["accept_ranges"] = h.get("Accept-Ranges")
        out["content_range"] = h.get("Content-Range")
        out["content_type"] = h.get("Content-Type")
        out["last_modified"] = h.get("Last-Modified")
        out["content_disposition"] = h.get("Content-Disposition")
        if out.get("content_range"):
            out["bytes"] = int(out["content_range"].split("/")[-1])
            out["range_supported"] = True
        else:
            cl = h.get("Content-Length")
            out["bytes"] = int(cl) if cl else None
            out["range_supported"] = False
        r.close()
    except Exception as e:  # 진단용이므로 삼키고 기록만
        out["error"] = repr(e)
    return out


def download(url: str, dest: Path, log: logging.Logger, resume: bool = True,
             expect_bytes: int | None = None) -> dict:
    """이어받기 가능한 내려받기. 서버가 Range를 무시하면 처음부터 다시 받는다."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    have = part.stat().st_size if (resume and part.exists()) else 0
    headers = {"User-Agent": UA}
    if have:
        headers["Range"] = f"bytes={have}-"
        log.info("이어받기 시도: %s 부터", f"{have:,}")

    t0 = time.time()
    with requests.get(url, headers=headers, stream=True, timeout=120) as r:
        r.raise_for_status()
        if have and r.status_code != 206:
            log.warning("서버가 Range를 무시했다(status=%s). 처음부터 받는다.", r.status_code)
            have = 0
        total = r.headers.get("Content-Length")
        total = (int(total) + have) if total else expect_bytes
        mode = "ab" if have else "wb"
        done = have
        last_report = 0
        with open(part, mode) as f:
            for block in r.iter_content(CHUNK):
                if not block:
                    continue
                f.write(block)
                done += len(block)
                if done - last_report >= 50 * CHUNK:
                    last_report = done
                    pct = f" ({done / total:.1%})" if total else ""
                    log.info("  %s bytes%s", f"{done:,}", pct)

    elapsed = time.time() - t0
    size = part.stat().st_size
    if total and size != total:
        raise IOError(f"크기 불일치: 받은 {size:,} 기대 {total:,}")
    part.replace(dest)
    log.info("완료 %s (%s bytes, %.1f초, %.1f MB/s)", dest.name, f"{size:,}",
             elapsed, (size - have) / max(elapsed, 1e-9) / 1e6)
    return {"path": str(dest), "bytes": size, "seconds": round(elapsed, 1)}


def write_manifest(dataset: str, edition: str, entries: list[dict], extra: dict | None = None) -> Path:
    d = RAW / dataset / edition
    d.mkdir(parents=True, exist_ok=True)
    man = {
        "dataset": dataset,
        "edition": edition,
        "fetched_at": now_iso(),
        "files": entries,
    }
    if extra:
        man.update(extra)
    p = d / "manifest.json"
    p.write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
    return p

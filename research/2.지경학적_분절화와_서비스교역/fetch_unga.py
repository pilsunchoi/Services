"""UN 총회 이념점수(Bailey, Strezhnev & Voeten)를 받는다.

하버드 데이터버스 doi:10.7910/DVN/LEJUQZ 의 최종 통과 표결 기준 연도별 추정치와 코드북.
파일 번호는 2026-09-16에 데이터버스 API로 확인한 값이다(데이터셋 판 39). 판이 바뀌면
번호도 바뀌므로, 실패하면 데이터셋 페이지에서 새 번호를 찾아 고친다.

  python research/2.지경학적_분절화와_서비스교역/fetch_unga.py
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "data" / "external" / "unga"
FILES = {
    14098429: "IdealpointestimatesFP_2026FP.csv",
    13642024: "Codebook_IdealPointEstimates1946-2025.txt",
}


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    for fid, name in FILES.items():
        out = DEST / name
        if out.exists():
            print("이미 있음:", name)
            continue
        r = requests.get(f"https://dataverse.harvard.edu/api/access/datafile/{fid}", timeout=180)
        r.raise_for_status()
        out.write_bytes(r.content)
        print(f"{name}: {len(r.content):,} bytes, sha256 {hashlib.sha256(r.content).hexdigest()[:16]}…")


if __name__ == "__main__":
    main()

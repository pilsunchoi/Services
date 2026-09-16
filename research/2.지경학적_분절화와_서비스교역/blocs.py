"""지정학적 블록 네 가지 정의를 만든다.

블록은 분석의 판단이지 자료가 아니므로 DB에 넣지 않고 이 폴더의 out/blocs.csv에 둔다.
정의를 하나로 고르지 않고 넷을 모두 만든다 — 이념점수 기반 분절화 측정이 정의에
민감하다는 비판(Airaudo et al. 2025, FEDS Notes)에 대응하기 위해서다.

  D1  근접 사분위, 2015~2017   미국에 가장 가까운 25% / 중국에 가장 가까운 25% / 나머지
  D2  근접 사분위, 2022~2024   같은 규칙, 사후 기간 이념점수 (최근 정렬, 역인과에 더 노출)
  D3  좁은 블록                 서방 = 러시아 정부 비우호국 지정(2022-03-05, 지령 430-r)
                                동방 = 중국(홍콩·마카오 포함) + 2022-03-02 유엔총회 ES-11/1 반대 5개국
  D4  서방 대 비서방             서방 = D3의 서방, 나머지 배정 가능한 경제 전부 = 비서방(비동맹 없음)

  D4를 처음에는 미국·중국 이념점수의 중간점으로 둘로 나누려 했으나 미국의 이념점수가
  극단값이라 중간점(1.05)이 일본(0.64)·한국(0.86)보다 높아 두 나라가 중국 쪽에 들어갔다.
  1차원 이념점수로 이분하면 이런 퇴화가 생기므로 서방 대 비서방으로 바꿨다.

이념점수가 없는 경제의 규칙(연구자 판단 항목):
  - 해외 영토는 주권국을 따른다(버뮤다·케이맨 → 영국, 아루바·퀴라소 → 네덜란드 등).
  - 홍콩·마카오는 중국을 따른다.
  - 대만은 기준안에서 미국 쪽에 둔다(비우호국 지정에 포함, 안보 정렬). 대안으로 제외한다.
  - 팔레스타인·코소보·해체된 경제·잔여 세계(WXD)는 배정하지 않는다.

이념점수 출처: Bailey, Strezhnev & Voeten (2017), 하버드 데이터버스 doi:10.7910/DVN/LEJUQZ
파일 IdealpointestimatesFP_2026FP.csv (최종 통과 표결 기준, 1946~2025).

  python research/2.지경학적_분절화와_서비스교역/blocs.py
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
IP_CSV = ROOT / "data" / "external" / "unga" / "IdealpointestimatesFP_2026FP.csv"
DB = ROOT / "data" / "processed" / "svcdb.duckdb"
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)

US, CN, NA = "US", "CN", "NON"  # "NA"는 pandas가 결측으로 읽으므로 쓰지 않는다

# 주권국을 따르는 영토
SOVEREIGN = {
    "ABW": "NLD", "CUW": "NLD", "SXM": "NLD",
    "AIA": "GBR", "BMU": "GBR", "CYM": "GBR", "MSR": "GBR", "TCA": "GBR",
    "FRO": "DNK", "NCL": "FRA", "PYF": "FRA",
    "HKG": "CHN", "MAC": "CHN",
}

# 러시아 정부 지령 430-r(2022-03-05) 비우호국 — EU 27개국 포함
EU27 = ["AUT", "BEL", "BGR", "HRV", "CYP", "CZE", "DNK", "EST", "FIN", "FRA", "DEU", "GRC",
        "HUN", "IRL", "ITA", "LVA", "LTU", "LUX", "MLT", "NLD", "POL", "PRT", "ROU", "SVK",
        "SVN", "ESP", "SWE"]
UNFRIENDLY_2022 = set(EU27) | {
    "ALB", "AND", "AUS", "CAN", "ISL", "JPN", "LIE", "FSM", "MCO", "MNE", "NZL", "MKD",
    "NOR", "SGP", "SMR", "KOR", "CHE", "TWN", "UKR", "GBR", "USA",
    # 영국 관할(지령 명시: 저지, 앵귈라, 영국령 버진아일랜드, 지브롤터) 가운데 자료에 있는 것
    "AIA",
}
# 2022-03-02 유엔총회 결의 ES-11/1 반대 5개국 + 중국과 그 특별행정구
EAST_NARROW = {"RUS", "BLR", "PRK", "ERI", "SYR", "CHN", "HKG", "MAC"}


def main() -> pd.DataFrame:
    ip = pd.read_csv(IP_CSV)
    ip = ip[["iso3c", "year", "IdealPointFP"]].dropna(subset=["iso3c"])

    def avg(y0: int, y1: int) -> pd.Series:
        return ip[ip.year.between(y0, y1)].groupby("iso3c").IdealPointFP.mean()

    pre, post = avg(2015, 2017), avg(2022, 2024)

    con = duckdb.connect(str(DB), read_only=True)
    econ = con.execute("""
        SELECT code, name_sdmx FROM dim_area
        WHERE NOT is_aggregate AND (in_batis OR in_bimts) ORDER BY code
    """).df()
    con.close()

    def quartile_blocs(ipser: pd.Series) -> dict[str, str]:
        """미국·중국에 가장 가까운 사분위. 겹치면 더 가까운 쪽."""
        s = ipser.dropna()
        d_us = (s - s["USA"]).abs()
        d_cn = (s - s["CHN"]).abs()
        q_us = d_us.quantile(0.25)
        q_cn = d_cn.quantile(0.25)
        out = {}
        for c in s.index:
            near_us, near_cn = d_us[c] <= q_us, d_cn[c] <= q_cn
            if near_us and near_cn:
                out[c] = US if d_us[c] < d_cn[c] else CN
            elif near_us:
                out[c] = US
            elif near_cn:
                out[c] = CN
            else:
                out[c] = NA
        out["USA"], out["CHN"] = US, CN
        return out

    d1, d2 = quartile_blocs(pre), quartile_blocs(post)

    rows = []
    for code, name in econ.itertuples(index=False):
        src = SOVEREIGN.get(code, code)
        rule = "이념점수" if src == code else f"주권국 {src}"
        r = {"code": code, "name": name, "ip_2015_17": pre.get(src), "ip_2022_24": post.get(src),
             "D1": d1.get(src), "D2": d2.get(src)}
        if code == "TWN":
            r.update(D1=US, D2=US)
            rule = "대만 규칙(기준안: 미국 쪽)"
        if code in UNFRIENDLY_2022:
            r["D3"] = US
        elif code in EAST_NARROW:
            r["D3"] = CN
        else:
            r["D3"] = NA
        # D3은 이념점수와 무관하므로 영토도 주권국을 따른다
        if code in SOVEREIGN and SOVEREIGN[code] in UNFRIENDLY_2022:
            r["D3"] = US
        if code in SOVEREIGN and SOVEREIGN[code] in EAST_NARROW:
            r["D3"] = CN
        for d in ("D1", "D2"):
            if r[d] is None or (isinstance(r[d], float) and pd.isna(r[d])):
                r[d] = None
        # D4: 서방 대 비서방. 배정 가능한 경제(D1이 있거나 대만)만 나눈다
        assignable = r["D1"] is not None
        r["D4"] = US if r["D3"] == US else (CN if assignable else None)
        r["rule"] = rule if r["D1"] is not None or code == "TWN" else "미배정(이념점수 없음)"
        rows.append(r)

    blocs = pd.DataFrame(rows)
    blocs.to_csv(OUT / "blocs.csv", index=False, encoding="utf-8-sig")

    print("경제 수", len(blocs))
    for d in ("D1", "D2", "D3", "D4"):
        print(d, blocs[d].value_counts(dropna=False).to_dict())
    print("\nD1과 D2가 다른 경제:", int((blocs.D1 != blocs.D2).sum()),
          "| 예:", blocs[(blocs.D1 != blocs.D2) & blocs.D1.notna()][["code", "D1", "D2"]].head(12).values.tolist())
    print("\n주요국:")
    print(blocs[blocs.code.isin(["USA", "CHN", "RUS", "KOR", "JPN", "DEU", "GBR", "IND", "BRA", "TUR",
                                 "SAU", "VNM", "IDN", "MEX", "SGP", "HKG", "TWN", "IRN", "ZAF", "ARE"])]
          [["code", "ip_2015_17", "ip_2022_24", "D1", "D2", "D3", "D4"]].round(2).to_string(index=False))
    return blocs


if __name__ == "__main__":
    main()

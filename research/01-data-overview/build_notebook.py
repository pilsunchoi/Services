"""재현 노트북(reproduce.ipynb)을 만든다.

본문이 인용한 수치를 다시 계산하고 마지막 절에서 대조한다. 어긋나면 그 자리에서
AssertionError로 멈춘다. 만든 뒤에는 nbconvert로 실행해 출력까지 담는다.

  python research/01-data-overview/build_notebook.py
  jupyter nbconvert --to notebook --execute --inplace <노트북> --ExecutePreprocessor.kernel_name=kcsdb
"""
from __future__ import annotations

from pathlib import Path

import nbformat as nbf

HERE = Path(__file__).resolve().parent
NB = HERE / "reproduce.ipynb"

cells: list = []


def md(text: str) -> None:
    cells.append(nbf.v4.new_markdown_cell(text.strip()))


def code(text: str) -> None:
    cells.append(nbf.v4.new_code_cell(text.strip()))


md("""
# 서비스 교역 자료의 구조와 기술적 개관 — 재현 노트북

`paper.md`가 인용하는 수치를 다시 계산한다.
마지막 절(§7)이 본문값과 대조하고 어긋나면 멈춘다.

필요한 것은 `duckdb`, `pandas`, `matplotlib`와 이 저장소가 만든
`data/processed/svcdb.duckdb`이다. DB를 만드는 절차는 저장소 README에 있다.
한국은행 수치는 경제통계시스템 오픈API에서 받은 값을 상수로 적어 두었다(인증키 불요).
""")

md("## §0. 연결")
code("""
import os
import duckdb
import pandas as pd

ROOT = os.path.abspath(os.getcwd())
while not os.path.exists(os.path.join(ROOT, "data", "processed", "svcdb.duckdb")):
    up = os.path.dirname(ROOT)
    if up == ROOT:
        raise FileNotFoundError("저장소 루트를 찾지 못했다")
    ROOT = up
DB = os.path.join(ROOT, "data", "processed", "svcdb.duckdb")
con = duckdb.connect(DB, read_only=True)
pd.set_option("display.width", 140)

# 집계 코드를 제외하는 조인 조각 — 섞으면 세계 총액이 두 배가 된다
IND_B = ("JOIN dim_area ar ON f.reporter=ar.code AND NOT ar.is_aggregate "
         "JOIN dim_area ap ON f.partner=ap.code AND NOT ap.is_aggregate")
IND_M = ("JOIN dim_area ae ON f.exporter=ae.code AND NOT ae.is_aggregate "
         "JOIN dim_area ai ON f.importer=ai.code AND NOT ai.is_aggregate")

con.execute("SELECT table_name, estimated_size FROM duckdb_tables() ORDER BY 1").df()
""")

md("## §1. 세계 규모 (본문 V.1)")
code(f"""
world = con.execute(f\"\"\"
WITH s AS (SELECT year, sum(balanced_value) v FROM fact_batis
           WHERE item_code='S' AND flow='EXP' AND reporter='W' AND partner='W' GROUP BY 1),
     g AS (SELECT year, sum(value) v FROM fact_bimts_hs2 f {{IND_M}}
           WHERE product='_T' AND adjustment='B' GROUP BY 1),
     gx AS (SELECT year, sum(value) v FROM fact_bimts_hs2 f {{IND_M}}
            WHERE product='_T' AND adjustment='B_ADJ_RX' GROUP BY 1)
SELECT g.year, s.v AS svc, g.v AS goods, gx.v AS goods_rx,
       100.0*s.v/(s.v+g.v) AS svc_share
FROM g LEFT JOIN s USING (year) LEFT JOIN gx USING (year) ORDER BY 1
\"\"\").df()
world[world.year >= 2005].round(1).to_string(index=False)
""")

md("## §2. 항목 구성 (본문 V.2)")
code("""
items = con.execute(\"\"\"
SELECT f.year, f.item_code, d.description, sum(f.balanced_value) v
FROM fact_batis f JOIN dim_service d USING (item_code)
WHERE f.flow='EXP' AND f.reporter='W' AND f.partner='W'
  AND f.item_code IN ('SA','SB','SC','SD','SE','SF','SG','SH','SI','SJ','SK','SL')
GROUP BY 1,2,3
\"\"\").df()
tot = items.groupby("year").v.sum()
items["share"] = items.apply(lambda r: 100 * r.v / tot[r.year], axis=1)
piv = items.pivot(index="year", columns="item_code", values="share").round(1)
piv.loc[[2005, 2019, 2020, 2024], ["SC", "SD", "SI", "SJ", "SG", "SH"]]
""")

code("""
dd = con.execute(\"\"\"
SELECT year,
  sum(balanced_value) FILTER (WHERE item_code IN ('SF','SG','SH','SI','SJ','SK')) dd,
  sum(balanced_value) FILTER (WHERE item_code='S') tot
FROM fact_batis WHERE flow='EXP' AND reporter='W' AND partner='W' GROUP BY 1 ORDER BY 1
\"\"\").df()
dd["share"] = (100 * dd.dd / dd.tot).round(1)
dd[dd.year.isin([2005, 2019, 2020, 2024])][["year", "share"]].to_string(index=False)
""")

md("## §3. 보고와 추정 (본문 V.3)")
code(f"""
cov = con.execute(\"\"\"
SELECT year,
  100.0*count(*) FILTER (WHERE reported_value IS NOT NULL)/count(*) pct_rows,
  100.0*sum(abs(reported_value)) FILTER (WHERE reported_value IS NOT NULL)
        /sum(abs(balanced_value)) pct_val
FROM fact_batis WHERE item_code='S' GROUP BY 1 ORDER BY 1
\"\"\").df().round(1)

meth = con.execute(f\"\"\"
SELECT f.year, m.mclass,
  100.0*count(*)/sum(count(*)) OVER (PARTITION BY f.year) pr,
  100.0*sum(abs(f.balanced_value))/sum(sum(abs(f.balanced_value))) OVER (PARTITION BY f.year) pv
FROM fact_batis f JOIN dim_methodology m ON f.methodology=m.code {{IND_B}}
WHERE f.item_code='S' GROUP BY 1,2
\"\"\").df()
mp = meth.pivot(index="year", columns="mclass", values="pv").round(1)
mr = meth.pivot(index="year", columns="mclass", values="pr").round(1)
print("보고 커버리지"); print(cov[cov.year.isin([2005, 2015, 2019, 2022, 2024])].to_string(index=False))
print("\\n금액 기준 방법론 비중"); print(mp.loc[[2005, 2015, 2019, 2024]])
print("\\n행 기준 방법론 비중"); print(mr.loc[[2005, 2015, 2019, 2024]])
""")

code("""
rep = con.execute(\"\"\"
SELECT f.reporter, a.name_sdmx,
  100.0*count(*) FILTER (WHERE f.reported_value IS NOT NULL)/count(*) pct_reported,
  sum(f.balanced_value) v
FROM fact_batis f
JOIN dim_area a ON f.reporter=a.code AND NOT a.is_aggregate
JOIN dim_area p ON f.partner=p.code AND NOT p.is_aggregate
WHERE f.item_code='S' AND f.flow='EXP' AND f.year=2019
GROUP BY 1,2 ORDER BY v DESC
\"\"\").df()
print("보고국 수:", len(rep),
      "| 하나라도 보고:", int((rep.pct_reported > 0).sum()),
      "| 절반 이상 보고:", int((rep.pct_reported >= 50).sum()))
rep.head(20).round(1).to_string(index=False)
""")

md("## §4. 보고치의 비대칭 (본문 V.4)")
code("""
asym = con.execute(\"\"\"
WITH x AS (SELECT reporter a, partner b, year y, reported_value v
           FROM fact_batis WHERE item_code='S' AND flow='EXP' AND reported_value IS NOT NULL),
     m AS (SELECT partner a, reporter b, year y, reported_value v
           FROM fact_batis WHERE item_code='S' AND flow='IMP' AND reported_value IS NOT NULL)
SELECT x.y AS year, x.a AS exporter, x.b AS importer, x.v AS exp_rep, m.v AS imp_rep,
       200.0*abs(x.v - m.v)/(x.v + m.v) AS pct_gap
FROM x JOIN m ON x.a=m.a AND x.b=m.b AND x.y=m.y
JOIN dim_area ae ON x.a=ae.code AND NOT ae.is_aggregate
JOIN dim_area ai ON x.b=ai.code AND NOT ai.is_aggregate
WHERE x.v > 0 AND m.v > 0
\"\"\").df()
a19 = asym[asym.year == 2019]
print("양쪽 보고 나라쌍(2019):", len(a19))
print("중위 %.1f%% | 사분위 %.1f~%.1f%%" % (a19.pct_gap.median(),
      a19.pct_gap.quantile(.25), a19.pct_gap.quantile(.75)))
print("25%% 초과 비율 %.1f%% | 50%% 초과 비율 %.1f%%" %
      (100 * (a19.pct_gap > 25).mean(), 100 * (a19.pct_gap > 50).mean()))
a19.sort_values("exp_rep", ascending=False).head(10).round(1).to_string(index=False)
""")

md("## §5. 한국 (본문 V.5)")
code(f"""
kor = con.execute(\"\"\"
SELECT year, flow, reported_value, balanced_value
FROM fact_batis WHERE reporter='KOR' AND partner='W' AND item_code='S' ORDER BY year, flow
\"\"\").df()
kg = con.execute(f\"\"\"
SELECT f.year, sum(f.value) goods FROM fact_bimts_hs2 f {{IND_M}}
WHERE f.exporter='KOR' AND f.product='_T' AND f.adjustment='B_ADJ_RX' GROUP BY 1
\"\"\").df()
ke = kor[kor.flow == 'EXP'].merge(kg, on='year')
ke["svc_share"] = (100 * ke.balanced_value / (ke.balanced_value + ke.goods)).round(1)
print(ke[ke.year.isin([2005, 2019, 2024])][["year", "balanced_value", "goods", "svc_share"]]
      .round(0).to_string(index=False))

rank = con.execute(\"\"\"
SELECT rk FROM (
  SELECT f.reporter, row_number() OVER (ORDER BY f.balanced_value DESC) rk
  FROM fact_batis f JOIN dim_area a ON f.reporter=a.code AND NOT a.is_aggregate
  WHERE f.item_code='S' AND f.flow='EXP' AND f.partner='W' AND f.year=2024)
WHERE reporter='KOR'
\"\"\").fetchone()[0]
print("2024년 서비스 수출 순위:", rank)
""")

code("""
kp = con.execute(\"\"\"
SELECT f.partner, a.name_sdmx, f.balanced_value v, f.methodology
FROM fact_batis f JOIN dim_area a ON f.partner=a.code AND NOT a.is_aggregate
WHERE f.reporter='KOR' AND f.year=2024 AND f.item_code='S' AND f.flow='EXP'
ORDER BY v DESC
\"\"\").df()
print("상위 10개국 비중: %.1f%%" % (100 * kp.head(10).v.sum() / kp.v.sum()))
kp.head(10).round(0).to_string(index=False)
""")

code("""
ki = con.execute(\"\"\"
SELECT f.item_code, d.description, f.balanced_value v
FROM fact_batis f JOIN dim_service d USING (item_code)
WHERE f.reporter='KOR' AND f.partner='W' AND f.year=2024 AND f.flow='EXP'
  AND f.item_code IN ('SA','SB','SC','SD','SE','SF','SG','SH','SI','SJ','SK','SL')
ORDER BY v DESC
\"\"\").df()
ki["share"] = (100 * ki.v / ki.v.sum()).round(1)
ki.round(0).to_string(index=False)
""")

md("""
## §6. 한국은행 공표치와의 대조 (본문 IV.3)

한국은행 지역별 경상수지(301Y015)에서 받은 값을 상수로 적었다. 조회일은 2026-09-16이고,
API 경로는 `StatisticSearch/{인증키}/json/kr/1/30/301Y015/A/2019/2024/{항목}/{지역}`이다.
항목은 서비스수입(REG2100)과 서비스지급(REG2200), 지역은 중국(CN)·미국(US)·일본(JP)·총계(SUM)다.
""")
code("""
BOK = {  # (방향, 연도) -> 백만 달러
    ("EXP", 2019): 103839, ("EXP", 2020): 91232, ("EXP", 2021): 120174,
    ("EXP", 2022): 132682, ("EXP", 2023): 127042, ("EXP", 2024): 142034,
    ("IMP", 2019): 130684, ("IMP", 2020): 105350, ("IMP", 2021): 129168,
    ("IMP", 2022): 143432, ("IMP", 2023): 157784, ("IMP", 2024): 171462,
}
BOK_PARTNER_2019 = {("EXP", "CHN"): 20338, ("EXP", "USA"): 17974, ("EXP", "JPN"): 9364,
                    ("IMP", "USA"): 31312, ("IMP", "CHN"): 17127, ("IMP", "JPN"): 10198}

k = con.execute(\"\"\"
SELECT year, flow, reported_value FROM fact_batis
WHERE reporter='KOR' AND partner='W' AND item_code='S' AND year BETWEEN 2019 AND 2024
\"\"\").df()
k["bok"] = k.apply(lambda r: BOK[(r.flow, int(r.year))], axis=1)
k["diff_pct"] = (100 * (k.reported_value - k.bok) / k.bok).round(2)
print(k.sort_values(["year", "flow"]).to_string(index=False))

kp19 = con.execute(\"\"\"
SELECT flow, partner, reported_value FROM fact_batis
WHERE reporter='KOR' AND item_code='S' AND year=2019 AND reported_value IS NOT NULL
  AND partner <> 'W'
\"\"\").df()
kp19["bok"] = kp19.apply(lambda r: BOK_PARTNER_2019[(r.flow, r.partner)], axis=1)
print("\\n2019년 상대국별 (BaTIS 보고치 대 한국은행)")
print(kp19.to_string(index=False))
""")

md("""
## §7. 본문 수치 검증

본문이 인용한 값과 여기서 계산한 값을 대조한다. 어긋나면 AssertionError로 멈춘다.
본문을 고치면 이 절도 함께 고친다.
""")
code("""
def chk(name, got, want, tol=0.05):
    ok = abs(got - want) <= tol
    print(("OK  " if ok else "FAIL") + f" {name}: 계산 {got} / 본문 {want}")
    assert ok, f"{name}: 계산 {got} != 본문 {want}"

w24 = world[world.year == 2024].iloc[0]
w05 = world[world.year == 2005].iloc[0]
chk("2024 세계 서비스 수출(백만 달러)", round(w24.svc), 8475072, tol=1)
chk("2005 세계 서비스 수출", round(w05.svc), 2673872, tol=1)
chk("2024 세계 상품 수출", round(w24.goods), 23583364, tol=1)
chk("2024 서비스 비중(%)", round(w24.svc_share, 1), 26.4)
chk("2005 서비스 비중(%)", round(w05.svc_share, 1), 20.5)
chk("2009 서비스 비중(%)", round(world[world.year == 2009].iloc[0].svc_share, 1), 22.8)
chk("2020 서비스 비중(%)", round(world[world.year == 2020].iloc[0].svc_share, 1), 23.2)

chk("2024 기타 사업서비스 비중(%)", piv.loc[2024, "SJ"], 24.3)
chk("2005 기타 사업서비스 비중(%)", piv.loc[2005, "SJ"], 19.3)
chk("2024 여행 비중(%)", piv.loc[2024, "SD"], 20.2)
chk("2020 여행 비중(%)", piv.loc[2020, "SD"], 10.8)
chk("2024 운송 비중(%)", piv.loc[2024, "SC"], 18.4)
chk("2005 통신·컴퓨터·정보 비중(%)", piv.loc[2005, "SI"], 5.6)
chk("2024 통신·컴퓨터·정보 비중(%)", piv.loc[2024, "SI"], 10.8)
chk("2020 디지털 전달 가능 비중(%)", float(dd[dd.year == 2020].share.iloc[0]), 63.4)
chk("2024 디지털 전달 가능 비중(%)", float(dd[dd.year == 2024].share.iloc[0]), 54.6)

chk("2019 보고 커버리지 행(%)", float(cov[cov.year == 2019].pct_rows.iloc[0]), 16.7)
chk("2019 보고 커버리지 금액(%)", float(cov[cov.year == 2019].pct_val.iloc[0]), 32.5)
chk("2024 보고 커버리지 행(%)", float(cov[cov.year == 2024].pct_rows.iloc[0]), 5.1)
chk("2019 모형 추정 금액 비중(%)", mp.loc[2019, "model"], 22.4)
chk("2019 모형 추정 행 비중(%)", mr.loc[2019, "model"], 79.2)
chk("2019 보고 금액 비중(%)", mp.loc[2019, "reported"], 49.8)

chk("2019 보고국 수", len(rep), 200, tol=0)
chk("2019 하나라도 보고한 보고국", int((rep.pct_reported > 0).sum()), 52, tol=0)
chk("2019 절반 이상 보고한 보고국", int((rep.pct_reported >= 50).sum()), 32, tol=0)
chk("한국 보고율(%)", float(rep[rep.reporter == "KOR"].pct_reported.iloc[0]), 1.5)

chk("2019 양쪽 보고 나라쌍 수", len(a19), 1719, tol=0)
chk("비대칭 중위(%)", round(float(a19.pct_gap.median()), 1), 40.4)
chk("비대칭 25% 초과 비율(%)", round(100 * float((a19.pct_gap > 25).mean()), 1), 67.3)
chk("비대칭 50% 초과 비율(%)", round(100 * float((a19.pct_gap > 50).mean()), 1), 42.5)

chk("2024 한국 서비스 수출", round(float(ke[ke.year == 2024].balanced_value.iloc[0])), 118185, tol=1)
chk("2024 한국 상품 수출", round(float(ke[ke.year == 2024].goods.iloc[0])), 719146, tol=1)
chk("2024 한국 서비스 비중(%)", float(ke[ke.year == 2024].svc_share.iloc[0]), 14.1)
chk("2005 한국 서비스 비중(%)", float(ke[ke.year == 2005].svc_share.iloc[0]), 12.3)
chk("2024 한국 서비스 수출 순위", rank, 19, tol=0)
chk("2024 한국 상위 10개국 비중(%)", round(100 * kp.head(10).v.sum() / kp.v.sum(), 1), 67.2)
chk("2024 한국 운송 비중(%)", float(ki[ki.item_code == "SC"].share.iloc[0]), 33.7)
chk("2024 한국 기타 사업서비스 비중(%)", float(ki[ki.item_code == "SJ"].share.iloc[0]), 20.8)

chk("2019 한국 수출 보고치 대 한국은행 차이(%)",
    float(k[(k.year == 2019) & (k.flow == "EXP")].diff_pct.iloc[0]), 0.0, tol=0.005)
chk("2024 한국 수입 보고치 대 한국은행 차이(%)",
    float(k[(k.year == 2024) & (k.flow == "IMP")].diff_pct.iloc[0]), -5.14, tol=0.01)
print("\\n모든 검증 통과")
""")

md("""
## §8. 서비스와 상품의 나라쌍 관계 (본문 V.6)

두 자료의 결측 규약이 다르므로 상품 교역이 관측된 쌍만 남는다는 점에 주의한다.
""")
code("""
import numpy as np
pair = con.execute(f\"\"\"
WITH s AS (SELECT f.reporter a, f.partner b, f.balanced_value v FROM fact_batis f {IND_B}
           WHERE f.item_code='S' AND f.flow='EXP' AND f.year=2024 AND f.balanced_value > 0),
     g AS (SELECT f.exporter a, f.importer b, f.value v FROM fact_bimts_hs2 f {IND_M}
           WHERE f.product='_T' AND f.adjustment='B_ADJ_RX' AND f.year=2024 AND f.value > 0)
SELECT s.a, s.b, s.v AS svc, g.v AS goods FROM s JOIN g ON s.a=g.a AND s.b=g.b
\"\"\").df()
rho = np.corrcoef(np.log(pair.svc), np.log(pair.goods))[0, 1]
print("나라쌍 수: %d | log 상관 %.3f" % (len(pair), rho))
assert len(pair) == 28765 and abs(round(rho, 3) - 0.793) < 0.001
print("검증 통과")
""")

nb = nbf.v4.new_notebook(cells=cells)
nb.metadata["kernelspec"] = {"display_name": "Python (kcsdb)", "language": "python", "name": "kcsdb"}
nb.metadata["language_info"] = {"name": "python"}
NB.write_text(nbf.writes(nb), encoding="utf-8")
print("작성:", NB)

"""연구 1의 수치와 그림을 만든다.

본문이 인용하는 수치는 전부 여기서 나온다. 결과는 out/stats.json에 쌓고
그림은 img/에 떨군다. 재현 노트북(overview.ipynb)은 같은 질의를 다시 돌려
본문 수치와 대조한다.

  python research/1.서비스교역_자료와_기술적_개관/analysis.py
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DB = ROOT / "data" / "processed" / "svcdb.duckdb"
IMG = HERE / "img"
OUT = HERE / "out"
IMG.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)

# 그림 표준: 흑백, 300dpi, 위·오른쪽 축선 제거, 격자 0.87, Malgun Gothic
plt.rcParams.update({
    "font.family": "Malgun Gothic", "axes.unicode_minus": False,
    "figure.dpi": 110, "savefig.dpi": 300, "savefig.bbox": "tight",
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": "0.87", "grid.linewidth": 0.8,
    "font.size": 10, "axes.titlesize": 11, "legend.frameon": False,
})

def year_axis(ax, step: int = 5) -> None:
    """연도 축은 정수로 찍는다 — 기본값이면 2007.5 같은 눈금이 생긴다."""
    ax.xaxis.set_major_locator(MultipleLocator(step))
    ax.xaxis.set_major_formatter(lambda v, pos: f"{int(v)}")


con = duckdb.connect(str(DB), read_only=True)
S: dict = {}


def q(sql: str):
    return con.execute(sql).df()


# 개별 경제만 남기는 조인 조각 — 집계 코드를 섞으면 두 배가 된다
IND_B = ("JOIN dim_area ar ON f.reporter=ar.code AND NOT ar.is_aggregate "
         "JOIN dim_area ap ON f.partner=ap.code AND NOT ap.is_aggregate")
IND_M = ("JOIN dim_area ae ON f.exporter=ae.code AND NOT ae.is_aggregate "
         "JOIN dim_area ai ON f.importer=ai.code AND NOT ai.is_aggregate")

# ---------------------------------------------------------------- 1. 세계 규모
world = q(f"""
WITH s AS (SELECT year, sum(balanced_value) v FROM fact_batis
           WHERE item_code='S' AND flow='EXP' AND reporter='W' AND partner='W' GROUP BY 1),
     g AS (SELECT year, sum(value) v FROM fact_bimts_hs2 f {IND_M}
           WHERE product='_T' AND adjustment='B' GROUP BY 1),
     gx AS (SELECT year, sum(value) v FROM fact_bimts_hs2 f {IND_M}
            WHERE product='_T' AND adjustment='B_ADJ_RX' GROUP BY 1)
SELECT g.year, s.v AS svc, g.v AS goods, gx.v AS goods_rx,
       100.0*s.v/(s.v+g.v) AS svc_share
FROM g LEFT JOIN s USING (year) LEFT JOIN gx USING (year) ORDER BY 1
""")
world.to_csv(OUT / "world.csv", index=False, encoding="utf-8-sig")
w = world.set_index("year")
S["world"] = {int(y): {"svc": None if r.svc != r.svc else round(r.svc),
                       "goods": round(r.goods), "goods_rx": round(r.goods_rx),
                       "share": None if r.svc_share != r.svc_share else round(r.svc_share, 1)}
              for y, r in w.iterrows()}

fig, ax = plt.subplots(figsize=(7.2, 4.0))
sub = world.dropna(subset=["svc"])
ax.plot(sub.year, sub.goods / 1e6, color="black", lw=1.6, label="상품 수출")
ax.plot(sub.year, sub.svc / 1e6, color="black", lw=1.6, ls="--", label="서비스 수출")
ax.set_ylabel("조 달러")
ax.set_xlabel("")
ax2 = ax.twinx()
ax2.plot(sub.year, sub.svc_share, color="0.45", lw=1.2, marker="o", ms=3.5,
         mfc="white", mec="0.45", label="서비스 비중(우축)")
ax2.set_ylabel("서비스 비중 (%)")
ax2.set_ylim(15, 30)
ax2.grid(False)
ax2.spines["top"].set_visible(False)
h1, l1 = ax.get_legend_handles_labels()
h2, l2 = ax2.get_legend_handles_labels()
ax.legend(h1 + h2, l1 + l2, loc="upper left")
ax.set_title("세계 수출: 상품과 서비스 (균형치, 개별 경제쌍 합)")
year_axis(ax)
fig.savefig(IMG / "fig1_world.png")
plt.close(fig)

# ---------------------------------------------------------------- 2. 항목 구성
items = q("""
SELECT f.year, f.item_code, d.description, sum(f.balanced_value) v
FROM fact_batis f JOIN dim_service d USING (item_code)
WHERE f.flow='EXP' AND f.reporter='W' AND f.partner='W'
  AND f.item_code IN ('SA','SB','SC','SD','SE','SF','SG','SH','SI','SJ','SK','SL')
GROUP BY 1,2,3 ORDER BY 1,4 DESC
""")
tot = items.groupby("year").v.sum()
items["share"] = items.apply(lambda r: 100 * r.v / tot[r.year], axis=1)
items.to_csv(OUT / "items.csv", index=False, encoding="utf-8-sig")
piv = items.pivot(index="year", columns="item_code", values="share")
S["items"] = {
    c: {"2005": round(piv.loc[2005, c], 1), "2019": round(piv.loc[2019, c], 1),
        "2020": round(piv.loc[2020, c], 1), "2024": round(piv.loc[2024, c], 1)}
    for c in piv.columns}
S["items_level_2024"] = {r.item_code: round(r.v) for r in
                         items[items.year == 2024].itertuples()}

NAMES = {"SJ": "기타 사업서비스", "SD": "여행", "SC": "운송",
         "SI": "통신·컴퓨터·정보", "SG": "금융", "SH": "지식재산권 사용료"}
fig, ax = plt.subplots(figsize=(7.2, 4.0))
styles = [("-", "black"), ("--", "black"), (":", "black"),
          ("-", "0.45"), ("--", "0.45"), (":", "0.45")]
for (code, label), (ls, c) in zip(NAMES.items(), styles):
    ax.plot(piv.index, piv[code], ls=ls, color=c, lw=1.5, label=label)
ax.set_ylabel("총서비스 대비 비중 (%)")
ax.set_title("세계 서비스 수출의 항목 구성 (균형치)")
ax.legend(ncol=2, loc="upper center")
ax.set_ylim(0, 30)
year_axis(ax)
fig.savefig(IMG / "fig2_items.png")
plt.close(fig)

# 디지털 전달 가능 서비스 대리지표 (SF+SG+SH+SI+SJ+SK)
ddx = q("""
SELECT year,
  sum(balanced_value) FILTER (WHERE item_code IN ('SF','SG','SH','SI','SJ','SK')) dd,
  sum(balanced_value) FILTER (WHERE item_code='S') tot
FROM fact_batis WHERE flow='EXP' AND reporter='W' AND partner='W' GROUP BY 1 ORDER BY 1
""")
ddx["share"] = 100 * ddx.dd / ddx.tot
S["digital_proxy"] = {int(r.year): round(r.share, 1) for r in ddx.itertuples()}
ddx.to_csv(OUT / "digital_proxy.csv", index=False, encoding="utf-8-sig")

# ---------------------------------------------------------------- 3. 보고와 추정
cov = q("""
SELECT year,
  100.0*count(*) FILTER (WHERE reported_value IS NOT NULL)/count(*) pct_rows,
  100.0*sum(abs(reported_value)) FILTER (WHERE reported_value IS NOT NULL)
        /sum(abs(balanced_value)) pct_val
FROM fact_batis WHERE item_code='S' GROUP BY 1 ORDER BY 1
""")
cov.to_csv(OUT / "coverage.csv", index=False, encoding="utf-8-sig")
S["coverage"] = {int(r.year): {"rows": round(r.pct_rows, 1), "value": round(r.pct_val, 1)}
                 for r in cov.itertuples()}

meth = q(f"""
SELECT f.year, m.mclass,
  100.0*count(*)/sum(count(*)) OVER (PARTITION BY f.year) pr,
  100.0*sum(abs(f.balanced_value))/sum(sum(abs(f.balanced_value))) OVER (PARTITION BY f.year) pv
FROM fact_batis f JOIN dim_methodology m ON f.methodology=m.code {IND_B}
WHERE f.item_code='S' GROUP BY 1,2 ORDER BY 1,2
""")
meth.to_csv(OUT / "methodology.csv", index=False, encoding="utf-8-sig")
mp = meth.pivot(index="year", columns="mclass", values="pv")
mr = meth.pivot(index="year", columns="mclass", values="pr")
S["methodology"] = {int(y): {c: round(mp.loc[y, c], 1) for c in mp.columns}
                    for y in (2005, 2015, 2019, 2024)}
S["methodology_rows"] = {int(y): {c: round(mr.loc[y, c], 1) for c in mr.columns}
                         for y in (2005, 2015, 2019, 2024)}

fig, ax = plt.subplots(figsize=(7.2, 4.0))
ax.plot(cov.year, cov.pct_val, color="black", lw=1.6, label="보고 커버리지(금액)")
ax.plot(cov.year, cov.pct_rows, color="black", lw=1.4, ls="--", label="보고 커버리지(행)")
ax.plot(mp.index, mp["model"], color="0.45", lw=1.5, ls=":", label="모형 추정 비중(금액)")
ax.set_ylabel("%")
ax.set_ylim(0, 60)
ax.set_title("총서비스의 보고 커버리지와 추정 비중")
ax.legend(loc="upper left")
year_axis(ax)
fig.savefig(IMG / "fig3_coverage.png")
plt.close(fig)

# 보고국별 양자 보고 여부 (2019년, 총서비스, 수출)
rep_by_country = q("""
SELECT f.reporter, a.name_sdmx,
  count(*) n_cells,
  100.0*count(*) FILTER (WHERE f.reported_value IS NOT NULL)/count(*) pct_reported,
  sum(f.balanced_value) v
FROM fact_batis f
JOIN dim_area a ON f.reporter=a.code AND NOT a.is_aggregate
JOIN dim_area p ON f.partner=p.code AND NOT p.is_aggregate
WHERE f.item_code='S' AND f.flow='EXP' AND f.year=2019
GROUP BY 1,2 ORDER BY v DESC
""")
rep_by_country.to_csv(OUT / "reporters_2019.csv", index=False, encoding="utf-8-sig")
top20 = rep_by_country.head(20)
S["reporters_top20_2019"] = [
    {"code": r.reporter, "name": r.name_sdmx, "pct_reported": round(r.pct_reported, 1),
     "v": round(r.v)} for r in top20.itertuples()]
S["reporters_any_2019"] = {
    "n_reporters": int(len(rep_by_country)),
    "n_with_any": int((rep_by_country.pct_reported > 0).sum()),
    "n_over_half": int((rep_by_country.pct_reported >= 50).sum()),
}

# ---------------------------------------------------------------- 4. 비대칭
asym = q("""
WITH x AS (SELECT reporter a, partner b, year y, reported_value v
           FROM fact_batis WHERE item_code='S' AND flow='EXP' AND reported_value IS NOT NULL),
     m AS (SELECT partner a, reporter b, year y, reported_value v
           FROM fact_batis WHERE item_code='S' AND flow='IMP' AND reported_value IS NOT NULL)
SELECT x.y AS year, x.a AS exporter, x.b AS importer,
       x.v AS exp_reported, m.v AS imp_reported,
       (x.v - m.v) AS gap,
       CASE WHEN (x.v + m.v) > 0 THEN 200.0*abs(x.v - m.v)/(x.v + m.v) END AS pct_gap
FROM x JOIN m ON x.a=m.a AND x.b=m.b AND x.y=m.y
JOIN dim_area ae ON x.a=ae.code AND NOT ae.is_aggregate
JOIN dim_area ai ON x.b=ai.code AND NOT ai.is_aggregate
WHERE x.v > 0 AND m.v > 0
""")
asym.to_csv(OUT / "asymmetry.csv", index=False, encoding="utf-8-sig")
a2019 = asym[asym.year == 2019]
S["asymmetry"] = {
    "n_pairs_all_years": int(len(asym)),
    "n_pairs_2019": int(len(a2019)),
    "median_pct_2019": round(float(a2019.pct_gap.median()), 1),
    "q25_2019": round(float(a2019.pct_gap.quantile(.25)), 1),
    "q75_2019": round(float(a2019.pct_gap.quantile(.75)), 1),
    "over_25pct_2019": round(100 * float((a2019.pct_gap > 25).mean()), 1),
    "over_50pct_2019": round(100 * float((a2019.pct_gap > 50).mean()), 1),
}
# 전체 보고 나라쌍 대비 양쪽이 모두 보고한 비율
both_share = q("""
WITH cells AS (SELECT reporter, partner, year FROM fact_batis f
               JOIN dim_area ar ON f.reporter=ar.code AND NOT ar.is_aggregate
               JOIN dim_area ap ON f.partner=ap.code AND NOT ap.is_aggregate
               WHERE item_code='S' AND flow='EXP' AND year=2019)
SELECT count(*) FROM cells
""")
S["asymmetry"]["n_directed_cells_2019"] = int(both_share.iloc[0, 0])

fig, ax = plt.subplots(figsize=(7.2, 4.0))
ax.hist(a2019.pct_gap.clip(upper=200), bins=40, color="0.82", edgecolor="black", lw=.7)
ax.axvline(a2019.pct_gap.median(), color="black", ls="--", lw=1.2)
ax.set_xlabel("수출 보고와 상대국 수입 보고의 차이 (%, 두 값 평균 대비)")
ax.set_ylabel("나라쌍 수")
ax.set_title("양쪽이 모두 보고한 나라쌍의 비대칭 (2019년, 총서비스)")
ax.annotate(f"중위 {a2019.pct_gap.median():.0f}%",
            xy=(a2019.pct_gap.median(), ax.get_ylim()[1] * .82),
            xytext=(a2019.pct_gap.median() + 22, ax.get_ylim()[1] * .82),
            arrowprops=dict(arrowstyle="->", color="black", lw=.9))
fig.savefig(IMG / "fig4_asymmetry.png")
plt.close(fig)

# ---------------------------------------------------------------- 5. 한국
kor_tot = q("""
SELECT year, flow, reported_value, final_value, balanced_value, methodology
FROM fact_batis WHERE reporter='KOR' AND partner='W' AND item_code='S' ORDER BY year, flow
""")
kor_tot.to_csv(OUT / "korea_total.csv", index=False, encoding="utf-8-sig")
S["korea_total"] = {int(r.year): {r.flow: {"rep": None if r.reported_value != r.reported_value
                                           else round(r.reported_value),
                                           "bal": round(r.balanced_value)}}
                    for r in kor_tot.itertuples() if r.year in (2005, 2019, 2023, 2024)}
kt = kor_tot.pivot(index="year", columns="flow")
S["korea_series"] = {
    int(y): {"exp_bal": round(kt[("balanced_value", "EXP")][y]),
             "imp_bal": round(kt[("balanced_value", "IMP")][y]),
             "exp_rep": None if kt[("reported_value", "EXP")][y] != kt[("reported_value", "EXP")][y]
                        else round(kt[("reported_value", "EXP")][y])}
    for y in kt.index}

kor_partners = q("""
SELECT f.partner, a.name_sdmx, f.flow, f.balanced_value v, f.methodology
FROM fact_batis f JOIN dim_area a ON f.partner=a.code AND NOT a.is_aggregate
WHERE f.reporter='KOR' AND f.year=2024 AND f.item_code='S'
ORDER BY f.flow, v DESC
""")
kor_partners.to_csv(OUT / "korea_partners_2024.csv", index=False, encoding="utf-8-sig")
kexp = kor_partners[kor_partners.flow == "EXP"]
S["korea_partners_2024"] = [
    {"code": r.partner, "name": r.name_sdmx, "v": round(r.v), "method": r.methodology}
    for r in kexp.head(10).itertuples()]
S["korea_top10_share_2024"] = round(100 * kexp.head(10).v.sum() / kexp.v.sum(), 1)

kor_items = q("""
SELECT f.item_code, d.description, f.flow, f.balanced_value v
FROM fact_batis f JOIN dim_service d USING (item_code)
WHERE f.reporter='KOR' AND f.partner='W' AND f.year=2024
  AND f.item_code IN ('SA','SB','SC','SD','SE','SF','SG','SH','SI','SJ','SK','SL')
ORDER BY f.flow, v DESC
""")
kor_items.to_csv(OUT / "korea_items_2024.csv", index=False, encoding="utf-8-sig")
ke = kor_items[kor_items.flow == "EXP"]
tot_ke = ke.v.sum()
S["korea_items_2024"] = [{"code": r.item_code, "name": r.description,
                          "v": round(r.v), "share": round(100 * r.v / tot_ke, 1)}
                         for r in ke.itertuples()]

# 한국 상품 수출 (BIMTS) — 서비스와 나란히
kor_goods = q(f"""
SELECT f.year, sum(f.value) v FROM fact_bimts_hs2 f {IND_M}
WHERE f.exporter='KOR' AND f.product='_T' AND f.adjustment='B_ADJ_RX' GROUP BY 1 ORDER BY 1
""")
kor_goods.to_csv(OUT / "korea_goods.csv", index=False, encoding="utf-8-sig")
kg = kor_goods.set_index("year").v
ks = {y: S["korea_series"][y]["exp_bal"] for y in S["korea_series"]}
S["korea_svc_share"] = {y: round(100 * ks[y] / (ks[y] + kg[y]), 1)
                        for y in sorted(ks) if y in kg.index}

fig, ax = plt.subplots(figsize=(7.2, 4.0))
yrs = sorted(ks)
ax.plot(yrs, [ks[y] / 1000 for y in yrs], color="black", lw=1.6, label="서비스 수출")
ax.plot(yrs, [S["korea_series"][y]["imp_bal"] / 1000 for y in yrs], color="black",
        lw=1.4, ls="--", label="서비스 수입")
ax.plot(yrs, [kg[y] / 1000 for y in yrs if y in kg.index], color="0.45", lw=1.5, ls=":",
        label="상품 수출(재수출 조정)")
ax.set_ylabel("십억 달러")
ax.set_title("한국의 서비스와 상품 교역 (균형치)")
ax.legend(loc="upper left")
year_axis(ax)
fig.savefig(IMG / "fig5_korea.png")
plt.close(fig)

# ---------------------------------------------------------------- 6. 집중도
conc = q("""
WITH t AS (SELECT f.reporter, f.balanced_value v FROM fact_batis f
           JOIN dim_area a ON f.reporter=a.code AND NOT a.is_aggregate
           WHERE f.item_code='S' AND f.flow='EXP' AND f.partner='W' AND f.year=2024)
SELECT count(*) n, sum(v) tot,
       sum(v) FILTER (WHERE rk <= 10) top10, sum(v) FILTER (WHERE rk <= 30) top30
FROM (SELECT *, row_number() OVER (ORDER BY v DESC) rk FROM t)
""")
S["concentration_2024"] = {
    "n_economies": int(conc.n[0]),
    "top10_share": round(100 * conc.top10[0] / conc.tot[0], 1),
    "top30_share": round(100 * conc.top30[0] / conc.tot[0], 1),
}
top_exporters = q("""
SELECT f.reporter, a.name_sdmx, f.balanced_value v FROM fact_batis f
JOIN dim_area a ON f.reporter=a.code AND NOT a.is_aggregate
WHERE f.item_code='S' AND f.flow='EXP' AND f.partner='W' AND f.year=2024
ORDER BY v DESC LIMIT 15
""")
top_exporters.to_csv(OUT / "top_exporters_2024.csv", index=False, encoding="utf-8-sig")
S["top_exporters_2024"] = [{"code": r.reporter, "name": r.name_sdmx, "v": round(r.v)}
                           for r in top_exporters.itertuples()]
S["korea_rank_2024"] = int(q("""
SELECT rk FROM (
  SELECT f.reporter, row_number() OVER (ORDER BY f.balanced_value DESC) rk
  FROM fact_batis f JOIN dim_area a ON f.reporter=a.code AND NOT a.is_aggregate
  WHERE f.item_code='S' AND f.flow='EXP' AND f.partner='W' AND f.year=2024)
WHERE reporter='KOR'
""").iloc[0, 0])

# ---------------------------------------------------------------- 7. 서비스와 상품의 관계
pair = q(f"""
WITH s AS (SELECT f.reporter a, f.partner b, f.balanced_value v FROM fact_batis f {IND_B}
           WHERE f.item_code='S' AND f.flow='EXP' AND f.year=2024 AND f.balanced_value > 0),
     g AS (SELECT f.exporter a, f.importer b, f.value v FROM fact_bimts_hs2 f {IND_M}
           WHERE f.product='_T' AND f.adjustment='B_ADJ_RX' AND f.year=2024 AND f.value > 0)
SELECT s.a, s.b, s.v AS svc, g.v AS goods FROM s JOIN g ON s.a=g.a AND s.b=g.b
""")
pair.to_csv(OUT / "pairs_2024.csv", index=False, encoding="utf-8-sig")
import numpy as np
S["pairs_2024"] = {
    "n": int(len(pair)),
    "corr_log": round(float(np.corrcoef(np.log(pair.svc), np.log(pair.goods))[0, 1]), 3),
    "median_ratio": round(float((pair.svc / pair.goods).median()), 3),
}

(OUT / "stats.json").write_text(json.dumps(S, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(S, ensure_ascii=False, indent=2)[:4000])
print("\n그림:", sorted(p.name for p in IMG.glob("*.png")))
con.close()

"""연구 2 — 지경학적 분절화는 서비스 교역에서도 일어나는가.

본문이 인용하는 수치와 그림을 전부 여기서 만든다. 결과는 out/stats.json, 그림은 img/.
블록은 먼저 blocs.py로 만든다.

설계의 뼈대
  - 핵심 지표: 두 블록(미국 쪽 US, 중국 쪽 CN)에 속한 경제 사이의 교역 가운데 블록을
    넘는 흐름의 비중 S. 금액 수준이 아니라 비중이므로 환율·가격 효과가 크게 줄어든다.
  - 같은 국가쌍: 서비스와 상품을 같은 방향쌍 집합에서 측정한다. 집합은 사전(2015~2017)과
    사후(2022~2023) 모든 연도에 어느 한쪽이라도 총서비스를 보고한 방향쌍으로 고정한다.
    보고 범위가 해마다 바뀌어 생기는 구성 변화를 막기 위해서다.
  - 기간 통계는 연도 평균이 아니라 기간 합산 비율(기간 동안의 블록 간 합 / 전체 합)이다.
  - 중력모형은 쓰지 않는다. 블록 크기 변화는 집약도 I = S / E로 따로 본다.

  python research/2.지경학적_분절화와_서비스교역/blocs.py
  python research/2.지경학적_분절화와_서비스교역/analysis.py
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import igraph as ig
import leidenalg
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DB = ROOT / "data" / "processed" / "svcdb.duckdb"
BACI = Path(r"C:/Work/Projects/UNComtraade/data/processed/baci_net.duckdb")
IMG, OUT = HERE / "img", HERE / "out"
IMG.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)

plt.rcParams.update({
    "font.family": "Malgun Gothic", "axes.unicode_minus": False,
    "figure.dpi": 110, "savefig.dpi": 300, "savefig.bbox": "tight",
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": "0.87", "grid.linewidth": 0.8,
    "font.size": 10, "axes.titlesize": 11, "legend.frameon": False,
})

CATS = ["SA", "SB", "SC", "SD", "SE", "SF", "SG", "SH", "SI", "SJ", "SK", "SL"]
GROUP = {"SC": "운송", "SD": "여행", "SI": "ICT",
         "SF": "기타 디지털", "SG": "기타 디지털", "SH": "기타 디지털", "SJ": "기타 디지털", "SK": "기타 디지털",
         "SA": "기타", "SB": "기타", "SE": "기타", "SL": "기타"}
DEFS = ["D1", "D2", "D3", "D4"]
PANEL_YEARS = (2015, 2016, 2017, 2022, 2023)
PER = {"early": [2012, 2013, 2014], "pre": [2015, 2016, 2017], "war": [2018, 2019],
       "covid": [2020, 2021], "post": [2022, 2023, 2024], "post23": [2022, 2023]}
S: dict = {}
blocs = pd.read_csv(OUT / "blocs.csv")


def r(x, n=2):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), n)


def year_axis(ax, step=2):
    ax.xaxis.set_major_locator(MultipleLocator(step))
    ax.xaxis.set_major_formatter(lambda v, pos: f"{int(v)}")


# ============================================================ 1. 자료와 패널
con = duckdb.connect()
con.execute(f"ATTACH '{DB.as_posix()}' AS s (READ_ONLY)")
cat_list = ",".join(f"'{c}'" for c in ["S"] + CATS)
con.execute(f"""
CREATE TEMP TABLE svc AS
WITH e AS (SELECT year, item_code k, reporter i, partner j, balanced_value bal, reported_value rep_x,
                  methodology meth
           FROM s.fact_batis WHERE flow='EXP' AND item_code IN ({cat_list})),
     m AS (SELECT year, item_code k, partner i, reporter j, reported_value rep_m
           FROM s.fact_batis WHERE flow='IMP' AND item_code IN ({cat_list}))
SELECT e.year, e.k, e.i, e.j, e.bal, e.rep_x, m.rep_m, e.meth
FROM e LEFT JOIN m USING (year, k, i, j)
JOIN s.dim_area ai ON e.i=ai.code AND NOT ai.is_aggregate
JOIN s.dim_area aj ON e.j=aj.code AND NOT aj.is_aggregate
""")

panel = con.execute(f"""
SELECT i, j, sum((rep_x IS NOT NULL)::INT) nx, sum((rep_m IS NOT NULL)::INT) nm
FROM svc WHERE k='S' AND year IN {PANEL_YEARS} GROUP BY 1,2
HAVING sum((rep_x IS NOT NULL OR rep_m IS NOT NULL)::INT) = {len(PANEL_YEARS)}
""").df()
n = len(PANEL_YEARS)
# 보고치의 출처를 쌍마다 고정한다 — 러시아처럼 한쪽 보고가 끊기면 출처가 바뀌어 비대칭이 섞이기 때문
panel["src"] = np.where(panel.nx == n, "x", np.where(panel.nm == n, "m", "mixed"))
con.register("panel", panel)

sv = con.execute("""
SELECT s.year, s.k, s.i, s.j, s.bal,
  CASE p.src WHEN 'x' THEN s.rep_x WHEN 'm' THEN s.rep_m END rep, p.src
FROM svc s JOIN panel p USING (i, j) WHERE s.year >= 2012
""").df()
gd = con.execute("""
SELECT g.year, g.exporter i, g.importer j, g.adjustment adj, g.value bal FROM s.fact_bimts_hs2 g
JOIN panel p ON g.exporter=p.i AND g.importer=p.j
WHERE g.product='_T' AND g.year >= 2012
""").df()

# 독립 조정 자료 BACI(CEPII) — 같은 방향쌍. 천 달러를 백만 달러로
con.execute(f"ATTACH '{BACI.as_posix()}' AS b (READ_ONLY)")
baci = con.execute("""
SELECT e.t AS year, ci.iso3 i, cj.iso3 j, e.v/1000.0 bal
FROM b.edge_total e
JOIN b.dim_country ci ON e.i=ci.country_code
JOIN b.dim_country cj ON e.j=cj.country_code
JOIN panel p ON ci.iso3=p.i AND cj.iso3=p.j
WHERE e.t >= 2012
""").df()

svS = sv[sv.k == "S"]
series = {
    "svc_bal": (svS, "bal"),
    "svc_rep": (svS[svS.src != "mixed"].dropna(subset=["rep"]), "rep"),
    "goods_rx": (gd[gd.adj == "B_ADJ_RX"], "bal"),
    "goods_b": (gd[gd.adj == "B"], "bal"),
    "goods_baci": (baci, "bal"),
}

S["panel"] = {
    "n_pairs": int(len(panel)),
    "src_x": int((panel.src == "x").sum()), "src_m": int((panel.src == "m").sum()),
    "src_mixed": int((panel.src == "mixed").sum()),
    "n_economies": int(len(set(panel.i) | set(panel.j))),
    "usa_chn_in": bool(((panel.i == "USA") & (panel.j == "CHN")).any() and ((panel.i == "CHN") & (panel.j == "USA")).any()),
}
tot_all = con.execute("""
SELECT year, sum(bal) FROM svc WHERE k='S' AND year IN (2019, 2023) GROUP BY 1 ORDER BY 1
""").fetchall()
for y, v in tot_all:
    S["panel"][f"svc_cover_{y}"] = r(100 * svS[svS.year == y].bal.sum() / v, 1)
g_all = con.execute("""
SELECT f.year, sum(f.value) FROM s.fact_bimts_hs2 f
JOIN s.dim_area ae ON f.exporter=ae.code AND NOT ae.is_aggregate
JOIN s.dim_area ai ON f.importer=ai.code AND NOT ai.is_aggregate
WHERE f.product='_T' AND f.adjustment='B_ADJ_RX' AND f.year IN (2019, 2023) GROUP BY 1 ORDER BY 1
""").fetchall()
grx = series["goods_rx"][0]
for y, v in g_all:
    S["panel"][f"goods_cover_{y}"] = r(100 * grx[grx.year == y].bal.sum() / v, 1)

# 블록 구성
S["blocs"] = {d: {k: int(v) for k, v in blocs[d].value_counts().items()} for d in DEFS}
both = blocs.dropna(subset=["D1", "D2"])
S["blocs"]["d1_d2_switch"] = int((both.D1 != both.D2).sum())
S["blocs"]["d1_d2_n"] = int(len(both))


# ============================================================ 2. 지표
def tag(df, dname, drop=()):
    b = blocs.set_index("code")[dname]
    d = df[~df.i.isin(drop) & ~df.j.isin(drop)].copy()
    d["bi"], d["bj"] = d.i.map(b), d.j.map(b)
    return d[d.bi.isin(["US", "CN"]) & d.bj.isin(["US", "CN"])]


def annual(df, val, dname, drop=()):
    d = tag(df, dname, drop)
    out = []
    for y, g in d.groupby("year"):
        tot = g[val].sum()
        cross = g.loc[g.bi != g.bj, val].sum()
        xU = g.loc[g.bi == "US", val].sum() / tot
        mU = g.loc[g.bj == "US", val].sum() / tot
        E = xU * (1 - mU) + (1 - xU) * mU
        out.append((y, 100 * cross / tot, (cross / tot) / E))
    return pd.DataFrame(out, columns=["year", "S", "I"]).set_index("year")


def pooled(df, val, dname, years, drop=()):
    d = tag(df, dname, drop)
    d = d[d.year.isin(years)]
    tot = d[val].sum()
    cross = d.loc[d.bi != d.bj, val].sum()
    xU = d.loc[d.bi == "US", val].sum() / tot
    mU = d.loc[d.bj == "US", val].sum() / tot
    E = xU * (1 - mU) + (1 - xU) * mU
    return 100 * cross / tot, (cross / tot) / E


def post_years(name):
    return PER["post23"] if name == "svc_rep" else PER["post"]


# 보고치 계열의 유효 연도. 패널 안 보고 완결도가 금액 기준 99% 이상인 해만 쓴다
# (2012 91.4%, 2013 95.5%, 2014 99.4%, 2015~2023 99.9% 이상, 2024 72.9%)
REP_YEARS = range(2014, 2024)


main_rows = []
for dname in DEFS:
    for name, (df, val) in series.items():
        s_early, i_early = pooled(df, val, dname, PER["early"])
        s_pre, i_pre = pooled(df, val, dname, PER["pre"])
        s_war, i_war = pooled(df, val, dname, PER["war"])
        s_cov, _ = pooled(df, val, dname, PER["covid"])
        s_post, i_post = pooled(df, val, dname, post_years(name))
        main_rows.append(dict(
            defn=dname, series=name, S_early=s_early, S_pre=s_pre, S_war=s_war, S_covid=s_cov, S_post=s_post,
            d_pretrend=(np.nan if name == "svc_rep" else s_pre - s_early), d_war=s_war - s_pre, d_post=s_post - s_pre,
            dlogodds_post=np.log((s_post / (100 - s_post)) / (s_pre / (100 - s_pre))),
            I_pre=i_pre, I_post=i_post, dI_pct=100 * (i_post / i_pre - 1)))
main = pd.DataFrame(main_rows)
main.to_csv(OUT / "main_changes.csv", index=False, encoding="utf-8-sig")
S["main"] = {f"{row.defn}|{row.series}": {k: r(getattr(row, k), 3 if k in ("I_pre", "I_post", "dlogodds_post") else 2)
                                          for k in ("S_early", "S_pre", "S_war", "S_covid", "S_post", "d_pretrend",
                                                    "d_war", "d_post", "dlogodds_post", "I_pre", "I_post", "dI_pct")}
             for row in main.itertuples()}

# 연도별 계열 (그림 1)
ann = {name: annual(df, val, "D1") for name, (df, val) in series.items()}
ann_df = pd.concat({k: v.S for k, v in ann.items()}, axis=1)
ann_df.loc[~ann_df.index.isin(REP_YEARS), "svc_rep"] = np.nan
ann_df.to_csv(OUT / "annual_D1.csv", encoding="utf-8-sig")
S["annual_D1"] = {int(y): {k: r(v, 2) for k, v in row.items()} for y, row in ann_df.iterrows()}
ann_d3 = pd.concat({k: annual(df, val, "D3").S for k, (df, val) in series.items()}, axis=1)
ann_d3.loc[~ann_d3.index.isin(REP_YEARS), "svc_rep"] = np.nan
ann_d3.to_csv(OUT / "annual_D3.csv", encoding="utf-8-sig")
S["annual_D3"] = {int(y): {k: r(v, 2) for k, v in row.items()} for y, row in ann_d3.iterrows()}

fig, axes = plt.subplots(1, 2, figsize=(10.2, 3.9), sharey=False)
for ax, (tbl, title) in zip(axes, ((ann_df, "(가) D1"), (ann_d3, "(나) D3"))):
    ax.axvspan(2019.5, 2021.5, color="0.93", lw=0)
    for x in (2018, 2022):
        ax.axvline(x, color="0.55", lw=0.8, ls=":")
    ax.plot(tbl.index, tbl.goods_rx, color="black", lw=1.6, label="상품 (BIMTS, 재수출 조정)")
    ax.plot(tbl.index, tbl.svc_bal, color="black", lw=1.6, ls="--", label="서비스 (BaTIS 균형치)")
    ax.plot(tbl.index, tbl.svc_rep, color="0.45", lw=1.3, marker="o", ms=3.2, mfc="white", mec="0.45",
            label="서비스 (보고치)")
    ax.set_title(title, loc="left", fontsize=10)  # 칸 표지. 설명 제목은 본문이 맡는다
    ax.set_ylabel("블록 간 교역 비중 (%)")
    year_axis(ax)
h, l = axes[0].get_legend_handles_labels()
fig.legend(h, l, loc="lower center", ncol=3, fontsize=9, bbox_to_anchor=(0.5, -0.06))
fig.tight_layout()
fig.savefig(IMG / "fig1_cross_share.png")
plt.close(fig)

# ============================================================ 3. 불확실성 — 수출국 단위 부트스트랩 (D1)
rng = np.random.default_rng(20260916)


def exporter_sums(df, val, dname, years):
    d = tag(df, dname)
    d = d[d.year.isin(years)]
    g = d.groupby("i")
    return pd.DataFrame({"tot": g[val].sum(), "cross": d[d.bi != d.bj].groupby("i")[val].sum()}).fillna(0)


boot = {}
for name in ("svc_bal", "svc_rep", "goods_rx"):
    df, val = series[name]
    boot[name] = (exporter_sums(df, val, "D1", PER["pre"]), exporter_sums(df, val, "D1", post_years(name)))
exps = sorted(set(boot["goods_rx"][0].index) | set(boot["svc_bal"][0].index))
B = 1000
draws = {k: [] for k in ("svc_bal", "svc_rep", "goods_rx", "diff_bal", "diff_rep")}
for _ in range(B):
    samp = rng.choice(exps, size=len(exps), replace=True)
    dd = {}
    for name, (pre, post) in boot.items():
        p0 = pre.reindex(samp).fillna(0).sum()
        p1 = post.reindex(samp).fillna(0).sum()
        dd[name] = 100 * (p1.cross / p1.tot - p0.cross / p0.tot)
        draws[name].append(dd[name])
    draws["diff_bal"].append(dd["svc_bal"] - dd["goods_rx"])
    draws["diff_rep"].append(dd["svc_rep"] - dd["goods_rx"])
S["bootstrap_D1"] = {k: {"lo": r(np.percentile(v, 2.5)), "hi": r(np.percentile(v, 97.5)), "n": B}
                     for k, v in draws.items()}
S["bootstrap_D1"]["n_exporters"] = len(exps)

# ============================================================ 4. 러시아와 대만·홍콩
rus_rows = []
for dname in DEFS:
    for name in ("svc_bal", "svc_rep", "goods_rx"):
        df, val = series[name]
        pre_all, _ = pooled(df, val, dname, PER["pre"])
        post_all, _ = pooled(df, val, dname, post_years(name))
        pre_x, _ = pooled(df, val, dname, PER["pre"], drop=("RUS", "BLR"))
        post_x, _ = pooled(df, val, dname, post_years(name), drop=("RUS", "BLR"))
        rus_rows.append(dict(defn=dname, series=name, d_all=post_all - pre_all, d_exrus=post_x - pre_x))
rus = pd.DataFrame(rus_rows)
rus.to_csv(OUT / "russia_exclusion.csv", index=False, encoding="utf-8-sig")
S["russia_exclusion"] = {f"{x.defn}|{x.series}": {"d_all": r(x.d_all), "d_exrus": r(x.d_exrus)} for x in rus.itertuples()}

# 러시아 관련 흐름의 보고 상태
rq = con.execute("""
SELECT CASE WHEN year BETWEEN 2015 AND 2017 THEN 'pre' ELSE 'post' END per,
  sum(bal) tot,
  sum(bal) FILTER (WHERE rep_x IS NOT NULL) by_x,
  sum(bal) FILTER (WHERE rep_x IS NULL AND rep_m IS NOT NULL) by_m_only,
  sum(bal) FILTER (WHERE rep_x IS NULL AND rep_m IS NULL) no_rep
FROM svc WHERE k='S' AND (i='RUS' OR j='RUS') AND (year BETWEEN 2015 AND 2017 OR year BETWEEN 2022 AND 2023)
GROUP BY 1
""").df().set_index("per")
S["russia_quality"] = {p: {"x_pct": r(100 * rq.loc[p, "by_x"] / rq.loc[p, "tot"], 1),
                           "mirror_only_pct": r(100 * rq.loc[p, "by_m_only"] / rq.loc[p, "tot"], 1),
                           "none_pct": r(100 * rq.loc[p, "no_rep"] / rq.loc[p, "tot"], 1)} for p in ("pre", "post")}
# 러시아 흐름의 보고치 대 균형치: 서방(D3) 상대, 수입국 미러 보고가 있는 쌍
rmir = con.execute("""
SELECT year, sum(bal) bal, sum(rep_m) mirror
FROM svc WHERE k='S' AND i='RUS' AND rep_m IS NOT NULL AND year BETWEEN 2015 AND 2023
GROUP BY 1 ORDER BY 1
""").df()
rmir.to_csv(OUT / "russia_mirror.csv", index=False, encoding="utf-8-sig")
S["russia_mirror"] = {int(x.year): {"bal": r(x.bal, 0), "mirror": r(x.mirror, 0)} for x in rmir.itertuples()}

tw = {}
for name in ("svc_bal", "goods_rx"):
    df, val = series[name]
    for lab, drop in (("base", ()), ("ex_twhk", ("TWN", "HKG", "MAC"))):
        p0, _ = pooled(df, val, "D1", PER["pre"], drop=drop)
        p1, _ = pooled(df, val, "D1", PER["post"], drop=drop)
        tw[f"{name}|{lab}"] = r(p1 - p0)
S["taiwan_hk_D1"] = tw

# ============================================================ 5. 서비스 범주 분해
cat = sv[sv.k.isin(CATS)].copy()
cat["grp"] = cat.k.map(GROUP)
S["cat_sum_check"] = r(100 * cat[cat.year == 2019].bal.sum() / svS[svS.year == 2019].bal.sum(), 2)


def decompose(dname, pre_y, post_y):
    d = tag(cat, dname)
    d["cross"] = d.bi != d.bj

    def st(years):
        x = d[d.year.isin(years)]
        tot = x.groupby("grp").bal.sum()
        cr = x[x.cross].groupby("grp").bal.sum().reindex(tot.index).fillna(0)
        return tot / tot.sum(), cr / tot

    w0, s0 = st(pre_y)
    w1, s1 = st(post_y)
    out = pd.DataFrame({"w_pre": 100 * w0, "w_post": 100 * w1, "s_pre": 100 * s0, "s_post": 100 * s1})
    out["ds"] = out.s_post - out.s_pre
    out["composition"] = 100 * ((s0 + s1) / 2 * (w1 - w0))
    out["within"] = 100 * ((w0 + w1) / 2 * (s1 - s0))
    return out


dec_rows = {}
for dname in DEFS:
    dec = decompose(dname, PER["pre"], PER["post"])
    dec.to_csv(OUT / f"decomp_{dname}.csv", encoding="utf-8-sig")
    dec_rows[dname] = {g: {k: r(v) for k, v in row.items()} for g, row in dec.iterrows()}
    dec_rows[dname]["_total"] = {"composition": r(dec.composition.sum()), "within": r(dec.within.sum()),
                                 "total": r(dec.composition.sum() + dec.within.sum())}
S["decomp"] = dec_rows
# 여행을 코로나 국경 통제 이후(2023~2024)로만 본 경우
dec_late = decompose("D1", PER["pre"], [2023, 2024])
S["decomp_D1_2023_24"] = {g: {k: r(v) for k, v in row.items()} for g, row in dec_late.iterrows()}
S["decomp_D1_2023_24"]["_total"] = {"composition": r(dec_late.composition.sum()),
                                    "within": r(dec_late.within.sum())}

# 범주별 연도 계열 (그림 2)
ca = tag(cat, "D1")
ca["cross"] = ca.bi != ca.bj
cs = (100 * ca[ca.cross].groupby(["year", "grp"]).bal.sum() / ca.groupby(["year", "grp"]).bal.sum()).unstack()
cs.to_csv(OUT / "annual_category_D1.csv", encoding="utf-8-sig")
S["annual_category_D1"] = {int(y): {k: r(v) for k, v in row.items()} for y, row in cs.iterrows()}

fig, ax = plt.subplots(figsize=(7.4, 4.0))
ax.axvspan(2019.5, 2021.5, color="0.93", lw=0)
for x in (2018, 2022):
    ax.axvline(x, color="0.55", lw=0.8, ls=":")
style = {"여행": ("black", "-", None), "운송": ("black", "--", None), "ICT": ("0.35", "-", "o"),
         "기타 디지털": ("0.35", "--", "s")}
for g, (c, ls, mk) in style.items():
    ax.plot(cs.index, cs[g], color=c, ls=ls, lw=1.5, marker=mk, ms=3.2, mfc="white", mec=c, label=g)
ax.plot(ann_df.index, ann_df.goods_rx, color="0.65", lw=1.2, ls=":", label="상품(참고)")
ax.set_ylabel("블록 간 교역 비중 (%)")
ax.legend(ncol=3, loc="upper center", fontsize=8.5, bbox_to_anchor=(0.5, -0.1))
year_axis(ax)
fig.savefig(IMG / "fig2_categories.png")
plt.close(fig)

# ============================================================ 6. 교역망 군집과 블록의 일치도
# 네트워크는 빈칸이 있으면 군집이 왜곡되므로 패널이 아니라 전체 균형치를 쓴다.
top = con.execute("""
WITH t AS (
  SELECT reporter c, sum(balanced_value) v FROM s.fact_batis
  WHERE item_code='S' AND flow IN ('EXP','IMP') AND partner='W' AND year BETWEEN 2015 AND 2017 GROUP BY 1)
SELECT c FROM t JOIN s.dim_area a ON t.c=a.code AND NOT a.is_aggregate ORDER BY v DESC LIMIT 80
""").df().c.tolist()
b1 = blocs.set_index("code")["D1"]
top = [c for c in top if isinstance(b1.get(c), str)]
S["network"] = {"n_nodes": len(top)}
con.register("topc", pd.DataFrame({"c": top}))
net_svc = con.execute("""
SELECT year, i, j, bal FROM svc WHERE k='S' AND i IN (SELECT c FROM topc) AND j IN (SELECT c FROM topc)
  AND year >= 2012 AND bal > 0
""").df()
net_gd = con.execute("""
SELECT year, exporter i, importer j, value bal FROM s.fact_bimts_hs2
WHERE product='_T' AND adjustment='B_ADJ_RX' AND year >= 2012 AND value > 0
  AND exporter IN (SELECT c FROM topc) AND importer IN (SELECT c FROM topc)
""").df()


def bloc_modularity(gr, dname):
    """블록 구분 자체의 가중 모듈러리티. 군집 탐지와 달리 확률적이지 않고 군집 수에 좌우되지 않는다."""
    lab = {"US": 0, "CN": 1, "NON": 2}
    bb = blocs.set_index("code")[dname]
    memb = [lab.get(bb.get(nm), 2) for nm in gr.vs["name"]]
    return gr.modularity(memb, weights="weight")


def ari_by_year(edges, seeds=range(20)):
    rows = []
    for y, g in edges.groupby("year"):
        und = g.assign(a=np.minimum(g.i, g.j), b=np.maximum(g.i, g.j)).groupby(["a", "b"]).bal.sum().reset_index()
        und = und[und.a != und.b]
        # 가중치: 두 나라 총교역 대비 쌍 교역의 비중(대칭화). 규모가 큰 나라가 모든 군집을 흡수하는 것을 줄인다
        tot = pd.concat([und.groupby("a").bal.sum(), und.groupby("b").bal.sum()]).groupby(level=0).sum()
        und["w"] = und.bal / np.sqrt(und.a.map(tot) * und.b.map(tot))
        gr = ig.Graph.TupleList(und[["a", "b", "w"]].itertuples(index=False), weights=True)
        names = gr.vs["name"]
        aligned = [k for k, nm in enumerate(names) if b1.get(nm) in ("US", "CN")]
        truth = [0 if b1[names[k]] == "US" else 1 for k in aligned]
        aris, ncom = [], []
        for sd in seeds:
            part = leidenalg.find_partition(gr, leidenalg.ModularityVertexPartition, weights="weight", seed=sd)
            memb = part.membership
            aris.append(ig.compare_communities(truth, [memb[k] for k in aligned], method="adjusted_rand"))
            ncom.append(len(set(memb)))
        rows.append((y, np.mean(aris), np.mean(ncom), bloc_modularity(gr, "D1"), bloc_modularity(gr, "D3")))
    return pd.DataFrame(rows, columns=["year", "ari", "ncom", "q_d1", "q_d3"]).set_index("year")


ari_s, ari_g = ari_by_year(net_svc), ari_by_year(net_gd)
ari = pd.DataFrame({"svc_ari": ari_s.ari, "goods_ari": ari_g.ari, "svc_ncom": ari_s.ncom, "goods_ncom": ari_g.ncom,
                    "svc_q_d1": ari_s.q_d1, "goods_q_d1": ari_g.q_d1, "svc_q_d3": ari_s.q_d3, "goods_q_d3": ari_g.q_d3})
ari.to_csv(OUT / "network_ari.csv", encoding="utf-8-sig")
S["network"]["annual"] = {int(y): {k: r(v, 3) for k, v in row.items()} for y, row in ari.iterrows()}
for lab, yrs in (("pre", PER["pre"]), ("post", PER["post"])):
    S["network"][lab] = {k: r(ari.loc[yrs, k].mean(), 3) for k in ari.columns}

fig, axes = plt.subplots(1, 2, figsize=(10.2, 3.8))
for ax in axes:
    ax.axvspan(2019.5, 2021.5, color="0.93", lw=0)
    for x in (2018, 2022):
        ax.axvline(x, color="0.55", lw=0.8, ls=":")
    year_axis(ax)
ax = axes[0]
ax.plot(ari.index, ari.goods_q_d1, color="black", lw=1.6, label="상품")
ax.plot(ari.index, ari.svc_q_d1, color="black", lw=1.6, ls="--", label="서비스")
ax.set_ylabel("모듈러리티")
ax.set_title("(가) 블록 모듈러리티", loc="left", fontsize=10)
ax.legend(loc="upper left")
ax = axes[1]
ax.plot(ari.index, ari.goods_ari, color="black", lw=1.6, label="상품")
ax.plot(ari.index, ari.svc_ari, color="black", lw=1.6, ls="--", label="서비스")
ax.set_ylabel("조정 랜드 지수")
ax.set_title("(나) 군집 일치도", loc="left", fontsize=10)
fig.tight_layout()
fig.savefig(IMG / "fig3_network.png")
plt.close(fig)

(OUT / "stats.json").write_text(json.dumps(S, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({k: S[k] for k in ("panel", "blocs", "bootstrap_D1", "russia_quality", "taiwan_hk_D1",
                                    "cat_sum_check")}, ensure_ascii=False, indent=1))
print(main[["defn", "series", "S_pre", "S_war", "S_post", "d_pretrend", "d_war", "d_post", "dI_pct"]].round(2).to_string(index=False))
print(pd.DataFrame(S["decomp"]["D1"]).T.round(2))
print(ari.round(3))

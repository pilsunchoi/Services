# SVCDB — 나라쌍 서비스 교역 DB (BaTIS) + 상품 교역 짝 (BIMTS)

OECD-WTO **BaTIS**(Balanced Trade in Services)를 본체로, OECD **BIMTS**(Balanced
International Merchandise Trade Statistics)를 짝으로 담은 DuckDB다. 설계 원칙은
`docs/db-principles.md`, 수집 계획과 그 정정 기록은 `docs/collection-plan.md`에 있다.

대시보드는 `docs/index.html` 한 파일이다(개요 · DB 구축 · 균형화와 추정 · 데이터 함정 ·
받기·사용 · 연구). GitHub Pages로 배포할 때는 source를 `main` 브랜치 `/docs`로 둔다.
숫자 카드와 표 목록은 손으로 고치지 않는다 — `python scripts/07_db_status.py --html`이
DB를 읽어 `DB_STATUS`·`DB_INVENTORY` 구간을 다시 쓴다. **표를 새로 만들면
`07_db_status.py`의 `INVENTORY` 사전에 한 줄을 더해야 한다.**

## 무엇이 들어 있나

| 표 | 행수 | 기간 | 내용 |
|---|---:|---|---|
| `fact_batis` | 50,172,380 | 2005–2024 | 나라쌍 서비스 교역. EBOPS 2010 31항목. **보고치·조정치·균형치 셋 + 방법론 코드** |
| `fact_bimts_hs2` | 52,380,894 | 1995–2024 | 나라쌍 상품 교역, HS2017 2단위 98종. 균형치 2종 |
| `fact_bimts_cpa2` | 40,136,616 | 1995–2024 | 같은 자료, CPA 2.1 57종(계층 구조) |
| `dim_area` | 223 | | 경제 코드. 세 출처를 나란히 두고 집계 여부를 표시 |
| `dim_service` | 31 | | EBOPS 2010 항목과 파생 산식 |
| `dim_methodology` | 37 | | BaTIS 방법론 코드와 분류 |
| `dim_hs2017` · `dim_cpa21` | 6,905 · 5,566 | | 품목 코드 |
| `dim_edition` · `meta_constants` | | | 판 이력, 상수로 빠진 열 |

단위는 모두 **백만 USD**다. DB 파일은 `data/processed/svcdb.duckdb`(약 1.9 GB,
gitignore됨 — 로컬 전용).

## 쓰기 전에 알아야 할 것 셋

1. **집계 코드를 개별 경제와 섞지 말 것.** `dim_area.is_aggregate`가 참인 코드
   (`W`, `EU27_2020`, `OECD`, `WXOECD`, `WXEU27_2020`, `BEL_LUX`, `SACU`)를 개별과
   함께 더하면 세계 교역이 두 배가 된다. 이름이 그룹 같은 `WXD`(Rest of the world)는
   개별 경제(잔차)이므로 **빼면 안 된다**.
2. **BaTIS의 값은 셋이다.** 어느 것을 쓰는지 밝히지 않은 분석은 재현되지 않는다.
   `reported_value`는 전체 행의 3.5%에만 있고, `balanced_value`는 각국 공표치와 다르다
   (한국 2023년 서비스 수출: 보고 125,666 대 균형 107,385 백만 USD). 균형치는 개별
   경제쌍에서 수출=거울상 수입이 **정확히** 성립하므로, 균형치로는 비대칭을 연구할 수 없다.
3. **CPA 2.1은 계층이다.** 전 품목을 더하면 여러 번 센다. 섹션(`CPA_2_1_A` 꼴)만
   더해야 총계(`_T`)와 같다. HS2017 2단위는 평평하다.

## 연결

```python
import duckdb
con = duckdb.connect("data/processed/svcdb.duckdb", read_only=True)
con.execute("""
    SELECT year, sum(balanced_value) AS exports_musd
    FROM fact_batis
    WHERE reporter='KOR' AND partner='W' AND flow='EXP' AND item_code='S'
    GROUP BY 1 ORDER BY 1
""").df()
```

## 연구

`research/` 아래에 이 DB로 수행한 분석을 둔다. 각 연구는 문서, 재현 노트북, 수치를
만드는 스크립트를 함께 담는다. 노트북 마지막 절이 본문이 인용한 값을 다시 계산해
대조하므로, 판이 바뀌어 숫자가 달라지면 그 자리에서 멈춘다.

1. [서비스 교역 자료의 구조와 기술적 개관](research/01-data-overview/paper.md)
   — BaTIS와 BIMTS의 구조, 국제·국내 자료와의 관계, 세계 규모와 보고 커버리지, 비대칭,
   한국의 위치. [재현 노트북](research/01-data-overview/reproduce.ipynb)
2. [지경학적 분절화는 서비스 교역에서도 일어나는가](research/02-fragmentation/paper.md)
   — 같은 국가쌍에서 상품과 서비스의 블록 간 교역 비중을 비교. 네 가지 블록 정의, 서비스 범주 분해,
   교역망 구조. [재현 노트북](research/02-fragmentation/reproduce.ipynb). 이념점수 원자료는
   `research/02-fragmentation/fetch_unga.py`가 받고, 상품 대조 계열(BACI)은 TradeNetworkAtlas 프로젝트의 DB를 읽는다.

## 파이프라인

```bash
python scripts/00_probe_source.py             # 판이 바뀌었는지 점검(내려받지 않음)
python scripts/01_fetch_batis.py              # BaTIS 벌크 zip (490MB)
python scripts/02_fetch_bimts.py --depth 2d cpa   # BIMTS 2단위 (1.3GB)
python scripts/03_load_batis.py               # CSV → parquet → fact_batis
python scripts/04_load_bimts.py               # CSV → parquet → fact_bimts_*
python scripts/05_build_dims.py               # dim_area·service·methodology
python scripts/05b_build_product_dims.py      # dim_hs2017·dim_cpa21
python scripts/06_validate.py                 # 무결성 검증 (PASS/WARN/FAIL)
python scripts/07_db_status.py                # 현황
```

필요한 패키지는 `requirements.txt`의 넷이면 된다 — conda나 특정 파이썬 버전은 필요 없다.

`data/raw/<dataset>/<edition>/`에 받은 zip 원본과 `manifest.json`(URL·크기·sha256·시각)이
남는다. **OECD는 새 판을 내며 URL을 그대로 두므로 이 사본이 판을 특정하는 유일한
근거다.**

## 출처

- OECD-WTO Balanced Trade in Services (BaTIS), BPM6, December 2025 판.
- OECD Balanced International Merchandise Trade Statistics (BIMTS), 2026-05 파일.
- 둘 다 OECD 배포본을 정본으로 삼았다. OECD 콘텐츠는 2024년 7월 이후 CC BY 4.0이
  기본이며, BaTIS는 WTO와의 공동 산출물이므로 인용 시 양쪽을 함께 밝힌다.
- 방법론 문서는 `data/external/`에 함께 보존한다.

## 라이선스

이 저장소의 코드와 문서는 [MIT 라이선스](LICENSE)를 따른다. **원자료는 그 대상이
아니다** — OECD·WTO의 이용조건과 출처표시 의무, 판을 밝혀야 하는 이유는
[`NOTICE.md`](NOTICE.md)에 있다.

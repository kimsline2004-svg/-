# -*- coding: utf-8 -*-
"""
미국주식 재무 조회 앱
회사명(또는 티커)을 입력하면 매출, 영업이익, 영업활동현금흐름(OCF), 잉여현금흐름(FCF), 시가총액을 보여줍니다.

데이터 출처 (사이드바에서 선택)
  - SEC  : 미국 증권거래위원회 EDGAR XBRL API (무료, 10년 이상, API 키 불필요)
  - FMP  : Financial Modeling Prep API (무료 요금제는 최근 5개 기간까지)
"""

from datetime import date

import altair as alt
import requests
import pandas as pd
import streamlit as st

# 기관/회사 네트워크나 백신 프로그램이 HTTPS를 검사(SSL 인터셉트)하는 환경에서는
# 파이썬 기본 인증서 목록으로 검증이 실패한다. 윈도우가 이미 신뢰하는
# 시스템 인증서 저장소를 파이썬도 함께 쓰도록 설정한다.
TRUSTSTORE_ACTIVE = False
try:
    import truststore

    truststore.inject_into_ssl()
    TRUSTSTORE_ACTIVE = True
except Exception:
    pass

BASE_URL = "https://financialmodelingprep.com/stable"
PLAN_ERR = "[PLAN]"  # 요금제 제한 오류를 구분하기 위한 내부 표식

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

VALUE_COLS = [
    "매출 (Revenue)",
    "영업이익 (Operating Income)",
    "영업활동현금흐름 (OCF)",
    "잉여현금흐름 (FCF)",
]

st.set_page_config(page_title="미국주식 재무 조회기", page_icon="📊", layout="wide")


# ---------------------------------------------------------------------------
# 공통 유틸
# ---------------------------------------------------------------------------

def format_usd(value):
    """큰 금액을 보기 좋은 단위(T/B/M)로 변환"""
    if value is None:
        return "N/A"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "N/A"
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1e12:
        return f"{sign}${value / 1e12:,.2f}T"
    if value >= 1e9:
        return f"{sign}${value / 1e9:,.2f}B"
    if value >= 1e6:
        return f"{sign}${value / 1e6:,.2f}M"
    return f"{sign}${value:,.0f}"


def get_first(d, keys, default=None):
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] is not None:
            return d[k]
    return default


def ssl_verify():
    return not st.session_state.get("skip_ssl_verify", False)


# 지표별 고정 색상 (순서 고정, 순환 금지)
SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
GROWTH_COLOR = "#4a3aa7"  # 성장률 선 (막대 색과 겹치지 않는 슬롯)
GRID_COLOR = "#ececec"
LABEL_COLOR = "#52514e"


def pick_unit(frame):
    """표에 들어있는 금액 규모에 맞춰 축 단위를 고른다"""
    values = pd.to_numeric(frame.stack(), errors="coerce").dropna().abs()
    biggest = float(values.max()) if len(values) else 0.0
    if biggest >= 1e12:
        return 1e12, "조 달러 (USD T)"
    if biggest >= 1e9:
        return 1e9, "십억 달러 (USD B)"
    if biggest >= 1e6:
        return 1e6, "백만 달러 (USD M)"
    return 1.0, "달러 (USD)"


def show_chart(chart):
    """Streamlit 버전에 따라 너비 옵션이 달라 두 방식을 모두 지원"""
    try:
        st.altair_chart(chart, width="stretch")
    except TypeError:
        st.altair_chart(chart, use_container_width=True)


def label_to_date(label):
    """기간 라벨('2024' 또는 '2024-06-30')을 날짜로 변환"""
    text = str(label)
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    try:
        return date(int(text[:4]), 12, 31)
    except (ValueError, TypeError):
        return None


def previous_year_label(label, period_order, period_kind):
    """전년 동기(연간이면 직전 연도, 분기면 4분기 전) 라벨을 찾는다"""
    current = label_to_date(label)
    if current is None:
        return None
    if period_kind == "annual":
        target_year = current.year - 1
        for candidate in period_order:
            candidate_date = label_to_date(candidate)
            if candidate_date and candidate_date.year == target_year:
                return candidate
        return None
    best, best_gap = None, None
    for candidate in period_order:
        candidate_date = label_to_date(candidate)
        if not candidate_date or candidate_date >= current:
            continue
        gap = abs((current - candidate_date).days - 365)
        if gap <= 45 and (best_gap is None or gap < best_gap):
            best, best_gap = candidate, gap
    return best


def compute_growth(long_df, period_order, period_kind, series_field="지표"):
    """전년 대비 성장률(%) 계산. 직전 값이 0 이하이면 비율이 왜곡되므로 건너뛴다."""
    records = []
    for series_name, group in long_df.groupby(series_field, sort=False):
        values = dict(zip(group["기간"], group["원값"]))
        for label in period_order:
            base_label = previous_year_label(label, period_order, period_kind)
            if base_label is None:
                continue
            current, base = values.get(label), values.get(base_label)
            if current is None or base is None or base <= 0:
                continue
            records.append(
                {
                    "기간": label,
                    series_field: series_name,
                    "성장률": (current - base) / base * 100.0,
                    "비교": f"{base_label} 대비",
                }
            )
    return pd.DataFrame(records)


GROWTH_MIN = -30.0  # 성장률 축 하한 (%)
GROWTH_MAX = 50.0   # 성장률 축 상한 (%)


def growth_axis_values(step=10):
    """성장률 축 눈금을 범위에 맞춰 10% 간격으로 만든다"""
    start = int(GROWTH_MIN // step * step)
    values = []
    tick = start
    while tick <= GROWTH_MAX:
        if tick >= GROWTH_MIN:
            values.append(tick)
        tick += step
    return values


def growth_overlay(growth_df, period_order, color=None):
    """
    막대그래프 위에 겹쳐 그리는 전년 대비 성장률 선 (오른쪽 축).
    축은 0~60%로 고정하고, 범위를 벗어난 값은 경계선 위에 찍는다.
    실제 값은 마우스를 올리면 그대로 확인할 수 있다.
    """
    color = color or GROWTH_COLOR

    data = growth_df.copy()
    data["표시값"] = data["성장률"].clip(lower=GROWTH_MIN, upper=GROWTH_MAX)
    data["실제"] = data["성장률"].map(lambda v: f"{v:,.1f}%")
    data["상한초과"] = data["성장률"] > GROWTH_MAX
    data["하한미만"] = data["성장률"] < GROWTH_MIN

    axis = alt.Axis(
        title=f"전년 대비 (%) · {GROWTH_MIN:.0f}~{GROWTH_MAX:.0f} 고정",
        orient="right", format=".0f", values=growth_axis_values(),
        labelFontSize=11, titleFontSize=11, titleColor=color, labelColor=color,
        ticks=False, labelPadding=5, grid=False,
    )
    scale = alt.Scale(domain=[GROWTH_MIN, GROWTH_MAX], clamp=True, nice=False)
    tooltip = [
        alt.Tooltip("기간:N", title="기간"),
        alt.Tooltip("실제:N", title="성장률(실제)"),
        alt.Tooltip("비교:N", title="기준"),
    ]

    zero_rule = (
        alt.Chart(pd.DataFrame({"표시값": [0.0]}))
        .mark_rule(color=color, strokeDash=[4, 4], opacity=0.4)
        .encode(y=alt.Y("표시값:Q", axis=axis, scale=scale))
    )

    line = (
        alt.Chart(data)
        .mark_line(
            strokeWidth=2, color=color,
            point=alt.OverlayMarkDef(size=80, filled=True, color=color, stroke="#ffffff", strokeWidth=2),
        )
        .encode(
            x=alt.X("기간:N", sort=period_order),
            y=alt.Y("표시값:Q", axis=axis, scale=scale),
            tooltip=tooltip,
        )
    )

    # 범위를 벗어나 경계에 붙은 값은 삼각형으로 표시
    over = (
        alt.Chart(data)
        .transform_filter(alt.datum["상한초과"])
        .mark_point(shape="triangle-up", size=150, filled=True, color=color,
                    stroke="#ffffff", strokeWidth=1.5, yOffset=-7)
        .encode(x=alt.X("기간:N", sort=period_order), y=alt.Y("표시값:Q", axis=axis, scale=scale),
                tooltip=tooltip)
    )
    under = (
        alt.Chart(data)
        .transform_filter(alt.datum["하한미만"])
        .mark_point(shape="triangle-down", size=150, filled=True, color=color,
                    stroke="#ffffff", strokeWidth=1.5, yOffset=7)
        .encode(x=alt.X("기간:N", sort=period_order), y=alt.Y("표시값:Q", axis=axis, scale=scale),
                tooltip=tooltip)
    )

    return alt.layer(zero_rule, line, over, under)


def api_get(path, params):
    """FMP API 호출 공통 함수. 실패 시 (None, 에러메시지) 반환"""
    params = dict(params)
    params["apikey"] = st.session_state.get("api_key", "")
    try:
        resp = requests.get(f"{BASE_URL}/{path}", params=params, timeout=15, verify=ssl_verify())
    except requests.exceptions.SSLError as e:
        return None, (
            "SSL 인증서 검증에 실패했습니다. 기관·회사 네트워크나 백신 프로그램이 HTTPS 통신을 "
            "검사하는 환경에서 발생합니다.\n\n"
            "해결: PowerShell에서 `pip install truststore` 실행 후 앱 재시작. "
            "그래도 안 되면 사이드바 '고급 설정'에서 인증서 검증 건너뛰기를 켜보세요.\n\n"
            f"(원본 오류: {e})"
        )
    except requests.RequestException as e:
        return None, f"네트워크 오류: {e}"

    if resp.status_code == 401:
        return None, "API 키가 유효하지 않습니다. 사이드바에서 API 키를 확인해 주세요."
    if resp.status_code in (402, 403):
        return None, (
            f"{PLAN_ERR}현재 요금제(무료)에서 제공되지 않는 데이터입니다. "
            f"(요청: {path}, 기간: {params.get('period', '-')}, 종목: {params.get('symbol', '-')})\n\n"
            f"API 원문: {resp.text[:300]}"
        )
    if resp.status_code == 429:
        return None, "API 호출 한도를 초과했습니다 (무료 요금제는 하루 250회). 잠시 후 다시 시도해 주세요."
    if resp.status_code != 200:
        return None, f"API 오류 (status {resp.status_code}): {resp.text[:200]}"

    try:
        data = resp.json()
    except ValueError:
        return None, "응답을 해석할 수 없습니다 (JSON 아님)."

    if isinstance(data, dict) and data.get("Error Message"):
        return None, data["Error Message"]

    return data, None


US_EXCHANGE_KEYWORDS = ("NASDAQ", "NYSE", "AMEX", "CBOE", "BATS")


def is_us_listing(item):
    """미국 상장 종목인지 판별 (FMP 무료 요금제는 미국 상장 종목만 조회 가능)"""
    symbol = str(get_first(item, ["symbol"], "") or "")
    if "." in symbol:  # AAPL.DE, AAPL.MX 등 해외 거래소 상장분
        return False
    exch = str(get_first(item, ["exchangeShortName", "exchange", "exchangeFullName"], "") or "").upper()
    if not exch:
        return True
    return any(k in exch for k in US_EXCHANGE_KEYWORDS)


def looks_like_ticker(q):
    """NVDA, AAPL 처럼 티커로 보이는 입력인지"""
    return bool(q) and q.isalnum() and len(q) <= 6 and " " not in q


def match_rank(item, query):
    """검색어와 얼마나 정확히 일치하는지 (작을수록 우선)"""
    q = query.upper()
    symbol = str(get_first(item, ["symbol"], "") or "").upper()
    name = str(get_first(item, ["name", "companyName"], "") or "").upper()
    if symbol == q:
        return 0
    if symbol.startswith(q):
        return 1
    if name.startswith(q):
        return 2
    if q in name:
        return 3
    return 4


def fmp_search(query):
    """티커 검색(search-symbol)과 회사명 검색(search-name)을 함께 사용해 후보를 모은다"""
    q = query.strip()
    paths = ["search-symbol", "search-name"] if looks_like_ticker(q) else ["search-name", "search-symbol"]

    merged, seen, first_error = [], set(), None
    for path in paths:
        data, err = api_get(path, {"query": q, "limit": 20})
        if err:
            first_error = first_error or err
            continue
        for item in data or []:
            symbol = str(get_first(item, ["symbol"], "") or "").upper()
            if symbol and symbol not in seen:
                seen.add(symbol)
                merged.append(item)
        if any(match_rank(x, q) == 0 for x in merged):
            break

    if not merged:
        return (None, first_error) if first_error else ([], None)

    if st.session_state.get("us_only", True):
        merged = [x for x in merged if is_us_listing(x)] or merged

    merged.sort(key=lambda x: (match_rank(x, q), 0 if is_us_listing(x) else 1))
    return merged, None


FREE_PLAN_MAX_LIMIT = 5  # FMP 무료 요금제는 limit 0~5만 허용


def fmp_fetch_statement(path, symbol, period_param, limit):
    """재무제표 조회. 요금제 제한에 걸리면 연간으로 자동 재시도한다."""
    limit = max(1, min(int(limit), FREE_PLAN_MAX_LIMIT))
    data, err = api_get(path, {"symbol": symbol, "period": period_param, "limit": limit})
    if err and err.startswith(PLAN_ERR) and period_param != "annual":
        data_annual, err_annual = api_get(
            path, {"symbol": symbol, "period": "annual", "limit": limit}
        )
        if not err_annual:
            return data_annual, None, "annual"
    return data, err, period_param


def fmp_rows(symbol, period_param, n_periods):
    """FMP에서 기간별 지표를 뽑아 표 형태로 만든다. (rows, errors, 실제기간종류)"""
    income_data, income_err, used_period = fmp_fetch_statement(
        "income-statement", symbol, period_param, n_periods
    )
    cash_data, cash_err, _ = fmp_fetch_statement(
        "cash-flow-statement", symbol, period_param, n_periods
    )

    income_by_date, cash_by_date = {}, {}
    if isinstance(income_data, list):
        for item in income_data:
            income_by_date[get_first(item, ["date"])] = item
    if isinstance(cash_data, list):
        for item in cash_data:
            cash_by_date[get_first(item, ["date"])] = item

    rows = []
    for date_key in sorted(set(income_by_date) | set(cash_by_date), reverse=True):
        inc = income_by_date.get(date_key, {})
        cf = cash_by_date.get(date_key, {})

        ocf = get_first(cf, ["operatingCashFlow", "netCashProvidedByOperatingActivities"])
        fcf = get_first(cf, ["freeCashFlow"])
        capex = get_first(cf, ["capitalExpenditure"])
        if fcf is None and ocf is not None and capex is not None:
            fcf = ocf + capex  # FMP의 capex는 통상 음수로 제공됨

        label = get_first(inc, ["fiscalYear"], date_key) if used_period == "annual" else date_key
        rows.append(
            {
                "기간": label,
                VALUE_COLS[0]: get_first(inc, ["revenue"]),
                VALUE_COLS[1]: get_first(inc, ["operatingIncome"]),
                VALUE_COLS[2]: ocf,
                VALUE_COLS[3]: fcf,
            }
        )

    errors = [e for e in (income_err, cash_err) if e]
    return rows, errors, used_period


# ---------------------------------------------------------------------------
# 데이터 출처 2 — SEC EDGAR (XBRL)
# ---------------------------------------------------------------------------

# 회사마다 사용하는 XBRL 태그가 달라 우선순위 목록으로 찾는다.
REVENUE_TAGS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
    "RevenuesNetOfInterestExpense",
]
OPERATING_INCOME_TAGS = ["OperatingIncomeLoss"]
OCF_TAGS = [
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
]
CAPEX_TAGS = [
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
    "PaymentsForCapitalImprovements",
    "PaymentsToAcquireOtherPropertyPlantAndEquipment",
]


def sec_headers(contact):
    """SEC는 연락처가 담긴 User-Agent를 요구한다 (예: MyApp myemail@example.com)."""
    contact = (contact or "").strip() or "us-stock-financials-app@example.com"
    return {
        "User-Agent": f"financials-viewer/1.0 {contact}",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }


def _sec_get_json(url, contact, verify, timeout=60):
    resp = requests.get(url, headers=sec_headers(contact), timeout=timeout, verify=verify)
    if resp.status_code == 403:
        raise RuntimeError(
            f"SEC가 요청을 거부했습니다(403). 접속 주소: {url}\n"
            "SEC 서버가 프로그램 접속을 차단했거나, 기관 네트워크에서 막혔을 수 있습니다."
        )
    if resp.status_code == 404:
        raise RuntimeError("SEC에 해당 기업의 재무 데이터가 없습니다.")
    resp.raise_for_status()
    return resp.json()


@st.cache_data(ttl=86400, show_spinner=False)
def sec_ticker_table(contact, verify):
    """SEC 공식 티커 목록 (하루 1회만 내려받아 캐시)"""
    data = _sec_get_json(SEC_TICKERS_URL, contact, verify, timeout=30)
    rows = []
    for item in data.values():
        rows.append(
            {
                "symbol": str(item.get("ticker", "")).upper(),
                "name": item.get("title", ""),
                "cik": int(item.get("cik_str", 0)),
            }
        )
    return rows


def resolve_cik_via_fmp(symbol):
    """www.sec.gov 목록이 막혔을 때 FMP 프로필에서 CIK를 얻는다"""
    data, err = api_get("profile", {"symbol": symbol})
    if err or not isinstance(data, list) or not data:
        return None
    cik = get_first(data[0], ["cik"])
    try:
        return int(str(cik).lstrip("CIK").lstrip("0") or 0) or None
    except (TypeError, ValueError):
        return None


def sec_search(query):
    """SEC 티커 목록에서 회사명/티커로 검색. 목록이 막히면 FMP 검색으로 대체한다."""
    contact = st.session_state.get("sec_contact", "")
    try:
        rows = sec_ticker_table(contact, ssl_verify())
    except Exception as e:
        # www.sec.gov 접속이 막힌 경우: FMP로 종목만 찾고, CIK는 나중에 FMP 프로필에서 얻는다
        if st.session_state.get("api_key"):
            results, fmp_err = fmp_search(query)
            if results:
                st.info(
                    "SEC 종목 목록 서버(www.sec.gov)에 접속하지 못해 종목 검색만 FMP로 대체했습니다. "
                    "재무 데이터는 그대로 SEC에서 가져옵니다."
                )
                return results, None
            return None, fmp_err or f"SEC 종목 목록을 불러오지 못했습니다: {e}"
        return None, (
            f"SEC 종목 목록을 불러오지 못했습니다: {e}\n\n"
            "FMP API 키를 입력하면 종목 검색만 FMP로 대체해서 계속 사용할 수 있습니다."
        )

    q = query.strip().upper()
    matches = [
        r for r in rows
        if r["symbol"] == q or r["symbol"].startswith(q) or q in r["name"].upper()
    ]
    matches.sort(
        key=lambda r: (
            0 if r["symbol"] == q else 1 if r["symbol"].startswith(q) else
            2 if r["name"].upper().startswith(q) else 3,
            len(r["symbol"]),
        )
    )
    return [
        {"symbol": r["symbol"], "name": r["name"], "cik": r["cik"], "exchangeFullName": "SEC EDGAR"}
        for r in matches[:20]
    ], None


@st.cache_data(ttl=3600, show_spinner=False)
def sec_company_facts(cik, contact, verify):
    """기업의 전체 XBRL 재무 데이터 (한 번 받아서 캐시)"""
    return _sec_get_json(SEC_FACTS_URL.format(cik=str(cik).zfill(10)), contact, verify, timeout=90)


def _sec_raw_facts(facts, tags):
    """태그 우선순위대로 훑어 {(시작일, 종료일): 금액} 형태로 수집"""
    us_gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    picked = {}  # (시작일, 종료일) -> (금액, 제출일, 태그)
    for tag in tags:  # 앞선 태그가 우선. 기업이 중간에 태그를 바꿔도 뒤 태그가 빈 기간을 채운다.
        entry = us_gaap.get(tag)
        if not entry:
            continue
        for unit_name, items in (entry.get("units") or {}).items():
            if not unit_name.startswith("USD"):
                continue
            for item in items:
                begin, finish, val = item.get("start"), item.get("end"), item.get("val")
                if not begin or not finish or val is None:
                    continue
                key = (begin, finish)
                filed = item.get("filed", "")
                if key in picked:
                    # 같은 기간이면 나중에 제출된(정정된) 값을 쓰되, 태그 우선순위는 유지
                    if picked[key][2] == tag and filed > picked[key][1]:
                        picked[key] = (float(val), filed, tag)
                else:
                    picked[key] = (float(val), filed, tag)
    return {k: v[0] for k, v in picked.items()}


def _period_days(begin, finish):
    try:
        return (date.fromisoformat(finish) - date.fromisoformat(begin)).days
    except (ValueError, TypeError):
        return None


def _sec_series(facts, tags, period_kind):
    """
    기간 종류에 맞는 {기간종료일: 금액}.

    분기의 경우 현금흐름표는 10-Q에 누적(3개월→6개월→9개월)으로만 실리는 경우가 많아,
    누적값을 앞 기간과 차감해 각 분기 금액을 복원한다. 10-K의 연간값에서 9개월 누적을
    빼면 4분기도 채워진다.
    """
    raw = _sec_raw_facts(facts, tags)

    if period_kind == "annual":
        result = {}
        for (begin, finish), val in raw.items():
            days = _period_days(begin, finish)
            if days is not None and 330 <= days <= 400:
                result[finish] = val
        return result

    # 1) 3개월짜리로 직접 공시된 값 (손익계산서는 보통 여기서 다 잡힌다)
    direct = {}
    for (begin, finish), val in raw.items():
        days = _period_days(begin, finish)
        if days is not None and 75 <= days <= 105:
            direct[finish] = val

    # 2) 누적 공시를 차감해 분기값 복원 (현금흐름표용)
    derived = {}
    groups = {}
    for (begin, finish), val in raw.items():
        days = _period_days(begin, finish)
        if days is None or not 75 <= days <= 400:
            continue
        groups.setdefault(begin, []).append((finish, val, days))

    for begin, items in groups.items():
        items.sort(key=lambda x: x[0])  # 종료일 순 = 누적 순서
        prev_end, prev_val, prev_days = None, 0.0, 0
        for finish, val, days in items:
            if prev_end is None:
                if 75 <= days <= 105:  # 누적 사슬의 첫 구간이 1분기인 경우만 사용
                    derived.setdefault(finish, val)
            else:
                gap = _period_days(prev_end, finish)
                if gap is not None and 75 <= gap <= 105 and days > prev_days:
                    derived.setdefault(finish, val - prev_val)
            prev_end, prev_val, prev_days = finish, val, days

    derived.update(direct)  # 직접 공시된 값이 우선
    return derived


def sec_rows(cik, period_param, n_periods):
    """SEC에서 기간별 지표를 뽑아 표 형태로 만든다"""
    contact = st.session_state.get("sec_contact", "")
    try:
        facts = sec_company_facts(int(cik), contact, ssl_verify())
    except Exception as e:
        return [], [f"SEC 재무 데이터를 불러오지 못했습니다: {e}"], period_param

    kind = "annual" if period_param == "annual" else "quarter"
    revenue = _sec_series(facts, REVENUE_TAGS, kind)
    operating = _sec_series(facts, OPERATING_INCOME_TAGS, kind)
    ocf = _sec_series(facts, OCF_TAGS, kind)
    capex = _sec_series(facts, CAPEX_TAGS, kind)

    all_ends = sorted(set(revenue) | set(operating) | set(ocf), reverse=True)[: int(n_periods)]
    if not all_ends:
        return [], ["SEC에서 해당 기간의 재무 데이터를 찾지 못했습니다."], period_param

    labels = [end[:4] for end in all_ends] if kind == "annual" else list(all_ends)
    if len(set(labels)) != len(labels):  # 같은 연도가 겹치면 날짜 전체를 표기
        labels = list(all_ends)

    rows = []
    for label, end in zip(labels, all_ends):
        operating_cf = ocf.get(end)
        capital_exp = capex.get(end)
        fcf = None
        if operating_cf is not None and capital_exp is not None:
            fcf = operating_cf - capital_exp  # SEC의 capex는 양수(현금 유출)로 보고됨
        rows.append(
            {
                "기간": label,
                VALUE_COLS[0]: revenue.get(end),
                VALUE_COLS[1]: operating.get(end),
                VALUE_COLS[2]: operating_cf,
                VALUE_COLS[3]: fcf,
            }
        )
    return rows, [], period_param


# ---------------------------------------------------------------------------
# 사이드바
# ---------------------------------------------------------------------------

def default_api_key():
    """.streamlit/secrets.toml 에 FMP_API_KEY가 있으면 기본값으로 사용"""
    try:
        return st.secrets.get("FMP_API_KEY", "")
    except Exception:
        return ""


with st.sidebar:
    st.header("설정")

    source = st.radio(
        "데이터 출처",
        options=["SEC EDGAR (무료·최대 20개 기간)", "FMP (최근 5개 기간)"],
        index=0,
        help="SEC EDGAR는 기업이 제출한 10-K/10-Q 원본 데이터라 기간 제한이 사실상 없습니다. "
        "FMP는 정제된 데이터지만 무료 요금제에서 5개 기간까지만 제공됩니다.",
    )
    use_sec = source.startswith("SEC")

    period = st.radio("기간", options=["연간 (Annual)", "분기 (Quarterly)"], index=0)
    period_param = "annual" if period.startswith("연간") else "quarter"

    n_periods = st.slider(
        "표시할 기간 수",
        min_value=1,
        max_value=20 if use_sec else 5,
        value=10 if use_sec else 5,
        help="FMP 무료 요금제는 최대 5개까지만 조회할 수 있습니다. SEC는 더 긴 기간이 가능합니다.",
    )

    st.markdown("---")

    if use_sec:
        st.session_state["sec_contact"] = st.text_input(
            "SEC 연락처 이메일",
            value=st.session_state.get("sec_contact", ""),
            help="SEC는 API 요청자에게 연락처를 요구합니다. 본인 이메일을 넣어두면 차단 없이 조회됩니다.",
            placeholder="예: hong@example.com",
        )
        st.caption("시가총액·현재가는 SEC에 없어 FMP 키가 있으면 그쪽에서 가져옵니다.")

        if st.button("SEC 연결 테스트", help="SEC 서버 두 곳에 실제로 접속되는지 확인합니다."):
            for name, test_url in (
                ("종목 목록 (www.sec.gov)", SEC_TICKERS_URL),
                ("재무 데이터 (data.sec.gov)", SEC_FACTS_URL.format(cik="0000320193")),
            ):
                try:
                    r = requests.get(
                        test_url,
                        headers=sec_headers(st.session_state.get("sec_contact", "")),
                        timeout=20,
                        verify=ssl_verify(),
                    )
                    if r.status_code == 200:
                        st.success(f"{name}: 정상 (200)")
                    else:
                        st.error(f"{name}: 실패 ({r.status_code})")
                except Exception as exc:
                    st.error(f"{name}: 접속 오류 — {exc}")

    api_key_input = st.text_input(
        "Financial Modeling Prep API 키",
        value=default_api_key(),
        type="password",
        help="FMP 데이터 출처 및 시가총액 조회에 사용됩니다.",
    )
    st.session_state["api_key"] = api_key_input.strip()

    if not use_sec:
        st.session_state["us_only"] = st.checkbox(
            "미국 상장 종목만 표시",
            value=True,
            help="FMP 무료 요금제는 미국 상장 종목(NASDAQ·NYSE 등)만 조회할 수 있습니다.",
        )

    st.markdown("---")
    st.markdown("---")
    with st.expander("고급 설정 (SSL 오류 시)"):
        if TRUSTSTORE_ACTIVE:
            st.caption("✅ 윈도우 시스템 인증서 저장소를 사용 중입니다.")
        else:
            st.caption(
                "⚠️ truststore 모듈이 없습니다. SSL 오류가 나면 PowerShell에서 "
                "`pip install truststore` 실행 후 앱을 다시 시작하세요."
            )
        skip_ssl = st.checkbox(
            "SSL 인증서 검증 건너뛰기",
            value=False,
            help="위 방법으로 해결되지 않을 때만 사용하세요. 통신 내용의 변조를 확인할 수 없게 됩니다.",
        )
        st.session_state["skip_ssl_verify"] = skip_ssl
        if skip_ssl:
            try:
                import urllib3

                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            except Exception:
                pass
            st.warning("인증서 검증이 꺼져 있습니다. 문제 해결 후에는 다시 켜는 것을 권장합니다.")

    st.caption(
        "출처: [SEC EDGAR](https://www.sec.gov/edgar) · "
        "[Financial Modeling Prep](https://financialmodelingprep.com)"
    )

# ---------------------------------------------------------------------------
# 메인 화면
# ---------------------------------------------------------------------------

st.title("📊 미국주식 재무 조회기")
st.caption("회사명 또는 티커(예: Apple, AAPL, Microsoft, NVDA)를 입력하면 매출·영업이익·OCF·FCF·시가총액을 보여줍니다.")

if not use_sec and not st.session_state.get("api_key"):
    st.info("FMP를 쓰려면 사이드바에 API 키를 입력하거나, 데이터 출처를 SEC EDGAR로 바꿔 주세요.")

query = st.text_input("회사명 또는 티커 입력", placeholder="예: Apple, Tesla, Microsoft, NVDA ...")
search_disabled = (not use_sec) and (not st.session_state.get("api_key"))
search_clicked = st.button("검색", type="primary", disabled=search_disabled)

if "candidates" not in st.session_state:
    st.session_state["candidates"] = []

if search_clicked and query.strip():
    with st.spinner("종목 검색 중..."):
        results, err = sec_search(query) if use_sec else fmp_search(query)
    if err:
        st.error(err.replace(PLAN_ERR, ""))
        st.session_state["candidates"] = []
    elif not results:
        st.warning("일치하는 종목을 찾지 못했습니다. 영문 회사명이나 티커로 다시 시도해 보세요.")
        st.session_state["candidates"] = []
    else:
        st.session_state["candidates"] = results

candidates = st.session_state.get("candidates", [])
selected = None

if candidates:
    def label_for(item):
        symbol = get_first(item, ["symbol"], "?")
        name = get_first(item, ["name", "companyName"], "")
        exch = get_first(item, ["exchangeFullName", "stockExchange", "exchangeShortName"], "")
        return f"{symbol} — {name} ({exch})" if exch else f"{symbol} — {name}"

    labels = [label_for(c) for c in candidates]
    choice = st.selectbox("검색 결과에서 종목을 선택하세요", options=labels, index=0)
    selected = candidates[labels.index(choice)]

# ---------------------------------------------------------------------------
# 재무 데이터 조회 및 표시
# ---------------------------------------------------------------------------

if selected:
    selected_symbol = get_first(selected, ["symbol"])
    selected_name = get_first(selected, ["name", "companyName"], selected_symbol)
    selected_cik = get_first(selected, ["cik"])

    with st.spinner(f"{selected_symbol} 재무 데이터 조회 중..."):
        profile = {}
        profile_error = None
        if st.session_state.get("api_key"):
            profile_data, profile_error = api_get("profile", {"symbol": selected_symbol})
            if isinstance(profile_data, list) and profile_data:
                profile = profile_data[0]

        # SEC 목록이 막혀 CIK가 없으면 FMP 프로필에서 가져온다
        if use_sec and not selected_cik:
            cik_from_profile = get_first(profile, ["cik"])
            if cik_from_profile:
                try:
                    selected_cik = int(str(cik_from_profile).lstrip("CIK") or 0) or None
                except (TypeError, ValueError):
                    selected_cik = None
            if not selected_cik:
                selected_cik = resolve_cik_via_fmp(selected_symbol)

        if use_sec and selected_cik:
            rows, errors, used_period = sec_rows(selected_cik, period_param, n_periods)
        elif use_sec:
            rows, errors, used_period = [], [
                "이 종목의 SEC 기업번호(CIK)를 찾지 못했습니다. 사이드바에서 데이터 출처를 FMP로 바꿔 보세요."
            ], period_param
        else:
            rows, errors, used_period = fmp_rows(selected_symbol, period_param, n_periods)

        if profile_error:
            errors = list(errors) + [profile_error]

    if used_period != period_param:
        st.info("분기 데이터가 제한되어 연간 데이터로 표시합니다.")

    seen_errors = set()
    for e in errors:
        if e and e not in seen_errors:
            seen_errors.add(e)
            st.error(e.replace(PLAN_ERR, ""))

    company_name = get_first(profile, ["companyName"], selected_name)
    currency = get_first(profile, ["currency"], "USD")
    market_cap = get_first(profile, ["marketCap"])
    price = get_first(profile, ["price"])

    st.subheader(f"{company_name} ({selected_symbol})")

    col1, col2, col3 = st.columns(3)
    col1.metric("현재가", f"${price:,.2f}" if isinstance(price, (int, float)) else "N/A")
    col2.metric("시가총액", format_usd(market_cap))
    col3.metric("통화", currency)
    if market_cap is None:
        st.caption("시가총액·현재가는 FMP API 키가 있어야 표시됩니다 (SEC에는 주가 정보가 없습니다).")

    if rows:
        df = pd.DataFrame(rows)
        value_cols = VALUE_COLS

        df_display = df.copy()
        for col in value_cols:
            df_display[col] = df_display[col].apply(format_usd)

        st.markdown("### 최근 재무 지표")
        try:
            st.dataframe(df_display, width="stretch", hide_index=True)
        except TypeError:
            st.dataframe(df_display, use_container_width=True, hide_index=True)

        # ------------------------- 차트 -------------------------
        SHORT_LABELS = {
            VALUE_COLS[0]: "매출",
            VALUE_COLS[1]: "영업이익",
            VALUE_COLS[2]: "OCF",
            VALUE_COLS[3]: "FCF",
        }
        short_cols = [SHORT_LABELS[c] for c in value_cols]

        chart_df = df.copy()
        chart_df["기간"] = chart_df["기간"].astype(str)
        chart_df = chart_df.sort_values("기간")  # 오래된 기간 -> 최근 기간
        period_order = chart_df["기간"].tolist()
        period_kind = "annual" if used_period == "annual" else "quarter"

        unit_div, unit_label = pick_unit(chart_df[value_cols])

        long_df = chart_df.melt(
            id_vars="기간", value_vars=value_cols, var_name="지표", value_name="원값"
        )
        long_df["원값"] = pd.to_numeric(long_df["원값"], errors="coerce")
        long_df = long_df.dropna(subset=["원값"])
        long_df["지표"] = long_df["지표"].map(SHORT_LABELS)
        long_df["값"] = long_df["원값"] / unit_div
        long_df["금액"] = long_df["원값"].apply(format_usd)

        growth_df = compute_growth(long_df, period_order, period_kind)

        tooltip = [
            alt.Tooltip("기간:N", title="기간"),
            alt.Tooltip("지표:N", title="지표"),
            alt.Tooltip("금액:N", title="금액"),
        ]
        y_axis = alt.Axis(
            labelFontSize=12, titleFontSize=12, titleAngle=0,
            titleAlign="left", titleAnchor="start", titleY=-12, titleX=0,
        )
        label_angle = 0 if len(period_order) <= 8 else -45
        growth_note = "전년 동기(4분기 전) 대비" if period_kind == "quarter" else "전년 대비"

        st.markdown("### 추이 차트 (4개 지표 한눈에 비교)")
        st.caption(f"단위: {unit_label} · 막대에 마우스를 올리면 정확한 금액이 표시됩니다.")
        combined = (
            alt.Chart(long_df)
            .mark_bar(cornerRadiusEnd=6)
            .encode(
                x=alt.X(
                    "기간:N", sort=period_order, title=None,
                    axis=alt.Axis(labelAngle=label_angle, labelFontSize=14, labelPadding=10),
                    scale=alt.Scale(paddingInner=0.25),
                ),
                xOffset=alt.XOffset("지표:N", sort=short_cols, scale=alt.Scale(paddingInner=0.12)),
                y=alt.Y("값:Q", title=None, axis=alt.Axis(labelFontSize=12)),
                color=alt.Color(
                    "지표:N", sort=short_cols,
                    scale=alt.Scale(domain=short_cols, range=SERIES_COLORS),
                    legend=alt.Legend(
                        orient="top", title=None, labelFontSize=14,
                        symbolType="square", labelLimit=300,
                    ),
                ),
                tooltip=tooltip,
            )
            .properties(height=520)
            .configure_axis(grid=True, gridColor=GRID_COLOR, domain=False, tickColor=GRID_COLOR)
            .configure_view(stroke=None)
            .configure_legend(labelColor=LABEL_COLOR)
        )
        show_chart(combined)

        st.markdown("### 지표별 막대그래프 (성장률 선 포함)")
        st.caption(
            f"왼쪽 축 = 금액({unit_label}), 오른쪽 축 = {growth_note} "
            f"성장률(%, {GROWTH_MIN:.0f}~{GROWTH_MAX:.0f} 고정). "
            f"{GROWTH_MAX:.0f}%를 넘거나 {GROWTH_MIN:.0f}% 아래인 값은 경계선에 삼각형으로 표시되며, "
            "마우스를 올리면 실제 값이 나옵니다."
        )
        columns = st.columns(2)
        show_labels = len(period_order) <= 10  # 기간이 많으면 숫자 라벨은 생략
        for idx, (full_name, short_name) in enumerate(zip(value_cols, short_cols)):
            metric_df = long_df[long_df["지표"] == short_name]
            if metric_df.empty:
                continue

            metric_growth = growth_df[growth_df["지표"] == short_name] if not growth_df.empty else growth_df
            # FCF는 성장률 선 없이 막대만 표시
            has_growth = not metric_growth.empty and short_name != "FCF"

            # 막대 위 금액 라벨이 잘리지 않도록 위쪽 여백 확보
            metric_domain = None
            if show_labels:
                top = float(metric_df["값"].max())
                bottom = float(metric_df["값"].min())
                metric_domain = [min(0.0, bottom * 1.15), top * 1.18 if top > 0 else 0.0]

            bars = (
                alt.Chart(metric_df)
                .mark_bar(cornerRadiusEnd=6, color=SERIES_COLORS[idx])
                .encode(
                    x=alt.X(
                        "기간:N", sort=period_order, title=None,
                        axis=alt.Axis(labelAngle=label_angle, labelFontSize=13, labelPadding=8),
                        scale=alt.Scale(paddingInner=0.35),
                    ),
                    y=alt.Y(
                        "값:Q", title=unit_label, axis=y_axis,
                        scale=alt.Scale(domain=metric_domain) if metric_domain else alt.Undefined,
                    ),
                    tooltip=tooltip,
                )
            )
            layers = bars
            if show_labels:
                layers = bars + (
                    alt.Chart(metric_df)
                    .mark_text(dy=-14, fontSize=12, color=LABEL_COLOR)
                    .encode(
                        x=alt.X("기간:N", sort=period_order),
                        y=alt.Y("값:Q"),
                        text=alt.Text("금액:N"),
                    )
                )
            title = full_name
            if has_growth:
                # 성장률 선을 막대 위에 겹쳐 그린다 (오른쪽 축 = %)
                layers = alt.layer(layers, growth_overlay(metric_growth, period_order)).resolve_scale(
                    y="independent"
                )
                title = f"{full_name} · 선 = {growth_note} 성장률(%)"

            panel = (
                layers
                .properties(height=340, title=title)
                .properties(padding={"left": 5, "right": 38, "top": 8, "bottom": 5})
                .configure_axis(grid=True, gridColor=GRID_COLOR, domain=False, tickColor=GRID_COLOR)
                .configure_view(stroke=None)
                .configure_title(fontSize=15, anchor="start", color="#0b0b0b", offset=10)
            )
            with columns[idx % 2]:
                show_chart(panel)

    elif not errors:
        st.warning("해당 종목의 재무제표 데이터를 찾을 수 없습니다.")

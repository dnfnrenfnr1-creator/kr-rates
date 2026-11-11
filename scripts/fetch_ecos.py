"""한국은행 ECOS에서 한국 금리·환율 최근 30일치와 물가지수 최근 24개월치를 받아 ecos.json으로 저장."""
import json, os, sys, urllib.request, datetime as dt
from zoneinfo import ZoneInfo

KEY = os.environ["ECOS_KEY"]
SERIES = {
    "KR_BASE":  ("722Y001", "0101000"),
    "KR_CD91":  ("817Y002", "010502000"),
    "KR_3Y":    ("817Y002", "010200000"),
    "KR_10Y":   ("817Y002", "010210000"),
    "KR_AA3Y":  ("817Y002", "010300000"),
    "KR_BBB3Y": ("817Y002", "010320000"),
    "USDKRW":   ("731Y001", "0000001"),
}
today = dt.datetime.now(ZoneInfo("Asia/Seoul")).date()
start = (today - dt.timedelta(days=30)).strftime("%Y%m%d")
end = today.strftime("%Y%m%d")

rows, errors = {}, []
for col, (stat, item) in SERIES.items():
    url = f"https://ecos.bok.or.kr/api/StatisticSearch/{KEY}/json/kr/1/100/{stat}/D/{start}/{end}/{item}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            body = json.load(r)
        data = body.get("StatisticSearch", {}).get("row", [])
        if not data:
            errors.append(f"{col}: {body.get('RESULT', {}).get('MESSAGE', 'no rows')}")
        for x in data:
            t = x["TIME"]
            d = f"{t[:4]}-{t[4:6]}-{t[6:]}"
            v = x.get("DATA_VALUE")
            rows.setdefault(d, {"date": d})[col] = float(v) if v not in (None, "") else None
    except Exception as e:
        errors.append(f"{col}: {e}")

# 월별 물가지수 (2020=100)
MONTHLY = {
    "KR_CPI":  ("901Y009", "0"),     # 소비자물가 총지수
    "KR_CORE": ("901Y009", "QB"),    # 농산물및석유류제외
    "KR_PPI":  ("404Y014", "*AA"),   # 생산자물가 총지수
}
mstart = (today.replace(day=1) - dt.timedelta(days=730)).strftime("%Y%m")
mend = today.strftime("%Y%m")
mrows, merrors = {}, []
for col, (stat, item) in MONTHLY.items():
    url = f"https://ecos.bok.or.kr/api/StatisticSearch/{KEY}/json/kr/1/100/{stat}/M/{mstart}/{mend}/{item}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            body = json.load(r)
        data = body.get("StatisticSearch", {}).get("row", [])
        if not data:
            merrors.append(f"{col}: {body.get('RESULT', {}).get('MESSAGE', 'no rows')}")
        for x in data:
            t = x["TIME"]
            d = f"{t[:4]}-{t[4:6]}-01"
            v = x.get("DATA_VALUE")
            mrows.setdefault(d, {"date": d})[col] = float(v) if v not in (None, "") else None
    except Exception as e:
        merrors.append(f"{col}: {e}")
monthly = []
for d in sorted(mrows):
    for col in MONTHLY:
        mrows[d].setdefault(col, None)
    monthly.append(mrows[d])

out = []
for d in sorted(rows):
    r = rows[d]
    for col in SERIES:
        r.setdefault(col, None)
    out.append(r)

with open("ecos.json", "w", encoding="utf-8") as f:
    json.dump({"fetched_at": dt.datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="minutes"),
               "errors": errors + merrors, "rows": out, "monthly": monthly}, f, ensure_ascii=False, indent=1)
print(f"{len(out)} rows, {len(monthly)} monthly, errors: {errors + merrors}")
if len(errors) == len(SERIES):
    sys.exit(1)

"""한국은행 ECOS에서 한국 금리·환율 최근 30일치를 받아 ecos.json으로 저장."""
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

out = []
for d in sorted(rows):
    r = rows[d]
    for col in SERIES:
        r.setdefault(col, None)
    out.append(r)

with open("ecos.json", "w", encoding="utf-8") as f:
    json.dump({"fetched_at": dt.datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="minutes"),
               "errors": errors, "rows": out}, f, ensure_ascii=False, indent=1)
print(f"{len(out)} rows, errors: {errors}")
if len(errors) == len(SERIES):
    sys.exit(1)

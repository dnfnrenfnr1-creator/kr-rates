"""한국 월별 물가지수(ECOS)를 받아 prices.json으로 저장.

지수 레벨만 저장하고, 전년비·전월비는 대시보드에서 계산한다. (2020=100, 원계열)
- KR_CPI: 소비자물가 총지수 (901Y009 / 0)
- KR_CORE: 농산물및석유류제외지수 (901Y010 / QB)
- KR_PPI: 생산자물가 총지수 (404Y014 / *AA)
미국은 BLS·FRED가 GitHub 서버 접속을 막아서 DBnomics(BLS 원자료 미러)로 받는다. 계절조정.
- US_CPI: CUSR0000SA0, US_CORE: CUSR0000SA0L1E, US_PPI: WPSFD4(최종수요), US_PPI_CORE: WPSFD49104(식품·에너지 제외)
"""
import json, os, sys, urllib.request, datetime as dt
from zoneinfo import ZoneInfo

START = "2018-01"
KR = {"KR_CPI": ("901Y009", "0"), "KR_CORE": ("901Y010", "QB"), "KR_PPI": ("404Y014", "*AA")}
US = {"US_CPI": "BLS/cu/CUSR0000SA0", "US_CORE": "BLS/cu/CUSR0000SA0L1E", "US_PPI": "BLS/wp/WPSFD4", "US_PPI_CORE": "BLS/wp/WPSFD49104"}
COLS = list(US) + list(KR)

rows, errors = {}, []


def put(month, col, v):
    try:
        val = float(v)
    except (TypeError, ValueError):
        return
    rows.setdefault(month, {"month": month})[col] = val


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 kr-rates"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8")


for col, sid in US.items():
    try:
        body = json.loads(get(f"https://api.db.nomics.world/v22/series/{sid}?observations=1&format=json"))
        docs = body.get("series", {}).get("docs", [])
        if not docs:
            errors.append(f"{col}: no series"); continue
        n = 0
        for per, v in zip(docs[0].get("period", []), docs[0].get("value", [])):
            if per >= START and v not in (None, "NA"):
                put(per[:7], col, v); n += 1
        if not n:
            errors.append(f"{col}: no rows")
    except Exception as e:
        errors.append(f"{col}: {e}")

key = os.environ.get("ECOS_KEY")
end = dt.datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m")
for col, (stat, item) in KR.items():
    if not key:
        errors.append(f"{col}: no ECOS_KEY"); continue
    url = f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/1000/{stat}/M/{START.replace('-', '')}/{end}/{item}"
    try:
        body = json.loads(get(url))
        data = body.get("StatisticSearch", {}).get("row", [])
        if not data:
            errors.append(f"{col}: {body.get('RESULT', {}).get('MESSAGE', 'no rows')}")
        for x in data:
            t = x["TIME"]
            put(f"{t[:4]}-{t[4:6]}", col, x.get("DATA_VALUE"))
    except Exception as e:
        errors.append(f"{col}: {type(e).__name__}")  # URL에 키가 있으니 예외 문구는 남기지 않음

out = []
for m in sorted(rows):
    r = rows[m]
    for c in COLS:
        r.setdefault(c, None)
    out.append(r)

latest = {c: max((r["month"] for r in out if r[c] is not None), default=None) for c in COLS}
with open("prices.json", "w", encoding="utf-8") as f:
    json.dump({"fetched_at": dt.datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="minutes"),
               "errors": errors, "latest": latest, "rows": out}, f, ensure_ascii=False, indent=1)
print(f"{len(out)} months, latest: {latest}, errors: {errors}")
if len(errors) == len(COLS):
    sys.exit(1)

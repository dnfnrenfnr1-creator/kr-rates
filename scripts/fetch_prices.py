"""미국(FRED)·한국(ECOS) 월별 물가지수를 받아 prices.json으로 저장.

지수 레벨만 저장하고, 전년비·전월비는 대시보드에서 계산한다.
- 미국: CPI(CPIAUCSL), 근원 CPI(CPILFESL), PPI 최종수요(PPIFIS), 근원 PPI(PPIFES) — 계절조정
- 한국: 소비자물가 총지수, 농산물·석유류 제외(근원), 생산자물가 총지수 — 원계열
"""
import csv, io, json, os, sys, urllib.request, datetime as dt
from zoneinfo import ZoneInfo

START = "2018-01"
US = {"US_CPI": "CPIAUCSL", "US_CORE": "CPILFESL", "US_PPI": "PPIFIS", "US_PPI_CORE": "PPIFES"}
KR = {"KR_CPI": ("901Y009", "0"), "KR_CORE": ("901Y009", "QB"), "KR_PPI": ("404Y014", "*AA")}
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
        text = get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={START}-01")
        n = 0
        for r in csv.reader(io.StringIO(text)):
            if len(r) >= 2 and r[0][:4].isdigit():
                put(r[0][:7], col, r[1]); n += 1
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

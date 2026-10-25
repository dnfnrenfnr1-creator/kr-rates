"""미국(BLS)·한국(ECOS) 월별 물가지수를 받아 prices.json으로 저장.

지수 레벨만 저장하고, 전년비·전월비는 대시보드에서 계산한다.
- 미국(BLS API): CPI 전체(CUSR0000SA0), 근원 CPI(CUSR0000SA0L1E), PPI 최종수요(WPSFD4), 근원 PPI 식품·에너지 제외(WPSFD49104) — 계절조정
- 한국: 소비자물가 총지수, 농산물·석유류 제외(근원), 생산자물가 총지수 — 원계열
"""
import csv, io, json, os, sys, urllib.request, datetime as dt
from zoneinfo import ZoneInfo

START = "2018-01"
US = {"US_CPI": "CUSR0000SA0", "US_CORE": "CUSR0000SA0L1E", "US_PPI": "WPSFD4", "US_PPI_CORE": "WPSFD49104"}
KR = {"KR_CPI": ("901Y009", "0"), "KR_CORE": ("901Y009", None), "KR_PPI": ("404Y014", "*AA")}
CORE_NAME = "농산물및석유류제외"  # 901Y009 안에서 이 이름의 항목 코드를 찾아 씀
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


try:
    body = json.dumps({"seriesid": list(US.values()), "startyear": START[:4],
                       "endyear": str(dt.date.today().year)}).encode()
    req = urllib.request.Request("https://api.bls.gov/publicAPI/v1/timeseries/data/", data=body,
                                 headers={"Content-Type": "application/json", "User-Agent": "kr-rates"})
    with urllib.request.urlopen(req, timeout=60) as r:
        res = json.load(r)
    if res.get("status") != "REQUEST_SUCCEEDED":
        errors.append(f"BLS: {res.get('status')} {res.get('message')}")
    by_id = {s["seriesID"]: s.get("data", []) for s in res.get("Results", {}).get("series", [])}
    for col, sid in US.items():
        data = by_id.get(sid, [])
        if not data:
            errors.append(f"{col}: no rows")
        for x in data:
            if x.get("period", "").startswith("M") and x["period"] != "M13":
                put(f"{x['year']}-{x['period'][1:]}", col, x.get("value"))
except Exception as e:
    errors.append(f"BLS: {e}")

key = os.environ.get("ECOS_KEY")
end = dt.datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m")
for col, (stat, item) in KR.items():
    if not key:
        errors.append(f"{col}: no ECOS_KEY"); continue
    if item is None:
        try:
            lst = json.loads(get(f"https://ecos.bok.or.kr/api/StatisticItemList/{key}/json/kr/1/1000/{stat}"))
            for it in lst.get("StatisticItemList", {}).get("row", []):
                if CORE_NAME in it.get("ITEM_NAME", "").replace(" ", "") and it.get("CYCLE") in (None, "M"):
                    item = it["ITEM_CODE"]; break
        except Exception as e:
            errors.append(f"{col}: item lookup {type(e).__name__}")
        if item is None:
            errors.append(f"{col}: item code not found"); continue
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

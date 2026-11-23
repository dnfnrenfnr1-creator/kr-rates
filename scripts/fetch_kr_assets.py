"""국내 보유 종목 시세(한국투자증권 API)와 DART 사업보고서 요약을 받아 kr_assets.json으로 저장.

- 종목 목록: kr_tickers.txt (한 줄에 6자리 종목코드 하나, # 뒤는 주석)
  자산관리 현황판 입력판의 '국내 주식' 종목코드와 맞춰 둔다.
- 한국투자증권(실전투자): 현재가·전일대비·52주 고저·PER·PBR, 주간 종가(약 2년)
  접근토큰은 하루 1회 발급이 원칙이라, 같은 날 이미 받은 시세가 있으면 토큰을 새로 받지 않고 재사용한다.
- DART: 최근 사업보고서 주요계정(매출액·영업이익·당기순이익, 3개년), 최근 90일 공시 목록
  ETF처럼 DART 고유번호가 없는 종목은 재무·공시를 건너뛴다.
- ECOS: 원/달러 매매기준율(731Y001 / 0000001) 최근 영업일 값 — 현황판 달러 자산 원화 환산용
필요한 Secrets: KIS_APP_KEY, KIS_APP_SECRET, DART_KEY, ECOS_KEY
"""
import io, json, os, re, time, zipfile, urllib.request, urllib.parse, datetime as dt
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
NOW = dt.datetime.now(KST)
KIS = "https://openapi.koreainvestment.com:9443"
DART = "https://opendart.fss.or.kr/api"

errors = []
out = {"fetched_at": NOW.strftime("%Y-%m-%dT%H:%M+09:00"), "errors": errors,
       "quotes": [], "weekly": [], "financials": [], "disclosures": [], "fx": []}


def http(url, data=None, headers=None, timeout=40):
    h = {"User-Agent": "Mozilla/5.0 kr-rates"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def load_tickers():
    codes = []
    try:
        with open("kr_tickers.txt", encoding="utf-8") as f:
            for line in f:
                c = line.split("#", 1)[0].strip()
                if re.fullmatch(r"[0-9A-Z]{6}", c) and c not in codes:
                    codes.append(c)
    except FileNotFoundError:
        errors.append("kr_tickers.txt 없음")
    return codes


# ---------- 한국투자증권 ----------
def kis_token(key, secret):
    body = json.dumps({"grant_type": "client_credentials", "appkey": key, "appsecret": secret}).encode()
    res = json.loads(http(KIS + "/oauth2/tokenP", data=body, headers={"content-type": "application/json"}))
    if "access_token" not in res:
        raise RuntimeError(f"토큰 발급 실패: {res.get('error_description') or res}")
    return res["access_token"]


def kis_get(path, tr_id, params, token, key, secret):
    url = KIS + path + "?" + urllib.parse.urlencode(params)
    headers = {"content-type": "application/json; charset=utf-8", "authorization": f"Bearer {token}",
               "appkey": key, "appsecret": secret, "tr_id": tr_id, "custtype": "P"}
    res = json.loads(http(url, headers=headers))
    if res.get("rt_cd") not in (None, "0"):
        raise RuntimeError(res.get("msg1") or res.get("msg_cd") or "KIS 오류")
    time.sleep(0.15)  # 초당 호출 한도 여유
    return res


def reuse_today(codes):
    """오늘(한국시간) 이미 받은 KIS 시세가 있고 종목이 그대로면 재사용한다. 토큰을 하루 1번만 발급하기 위해서."""
    try:
        with open("kr_assets.json", encoding="utf-8") as f:
            prev = json.load(f)
    except Exception:
        return None
    if str(prev.get("kis_date") or "") != NOW.strftime("%Y-%m-%d"):
        return None
    have = {q.get("code") for q in prev.get("quotes") or []} | set(prev.get("kis_missing") or [])
    if not set(codes) <= have:
        return None
    return prev


def fetch_kis(codes):
    prev = reuse_today(codes)
    if prev is not None:
        out["quotes"] = [q for q in prev.get("quotes") or [] if q.get("code") in codes]
        out["weekly"] = [w for w in prev.get("weekly") or [] if w.get("code") in codes]
        out["kis_date"] = prev.get("kis_date")
        out["kis_missing"] = [c for c in prev.get("kis_missing") or [] if c in codes]
        out["kis_reused"] = True
        for c in out["kis_missing"]:
            errors.append(f"KIS 시세 {c}: 시세가 없어요(종목코드를 확인해 주세요. 영문 O와 숫자 0이 헷갈리기 쉬워요)")
        return {q["code"]: q.get("name") for q in out["quotes"]}
    key, secret = os.environ.get("KIS_APP_KEY"), os.environ.get("KIS_APP_SECRET")
    if not (key and secret):
        errors.append("KIS: KIS_APP_KEY / KIS_APP_SECRET 없음")
        return {}
    try:
        token = kis_token(key, secret)
    except Exception as e:
        errors.append(f"KIS: {e}")
        return {}
    out["kis_date"] = NOW.strftime("%Y-%m-%d")
    out["kis_missing"] = []
    names = {}
    start = (NOW - dt.timedelta(days=730)).strftime("%Y%m%d")
    end = NOW.strftime("%Y%m%d")
    for c in codes:
        try:
            ch = kis_get("/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice", "FHKST03010100",
                         {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": c, "FID_INPUT_DATE_1": start,
                          "FID_INPUT_DATE_2": end, "FID_PERIOD_DIV_CODE": "W", "FID_ORG_ADJ_PRC": "0"},
                         token, key, secret)
            o1 = ch.get("output1") or {}
            names[c] = (o1.get("hts_kor_isnm") or "").strip()
            for r in ch.get("output2") or []:
                d, cl = r.get("stck_bsop_date"), num(r.get("stck_clpr"))
                if d and cl:
                    out["weekly"].append({"code": c, "date": f"{d[:4]}-{d[4:6]}-{d[6:]}", "close": cl})
        except Exception as e:
            errors.append(f"KIS 주간 {c}: {e}")
        try:
            p = kis_get("/uapi/domestic-stock/v1/quotations/inquire-price", "FHKST01010100",
                        {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": c}, token, key, secret).get("output") or {}
            if not num(p.get("stck_prpr")) and not names.get(c):
                errors.append(f"KIS 시세 {c}: 시세가 없어요(종목코드를 확인해 주세요. 영문 O와 숫자 0이 헷갈리기 쉬워요)")
                out["kis_missing"].append(c)
                continue
            out["quotes"].append({
                "code": c, "name": names.get(c) or c, "price": num(p.get("stck_prpr")),
                "change": num(p.get("prdy_vrss")), "changePct": num(p.get("prdy_ctrt")),
                "hi52": num(p.get("w52_hgpr")), "lo52": num(p.get("w52_lwpr")),
                "per": num(p.get("per")), "pbr": num(p.get("pbr")),
                "marketCapEok": num(p.get("hts_avls")), "sector": (p.get("bstp_kor_isnm") or "").strip(),
                "date": NOW.strftime("%Y-%m-%d")})
        except Exception as e:
            errors.append(f"KIS 시세 {c}: {e}")
    out["weekly"].sort(key=lambda r: (r["code"], r["date"]))
    return names


# ---------- DART ----------
def dart_json(endpoint, key, **params):
    params["crtfc_key"] = key
    res = json.loads(http(f"{DART}/{endpoint}?" + urllib.parse.urlencode(params)))
    time.sleep(0.2)
    return res


def pick(items, names):
    for want in names:
        for it in items:
            nm = (it.get("account_nm") or "").replace(" ", "")
            if nm == want or nm.startswith(want):
                return it
    return None


def fetch_dart(codes, kis_names):
    key = os.environ.get("DART_KEY")
    if not key:
        errors.append("DART: DART_KEY 없음")
        return
    try:
        z = zipfile.ZipFile(io.BytesIO(http(f"{DART}/corpCode.xml?crtfc_key={key}", timeout=120)))
        root = ET.fromstring(z.read(z.namelist()[0]))
        corp = {}
        for el in root.iter("list"):
            sc = (el.findtext("stock_code") or "").strip()
            if sc:
                corp[sc] = ((el.findtext("corp_code") or "").strip(), (el.findtext("corp_name") or "").strip())
    except Exception as e:
        errors.append(f"DART 고유번호: {e}")
        return
    bgn = (NOW - dt.timedelta(days=90)).strftime("%Y%m%d")
    for c in codes:
        if c not in corp:
            continue  # ETF 등
        cc, cname = corp[c]
        # 최근 사업보고서(11011): 올해-1년 → 없으면 올해-2년
        for year in (NOW.year - 1, NOW.year - 2):
            try:
                res = dart_json("fnlttSinglAcnt.json", key, corp_code=cc, bsns_year=str(year), reprt_code="11011")
            except Exception as e:
                errors.append(f"DART 재무 {c}: {e}"); break
            if res.get("status") != "000":
                continue
            items = res.get("list") or []
            fs = [i for i in items if i.get("fs_div") == "CFS"] or [i for i in items if i.get("fs_div") == "OFS"]
            rev = pick(fs, ["매출액", "수익(매출액)", "영업수익", "매출"])
            op = pick(fs, ["영업이익"])
            net = pick(fs, ["당기순이익", "분기순이익", "반기순이익"])
            for k, label in (("thstrm_amount", 0), ("frmtrm_amount", 1), ("bfefrmtrm_amount", 2)):
                row = {"code": c, "name": cname, "year": str(year - label),
                       "fs": "연결" if fs and fs[0].get("fs_div") == "CFS" else "별도",
                       "revenue": num(rev.get(k)) if rev else None,
                       "operatingIncome": num(op.get(k)) if op else None,
                       "netIncome": num(net.get(k)) if net else None}
                if any(row[x] is not None for x in ("revenue", "operatingIncome", "netIncome")):
                    out["financials"].append(row)
            break
        try:
            res = dart_json("list.json", key, corp_code=cc, bgn_de=bgn, end_de=NOW.strftime("%Y%m%d"), page_count="10")
            for d in res.get("list") or [] if res.get("status") == "000" else []:
                r = d.get("rcept_dt") or ""
                out["disclosures"].append({"code": c, "name": cname, "date": f"{r[:4]}-{r[4:6]}-{r[6:]}",
                                           "title": (d.get("report_nm") or "").strip(), "rceptNo": d.get("rcept_no")})
        except Exception as e:
            errors.append(f"DART 공시 {c}: {e}")
    out["financials"].sort(key=lambda r: (r["code"], r["year"]))


# ---------- ECOS 원/달러 ----------
def fetch_fx():
    key = os.environ.get("ECOS_KEY")
    if not key:
        errors.append("ECOS: ECOS_KEY 없음")
        return
    start = (NOW - dt.timedelta(days=20)).strftime("%Y%m%d")
    url = f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/40/731Y001/D/{start}/{NOW.strftime('%Y%m%d')}/0000001"
    try:
        body = json.loads(http(url))
        rows = body.get("StatisticSearch", {}).get("row", [])
        if not rows:
            errors.append(f"ECOS 환율: {body.get('RESULT', {}).get('MESSAGE') or '데이터 없음'}")
        for r in rows:
            t, v = r.get("TIME") or "", num(r.get("DATA_VALUE"))
            if len(t) == 8 and v:
                out["fx"].append({"date": f"{t[:4]}-{t[4:6]}-{t[6:]}", "usdkrw": v})
        out["fx"].sort(key=lambda r: r["date"])
    except Exception as e:
        errors.append(f"ECOS 환율: {e}")


codes = load_tickers()
out["secrets_seen"] = {k: bool(os.environ.get(k)) for k in ("KIS_APP_KEY", "KIS_APP_SECRET", "DART_KEY", "ECOS_KEY")}
fetch_fx()
out["codes"] = codes
if codes:
    names = fetch_kis(codes)
    fetch_dart(codes, names)
with open("kr_assets.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print(f"환율 {len(out['fx'])}일, 종목 {len(codes)}개, 시세 {len(out['quotes'])}, 주간 {len(out['weekly'])}, 재무 {len(out['financials'])}, 공시 {len(out['disclosures'])}, 오류 {len(errors)}")
for e in errors:
    print("  -", e)

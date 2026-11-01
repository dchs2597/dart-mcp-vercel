"""OpenDART API 호출 모듈. 도구 함수는 모두 dict를 반환한다."""
import datetime as dt
import gzip
import html as _html
import io
import json
import os
import re
import zipfile
import xml.etree.ElementTree as ET

import requests

API = "https://opendart.fss.or.kr/api/"
HERE = os.path.dirname(os.path.abspath(__file__))
BUNDLED = os.path.join(os.path.dirname(HERE), "data", "corpcodes.json.gz")
TMP = os.environ.get("DART_CACHE_DIR", "/tmp/dart-cache")

REPRT = {"11011": "사업보고서", "11012": "반기보고서", "11013": "1분기보고서", "11014": "3분기보고서"}
SJ = {"BS": "재무상태표", "IS": "손익계산서", "CIS": "포괄손익계산서", "CF": "현금흐름표", "SCE": "자본변동표"}
REPORT_API = {
    "조건부자본증권미상환": "cndlCaplScritsNrdmpBlce", "미등기임원보수": "unrstExctvMendngSttus",
    "회사채미상환": "cprndNrdmpBlce", "단기사채미상환": "srtpdPsndbtNrdmpBlce", "기업어음미상환": "entrprsBilScritsNrdmpBlce",
    "채무증권발행": "detScritsIsuAcmslt", "사모자금사용": "prvsrpCptalUseDtls", "공모자금사용": "pssrpCptalUseDtls",
    "임원전체보수승인": "drctrAdtAllMendngSttusGmtsckConfmAmount", "임원전체보수유형": "drctrAdtAllMendngSttusMendngPymntamtTyCl",
    "주식총수": "stockTotqySttus", "회계감사": "accnutAdtorNmNdAdtOpinion", "감사용역": "adtServcCnclsSttus",
    "회계감사용역계약": "accnutAdtorNonAdtServcCnclsSttus", "사외이사": "outcmpnyDrctrNdChangeSttus",
    "신종자본증권미상환": "newCaplScritsNrdmpBlce", "증자": "irdsSttus", "배당": "alotMatter", "자기주식": "tesstkAcqsDspsSttus",
    "최대주주": "hyslrSttus", "최대주주변동": "hyslrChgSttus", "소액주주": "mrhlSttus", "임원": "exctvSttus", "직원": "empSttus",
    "임원개인보수": "hmvAuditIndvdlBySttus", "임원전체보수": "hmvAuditAllSttus", "개인별보수": "indvdlByPay", "타법인출자": "otrCprInvstmntSttus",
}
EVENT_API = {
    "부도발생": "dfOcr", "영업정지": "bsnSp", "회생절차": "ctrcvsBgrq", "해산사유": "dsRsOcr", "유상증자": "piicDecsn",
    "무상증자": "fricDecsn", "유무상증자": "pifricDecsn", "감자": "crDecsn", "관리절차개시": "bnkMngtPcbg", "소송": "lwstLg",
    "해외상장결정": "ovLstDecsn", "해외상장폐지결정": "ovDlstDecsn", "해외상장": "ovLst", "해외상장폐지": "ovDlst",
    "전환사채발행": "cvbdIsDecsn", "신주인수권부사채발행": "bdwtIsDecsn", "교환사채발행": "exbdIsDecsn", "관리절차중단": "bnkMngtPcsp",
    "조건부자본증권발행": "wdCocobdIsDecsn", "자산양수도": "astInhtrfEtcPtbkOpt", "타법인증권양도": "otcprStkInvscrTrfDecsn",
    "유형자산양도": "tgastTrfDecsn", "유형자산양수": "tgastInhDecsn", "타법인증권양수": "otcprStkInvscrInhDecsn",
    "영업양도": "bsnTrfDecsn", "영업양수": "bsnInhDecsn", "자기주식취득신탁계약해지": "tsstkAqTrctrCcDecsn",
    "자기주식취득신탁계약체결": "tsstkAqTrctrCnsDecsn", "자기주식처분": "tsstkDpDecsn", "자기주식취득": "tsstkAqDecsn",
    "주식교환": "stkExtrDecsn", "회사분할합병": "cmpDvmgDecsn", "회사분할": "cmpDvDecsn", "회사합병": "cmpMgDecsn",
    "사채권양수": "stkrtbdInhDecsn", "사채권양도결정": "stkrtbdTrfDecsn",
}
KINDS = {"A": "정기공시", "B": "주요사항보고", "C": "발행공시", "D": "지분공시", "E": "기타공시",
         "F": "외부감사관련", "G": "펀드공시", "H": "자산유동화", "I": "거래소공시", "J": "공정위공시"}


class DartError(Exception):
    pass


def _key():
    k = os.environ.get("DART_API_KEY", "").strip()
    if not k:
        raise DartError("서버에 DART_API_KEY 환경변수가 설정되지 않았습니다.")
    return k


def _get(path, **params):
    r = requests.get(API + path, params={"crtfc_key": _key(), **params}, timeout=25)
    r.raise_for_status()
    return r


# ---- 회사 고유번호 목록 ---------------------------------------------------
_corp = None  # list of [corp_code, corp_name, stock_code, modify_date]


def _download_corp_codes():
    z = zipfile.ZipFile(io.BytesIO(_get("corpCode.xml").content))
    root = ET.fromstring(z.read(z.namelist()[0]))
    rows = []
    for el in root.findall("list"):
        d = {c.tag: (c.text or "").strip() for c in el}
        rows.append([d.get("corp_code", ""), d.get("corp_name", ""), d.get("stock_code", ""), d.get("modify_date", "")])
    if len(rows) < 1000:  # 샘플 응답(키 오류)이면 버린다
        raise DartError("회사 목록을 받지 못했습니다. DART_API_KEY가 등록된 키인지 확인하세요.")
    return rows


def _load_bundled():
    with gzip.open(BUNDLED, "rt", encoding="utf-8") as f:
        return json.load(f)


def corp_codes(refresh=False):
    """우선순위: 메모리 → /tmp 캐시 → 내장 목록(data/corpcodes.json.gz) → DART 다운로드.
    refresh=True 이면 DART에서 새로 내려받아 /tmp 캐시를 갱신한다."""
    global _corp
    if _corp is not None and not refresh:
        return _corp
    os.makedirs(TMP, exist_ok=True)
    cache = os.path.join(TMP, "corpcodes.json")
    if not refresh:
        if os.path.exists(cache):
            _corp = json.load(open(cache, encoding="utf-8"))
            return _corp
        if os.path.exists(BUNDLED):
            _corp = _load_bundled()
            return _corp
    try:
        _corp = _download_corp_codes()
        json.dump(_corp, open(cache, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        if _corp is None:
            if os.path.exists(BUNDLED):
                _corp = _load_bundled()
            else:
                raise
    return _corp


def _find(rows, corp):
    corp = str(corp).strip()
    if corp.isdigit() and len(corp) == 6:
        return [r for r in rows if r[2] == corp]
    hit = [r for r in rows if r[1] == corp]
    if not hit:
        hit = [r for r in rows if corp in r[1] and r[2]]
    return hit


def resolve(corp):
    corp = str(corp).strip()
    if corp.isdigit() and len(corp) == 8:
        return corp
    hit = _find(corp_codes(), corp)
    if not hit:
        hit = _find(corp_codes(refresh=True), corp)
    if not hit:
        raise DartError(f"'{corp}' 회사를 찾지 못했습니다. search_company로 정확한 법인명 또는 고유번호를 확인하세요.")
    return hit[0][0]


def _row(r):
    return {"corp_code": r[0], "corp_name": r[1], "stock_code": r[2], "modify_date": r[3]}


# ---- 도구 함수 -------------------------------------------------------------

def search_company(query: str, listed_only: bool = False):
    q = str(query).strip()
    rows = corp_codes()
    if q.isdigit() and len(q) == 6:
        hit = [r for r in rows if r[2] == q]
    else:
        hit = [r for r in rows if q in r[1]]
    if listed_only:
        hit = [r for r in hit if r[2]]
    hit.sort(key=lambda r: (r[2] == "", r[1] != q, r[3]))
    out = {"count": len(hit), "rows": [_row(r) for r in hit[:40]]}
    if not hit:
        out["message"] = "검색 결과가 없습니다. 법인명 전체(예: '삼성전자', '주식회사' 제외)로 다시 시도하세요."
    return out


def get_company_overview(corp: str):
    d = _get("company.json", corp_code=resolve(corp)).json()
    if str(d.get("status")) != "000":
        raise DartError(f"조회 실패: {d}")
    d.pop("status", None); d.pop("message", None)
    return d


def get_financial_statement(corp: str, year, reprt_code="11011", sj_div="ALL", fs_div="AUTO"):
    reprt_code = str(reprt_code)
    if reprt_code not in REPRT:
        raise DartError(f"reprt_code는 {list(REPRT)} 중 하나여야 합니다.")
    code = resolve(corp)
    order = ["CFS", "OFS"] if fs_div.upper() == "AUTO" else [fs_div.upper()]
    rows, used, d = [], None, {}
    for fs in order:
        d = _get("fnlttSinglAcntAll.json", corp_code=code, bsns_year=str(year), reprt_code=reprt_code, fs_div=fs).json()
        rows = d.get("list", [])
        if rows:
            used = fs
            break
    if not rows:
        return {"count": 0, "rows": [], "corp_code": code,
                "message": f"재무제표 없음 (status {d.get('status')}: {d.get('message')}). 상장사·2015년 이후만 제공됩니다."}
    sj = sj_div.upper()
    if sj != "ALL":
        sel = [r for r in rows if r["sj_div"] == sj]
        if not sel and sj == "IS":
            sj, sel = "CIS", [r for r in rows if r["sj_div"] == "CIS"]
        rows = sel
    keep = ["sj_div", "account_nm", "thstrm_nm", "thstrm_amount", "thstrm_add_amount",
            "frmtrm_nm", "frmtrm_amount", "bfefrmtrm_amount"]
    return {"corp_code": code, "year": str(year), "reprt_code": reprt_code, "reprt_name": REPRT[reprt_code],
            "fs_div": used, "fs_name": "연결재무제표" if used == "CFS" else "별도재무제표", "sj_div": sj, "unit": "원(KRW)",
            "count": len(rows), "rows": [{k: r.get(k) for k in keep if r.get(k) not in (None, "")} for r in rows]}


def get_business_report_item(corp: str, item: str, year, reprt_code="11011"):
    if item not in REPORT_API:
        raise DartError(f"item은 다음 중 하나여야 합니다: {', '.join(REPORT_API)}")
    reprt_code = str(reprt_code)
    if reprt_code not in REPRT:
        raise DartError(f"reprt_code는 {list(REPRT)} 중 하나여야 합니다.")
    code = resolve(corp)
    d = _get(REPORT_API[item] + ".json", corp_code=code, bsns_year=str(year), reprt_code=reprt_code).json()
    rows = d.get("list", [])
    out = {"corp_code": code, "item": item, "year": str(year), "reprt_code": reprt_code, "count": len(rows), "rows": rows[:200]}
    if not rows:
        out["message"] = f"데이터 없음 (status {d.get('status')}: {d.get('message')}). 연도나 보고서 종류를 바꿔 보세요."
    return out


def _dates(start, end):
    end = (end or "").replace("-", "") or dt.date.today().strftime("%Y%m%d")
    start = (start or "").replace("-", "") or (dt.date.today() - dt.timedelta(days=365)).strftime("%Y%m%d")
    return start, end


def get_major_events(corp: str, event: str, start="", end=""):
    if event not in EVENT_API:
        raise DartError(f"event는 다음 중 하나여야 합니다: {', '.join(EVENT_API)}")
    code = resolve(corp)
    start, end = _dates(start, end)
    d = _get(EVENT_API[event] + ".json", corp_code=code, bgn_de=start, end_de=end).json()
    rows = d.get("list", [])
    out = {"corp_code": code, "event": event, "start": start, "end": end, "count": len(rows), "rows": rows[:200]}
    if not rows:
        out["message"] = f"해당 기간에 보고된 건이 없습니다 (status {d.get('status')})."
    return out


def list_disclosures(corp="", start="", end="", kind="", final_only=True, page=1):
    start, end = _dates(start, end)
    p = dict(bgn_de=start, end_de=end, page_count=100, page_no=int(page), last_reprt_at="Y" if final_only else "N")
    if str(corp).strip():
        p["corp_code"] = resolve(corp)
    if kind:
        p["pblntf_ty"] = kind
    d = _get("list.json", **p).json()
    keep = ["rcept_no", "rcept_dt", "corp_name", "corp_code", "stock_code", "corp_cls", "report_nm", "flr_nm", "rm"]
    rows = d.get("list", [])
    out = {"start": start, "end": end, "kind": KINDS.get(kind, "전체"), "total_count": d.get("total_count"),
           "page": int(page), "total_page": d.get("total_page"), "rows": [{k: r.get(k) for k in keep} for r in rows]}
    if not rows:
        out["message"] = f"해당 조건의 공시가 없습니다 (status {d.get('status')}: {d.get('message')})."
    return out


def get_disclosure_text(rcept_no: str, max_chars=20000, offset=0):
    z = zipfile.ZipFile(io.BytesIO(_get("document.xml", rcept_no=str(rcept_no).strip()).content))
    raw = z.read(z.namelist()[0])
    try:
        html = raw.decode("utf-8")
    except UnicodeDecodeError:
        html = raw.decode("euc-kr", errors="ignore")
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    t = re.sub(r"<br\s*/?>|</p>|</tr>|</div>|</title>", "\n", t, flags=re.I)
    t = re.sub(r"</t[dh]>", "\t", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = _html.unescape(t).replace("&cr;", " ")
    t = re.sub(r"[ \t ]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t).strip()
    max_chars = max(1000, min(int(max_chars), 60000))
    offset = max(0, int(offset))
    chunk = t[offset: offset + max_chars]
    return {"rcept_no": rcept_no, "total_chars": len(t), "offset": offset, "returned_chars": len(chunk),
            "has_more": offset + max_chars < len(t), "text": chunk,
            "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"}


def list_dart_codes():
    return {"reprt_code": REPRT, "sj_div": SJ, "business_report_items": list(REPORT_API),
            "major_events": list(EVENT_API), "disclosure_kinds": KINDS}


def check_status():
    try:
        d = _get("company.json", corp_code="00126380").json()
        ok = str(d.get("status")) == "000"
        n = len(corp_codes())
        return {"ok": ok and n > 1000, "dart_status": d.get("status"), "message": d.get("message"),
                "companies_loaded": n, "note": "" if n > 1000 else "회사 목록이 샘플뿐입니다. 키가 등록된 키인지 확인하세요."}
    except Exception as e:
        return {"ok": False, "message": str(e)}

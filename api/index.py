"""DART MCP 원격 서버 — MCP Streamable HTTP(무상태, JSON 응답) 구현.

엔드포인트: POST https://<배포주소>/mcp/<MCP_SECRET>
환경변수:  DART_API_KEY (DART 오픈API 키), MCP_SECRET (URL 비밀 경로)
"""
import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dart_core as dc  # noqa: E402

SERVER_INFO = {"name": "dart-mcp", "version": "0.2.0"}
PROTOCOL_DEFAULT = "2025-06-18"
INSTRUCTIONS = (
    "금융감독원 전자공시시스템(DART) 조회 도구. 회사명이 불확실하면 search_company로 corp_code를 먼저 확인한다. "
    "재무제표는 연결(CFS) 우선, 없으면 별도(OFS). 금액은 원(KRW) 단위이므로 사용자에게는 억·조 원으로 환산해 단위를 밝힌다. "
    "숫자마다 보고서 종류·사업연도·연결/별도 기준을 함께 적는다."
)

CORP = {"type": "string", "description": "8자리 고유번호(corp_code), 정확한 법인명, 또는 6자리 종목코드"}
REPRT = {"type": "string", "default": "11011", "enum": list(dc.REPRT),
         "description": "11011=사업보고서(연간), 11012=반기, 11013=1분기, 11014=3분기"}
YEAR = {"type": "string", "description": "사업연도 YYYY (2015년 이후)"}

TOOLS = [
    {"name": "check_dart_status", "description": "서버의 DART API 키 상태와 회사 목록 적재 여부를 확인한다.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "search_company", "description": "회사명(일부 가능)이나 6자리 종목코드로 DART 고유번호(corp_code)를 찾는다. 결과의 corp_code를 다른 도구에 넘긴다.",
     "inputSchema": {"type": "object", "required": ["query"], "properties": {
         "query": {"type": "string", "description": "회사명 일부, 정확한 법인명, 또는 6자리 종목코드"},
         "listed_only": {"type": "boolean", "default": False, "description": "상장사만 반환"}}}},
    {"name": "get_company_overview", "description": "기업 개황(대표자, 설립일, 주소, 업종코드, 결산월, 상장구분 corp_cls: Y=유가 K=코스닥 N=코넥스 E=기타).",
     "inputSchema": {"type": "object", "required": ["corp"], "properties": {"corp": CORP}}},
    {"name": "get_financial_statement", "description": "상장사 재무제표 전체 계정. 연결 우선, 없으면 별도. 손익계산서(IS)가 없으면 포괄손익계산서(CIS)로 자동 전환. 금액 단위 원. thstrm=당기, frmtrm=전기.",
     "inputSchema": {"type": "object", "required": ["corp", "year"], "properties": {
         "corp": CORP, "year": YEAR, "reprt_code": REPRT,
         "sj_div": {"type": "string", "default": "ALL", "enum": ["ALL", "BS", "IS", "CIS", "CF", "SCE"],
                    "description": "BS=재무상태표, IS=손익계산서, CIS=포괄손익계산서, CF=현금흐름표, SCE=자본변동표, ALL=전체"},
         "fs_div": {"type": "string", "default": "AUTO", "enum": ["AUTO", "CFS", "OFS"], "description": "CFS=연결, OFS=별도, AUTO=연결 우선"}}}},
    {"name": "get_business_report_item", "description": "사업보고서 항목 조회 — 배당, 최대주주, 최대주주변동, 소액주주, 임원, 직원, 증자, 자기주식, 타법인출자, 회계감사, 주식총수 등 28종 (전체 목록은 list_dart_codes).",
     "inputSchema": {"type": "object", "required": ["corp", "item", "year"], "properties": {
         "corp": CORP, "item": {"type": "string", "enum": list(dc.REPORT_API), "description": "조회 항목"}, "year": YEAR, "reprt_code": REPRT}}},
    {"name": "get_major_events", "description": "주요사항보고서 조회 — 유상증자, 무상증자, 전환사채발행, 신주인수권부사채발행, 회사합병, 회사분할, 영업양수도, 자기주식취득, 소송 등 36종. 기간 생략 시 최근 1년.",
     "inputSchema": {"type": "object", "required": ["corp", "event"], "properties": {
         "corp": CORP, "event": {"type": "string", "enum": list(dc.EVENT_API), "description": "주요사항 종류"},
         "start": {"type": "string", "description": "시작일 YYYYMMDD"}, "end": {"type": "string", "description": "종료일 YYYYMMDD"}}}},
    {"name": "list_disclosures", "description": "공시 목록(접수번호 rcept_no, 보고서명, 제출인, 접수일). 원문은 rcept_no로 get_disclosure_text 호출. 기간 생략 시 최근 1년, 페이지당 100건.",
     "inputSchema": {"type": "object", "properties": {
         "corp": {"type": "string", "description": "고유번호·법인명·종목코드. 비우면 전체 회사"},
         "start": {"type": "string", "description": "시작일 YYYYMMDD"}, "end": {"type": "string", "description": "종료일 YYYYMMDD"},
         "kind": {"type": "string", "enum": ["", "A", "B", "C", "D", "E", "F", "G", "H", "I", "J"],
                  "description": "A=정기공시 B=주요사항보고 C=발행공시 D=지분공시 E=기타 F=외부감사 G=펀드 H=자산유동화 I=거래소 J=공정위. 비우면 전체"},
         "final_only": {"type": "boolean", "default": True, "description": "정정 전 보고서 제외"},
         "page": {"type": "integer", "default": 1, "description": "페이지 번호"}}}},
    {"name": "get_disclosure_text", "description": "공시 원문을 텍스트로 읽는다. 긴 문서는 offset을 늘려 나눠 읽는다.",
     "inputSchema": {"type": "object", "required": ["rcept_no"], "properties": {
         "rcept_no": {"type": "string", "description": "14자리 접수번호"},
         "max_chars": {"type": "integer", "default": 20000}, "offset": {"type": "integer", "default": 0}}}},
    {"name": "list_dart_codes", "description": "이 서버가 받는 코드 목록(보고서 코드, 재무제표 구분, 사업보고서 항목, 주요사항 종류, 공시 유형).",
     "inputSchema": {"type": "object", "properties": {}}},
]

HANDLERS = {
    "check_dart_status": lambda a: dc.check_status(),
    "search_company": lambda a: dc.search_company(a["query"], bool(a.get("listed_only", False))),
    "get_company_overview": lambda a: dc.get_company_overview(a["corp"]),
    "get_financial_statement": lambda a: dc.get_financial_statement(
        a["corp"], a["year"], a.get("reprt_code", "11011"), a.get("sj_div", "ALL"), a.get("fs_div", "AUTO")),
    "get_business_report_item": lambda a: dc.get_business_report_item(a["corp"], a["item"], a["year"], a.get("reprt_code", "11011")),
    "get_major_events": lambda a: dc.get_major_events(a["corp"], a["event"], a.get("start", ""), a.get("end", "")),
    "list_disclosures": lambda a: dc.list_disclosures(a.get("corp", ""), a.get("start", ""), a.get("end", ""),
                                                      a.get("kind", ""), bool(a.get("final_only", True)), a.get("page", 1)),
    "get_disclosure_text": lambda a: dc.get_disclosure_text(a["rcept_no"], a.get("max_chars", 20000), a.get("offset", 0)),
    "list_dart_codes": lambda a: dc.list_dart_codes(),
}


def _rpc_result(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _rpc_error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def handle_message(msg):
    """JSON-RPC 메시지 하나를 처리한다. 알림(id 없음)은 None을 돌려준다."""
    method = msg.get("method")
    req_id = msg.get("id")
    params = msg.get("params") or {}
    if req_id is None:  # notification
        return None
    if method == "initialize":
        return _rpc_result(req_id, {
            "protocolVersion": params.get("protocolVersion") or PROTOCOL_DEFAULT,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": INSTRUCTIONS,
        })
    if method == "ping":
        return _rpc_result(req_id, {})
    if method == "tools/list":
        return _rpc_result(req_id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        fn = HANDLERS.get(name)
        if fn is None:
            return _rpc_error(req_id, -32602, f"Unknown tool: {name}")
        try:
            data = fn(args)
            text = json.dumps(data, ensure_ascii=False, indent=1)
            return _rpc_result(req_id, {"content": [{"type": "text", "text": text}], "isError": False})
        except dc.DartError as e:
            return _rpc_result(req_id, {"content": [{"type": "text", "text": str(e)}], "isError": True})
        except Exception as e:
            traceback.print_exc()
            return _rpc_result(req_id, {"content": [{"type": "text", "text": f"서버 오류: {type(e).__name__}: {e}"}], "isError": True})
    if method in ("resources/list", "prompts/list"):
        key = method.split("/")[0]
        return _rpc_result(req_id, {key: []})
    return _rpc_error(req_id, -32601, f"Method not found: {method}")


def _authorized(path, query):
    secret = os.environ.get("MCP_SECRET", "").strip()
    if not secret:
        return True  # 비밀 경로 미설정 시 개방 (권장하지 않음)
    return ("/" + secret) in path or query.get("k", [""])[0] == secret


class handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, status, body=b"", ctype="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if body else ""))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _route(self):
        u = urlparse(self.path)
        return u.path, parse_qs(u.query)

    def do_GET(self):
        path, query = self._route()
        if path.startswith("/.well-known/"):
            return self._send(404, b'{"error":"not found"}')
        if not _authorized(path, query):
            return self._send(404, b'{"error":"not found"}')
        if path.rstrip("/").endswith("/health"):
            return self._send(200, json.dumps(dc.check_status(), ensure_ascii=False).encode("utf-8"))
        # Streamable HTTP의 GET(SSE 스트림)은 지원하지 않는다 → 405
        body = json.dumps({"server": SERVER_INFO, "note": "MCP endpoint: send JSON-RPC via POST"}).encode("utf-8")
        return self._send(405 if "mcp" in path else 200, body)

    def do_DELETE(self):
        return self._send(200, b"")

    def do_POST(self):
        path, query = self._route()
        if not _authorized(path, query):
            return self._send(404, b'{"error":"not found"}')
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8") or "null")
        except Exception:
            return self._send(400, json.dumps(_rpc_error(None, -32700, "Parse error")).encode("utf-8"))
        msgs = payload if isinstance(payload, list) else [payload]
        if not all(isinstance(m, dict) for m in msgs):
            return self._send(400, json.dumps(_rpc_error(None, -32600, "Invalid request")).encode("utf-8"))
        responses = [r for r in (handle_message(m) for m in msgs) if r is not None]
        if not responses:  # 알림만 들어온 경우
            return self._send(202, b"")
        out = responses if isinstance(payload, list) else responses[0]
        return self._send(200, json.dumps(out, ensure_ascii=False).encode("utf-8"))

    def log_message(self, fmt, *args):  # Vercel 로그로 보냄
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


if __name__ == "__main__":  # 로컬 테스트: python3 api/index.py 8787
    from http.server import ThreadingHTTPServer
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    print(f"listening on http://127.0.0.1:{port}/mcp/<MCP_SECRET>", file=sys.stderr)
    ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()

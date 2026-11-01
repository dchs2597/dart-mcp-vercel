# dart-mcp-remote — DART 전자공시 MCP 서버 (claude.ai 커스텀 커넥터용)

금융감독원 OpenDART API를 claude.ai 웹·모바일·데스크톱 어디서나 쓰기 위한 원격 MCP 서버. Vercel 무료 플랜에서 동작하며 DART API 키는 Vercel 환경변수에만 저장된다.

## 1. 배포 (약 2분)

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2Fdchs2597%2Fdart-mcp-remote&env=DART_API_KEY,MCP_SECRET&envDescription=DART_API_KEY%3A%20opendart.fss.or.kr%20%EC%9D%B8%EC%A6%9D%ED%82%A4%2C%20MCP_SECRET%3A%20URL%20%EB%B9%84%EB%B0%80%20%EA%B2%BD%EB%A1%9C%EC%9A%A9%20%EC%9E%84%EC%9D%98%20%EB%AC%B8%EC%9E%90%EC%97%B4&project-name=dart-mcp&repository-name=dart-mcp-remote)

1. 위 버튼 → GitHub로 Vercel 로그인(무료 Hobby) → 저장소 복제
2. 환경변수 입력
   - `DART_API_KEY`: opendart.fss.or.kr → 오픈API → 인증키 신청/관리 → 인증키 관리 탭의 40자 키
   - `MCP_SECRET`: URL에 붙일 비밀 문자열(영문·숫자 20자 이상, 아무 값이나). 이 값을 모르는 사람은 서버를 쓸 수 없다.
3. Deploy → 완료되면 주소가 `https://dart-mcp-xxxx.vercel.app` 형태로 나온다.
4. 확인: 브라우저에서 `https://<주소>/mcp/<MCP_SECRET>/health` 를 열어 `"ok": true, "companies_loaded": 119879` 가 보이면 정상.

## 2. claude.ai 커넥터 등록

설정 → 커넥터 → **커스텀 커넥터 추가**

- 이름: `DART`
- 원격 MCP 서버 URL: `https://<주소>/mcp/<MCP_SECRET>`
- OAuth 항목은 비워 둔다(인증 없음, URL 비밀 경로로 보호).

등록 후 새 대화에서 "루닛 2024년 사업보고서 연결 손익계산서 보여줘" 같은 요청이 바로 처리된다.

## 도구

| 도구 | 기능 |
|---|---|
| `check_dart_status` | 키 상태·회사 목록 적재 확인 |
| `search_company` | 회사명·종목코드 → 고유번호(corp_code) |
| `get_company_overview` | 기업 개황 |
| `get_financial_statement` | 재무제표 (연결 우선, IS 없으면 CIS 자동 전환) |
| `get_business_report_item` | 사업보고서 항목 28종 (배당, 최대주주, 임원·직원, 증자, 자기주식, 타법인출자 등) |
| `get_major_events` | 주요사항보고 36종 (유상증자, CB·BW 발행, 합병·분할, 영업양수도, 자기주식 등) |
| `list_disclosures` | 공시 목록 (접수번호, 보고서명, 접수일) |
| `get_disclosure_text` | 공시 원문 텍스트 (offset 분할) |
| `list_dart_codes` | 코드 목록 |

## 구조

- `api/index.py` — MCP Streamable HTTP(무상태·JSON 응답) 서버. 의존성은 `requests`뿐.
- `api/dart_core.py` — OpenDART API 호출.
- `data/corpcodes.json.gz` — 회사 고유번호 목록 스냅샷(119,879개). 콜드 스타트 때 즉시 로드하고, 검색이 비면 DART에서 새로 내려받아 갱신한다.
- `vercel.json` — 서울 리전(icn1), 모든 경로를 `api/index`로 라우팅, 함수 제한 60초.

## 로컬 실행

```bash
pip install requests
DART_API_KEY=<키> MCP_SECRET=test python3 api/index.py 8787
curl http://127.0.0.1:8787/mcp/test/health
```

## 보안

- 키는 환경변수에만 있다. 저장소에는 키가 없다.
- URL 비밀 경로(`MCP_SECRET`)를 모르면 404만 받는다. 노출됐다고 판단되면 Vercel 환경변수를 바꾸고 재배포한 뒤 커넥터 URL을 갱신한다.
- DART 오픈API는 키당 일 20,000건 한도가 있다.

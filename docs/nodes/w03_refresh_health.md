# W03 — Data Refresh + Health

상태: FROZEN (2026-09-11 전체 사전 승인)
버전: 1.0

## 책임
- `POST /api/datasets/refresh` `{hub: "LPHB-30260", crt_by: "demo"|"all"}` → 워커 스레드에서 Node 00 `scripts/extract_lmd.main` 실행(읽기 전용 SELECT) → 새 폴더 `data/private/lmd_<hub>_<crt_by>/`. 같은 hub의 기존 데이터셋에 `distance_truth.csv`가 있으면 복사 (hub→zip 실측은 hub 단위)
- `GET /api/refresh/{job_id}` → `{status: queued|running|done|error, dataset?, rows?, error?}`
- `GET /api/health` 확장: `db: {ok: bool, latency_ms|error}` (SELECT 1, 3초 타임아웃, 30초 캐시), `valhalla`, `datasets`
- 프론트: 헬스 줄에 db 상태, Dataset 옆 "Refresh from QA DB" 버튼(crt_by 선택) → 완료 시 목록 갱신

## 승인 기준 (테스트)
1. 추출 함수를 stub으로 바꿔 refresh → done, 새 데이터셋이 `/api/datasets`에 나타남, truth 복사됨
2. stub이 예외 → status error + 메시지
3. `/api/health`에 db 키 존재 (연결 실패 시 ok=false, 앱은 정상)

## 알려진 한계 (ponytail)
- 자격증명은 Node 00과 동일 경로(JDAext yml 또는 env). 웹에서 입력받지 않음
- 동시 refresh 1건

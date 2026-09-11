# Node 10 — Optimization

상태: FROZEN (2026-09-10 승인)
버전: 1.0
의존성 추가: `ortools` (CP-SAT). 운영 최적화 전용. 네트워크 설계는 Pyomo+HiGHS (POC 외).

## 책임
Node 09가 `pending`으로 넘긴 규칙을 실행한다. POC는 **Shipment Consolidation** 1종.

`consolidate(ds, window)`:
1. lane 그룹 = (origin.key, dest.key, carrier_id, mode)
2. 그룹 내 ship_date 정렬. 가장 이른 미처리 shipment부터 `days` 이내를 하나의 윈도우로 자름 (greedy, 겹침 없음)
3. 윈도우 내 bin packing: 용량 `max_weight_lb`, 목표 bin 수 최소. CP-SAT. 단일 shipment이거나 총중량 ≤ 용량이면 solver 생략
4. 단일 shipment 중량 > 용량 → 자기 bin, `oversize` 기록
5. 멤버 2개 이상인 bin → 통합 Shipment. id `CONS-0001…`, weight/actual_cost/pieces/pallets 합(pieces·pallets는 전부 있을 때만), ship_date = 멤버 최소, deliver_date = 멤버 최대(있으면), origin/dest/carrier/mode/service_level 첫 멤버, source_row 첫 멤버. 멤버 1개 bin은 원본 유지
6. 순서: 원본 shipments 순서를 유지하되 통합 shipment는 첫 멤버 위치

## 비책임
- Load Building(3D/팔레트), Carrier Assignment → POC 외. 같은 모듈에 함수 추가로 확장
- 재요율 → Node 12. 통합 shipment의 `actual_cost`는 멤버 합계(비교 기준 유지)

## Interface

```python
from tmod.optimization import consolidate, optimize, pack_bins, ConsolidationReport

def pack_bins(weights: Sequence[int], capacity: int, time_limit_s: float = 5.0) -> list[list[int]]   # index 리스트의 bin 목록, 최적 또는 시간 내 최선

@dataclass(frozen=True)
class ConsolidationReport:
    shipments_before: int
    shipments_after: int
    bins: tuple[tuple[str, tuple[str, ...]], ...]    # (cons_id, member shipment ids), 멤버 2개 이상만
    oversize: tuple[str, ...]                        # 용량 초과 단일 shipment id
    solver_calls: int
    solver_optimal: int                              # OPTIMAL 상태 수 (나머지는 FEASIBLE)

def consolidate(ds: Dataset, window: ConsolidationWindow, time_limit_s: float = 5.0) -> tuple[Dataset, ConsolidationReport]
def optimize(ds: Dataset, pending: Sequence[Rule], time_limit_s: float = 5.0) -> tuple[Dataset, tuple[ConsolidationReport, ...]]   # pending 규칙 순서대로 실행
```

`Dataset.locations`, `rates`, `named_locations` 불변.

## 승인 기준 (테스트)
1. `pack_bins([6,5,4,3,2], 10)` → 2 bins (합 20, 최적)
2. `pack_bins` 각 bin 합 ≤ 용량, 모든 index 정확히 1회
3. 같은 lane 3일 내 3건(중량 합 ≤ cap) → 1건으로 통합, weight/actual_cost 합, ship_date 최소
4. 윈도우 밖(days 초과) shipment는 별도
5. 다른 carrier/lane은 통합 안 됨
6. oversize 단일 shipment 유지 + 기록
7. pieces 일부 None → 통합 pieces None
8. `optimize`가 pending 순서 실행, 빈 pending → 원본 그대로

## 알려진 한계 (ponytail)
- 윈도우 greedy 절단. 윈도우 경계 최적화(날짜 이동 허용)는 서비스 제약 데이터 나오면.
- 용량은 중량만. cube/pallet 제약은 필드 채워진 데이터 확보 시 CP-SAT 제약 한 줄 추가.
- 윈도우당 shipment 수백 건이면 CP-SAT 시간 제한에 걸려 FEASIBLE 반환. `solver_optimal`로 감지.

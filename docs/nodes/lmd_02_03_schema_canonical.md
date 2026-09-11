# LMD Node 02/03 — Schema + Canonical (`tmod/lmd.py`)

상태: FROZEN (2026-09-11 승인)
버전: 1.0
기존 Node 02(`validate`)·03은 FROZEN 그대로. 이 모듈은 LMD 전용 스키마 상수와 캐노니컬 빌더를 추가한다.

## 책임
- `LMD_SCHEMAS`: Node 02 `TableSchema`로 표현한 LMD 테이블 4종. `validate(tables, schemas=LMD_SCHEMAS)`로 검증 (기존 함수 재사용)
- `build_lmd(tables, report) -> LmdDataset`: rejected 행 제외, ship_to × appt_dt 단위 **Stop**으로 집계
- `to_dataset(lmd) -> Dataset` / `apply_geocoded(lmd, ds) -> LmdDataset`: Node 04/05를 무변경 재사용하기 위한 어댑터. hub→stop pseudo-Shipment (actual_cost 0, carrier = truck 또는 "UNASSIGNED")

## 스키마 (`LMD_SCHEMAS`)
| 테이블 | 필수 컬럼 | 선택 | 규칙 |
|--------|-----------|------|------|
| shipments | shipment_id(unique), hub_cd, ship_to_id, req_capa_min(int≥0), status_cd | appt_dt(date), zip_cd, lat, lon, zone_cd, charge_min, stop_base_min, install_min, tot_wgt, tot_cuft, item_cnt, load_id, appt_truck_id, appt_window, svc_tier, order_type, addr_line | any_of zip_cd \| lat+lon. **FK 없음**: 실 데이터에 pool 트럭 `'1'`(마스터 외) 100건 존재 → Node 08에서 마스터 외 truck_id는 POOL로 취급 |
| trucks | truck_id(unique), daily_work_min(int), daily_duty_min(int) | shift_start_hh, shift_end_hh, active_yn, truck_type | |
| zone_zip (선택) | zip_from, zip_to, zone_cd | match_priority(int) | |
| params (선택) | param_cd, param_val | | |

alias: `zip→zip_cd`, `truck_id→appt_truck_id`(shipments), `work_min→daily_work_min`, `duty_min→daily_duty_min`.

## Interface
```python
from tmod.lmd import LMD_SCHEMAS, build_lmd, to_dataset, apply_geocoded, LmdDataset, Stop, Truck

@dataclass(frozen=True)
class Stop:
    id: str                       # f"{ship_to_id}@{appt_dt}[#{load_id}]" (appt_dt 없으면 @none)
    ship_to_id: str
    appt_dt: date | None
    location: Location            # zip / lat / lon (Node 03 Location 재사용)
    zone: str | None
    service_min: int              # stop_base(1회) + Σ charge_min
    capa_min_sum: int             # Σ req_capa_min (엔진 수치와 대사용)
    shipments: tuple[str, ...]
    load_id: str | None
    truck_id: str | None
    window: str | None            # "08:00-12:00"
    status: str                   # 멤버 중 최대 rung 상태
    weight_lb: Decimal
    cuft: Decimal
    pieces: int | None

@dataclass(frozen=True)
class Truck:
    id: str
    work_min: int
    duty_min: int
    shift_start: str | None
    shift_end: str | None

@dataclass(frozen=True)
class LmdDataset:
    hub_cd: str
    hub: Location                 # zip = hub_cd 뒤 5자리 또는 params HUB_ZIP
    stops: tuple[Stop, ...]
    trucks: tuple[Truck, ...]
    params: dict[str, str]
    zone_ranges: tuple[tuple[str, str, str], ...]   # (zip_from, zip_to, zone_cd), 좁은 범위 우선, 동률이면 match_priority 높은 것 (실 데이터 ZONE_CD 548건과 대사 검증)
    def zone_of(self, zip: str) -> str | None
    def by_day(self) -> dict[date | None, tuple[Stop, ...]]
    def baseline_loads(self) -> dict[str, tuple[Stop, ...]]      # load_id → stops (load_id 있는 것만)

def build_lmd(tables: dict[str, RawTable], report: ValidationReport, stop_base_min: int | None = None) -> LmdDataset
def to_dataset(lmd: LmdDataset) -> Dataset          # Node 04/05용 pseudo shipments (id = stop.id, origin=hub, dest=stop.location)
def apply_geocoded(lmd: LmdDataset, ds: Dataset) -> LmdDataset   # ds.shipments의 origin/dest 좌표를 hub/stops에 반영
```

## 규칙
- Stop 그룹 키 = (ship_to_id, appt_dt, load_id). 같은 ship_to·같은 날이라도 엔진이 다른 load로 나눴으면 다른 Stop (실 데이터 8건). id = `ship_to@date#load_id`
- service_min = `stop_base_min`(params STOP_BASE_MIN, 인자로 override) 1회 + Σ charge_min. 멤버 중 zip/zone/load/truck/window 불일치 시 첫 멤버 값 사용 + `Issue` 대신 ValueError? → **아니오**: 첫 멤버 값 채택, 불일치 건수는 `build_lmd` 로그 없이 무시 (demo 데이터에서 0건 확인 후 확정)
- status: 멤버 중 `rung` 최대. rung 순서 REQUESTED(1) < SEND_TO_OPT/SOFT_ALLOC(2) < OPTIMIZED(3) < HARD_CONSUME(4) < IN_TRANSIT(5) < COMPLETED/RETURN(6)
- shipments 또는 trucks에 MISSING_TABLE/COLUMN → ValueError

## 승인 기준 (테스트)
1. 소형 fixture: 5 shipments(2 ship_to 같은 날, 1 ship_to 다른 날, 1 좌표만, 1 rejected) → Stop 4개, service_min 계산 정확, rejected 제외
2. `validate(..., LMD_SCHEMAS)`: 마스터 외 truck_id도 통과 (pool). trucks 테이블 누락 → ValueError
3. `zone_of("30310") == "Z1"` (범위 30301–30318), 범위 밖 None, 겹치는 좁은 범위(30318 단독 Z2) 우선
4. `to_dataset` → `normalize` → `geocode` → `apply_geocoded`: hub·stop lat/lon 채워짐 (ZCTA 30260, 30309)
5. `baseline_loads` load_id별 stop 묶음, `by_day` 키 = appt_dt
6. 실 추출 데이터(`data/private/lmd_lphb30260_demo`) 있으면: 548→Stop 수, load 68개, 트럭 10대. 없으면 skip

## 알려진 한계 (ponytail)
- Stop 순서(STOP_SEQ) 없음 → Node 08에서 최근접 규칙
- 다중 hub 미지원. hub_cd 1개 가정, 다르면 ValueError

# Node 11 — Simulation

상태: FROZEN (2026-09-10 승인)
버전: 1.0 (POC stub — pass-through)

## 책임
시나리오 Dataset에 동적 이벤트(출발 지연, 용량 제약, 도착 변동)를 적용해 서비스 KPI(리드타임, 지연 건수)를 산출한다. **POC는 인터페이스만 고정하고 pass-through.** SimPy 의존성은 실 구현 시 추가.

POC 동작: shipments 불변. `Route.minutes`(Node 06)로 결정적 transit 추정만 계산해 `deliver_date`가 비어 있는 shipment에 채운다. ship_date + ceil(minutes / (drive_hours_per_day × 60)) 일.

## 비책임
- 확률적 이벤트, 큐잉, 용량 제약 → 실 구현 (SimPy)
- 비용 → Node 12

## Interface

```python
from tmod.simulation import simulate, SimConfig, SimReport

@dataclass(frozen=True)
class SimConfig:
    drive_hours_per_day: float = 11.0    # HOS 기준
    seed: int = 0                        # 실 구현용, POC 미사용

@dataclass(frozen=True)
class SimReport:
    shipments: int
    transit_days_filled: int             # deliver_date를 채운 건수
    avg_transit_days: float              # matrix에 route 있는 shipment 기준
    engine: str                          # "deterministic-stub" | 향후 "simpy"

def simulate(ds: Dataset, matrix: RouteMatrix, config: SimConfig = SimConfig()) -> tuple[Dataset, SimReport]
```

## 승인 기준 (테스트)
1. deliver_date 있는 shipment 유지, 없는 shipment는 ship_date + transit days
2. 1,320분(22h) / 11h/day → 2일. 0분 → 1일 최소
3. route 없는 shipment는 deliver_date None 유지, avg 계산에서 제외
4. rates/locations 불변, engine == "deterministic-stub"

## 알려진 한계 (ponytail)
- 결정적 stub. SimPy 구현은 Node 13 서비스 KPI가 확률 분포를 요구할 때. contract 2.0에서 `SimReport`에 분포 필드 추가, `simulate` 시그니처 유지.

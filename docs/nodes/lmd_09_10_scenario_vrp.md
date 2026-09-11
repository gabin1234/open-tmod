# LMD Node 09/10 — Scenario + VRP Optimization (`tmod/lmd_optimize.py`)

상태: FROZEN (2026-09-11 사전 승인)
버전: 1.0
의존성: ortools (Node 10에서 이미 도입). **Routing solver는 stop 순서·트럭 배정(운영 최적화)에만 사용. 도로 거리는 Node 06 Provider.**

## Node 09 — Scenario 규칙
```python
@dataclass(frozen=True)
class LmdScenario:
    name: str
    trucks: int | None = None          # None = 마스터 대수(10). 트럭 대수 what-if
    work_min: int | None = None        # 작업 한도 override (기본 마스터/params 500)
    duty_min: int | None = None        # 근무 한도 override (기본 600)
    stop_pool: str = "baseline"        # "baseline" = LOAD_ID 있는 stop만 (공정 비교) | "all" = SOFT_ALLOC 포함 전부
    zone_penalty_min: int = 0          # 다른 zone stop으로 이동 시 가산 분 (0 = zone 무시, soft 제약)
    time_limit_s: float = 5.0          # 일별 solver 상한
```
JSON 로드: `load_lmd_scenario(path)` (키 = 필드명).

## Node 10 — 일별 VRP
- 단위: appt_dt 하루. depot = hub, node = Stop. 거리·시간 = Node 08 `_Dist`(Provider 체인) 캐시
- 차원: `duty` (transit = drive_min(i→j) + service_min(j), 상한 duty_min), `work` (transit = service_min(j), 상한 work_min)
- 목표: 차량 고정비(대수 최소) → arc 비용 = miles×100 (+ zone_penalty). 라우팅 불가 stop은 disjunction penalty로 drop → `unrouted`
- 탐색: PATH_CHEAPEST_ARC + GUIDED_LOCAL_SEARCH, time limit = min(time_limit_s, 1 + 0.3×stop수)
- 결과 load_id = `OPT-{day}-{k}`, truck_id = 마스터 k번째 트럭 id. Node 08 `evaluate_loads`로 재평가 → 동일 KPI

## Interface
```python
from tmod.lmd_optimize import LmdScenario, load_lmd_scenario, optimize, optimize_day, OptimizeReport

@dataclass(frozen=True)
class OptimizeReport:
    days: int; stops: int; routed: int; unrouted: tuple[str, ...]; loads: int
    solver_status: dict[str, int]      # "solved" | "no_solution" 일수

def optimize_day(lmd, stops: Sequence[Stop], providers, scenario) -> tuple[dict[str, tuple[Stop, ...]], tuple[str, ...]]   # (loads, unrouted ids)
def optimize(lmd, providers, scenario) -> tuple[dict[str, tuple[Stop, ...]], OptimizeReport]
```

## 승인 기준 (테스트)
1. 격자 stop 6개, 트럭 1대 duty 부족 → 2대로 전부 라우팅, 각 load duty ≤ 한도 (evaluate_loads로 재검증)
2. 트럭 1대·duty 충분 → load 1개
3. stop 1개가 duty 한도 초과(service > duty) → unrouted에 기록, 나머지 라우팅
4. zone_penalty_min > 0 → 같은 zone끼리 묶임 (2 zone × 2 stop, 트럭 2대)
5. 실 데이터(skip-if-missing): 27일 전부 solved, baseline 175 stop 전부 routed, 총 duty 초과 0

## 알려진 한계 (ponytail)
- 시간창·shift 시각 미반영 (모두 08–12). 필요 시 time dimension에 window 추가 한 줄
- 하루 단위 독립 최적화. 날짜 이동(RAD 재조정)은 Suggest 엔진 영역

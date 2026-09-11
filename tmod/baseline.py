"""Node 08 Baseline: pipeline 01-07 + gap vs actual_cost + knob calibration. Contract: docs/nodes/08_baseline.md"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Sequence

from tmod.address import normalize
from tmod.canonical import Dataset, build
from tmod.geocoding import ZipCentroidGeocoder, geocode
from tmod.ingestion import ingest
from tmod.rating import RatedCost, rate_all
from tmod.routing import HaversineProvider, RouteMatrix, RoutingProvider, route_matrix
from tmod.validation import validate


@dataclass(frozen=True)
class Knobs:
    circuity: float = 1.2
    mph: float = 50.0
    cwt_round_up: bool = False


DEFAULT_GRID = tuple(Knobs(circuity=round(1.10 + 0.05 * i, 2), cwt_round_up=r) for i in range(7) for r in (False, True))


@dataclass(frozen=True)
class BaselineResult:
    knobs: Knobs
    rated: tuple[RatedCost, ...]
    matrix: RouteMatrix
    total_model: Decimal
    total_actual: Decimal
    gap_pct: float
    by_carrier: dict[str, tuple[Decimal, Decimal, float]]
    unrated: tuple[tuple[str, str], ...]
    unrated_pct: float
    within_tolerance: bool

    @property
    def carrier_abs_error(self) -> Decimal:
        """Sum of |model - actual| per carrier. Calibration objective: offsetting errors do not cancel."""
        return sum((abs(m - a) for m, a, _ in self.by_carrier.values()), Decimal(0))

    def summary(self) -> str:
        lines = [f"knobs: {self.knobs}",
                 f"rated {len(self.rated)}, unrated {len(self.unrated)} ({self.unrated_pct:.1f}%)",
                 f"model {self.total_model:,.2f} vs actual {self.total_actual:,.2f}  gap {self.gap_pct:+.2f}%  "
                 f"{'WITHIN' if self.within_tolerance else 'OUTSIDE'} tolerance"]
        for c, (m, a, g) in sorted(self.by_carrier.items()):
            lines.append(f"  {c}: model {m:,.2f} actual {a:,.2f} gap {g:+.2f}%")
        return "\n".join(lines)


def _gap(model: Decimal, actual: Decimal) -> float:
    return float((model - actual) / actual * 100) if actual else float("inf")


def prepare(files: dict[str, str | Path]) -> tuple[Dataset, dict[str, str]]:
    tables = ingest(files)
    rep = validate(tables)
    ds = build(tables, rep)
    ds, arep = normalize(ds)
    ds, grep = geocode(ds, [ZipCentroidGeocoder()])
    return ds, {"validation": rep.summary(),
                "address": f"{len(arep.issues)} issues, locations {arep.locations_before}->{arep.locations_after}",
                "geocode": f"{grep.by_precision}, ungeocoded {len(grep.ungeocoded)}"}


def evaluate(ds: Dataset, knobs: Knobs = Knobs(), providers: Sequence[RoutingProvider] | None = None,
             tolerance: float = 2.0) -> BaselineResult:
    providers = providers or [HaversineProvider(knobs.circuity, knobs.mph)]
    matrix, _ = route_matrix(ds, providers)
    rated, rrep = rate_all(ds, matrix, knobs.cwt_round_up)
    actual_by_id = {s.id: s.actual_cost for s in ds.shipments}
    total_actual = sum((actual_by_id[r.shipment_id] for r in rated), Decimal(0))
    per: dict[str, list[Decimal]] = {}
    for r in rated:
        acc = per.setdefault(r.carrier_id, [Decimal(0), Decimal(0)])
        acc[0] += r.total
        acc[1] += actual_by_id[r.shipment_id]
    by_carrier = {c: (m, a, _gap(m, a)) for c, (m, a) in per.items()}
    gap = _gap(rrep.total, total_actual)
    return BaselineResult(knobs, rated, matrix, rrep.total, total_actual, gap, by_carrier, rrep.unrated,
                          len(rrep.unrated) / len(ds.shipments) * 100 if ds.shipments else 0.0, abs(gap) <= tolerance)


def calibrate(ds: Dataset, grid: Iterable[Knobs] = DEFAULT_GRID, tolerance: float = 2.0) -> BaselineResult:
    return min((evaluate(ds, k, tolerance=tolerance) for k in grid), key=lambda r: r.carrier_abs_error)


def run_baseline(files: dict[str, str | Path], knobs: Knobs | None = None, tolerance: float = 2.0
                 ) -> tuple[BaselineResult, dict[str, str]]:
    ds, reports = prepare(files)
    res = evaluate(ds, knobs, tolerance=tolerance) if knobs else calibrate(ds, tolerance=tolerance)
    return res, reports


def save_knobs(path: str | Path, knobs: Knobs) -> None:
    Path(path).write_text(json.dumps(asdict(knobs), indent=1))


def load_knobs(path: str | Path) -> Knobs:
    return Knobs(**json.loads(Path(path).read_text()))


if __name__ == "__main__":
    folder = Path(sys.argv[1])
    kpath = Path(sys.argv[sys.argv.index("--knobs") + 1]) if "--knobs" in sys.argv else folder / "baseline_knobs.json"
    knobs = load_knobs(kpath) if kpath.exists() else None
    res, reports = run_baseline({"shipments": folder / "shipments.csv", "rates": folder / "rates.csv"}, knobs)
    for k, v in reports.items():
        print(f"[{k}] {v}")
    print(res.summary())
    if knobs is None:
        save_knobs(kpath, res.knobs)
        print(f"saved knobs -> {kpath}")

"""LMD track Node 02/03: schema constants + canonical LmdDataset. Contract: docs/nodes/lmd_02_03_schema_canonical.md"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from tmod.canonical import Dataset, Location, Shipment
from tmod.ingestion import RawTable
from tmod.validation import Column, TableSchema, ValidationReport, parse_date, parse_decimal, parse_int

ZERO = Decimal(0)
LMD_SCHEMAS: dict[str, TableSchema] = {
    "shipments": TableSchema(
        "shipments",
        (Column("shipment_id", required=True), Column("hub_cd", required=True), Column("ship_to_id", required=True),
         Column("req_capa_min", "int", required=True, min=ZERO), Column("status_cd", required=True),
         Column("appt_dt", "date"), Column("zip_cd"), Column("lat", "lat"), Column("lon", "lon"), Column("zone_cd"),
         Column("charge_min", "int", min=ZERO), Column("stop_base_min", "int", min=ZERO), Column("install_min", "int", min=ZERO),
         Column("tot_wgt", "decimal", min=ZERO), Column("tot_cuft", "decimal", min=ZERO), Column("item_cnt", "int", min=ZERO),
         Column("load_id"), Column("appt_truck_id"), Column("appt_window"), Column("svc_tier"), Column("order_type"), Column("addr_line")),
        any_of=((("zip_cd",), ("lat", "lon")),),
        unique=("shipment_id",),
        aliases={"zip": "zip_cd", "truck_id": "appt_truck_id"},
    ),
    "trucks": TableSchema(
        "trucks",
        (Column("truck_id", required=True), Column("daily_work_min", "int", required=True, min=ZERO),
         Column("daily_duty_min", "int", required=True, min=ZERO), Column("shift_start_hh"), Column("shift_end_hh"),
         Column("active_yn"), Column("truck_type")),
        unique=("truck_id",),
        aliases={"work_min": "daily_work_min", "duty_min": "daily_duty_min"},
    ),
    "zone_zip": TableSchema("zone_zip", (Column("zip_from", required=True), Column("zip_to", required=True),
                                         Column("zone_cd", required=True), Column("match_priority", "int")), required=False),
    "params": TableSchema("params", (Column("param_cd", required=True), Column("param_val")), required=False),
}

RUNG = {"REQUESTED": 1, "SEND_TO_OPT": 2, "SOFT_ALLOC": 2, "OPTIMIZED": 3, "HARD_CONSUME": 4, "IN_TRANSIT": 5,
        "COMPLETED": 6, "RETURN": 6}


@dataclass(frozen=True)
class Stop:
    id: str
    ship_to_id: str
    appt_dt: date | None
    location: Location
    zone: str | None
    service_min: int
    capa_min_sum: int
    shipments: tuple[str, ...]
    load_id: str | None
    truck_id: str | None
    window: str | None
    status: str
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
    hub: Location
    stops: tuple[Stop, ...]
    trucks: tuple[Truck, ...]
    params: dict[str, str]
    zone_ranges: tuple[tuple[str, str, str], ...]

    def zone_of(self, zip_: str) -> str | None:
        return next((z for lo, hi, z in self.zone_ranges if lo <= zip_ <= hi), None)

    def by_day(self) -> dict[date | None, tuple[Stop, ...]]:
        out: dict[date | None, list[Stop]] = {}
        for s in self.stops:
            out.setdefault(s.appt_dt, []).append(s)
        return {k: tuple(v) for k, v in out.items()}

    def baseline_loads(self) -> dict[str, tuple[Stop, ...]]:
        out: dict[str, list[Stop]] = {}
        for s in self.stops:
            if s.load_id:
                out.setdefault(s.load_id, []).append(s)
        return {k: tuple(v) for k, v in out.items()}


def _rows(name: str, tables: dict[str, RawTable], report: ValidationReport):
    fatal = [f for f in report.findings if f.table == name and f.code in ("MISSING_TABLE", "MISSING_COLUMN")]
    if fatal:
        raise ValueError(f"{name}: {fatal[0].code} {fatal[0].column or ''}".strip())
    if name not in tables:
        return
    m = report.mapping[name]
    rejected = report.rejected.get(name, frozenset())
    for row in tables[name].rows:
        if row["_row"] not in rejected:
            yield lambda c, r=row: r[m[c]].strip() if c in m else ""


def _float(s: str) -> float | None:
    d = parse_decimal(s)
    return None if d is None else float(d)


def build_lmd(tables: dict[str, RawTable], report: ValidationReport, stop_base_min: int | None = None) -> LmdDataset:
    params = {g("param_cd"): g("param_val") for g in _rows("params", tables, report)}
    base = stop_base_min if stop_base_min is not None else int(params.get("STOP_BASE_MIN", "20"))
    # most specific first: narrower range, then higher match_priority (verified against stored ZONE_CD, 548 rows)
    zones = tuple((lo, hi, z) for _, _, lo, hi, z in sorted(
        (int(g("zip_to")) - int(g("zip_from")) if g("zip_to").isdigit() and g("zip_from").isdigit() else 0,
         -(parse_int(g("match_priority")) or 0), g("zip_from"), g("zip_to"), g("zone_cd")) for g in _rows("zone_zip", tables, report)))
    trucks = tuple(Truck(g("truck_id"), parse_int(g("daily_work_min")), parse_int(g("daily_duty_min")),
                         g("shift_start_hh") or None, g("shift_end_hh") or None) for g in _rows("trucks", tables, report))

    groups: dict[tuple[str, date | None, str], list] = {}
    hubs: set[str] = set()
    for g in _rows("shipments", tables, report):
        hubs.add(g("hub_cd"))
        groups.setdefault((g("ship_to_id"), parse_date(g("appt_dt")), g("load_id")), []).append(g)
    if len(hubs) != 1:
        raise ValueError(f"expected exactly one hub_cd, got {sorted(hubs)}")
    hub_cd = hubs.pop()
    hub_zip = params.get("HUB_ZIP") or (hub_cd[-5:] if hub_cd[-5:].isdigit() else None)

    stops = []
    for (ship_to, day, load), gs in groups.items():
        f = gs[0]
        stops.append(Stop(
            id=f"{ship_to}@{day.isoformat() if day else 'none'}" + (f"#{load}" if load else ""), ship_to_id=ship_to, appt_dt=day,
            location=Location(zip=f("zip_cd") or None, address=f("addr_line") or None, lat=_float(f("lat")), lon=_float(f("lon"))),
            zone=f("zone_cd") or None,
            service_min=base + sum(parse_int(g("charge_min")) or 0 for g in gs),
            capa_min_sum=sum(parse_int(g("req_capa_min")) or 0 for g in gs),
            shipments=tuple(g("shipment_id") for g in gs),
            load_id=f("load_id") or None, truck_id=f("appt_truck_id") or None, window=f("appt_window") or None,
            status=max((g("status_cd") for g in gs), key=lambda s: RUNG.get(s, 0)),
            weight_lb=sum((parse_decimal(g("tot_wgt")) or ZERO for g in gs), ZERO),
            cuft=sum((parse_decimal(g("tot_cuft")) or ZERO for g in gs), ZERO),
            pieces=sum(parse_int(g("item_cnt")) or 0 for g in gs) or None,
        ))
    return LmdDataset(hub_cd, Location(zip=hub_zip), tuple(stops), trucks, params, zones)


def to_dataset(lmd: LmdDataset) -> Dataset:
    """Pseudo shipments hub->stop so Node 04/05 run unchanged."""
    ships = tuple(Shipment(s.id, s.appt_dt or date(1970, 1, 1), s.truck_id or "UNASSIGNED", s.weight_lb, ZERO, lmd.hub,
                           s.location, s.status, None, None, s.pieces, None, i) for i, s in enumerate(lmd.stops))
    uniq: dict[str, Location] = {}
    for sh in ships:
        uniq.setdefault(sh.origin.key, sh.origin)
        uniq.setdefault(sh.dest.key, sh.dest)
    return Dataset(ships, (), tuple(uniq.values()), {})


def apply_geocoded(lmd: LmdDataset, ds: Dataset) -> LmdDataset:
    by_id = {sh.id: sh for sh in ds.shipments}
    hub = next(iter(ds.shipments)).origin if ds.shipments else lmd.hub
    stops = tuple(replace(s, location=by_id[s.id].dest) if s.id in by_id else s for s in lmd.stops)
    return replace(lmd, hub=hub, stops=stops)

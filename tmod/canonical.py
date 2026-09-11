"""Node 03 Canonical Model: RawTable + ValidationReport -> Dataset.

Contract: docs/nodes/03_canonical.md
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from tmod.ingestion import RawTable
from tmod.validation import ValidationReport, parse_date, parse_decimal, parse_int


@dataclass(frozen=True)
class Location:
    zip: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    lat: float | None = None
    lon: float | None = None

    @property
    def key(self) -> str:
        if self.lat is not None and self.lon is not None:
            return f"ll:{self.lat:.5f},{self.lon:.5f}"
        if self.zip:
            return f"zip:{self.zip}"
        return f"addr:{(self.address or '').lower()}"


@dataclass(frozen=True)
class Shipment:
    id: str
    ship_date: date
    carrier_id: str
    weight_lb: Decimal
    actual_cost: Decimal
    origin: Location
    dest: Location
    mode: str | None
    service_level: str | None
    deliver_date: date | None
    pieces: int | None
    pallets: int | None
    source_row: int


@dataclass(frozen=True)
class RateCard:
    carrier_id: str
    rate_type: str
    rate: Decimal
    min_charge: Decimal | None
    fuel_pct: Decimal | None
    mode: str | None
    source_row: int


@dataclass(frozen=True)
class Dataset:
    shipments: tuple[Shipment, ...]
    rates: tuple[RateCard, ...]
    locations: tuple[Location, ...]
    named_locations: dict[str, Location]

    @property
    def total_actual_cost(self) -> Decimal:
        return sum((s.actual_cost for s in self.shipments), Decimal(0))


def _rows(name: str, tables: dict[str, RawTable], report: ValidationReport):
    """Yield (source_row, getter) for accepted rows. getter(col) -> stripped str or ''."""
    fatal = [f for f in report.findings
             if f.table == name and f.code in ("MISSING_TABLE", "MISSING_COLUMN")]
    if fatal:
        raise ValueError(f"{name}: {fatal[0].code} {fatal[0].column or ''}".strip())
    m = report.mapping[name]
    rejected = report.rejected.get(name, frozenset())
    for row in tables[name].rows:
        if row["_row"] in rejected:
            continue
        yield row["_row"], (lambda c, r=row: r[m[c]].strip() if c in m else "")


def _float(s: str) -> float | None:
    d = parse_decimal(s)
    return None if d is None else float(d)


def _location(g, prefix: str) -> Location:
    p = f"{prefix}_" if prefix else ""
    return Location(
        zip=g(f"{p}zip") or None,
        address=g(f"{p}address") or None,
        city=g(f"{p}city") or None,
        state=g(f"{p}state") or None,
        lat=_float(g(f"{p}lat")),
        lon=_float(g(f"{p}lon")),
    )


def build(tables: dict[str, RawTable], report: ValidationReport) -> Dataset:
    shipments = tuple(
        Shipment(
            id=g("shipment_id"),
            ship_date=parse_date(g("ship_date")),
            carrier_id=g("carrier_id"),
            weight_lb=parse_decimal(g("weight_lb")),
            actual_cost=parse_decimal(g("actual_cost")),
            origin=_location(g, "origin"),
            dest=_location(g, "dest"),
            mode=g("mode") or None,
            service_level=g("service_level") or None,
            deliver_date=parse_date(g("deliver_date")),
            pieces=parse_int(g("pieces")),
            pallets=parse_int(g("pallets")),
            source_row=rn,
        )
        for rn, g in _rows("shipments", tables, report)
    )
    rates = tuple(
        RateCard(
            carrier_id=g("carrier_id"),
            rate_type=g("rate_type").lower(),
            rate=parse_decimal(g("rate")),
            min_charge=parse_decimal(g("min_charge")),
            fuel_pct=parse_decimal(g("fuel_pct")),
            mode=g("mode") or None,
            source_row=rn,
        )
        for rn, g in _rows("rates", tables, report)
    )
    if not shipments or not rates:
        raise ValueError("no accepted shipments or rates rows")

    named = {}
    if "locations" in tables and "locations" in report.mapping:
        named = {g("location_id"): _location(g, "") for _, g in _rows("locations", tables, report)}

    uniq: dict[str, Location] = {}
    for s in shipments:
        uniq.setdefault(s.origin.key, s.origin)
        uniq.setdefault(s.dest.key, s.dest)
    return Dataset(shipments, rates, tuple(uniq.values()), named)

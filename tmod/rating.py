"""Node 07 Rating: Shipment + Route + RateCard -> cost. Contract: docs/nodes/07_rating.md"""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Sequence

from tmod.canonical import Dataset, RateCard, Shipment
from tmod.routing import Route, RouteMatrix

CENT = Decimal("0.01")


def _money(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class RatedCost:
    shipment_id: str
    carrier_id: str
    rate_type: str
    miles: float | None
    linehaul: Decimal
    fuel: Decimal
    total: Decimal
    min_applied: bool
    rate_card_row: int


@dataclass(frozen=True)
class RatingReport:
    rated: int
    unrated: tuple[tuple[str, str], ...]
    total: Decimal


def select_rate(cards: Sequence[RateCard], carrier_id: str, mode: str | None) -> RateCard | None:
    mine = sorted((c for c in cards if c.carrier_id == carrier_id), key=lambda c: c.source_row)
    exact = [c for c in mine if c.mode is not None and mode is not None and c.mode.lower() == mode.lower()]
    generic = [c for c in mine if c.mode is None]
    return (exact or generic or [None])[0]


def rate_shipment(s: Shipment, route: Route | None, card: RateCard, cwt_round_up: bool = False) -> RatedCost:
    miles = route.miles if route else None
    if card.rate_type == "per_mile":
        if route is None:
            raise ValueError(f"{s.id}: per_mile rate needs a route")
        base = card.rate * Decimal(str(miles))
    elif card.rate_type == "per_cwt":
        cwt = Decimal(math.ceil(s.weight_lb / 100)) if cwt_round_up else s.weight_lb / 100
        base = card.rate * cwt
    elif card.rate_type == "flat":
        base = card.rate
    else:
        raise ValueError(f"unknown rate_type {card.rate_type!r}")
    min_applied = card.min_charge is not None and base < card.min_charge
    linehaul = _money(card.min_charge if min_applied else base)
    fuel = _money(linehaul * (card.fuel_pct or Decimal(0)) / 100)
    return RatedCost(s.id, card.carrier_id, card.rate_type, miles, linehaul, fuel, linehaul + fuel,
                     min_applied, card.source_row)


def rate_all(ds: Dataset, matrix: RouteMatrix, cwt_round_up: bool = False) -> tuple[tuple[RatedCost, ...], RatingReport]:
    rated: list[RatedCost] = []
    unrated: list[tuple[str, str]] = []
    for s in ds.shipments:
        card = select_rate(ds.rates, s.carrier_id, s.mode)
        if card is None:
            unrated.append((s.id, "NO_RATE"))
            continue
        route = matrix.get((s.origin.key, s.dest.key))
        if card.rate_type == "per_mile" and route is None:
            unrated.append((s.id, "NO_ROUTE"))
            continue
        rated.append(rate_shipment(s, route, card, cwt_round_up))
    total = sum((r.total for r in rated), Decimal(0))
    return tuple(rated), RatingReport(len(rated), tuple(unrated), total)

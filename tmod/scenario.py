"""Node 09 Scenario: rules applied on a Dataset, pure. Contract: docs/nodes/09_scenario.md"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path

from tmod.canonical import Dataset


@dataclass(frozen=True)
class CarrierSwitch:
    from_carrier: str
    to_carrier: str
    to_mode: str | None = None
    lanes: frozenset[tuple[str, str]] | None = None


@dataclass(frozen=True)
class ConsolidationWindow:
    days: int
    max_weight_lb: Decimal


Rule = CarrierSwitch | ConsolidationWindow


@dataclass(frozen=True)
class Scenario:
    name: str
    rules: tuple[Rule, ...]


@dataclass(frozen=True)
class ApplyReport:
    changed: tuple[tuple[str, str], ...]
    pending: tuple[Rule, ...]


def apply(ds: Dataset, scenario: Scenario) -> tuple[Dataset, ApplyReport]:
    carriers = {r.carrier_id for r in ds.rates}
    shipments = list(ds.shipments)
    changed: list[tuple[str, str]] = []
    pending: list[Rule] = []
    for rule in scenario.rules:
        if isinstance(rule, CarrierSwitch):
            if rule.to_carrier not in carriers:
                raise ValueError(f"{scenario.name}: to_carrier {rule.to_carrier!r} has no rate card")
            for i, s in enumerate(shipments):
                if s.carrier_id != rule.from_carrier:
                    continue
                if rule.lanes is not None and (s.origin.zip, s.dest.zip) not in rule.lanes:
                    continue
                shipments[i] = replace(s, carrier_id=rule.to_carrier, mode=rule.to_mode or s.mode)
                changed.append((s.id, f"{rule.from_carrier}->{rule.to_carrier}"))
        elif isinstance(rule, ConsolidationWindow):
            if rule.days < 1 or rule.max_weight_lb <= 0:
                raise ValueError(f"{scenario.name}: invalid ConsolidationWindow {rule}")
            pending.append(rule)
        else:
            raise ValueError(f"unknown rule {rule!r}")
    return replace(ds, shipments=tuple(shipments)), ApplyReport(tuple(changed), tuple(pending))


def load_scenario(path: str | Path) -> Scenario:
    doc = json.loads(Path(path).read_text())
    rules: list[Rule] = []
    for r in doc["rules"]:
        t = r.get("type")
        if t == "carrier_switch":
            lanes = r.get("lanes")
            rules.append(CarrierSwitch(r["from_carrier"], r["to_carrier"], r.get("to_mode"),
                                       frozenset(tuple(l) for l in lanes) if lanes is not None else None))
        elif t == "consolidation_window":
            rules.append(ConsolidationWindow(int(r["days"]), Decimal(str(r["max_weight_lb"]))))
        else:
            raise ValueError(f"unknown rule type {t!r}")
    return Scenario(doc["name"], tuple(rules))

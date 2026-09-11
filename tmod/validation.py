"""Node 02 Validation: RawTable -> ValidationReport. Report only, no transform.

Contract: docs/nodes/02_validation.md
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from tmod.ingestion import RawTable

# ---- parsers (owned here, reused by Node 03) --------------------------------

_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d", "%Y%m%d", "%m/%d/%y")


def parse_decimal(s: str) -> Decimal | None:
    s = s.strip().replace("$", "").replace(",", "")
    if not s:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        raise ValueError(f"not a number: {s!r}")


def parse_int(s: str) -> int | None:
    d = parse_decimal(s)
    if d is None:
        return None
    if d != d.to_integral_value():
        raise ValueError(f"not an integer: {s!r}")
    return int(d)


def parse_date(s: str) -> date | None:
    s = s.strip()
    if not s:
        return None
    head = s.replace("T", " ").split(" ")[0]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(head, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"not a date: {s!r}")


def _parse_lat(s: str):
    v = parse_decimal(s)
    if v is not None and not -90 <= v <= 90:
        raise ValueError(f"latitude out of range: {s!r}")
    return v


def _parse_lon(s: str):
    v = parse_decimal(s)
    if v is not None and not -180 <= v <= 180:
        raise ValueError(f"longitude out of range: {s!r}")
    return v


PARSERS = {"str": lambda s: s.strip() or None, "int": parse_int, "decimal": parse_decimal,
           "date": parse_date, "lat": _parse_lat, "lon": _parse_lon, "enum": lambda s: s.strip().lower() or None}

# ---- schema -------------------------------------------------------------------


@dataclass(frozen=True)
class Column:
    name: str
    type: str = "str"
    required: bool = False
    min: Decimal | None = None
    enum: tuple[str, ...] = ()


@dataclass(frozen=True)
class TableSchema:
    name: str
    columns: tuple[Column, ...]
    required: bool = True
    any_of: tuple[tuple[tuple[str, ...], ...], ...] = ()  # each entry: alternatives, each alternative: cols all present
    unique: tuple[str, ...] = ()
    foreign_keys: tuple[tuple[str, str, str], ...] = ()  # (col, ref_table, ref_col)
    aliases: dict[str, str] = field(default_factory=dict)  # raw normalized -> schema col


ZERO = Decimal(0)
_LOC = lambda p: ((f"{p}_zip",), (f"{p}_address",), (f"{p}_lat", f"{p}_lon"))  # noqa: E731

SCHEMAS: dict[str, TableSchema] = {
    "shipments": TableSchema(
        "shipments",
        (
            Column("shipment_id", required=True),
            Column("ship_date", "date", required=True),
            Column("carrier_id", required=True),
            Column("weight_lb", "decimal", required=True, min=ZERO),
            Column("actual_cost", "decimal", required=True, min=ZERO),
            Column("origin_zip"), Column("origin_address"), Column("origin_lat", "lat"), Column("origin_lon", "lon"),
            Column("origin_city"), Column("origin_state"),
            Column("dest_zip"), Column("dest_address"), Column("dest_lat", "lat"), Column("dest_lon", "lon"),
            Column("dest_city"), Column("dest_state"),
            Column("mode"), Column("service_level"), Column("deliver_date", "date"),
            Column("pieces", "int", min=ZERO), Column("pallets", "int", min=ZERO),
        ),
        any_of=(_LOC("origin"), _LOC("dest")),
        unique=("shipment_id",),
        foreign_keys=(("carrier_id", "rates", "carrier_id"),),
        aliases={"origin_postal_code": "origin_zip", "dest_postal_code": "dest_zip", "destination_zip": "dest_zip",
                 "weight": "weight_lb", "cost": "actual_cost", "carrier": "carrier_id", "scac": "carrier_id"},
    ),
    "rates": TableSchema(
        "rates",
        (
            Column("carrier_id", required=True),
            Column("rate_type", "enum", required=True, enum=("per_mile", "per_cwt", "flat")),
            Column("rate", "decimal", required=True, min=ZERO),
            Column("min_charge", "decimal", min=ZERO),
            Column("fuel_pct", "decimal", min=ZERO),
            Column("mode"),
        ),
        aliases={"carrier": "carrier_id", "scac": "carrier_id"},
    ),
    "locations": TableSchema(
        "locations",
        (Column("location_id", required=True), Column("address"), Column("lat", "lat"), Column("lon", "lon"),
         Column("city"), Column("state"), Column("zip")),
        required=False,
        any_of=((("address",), ("lat", "lon"), ("zip",)),),
        unique=("location_id",),
    ),
}

# ---- report -------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    severity: str
    table: str
    row: int | None
    column: str | None
    code: str
    detail: str


@dataclass(frozen=True)
class ValidationReport:
    findings: tuple[Finding, ...]
    mapping: dict[str, dict[str, str]]
    rejected: dict[str, frozenset[int]]
    row_counts: dict[str, tuple[int, int]]

    @property
    def ok(self) -> bool:
        return not any(f.severity == "ERROR" for f in self.findings)

    def summary(self) -> str:
        lines = [f"{'OK' if self.ok else 'FAIL'}: {sum(f.severity == 'ERROR' for f in self.findings)} errors, "
                 f"{sum(f.severity == 'WARN' for f in self.findings)} warnings"]
        for t, (total, kept) in self.row_counts.items():
            lines.append(f"  {t}: {kept}/{total} rows accepted")
        return "\n".join(lines)


def _resolve(schema: TableSchema, table: RawTable) -> dict[str, str]:
    known = {c.name for c in schema.columns}
    out: dict[str, str] = {}
    for raw in table.columns:
        col = raw if raw in known else schema.aliases.get(raw)
        if col and col not in out:
            out[col] = raw
    return out


def _validate_table(schema: TableSchema, table: RawTable, findings: list[Finding], refs: dict[tuple[str, str], set]) -> set[int]:
    t = schema.name
    mapping = _resolve(schema, table)
    bad: set[int] = set()

    for raw in table.columns:
        if raw not in mapping.values():
            findings.append(Finding("WARN", t, None, raw, "UNKNOWN_COLUMN", "not in schema, ignored"))
    for i in table.issues:
        findings.append(Finding("WARN", t, i.row, None, "INGEST_ISSUE", f"{i.code}: {i.detail}"))

    missing = [c.name for c in schema.columns if c.required and c.name not in mapping]
    if missing:
        for m in missing:
            findings.append(Finding("ERROR", t, None, m, "MISSING_COLUMN", "required column absent"))
        return {r["_row"] for r in table.rows}

    seen: dict[str, dict] = {u: {} for u in schema.unique if u in mapping}
    for row in table.rows:
        rn = row["_row"]
        values: dict[str, object] = {}
        for c in schema.columns:
            if c.name not in mapping:
                continue
            raw_val = row[mapping[c.name]]
            try:
                v = PARSERS[c.type](raw_val)
            except ValueError as e:
                findings.append(Finding("ERROR", t, rn, c.name, "BAD_TYPE", str(e)))
                bad.add(rn)
                continue
            if v is None:
                if c.required:
                    findings.append(Finding("ERROR", t, rn, c.name, "MISSING_VALUE", "required"))
                    bad.add(rn)
                continue
            if c.min is not None and v < c.min:
                findings.append(Finding("ERROR", t, rn, c.name, "OUT_OF_RANGE", f"{v} < {c.min}"))
                bad.add(rn)
            if c.enum and v not in c.enum:
                findings.append(Finding("ERROR", t, rn, c.name, "BAD_ENUM", f"{v!r} not in {c.enum}"))
                bad.add(rn)
            values[c.name] = v
        for alternatives in schema.any_of:
            if not any(all(values.get(col) is not None for col in alt) for alt in alternatives):
                findings.append(Finding("ERROR", t, rn, None, "MISSING_LOCATION", f"need one of {alternatives}"))
                bad.add(rn)
        for u in seen:
            v = values.get(u)
            if v is None:
                continue
            if v in seen[u]:
                findings.append(Finding("ERROR", t, rn, u, "DUPLICATE_KEY", f"{v!r} first seen row {seen[u][v]}"))
                bad.add(rn)
            else:
                seen[u][v] = rn
        for col, ref_t, ref_c in schema.foreign_keys:
            v = values.get(col)
            if v is not None and v not in refs.get((ref_t, ref_c), set()):
                findings.append(Finding("ERROR", t, rn, col, "UNKNOWN_REF", f"{v!r} not in {ref_t}.{ref_c}"))
                bad.add(rn)
    return bad


def _ref_values(schemas: dict[str, TableSchema], tables: dict[str, RawTable]) -> dict[tuple[str, str], set]:
    refs: dict[tuple[str, str], set] = {}
    for s in schemas.values():
        for _, ref_t, ref_c in s.foreign_keys:
            if ref_t in tables and ref_t in schemas:
                m = _resolve(schemas[ref_t], tables[ref_t])
                if ref_c in m:
                    refs[(ref_t, ref_c)] = {r[m[ref_c]].strip() for r in tables[ref_t].rows if r[m[ref_c]].strip()}
    return refs


def validate(tables: dict[str, RawTable], schemas: dict[str, TableSchema] = SCHEMAS) -> ValidationReport:
    findings: list[Finding] = []
    mapping: dict[str, dict[str, str]] = {}
    rejected: dict[str, frozenset[int]] = {}
    counts: dict[str, tuple[int, int]] = {}
    refs = _ref_values(schemas, tables)

    for name, schema in schemas.items():
        if name not in tables:
            if schema.required:
                findings.append(Finding("ERROR", name, None, None, "MISSING_TABLE", "required table absent"))
            continue
        table = tables[name]
        mapping[name] = _resolve(schema, table)
        bad = _validate_table(schema, table, findings, refs)
        rejected[name] = frozenset(bad)
        counts[name] = (len(table.rows), len(table.rows) - len(bad))
    for name in tables.keys() - schemas.keys():
        findings.append(Finding("WARN", name, None, None, "UNKNOWN_COLUMN", "table not in schema, ignored"))
    return ValidationReport(tuple(findings), mapping, rejected, counts)

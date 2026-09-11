"""Node 04 Address: normalize Location fields (zip-centric). Contract: docs/nodes/04_address.md"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace

from tmod.canonical import Dataset, Location

_US_ZIP = re.compile(r"^\d{5}(\d{4})?$")
_CA_POSTAL = re.compile(r"^[A-Z]\d[A-Z]\d[A-Z]\d$")
_PUNCT = re.compile(r"[^\w\s]")
_WS = re.compile(r"\s+")

STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO",
    "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC",
}
_ABBR = set(STATES.values())

SUFFIX = {"STREET": "ST", "AVENUE": "AVE", "ROAD": "RD", "BOULEVARD": "BLVD", "DRIVE": "DR", "LANE": "LN",
          "COURT": "CT", "PLACE": "PL", "HIGHWAY": "HWY", "PARKWAY": "PKWY", "SUITE": "STE",
          "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W"}


def normalize_zip(s: str | None) -> tuple[str | None, str | None]:
    if not s or not s.strip():
        return None, None
    z = re.sub(r"[\s\-]", "", s).upper()
    if z.isdigit() and 3 <= len(z) < 5:
        z = z.zfill(5)
    if _US_ZIP.match(z):
        return z[:5], None
    if _CA_POSTAL.match(z):
        return z, "NON_US_ZIP"
    return s.strip(), "INVALID_ZIP"


def normalize_state(s: str | None) -> tuple[str | None, str | None]:
    if not s or not s.strip():
        return None, None
    t = _WS.sub(" ", s.strip())
    if t.upper() in _ABBR:
        return t.upper(), None
    if t.lower() in STATES:
        return STATES[t.lower()], None
    return t, "UNKNOWN_STATE"


def normalize_city(s: str | None) -> str | None:
    if not s or not s.strip():
        return None
    return _WS.sub(" ", s.strip()).title()


def normalize_address(s: str | None) -> str | None:
    if not s or not s.strip():
        return None
    words = _WS.sub(" ", _PUNCT.sub(" ", s.upper())).strip().split(" ")
    return " ".join(SUFFIX.get(w, w) for w in words)


def normalize_location(loc: Location) -> tuple[Location, tuple[str, ...]]:
    zip_, zi = normalize_zip(loc.zip)
    state, si = normalize_state(loc.state)
    issues = tuple(i for i in (zi, si) if i)
    return replace(loc, zip=zip_, state=state, city=normalize_city(loc.city),
                   address=normalize_address(loc.address)), issues


@dataclass(frozen=True)
class AddressIssue:
    shipment_id: str
    side: str
    code: str
    value: str


@dataclass(frozen=True)
class AddressReport:
    issues: tuple[AddressIssue, ...]
    locations_before: int
    locations_after: int


def normalize(ds: Dataset) -> tuple[Dataset, AddressReport]:
    issues: list[AddressIssue] = []

    def norm(loc: Location, sid: str, side: str) -> Location:
        new, codes = normalize_location(loc)
        issues.extend(AddressIssue(sid, side, c, loc.zip if "ZIP" in c else loc.state or "") for c in codes)
        return new

    shipments = tuple(replace(s, origin=norm(s.origin, s.id, "origin"), dest=norm(s.dest, s.id, "dest"))
                      for s in ds.shipments)
    named = {k: norm(v, "", k) for k, v in ds.named_locations.items()}
    uniq: dict[str, Location] = {}
    for s in shipments:
        uniq.setdefault(s.origin.key, s.origin)
        uniq.setdefault(s.dest.key, s.dest)
    out = Dataset(shipments, ds.rates, tuple(uniq.values()), named)
    return out, AddressReport(tuple(issues), len(ds.locations), len(out.locations))

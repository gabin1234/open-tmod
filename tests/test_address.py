from datetime import date
from decimal import Decimal

from tmod.address import normalize, normalize_address, normalize_city, normalize_state, normalize_zip
from tmod.canonical import Dataset, Location, RateCard, Shipment


def test_zip():
    assert normalize_zip("2101") == ("02101", None)
    assert normalize_zip("60601-1234") == ("60601", None)
    assert normalize_zip("606011234") == ("60601", None)
    assert normalize_zip(" 60601 ") == ("60601", None)
    assert normalize_zip("k1a 0b1") == ("K1A0B1", "NON_US_ZIP")
    assert normalize_zip("ABCDE") == ("ABCDE", "INVALID_ZIP")
    assert normalize_zip("") == (None, None)
    assert normalize_zip(None) == (None, None)


def test_state_city_address():
    assert normalize_state("illinois") == ("IL", None)
    assert normalize_state(" il ") == ("IL", None)
    assert normalize_state("New  York") == ("NY", None)
    assert normalize_state("Ontario") == ("Ontario", "UNKNOWN_STATE")
    assert normalize_city("  new   york ") == "New York"
    assert normalize_address("123 Main Street, Suite 4") == "123 MAIN ST STE 4"
    assert normalize_address("1 N. Wacker Dr.") == "1 N WACKER DR"
    assert normalize_address(None) is None


def _ship(i, o, d):
    return Shipment(i, date(2024, 1, 1), "C1", Decimal(10), Decimal(100), o, d,
                    None, None, None, None, None, source_row=2)


def test_normalize_dataset():
    a = Location(zip="60601", state="illinois")
    b = Location(zip="60601-1234", state="IL")
    c = Location(zip="XYZ", lat=40.75, lon=-73.99)
    d = Location(zip="10001", city=" new york ")
    ds = Dataset((_ship("S1", a, c), _ship("S2", b, d)), (RateCard("C1", "flat", Decimal(1), None, None, None, 2),),
                 (a, c, b, d), {"DC": Location(zip="2101")})
    out, rep = normalize(ds)
    assert rep.locations_before == 4 and rep.locations_after == 3
    assert out.shipments[0].origin.key == out.shipments[1].origin.key == "zip:60601"
    assert out.shipments[0].origin.state == "IL"
    assert out.shipments[1].dest.city == "New York"
    assert out.shipments[0].dest.lat == 40.75 and out.shipments[0].dest.zip == "XYZ"
    assert [(i.shipment_id, i.side, i.code) for i in rep.issues] == [("S1", "dest", "INVALID_ZIP")]
    assert out.named_locations["DC"].zip == "02101"
    assert out.shipments[0].actual_cost == Decimal(100) and out.rates == ds.rates

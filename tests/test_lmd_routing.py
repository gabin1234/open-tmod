import csv
import random
from pathlib import Path

import pytest

from tmod.canonical import Location
from tmod.geocoding import ZipCentroidGeocoder
from tmod.lmd_routing import AffineHaversineProvider, TruthProvider, calibrate, load_calibration, load_truth, save_calibration
from tmod.routing import haversine_miles

HUB = Location(zip="30260")
GEO = ZipCentroidGeocoder()
REAL = Path("data/private/lmd_lphb30260_demo/distance_truth.csv")


def test_providers():
    a, b = Location(zip="30260", lat=33.58, lon=-84.34), Location(zip="30309", lat=33.79, lon=-84.39)
    r = AffineHaversineProvider(8.0, 1.1, mph=30).route(a, b)
    gc = haversine_miles(a.lat, a.lon, b.lat, b.lon)
    assert abs(r.miles - (8 + 1.1 * gc)) < 1e-9 and abs(r.minutes - r.miles * 2) < 1e-9 and r.provider == "affine_haversine"
    assert AffineHaversineProvider(-100, 1).route(a, b).miles == 0.5
    tp = TruthProvider({("30260", "30309"): 21.5}, mph=30)
    assert tp.route(a, b).miles == 21.5 and tp.route(b, a).minutes == 43.0 and tp.route(a, b).provider == "truth"
    assert tp.route(a, Location(zip="99999")) is None and tp.route(a, Location(lat=1.0, lon=1.0)) is None


def test_calibrate_recovers_synthetic(tmp_path):
    rng = random.Random(3)
    hub = GEO.geocode(HUB)
    zips = [z for z in GEO.exact if z.startswith("30")][:120]
    truth = {}
    for z in zips:
        la, lo = GEO.exact[z]
        gc = haversine_miles(hub.lat, hub.lon, la, lo)
        if gc >= 1:
            truth[("30260", z)] = (5 + 1.3 * gc) * (1 + rng.gauss(0, 0.03))
    cal = calibrate(HUB, truth)
    assert abs(cal.a - 5) < 0.5 * 5 + 1 and abs(cal.b - 1.3) < 0.13, cal
    assert cal.within_tolerance and cal.test_mape_pct < 6 and cal.n_zips == len(truth)
    save_calibration(tmp_path / "c.json", cal)
    assert load_calibration(tmp_path / "c.json") == cal


def test_load_truth(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("hub_zip,zip,n_loads,median_miles,mean_miles,min_miles,max_miles\n30260,30309,10,21.5,21.5,21.5,21.5\n")
    assert load_truth(p) == {("30260", "30309"): 21.5}


@pytest.mark.skipif(not REAL.exists(), reason="private truth not present")
def test_real_gate():
    truth = load_truth(REAL)
    weights = {(r["hub_zip"], r["zip"]): int(r["n_loads"]) for r in csv.DictReader(open(REAL))}
    cal = calibrate(HUB, truth, weights=weights)
    print(f"\nreal calibration: a={cal.a:.2f} b={cal.b:.3f} zips={cal.n_zips} train {cal.train_gap_pct:+.2f}% "
          f"test {cal.test_gap_pct:+.2f}% MAPE {cal.test_mape_pct:.1f}% bands {cal.band_gap_pct}")
    assert cal.within_tolerance

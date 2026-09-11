"""Synthetic TMS sample for pipeline verification. Deterministic. Run: uv run python scripts/make_sample.py

Ground truth: actual_cost = rate(haversine * 1.25) * (1 + N(0, 0.02)). Calibration should recover circuity ~1.25.
"""
import csv
import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from tmod.canonical import Location
from tmod.geocoding import ZipCentroidGeocoder
from tmod.routing import haversine_miles

OUT = Path(__file__).resolve().parent.parent / "data" / "sample"
ORIGINS = ["60601", "75201"]
DESTS = ["10001", "30301", "90001", "98101", "33101", "80202", "02101", "19102", "43215", "55401", "63101", "85001", "37201"]
CARRIERS = {  # carrier: (rate_type, rate, min, fuel, mode)
    "C1": ("per_mile", 2.10, None, 22, "TL"),
    "C2": ("per_cwt", 18.50, 95, 18, "LTL"),
    "C3": ("flat", 450, None, None, None),
}
TRUE_CIRCUITY = 1.25

rng = random.Random(7)
geo = ZipCentroidGeocoder()
pt = {z: geo.geocode(Location(zip=z)) for z in ORIGINS + DESTS}


def cost(carrier, miles, weight):
    rt, rate, mn, fuel, _ = CARRIERS[carrier]
    base = {"per_mile": rate * miles, "per_cwt": rate * weight / 100, "flat": rate}[rt]
    lh = max(base, mn or 0)
    return lh * (1 + (fuel or 0) / 100)


rows = []
for i in range(200):
    o, d = rng.choice(ORIGINS), rng.choice(DESTS)
    carrier = rng.choices(list(CARRIERS), weights=[5, 4, 1])[0]
    weight = rng.randint(400, 44000) if carrier == "C1" else rng.randint(150, 9000)
    miles = haversine_miles(pt[o].lat, pt[o].lon, pt[d].lat, pt[d].lon) * TRUE_CIRCUITY
    actual = cost(carrier, miles, weight) * (1 + rng.gauss(0, 0.02))
    day = date(2024, 3, 1) + timedelta(days=rng.randint(0, 30))
    rows.append([f"SH{i+1:04d}", day.strftime("%m/%d/%Y"), carrier, str(weight), f"{actual:.2f}", o, d, CARRIERS[carrier][4] or ""])

# dirty rows: Excel-dropped zero, ZIP+4, bad weight, unknown carrier
rows[3][6] = "2101"
rows[5][5] = "60601-1234"
rows.append(["SH_BAD1", "03/05/2024", "C1", "abc", "100.00", "60601", "10001", "TL"])
rows.append(["SH_BAD2", "03/05/2024", "C9", "1000", "100.00", "60601", "10001", "TL"])

with open(OUT / "shipments.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Shipment ID", "Ship Date", "SCAC", "Weight", "Cost", "Origin Postal Code", "Dest Zip", "Mode"])
    w.writerows(rows)
with open(OUT / "rates.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["carrier_id", "rate_type", "rate", "min_charge", "fuel_pct", "mode"])
    for c, (rt, rate, mn, fuel, mode) in CARRIERS.items():
        w.writerow([c, rt, rate, mn or "", fuel or "", mode or ""])
print(f"wrote {len(rows)} shipments to {OUT}")

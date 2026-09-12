import random
from datetime import datetime, timedelta

from tmod.product.history import estimate_factors, merge_hours, service_estimate


def test_estimate_and_merge():
    rng = random.Random(1)
    pairs = []
    for day in range(30):                       # weekdays only: 2026-09-14 is a Monday, skip weekends
        base = datetime(2026, 9, 14) + timedelta(days=day)
        if base.weekday() >= 5:
            continue
        for hour, factor, n in ((8, 1.4, 5), (11, 1.0, 5), (16, 1.3, 5), (3, 1.0, 1)):
            for _ in range(n):
                ff = rng.uniform(6, 40)
                pairs.append((base.replace(hour=hour, minute=rng.randint(0, 59)), 30 + ff * factor * rng.uniform(0.9, 1.1), ff))
    assert service_estimate([25, 30, 35] * 4) == 30 and service_estimate([1, 2]) == 30.0
    f = estimate_factors(pairs, service_min=30)
    assert abs(f[("WEEKDAY", 8)][0] - 1.4) < 0.1 and abs(f[("WEEKDAY", 11)][0] - 1.0) < 0.1 and abs(f[("WEEKDAY", 16)][0] - 1.3) < 0.1
    assert ("WEEKDAY", 3) not in f                      # n < 30
    m = merge_hours({("WEEKDAY", 7): (1.38, 40), ("WEEKDAY", 8): (1.40, 50), ("WEEKDAY", 9): (1.1, 60), ("WEEKDAY", 11): (1.0, 30), ("WEEKEND", 9): (1.0, 31)})
    assert m == [("WEEKDAY", 7, 9, 1.391, 90), ("WEEKDAY", 9, 10, 1.1, 60), ("WEEKDAY", 11, 12, 1.0, 30), ("WEEKEND", 9, 10, 1.0, 31)]

"""Node 14 Map: single-file HTML (Leaflet CDN). Contract: docs/nodes/14_map.md"""
from __future__ import annotations

import html
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from tmod.canonical import Dataset
from tmod.comparison import Comparison
from tmod.rerating import RerateResult
from tmod.routing import RouteMatrix


def _lanes(ds: Dataset, rated_ids: set[str], costs: dict[str, Decimal], gate: bool) -> list[dict]:
    agg: dict[tuple, dict] = defaultdict(lambda: {"n": 0, "weight": Decimal(0), "cost": Decimal(0)})
    coords: dict[tuple, list] = {}
    for s in ds.shipments:
        if s.id not in rated_ids or None in (s.origin.lat, s.origin.lon, s.dest.lat, s.dest.lon):
            continue
        k = (s.origin.key, s.dest.key)
        a = agg[k]
        a["n"] += 1
        a["weight"] += s.weight_lb
        a["cost"] += costs.get(s.id, Decimal(0))
        coords[k] = [[s.origin.lat, s.origin.lon], [s.dest.lat, s.dest.lon]]
    out = []
    for k, a in agg.items():
        label = f"{k[0]} → {k[1]}<br>{a['n']} shipments, {a['weight']:,.0f} lb"
        if gate:
            label += f"<br>cost {a['cost']:,.2f}"
        out.append({"coords": coords[k], "n": a["n"], "label": label})
    return out


def render_html(cmp: Comparison, ds_base: Dataset, ds_scen: Dataset, base_matrix: RouteMatrix,
                scen_matrix: RouteMatrix, scen: RerateResult, title: str = "Open T-Modeler POC") -> str:
    gate = cmp.gate_passed
    scen_cost = {r.shipment_id: r.total for r in scen.rated}
    scen_ids = set(scen_cost)
    base_ids = {d for ps in cmp.per_shipment for d in ps.members}
    base_lanes = _lanes(ds_base, base_ids, {}, False)  # baseline lane tooltips never show cost
    scen_lanes = _lanes(ds_scen, scen_ids, scen_cost, gate)
    pts = sorted({(round(l.lat, 4), round(l.lon, 4)) for l in ds_scen.locations if l.lat is not None})

    miles = {r.shipment_id: r.miles for r in scen.rated}
    carrier = {s.id: s.carrier_id for s in ds_scen.shipments}
    cols = ["scenario_id", "members", "carrier", "miles"] + (["baseline_cost", "scenario_cost", "delta"] if gate else [])
    rows = []
    for d in sorted(cmp.per_shipment, key=lambda d: -(abs(d.delta) if d.delta is not None else 0)):
        cells = [d.scenario_id, str(len(d.members)), carrier.get(d.scenario_id, ""),
                 "-" if miles.get(d.scenario_id) is None else f"{miles[d.scenario_id]:,.0f}"]
        if gate:
            cells += ["-" if d.baseline_cost is None else f"{d.baseline_cost:,.2f}", f"{d.scenario_cost:,.2f}",
                      "-" if d.delta is None else f"{d.delta:+,.2f}"]
        rows.append("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in cells) + "</tr>")

    data = json.dumps({"base": base_lanes, "scen": scen_lanes, "pts": pts}, default=str)
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>body{{margin:0;font:14px system-ui}}#map{{height:60vh}}pre{{background:#f4f4f4;padding:8px}}
table{{border-collapse:collapse}}td,th{{border:1px solid #ccc;padding:2px 6px;text-align:right}}td:first-child,th:first-child{{text-align:left}}
.wrap{{display:flex;gap:16px;padding:8px}}.legend span{{display:inline-block;width:24px;height:3px;margin-right:4px}}</style></head>
<body><div id="map"></div>
<div class="wrap"><div><h3>{html.escape(title)}</h3><pre>{html.escape(cmp.summary())}</pre>
<div class="legend"><span style="background:#888"></span>baseline lanes &nbsp; <span style="background:#1f77b4"></span>scenario lanes</div></div>
<div><h3>Scenario shipments ({len(rows)})</h3><table><tr>{"".join(f"<th>{c}</th>" for c in cols)}</tr>{"".join(rows)}</table></div></div>
<script>
const D={data};
const map=L.map('map');L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{attribution:'© OpenStreetMap'}}).addTo(map);
const g=L.featureGroup().addTo(map);
D.base.forEach(l=>L.polyline(l.coords,{{color:'#888',weight:4+Math.log2(l.n),opacity:.5}}).bindTooltip(l.label).addTo(g));
D.scen.forEach(l=>L.polyline(l.coords,{{color:'#1f77b4',weight:1+Math.log2(l.n),opacity:.8}}).bindTooltip(l.label).addTo(g));
D.pts.forEach(p=>L.circleMarker(p,{{radius:4,color:'#d62728'}}).addTo(g));
if(D.pts.length)map.fitBounds(g.getBounds().pad(0.1));else map.setView([39,-96],4);
</script></body></html>"""


def write_html(path: str | Path, *args, **kwargs) -> Path:
    p = Path(path)
    p.write_text(render_html(*args, **kwargs))
    return p

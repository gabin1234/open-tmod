"""LMD Node 14: single-file Leaflet map of baseline vs scenario routes. Contract: docs/nodes/lmd_13_14_compare_map.md"""
from __future__ import annotations

import html
import json
from pathlib import Path

from tmod.canonical import Location
from tmod.lmd_baseline import BaselineRoutes, RoutePlan
from tmod.lmd_compare import RouteComparison

COLORS = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#8c564b", "#e377c2", "#17becf", "#bcbd22", "#7f7f7f"]


def _plan_json(p: RoutePlan, hub: Location, color: str) -> dict:
    pts = [[hub.lat, hub.lon]] + [[s.location.lat, s.location.lon] for s in p.stops] + [[hub.lat, hub.lon]]
    return {"load": p.load_id, "day": p.day.isoformat() if p.day else "none", "truck": p.truck_id, "color": color,
            "pts": pts, "stops": [s.id for s in p.stops], "miles": round(p.miles, 1), "duty": round(p.duty_min),
            "over": p.over_duty or p.over_work}


def render_lmd_html(cmp: RouteComparison, base: BaselineRoutes, scen: BaselineRoutes, hub: Location,
                    title: str = "Open T-Modeler LMD") -> str:
    days = sorted({p.day.isoformat() if p.day else "none" for p in base.plans + scen.plans})
    data = {"hub": [hub.lat, hub.lon],
            "base": [_plan_json(p, hub, "#888") for p in base.plans],
            "scen": [_plan_json(p, hub, COLORS[i % len(COLORS)]) for i, p in enumerate(scen.plans)],
            "days": days}
    rows = "".join(f"<tr><td>{html.escape(p.load_id)}</td><td>{p.day}</td><td>{html.escape(p.truck_id or '')}</td>"
                   f"<td>{len(p.stops)}</td><td>{p.miles:,.0f}</td><td>{p.duty_min:,.0f}</td><td>{'!' if p.over_duty or p.over_work else ''}</td></tr>"
                   for p in scen.plans)
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>body{{margin:0;font:14px system-ui}}#map{{height:62vh}}pre{{background:#f4f4f4;padding:8px;font-size:12px}}
table{{border-collapse:collapse;font-size:12px}}td,th{{border:1px solid #ccc;padding:2px 6px;text-align:right}}td:first-child{{text-align:left}}
.wrap{{display:flex;gap:16px;padding:8px}}.bar{{padding:6px 8px;background:#eee}}</style></head><body>
<div class="bar">{html.escape(title)} — day <select id="day"><option value="all">all</option>{"".join(f'<option value="{d}">{d}</option>' for d in days)}</select>
&nbsp; <label><input type="checkbox" id="showBase" checked> baseline (grey)</label> <label><input type="checkbox" id="showScen" checked> scenario (color)</label></div>
<div id="map"></div>
<div class="wrap"><div><pre>{html.escape(cmp.summary())}</pre></div>
<div><h3>Scenario loads ({len(scen.plans)})</h3><div style="max-height:40vh;overflow:auto"><table><tr><th>load</th><th>day</th><th>truck</th><th>stops</th><th>miles</th><th>duty</th><th>over</th></tr>{rows}</table></div></div></div>
<script>
const D={json.dumps(data)};
const map=L.map('map');L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{attribution:'© OpenStreetMap'}}).addTo(map);
L.marker(D.hub).addTo(map).bindTooltip('hub');
const g=L.featureGroup().addTo(map);
function draw(){{g.clearLayers();const day=document.getElementById('day').value;
 const show=(arr,w,op)=>arr.forEach(p=>{{if(day!=='all'&&p.day!==day)return;
   L.polyline(p.pts,{{color:p.color,weight:w,opacity:op,dashArray:p.over?'6 4':null}}).bindTooltip(`${{p.load}} ${{p.truck||''}} ${{p.stops.length}} stops ${{p.miles}} mi ${{p.duty}} min`).addTo(g);
   p.pts.slice(1,-1).forEach(q=>L.circleMarker(q,{{radius:3,color:p.color}}).addTo(g));}});
 if(document.getElementById('showBase').checked)show(D.base,6,.35);
 if(document.getElementById('showScen').checked)show(D.scen,2.5,.9);
 if(g.getLayers().length)map.fitBounds(g.getBounds().pad(0.1));else map.setView(D.hub,10);}}
['day','showBase','showScen'].forEach(id=>document.getElementById(id).addEventListener('change',draw));draw();
</script></body></html>"""


def write_lmd_html(path: str | Path, *a, **kw) -> Path:
    p = Path(path)
    p.write_text(render_lmd_html(*a, **kw))
    return p

// W02 frontend — talks only to the W01 API. No build step.
const $ = id => document.getElementById(id);
const COLORS = ["#1f77b4","#d62728","#2ca02c","#9467bd","#ff7f0e","#8c564b","#e377c2","#17becf","#bcbd22","#7f7f7f"];
const FIELDS = ["loads","stops","miles","hub_miles","inter_stop_miles","drive_min","service_min","duty_min","over_work","over_duty","late_stops","wait_min","max_trucks_per_day"];
let current = null, currentId = null, selected = null, layer = null, map = null;

const api = async (path, opt) => { const r = await fetch(path, opt); if (r.status === 204) return null; const j = await r.json(); if (!r.ok) throw new Error(j.detail || r.status); return j; };
const fmt = (v, d = 0) => v == null ? "-" : Number(v).toLocaleString(undefined, {maximumFractionDigits: d});

async function init() {
  map = L.map("map").setView([33.75, -84.39], 9);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {attribution: "© OpenStreetMap"}).addTo(map);
  layer = L.featureGroup().addTo(map);
  const h = await api("/api/health");
  $("health").textContent = `api ok · valhalla ${h.valhalla ? "up" : "down"} · ${h.datasets} dataset(s)`;
  $("valhalla").checked = h.valhalla;
  const ds = await api("/api/datasets");
  $("dataset").innerHTML = ds.map(d => `<option value="${d.id}">${d.id} (${d.shipments} shpm${d.has_truth ? "" : ", no truth"})</option>`).join("");
  $("run").onclick = submit;
  ["day","showBase","showScen"].forEach(id => $(id).onchange = draw);
  await refreshRuns();
  setInterval(refreshRuns, 3000);
}

function scenarioFromForm() {
  const num = id => $(id).value === "" ? null : Number($(id).value);
  return {name: $("s_name").value || "vrp", trucks: num("s_trucks"), work_min: num("s_work_min"), duty_min: num("s_duty_min"),
          stop_pool: $("s_stop_pool").value, zone_penalty_min: Number($("s_zone_penalty_min").value || 0),
          time_limit_s: Number($("s_time_limit_s").value || 5), use_windows: $("s_use_windows").checked};
}

async function submit() {
  $("run").disabled = true;
  try {
    const body = {dataset: $("dataset").value, scenario: scenarioFromForm(), valhalla_url: $("valhalla").checked ? "http://localhost:8002" : null};
    const r = await api("/api/runs", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
    currentId = r.run_id;
    await refreshRuns();
  } catch (e) { alert(e.message); }
  $("run").disabled = false;
}

async function refreshRuns() {
  const runs = await api("/api/runs");
  $("runs").innerHTML = runs.map(r => {
    const k = r.kpi_summary ? ` · loads ${r.kpi_summary.loads[0]}→${r.kpi_summary.loads[1]} · mi ${fmt(r.kpi_summary.miles[0])}→${fmt(r.kpi_summary.miles[1])}` : "";
    return `<div class="run ${r.run_id === currentId ? "active" : ""}" data-id="${r.run_id}">
      <b>${r.scenario_name || ""}</b> <span class="badge ${r.status}">${r.status}</span> <span style="float:right" class="muted">${r.created_at.slice(5, 16).replace("T", " ")}</span>
      <div class="muted">${r.dataset}${k}</div>${r.error ? `<div class="err">${r.error}</div>` : ""}
      <button data-del="${r.run_id}" style="float:right;font-size:11px;padding:1px 6px">✕</button></div>`; }).join("") || '<div class="muted">no runs yet</div>';
  $("runs").querySelectorAll(".run").forEach(el => el.onclick = () => load(el.dataset.id));
  $("runs").querySelectorAll("[data-del]").forEach(b => b.onclick = async ev => { ev.stopPropagation(); await api(`/api/runs/${b.dataset.del}`, {method: "DELETE"}); if (b.dataset.del === currentId) currentId = null; refreshRuns(); });
  const cur = runs.find(r => r.run_id === currentId);
  if (cur && cur.status === "done" && (!current || current.run_id !== currentId)) load(currentId);
  else if (cur && cur.status !== "done") $("kpi").textContent = `run ${cur.status}…`;
}

async function load(id) {
  currentId = id;
  const d = await api(`/api/runs/${id}`);
  if (d.status !== "done") { $("kpi").textContent = `run ${d.status}${d.error ? ": " + d.error : ""}`; return; }
  current = d; selected = null;
  renderKpi(d); renderLoads(d);
  const days = [...new Set([...d.plans.baseline, ...d.plans.scenario].map(p => p.day || "none"))].sort();
  $("day").innerHTML = '<option value="all">all</option>' + days.map(x => `<option value="${x}">${x}</option>`).join("");
  draw(true);
  refreshRuns();
}

function renderKpi(d) {
  const g = d.gate.passed, b = d.kpi.baseline, s = d.kpi.scenario;
  const rows = FIELDS.map(f => `${f.padEnd(20)}${fmt(b[f]).padStart(11)}${fmt(s[f]).padStart(11)}${(g ? (d.kpi.delta[f] >= 0 ? "+" : "") + fmt(d.kpi.delta[f]) : "GATED").padStart(10)}${(g ? (d.kpi.delta_pct[f] == null ? "-" : (d.kpi.delta_pct[f] >= 0 ? "+" : "") + d.kpi.delta_pct[f].toFixed(1) + "%") : "GATED").padStart(9)}`);
  $("kpi").textContent = `${"kpi".padEnd(20)}${"baseline".padStart(11)}${"scenario".padStart(11)}${"delta".padStart(10)}${"delta%".padStart(9)}\n` + rows.join("\n");
  $("meta").innerHTML = `<b>${d.scenario.name}</b> · ${d.dataset}<br>gate ${g ? "PASS" : "FAIL"} (test gap ${d.gate.test_gap_pct > 0 ? "+" : ""}${d.gate.test_gap_pct}%)<br>` +
    `days ${d.optimize.days} · stops ${d.optimize.stops} · routed ${d.optimize.routed} · loads ${d.optimize.loads}${d.optimize.unrouted.length ? " · unrouted " + d.optimize.unrouted.length : ""}<br>` +
    `windows ${d.scenario.use_windows ? "on" : "off"} · pool ${d.scenario.stop_pool} · road ${d.valhalla_url ? "valhalla" : "model"}`;
}

function renderLoads(d) {
  const rows = d.plans.scenario.map((p, i) => `<tr data-i="${i}"><td>${p.load_id}</td><td>${p.day}</td><td>${p.truck_id || ""}</td><td>${p.stops.length}</td><td>${fmt(p.miles)}</td><td>${fmt(p.drive_min)}</td><td>${fmt(p.duty_min)}</td><td>${p.late_stops || ""}</td><td>${p.over_duty || p.over_work ? "!" : ""}</td></tr>`);
  $("loads").innerHTML = `<tr><th>load</th><th>day</th><th>truck</th><th>stops</th><th>miles</th><th>drive</th><th>duty</th><th>late</th><th>over</th></tr>` + rows.join("");
  $("loads").querySelectorAll("tr[data-i]").forEach(tr => tr.onclick = () => { const i = Number(tr.dataset.i); selected = selected === i ? null : i; $("loads").querySelectorAll("tr").forEach(t => t.classList.toggle("sel", Number(t.dataset.i) === selected)); const p = d.plans.scenario[i]; $("day").value = p.day || "none"; draw(true); });
}

function planLine(p, color, w, op, hub) {
  const pts = [[hub.lat, hub.lon], ...p.stops.map(s => [s.lat, s.lon]), [hub.lat, hub.lon]];
  const road = p.legs.some(l => l.geometry) ? p.legs.map((l, i) => l.geometry || [pts[i], pts[i + 1]]) : [pts];
  const line = L.polyline(road, {color, weight: w, opacity: op, dashArray: p.over_duty || p.over_work ? "6 4" : null})
    .bindTooltip(`${p.load_id} ${p.truck_id || ""} · ${p.stops.length} stops · ${fmt(p.miles)} mi · ${fmt(p.duty_min)} min${p.late_stops ? " · late " + p.late_stops : ""}`);
  return [line, ...p.stops.map(s => L.circleMarker([s.lat, s.lon], {radius: 3, color}).bindTooltip(`${s.ship_to_id} ${s.zone || ""} ${s.service_min} min ${s.window || ""}`))];
}

function draw(fit) {
  if (!current) return;
  layer.clearLayers();
  const day = $("day").value, hub = current.hub;
  L.marker([hub.lat, hub.lon]).bindTooltip("hub " + hub.zip).addTo(layer);
  const vis = p => day === "all" || (p.day || "none") === day;
  if ($("showBase").checked) current.plans.baseline.filter(vis).forEach(p => planLine(p, "#888", 6, .35, hub).forEach(l => l.addTo(layer)));
  if ($("showScen").checked) current.plans.scenario.forEach((p, i) => { if (!vis(p)) return; if (selected != null && selected !== i) return; planLine(p, COLORS[i % COLORS.length], selected === i ? 5 : 2.5, .9, hub).forEach(l => l.addTo(layer)); });
  $("sel").textContent = selected != null ? `showing ${current.plans.scenario[selected].load_id}` : "";
  if (fit && layer.getLayers().length > 1) map.fitBounds(layer.getBounds().pad(0.1));
}

init();

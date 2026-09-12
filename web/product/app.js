// P06 product frontend — talks only to /api/v2. No build step.
const $ = id => document.getElementById(id);
const api = async (path, opt = {}) => {
  const r = await fetch(path, opt);
  if (r.status === 204) return null;
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail ? (typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail)) : r.status);
  return j;
};
const J = (path, method, body) => api(path, {method, headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
const fmt = (v, d = 0) => v == null ? "–" : Number(v).toLocaleString(undefined, {maximumFractionDigits: d});
const hm = iso => iso ? new Date(iso).toLocaleTimeString("en-US", {hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "America/New_York"}) : "";
const mi = m => fmt(m / 1609.34, 1);
const COLORS = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#8c564b", "#e377c2", "#17becf", "#bcbd22", "#7f7f7f"];
const state = {scenario: null, runs: [], map: null, layer: null, rmap: null, rlayer: null, seg: null, run: null};

// ---------- nav ----------
document.querySelectorAll("nav button").forEach(b => b.onclick = () => show(b.dataset.v));
function show(v) {
  document.querySelectorAll("nav button").forEach(b => b.classList.toggle("on", b.dataset.v === v));
  document.querySelectorAll(".view").forEach(s => s.classList.toggle("on", s.id === "v-" + v));
  if (v === "result") { initMap(); loadRunList(); }
  if (v === "road") { initRoadMap(); loadAdjustments(); }
  if (v === "shipments") loadShipmentDates();
  if (v === "vehicles") loadVehicles();
  if (v === "compare") loadRunList();
}

async function init() {
  try { const h = await api("/api/health"); $("health").textContent = `api ok · valhalla ${h.valhalla ? "up" : "down"} · db ${h.db && h.db.ok ? "up" : "down"}`; } catch (e) { $("health").textContent = "api down"; }
  const depots = await api("/api/v2/master/depot");
  $("sc-depot").innerHTML = depots.map(d => `<option value="${d.depot_code}">${d.depot_code} — ${d.name}</option>`).join("");
  $("sc-date").value = new Date().toISOString().slice(0, 10);
  $("sc-create").onclick = createScenario;
  await loadScenarios();
}

// ---------- scenarios ----------
async function loadScenarios() {
  const list = await api("/api/v2/scenarios");
  $("sc-list").querySelector("tbody").innerHTML = list.map(s => `<tr data-code="${s.scenario_code}" class="${state.scenario && state.scenario.scenario_code === s.scenario_code ? "sel" : ""}">
    <td>${s.scenario_code}</td><td>${s.plan_date}</td><td><span class="badge ${s.status}">${s.status}</span></td><td class="num">${s.shipments}</td><td class="num">${s.runs}</td></tr>`).join("") || '<tr><td colspan="5" class="muted">none</td></tr>';
  $("sc-list").querySelectorAll("tr[data-code]").forEach(tr => tr.onclick = () => openScenario(tr.dataset.code));
}

async function createScenario() {
  $("sc-create-msg").textContent = "…";
  try {
    const s = await J("/api/v2/scenarios", "POST", {code: $("sc-code").value.trim(), name: $("sc-name").value || $("sc-code").value, plan_date: $("sc-date").value,
      depot_code: $("sc-depot").value, provider: $("sc-prov").value, time_limit_s: Number($("sc-tl").value || 30)});
    $("sc-create-msg").textContent = `created · ${s.populated} shipments for ${s.plan_date}`;
    await loadScenarios(); openScenario(s.scenario_code);
  } catch (e) { $("sc-create-msg").innerHTML = `<span class="err">${e.message}</span>`; }
}

async function openScenario(code) {
  const s = await api(`/api/v2/scenarios/${code}`);
  state.scenario = s;
  loadScenarios();
  const cons = s.constraints.map(c => `<tr><td><label style="margin:0"><input type="checkbox" data-c="${c.constraint_code}" ${c.enabled ? "checked" : ""}> ${c.constraint_code}</label><div class="muted">${c.name} · P${c.phase} · ${c.ctype}</div></td>
      <td><input data-p="${c.constraint_code}" value='${JSON.stringify(c.params)}' ${Object.keys(c.param_schema || {}).length ? "" : "disabled"}></td></tr>`).join("");
  const w = s.weights.map(o => `<label>${o.objective_code} <span class="muted">(${o.unit})</span><input type="number" data-w="${o.objective_code}" value="${o.weight_pct}" min="0" max="100"></label>`).join("");
  const vehicles = await api("/api/v2/master/vehicle");
  const veh = vehicles.map(v => `<label style="display:inline-block;width:31%;margin:2px 0"><input type="checkbox" data-v="${v.vehicle_code}" ${s.vehicles.includes(v.vehicle_code) ? "checked" : ""}> ${v.vehicle_code}</label>`).join("");
  const adj = s.adjustments.map(a => `<label style="margin:2px 0"><input type="checkbox" data-a="${a.adjustment_id}" ${a.enabled ? "checked" : ""}> ${a.road_name} ${a.day_of_week || "daily"} ${a.time_from.slice(0, 5)}–${a.time_to.slice(0, 5)} ×${a.factor} <span class="muted">${a.reason || ""}</span></label>`).join("") || '<div class="muted">no road adjustments defined (Road Weight tab)</div>';
  const runs = s.runs.map(r => `<tr data-run="${r.optimization_run_id}"><td>#${r.optimization_run_id}</td><td><span class="badge ${r.solver_status}">${r.solver_status}</span></td><td class="num">${fmt(r.vehicle_count)}</td><td class="num">${r.total_distance_m == null ? "–" : mi(r.total_distance_m)}</td><td class="num">${r.total_route_s == null ? "–" : fmt(r.total_route_s / 60)}</td><td class="num">${r.total_cost == null ? "–" : "$" + fmt(r.total_cost)}</td><td class="muted">${r.created_at.slice(5, 16).replace("T", " ")}</td></tr>`).join("") || '<tr><td colspan="7" class="muted">no runs</td></tr>';
  $("sc-detail").innerHTML = `
   <div class="card"><h3>${s.scenario_code} <span class="badge ${s.status}">${s.status}</span></h3>
    <div class="row"><label>name<input id="e-name" value="${s.name}"></label><label>plan date<input value="${s.plan_date}" disabled></label><label>depot<input value="${s.depot_code}" disabled></label>
     <label>provider<select id="e-prov"><option ${s.distance_provider === "VALHALLA" ? "selected" : ""}>VALHALLA</option><option ${s.distance_provider === "OSRM" ? "selected" : ""}>OSRM</option></select></label><label>time limit s<input id="e-tl" type="number" value="${s.time_limit_s}"></label></div>
    <div class="muted" style="margin-top:6px">shipments in scenario: <b>${s.shipment_count}</b> <button class="btn" id="e-populate" style="padding:1px 8px;font-size:12px">populate from ${s.plan_date}</button></div>
    <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap"><button class="btn primary" id="e-save">Save</button><button class="btn primary" id="e-run">Optimize</button><button class="btn" id="e-copy">Copy</button><button class="btn danger" id="e-del">Delete</button><span id="e-msg" class="muted"></span></div></div>
   <div class="grid" style="grid-template-columns:1fr 1fr">
    <div class="card"><h3>Constraints</h3><table><thead><tr><th>constraint</th><th>params</th></tr></thead><tbody>${cons}</tbody></table></div>
    <div><div class="card"><h3>Objective weights (sum 100)</h3>${w}</div>
         <div class="card"><h3>Vehicles (${s.vehicles.length})</h3>${veh}</div>
         <div class="card"><h3>Road adjustments</h3>${adj}</div></div>
   </div>
   <div class="card"><h3>Runs</h3><table><thead><tr><th>run</th><th>status</th><th class="num">veh</th><th class="num">mi</th><th class="num">route min</th><th class="num">cost</th><th>at</th></tr></thead><tbody id="e-runs">${runs}</tbody></table></div>`;
  $("e-save").onclick = saveScenario; $("e-run").onclick = runScenario; $("e-copy").onclick = copyScenario; $("e-del").onclick = deleteScenario; $("e-populate").onclick = async () => { const r = await api(`/api/v2/scenarios/${code}/populate`, {method: "POST"}); $("e-msg").textContent = `added ${r.added}`; openScenario(code); };
  $("e-runs").querySelectorAll("tr[data-run]").forEach(tr => tr.onclick = () => { show("result"); loadRunList().then(() => { $("run-sel").value = tr.dataset.run; loadRun(); }); });
  $("sc-detail").querySelectorAll("input[data-a]").forEach(cb => cb.onchange = () => api(`/api/v2/scenarios/${code}/adjustments/${cb.dataset.a}?enabled=${cb.checked}`, {method: "POST"}));
}

function collectScenarioEdits() {
  const constraints = {};
  document.querySelectorAll("#sc-detail input[data-c]").forEach(cb => { let params = {}; try { params = JSON.parse(document.querySelector(`#sc-detail input[data-p="${cb.dataset.c}"]`).value || "{}"); } catch (e) { throw new Error(`bad JSON params for ${cb.dataset.c}`); } constraints[cb.dataset.c] = {enabled: cb.checked, params}; });
  const weights = {};
  document.querySelectorAll("#sc-detail input[data-w]").forEach(i => { if (Number(i.value) > 0) weights[i.dataset.w] = Number(i.value); });
  const vehicles = [...document.querySelectorAll("#sc-detail input[data-v]:checked")].map(i => i.dataset.v);
  return {name: $("e-name").value, provider: $("e-prov").value, time_limit_s: Number($("e-tl").value), constraints, weights, vehicles};
}

async function saveScenario() {
  try { await J(`/api/v2/scenarios/${state.scenario.scenario_code}`, "PUT", collectScenarioEdits()); $("e-msg").textContent = "saved"; openScenario(state.scenario.scenario_code); }
  catch (e) { $("e-msg").innerHTML = `<span class="err">${e.message}</span>`; }
}

async function runScenario() {
  const code = state.scenario.scenario_code;
  try {
    await J(`/api/v2/scenarios/${code}`, "PUT", collectScenarioEdits());
    const j = await api(`/api/v2/scenarios/${code}/run`, {method: "POST"});
    $("e-msg").textContent = "optimizing…";
    const poll = async () => {
      const r = await api(`/api/v2/jobs/${j.job_id}`);
      if (r.status === "done") { $("e-msg").textContent = `done: ${r.result.status} · ${r.result.vehicles} vehicles · ${mi(r.result.total_distance_m)} mi · $${fmt(r.result.total_cost)}`; openScenario(code); }
      else if (r.status === "error") $("e-msg").innerHTML = `<span class="err">${r.error}</span>`;
      else setTimeout(poll, 1500);
    };
    poll();
  } catch (e) { $("e-msg").innerHTML = `<span class="err">${e.message}</span>`; }
}

async function copyScenario() {
  const code = prompt("new scenario code", state.scenario.scenario_code + "-COPY");
  if (!code) return;
  try { const s = await api(`/api/v2/scenarios/${state.scenario.scenario_code}/copy?new_code=${encodeURIComponent(code)}`, {method: "POST"}); await loadScenarios(); openScenario(s.scenario_code); }
  catch (e) { $("e-msg").innerHTML = `<span class="err">${e.message}</span>`; }
}

async function deleteScenario() {
  if (!confirm(`archive ${state.scenario.scenario_code}?`)) return;
  await api(`/api/v2/scenarios/${state.scenario.scenario_code}`, {method: "DELETE"});
  state.scenario = null; $("sc-detail").innerHTML = '<div class="muted">select a scenario</div>'; loadScenarios();
}

// ---------- result map ----------
function initMap() {
  if (state.map) return;
  state.map = L.map("map").setView([33.75, -84.39], 9);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {attribution: "© OpenStreetMap"}).addTo(state.map);
  state.layer = L.featureGroup().addTo(state.map);
  $("run-sel").onchange = loadRun; $("run-detail").onchange = loadRun;
}

async function loadRunList() {
  const scs = await api("/api/v2/scenarios");
  const runs = [];
  for (const s of scs) { if (s.runs) { const d = await api(`/api/v2/scenarios/${s.scenario_code}`); d.runs.forEach(r => runs.push({...r, scenario_code: s.scenario_code})); } }
  state.runs = runs;
  const ok = runs.filter(r => r.solver_status === "OPTIMAL" || r.solver_status === "FEASIBLE");   // ERROR/INFEASIBLE runs have no metrics
  const opt = r => `<option value="${r.optimization_run_id}">#${r.optimization_run_id} ${r.scenario_code} · ${r.solver_status} · ${fmt(r.vehicle_count)} veh</option>`;
  const opts = ok.map(opt).join("");
  const cur = $("run-sel").value;
  $("run-sel").innerHTML = opts; $("cmp-a").innerHTML = opts; $("cmp-b").innerHTML = opts;
  if (cur) $("run-sel").value = cur;
  if (ok.length && !state.run && document.querySelector("#v-result.on")) loadRun();
}

async function loadRun() {
  const id = $("run-sel").value;
  if (!id) return;
  $("run-meta").textContent = "loading…";
  const r = await api(`/api/v2/runs/${id}?detail=${$("run-detail").checked ? 1 : 0}`);
  state.run = r;
  $("run-meta").textContent = `${r.scenario_code} · ${r.solver_status} · ${fmt(r.vehicle_count)} vehicles · ${mi(r.total_distance_m)} mi · drive ${fmt(r.total_drive_s / 60)} min · service ${fmt(r.total_service_s / 60)} min · $${fmt(r.total_cost)}`;
  state.layer.clearLayers();
  const depot = r.routes[0] && r.routes[0].stops[0];
  if (depot) L.marker([depot.latitude, depot.longitude]).bindTooltip("depot " + depot.location_code).addTo(state.layer);
  r.routes.forEach((v, i) => {
    const color = COLORS[i % COLORS.length];
    const pts = v.stops.map(s => [s.latitude, s.longitude]);
    const road = v.legs.some(l => l.geometry) ? v.legs.map((l, k) => l.geometry || [pts[k], pts[k + 1]]) : [pts];
    L.polyline(road, {color, weight: 3, opacity: .85}).bindTooltip(`${v.vehicle_code} · ${v.shipments} shipments · ${mi(v.distance_m)} mi`).addTo(state.layer);
    let n = 0;
    v.stops.forEach(s => { if (!s.shipment_id) return; n++; L.circleMarker([s.latitude, s.longitude], {radius: 9, color, fillColor: "#fff", fillOpacity: 1, weight: 2}).bindTooltip(`${v.vehicle_code} #${n} ${s.source_ref} · ${hm(s.arrival_time)} · ${s.address_line || s.postal_code || ""}`).addTo(state.layer);
      L.marker([s.latitude, s.longitude], {icon: L.divIcon({className: "", html: `<div style="font:bold 10px system-ui;color:${color};text-align:center;width:18px;margin-left:-9px;margin-top:-6px">${n}</div>`})}).addTo(state.layer); });
  });
  if (state.layer.getLayers().length) state.map.fitBounds(state.layer.getBounds().pad(0.1));
  $("run-vehicles").querySelector("tbody").innerHTML = r.routes.map((v, i) => `<tr data-i="${i}"><td><span style="color:${COLORS[i % COLORS.length]}">■</span> ${v.vehicle_code}</td><td class="num">${v.shipments}</td><td class="num">${mi(v.distance_m)}</td><td>${hm(v.stops[0].departure_time)} → ${hm(v.stops[v.stops.length - 1].arrival_time)}</td></tr>`).join("");
  $("run-vehicles").querySelectorAll("tr[data-i]").forEach(tr => tr.onclick = () => showSeq(r.routes[Number(tr.dataset.i)]));
  if (r.routes[0]) showSeq(r.routes[0]);
  $("run-un").innerHTML = r.unassigned.length ? r.unassigned.map(u => `${u.source_ref} <span class="muted">${u.reason}</span>`).join("<br>") : "none";
}

function showSeq(v) {
  $("run-seq").querySelector("tbody").innerHTML = v.stops.map(s => `<tr><td>${s.route_sequence}</td><td>${s.shipment_id ? s.source_ref : "depot"}<div class="muted">${s.address_line || s.location_code}</div></td><td>${hm(s.arrival_time)}</td><td>${hm(s.departure_time)}</td><td class="num">${fmt(s.service_s / 60)}</td><td class="num">${mi(s.distance_from_previous_m)}</td><td class="num">${s.late_s ? fmt(s.late_s / 60) : ""}</td></tr>`).join("");
}

// ---------- shipments ----------
async function loadShipmentDates() {
  const d = await api("/api/v2/shipments/dates");
  $("sh-date").innerHTML = d.map(x => `<option value="${x.requested_date}">${x.requested_date} (${x.n})</option>`).join("");
  $("sh-date").onchange = loadShipments; $("sh-upload").onclick = uploadShipments; $("sh-refresh").onclick = refreshShipments;
  if (d.length) loadShipments();
}
async function loadShipments() {
  const rows = await api(`/api/v2/shipments?date=${$("sh-date").value}&limit=1000`);
  $("sh-list").querySelector("tbody").innerHTML = rows.map(s => `<tr><td>${s.source_ref}</td><td>${s.order_ref || ""}</td><td>${s.customer_name || s.customer_code || ""}</td><td>${s.address_line || ""}</td><td>${s.postal_code || ""}</td><td class="num">${fmt(s.weight_kg)}</td><td class="num">${fmt(s.volume_m3, 2)}</td><td class="num">${fmt(s.service_s / 60)}</td><td>${s.window_start ? hm(s.window_start) + "–" + hm(s.window_end) : ""}</td><td class="num">${s.priority ?? ""}</td><td>${s.optional_flag ? "opt" : ""}</td></tr>`).join("");
}
async function uploadShipments() {
  const f = $("sh-file").files[0]; if (!f) { alert("choose an .xlsx"); return; }
  const fd = new FormData(); fd.append("file", f);
  try { const r = await api("/api/v2/shipments/upload", {method: "POST", body: fd}); $("sh-msg").textContent = `ok: ${r.shipments} shipments, ${r.locations} locations, skipped ${JSON.stringify(r.skipped)}`; loadShipmentDates(); }
  catch (e) { $("sh-msg").innerHTML = `<span class="err">${e.message}</span>`; }
}
async function refreshShipments() {
  const j = await api("/api/v2/shipments/refresh", {method: "POST"});
  $("sh-msg").textContent = "refreshing from Blue Yonder…";
  const poll = async () => { const r = await api(`/api/v2/jobs/${j.job_id}`); if (r.status === "done") { $("sh-msg").textContent = `done: ${JSON.stringify(r.result)}`; loadShipmentDates(); } else if (r.status === "error") $("sh-msg").innerHTML = `<span class="err">${r.error}</span>`; else setTimeout(poll, 2000); };
  poll();
}

// ---------- vehicles ----------
const VT_COLS = ["type_code", "name", "capacity_kg", "capacity_m3", "max_stops", "max_route_s", "fixed_cost", "cost_per_km", "cost_per_hour"];
const V_COLS = ["vehicle_code", "name", "vehicle_type_id", "depot_id", "crew_size", "work_limit_s", "duty_limit_s"];
async function loadVehicles() {
  const [types, vehicles] = await Promise.all([api("/api/v2/master/vehicle_type"), api("/api/v2/master/vehicle")]);
  const row = (r, cols, key, table) => `<tr>${cols.map(c => `<td ${c === key ? "" : 'contenteditable="true"'} data-c="${c}">${r[c] ?? ""}</td>`).join("")}<td><button class="btn" data-save="${r[key]}" style="padding:1px 6px;font-size:11px">save</button> <button class="btn danger" data-del="${r[key]}" style="padding:1px 6px;font-size:11px">✕</button></td></tr>`;
  $("vt-list").querySelector("tbody").innerHTML = types.map(t => row(t, VT_COLS, "type_code")).join("");
  $("v-list").querySelector("tbody").innerHTML = vehicles.map(v => row(v, V_COLS, "vehicle_code")).join("");
  const wire = (tableId, cols, key, table) => {
    $(tableId).querySelectorAll("[data-save]").forEach(b => b.onclick = async () => {
      const tr = b.closest("tr"); const body = {};
      cols.forEach(c => { const v = tr.querySelector(`td[data-c="${c}"]`).textContent.trim(); if (v !== "") body[c] = isNaN(v) || c.endsWith("code") || c === "name" ? v : Number(v); });
      try { await J(`/api/v2/master/${table}`, "POST", body); $("v-msg").textContent = `saved ${body[key]}`; } catch (e) { $("v-msg").innerHTML = `<span class="err">${e.message}</span>`; }
    });
    $(tableId).querySelectorAll("[data-del]").forEach(b => b.onclick = async () => { await api(`/api/v2/master/${table}/${b.dataset.del}`, {method: "DELETE"}); loadVehicles(); });
  };
  wire("vt-list", VT_COLS, "type_code", "vehicle_type"); wire("v-list", V_COLS, "vehicle_code", "vehicle");
  $("vt-add").onclick = () => { const code = prompt("type code"); if (code) J("/api/v2/master/vehicle_type", "POST", {type_code: code, name: code}).then(loadVehicles).catch(e => alert(e.message)); };
  $("v-add").onclick = () => { const code = prompt("vehicle code"); if (code && types[0]) J("/api/v2/master/vehicle", "POST", {vehicle_code: code, vehicle_type_id: types[0].vehicle_type_id, depot_id: vehicles[0] ? vehicles[0].depot_id : 1}).then(loadVehicles).catch(e => alert(e.message)); };
}

// ---------- road weight ----------
function initRoadMap() {
  if (state.rmap) return;
  state.rmap = L.map("rmap").setView([33.75, -84.39], 10);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {attribution: "© OpenStreetMap"}).addTo(state.rmap);
  state.rlayer = L.featureGroup().addTo(state.rmap);
  state.rmap.on("click", async e => { const segs = await api(`/api/v2/segments/near?lat=${e.latlng.lat}&lon=${e.latlng.lng}`); renderSegs(segs); });
  $("seg-q").oninput = async () => { if ($("seg-q").value.length >= 2) renderSegs(await api(`/api/v2/segments?q=${encodeURIComponent($("seg-q").value)}`)); };
  $("adj-save").onclick = saveAdjustment;
}
function renderSegs(segs) {
  $("seg-list").innerHTML = segs.map(s => `<div><a href="#" data-seg="${s.segment_code}">${s.road_name}</a> <span class="muted">${s.segment_code} · ${fmt(s.length_m)} m</span></div>`).join("") || '<div class="muted">no segments yet — segments are registered when routes are computed with road geometry (Map / Result, road geometry on)</div>';
  $("seg-list").querySelectorAll("a[data-seg]").forEach(a => a.onclick = ev => { ev.preventDefault(); selectSeg(segs.find(s => s.segment_code === a.dataset.seg)); });
}
function selectSeg(s) {
  state.seg = s; $("seg-sel").innerHTML = `<b>${s.road_name}</b> <span class="muted">${s.segment_code}</span>`;
  state.rlayer.clearLayers();
  if (s.geometry) { const l = L.polyline(s.geometry, {color: "#b4552b", weight: 6}).addTo(state.rlayer); state.rmap.fitBounds(l.getBounds().pad(0.5)); }
}
async function saveAdjustment() {
  if (!state.seg) { $("adj-msg").textContent = "select a segment first"; return; }
  try {
    await J(`/api/v2/segments/${state.seg.segment_code}/adjustments`, "POST", {day_of_week: $("adj-dow").value || null, time_from: $("adj-from").value, time_to: $("adj-to").value, factor: Number($("adj-f").value), reason: $("adj-reason").value});
    $("adj-msg").textContent = "saved"; loadAdjustments();
  } catch (e) { $("adj-msg").innerHTML = `<span class="err">${e.message}</span>`; }
}
async function loadAdjustments() {
  const rows = await api("/api/v2/adjustments");
  $("adj-list").querySelector("tbody").innerHTML = rows.map(a => `<tr><td>${a.road_name}<div class="muted">${a.segment_code}</div></td><td>${a.day_of_week || "daily"}</td><td>${a.time_from.slice(0, 5)}–${a.time_to.slice(0, 5)}</td><td class="num">${a.factor}</td><td>${a.reason || ""}</td><td><button class="btn danger" data-del="${a.adjustment_id}" style="padding:1px 6px;font-size:11px">✕</button></td></tr>`).join("");
  $("adj-list").querySelectorAll("[data-del]").forEach(b => b.onclick = async () => { await api(`/api/v2/adjustments/${b.dataset.del}`, {method: "DELETE"}); loadAdjustments(); });
}

// ---------- compare ----------
$("cmp-go").onclick = async () => {
  const c = await api(`/api/v2/compare?a=${$("cmp-a").value}&b=${$("cmp-b").value}`);
  const rows = [["scenario", c.a.scenario_code, c.b.scenario_code, ""], ["status", c.a.solver_status, c.b.solver_status, ""],
    ["vehicles", c.a.vehicle_count, c.b.vehicle_count, c.delta.vehicle_count], ["distance mi", mi(c.a.total_distance_m), mi(c.b.total_distance_m), c.delta.total_distance_m == null ? "" : mi(c.delta.total_distance_m)],
    ["drive min", fmt(c.a.total_drive_s / 60), fmt(c.b.total_drive_s / 60), c.delta.total_drive_s == null ? "" : fmt(c.delta.total_drive_s / 60)], ["service min", fmt(c.a.total_service_s / 60), fmt(c.b.total_service_s / 60), c.delta.total_service_s == null ? "" : fmt(c.delta.total_service_s / 60)],
    ["route min", fmt(c.a.total_route_s / 60), fmt(c.b.total_route_s / 60), c.delta.total_route_s == null ? "" : fmt(c.delta.total_route_s / 60)], ["cost $", fmt(c.a.total_cost), fmt(c.b.total_cost), c.delta.total_cost == null ? "" : fmt(c.delta.total_cost)],
    ["unassigned", c.a.unassigned, c.b.unassigned, c.delta.unassigned]];
  $("cmp-table").querySelector("tbody").innerHTML = rows.map(r => `<tr><td>${r[0]}</td><td class="num">${r[1] ?? "–"}</td><td class="num">${r[2] ?? "–"}</td><td class="num">${r[3] ?? ""}</td></tr>`).join("");
};

init();

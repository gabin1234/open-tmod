// P06 product frontend — talks only to /api/v2. No build step.
const $ = id => document.getElementById(id);
const api = async (path, opt = {}) => {
  const r = await fetch(path, opt);
  if (r.status === 204) return null;
  const j = await r.json().catch(() => ({}));
  if (!r.ok) {
    let msg = j.detail;
    if (Array.isArray(msg)) msg = msg.map(e => `${(e.loc || []).slice(1).join(".")}: ${e.msg}`).join("; ");   // pydantic 422
    throw new Error(msg ? String(msg) : `HTTP ${r.status}`);
  }
  return j;
};
const J = (path, method, body) => api(path, {method, headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
const fmt = (v, d = 0) => v == null ? "–" : Number(v).toLocaleString(undefined, {maximumFractionDigits: d});
const hm = iso => iso ? new Date(iso).toLocaleTimeString("en-US", {hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "America/New_York"}) : "";
const mi = m => fmt(m, 1);   // distances are already miles
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
  try { const h = await api("/api/health"); $("health").textContent = `${h.version || ""} · postgres ${h.postgres && h.postgres.ok ? "up" : "down"} · valhalla ${h.valhalla ? "up" : "down"} · osrm ${h.osrm ? "up" : "down"} · blue yonder ${h.db && h.db.ok ? "up" : "down"}`; } catch (e) { $("health").textContent = "api down"; }
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
  const code = $("sc-code").value.trim();
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,60}$/.test(code)) { $("sc-create-msg").innerHTML = '<span class="err">code is required: letters, digits, . _ - (no spaces)</span>'; $("sc-code").focus(); return; }
  if (!$("sc-date").value) { $("sc-create-msg").innerHTML = '<span class="err">plan date is required</span>'; return; }
  $("sc-create-msg").textContent = "…";
  try {
    const s = await J("/api/v2/scenarios", "POST", {code, name: $("sc-name").value.trim() || code, plan_date: $("sc-date").value,
      depot_code: $("sc-depot").value, provider: "VALHALLA", time_limit_s: Number($("sc-tl").value || 30)});
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
  const runs = s.runs.map(r => `<tr data-run="${r.optimization_run_id}"><td>#${r.optimization_run_id}</td><td><span class="badge ${r.solver_status}">${r.solver_status}</span></td><td class="num">${fmt(r.vehicle_count)}</td><td class="num">${r.total_distance_mi == null ? "–" : mi(r.total_distance_mi)}</td><td class="num">${r.total_route_s == null ? "–" : fmt(r.total_route_s / 60)}</td><td class="num">${r.total_cost == null ? "–" : "$" + fmt(r.total_cost)}</td><td class="muted">${r.created_at.slice(5, 16).replace("T", " ")}</td></tr>`).join("") || '<tr><td colspan="7" class="muted">no runs</td></tr>';
  $("sc-detail").innerHTML = `
   <div class="card"><h3>${s.scenario_code} <span class="badge ${s.status}">${s.status}</span></h3>
    <div class="row"><label>name<input id="e-name" value="${s.name}"></label><label>plan date<input value="${s.plan_date}" disabled></label><label>depot<input value="${s.depot_code}" disabled></label>
     <label>road routing<input value="Valhalla · truck (${s.distance_provider})" disabled></label><label>time limit s<input id="e-tl" type="number" value="${s.time_limit_s}"></label></div>
    <label style="margin-top:6px"><input type="checkbox" id="e-multidepot" ${s.settings && s.settings.multi_depot ? "checked" : ""}> multi-depot: vehicles start and end at their own depot</label>
    <div class="muted" style="margin-top:6px">shipments in scenario: <b>${s.shipment_count}</b> <button class="btn" id="e-populate" style="padding:1px 8px;font-size:12px">populate from ${s.plan_date}</button></div>
    <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap"><button class="btn primary" id="e-save">Save</button><button class="btn primary" id="e-run">Optimize</button><button class="btn" id="e-copy">Copy</button><button class="btn danger" id="e-del">Delete</button><span id="e-msg" class="muted"></span></div></div>
   <div class="grid" style="grid-template-columns:1fr 1fr">
    <div class="card"><h3>Constraints</h3><table><thead><tr><th>constraint</th><th>params</th></tr></thead><tbody>${cons}</tbody></table></div>
    <div><div class="card"><h3>Objective weights (sum 100)</h3>${w}</div>
         <div class="card"><h3>Vehicles (${s.vehicles.length})</h3>${veh}</div>
         <div class="card"><h3>Road adjustments</h3>${adj}</div></div>
   </div>
   <div class="card"><h3>Shipments in scenario (<span id="e-shcount">${s.shipment_count}</span>)</h3>
    <div class="row" style="align-items:end;margin-bottom:6px"><label>add by date<input id="e-add-date" type="date" value="${s.plan_date}"></label><button class="btn" id="e-add-date-btn">Add date</button>
     <label>add by import batch<select id="e-add-batch"></select></label><button class="btn" id="e-add-batch-btn">Add batch</button><button class="btn danger" id="e-clear-btn">Remove all</button><span id="e-sh-msg" class="muted"></span></div>
    <div class="scroll" style="max-height:32vh"><table id="e-shipments"><thead><tr><th>ref</th><th>date</th><th>kind</th><th>customer</th><th>zip</th><th class="num">lb</th><th class="num">svc min</th><th>window</th><th>batch</th><th></th></tr></thead><tbody></tbody></table></div></div>
   <div class="card"><h3>Runs</h3><table><thead><tr><th>run</th><th>status</th><th class="num">veh</th><th class="num">mi</th><th class="num">route min</th><th class="num">cost</th><th>at</th></tr></thead><tbody id="e-runs">${runs}</tbody></table></div>`;
  loadScenarioShipments(code);
  $("e-save").onclick = saveScenario; $("e-run").onclick = runScenario; $("e-copy").onclick = copyScenario; $("e-del").onclick = deleteScenario; $("e-populate").onclick = async () => { const r = await api(`/api/v2/scenarios/${code}/populate`, {method: "POST"}); $("e-msg").textContent = `added ${r.added}`; openScenario(code); };
  $("e-runs").querySelectorAll("tr[data-run]").forEach(tr => tr.onclick = () => { show("result"); loadRunList().then(() => { $("run-sel").value = tr.dataset.run; loadRun(); }); });
  $("sc-detail").querySelectorAll("input[data-a]").forEach(cb => cb.onchange = () => api(`/api/v2/scenarios/${code}/adjustments/${cb.dataset.a}?enabled=${cb.checked}`, {method: "POST"}));
}

async function loadScenarioShipments(code) {
  const [rows, batches] = await Promise.all([api(`/api/v2/scenarios/${encodeURIComponent(code)}/shipments`), api("/api/v2/shipments/batches")]);
  $("e-shcount").textContent = rows.length;
  $("e-add-batch").innerHTML = batches.map(b => `<option value="${b.batch}">${b.batch} (${b.n})</option>`).join("") || '<option value="">(no batches)</option>';
  $("e-shipments").querySelector("tbody").innerHTML = rows.map(s => `<tr><td>${s.source_ref}</td><td>${s.requested_date}</td><td>${s.kind === "DELIVERY" ? "" : s.kind}</td><td>${s.customer_name || ""}</td><td>${s.postal_code || ""}</td><td class="num">${fmt(s.weight_lb)}</td><td class="num">${fmt(s.service_s / 60)}</td><td>${s.window_start ? hm(s.window_start) + "–" + hm(s.window_end) : ""}</td><td class="muted">${(s.source_batch || "").split(":").slice(0, 2).join(":")}</td><td><button class="btn danger" data-rm="${s.shipment_id}" style="padding:0 6px;font-size:11px">✕</button></td></tr>`).join("") || '<tr><td colspan="10" class="muted">no shipments — add by date or batch</td></tr>';
  const msg = t => { $("e-sh-msg").textContent = t; };
  const add = async body => { try { const r = await J(`/api/v2/scenarios/${encodeURIComponent(code)}/shipments`, "POST", body); msg(`added ${r.added} (total ${r.total})`); loadScenarioShipments(code); loadScenarios(); } catch (e) { $("e-sh-msg").innerHTML = `<span class="err">${e.message}</span>`; } };
  $("e-add-date-btn").onclick = () => add({date: $("e-add-date").value});
  $("e-add-batch-btn").onclick = () => $("e-add-batch").value ? add({batch: $("e-add-batch").value}) : msg("no batch selected");
  $("e-clear-btn").onclick = async () => { if (!confirm("remove all shipments from this scenario?")) return; await api(`/api/v2/scenarios/${encodeURIComponent(code)}/shipments`, {method: "DELETE"}); loadScenarioShipments(code); loadScenarios(); };
  $("e-shipments").querySelectorAll("[data-rm]").forEach(b => b.onclick = async () => { await api(`/api/v2/scenarios/${encodeURIComponent(code)}/shipments/${b.dataset.rm}`, {method: "DELETE"}); loadScenarioShipments(code); loadScenarios(); });
}

function collectScenarioEdits() {
  const constraints = {};
  document.querySelectorAll("#sc-detail input[data-c]").forEach(cb => { let params = {}; try { params = JSON.parse(document.querySelector(`#sc-detail input[data-p="${cb.dataset.c}"]`).value || "{}"); } catch (e) { throw new Error(`bad JSON params for ${cb.dataset.c}`); } constraints[cb.dataset.c] = {enabled: cb.checked, params}; });
  const weights = {};
  document.querySelectorAll("#sc-detail input[data-w]").forEach(i => { if (Number(i.value) > 0) weights[i.dataset.w] = Number(i.value); });
  const vehicles = [...document.querySelectorAll("#sc-detail input[data-v]:checked")].map(i => i.dataset.v);
  const settings = {...(state.scenario.settings || {}), multi_depot: $("e-multidepot").checked};
  const wsum = Object.values(weights).reduce((a, b) => a + b, 0);
  if (Math.abs(wsum - 100) > 0.01) throw new Error(`objective weights must sum to 100 (now ${wsum})`);
  if (!vehicles.length) throw new Error("select at least one vehicle");
  return {name: $("e-name").value.trim(), provider: "VALHALLA", time_limit_s: Number($("e-tl").value) || 30, constraints, weights, vehicles, settings};
}

async function saveScenario() {
  if (!$("e-name").value.trim()) { $("e-msg").innerHTML = '<span class="err">name is required</span>'; return; }
  try { await J(`/api/v2/scenarios/${encodeURIComponent(state.scenario.scenario_code)}`, "PUT", collectScenarioEdits()); $("e-msg").textContent = "saved"; await openScenario(state.scenario.scenario_code); $("e-msg").textContent = "saved"; }
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
      if (r.status === "done") { $("e-msg").textContent = `done: ${r.result.status} · ${r.result.vehicles} vehicles · ${mi(r.result.total_distance_mi)} mi · $${fmt(r.result.total_cost)}`; openScenario(code); }
      else if (r.status === "error") $("e-msg").innerHTML = `<span class="err">${r.error}</span>`;
      else setTimeout(poll, 1500);
    };
    poll();
  } catch (e) { $("e-msg").innerHTML = `<span class="err">${e.message}</span>`; }
}

async function copyScenario() {
  const code = (prompt("new scenario code", state.scenario.scenario_code + "-COPY") || "").trim();
  if (!code) return;
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,60}$/.test(code)) { $("e-msg").innerHTML = '<span class="err">code: letters, digits, . _ - only</span>'; return; }
  try { const s = await api(`/api/v2/scenarios/${state.scenario.scenario_code}/copy?new_code=${encodeURIComponent(code)}`, {method: "POST"}); await loadScenarios(); openScenario(s.scenario_code); }
  catch (e) { $("e-msg").innerHTML = `<span class="err">${e.message}</span>`; }
}

async function deleteScenario() {
  const code = state.scenario && state.scenario.scenario_code;
  if (!code) { $("e-msg").innerHTML = '<span class="err">no scenario selected</span>'; return; }
  if (!confirm(`Archive scenario ${code}? Its runs stay in the database but it disappears from the list.`)) return;
  try { await api(`/api/v2/scenarios/${encodeURIComponent(code)}`, {method: "DELETE"}); }
  catch (e) { $("e-msg").innerHTML = `<span class="err">${e.message}</span>`; return; }
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
  $("run-meta").textContent = `${r.scenario_code} · ${r.solver_status} · ${fmt(r.vehicle_count)} vehicles · ${mi(r.total_distance_mi)} mi · drive ${fmt(r.total_drive_s / 60)} min · service ${fmt(r.total_service_s / 60)} min · $${fmt(r.total_cost)}`;
  state.layer.clearLayers();
  const depots = {};
  r.routes.forEach(v => { const d = v.stops[0]; if (d) depots[d.location_code] = d; });
  Object.values(depots).forEach(d => L.marker([d.latitude, d.longitude]).bindTooltip("depot " + d.location_code).addTo(state.layer));
  r.routes.forEach((v, i) => {
    const color = COLORS[i % COLORS.length];
    const pts = v.stops.map(s => [s.latitude, s.longitude]);
    const road = v.legs.some(l => l.geometry) ? v.legs.map((l, k) => l.geometry || [pts[k], pts[k + 1]]) : [pts];
    L.polyline(road, {color, weight: 3, opacity: .85}).bindTooltip(`${v.vehicle_code} · ${v.shipments} shipments · ${mi(v.distance_mi)} mi`).addTo(state.layer);
    let n = 0;
    v.stops.forEach(s => { if (!s.shipment_id) return; n++; L.circleMarker([s.latitude, s.longitude], {radius: 9, color, fillColor: "#fff", fillOpacity: 1, weight: 2}).bindTooltip(`${v.vehicle_code} #${n} ${s.stop_kind === "PICKUP" ? "pickup " : ""}${s.source_ref} · ${hm(s.arrival_time)} · ${s.address_line || s.postal_code || ""}`).addTo(state.layer);
      L.marker([s.latitude, s.longitude], {icon: L.divIcon({className: "", html: `<div style="font:bold 10px system-ui;color:${color};text-align:center;width:18px;margin-left:-9px;margin-top:-6px">${n}</div>`})}).addTo(state.layer); });
  });
  if (state.layer.getLayers().length) state.map.fitBounds(state.layer.getBounds().pad(0.1));
  $("run-vehicles").querySelector("tbody").innerHTML = r.routes.map((v, i) => `<tr data-i="${i}"><td><span style="color:${COLORS[i % COLORS.length]}">■</span> ${v.vehicle_code}</td><td class="num">${v.shipments}</td><td class="num">${mi(v.distance_mi)}</td><td>${hm(v.stops[0].departure_time)} → ${hm(v.stops[v.stops.length - 1].arrival_time)}</td></tr>`).join("");
  $("run-vehicles").querySelectorAll("tr[data-i]").forEach(tr => tr.onclick = () => showSeq(r.routes[Number(tr.dataset.i)]));
  if (r.routes[0]) showSeq(r.routes[0]);
  $("run-un").innerHTML = r.unassigned.length ? r.unassigned.map(u => `${u.source_ref} <span class="muted">${u.reason}</span>`).join("<br>") : "none";
}

function showSeq(v) {
  $("run-seq").querySelector("tbody").innerHTML = v.stops.map(s => `<tr><td>${s.route_sequence}</td><td>${s.shipment_id ? (s.stop_kind === "PICKUP" ? "▲ " : "") + s.source_ref : "depot"}<div class="muted">${s.address_line || s.location_code}${s.load_after_lb != null && s.stop_kind !== "DELIVERY" ? " · load " + fmt(s.load_after_lb) + " lb" : ""}</div></td><td>${hm(s.arrival_time)}</td><td>${hm(s.departure_time)}</td><td class="num">${fmt(s.service_s / 60)}</td><td class="num">${mi(s.distance_from_previous_mi)}</td><td class="num">${s.late_s ? fmt(s.late_s / 60) : ""}</td></tr>`).join("");
}

// ---------- shipments ----------
async function loadShipmentDates() {
  const [d, b] = await Promise.all([api("/api/v2/shipments/dates"), api("/api/v2/shipments/batches")]);
  $("sh-date").innerHTML = '<option value="">(any date)</option>' + d.map(x => `<option value="${x.requested_date}">${x.requested_date} (${x.n})</option>`).join("");
  $("sh-batch").innerHTML = '<option value="">(all)</option>' + b.map(x => `<option value="${x.batch}">${x.batch} · ${x.n} shpm · ${x.date_from}${x.date_to !== x.date_from ? "…" + x.date_to : ""}</option>`).join("");
  $("sh-date").onchange = loadShipments; $("sh-batch").onchange = loadShipments; $("sh-upload").onclick = uploadShipments; $("sh-refresh").onclick = refreshShipments; $("sh-mk-btn").onclick = createScenarioFromUpload;
  if (d.length) { if (!$("sh-date").value && d.length) $("sh-date").value = d[d.length - 1].requested_date; loadShipments(); }
}
async function loadShipments() {
  const q = [$("sh-date").value ? `date=${$("sh-date").value}` : "", $("sh-batch").value ? `batch=${encodeURIComponent($("sh-batch").value)}` : ""].filter(Boolean).join("&");
  const rows = await api(`/api/v2/shipments?${q}&limit=1000`);
  $("sh-list").querySelector("tbody").innerHTML = rows.map(s => `<tr><td>${s.source_ref}</td><td>${s.order_ref || ""}</td><td>${s.kind === "DELIVERY" ? "" : s.kind + (s.pickup_postal_code ? " from " + s.pickup_postal_code : "")}</td><td>${s.customer_name || s.customer_code || ""}</td><td>${s.address_line || ""}</td><td>${s.postal_code || ""}</td><td class="num">${fmt(s.weight_lb)}</td><td class="num">${fmt(s.volume_cuft, 1)}</td><td class="num">${fmt(s.service_s / 60)}</td><td>${s.window_start ? hm(s.window_start) + "–" + hm(s.window_end) : ""}</td><td class="num">${s.priority ?? ""}</td><td>${s.optional_flag ? "opt" : ""}</td></tr>`).join("");
}
async function uploadShipments() {
  const f = $("sh-file").files[0]; if (!f) { $("sh-msg").innerHTML = '<span class="err">choose an .xlsx file first</span>'; return; }
  const fd = new FormData(); fd.append("file", f);
  try {
    const r = await api("/api/v2/shipments/upload", {method: "POST", body: fd});
    $("sh-msg").textContent = `ok: ${r.shipments} shipments, ${r.locations} locations, dates ${r.dates.map(x => x.date + "(" + x.n + ")").join(", ")}${Object.keys(r.skipped).length ? " · skipped " + JSON.stringify(r.skipped) : ""}`;
    state.lastBatch = r.batch;
    $("sh-mk-code").value = "SC-" + (r.dates[0] ? r.dates[0].date : "UPLOAD") + "-" + f.name.replace(/\.xlsx$/i, "").replace(/[^A-Za-z0-9]+/g, "-").slice(0, 20).toUpperCase();
    $("sh-mk").style.display = ""; $("sh-mk-msg").textContent = "";
    await loadShipmentDates(); $("sh-batch").value = r.batch; $("sh-date").value = ""; loadShipments();
  } catch (e) { $("sh-msg").innerHTML = `<span class="err">${e.message}</span>`; }
}
async function createScenarioFromUpload() {
  const batch = state.lastBatch || $("sh-batch").value;
  if (!batch) { $("sh-mk-msg").innerHTML = '<span class="err">upload a file or pick a batch first</span>'; return; }
  const code = $("sh-mk-code").value.trim();
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,60}$/.test(code)) { $("sh-mk-msg").innerHTML = '<span class="err">scenario code: letters, digits, . _ -</span>'; return; }
  try {
    const s = await J("/api/v2/scenarios", "POST", {code, name: code, batch, depot_code: $("sc-depot").value, provider: "VALHALLA", time_limit_s: 30});
    $("sh-mk-msg").textContent = `created ${s.scenario_code} with ${s.shipment_count} shipments (plan date ${s.plan_date})`;
    await loadScenarios(); show("scenarios"); openScenario(s.scenario_code);
  } catch (e) { $("sh-mk-msg").innerHTML = `<span class="err">${e.message}</span>`; }
}
async function refreshShipments() {
  const j = await api("/api/v2/shipments/refresh", {method: "POST"});
  $("sh-msg").textContent = "refreshing from Blue Yonder…";
  const poll = async () => { const r = await api(`/api/v2/jobs/${j.job_id}`); if (r.status === "done") { $("sh-msg").textContent = `done: ${JSON.stringify(r.result)}`; loadShipmentDates(); } else if (r.status === "error") $("sh-msg").innerHTML = `<span class="err">${r.error}</span>`; else setTimeout(poll, 2000); };
  poll();
}

// ---------- vehicles ----------
const VT_COLS = ["type_code", "name", "capacity_lb", "capacity_cuft", "max_stops", "max_route_s", "fixed_cost", "cost_per_mi", "cost_per_hour"];
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
  const err = e => { $("v-msg").innerHTML = `<span class="err">${e.message}</span>`; };
  $("vt-add").onclick = () => { const code = (prompt("type code") || "").trim(); if (code) J("/api/v2/master/vehicle_type", "POST", {type_code: code, name: code}).then(loadVehicles).catch(err); };
  $("v-add").onclick = () => { const code = (prompt("vehicle code") || "").trim(); if (code && types[0]) J("/api/v2/master/vehicle", "POST", {vehicle_code: code, vehicle_type_id: types[0].vehicle_type_id, depot_id: vehicles[0] ? vehicles[0].depot_id : 1}).then(loadVehicles).catch(err); };
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
  $("seg-list").innerHTML = segs.map(s => `<div><a href="#" data-seg="${s.segment_code}">${s.road_name}</a> <span class="muted">${s.segment_code} · ${fmt(s.length_mi)} m</span></div>`).join("") || '<div class="muted">no segments yet — segments are registered when routes are computed with road geometry (Map / Result, road geometry on)</div>';
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
    ["vehicles", c.a.vehicle_count, c.b.vehicle_count, c.delta.vehicle_count], ["distance mi", mi(c.a.total_distance_mi), mi(c.b.total_distance_mi), c.delta.total_distance_mi == null ? "" : mi(c.delta.total_distance_mi)],
    ["drive min", fmt(c.a.total_drive_s / 60), fmt(c.b.total_drive_s / 60), c.delta.total_drive_s == null ? "" : fmt(c.delta.total_drive_s / 60)], ["service min", fmt(c.a.total_service_s / 60), fmt(c.b.total_service_s / 60), c.delta.total_service_s == null ? "" : fmt(c.delta.total_service_s / 60)],
    ["route min", fmt(c.a.total_route_s / 60), fmt(c.b.total_route_s / 60), c.delta.total_route_s == null ? "" : fmt(c.delta.total_route_s / 60)], ["cost $", fmt(c.a.total_cost), fmt(c.b.total_cost), c.delta.total_cost == null ? "" : fmt(c.delta.total_cost)],
    ["unassigned", c.a.unassigned, c.b.unassigned, c.delta.unassigned]];
  $("cmp-table").querySelector("tbody").innerHTML = rows.map(r => `<tr><td>${r[0]}</td><td class="num">${r[1] ?? "–"}</td><td class="num">${r[2] ?? "–"}</td><td class="num">${r[3] ?? ""}</td></tr>`).join("");
};

init();

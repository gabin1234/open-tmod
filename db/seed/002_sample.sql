-- Sample master data (P01). Atlanta LMD hub, 10 trucks from LMD_MST_TRUCK, constraint/objective catalogue, Silver Avenue example.
SET search_path TO tmod, public;

INSERT INTO source_system (system_code, name, read_only, connection_ref) VALUES
  ('BLUE_YONDER', 'Blue Yonder TMS (AICTMSNQ)', true, 'TMOD_ORA_DSN'),
  ('XLSX', 'Planner spreadsheet upload', true, NULL)
ON CONFLICT (system_code) DO NOTHING;

INSERT INTO location (location_code, name, city, state_code, postal_code, latitude, longitude, geocode_source) VALUES
  ('HUB-LPHB-30260', 'Atlanta LMD Hub (Morrow)', 'Morrow', 'GA', '30260', 33.587165, -84.334307, 'ZCTA')
ON CONFLICT (location_code) DO NOTHING;

INSERT INTO depot (depot_code, name, location_id, open_time, close_time)
SELECT 'LPHB-30260', 'Atlanta LMD Hub', location_id, '08:00', '18:00' FROM location WHERE location_code='HUB-LPHB-30260'
ON CONFLICT (depot_code) DO NOTHING;

INSERT INTO vehicle_type (type_code, name, capacity_kg, capacity_m3, max_stops, max_route_s, fixed_cost, cost_per_km, cost_per_hour, osrm_profile) VALUES
  ('BOX26', '26ft box truck, 2-man crew', 4500, 45, 12, 36000, 250.00, 1.20, 45.00, 'truck')
ON CONFLICT (type_code) DO NOTHING;

INSERT INTO vehicle (vehicle_code, name, vehicle_type_id, depot_id, crew_size, work_limit_s, duty_limit_s)
SELECT 'T' || lpad(g::text, 2, '0'), 'ATL Truck ' || lpad(g::text, 2, '0'), vt.vehicle_type_id, d.depot_id, 2, 500*60, 600*60
FROM generate_series(1,10) g, vehicle_type vt, depot d WHERE vt.type_code='BOX26' AND d.depot_code='LPHB-30260'
ON CONFLICT (vehicle_code) DO NOTHING;

INSERT INTO vehicle_availability (vehicle_id, day_of_week, shift_start, shift_end)
SELECT v.vehicle_id, NULL, '08:00', '18:00' FROM vehicle v
WHERE NOT EXISTS (SELECT 1 FROM vehicle_availability a WHERE a.vehicle_id=v.vehicle_id);

INSERT INTO service_time_rule (rule_code, description, customer_type, product_category, stop_base_s, per_unit_s, priority) VALUES
  ('STOP_BASE', 'Base time per stop (LMD STOP_BASE_MIN=20)', NULL, NULL, 20*60, 0, 100),
  ('WHG_INSTALL', 'White-glove install per unit', NULL, 'WHG', 0, 45*60, 10)
ON CONFLICT (rule_code) DO NOTHING;

INSERT INTO constraint_def (constraint_code, name, ctype, phase, param_schema, default_params, description) VALUES
  ('CAPACITY_WEIGHT', 'Vehicle weight capacity', 'HARD', 1, '{}', '{}', 'sum(shipment.weight_kg) <= vehicle_type.capacity_kg'),
  ('CAPACITY_VOLUME', 'Vehicle volume capacity', 'HARD', 1, '{}', '{}', 'sum(volume_m3) <= capacity_m3'),
  ('SERVICE_TIME',    'Service time at stops', 'HARD', 1, '{}', '{}', 'stop_base + per-unit from service_time_rule'),
  ('TIME_WINDOW',     'Delivery time window', 'HARD', 1, '{"max_wait_s":"integer"}', '{"max_wait_s": 7200}', 'arrival within [window_start, window_end], waiting allowed'),
  ('WORK_LIMIT',      'Daily service-time budget', 'HARD', 1, '{}', '{}', 'sum(service_s) <= vehicle.work_limit_s'),
  ('DUTY_LIMIT',      'Daily on-duty budget (max route duration)', 'HARD', 2, '{}', '{}', 'drive+service+wait <= vehicle.duty_limit_s / type.max_route_s'),
  ('MAX_DISTANCE',    'Max route distance', 'HARD', 2, '{}', '{}', 'sum(distance_m) <= vehicle_type.max_distance_m'),
  ('VEHICLE_COMPAT',  'Vehicle/customer/product compatibility', 'HARD', 2, '{}', '{}', 'vehicle_restriction rows'),
  ('OPTIONAL_DROP',   'Optional shipments may be dropped', 'SOFT', 2, '{"default_penalty":"number"}', '{"default_penalty": 500}', 'shipment.optional_flag with drop_penalty'),
  ('SOFT_TIME_WINDOW','Soft window with lateness penalty', 'SOFT', 3, '{"penalty_per_min":"number"}', '{"penalty_per_min": 2.0}', 'lateness allowed, penalised in objective'),
  ('ROAD_ADJUSTMENT', 'Time-of-day road factors', 'HARD', 3, '{}', '{}', 'apply road_adjustment factors to travel time')
ON CONFLICT (constraint_code) DO NOTHING;

INSERT INTO objective_def (objective_code, name, unit, phase) VALUES
  ('COST', 'Total cost (fixed + per km + per hour)', 'currency', 1),
  ('TRAVEL_TIME', 'Total drive time', 's', 1),
  ('VEHICLE_COUNT', 'Vehicles used', 'count', 1),
  ('DISTANCE', 'Total distance', 'm', 1),
  ('LATENESS', 'Total lateness', 's', 3)
ON CONFLICT (objective_code) DO NOTHING;

INSERT INTO road_segment (segment_code, road_name, osm_way_id, length_m, geometry) VALUES
  ('SEG-000001', 'Silver Avenue', 123456789, 1420.0, '[[33.60,-84.34],[33.61,-84.33]]')
ON CONFLICT (segment_code) DO NOTHING;

INSERT INTO road_adjustment (segment_id, day_of_week, time_from, time_to, factor, reason)
SELECT s.segment_id, d, '07:00', '09:00', 1.50, 'Morning congestion'
FROM road_segment s, unnest(ARRAY['MON','TUE','WED','THU','FRI']::day_of_week[]) d
WHERE s.segment_code='SEG-000001'
  AND NOT EXISTS (SELECT 1 FROM road_adjustment a WHERE a.segment_id=s.segment_id AND a.day_of_week=d);

INSERT INTO scenario (scenario_code, name, plan_date, depot_id, distance_provider, time_limit_s, status)
SELECT 'SC-2026-09-15-BASE', 'Atlanta 2026-09-15 baseline', '2026-09-15', depot_id, 'OSRM', 30, 'DRAFT' FROM depot WHERE depot_code='LPHB-30260'
ON CONFLICT (scenario_code) DO NOTHING;

INSERT INTO scenario_vehicle (scenario_id, vehicle_id)
SELECT s.scenario_id, v.vehicle_id FROM scenario s, vehicle v WHERE s.scenario_code='SC-2026-09-15-BASE'
ON CONFLICT DO NOTHING;

INSERT INTO scenario_constraint (scenario_id, constraint_code, enabled_flag, params)
SELECT s.scenario_id, c.constraint_code, c.phase = 1, c.default_params FROM scenario s, constraint_def c WHERE s.scenario_code='SC-2026-09-15-BASE'
ON CONFLICT DO NOTHING;

INSERT INTO scenario_objective_weight (scenario_id, objective_code, weight_pct)
SELECT s.scenario_id, o.code, o.w FROM scenario s, (VALUES ('COST',50.0),('TRAVEL_TIME',30.0),('VEHICLE_COUNT',20.0)) o(code,w)
WHERE s.scenario_code='SC-2026-09-15-BASE'
ON CONFLICT DO NOTHING;

INSERT INTO scenario_road_adjustment (scenario_id, adjustment_id)
SELECT s.scenario_id, a.adjustment_id FROM scenario s, road_adjustment a WHERE s.scenario_code='SC-2026-09-15-BASE'
ON CONFLICT DO NOTHING;

-- Blue Yonder LMD_SHIPMENT -> shipment mapping (seed for P02)
INSERT INTO source_mapping_master (source_system_id, source_table, source_column, target_table, target_column, transformation_rule, sort_order)
SELECT ss.source_system_id, m.st, m.sc, m.tt, m.tc, m.rule, m.ord FROM source_system ss, (VALUES
  ('TMS_IF.LMD_SHIPMENT','SHIPMENT_ID','shipment','source_ref',NULL,1),
  ('TMS_IF.LMD_SHIPMENT','ORDER_NO','shipment','order_ref',NULL,2),
  ('TMS_IF.LMD_SHIPMENT','APPT_DT','shipment','requested_date','date',3),
  ('TMS_IF.LMD_SHIPMENT','APPT_WINDOW','shipment','window_start','window_start_of:APPT_DT',4),
  ('TMS_IF.LMD_SHIPMENT','APPT_WINDOW','shipment','window_end','window_end_of:APPT_DT',5),
  ('TMS_IF.LMD_SHIPMENT','CHARGE_MIN','shipment','service_s','min_to_s',6),
  ('TMS_IF.LMD_SHIPMENT','TOT_WGT','shipment','weight_kg','lb_to_kg',7),
  ('TMS_IF.LMD_SHIPMENT','TOT_CUFT','shipment','volume_m3','cuft_to_m3',8),
  ('TMS_IF.LMD_SHIPMENT','ITEM_CNT','shipment','pieces','int',9),
  ('TMS_IF.LMD_SHIPMENT','LOAD_ID','shipment','source_load_ref',NULL,10),
  ('TMS_IF.LMD_SHIPMENT','APPT_TRUCK_ID','shipment','source_vehicle_ref',NULL,11),
  ('TMS_IF.LMD_SHIPMENT','SHIP_TO_ID','location','location_code','prefix:BY-',12),
  ('TMS_IF.LMD_SHIPMENT','ADDR_LINE','location','address_line',NULL,13),
  ('TMS_IF.LMD_SHIPMENT','ZIP_CD','location','postal_code','zip5',14),
  ('TMS_IF.LMD_SHIPMENT','LAT','location','latitude','float',15),
  ('TMS_IF.LMD_SHIPMENT','LON','location','longitude','float',16),
  ('TMS_IF.LMD_SHIPMENT','CUST_CD','customer','customer_code',NULL,17),
  ('TMS_IF.LMD_SHIPMENT','SHIP_TO_NM','customer','name',NULL,18)
) m(st,sc,tt,tc,rule,ord) WHERE ss.system_code='BLUE_YONDER'
ON CONFLICT DO NOTHING;

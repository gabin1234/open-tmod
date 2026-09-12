-- Open T-Modeler product schema (P01, v2.0 imperial). Idempotent. Units: miles, seconds, lb, cuft, USD, timestamptz.
-- Domains: master | source | constraint | scenario | routing | result
CREATE SCHEMA IF NOT EXISTS tmod;
SET search_path TO tmod, public;

DO $$ BEGIN
  CREATE TYPE shipment_kind AS ENUM ('DELIVERY','PICKUP','PICKUP_DELIVERY');
  CREATE TYPE day_of_week AS ENUM ('MON','TUE','WED','THU','FRI','SAT','SUN');
  CREATE TYPE solver_status AS ENUM ('QUEUED','RUNNING','OPTIMAL','FEASIBLE','INFEASIBLE','ERROR','CANCELLED');
  CREATE TYPE constraint_type AS ENUM ('HARD','SOFT');
  CREATE TYPE scenario_status AS ENUM ('DRAFT','READY','RUNNING','DONE','ARCHIVED');
  CREATE TYPE distance_provider AS ENUM ('OSRM','VALHALLA','PCMILER','HAVERSINE','MANUAL');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ---------- master ----------
CREATE TABLE IF NOT EXISTS location (
  location_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  location_code   text NOT NULL UNIQUE,
  name            text,
  address_line    text,
  city            text,
  state_code      text,
  postal_code     text,
  country_code    text NOT NULL DEFAULT 'US',
  latitude        double precision,
  longitude       double precision,
  geocode_source  text,
  active_flag     boolean NOT NULL DEFAULT true,
  effective_from  date NOT NULL DEFAULT CURRENT_DATE,
  effective_to    date,
  created_at timestamptz NOT NULL DEFAULT now(), created_by text NOT NULL DEFAULT current_user,
  updated_at timestamptz NOT NULL DEFAULT now(), updated_by text NOT NULL DEFAULT current_user,
  CHECK (latitude IS NULL OR latitude BETWEEN -90 AND 90),
  CHECK (longitude IS NULL OR longitude BETWEEN -180 AND 180)
);
CREATE INDEX IF NOT EXISTS ix_location_postal ON location (postal_code);

CREATE TABLE IF NOT EXISTS depot (
  depot_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  depot_code      text NOT NULL UNIQUE,
  name            text NOT NULL,
  location_id     bigint NOT NULL REFERENCES location(location_id),
  open_time       time NOT NULL DEFAULT '08:00',
  close_time      time NOT NULL DEFAULT '18:00',
  active_flag     boolean NOT NULL DEFAULT true,
  effective_from  date NOT NULL DEFAULT CURRENT_DATE,
  effective_to    date,
  created_at timestamptz NOT NULL DEFAULT now(), created_by text NOT NULL DEFAULT current_user,
  updated_at timestamptz NOT NULL DEFAULT now(), updated_by text NOT NULL DEFAULT current_user
);

CREATE TABLE IF NOT EXISTS vehicle_type (
  vehicle_type_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  type_code       text NOT NULL UNIQUE,
  name            text NOT NULL,
  capacity_lb     numeric(12,2),
  capacity_cuft     numeric(12,3),
  max_stops       integer,
  max_route_s     integer,           -- max route duration
  max_distance_mi numeric(10,2),
  fixed_cost      numeric(12,2) NOT NULL DEFAULT 0,
  cost_per_mi     numeric(10,4) NOT NULL DEFAULT 0,   -- USD per mile
  cost_per_hour   numeric(10,4) NOT NULL DEFAULT 0,
  osrm_profile    text NOT NULL DEFAULT 'car',   -- routing profile (car/truck)
  active_flag     boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(), created_by text NOT NULL DEFAULT current_user,
  updated_at timestamptz NOT NULL DEFAULT now(), updated_by text NOT NULL DEFAULT current_user
);

CREATE TABLE IF NOT EXISTS vehicle (
  vehicle_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  vehicle_code    text NOT NULL UNIQUE,
  name            text,
  vehicle_type_id bigint NOT NULL REFERENCES vehicle_type(vehicle_type_id),
  depot_id        bigint NOT NULL REFERENCES depot(depot_id),
  crew_size       smallint NOT NULL DEFAULT 1,
  work_limit_s    integer,           -- service-time budget per day (null = type/unbounded)
  duty_limit_s    integer,           -- total on-duty budget per day
  active_flag     boolean NOT NULL DEFAULT true,
  effective_from  date NOT NULL DEFAULT CURRENT_DATE,
  effective_to    date,
  created_at timestamptz NOT NULL DEFAULT now(), created_by text NOT NULL DEFAULT current_user,
  updated_at timestamptz NOT NULL DEFAULT now(), updated_by text NOT NULL DEFAULT current_user
);
CREATE INDEX IF NOT EXISTS ix_vehicle_depot ON vehicle (depot_id) WHERE active_flag;

CREATE TABLE IF NOT EXISTS vehicle_availability (
  availability_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  vehicle_id      bigint NOT NULL REFERENCES vehicle(vehicle_id) ON DELETE CASCADE,
  day_of_week     day_of_week,       -- null = every day
  shift_start     time NOT NULL,
  shift_end       time NOT NULL,
  effective_from  date NOT NULL DEFAULT CURRENT_DATE,
  effective_to    date,
  active_flag     boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(), created_by text NOT NULL DEFAULT current_user,
  CHECK (shift_end > shift_start)
);

CREATE TABLE IF NOT EXISTS customer (
  customer_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  customer_code   text NOT NULL UNIQUE,
  name            text NOT NULL,
  customer_type   text,
  default_location_id bigint REFERENCES location(location_id),
  priority        smallint NOT NULL DEFAULT 5,   -- 1 = highest
  active_flag     boolean NOT NULL DEFAULT true,
  effective_from  date NOT NULL DEFAULT CURRENT_DATE,
  effective_to    date,
  created_at timestamptz NOT NULL DEFAULT now(), created_by text NOT NULL DEFAULT current_user,
  updated_at timestamptz NOT NULL DEFAULT now(), updated_by text NOT NULL DEFAULT current_user
);

CREATE TABLE IF NOT EXISTS product (
  product_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  product_code    text NOT NULL UNIQUE,
  name            text,
  category        text,
  unit_weight_lb  numeric(10,3),
  unit_volume_cuft  numeric(10,4),
  install_s       integer NOT NULL DEFAULT 0,   -- per-unit service time
  active_flag     boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(), created_by text NOT NULL DEFAULT current_user,
  updated_at timestamptz NOT NULL DEFAULT now(), updated_by text NOT NULL DEFAULT current_user
);

CREATE TABLE IF NOT EXISTS service_time_rule (
  rule_id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  rule_code       text NOT NULL UNIQUE,
  description     text,
  customer_type   text,              -- null = any
  product_category text,             -- null = any
  stop_base_s     integer NOT NULL DEFAULT 0,   -- once per stop
  per_unit_s      integer NOT NULL DEFAULT 0,   -- per piece
  priority        smallint NOT NULL DEFAULT 100, -- lower wins
  active_flag     boolean NOT NULL DEFAULT true,
  effective_from  date NOT NULL DEFAULT CURRENT_DATE,
  effective_to    date,
  created_at timestamptz NOT NULL DEFAULT now(), created_by text NOT NULL DEFAULT current_user,
  updated_at timestamptz NOT NULL DEFAULT now(), updated_by text NOT NULL DEFAULT current_user
);

-- ---------- source ----------
CREATE TABLE IF NOT EXISTS source_system (
  source_system_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  system_code     text NOT NULL UNIQUE,        -- BLUE_YONDER, XLSX, ...
  name            text NOT NULL,
  read_only       boolean NOT NULL DEFAULT true,
  connection_ref  text,                        -- name of env/secret, never the secret
  active_flag     boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(), created_by text NOT NULL DEFAULT current_user
);

CREATE TABLE IF NOT EXISTS source_mapping_master (
  mapping_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  source_system_id bigint NOT NULL REFERENCES source_system(source_system_id),
  source_table    text NOT NULL,
  source_column   text NOT NULL,
  target_table    text NOT NULL,
  target_column   text NOT NULL,
  transformation_rule text,                    -- e.g. 'zip5', 'lb_to_kg', 'min_to_s', 'upper', 'date', 'const:LPHB-30260'
  sort_order      integer NOT NULL DEFAULT 0,
  active_flag     boolean NOT NULL DEFAULT true,
  effective_from  date NOT NULL DEFAULT CURRENT_DATE,
  effective_to    date,
  created_at timestamptz NOT NULL DEFAULT now(), created_by text NOT NULL DEFAULT current_user,
  updated_at timestamptz NOT NULL DEFAULT now(), updated_by text NOT NULL DEFAULT current_user,
  UNIQUE (source_system_id, source_table, source_column, target_table, target_column)
);

CREATE TABLE IF NOT EXISTS shipment (
  shipment_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  source_system_id bigint NOT NULL REFERENCES source_system(source_system_id),
  source_ref      text NOT NULL,               -- BY SHIPMENT_ID / xlsx shipment_id
  order_ref       text,
  kind            shipment_kind NOT NULL DEFAULT 'DELIVERY',
  customer_id     bigint REFERENCES customer(customer_id),
  pickup_location_id   bigint REFERENCES location(location_id),   -- null = depot
  delivery_location_id bigint NOT NULL REFERENCES location(location_id),
  requested_date  date NOT NULL,
  window_start    timestamptz,
  window_end      timestamptz,
  service_s       integer,                     -- explicit; null = derive via service_time_rule
  weight_lb       numeric(12,3) NOT NULL DEFAULT 0,
  volume_cuft       numeric(12,4) NOT NULL DEFAULT 0,
  pieces          integer NOT NULL DEFAULT 1,
  priority        smallint,
  optional_flag   boolean NOT NULL DEFAULT false,
  drop_penalty    numeric(12,2),
  source_load_ref text,                        -- BY LOAD_ID (baseline)
  source_vehicle_ref text,                     -- BY truck
  source_snapshot jsonb,                       -- raw mapped row for audit
  active_flag     boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(), created_by text NOT NULL DEFAULT current_user,
  updated_at timestamptz NOT NULL DEFAULT now(), updated_by text NOT NULL DEFAULT current_user,
  UNIQUE (source_system_id, source_ref),
  CHECK (window_end IS NULL OR window_start IS NULL OR window_end > window_start)
);
CREATE INDEX IF NOT EXISTS ix_shipment_date ON shipment (requested_date);
CREATE INDEX IF NOT EXISTS ix_shipment_delivery_loc ON shipment (delivery_location_id);

CREATE TABLE IF NOT EXISTS shipment_item (
  shipment_item_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  shipment_id     bigint NOT NULL REFERENCES shipment(shipment_id) ON DELETE CASCADE,
  product_id      bigint REFERENCES product(product_id),
  product_code_raw text,
  quantity        numeric(12,3) NOT NULL DEFAULT 1,
  weight_lb       numeric(12,3),
  volume_cuft       numeric(12,4),
  created_at timestamptz NOT NULL DEFAULT now()
);

-- ---------- constraint / objective ----------
CREATE TABLE IF NOT EXISTS constraint_def (
  constraint_code text PRIMARY KEY,            -- CAPACITY_WEIGHT, TIME_WINDOW, ...
  name            text NOT NULL,
  ctype           constraint_type NOT NULL DEFAULT 'HARD',
  phase           smallint NOT NULL DEFAULT 1,
  param_schema    jsonb NOT NULL DEFAULT '{}'::jsonb,   -- declares expected params, e.g. {"penalty_per_s": "number"}
  default_params  jsonb NOT NULL DEFAULT '{}'::jsonb,
  description     text,
  active_flag     boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(), created_by text NOT NULL DEFAULT current_user
);

CREATE TABLE IF NOT EXISTS objective_def (
  objective_code  text PRIMARY KEY,            -- COST, TRAVEL_TIME, VEHICLE_COUNT, DISTANCE, LATENESS
  name            text NOT NULL,
  unit            text NOT NULL,               -- currency | s | count | m
  phase           smallint NOT NULL DEFAULT 1,
  description     text,
  active_flag     boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(), created_by text NOT NULL DEFAULT current_user
);

CREATE TABLE IF NOT EXISTS vehicle_restriction (
  restriction_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  vehicle_type_id bigint REFERENCES vehicle_type(vehicle_type_id),   -- null = specific vehicle below
  vehicle_id      bigint REFERENCES vehicle(vehicle_id),
  customer_id     bigint REFERENCES customer(customer_id),
  location_id     bigint REFERENCES location(location_id),
  product_category text,
  allow_flag      boolean NOT NULL DEFAULT false,   -- false = forbidden, true = required/allowed
  reason          text,
  active_flag     boolean NOT NULL DEFAULT true,
  effective_from  date NOT NULL DEFAULT CURRENT_DATE,
  effective_to    date,
  created_at timestamptz NOT NULL DEFAULT now(), created_by text NOT NULL DEFAULT current_user,
  CHECK (vehicle_type_id IS NOT NULL OR vehicle_id IS NOT NULL),
  CHECK (customer_id IS NOT NULL OR location_id IS NOT NULL OR product_category IS NOT NULL)
);

-- ---------- scenario ----------
CREATE TABLE IF NOT EXISTS scenario (
  scenario_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  scenario_code   text NOT NULL UNIQUE,
  name            text NOT NULL,
  description     text,
  plan_date       date NOT NULL,
  depot_id        bigint NOT NULL REFERENCES depot(depot_id),
  distance_provider distance_provider NOT NULL DEFAULT 'OSRM',
  time_limit_s    integer NOT NULL DEFAULT 30,
  status          scenario_status NOT NULL DEFAULT 'DRAFT',
  copied_from_id  bigint REFERENCES scenario(scenario_id),
  settings        jsonb NOT NULL DEFAULT '{}'::jsonb,   -- misc toggles (e.g. allow_multi_depot)
  active_flag     boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(), created_by text NOT NULL DEFAULT current_user,
  updated_at timestamptz NOT NULL DEFAULT now(), updated_by text NOT NULL DEFAULT current_user
);
CREATE INDEX IF NOT EXISTS ix_scenario_date ON scenario (plan_date);

CREATE TABLE IF NOT EXISTS scenario_shipment (
  scenario_id     bigint NOT NULL REFERENCES scenario(scenario_id) ON DELETE CASCADE,
  shipment_id     bigint NOT NULL REFERENCES shipment(shipment_id),
  override_window_start timestamptz,
  override_window_end   timestamptz,
  override_service_s    integer,
  override_priority     smallint,
  PRIMARY KEY (scenario_id, shipment_id)
);

CREATE TABLE IF NOT EXISTS scenario_vehicle (
  scenario_id     bigint NOT NULL REFERENCES scenario(scenario_id) ON DELETE CASCADE,
  vehicle_id      bigint NOT NULL REFERENCES vehicle(vehicle_id),
  override_shift_start time,
  override_shift_end   time,
  override_capacity_lb numeric(12,2),
  PRIMARY KEY (scenario_id, vehicle_id)
);

CREATE TABLE IF NOT EXISTS scenario_constraint (
  scenario_id     bigint NOT NULL REFERENCES scenario(scenario_id) ON DELETE CASCADE,
  constraint_code text NOT NULL REFERENCES constraint_def(constraint_code),
  enabled_flag    boolean NOT NULL DEFAULT true,
  params          jsonb NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (scenario_id, constraint_code)
);

CREATE TABLE IF NOT EXISTS scenario_objective_weight (
  scenario_id     bigint NOT NULL REFERENCES scenario(scenario_id) ON DELETE CASCADE,
  objective_code  text NOT NULL REFERENCES objective_def(objective_code),
  weight_pct      numeric(5,2) NOT NULL CHECK (weight_pct >= 0 AND weight_pct <= 100),
  PRIMARY KEY (scenario_id, objective_code)
);

-- ---------- routing ----------
CREATE TABLE IF NOT EXISTS road_segment (
  segment_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  segment_code    text NOT NULL UNIQUE,        -- what the user sees next to the road name
  road_name       text NOT NULL,
  osm_way_id      bigint,
  osrm_edge_ref   text,                        -- provider-internal edge/node pair
  from_node       bigint,
  to_node         bigint,
  length_mi       numeric(10,4),
  geometry        jsonb,                       -- [[lat,lon],...] polyline for the map
  created_at timestamptz NOT NULL DEFAULT now(), created_by text NOT NULL DEFAULT current_user
);
CREATE INDEX IF NOT EXISTS ix_road_segment_way ON road_segment (osm_way_id);
CREATE INDEX IF NOT EXISTS ix_road_segment_name ON road_segment (road_name);

CREATE TABLE IF NOT EXISTS road_adjustment (
  adjustment_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  segment_id      bigint NOT NULL REFERENCES road_segment(segment_id) ON DELETE CASCADE,
  day_of_week     day_of_week,                 -- null = every day
  time_from       time NOT NULL DEFAULT '00:00',
  time_to         time NOT NULL DEFAULT '24:00',
  factor          numeric(6,3) NOT NULL CHECK (factor > 0),   -- travel time multiplier, e.g. 1.50
  reason          text,
  active_flag     boolean NOT NULL DEFAULT true,
  effective_from  date NOT NULL DEFAULT CURRENT_DATE,
  effective_to    date,
  created_at timestamptz NOT NULL DEFAULT now(), created_by text NOT NULL DEFAULT current_user,
  updated_at timestamptz NOT NULL DEFAULT now(), updated_by text NOT NULL DEFAULT current_user
);
CREATE INDEX IF NOT EXISTS ix_road_adjustment_segment ON road_adjustment (segment_id) WHERE active_flag;

CREATE TABLE IF NOT EXISTS scenario_road_adjustment (
  scenario_id     bigint NOT NULL REFERENCES scenario(scenario_id) ON DELETE CASCADE,
  adjustment_id   bigint NOT NULL REFERENCES road_adjustment(adjustment_id),
  enabled_flag    boolean NOT NULL DEFAULT true,
  PRIMARY KEY (scenario_id, adjustment_id)
);

CREATE TABLE IF NOT EXISTS distance_cache (
  from_location_id bigint NOT NULL REFERENCES location(location_id),
  to_location_id   bigint NOT NULL REFERENCES location(location_id),
  provider        distance_provider NOT NULL,
  profile         text NOT NULL DEFAULT 'car',
  distance_mi     numeric(10,3) NOT NULL,
  duration_s      integer NOT NULL,
  segment_ids     bigint[],                    -- traversed road_segment ids when known (for adjustments)
  geometry        jsonb,
  computed_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (from_location_id, to_location_id, provider, profile)
);

-- ---------- result ----------
CREATE TABLE IF NOT EXISTS optimization_run (
  optimization_run_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  scenario_id     bigint NOT NULL REFERENCES scenario(scenario_id) ON DELETE CASCADE,
  start_time      timestamptz,
  end_time        timestamptz,
  solver_status   solver_status NOT NULL DEFAULT 'QUEUED',
  objective_value numeric(16,4),
  vehicle_count   integer,
  total_distance_mi numeric(12,2),
  total_drive_s     bigint,
  total_service_s   bigint,
  total_route_s     bigint,
  total_cost      numeric(14,2),
  engine          text NOT NULL DEFAULT 'ortools-routing',
  engine_params   jsonb NOT NULL DEFAULT '{}'::jsonb,
  error_message   text,
  created_at timestamptz NOT NULL DEFAULT now(), created_by text NOT NULL DEFAULT current_user
);
CREATE INDEX IF NOT EXISTS ix_optrun_scenario ON optimization_run (scenario_id, created_at DESC);

CREATE TABLE IF NOT EXISTS optimization_route (
  route_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  optimization_run_id bigint NOT NULL REFERENCES optimization_run(optimization_run_id) ON DELETE CASCADE,
  vehicle_id      bigint NOT NULL REFERENCES vehicle(vehicle_id),
  route_sequence  integer NOT NULL,            -- 0 = depot start, n+1 = depot end
  stop_location_id bigint NOT NULL REFERENCES location(location_id),
  shipment_id     bigint REFERENCES shipment(shipment_id),   -- null for depot rows
  arrival_time    timestamptz,
  departure_time  timestamptz,
  wait_s          integer NOT NULL DEFAULT 0,
  service_s       integer NOT NULL DEFAULT 0,
  distance_from_previous_mi numeric(10,3) NOT NULL DEFAULT 0,
  travel_time_from_previous_s integer NOT NULL DEFAULT 0,
  load_after_lb   numeric(12,3),
  late_s          integer NOT NULL DEFAULT 0,  -- arrival beyond window_end
  UNIQUE (optimization_run_id, vehicle_id, route_sequence)
);
CREATE INDEX IF NOT EXISTS ix_optroute_run_vehicle ON optimization_route (optimization_run_id, vehicle_id);

CREATE TABLE IF NOT EXISTS optimization_unassigned (
  optimization_run_id bigint NOT NULL REFERENCES optimization_run(optimization_run_id) ON DELETE CASCADE,
  shipment_id     bigint NOT NULL REFERENCES shipment(shipment_id),
  reason          text,
  penalty_applied numeric(12,2),
  PRIMARY KEY (optimization_run_id, shipment_id)
);

-- updated_at trigger for tables that have it
CREATE OR REPLACE FUNCTION tmod.touch_updated_at() RETURNS trigger AS $$
BEGIN NEW.updated_at := now(); NEW.updated_by := current_user; RETURN NEW; END $$ LANGUAGE plpgsql;
DO $$ DECLARE t text; BEGIN
  FOR t IN SELECT table_name FROM information_schema.columns WHERE table_schema='tmod' AND column_name='updated_at' LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS trg_touch ON tmod.%I; CREATE TRIGGER trg_touch BEFORE UPDATE ON tmod.%I FOR EACH ROW EXECUTE FUNCTION tmod.touch_updated_at()', t, t);
  END LOOP; END $$;

-- v1.1 (P03): per-segment durations alongside segment_ids so time-of-day adjustments can be applied per edge
ALTER TABLE distance_cache ADD COLUMN IF NOT EXISTS segment_durations_s integer[];

-- v1.2 (P07): stop kind on route rows (DEPOT | PICKUP | DELIVERY)
ALTER TABLE optimization_route ADD COLUMN IF NOT EXISTS stop_kind text NOT NULL DEFAULT 'DELIVERY';

-- v1.3 (P09): historical/global travel-time profile (applies where no segment-level adjustment exists)
CREATE TABLE IF NOT EXISTS traffic_profile (
  profile_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  day_of_week     day_of_week,                 -- null = every day
  time_from       time NOT NULL,
  time_to         time NOT NULL,
  factor          numeric(6,3) NOT NULL CHECK (factor > 0),
  source          text NOT NULL DEFAULT 'SAMPLE',   -- SAMPLE | HISTORICAL | MANUAL
  region_code     text,                        -- null = global
  active_flag     boolean NOT NULL DEFAULT true,
  effective_from  date NOT NULL DEFAULT CURRENT_DATE,
  effective_to    date,
  created_at timestamptz NOT NULL DEFAULT now(), created_by text NOT NULL DEFAULT current_user,
  updated_at timestamptz NOT NULL DEFAULT now(), updated_by text NOT NULL DEFAULT current_user
);

-- v2.1 (P13): import batch id on shipments (xlsx upload / Blue Yonder refresh)
ALTER TABLE shipment ADD COLUMN IF NOT EXISTS source_batch text;
CREATE INDEX IF NOT EXISTS ix_shipment_batch ON shipment (source_batch);

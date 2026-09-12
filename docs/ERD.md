# ERD — Open T-Modeler product schema v1 (P01)

27 tables, 6 domains. Source of truth: `db/ddl/001_schema.sql`.

```mermaid
erDiagram
  %% master
  location ||--o{ depot : "location_id"
  location ||--o{ customer : "default_location_id"
  depot ||--o{ vehicle : "depot_id"
  vehicle_type ||--o{ vehicle : "vehicle_type_id"
  vehicle ||--o{ vehicle_availability : "vehicle_id"
  %% source
  source_system ||--o{ source_mapping_master : "source_system_id"
  source_system ||--o{ shipment : "source_system_id"
  customer ||--o{ shipment : "customer_id"
  location ||--o{ shipment : "delivery_location_id / pickup_location_id"
  shipment ||--o{ shipment_item : "shipment_id"
  product ||--o{ shipment_item : "product_id"
  %% constraint
  vehicle_type ||--o{ vehicle_restriction : "vehicle_type_id"
  vehicle ||--o{ vehicle_restriction : "vehicle_id"
  customer ||--o{ vehicle_restriction : "customer_id"
  %% scenario
  depot ||--o{ scenario : "depot_id"
  scenario ||--o{ scenario_shipment : "scenario_id"
  shipment ||--o{ scenario_shipment : "shipment_id"
  scenario ||--o{ scenario_vehicle : "scenario_id"
  vehicle ||--o{ scenario_vehicle : "vehicle_id"
  scenario ||--o{ scenario_constraint : "scenario_id"
  constraint_def ||--o{ scenario_constraint : "constraint_code"
  scenario ||--o{ scenario_objective_weight : "scenario_id"
  objective_def ||--o{ scenario_objective_weight : "objective_code"
  scenario ||--o{ scenario_road_adjustment : "scenario_id"
  %% routing
  road_segment ||--o{ road_adjustment : "segment_id"
  road_adjustment ||--o{ scenario_road_adjustment : "adjustment_id"
  location ||--o{ distance_cache : "from/to_location_id"
  %% result
  scenario ||--o{ optimization_run : "scenario_id"
  optimization_run ||--o{ optimization_route : "optimization_run_id"
  vehicle ||--o{ optimization_route : "vehicle_id"
  location ||--o{ optimization_route : "stop_location_id"
  shipment ||--o{ optimization_route : "shipment_id"
  optimization_run ||--o{ optimization_unassigned : "optimization_run_id"
  shipment ||--o{ optimization_unassigned : "shipment_id"

  shipment { bigint shipment_id PK  text source_ref  shipment_kind kind  date requested_date  timestamptz window_start  timestamptz window_end  int service_s  numeric weight_lb  numeric volume_cuft  bool optional_flag  numeric drop_penalty  text source_load_ref }
  vehicle { bigint vehicle_id PK  text vehicle_code  int work_limit_s  int duty_limit_s }
  vehicle_type { bigint vehicle_type_id PK  numeric capacity_lb  numeric capacity_cuft  int max_stops  int max_route_s  int max_distance_mi  numeric fixed_cost  numeric cost_per_mi  numeric cost_per_hour  text osrm_profile }
  scenario { bigint scenario_id PK  text scenario_code  date plan_date  distance_provider distance_provider  int time_limit_s  scenario_status status  jsonb settings }
  scenario_constraint { text constraint_code FK  bool enabled_flag  jsonb params }
  scenario_objective_weight { text objective_code FK  numeric weight_pct }
  constraint_def { text constraint_code PK  constraint_type ctype  smallint phase  jsonb param_schema  jsonb default_params }
  road_segment { bigint segment_id PK  text segment_code  text road_name  bigint osm_way_id  text osrm_edge_ref  jsonb geometry }
  road_adjustment { bigint adjustment_id PK  day_of_week day_of_week  time time_from  time time_to  numeric factor  text reason }
  distance_cache { distance_provider provider  text profile  int distance_mi  int duration_s  bigint_arr segment_ids }
  optimization_run { bigint optimization_run_id PK  solver_status solver_status  numeric objective_value  int vehicle_count  bigint total_distance_mi  bigint total_drive_s  bigint total_service_s  bigint total_route_s  numeric total_cost }
  optimization_route { bigint route_id PK  int route_sequence  timestamptz arrival_time  timestamptz departure_time  int wait_s  int service_s  int distance_from_previous_mi  int travel_time_from_previous_s  int late_s }
```

Conventions: identity bigint PKs + natural-key UNIQUE; audit (created/updated at/by) and effective_from/to + active_flag on masters; units mi / s / lb / cuft / USD (imperial, v2.0); ON DELETE CASCADE only for scenario and result children.

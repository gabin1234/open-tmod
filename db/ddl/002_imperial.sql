-- P12: metric -> imperial (US customary). Idempotent: renames only when the old column still exists.
SET search_path TO tmod, public;
DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT * FROM (VALUES
    ('vehicle_type','capacity_kg','capacity_lb','*2.20462'), ('vehicle_type','capacity_m3','capacity_cuft','*35.3147'),
    ('vehicle_type','max_distance_m','max_distance_mi','/1609.344'), ('vehicle_type','cost_per_km','cost_per_mi','*1.609344'),
    ('product','unit_weight_kg','unit_weight_lb','*2.20462'), ('product','unit_volume_m3','unit_volume_cuft','*35.3147'),
    ('shipment','weight_kg','weight_lb','*2.20462'), ('shipment','volume_m3','volume_cuft','*35.3147'),
    ('shipment_item','weight_kg','weight_lb','*2.20462'), ('shipment_item','volume_m3','volume_cuft','*35.3147'),
    ('scenario_vehicle','override_capacity_kg','override_capacity_lb','*2.20462'),
    ('optimization_route','load_after_kg','load_after_lb','*2.20462'), ('optimization_route','distance_from_previous_m','distance_from_previous_mi','/1609.344'),
    ('optimization_run','total_distance_m','total_distance_mi','/1609.344'),
    ('distance_cache','distance_m','distance_mi','/1609.344'), ('road_segment','length_m','length_mi','/1609.344')
  ) AS t(tbl, old, new, expr) LOOP
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='tmod' AND table_name=r.tbl AND column_name=r.old) THEN
      EXECUTE format('ALTER TABLE tmod.%I ALTER COLUMN %I TYPE numeric(14,4) USING (%I %s)', r.tbl, r.old, r.old, r.expr);
      EXECUTE format('ALTER TABLE tmod.%I RENAME COLUMN %I TO %I', r.tbl, r.old, r.new);
    END IF;
  END LOOP;
END $$;
UPDATE source_mapping_master SET transformation_rule='float' WHERE transformation_rule IN ('lb_to_kg','cuft_to_m3');
UPDATE source_mapping_master SET target_column='weight_lb' WHERE target_column='weight_kg';
UPDATE source_mapping_master SET target_column='volume_cuft' WHERE target_column='volume_m3';

-- P14: objective label units
UPDATE objective_def SET unit='mi' WHERE objective_code='DISTANCE' AND unit='m';

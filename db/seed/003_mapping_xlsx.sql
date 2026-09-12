SET search_path TO tmod, public;
INSERT INTO source_mapping_master (source_system_id, source_table, source_column, target_table, target_column, transformation_rule, sort_order)
SELECT ss.source_system_id, m.st, m.sc, m.tt, m.tc, m.rule, m.ord FROM source_system ss, (VALUES
  ('Shipments','shipment_id','shipment','source_ref',NULL,1),
  ('Shipments','purchase_order','shipment','order_ref',NULL,2),
  ('Shipments','delivery_date','shipment','requested_date','date',3),
  ('Shipments','window','shipment','window_start','window_start_of:delivery_date',4),
  ('Shipments','window','shipment','window_end','window_end_of:delivery_date',5),
  ('Shipments','service_minutes','shipment','service_s','min_to_s',6),
  ('Shipments','weight_lb','shipment','weight_kg','lb_to_kg',7),
  ('Shipments','volume_cuft','shipment','volume_m3','cuft_to_m3',8),
  ('Shipments','pieces','shipment','pieces','int',9),
  ('Shipments','load_id','shipment','source_load_ref',NULL,10),
  ('Shipments','truck_id','shipment','source_vehicle_ref',NULL,11),
  ('Shipments','address','location','address_line',NULL,12),
  ('Shipments','address','location','location_code','locid:zip',13),
  ('Shipments','city','location','city',NULL,14),
  ('Shipments','state','location','state_code','upper',15),
  ('Shipments','zip','location','postal_code','zip5',16),
  ('Shipments','latitude','location','latitude','float',17),
  ('Shipments','longitude','location','longitude','float',18),
  ('Shipments','customer_name','customer','name',NULL,19),
  ('Shipments','customer_name','customer','customer_code','slug',20)
) m(st,sc,tt,tc,rule,ord) WHERE ss.system_code='XLSX'
ON CONFLICT DO NOTHING;

"""P01 tests: run against a throwaway postgres container (docker). Skipped when docker is unavailable."""
import shutil
import time

import pytest

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available")
def test_ddl_seed_and_constraints(pg):
    import psycopg
    from tmod.product.db import init
    info = init(pg, seed=True, drop=True)
    assert info["tables"] == 28 and info["enums"] == 6 and info["foreign_keys"] >= 30, info
    assert init(pg, seed=True) == info  # idempotent DDL + seed
    with psycopg.connect(pg, autocommit=True) as con:
        con.execute("SET search_path TO tmod")
        q = lambda s: con.execute(s).fetchone()[0]  # noqa: E731
        assert q("SELECT count(*) FROM vehicle") == 10
        assert q("SELECT count(*) FROM constraint_def") == 12 and q("SELECT count(*) FROM objective_def") == 5
        assert q("SELECT count(*) FROM scenario") == 1 and q("SELECT count(*) FROM road_adjustment") == 5
        assert q("SELECT count(*) FROM source_mapping_master") == 18
        assert q("SELECT sum(weight_pct) FROM scenario_objective_weight") == 100
        assert q("SELECT count(*) FROM scenario_constraint WHERE enabled_flag") == 5  # phase-1 defaults on
        # FK violation
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            con.execute("INSERT INTO vehicle (vehicle_code, vehicle_type_id, depot_id) VALUES ('X', 999, 999)")
        # unique source ref
        loc = q("SELECT location_id FROM location LIMIT 1")
        ss = q("SELECT source_system_id FROM source_system WHERE system_code='XLSX'")
        con.execute("INSERT INTO shipment (source_system_id, source_ref, delivery_location_id, requested_date) VALUES (%s,'S1',%s,'2026-09-15')", (ss, loc))
        with pytest.raises(psycopg.errors.UniqueViolation):
            con.execute("INSERT INTO shipment (source_system_id, source_ref, delivery_location_id, requested_date) VALUES (%s,'S1',%s,'2026-09-15')", (ss, loc))
        # window check + updated_at trigger
        with pytest.raises(psycopg.errors.CheckViolation):
            con.execute("INSERT INTO shipment (source_system_id, source_ref, delivery_location_id, requested_date, window_start, window_end) VALUES (%s,'S2',%s,'2026-09-15','2026-09-15 12:00','2026-09-15 08:00')", (ss, loc))
        before = q("SELECT updated_at FROM vehicle WHERE vehicle_code='T01'")
        time.sleep(0.01)
        con.execute("UPDATE vehicle SET name='x' WHERE vehicle_code='T01'")
        assert q("SELECT updated_at FROM vehicle WHERE vehicle_code='T01'") > before
        # cascade: deleting scenario removes children, keeps masters
        con.execute("DELETE FROM scenario")
        assert q("SELECT count(*) FROM scenario_vehicle") == 0 and q("SELECT count(*) FROM vehicle") == 10

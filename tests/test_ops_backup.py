import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tmod.product.db import init


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available")
def test_backup_and_restore(pg, tmp_path):
    import psycopg
    init(pg, seed=True, drop=True)
    env = {**os.environ, "TMOD_PG_DSN": pg, "TMOD_PG_CONTAINER": "tmod-pg-test", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
    if shutil.which("pg_dump"):
        env["PATH"] = "/nonexistent"   # force the docker exec path so the test container is used
    r = subprocess.run(["bash", "ops/backup.sh", str(tmp_path)], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    dumps = list(tmp_path.glob("tmod-*.dump"))
    assert dumps and dumps[0].stat().st_size > 10000 and list(tmp_path.glob("data-*.tgz"))
    with psycopg.connect(pg, autocommit=True) as con:
        con.execute("DROP SCHEMA tmod CASCADE")
    r = subprocess.run(["bash", "ops/restore.sh", str(dumps[0])], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    with psycopg.connect(pg) as con:
        assert con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='tmod' AND table_type='BASE TABLE'").fetchone()[0] == 28
        assert con.execute("SELECT count(*) FROM tmod.vehicle").fetchone()[0] == 10

"""Shared fixtures: throwaway postgres in docker for product-track tests."""
import shutil
import subprocess
import time

import pytest

PORT = 55433
DSN = f"postgresql://tmod:tmod@localhost:{PORT}/tmod"


@pytest.fixture(scope="session")
def pg():
    name = "tmod-pg-test"
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    r = subprocess.run(["docker", "run", "-d", "--name", name, "-e", "POSTGRES_DB=tmod", "-e", "POSTGRES_USER=tmod",
                        "-e", "POSTGRES_PASSWORD=tmod", "-p", f"{PORT}:5432", "postgres:16"], capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"docker run failed: {r.stderr[:200]}")
    import psycopg
    for _ in range(60):
        try:
            psycopg.connect(DSN, connect_timeout=2).close()
            break
        except Exception:
            time.sleep(1)
    else:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        pytest.skip("postgres did not come up")
    yield DSN
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)



"""End-to-end verification harness.

Starts an embedded Postgres, runs the ETL twice (to prove idempotency),
exercises every API endpoint with FastAPI's TestClient, and prints the
results. This is a developer convenience — production deployments use
the real `docker compose up` flow described in the README.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

import pgserver  # noqa: E402

PGDATA = Path("/tmp/pgdata")
PGDATA.mkdir(exist_ok=True)
server = pgserver.get_server(str(PGDATA), cleanup_mode=None)
db_uri = server.get_uri()

# Convert plain `postgresql://` to SQLAlchemy's psycopg-3 dialect.
sqla_uri = db_uri.replace("postgresql://", "postgresql+psycopg://", 1)
os.environ["DATABASE_URL"] = sqla_uri
os.environ["DATA_DIR"] = str(REPO / "data")

print(f"[verify] DATABASE_URL={sqla_uri}")

# Reset any cached settings/engines that might have been imported earlier.
from app.config import get_settings  # noqa: E402
get_settings.cache_clear()

from app.db import init_db, SessionLocal  # noqa: E402
from app.etl.load_program_data import run_etl  # noqa: E402
from app.models import (  # noqa: E402
    EtlRunLog,
    Milestone,
    Program,
    Project,
    ProjectAnalytics,
    Risk,
)
from sqlalchemy import func, select  # noqa: E402


def counts() -> dict:
    with SessionLocal() as s:
        return {
            "programs": s.scalar(select(func.count()).select_from(Program)),
            "projects": s.scalar(select(func.count()).select_from(Project)),
            "milestones": s.scalar(select(func.count()).select_from(Milestone)),
            "risks": s.scalar(select(func.count()).select_from(Risk)),
            "analytics": s.scalar(select(func.count()).select_from(ProjectAnalytics)),
            "etl_runs": s.scalar(select(func.count()).select_from(EtlRunLog)),
        }


# Wipe the failed-records sink so we observe only this run's output.
failed_path = REPO / "data" / "failed" / "failed_records.jsonl"
if failed_path.exists():
    failed_path.write_text("")

init_db()

# First run
summary1 = run_etl()
print("\n[verify] --- ETL run #1 summary ---")
print(json.dumps(summary1, default=str, indent=2))
print("[verify] table counts after run #1:", counts())

# Second run — must produce identical row counts (idempotency check).
summary2 = run_etl()
print("\n[verify] --- ETL run #2 summary ---")
print(json.dumps(summary2, default=str, indent=2))
counts_after_2 = counts()
print("[verify] table counts after run #2:", counts_after_2)

# Show the failed-records file
print("\n[verify] --- failed_records.jsonl (head) ---")
if failed_path.exists():
    with failed_path.open() as fh:
        for line in fh.readlines()[:10]:
            print(line.rstrip())

# API exercise via TestClient.
from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


def show(label, resp):
    print(f"\n[verify] --- {label} ({resp.status_code}) ---")
    try:
        body = resp.json()
        # Trim long arrays for readability.
        if isinstance(body, list) and len(body) > 6:
            body = body[:6] + [f"... +{len(body) - 6} more"]
        print(json.dumps(body, default=str, indent=2))
    except Exception:
        print(resp.text)


show("GET /health", client.get("/health"))
show("GET /analytics/summary", client.get("/analytics/summary"))
show("GET /analytics/programs", client.get("/analytics/programs"))
show("GET /analytics/projects/at-risk", client.get("/analytics/projects/at-risk"))
show("GET /projects/PRJ-2002", client.get("/projects/PRJ-2002"))
show("GET /projects/PRJ-NOPE (expect 404)", client.get("/projects/PRJ-NOPE"))
show("POST /etl/run", client.post("/etl/run"))

print("\n[verify] DONE")

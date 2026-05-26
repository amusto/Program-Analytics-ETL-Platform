"""FastAPI entrypoint for the Program Analytics platform.

Exposes:

  GET  /health                       - liveness + DB check + last ETL timestamp
  GET  /analytics/summary            - top-level KPI numbers
  GET  /analytics/programs           - per-program rollup
  GET  /analytics/projects/at-risk   - projects flagged AT_RISK or CRITICAL
  GET  /projects/{project_id}        - drill-down detail with milestones + risks
  POST /etl/run                      - kick off a synchronous ETL run

The ETL run endpoint is intentionally synchronous for this POC. In
production, this call would enqueue an Airflow / Step Functions run and
return a run_id the caller can poll.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text

from app.api.analytics import router as analytics_router
from app.api.projects import router as projects_router
from app.db import SessionLocal, init_db
from app.etl.load_program_data import run_etl
from app.models import EtlRunLog
from app.schemas import EtlRunResponse, HealthResponse

logger = logging.getLogger("api")

app = FastAPI(
    title="Program Analytics ETL Platform",
    description=(
        "Miniature enterprise analytics platform demonstrating ETL ingestion, "
        "Pydantic validation, idempotent PostgreSQL loads, and FastAPI analytics "
        "endpoints over normalized program/project/milestone/risk data."
    ),
    version="0.1.0",
)

# Permissive CORS for the dev dashboard. In production this list would be
# locked down to the dashboard origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analytics_router)
app.include_router(projects_router)


@app.on_event("startup")
def _ensure_schema() -> None:
    """Create tables if they do not already exist.

    Safe to call repeatedly; SQLAlchemy create_all is a no-op when the
    schema is current. In production this would be replaced by Alembic
    migrations run as a separate step in the deploy pipeline.
    """
    init_db()


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    db_status = "ok"
    last_run = None
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
            last_run = session.scalar(
                select(EtlRunLog.completed_at)
                .where(EtlRunLog.status == "SUCCESS")
                .order_by(EtlRunLog.completed_at.desc())
                .limit(1)
            )
    except Exception as exc:  # pragma: no cover - liveness signal only
        logger.warning("Health check DB probe failed: %r", exc)
        db_status = "down"

    return HealthResponse(status="ok", database=db_status, last_etl_run=last_run)


@app.post("/etl/run", response_model=EtlRunResponse)
def trigger_etl() -> EtlRunResponse:
    """Trigger a synchronous ETL run against the configured data directory."""
    try:
        summary = run_etl()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"ETL run failed: {exc!r}") from exc

    with SessionLocal() as session:
        row = session.execute(
            select(EtlRunLog).where(EtlRunLog.run_id == summary["run_id"])
        ).scalar_one()
        return EtlRunResponse(
            run_id=row.run_id,
            started_at=row.started_at,
            completed_at=row.completed_at,
            source_record_count=row.source_record_count,
            loaded_record_count=row.loaded_record_count,
            failed_record_count=row.failed_record_count,
            status=row.status,
        )

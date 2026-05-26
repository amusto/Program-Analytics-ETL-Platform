"""End-to-end ETL command for program analytics data.

Run with:

    python -m app.etl.load_program_data

The pipeline:

  1. Read CSVs from data/raw/.
  2. Validate each row with Pydantic v2.
  3. Reject invalid rows into data/failed/failed_records.jsonl.
  4. Transform/enrich (derive schedule variance, budget utilization, health).
  5. Load into PostgreSQL idempotently via ON CONFLICT DO UPDATE.
  6. Record a row in etl_run_log capturing source/loaded/failed counts.

The whole run is logged to a row in `etl_run_log` so operators can audit
what landed and when. Re-running is safe: every UPSERT is keyed on the
natural primary key, so the second run produces the same row counts.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import init_db, session_scope
from app.etl.transformers import derive_project_metrics
from app.etl.validators import ValidationFailure, validate_rows
from app.models import (
    EtlRunLog,
    Milestone,
    Program,
    Project,
    ProjectAnalytics,
    Risk,
)
from app.schemas import MilestoneIn, ProgramIn, ProjectIn, RiskIn

logger = logging.getLogger("etl")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


# ---------------------------------------------------------------------------
# Idempotent upserts
# ---------------------------------------------------------------------------


def _model_dump(record: BaseModel) -> dict:
    """Serialize a Pydantic model for SQLAlchemy parameter binding."""
    return record.model_dump()


def upsert_programs(session: Session, rows: Iterable[ProgramIn]) -> int:
    payload = [_model_dump(r) for r in rows]
    if not payload:
        return 0
    stmt = insert(Program).values(payload)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Program.program_id],
        set_={
            "name": stmt.excluded.name,
            "portfolio": stmt.excluded.portfolio,
            "program_manager": stmt.excluded.program_manager,
            "start_date": stmt.excluded.start_date,
            "end_date": stmt.excluded.end_date,
            "total_budget": stmt.excluded.total_budget,
        },
    )
    session.execute(stmt)
    return len(payload)


def upsert_projects(session: Session, rows: Iterable[ProjectIn]) -> int:
    payload = [_model_dump(r) for r in rows]
    if not payload:
        return 0
    stmt = insert(Project).values(payload)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Project.project_id],
        set_={
            "program_id": stmt.excluded.program_id,
            "name": stmt.excluded.name,
            "owner": stmt.excluded.owner,
            "status": stmt.excluded.status,
            "budget": stmt.excluded.budget,
            "actual_spend": stmt.excluded.actual_spend,
            "start_date": stmt.excluded.start_date,
            "target_end_date": stmt.excluded.target_end_date,
            "actual_end_date": stmt.excluded.actual_end_date,
        },
    )
    session.execute(stmt)
    return len(payload)


def upsert_milestones(session: Session, rows: Iterable[MilestoneIn]) -> int:
    payload = [_model_dump(r) for r in rows]
    if not payload:
        return 0
    stmt = insert(Milestone).values(payload)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Milestone.milestone_id],
        set_={
            "project_id": stmt.excluded.project_id,
            "name": stmt.excluded.name,
            "status": stmt.excluded.status,
            "planned_date": stmt.excluded.planned_date,
            "actual_date": stmt.excluded.actual_date,
        },
    )
    session.execute(stmt)
    return len(payload)


def upsert_risks(session: Session, rows: Iterable[RiskIn]) -> int:
    payload = [_model_dump(r) for r in rows]
    if not payload:
        return 0
    stmt = insert(Risk).values(payload)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Risk.risk_id],
        set_={
            "project_id": stmt.excluded.project_id,
            "severity": stmt.excluded.severity,
            "category": stmt.excluded.category,
            "description": stmt.excluded.description,
            "opened_date": stmt.excluded.opened_date,
            "status": stmt.excluded.status,
        },
    )
    session.execute(stmt)
    return len(payload)


def upsert_project_analytics(session: Session, projects, risks_by_project, today: date) -> int:
    """Compute and upsert derived metrics for each project."""
    payloads: list[dict] = []
    for project in projects:
        risks_for_project = risks_by_project.get(project.project_id, [])
        metrics = derive_project_metrics(project, risks_for_project, today=today)
        payloads.append(asdict(metrics))

    if not payloads:
        return 0

    stmt = insert(ProjectAnalytics).values(payloads)
    stmt = stmt.on_conflict_do_update(
        index_elements=[ProjectAnalytics.project_id],
        set_={
            "schedule_variance_days": stmt.excluded.schedule_variance_days,
            "budget_utilization_percent": stmt.excluded.budget_utilization_percent,
            "open_risk_count": stmt.excluded.open_risk_count,
            "open_high_severity_risk_count": stmt.excluded.open_high_severity_risk_count,
            "open_medium_severity_risk_count": stmt.excluded.open_medium_severity_risk_count,
            "project_health": stmt.excluded.project_health,
            "computed_at": datetime.now(timezone.utc),
        },
    )
    session.execute(stmt)
    return len(payloads)


# ---------------------------------------------------------------------------
# Referential filtering
# ---------------------------------------------------------------------------


def _filter_referential(
    *,
    rows: list[BaseModel],
    fk_field: str,
    valid_parent_ids: set[str],
    source_file: str,
) -> tuple[list[BaseModel], list[ValidationFailure]]:
    """Drop rows that point at a parent that does not exist.

    Validation already catches typos in column values, but referential
    integrity violations only surface after we know which parents survived
    validation. We treat them as soft failures (write to failed_records)
    instead of letting them blow up the load.
    """
    valid: list[BaseModel] = []
    failures: list[ValidationFailure] = []
    for row in rows:
        parent_id = getattr(row, fk_field)
        if parent_id not in valid_parent_ids:
            failures.append(
                ValidationFailure(
                    source_file=source_file,
                    line_number=-1,
                    raw_row=row.model_dump(mode="json"),
                    errors=[
                        {
                            "loc": [fk_field],
                            "msg": f"foreign key {fk_field}={parent_id!r} does not exist",
                            "type": "value_error.foreign_key",
                        }
                    ],
                )
            )
        else:
            valid.append(row)
    return valid, failures


# ---------------------------------------------------------------------------
# Failed-record sink
# ---------------------------------------------------------------------------


def write_failed_records(failed_path: Path, failures: list[ValidationFailure]) -> None:
    """Append failed rows as JSON Lines for downstream inspection.

    JSONL is friendly to log aggregators and easy to load into S3/Athena
    or a data-quality dashboard. In production this would be a dead-letter
    queue (SQS DLQ) rather than a local file.
    """
    failed_path.parent.mkdir(parents=True, exist_ok=True)
    with failed_path.open("a", encoding="utf-8") as fh:
        for failure in failures:
            fh.write(
                json.dumps(
                    {
                        "captured_at": datetime.now(timezone.utc).isoformat(),
                        "source_file": failure.source_file,
                        "line_number": failure.line_number,
                        "raw_row": failure.raw_row,
                        "errors": failure.errors,
                    },
                    default=str,
                )
                + "\n"
            )


# ---------------------------------------------------------------------------
# Pipeline entrypoint
# ---------------------------------------------------------------------------


def run_etl(*, today: date | None = None) -> dict:
    """Execute one ETL run end-to-end and return a summary dict."""
    settings = get_settings()
    raw_dir = settings.raw_dir
    failed_path = settings.failed_dir / "failed_records.jsonl"
    today = today or date.today()

    run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    started_at = datetime.now(timezone.utc)
    logger.info("Starting ETL run %s", run_id)

    init_db()

    source_count = 0
    loaded_count = 0
    failed_count = 0
    status = "SUCCESS"
    notes_lines: list[str] = []

    try:
        # ----- Validate -----
        programs_result = validate_rows(raw_dir / "programs.csv", ProgramIn)
        projects_result = validate_rows(raw_dir / "projects.csv", ProjectIn)
        milestones_result = validate_rows(raw_dir / "milestones.csv", MilestoneIn)
        risks_result = validate_rows(raw_dir / "risks.csv", RiskIn)

        source_count = (
            len(programs_result.valid) + len(programs_result.failures)
            + len(projects_result.valid) + len(projects_result.failures)
            + len(milestones_result.valid) + len(milestones_result.failures)
            + len(risks_result.valid) + len(risks_result.failures)
        )

        # ----- Referential filtering -----
        valid_program_ids = {p.program_id for p in programs_result.valid}
        filtered_projects, project_ref_failures = _filter_referential(
            rows=projects_result.valid,
            fk_field="program_id",
            valid_parent_ids=valid_program_ids,
            source_file="projects.csv",
        )
        valid_project_ids = {p.project_id for p in filtered_projects}
        filtered_milestones, milestone_ref_failures = _filter_referential(
            rows=milestones_result.valid,
            fk_field="project_id",
            valid_parent_ids=valid_project_ids,
            source_file="milestones.csv",
        )
        filtered_risks, risk_ref_failures = _filter_referential(
            rows=risks_result.valid,
            fk_field="project_id",
            valid_parent_ids=valid_project_ids,
            source_file="risks.csv",
        )

        all_failures = (
            programs_result.failures
            + projects_result.failures
            + project_ref_failures
            + milestones_result.failures
            + milestone_ref_failures
            + risks_result.failures
            + risk_ref_failures
        )
        failed_count = len(all_failures)
        if all_failures:
            write_failed_records(failed_path, all_failures)
            notes_lines.append(f"Wrote {failed_count} failed records to {failed_path}")

        # ----- Group risks by project for analytics derivation -----
        risks_by_project: dict[str, list[RiskIn]] = {}
        for r in filtered_risks:
            risks_by_project.setdefault(r.project_id, []).append(r)

        # ----- Load -----
        # `loaded_count` mirrors the source-row contract: one count per
        # raw row that landed in the warehouse. Derived analytics rows are
        # written too, but they are bookkeeping, not source records, so we
        # do not include them in the lineage count.
        with session_scope() as session:
            loaded = 0
            loaded += upsert_programs(session, programs_result.valid)
            loaded += upsert_projects(session, filtered_projects)
            loaded += upsert_milestones(session, filtered_milestones)
            loaded += upsert_risks(session, filtered_risks)
            upsert_project_analytics(
                session, filtered_projects, risks_by_project, today=today
            )
            loaded_count = loaded

            # Log the run inside the same transaction so the row is consistent
            # with the data it describes.
            session.add(
                EtlRunLog(
                    run_id=run_id,
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    source_record_count=source_count,
                    loaded_record_count=loaded_count,
                    failed_record_count=failed_count,
                    status=status,
                    notes="; ".join(notes_lines) or None,
                )
            )

        logger.info(
            "ETL run %s complete: source=%d loaded=%d failed=%d",
            run_id,
            source_count,
            loaded_count,
            failed_count,
        )

    except Exception as exc:
        status = "FAILED"
        logger.exception("ETL run %s failed", run_id)
        # Record the failure outside the failed transaction so operators can
        # see runs that never completed.
        with session_scope() as session:
            session.add(
                EtlRunLog(
                    run_id=run_id,
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    source_record_count=source_count,
                    loaded_record_count=loaded_count,
                    failed_record_count=failed_count,
                    status=status,
                    notes=f"Exception: {exc!r}",
                )
            )
        raise

    return {
        "run_id": run_id,
        "started_at": started_at,
        "source_record_count": source_count,
        "loaded_record_count": loaded_count,
        "failed_record_count": failed_count,
        "status": status,
    }


def main() -> None:
    summary = run_etl()
    logger.info("Summary: %s", summary)


if __name__ == "__main__":
    main()

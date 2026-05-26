"""Analytics endpoints.

These endpoints serve pre-aggregated data from the project_analytics
table. The dashboard never has to JOIN raw rows at request time, which
is the same pattern a real analytics platform uses behind a star schema.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Program, Project, ProjectAnalytics, Risk
from app.schemas import AnalyticsSummary, AtRiskProject, ProgramRollup

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary", response_model=AnalyticsSummary)
def get_summary(db: Session = Depends(get_db)) -> AnalyticsSummary:
    total_programs = db.scalar(select(func.count()).select_from(Program)) or 0
    total_projects = db.scalar(select(func.count()).select_from(Project)) or 0

    critical_projects = (
        db.scalar(
            select(func.count())
            .select_from(ProjectAnalytics)
            .where(ProjectAnalytics.project_health == "CRITICAL")
        )
        or 0
    )
    at_risk_projects = (
        db.scalar(
            select(func.count())
            .select_from(ProjectAnalytics)
            .where(ProjectAnalytics.project_health == "AT_RISK")
        )
        or 0
    )
    avg_util = db.scalar(
        select(func.coalesce(func.avg(ProjectAnalytics.budget_utilization_percent), 0))
    )
    open_risks = (
        db.scalar(
            select(func.count())
            .select_from(Risk)
            .where(Risk.status == "OPEN")
        )
        or 0
    )

    return AnalyticsSummary(
        totalPrograms=int(total_programs),
        totalProjects=int(total_projects),
        criticalProjects=int(critical_projects),
        atRiskProjects=int(at_risk_projects),
        averageBudgetUtilization=round(float(avg_util or 0), 2),
        openRisks=int(open_risks),
    )


@router.get("/programs", response_model=list[ProgramRollup])
def list_program_rollups(db: Session = Depends(get_db)) -> list[ProgramRollup]:
    """Roll up project counts and health for every program."""
    critical = case((ProjectAnalytics.project_health == "CRITICAL", 1), else_=0)
    at_risk = case((ProjectAnalytics.project_health == "AT_RISK", 1), else_=0)
    on_track = case((ProjectAnalytics.project_health == "ON_TRACK", 1), else_=0)

    stmt = (
        select(
            Program.program_id,
            Program.name,
            Program.portfolio,
            Program.program_manager,
            func.count(Project.project_id).label("project_count"),
            func.coalesce(func.sum(critical), 0).label("critical_projects"),
            func.coalesce(func.sum(at_risk), 0).label("at_risk_projects"),
            func.coalesce(func.sum(on_track), 0).label("on_track_projects"),
            func.coalesce(
                func.avg(ProjectAnalytics.budget_utilization_percent), 0
            ).label("average_budget_utilization"),
        )
        .select_from(Program)
        .join(Project, Project.program_id == Program.program_id, isouter=True)
        .join(
            ProjectAnalytics,
            ProjectAnalytics.project_id == Project.project_id,
            isouter=True,
        )
        .group_by(
            Program.program_id,
            Program.name,
            Program.portfolio,
            Program.program_manager,
        )
        .order_by(Program.program_id)
    )

    rows = db.execute(stmt).all()

    # Open risks per program (counted separately to avoid double-aggregation
    # with the joined project_analytics rows above).
    risk_counts_stmt = (
        select(Program.program_id, func.count(Risk.risk_id))
        .select_from(Program)
        .join(Project, Project.program_id == Program.program_id)
        .join(Risk, Risk.project_id == Project.project_id)
        .where(Risk.status == "OPEN")
        .group_by(Program.program_id)
    )
    open_risks_by_program = dict(db.execute(risk_counts_stmt).all())

    results: list[ProgramRollup] = []
    for row in rows:
        results.append(
            ProgramRollup(
                program_id=row.program_id,
                name=row.name,
                portfolio=row.portfolio,
                program_manager=row.program_manager,
                project_count=int(row.project_count or 0),
                critical_projects=int(row.critical_projects or 0),
                at_risk_projects=int(row.at_risk_projects or 0),
                on_track_projects=int(row.on_track_projects or 0),
                average_budget_utilization=round(
                    float(row.average_budget_utilization or 0), 2
                ),
                open_risks=int(open_risks_by_program.get(row.program_id, 0)),
            )
        )
    return results


@router.get("/projects/at-risk", response_model=list[AtRiskProject])
def list_at_risk_projects(db: Session = Depends(get_db)) -> list[AtRiskProject]:
    """Every project whose derived health is AT_RISK or CRITICAL."""
    stmt = (
        select(
            Project.project_id,
            Project.name,
            Project.owner,
            Project.status,
            Project.program_id,
            Program.name.label("program_name"),
            ProjectAnalytics.project_health,
            ProjectAnalytics.budget_utilization_percent,
            ProjectAnalytics.schedule_variance_days,
            ProjectAnalytics.open_risk_count,
            ProjectAnalytics.open_high_severity_risk_count,
        )
        .join(Program, Program.program_id == Project.program_id)
        .join(ProjectAnalytics, ProjectAnalytics.project_id == Project.project_id)
        .where(ProjectAnalytics.project_health.in_(["AT_RISK", "CRITICAL"]))
        .order_by(
            case(
                (ProjectAnalytics.project_health == "CRITICAL", 0),
                (ProjectAnalytics.project_health == "AT_RISK", 1),
                else_=2,
            ),
            ProjectAnalytics.budget_utilization_percent.desc(),
        )
    )
    rows = db.execute(stmt).all()
    return [
        AtRiskProject(
            project_id=row.project_id,
            name=row.name,
            owner=row.owner,
            status=row.status,
            program_id=row.program_id,
            program_name=row.program_name,
            project_health=row.project_health,
            budget_utilization_percent=float(row.budget_utilization_percent),
            schedule_variance_days=int(row.schedule_variance_days),
            open_risk_count=int(row.open_risk_count),
            open_high_severity_risk_count=int(row.open_high_severity_risk_count),
        )
        for row in rows
    ]

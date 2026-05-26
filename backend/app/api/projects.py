"""Project-detail endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import Program, Project
from app.schemas import MilestoneOut, ProjectDetail, RiskOut

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(project_id: str, db: Session = Depends(get_db)) -> ProjectDetail:
    stmt = (
        select(Project)
        .options(
            selectinload(Project.milestones),
            selectinload(Project.risks),
            selectinload(Project.analytics),
            selectinload(Project.program),
        )
        .where(Project.project_id == project_id)
    )
    project = db.execute(stmt).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    analytics = project.analytics
    return ProjectDetail(
        project_id=project.project_id,
        program_id=project.program_id,
        program_name=project.program.name,
        name=project.name,
        owner=project.owner,
        status=project.status,
        budget=float(project.budget),
        actual_spend=float(project.actual_spend),
        start_date=project.start_date,
        target_end_date=project.target_end_date,
        actual_end_date=project.actual_end_date,
        project_health=analytics.project_health if analytics else None,
        schedule_variance_days=(
            int(analytics.schedule_variance_days) if analytics else None
        ),
        budget_utilization_percent=(
            float(analytics.budget_utilization_percent) if analytics else None
        ),
        open_risk_count=(int(analytics.open_risk_count) if analytics else 0),
        milestones=[
            MilestoneOut(
                milestone_id=m.milestone_id,
                name=m.name,
                status=m.status,
                planned_date=m.planned_date,
                actual_date=m.actual_date,
            )
            for m in sorted(project.milestones, key=lambda m: m.planned_date)
        ],
        risks=[
            RiskOut(
                risk_id=r.risk_id,
                severity=r.severity,
                category=r.category,
                description=r.description,
                opened_date=r.opened_date,
                status=r.status,
            )
            for r in sorted(project.risks, key=lambda r: r.opened_date)
        ],
    )

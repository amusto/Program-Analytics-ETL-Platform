"""Pydantic v2 schemas for ETL validation and API responses.

The ETL schemas double as input validators: every CSV row is parsed through
the corresponding model, so invalid rows fail at the boundary and never
reach Postgres. The API schemas are kept separate so we can evolve the
wire format independently of the storage model.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# ETL input schemas (parse raw CSV rows)
# ---------------------------------------------------------------------------


class ProgramIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    program_id: str
    name: str
    portfolio: str
    program_manager: str
    start_date: date
    end_date: date
    total_budget: Annotated[float, Field(ge=0)]

    @field_validator("end_date")
    @classmethod
    def end_after_start(cls, v: date, info) -> date:
        start = info.data.get("start_date")
        if start and v < start:
            raise ValueError("end_date must be on or after start_date")
        return v


ProjectStatus = Literal["NOT_STARTED", "IN_PROGRESS", "AT_RISK", "BLOCKED", "COMPLETED", "CANCELLED"]


class ProjectIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: str
    program_id: str
    name: str
    owner: str
    status: ProjectStatus
    budget: Annotated[float, Field(ge=0)]
    actual_spend: Annotated[float, Field(ge=0)] = 0.0
    start_date: date
    target_end_date: date
    actual_end_date: Optional[date] = None

    @field_validator("target_end_date")
    @classmethod
    def target_after_start(cls, v: date, info) -> date:
        start = info.data.get("start_date")
        if start and v < start:
            raise ValueError("target_end_date must be on or after start_date")
        return v


MilestoneStatus = Literal["NOT_STARTED", "IN_PROGRESS", "AT_RISK", "COMPLETED", "MISSED"]


class MilestoneIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    milestone_id: str
    project_id: str
    name: str
    status: MilestoneStatus
    planned_date: date
    actual_date: Optional[date] = None


RiskSeverity = Literal["LOW", "MEDIUM", "HIGH"]
RiskStatus = Literal["OPEN", "MITIGATED", "CLOSED"]


class RiskIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    risk_id: str
    project_id: str
    severity: RiskSeverity
    category: str
    description: str
    opened_date: date
    status: RiskStatus


# ---------------------------------------------------------------------------
# API response schemas
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: Literal["ok"]
    database: Literal["ok", "down"]
    last_etl_run: Optional[datetime] = None


class AnalyticsSummary(BaseModel):
    totalPrograms: int
    totalProjects: int
    criticalProjects: int
    atRiskProjects: int
    averageBudgetUtilization: float
    openRisks: int


class ProgramRollup(BaseModel):
    program_id: str
    name: str
    portfolio: str
    program_manager: str
    project_count: int
    critical_projects: int
    at_risk_projects: int
    on_track_projects: int
    average_budget_utilization: float
    open_risks: int


class AtRiskProject(BaseModel):
    project_id: str
    name: str
    owner: str
    status: str
    program_id: str
    program_name: str
    project_health: str
    budget_utilization_percent: float
    schedule_variance_days: int
    open_risk_count: int
    open_high_severity_risk_count: int


class ProjectDetail(BaseModel):
    project_id: str
    program_id: str
    program_name: str
    name: str
    owner: str
    status: str
    budget: float
    actual_spend: float
    start_date: date
    target_end_date: date
    actual_end_date: Optional[date]
    project_health: Optional[str]
    schedule_variance_days: Optional[int]
    budget_utilization_percent: Optional[float]
    open_risk_count: int
    milestones: list["MilestoneOut"]
    risks: list["RiskOut"]


class MilestoneOut(BaseModel):
    milestone_id: str
    name: str
    status: str
    planned_date: date
    actual_date: Optional[date]


class RiskOut(BaseModel):
    risk_id: str
    severity: str
    category: str
    description: str
    opened_date: date
    status: str


class EtlRunResponse(BaseModel):
    run_id: str
    started_at: datetime
    completed_at: Optional[datetime]
    source_record_count: int
    loaded_record_count: int
    failed_record_count: int
    status: str


ProjectDetail.model_rebuild()

"""Transformations that turn validated rows into reporting-ready records.

These derivations are the heart of the analytics layer. They are kept as
pure functions so they are easy to unit test and easy to reason about:
the same inputs always produce the same outputs, with no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.schemas import ProjectIn, RiskIn


@dataclass
class DerivedProjectMetrics:
    project_id: str
    schedule_variance_days: int
    budget_utilization_percent: float
    open_risk_count: int
    open_high_severity_risk_count: int
    open_medium_severity_risk_count: int
    project_health: str  # ON_TRACK | AT_RISK | CRITICAL


def compute_schedule_variance_days(project: ProjectIn, today: date) -> int:
    """Days late vs the target end date.

    Positive numbers mean late. For completed projects we compare actual
    end date to target. For in-flight projects we compare today to target
    (if today is past target) or zero (if we are still ahead of plan).
    """
    if project.actual_end_date is not None:
        delta = (project.actual_end_date - project.target_end_date).days
        return delta
    if today > project.target_end_date:
        return (today - project.target_end_date).days
    return 0


def compute_budget_utilization_percent(project: ProjectIn) -> float:
    """Actual spend as a percentage of budgeted spend.

    Returns 0 when the budget is zero to avoid divide-by-zero blowups. In
    production we would also flag zero-budget projects as a data-quality
    issue worth investigating.
    """
    if project.budget <= 0:
        return 0.0
    return round((project.actual_spend / project.budget) * 100, 2)


def classify_project_health(
    *,
    schedule_variance_days: int,
    budget_utilization_percent: float,
    open_high_severity_risk_count: int,
    open_medium_severity_risk_count: int,
) -> str:
    """Apply the project-health decision rules.

    CRITICAL:
        high-severity risk open OR budget utilization > 110 OR variance > 30
    AT_RISK:
        medium/high-severity risk open OR budget utilization > 90 OR variance > 14
    ON_TRACK:
        otherwise
    """
    if (
        open_high_severity_risk_count > 0
        or budget_utilization_percent > 110
        or schedule_variance_days > 30
    ):
        return "CRITICAL"
    if (
        open_medium_severity_risk_count > 0
        or budget_utilization_percent > 90
        or schedule_variance_days > 14
    ):
        # Note: HIGH-severity risk is already caught by the CRITICAL branch
        # above, so we only need MEDIUM here to satisfy the spec's
        # "medium/high risk open" condition for AT_RISK.
        return "AT_RISK"
    return "ON_TRACK"


def derive_project_metrics(
    project: ProjectIn,
    risks_for_project: list[RiskIn],
    *,
    today: date,
) -> DerivedProjectMetrics:
    """Combine schedule, budget, and risk signals into a single record."""
    open_risks = [r for r in risks_for_project if r.status == "OPEN"]
    high = sum(1 for r in open_risks if r.severity == "HIGH")
    medium = sum(1 for r in open_risks if r.severity == "MEDIUM")

    variance = compute_schedule_variance_days(project, today)
    utilization = compute_budget_utilization_percent(project)
    health = classify_project_health(
        schedule_variance_days=variance,
        budget_utilization_percent=utilization,
        open_high_severity_risk_count=high,
        open_medium_severity_risk_count=medium,
    )

    return DerivedProjectMetrics(
        project_id=project.project_id,
        schedule_variance_days=variance,
        budget_utilization_percent=utilization,
        open_risk_count=len(open_risks),
        open_high_severity_risk_count=high,
        open_medium_severity_risk_count=medium,
        project_health=health,
    )

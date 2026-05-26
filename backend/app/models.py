"""SQLAlchemy ORM models for the program analytics domain.

The schema is a normalized relational model that mirrors how a PMO actually
tracks work: portfolios contain programs, programs contain projects,
projects accumulate milestones and risks, and a separate analytics table
stores derived metrics so the dashboard never recomputes them on read.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Program(Base):
    __tablename__ = "programs"

    program_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    portfolio: Mapped[str] = mapped_column(String(128), nullable=False)
    program_manager: Mapped[str] = mapped_column(String(128), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    total_budget: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    projects: Mapped[list["Project"]] = relationship(
        back_populates="program", cascade="all, delete-orphan"
    )


class Project(Base):
    __tablename__ = "projects"

    project_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    program_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("programs.program_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    budget: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    actual_spend: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    target_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    actual_end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    program: Mapped[Program] = relationship(back_populates="projects")
    milestones: Mapped[list["Milestone"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    risks: Mapped[list["Risk"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    analytics: Mapped[Optional["ProjectAnalytics"]] = relationship(
        back_populates="project",
        uselist=False,
        cascade="all, delete-orphan",
    )


Index("ix_projects_program_id", Project.program_id)
Index("ix_projects_status", Project.status)


class Milestone(Base):
    __tablename__ = "milestones"

    milestone_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    planned_date: Mapped[date] = mapped_column(Date, nullable=False)
    actual_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    project: Mapped[Project] = relationship(back_populates="milestones")


Index("ix_milestones_project_id", Milestone.project_id)


class Risk(Base):
    __tablename__ = "risks"

    risk_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=False
    )
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    opened_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)

    project: Mapped[Project] = relationship(back_populates="risks")


Index("ix_risks_project_id", Risk.project_id)
Index("ix_risks_status", Risk.status)


class ProjectAnalytics(Base):
    """Derived metrics for a single project.

    Populated by the ETL after raw rows are loaded. The dashboard reads from
    this table instead of recomputing health on every request — the kind of
    pre-aggregated reporting layer you would build behind a star schema in
    a real data warehouse.
    """

    __tablename__ = "project_analytics"

    project_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("projects.project_id", ondelete="CASCADE"),
        primary_key=True,
    )
    schedule_variance_days: Mapped[int] = mapped_column(Integer, nullable=False)
    budget_utilization_percent: Mapped[float] = mapped_column(
        Numeric(8, 2), nullable=False
    )
    open_risk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    open_high_severity_risk_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    open_medium_severity_risk_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    project_health: Mapped[str] = mapped_column(String(16), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped[Project] = relationship(back_populates="analytics")


Index("ix_project_analytics_health", ProjectAnalytics.project_health)


class EtlRunLog(Base):
    """One row per ETL execution.

    Captures lineage so operators can audit which run loaded which rows and
    quickly spot trend changes in failed-record volume.
    """

    __tablename__ = "etl_run_log"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    loaded_record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="RUNNING")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

# Program Analytics ETL Platform

A miniature enterprise analytics platform for program / portfolio management,
built to demonstrate **data engineering thinking first, and full-stack
capability second**.

It ingests program, project, milestone, and risk data from multiple CSV
sources, validates it at the boundary with Pydantic v2, transforms it into
reporting-ready metrics (schedule variance, budget utilization, project
health), loads it into PostgreSQL idempotently, and exposes the curated
data through a FastAPI analytics API consumed by a lightweight React +
TypeScript dashboard.

> **One-line pitch:** *Not a CRUD app — a small ETL pipeline with a UI on top.*

![Program Analytics dashboard showing KPI cards (4 programs, 18 projects, 6 critical, 8 at-risk, 89.0% avg budget utilization, 15 open risks) above an at-risk project table](docs/screenshots/dashboard.png)

---

## 1. Architecture

```
            ┌─────────────────────────────┐
            │  data/raw/*.csv (sources)   │
            └──────────────┬──────────────┘
                           │ extract
                           ▼
            ┌─────────────────────────────┐
            │  Pydantic v2 validators     │  →  data/failed/failed_records.jsonl
            └──────────────┬──────────────┘     (DLQ — invalid + orphan rows)
                           │ transform / enrich
                           ▼
            ┌─────────────────────────────┐
            │  Derived metrics            │
            │   • schedule_variance_days  │
            │   • budget_utilization_pct  │
            │   • project_health          │
            └──────────────┬──────────────┘
                           │ load (UPSERT, idempotent)
                           ▼
            ┌─────────────────────────────┐
            │  PostgreSQL 16              │
            │   programs · projects       │
            │   milestones · risks        │
            │   project_analytics         │
            │   etl_run_log               │
            └──────────────┬──────────────┘
                           │ SQL (SQLAlchemy 2.0)
                           ▼
            ┌─────────────────────────────┐
            │  FastAPI analytics service  │
            │   /analytics/summary        │
            │   /analytics/programs       │
            │   /analytics/projects/at-risk│
            │   /projects/{id}            │
            │   /etl/run                  │
            └──────────────┬──────────────┘
                           │ HTTP / JSON
                           ▼
            ┌─────────────────────────────┐
            │  React + TypeScript UI      │
            │   KPI cards · at-risk table │
            │   program rollup            │
            └─────────────────────────────┘
```

---

## 2. Why this maps to enterprise ETL / VPA-style work

The Virtual Program Assistant (VPA) role is, at its core, about turning
fragmented program data into reliable, automated reporting that program
managers can trust. This POC exercises the same patterns at small scale:

- **Multi-source ingestion** — programs, projects, milestones, and risks
  arrive as separate CSV files, just as they would arrive from different
  enterprise systems (ServiceNow, Jira, MS Project, Anaplan).
- **Boundary validation** — Pydantic enforces schema *and* business rules
  (date ordering, valid enums, non-negative budgets) before any row touches
  PostgreSQL.
- **Failed-record handling** — invalid rows are routed to a JSONL sink
  with full error context, mirroring a Dead Letter Queue in production.
- **Idempotent loads** — every UPSERT is keyed on the natural primary key
  using PostgreSQL `INSERT ... ON CONFLICT DO UPDATE`, so the pipeline is
  safe to re-run during incident recovery.
- **Pre-aggregated reporting layer** — `project_analytics` stores derived
  metrics so the dashboard never recomputes them on read. This is the same
  pattern a real warehouse uses behind a star schema.
- **Lineage / audit** — every ETL run is recorded in `etl_run_log` with
  source / loaded / failed counts and status, giving operators a clean
  audit trail.

---

## 3. Running locally

### Option A — Docker Compose (recommended)

```bash
docker compose up --build
```

This starts:

- **postgres**  on `localhost:5432` (user `analytics`, db `program_analytics`)
- **backend**   on `localhost:8000` — runs the ETL on container start, then
  serves the FastAPI app via `uvicorn`

Hit the API:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/analytics/summary
curl http://localhost:8000/analytics/projects/at-risk
curl -X POST http://localhost:8000/etl/run
```

Open the auto-generated OpenAPI docs at <http://localhost:8000/docs>.

### Option B — local Python

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# point at any running Postgres
export DATABASE_URL=postgresql+psycopg://analytics:analytics@localhost:5432/program_analytics
export DATA_DIR=$(pwd)/../data

# run the ETL
python -m app.etl.load_program_data

# serve the API
uvicorn app.main:app --reload
```

### Frontend dashboard

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 (proxies API calls to :8000)
npm run build      # type-checked production build
```

---

## 4. Data model

| Table | Grain | Notes |
| --- | --- | --- |
| `programs` | one row per program | Portfolio + program-manager attribution. |
| `projects` | one row per project | FK to `programs`. Status + budget + dates. |
| `milestones` | one row per milestone | FK to `projects`. Planned vs actual dates. |
| `risks` | one row per risk | FK to `projects`. Severity, category, status. |
| `project_analytics` | one row per project | **Derived** metrics: variance, utilization, health, open-risk counts. Computed by the ETL. |
| `etl_run_log` | one row per ETL execution | source / loaded / failed counts, status, notes. Provides lineage. |

The schema is fully normalized in 3NF. Health is **not** stored on `projects`
itself — it lives in `project_analytics` because it is a derived, recomputable
metric. This keeps the source-of-truth schema independent from reporting logic
and makes it trivial to re-derive metrics with different rules.

---

## 5. ETL flow

```python
python -m app.etl.load_program_data
```

Per run, the ETL:

1. **Extract** — read all four CSVs in `data/raw/`.
2. **Validate** — each row is parsed through its Pydantic schema. Schema +
   business-rule violations are captured with their full error context.
3. **Filter referentially** — projects pointing at a missing program, and
   milestones/risks pointing at a missing project, are dropped into the
   failed-records sink instead of blowing up the load.
4. **Transform** — derive `schedule_variance_days`,
   `budget_utilization_percent`, and `project_health` for every project.
5. **Load** — UPSERT every entity using PostgreSQL `ON CONFLICT DO UPDATE`,
   keyed on the natural primary key. Re-running produces the same row
   counts; corrected CSVs overwrite stale fields in place.
6. **Log** — a single row in `etl_run_log` records the run, including
   source / loaded / failed counts so trends are queryable over time.

### Health rules

| Tier | Conditions (any one triggers) |
| --- | --- |
| `CRITICAL` | open HIGH-severity risk · budget utilization > 110% · schedule variance > 30 days |
| `AT_RISK` | open MEDIUM or HIGH risk · budget utilization > 90% · schedule variance > 14 days |
| `ON_TRACK` | none of the above |

---

## 6. Reliability patterns demonstrated

- **Validation at the boundary** — Pydantic v2 schemas reject malformed
  rows before they reach PostgreSQL, with structured error context per
  failure.
- **Idempotent loads** — every UPSERT uses
  `INSERT ... ON CONFLICT (pk) DO UPDATE`, so re-running the pipeline is
  safe and deterministic. Re-running against the sample data produces
  identical row counts.
- **Failed-record handling** — invalid rows are written as JSONL to
  `data/failed/failed_records.jsonl` with their raw payload and Pydantic
  errors. In production this would be the path to an SQS DLQ.
- **Normalized relational model** — 3NF across programs / projects /
  milestones / risks, with explicit foreign keys and cascade behavior.
- **Derived analytics table** — `project_analytics` decouples reporting
  metrics from the source-of-truth schema; metrics can be re-derived
  without touching the OLTP tables.
- **Run lineage** — `etl_run_log` captures every execution with source,
  loaded, failed counts and final status, enabling trend monitoring of
  data-quality (`failed_count`) over time.
- **Transaction safety** — the entire load (including the lineage row)
  commits atomically; partial loads roll back cleanly on failure.

---

## 7. Production extensions

A real version of this platform would evolve along the dimensions a
data-engineering team cares about most:

- **Orchestration** — move the `run_etl()` entrypoint into an Airflow /
  MWAA DAG (or AWS Step Functions). Per-source DAGs would be scheduled
  independently and emit metrics on duration, row counts, and failure
  rate.
- **Lakehouse / raw landing zone** — land raw CSV / API payloads in
  **S3** under a `raw/{source}/{date}/` partition scheme, write curated
  outputs as **Parquet** under `curated/`. Use Athena or Redshift Spectrum
  for ad-hoc queries on raw layers.
- **Streaming ingestion** — for sources that publish change events (a
  modern PMO/CRM with webhooks), ingest via **Kinesis** or **SQS**, with
  a Lambda consumer that writes incrementally into the curated layer.
- **Dead-letter handling** — replace `failed_records.jsonl` with an
  **SQS DLQ** and a small redrive process that surfaces failures in a
  data-quality dashboard for stewards to triage.
- **Observability** — emit **CloudWatch** metrics on every run
  (`source_count`, `loaded_count`, `failed_count`, `duration_ms`), alarm
  on failed-count spikes, and centralize structured JSON logs.
- **Schema migrations** — replace `create_all()` with **Alembic**
  migrations gated in CI and executed as a discrete deploy step for
  zero-downtime rollouts.
- **CI/CD** — GitHub Actions pipeline runs unit tests over the
  transformer functions (pure inputs → pure outputs), spins up an
  ephemeral Postgres for integration tests, builds and pushes the
  backend image, and runs the frontend type-check + build.
- **Performance** — partition `etl_run_log` and any high-volume fact
  tables by month (PostgreSQL declarative partitioning), add a **Redis**
  cache in front of `/analytics/summary` and `/analytics/programs` with a
  short TTL keyed on the latest successful `etl_run_log.completed_at`,
  and scale the API horizontally behind an ALB.
- **Security** — secrets via AWS Secrets Manager / SSM, scoped IAM roles
  per service, mTLS or signed JWTs between the dashboard and the API.

---

## 8. Repository layout

```
program-analytics-etl-platform/
├── README.md
├── docker-compose.yml
├── data/
│   ├── raw/                       # source CSVs
│   ├── failed/                    # failed_records.jsonl (DLQ stand-in)
│   └── processed/
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py                # FastAPI app + /health, /etl/run
│       ├── config.py              # Settings (env-driven)
│       ├── db.py                  # Engine + session factory
│       ├── models.py              # SQLAlchemy ORM models
│       ├── schemas.py             # Pydantic v2 schemas (ETL + API)
│       ├── etl/
│       │   ├── validators.py      # CSV → Pydantic; failure capture
│       │   ├── transformers.py    # variance / utilization / health
│       │   └── load_program_data.py  # entrypoint + UPSERT loader
│       └── api/
│           ├── analytics.py       # /analytics/*
│           └── projects.py        # /projects/{id}
└── frontend/
    ├── package.json
    ├── vite.config.ts
    └── src/
        ├── App.tsx
        ├── api.ts
        └── components/
            ├── KpiCard.tsx
            ├── ProjectTable.tsx
            └── RiskSummary.tsx
```

---

## 9. Interview talking points

- *"I built this as a miniature enterprise analytics platform, not just a
  CRUD app. It ingests program data from multiple sources, validates it
  at the boundary, transforms it into reporting-ready metrics, loads it
  into PostgreSQL idempotently, and exposes analytics through API
  endpoints and a lightweight dashboard."*
- *"Validation lives at the boundary, not after the load. Pydantic
  catches both schema and business-rule violations, and failed rows are
  routed to a JSONL sink — the local equivalent of an SQS DLQ — instead
  of being silently dropped or corrupting the load."*
- *"Every UPSERT is keyed on the natural primary key with
  `ON CONFLICT DO UPDATE`. Re-running the pipeline is safe and
  deterministic; I rely on that to recover from partial failures without
  manual cleanup."*
- *"Derived metrics live in a separate `project_analytics` table. The
  dashboard reads pre-aggregated rows — it never JOINs raw data at
  request time. That's the same pattern a real warehouse uses behind a
  star schema."*
- *"Every run lands a row in `etl_run_log` with source / loaded / failed
  counts. That gives operators a single place to monitor data-quality
  trends — a spike in `failed_count` is a signal worth alarming on."*
- *"In production, I would orchestrate this with Airflow or MWAA, land
  raw payloads in S3, write curated Parquet datasets, and add streaming
  ingestion via Kinesis or SQS where near-real-time updates matter. The
  failed-records sink becomes an SQS DLQ. The API gets a Redis cache
  keyed on the latest successful ETL completion time so the dashboard
  stays sub-50ms even at scale."*

# Cloud Report Ingestion API

<p align="left">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11+-blue">
  <img alt="Flask" src="https://img.shields.io/badge/Flask-API%20Layer-black">
  <img alt="Cloud Run" src="https://img.shields.io/badge/Google%20Cloud-Cloud%20Run-lightgrey">
  <img alt="SQL" src="https://img.shields.io/badge/SQL-BI%20Ready-green">
  <img alt="Docker" src="https://img.shields.io/badge/Docker-Containerized-blue">
  <img alt="Status" src="https://img.shields.io/badge/Status-Public--Safe%20Portfolio%20Version-success">
</p>

Public-safe version of a financial report ingestion and BI platform foundation built with Python, Flask, Cloud Run, Cloud Storage-compatible architecture and PostgreSQL/Cloud SQL-ready workflows.

The project demonstrates how operational financial reports can be collected, stored, normalized, loaded into SQL and prepared for Power BI, dashboards and self-service analytics.

> This repository is sanitized for portfolio use. It does not include real credentials, real users, real project IDs, internal endpoints, client data, private buckets, production secrets or confidential financial information.

---

## Overview

Financial operations teams often depend on recurring reports coming from external providers, internal files, APIs, webhooks and manual downloads.

Without a centralized ingestion layer, the process becomes fragmented:

- Reports are requested manually;
- Files are downloaded and renamed manually;
- Latest versions are difficult to track;
- Data formats are inconsistent;
- Power BI transformations become harder to maintain;
- SQL tables may not reflect the latest available information;
- Operational teams lose traceability over historical report versions.

This project was created to solve that problem by introducing a structured ingestion and BI-ready pipeline.

---

## What This Project Demonstrates

- Web portal for operational report monitoring;
- Webhook ingestion for external report deliveries;
- Report request and trigger endpoints;
- Cloud Storage-compatible landing zone for raw, latest and historical files;
- Column normalization for BI consumption;
- SQL loader for PostgreSQL/Cloud SQL;
- Friendly report names for Power BI and business users;
- Scheduler scripts for automated report collection;
- Example deployment scripts for Cloud Run;
- BI Platform V2 foundation with API, worker, frontend and semantic mart documentation.

---

## Architecture

```mermaid
flowchart TD
    A[External Report Provider] --> B[Cloud Run Portal / API]
    B --> C[Webhook Receiver]
    B --> D[Report Trigger Endpoints]
    C --> E[Raw Storage]
    D --> E
    E --> F[Latest Report Pointer]
    E --> G[Historical Storage]
    F --> H[Column Normalization]
    G --> H
    H --> I[SQL Loader]
    I --> J[Cloud SQL / PostgreSQL]
    J --> K[Power BI / Operational Portal]
    J --> L[BI Platform V2 Semantic Mart]

    classDef source fill:#111827,stroke:#38bdf8,stroke-width:2px,color:#ffffff;
    classDef process fill:#1f2937,stroke:#60a5fa,stroke-width:2px,color:#ffffff;
    classDef output fill:#1e3a8a,stroke:#93c5fd,stroke-width:2px,color:#ffffff;

    class A source;
    class B,C,D,E,F,G,H,I,J process;
    class K,L output;
```

---

## Main Capabilities

| Capability | Description |
|---|---|
| Report Ingestion | Receives or requests external operational reports. |
| Webhook Support | Accepts report deliveries through webhook-style endpoints. |
| Raw Storage | Preserves original files for traceability. |
| Latest Report Control | Maintains latest-report references for downstream consumption. |
| Historical Storage | Keeps dated report versions for audit and history. |
| Column Normalization | Converts inconsistent report columns into BI-friendly names. |
| SQL Loading | Loads normalized data into PostgreSQL/Cloud SQL-ready structures. |
| Scheduler Automation | Supports automated report refresh routines. |
| BI Integration | Prepares data for Power BI, SQL views and dashboard usage. |
| BI Platform V2 Foundation | Documents the evolution toward a self-service BI platform. |

---

## Repository Structure

```text
cloud-report-ingestion-api/
│
├── app.py
├── report_ingestion_service.py
├── sql_loader.py
├── report_column_normalizer.py
│
├── config/
│   ├── reports.example.txt
│   ├── report_api_catalog.example.json
│   ├── column_mappings.example.json
│   └── report_names.example.json
│
├── sql/
│   └── schema_cloudsql.sql
│
├── scripts/
│   ├── cloud_scheduler_setup.example.sh
│   ├── deploy_cloud_run_cloudsql.example.sh
│   ├── sync_reports_to_onedrive.example.ps1
│   ├── update_scheduler_deadline.sh
│   └── security_scan_before_commit.sh
│
├── docs/
│   ├── SESSION_LOG_BI_V2_FOUNDATION.md
│   ├── NEXT_STEPS_BI_V2.md
│   ├── TROUBLESHOOTING_BI_V2.md
│   ├── STATUS_BI_V2.md
│   └── SECURITY_REVIEW_BI_V2.md
│
├── prompts/
│   └── NEXT_CHAT_PROMPT_BI_V2.md
│
├── Dockerfile.portal
├── Dockerfile.sql_loader
├── cloudbuild.portal.yaml
├── requirements.txt
├── requirements_sql_loader.txt
├── SECURITY_REVIEW.md
├── CHANGELOG_BI_V2.md
├── .env.example
├── .gitignore
└── README.md
```

> Some BI V2 documentation files may be part of a later update. If the `docs/`, `prompts/` or `CHANGELOG_BI_V2.md` files are not present yet, they should be copied from the sanitized update package.

---

## Main Files

| File | Purpose |
|---|---|
| `app.py` | Portal, API and webhook application. |
| `report_ingestion_service.py` | Report request and ingestion service layer. |
| `sql_loader.py` | SQL/BI loading layer. |
| `report_column_normalizer.py` | Column and value normalization helpers. |
| `config/reports.example.txt` | Public-safe report catalog example. |
| `config/report_api_catalog.example.json` | Public-safe API report catalog. |
| `config/column_mappings.example.json` | Column mapping examples. |
| `config/report_names.example.json` | Friendly report name mapping. |
| `sql/schema_cloudsql.sql` | Example Cloud SQL/PostgreSQL schema. |
| `scripts/cloud_scheduler_setup.example.sh` | Example scheduler setup. |
| `scripts/deploy_cloud_run_cloudsql.example.sh` | Example Cloud Run deployment. |
| `scripts/sync_reports_to_onedrive.example.ps1` | Example local sync script. |
| `Dockerfile.portal` | Container definition for the portal/API service. |
| `Dockerfile.sql_loader` | Container definition for the SQL loader service. |

---

## BI Platform V2

This repository also documents the foundation for a parallel self-service BI platform built on top of the financial report ingestion architecture.

The V2 architecture keeps the legacy portal running while introducing:

- API backend for authentication, datasets, dashboards, tabs, widgets and query execution;
- Worker service for mart refresh and daily snapshot management;
- Frontend dashboard builder;
- SQL semantic mart;
- RBAC and audit schemas;
- Daily snapshot policy for report history;
- Smart numeric normalization for financial datasets;
- Public-safe documentation for troubleshooting and next steps.

---

## BI V2 Architecture

```mermaid
flowchart TD
    A[Raw Reports / API / Webhooks] --> B[Ingestion Layer]
    B --> C[Warehouse Layer]
    C --> D[Worker Refresh]
    D --> E[Semantic Mart]
    E --> F[Dataset Catalog]
    F --> G[Query API]
    G --> H[Dashboard Builder]
    H --> I[Self-Service BI Frontend]

    J[Security Layer] --> G
    J --> H
    K[Audit Layer] --> D
    K --> G
    K --> H

    classDef source fill:#111827,stroke:#38bdf8,stroke-width:2px,color:#ffffff;
    classDef process fill:#1f2937,stroke:#60a5fa,stroke-width:2px,color:#ffffff;
    classDef output fill:#1e3a8a,stroke:#93c5fd,stroke-width:2px,color:#ffffff;
    classDef governance fill:#064e3b,stroke:#6ee7b7,stroke-width:2px,color:#ffffff;

    class A source;
    class B,C,D,E,F,G,H process;
    class I output;
    class J,K governance;
```

---

## BI V2 Foundation Status

| Area | Status |
|---|---|
| Parallel API service | Foundation validated in private environment |
| Worker service | Foundation validated in private environment |
| Frontend service | Initial dashboard builder validated |
| Database schemas | App, security, warehouse, mart and audit layers designed |
| RBAC | Initial master-user flow validated |
| Dataset catalog | Initial version created |
| Field catalog | Initial version created |
| Dashboard persistence | Validated |
| Tab persistence | Validated |
| Widget persistence | Validated |
| Scheduler | Created and enabled |
| Semantic layer | Initial version only |
| Self-service query builder | Roadmap item |
| Widget deletion | Pending |
| Dashboard/model deletion | Pending |
| Formula builder | Pending |
| Advanced filters | Pending |

---

## BI V2 Next Stage

The next development stage is:

```text
Semantic Layer + Self-Service Query Builder
```

Main objectives:

- Expand semantic views;
- Expand dataset and field catalogs;
- Support multiple dimensions and measures;
- Support filters, sorting and pagination;
- Implement safe calculated fields;
- Add widget editing and deletion;
- Add dashboard/model deletion;
- Implement data freshness and worker status panels.

---

## Data Flow

```mermaid
sequenceDiagram
    participant Provider as External Provider
    participant API as Ingestion API
    participant Storage as Raw / Latest / History Storage
    participant Loader as SQL Loader
    participant SQL as Cloud SQL / PostgreSQL
    participant Worker as BI Worker
    participant Mart as Semantic Mart
    participant UI as BI Frontend

    Provider->>API: Send or expose report
    API->>Storage: Save raw and latest versions
    Storage->>Loader: Normalize and load report
    Loader->>SQL: Insert/update staging tables
    SQL->>Worker: Refresh semantic model
    Worker->>Mart: Update BI-ready views
    Mart->>UI: Serve dashboard widgets and datasets
```

---

## Local Setup

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it on Windows:

```bash
.venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create a local environment file:

```bash
copy .env.example .env
```

Run the app:

```bash
python app.py
```

Open:

```text
http://127.0.0.1:8080/healthz
```

---

## Example Environment Variables

```env
APP_ENV=local
PORT=8080
LOG_LEVEL=INFO

STORAGE_MODE=local
GCS_BUCKET=your-demo-bucket
GCS_PREFIX=report-ingestion-demo

WEBHOOK_API_KEY_NAME=x-webhook-key
WEBHOOK_API_KEY_VALUE=change-me

MANAGE_API_KEY=change-me
DATABASE_URL=postgresql://user:password@host:5432/database
```

Production credentials, API keys, secrets and private URLs must never be committed to the repository.

---

## Deployment Concept

```mermaid
flowchart LR
    A[Source Code] --> B[Cloud Build]
    B --> C[Container Image]
    C --> D[Cloud Run Portal/API]
    C --> E[SQL Loader / Worker]
    D --> F[Storage]
    E --> G[Cloud SQL / PostgreSQL]
    G --> H[Power BI / BI Platform V2]

    classDef build fill:#1f2937,stroke:#38bdf8,stroke-width:2px,color:#ffffff;
    classDef cloud fill:#1e3a8a,stroke:#93c5fd,stroke-width:2px,color:#ffffff;
    classDef output fill:#064e3b,stroke:#6ee7b7,stroke-width:2px,color:#ffffff;

    class A,B,C build;
    class D,E,F,G cloud;
    class H output;
```

---

## Security Notes

This public version intentionally removes:

- real `users.json`;
- `.env` files;
- service-account files;
- secret values;
- internal project IDs;
- real provider endpoints;
- private buckets;
- backup files;
- compiled `__pycache__` files;
- real report payloads;
- raw production logs;
- worker keys;
- JWTs;
- database passwords;
- production Cloud Scheduler headers.

For production, secrets should be injected with Secret Manager or environment variables, never committed to Git.

---

## Pre-Commit Security Scan

A public-safe scan helper may be available in:

```text
scripts/security_scan_before_commit.sh
```

Before committing sensitive updates, run:

```bash
bash scripts/security_scan_before_commit.sh
```

Also manually review:

```bash
git diff --cached
```

Search for:

```text
password
secret
token
jwt
key
x-worker-key
client_secret
database password
Authorization
Bearer
```

---

## Business Impact

This architecture reduces manual handling of recurring financial reports, centralizes report history, improves auditability and creates a cleaner path from operational files to BI-ready SQL tables.

The BI Platform V2 extension increases the strategic value of the project by moving from report ingestion to a self-service analytical foundation, supporting:

| Impact Area | Result |
|---|---|
| Operational Efficiency | Reduces manual report handling and repeated spreadsheet work. |
| Data Reliability | Standardizes column names, formats and latest-report references. |
| Auditability | Preserves raw, historical and normalized data layers. |
| BI Enablement | Creates a structured path to SQL, Power BI and dashboards. |
| Scalability | Allows new reports and datasets to be added with less rework. |
| Governance | Introduces RBAC, audit logs and semantic model separation. |
| Decision Support | Enables faster access to curated management information. |

---

## Public-Safe Scope

This repository focuses on architecture, implementation patterns and sanitized examples.

It intentionally excludes:

- real client data;
- real financial totals;
- real account numbers;
- internal endpoints;
- private credentials;
- production secrets;
- proprietary provider details;
- confidential report payloads.

```mermaid
flowchart TD
    A[Public Repository] --> B[Sanitized Code]
    A --> C[Sample Configuration]
    A --> D[Public-Safe Documentation]
    A --> E[Architecture and Roadmap]

    F[Private Production Layer] --> G[Real Reports]
    F --> H[Client Data]
    F --> I[Credentials]
    F --> J[Internal Infrastructure]

    classDef public fill:#064e3b,stroke:#6ee7b7,stroke-width:2px,color:#ffffff;
    classDef private fill:#7f1d1d,stroke:#fca5a5,stroke-width:2px,color:#ffffff;

    class A,B,C,D,E public;
    class F,G,H,I,J private;
```

---

## Status

Public-safe portfolio version.

The repository demonstrates the technical design and implementation approach without exposing confidential infrastructure, credentials or business data.

The BI Platform V2 layer is documented as a foundation and roadmap for the next stage of the project.

---

## Author

**Lucas Daniel de Oliveira Morandi**

Financial markets professional focused on automation, business intelligence, data workflows and operational efficiency for investment-related processes.

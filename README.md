# Cloud Report Ingestion API

Public-safe version of a financial report ingestion platform built with Python, Flask, Cloud Run, Cloud Storage and PostgreSQL/Cloud SQL.

> This repository is sanitized for portfolio use. It does not include real credentials, real users, real project IDs, internal endpoints, client data, private buckets, or production secrets.

## What this project demonstrates

- A web portal for operational report monitoring;
- Webhook ingestion for external report deliveries;
- Report request/trigger endpoints;
- Cloud Storage landing zone for raw, latest and historical files;
- Column normalization for BI consumption;
- SQL loader for PostgreSQL/Cloud SQL;
- Friendly report names for Power BI and business users;
- Scheduler scripts for automated report collection;
- Example deployment scripts for Cloud Run.

## Architecture

```text
External Report Provider
        ↓
Cloud Run Portal / API
        ↓
Raw + Latest + History Storage
        ↓
SQL Loader
        ↓
Cloud SQL / PostgreSQL
        ↓
Power BI / Operational Portal
```

## Main files

```text
app.py                              # Portal and webhook app
report_ingestion_service.py          # API/report ingestion service
sql_loader.py                        # SQL/BI loading layer
report_column_normalizer.py          # Column and value normalization helpers
config/reports.example.txt           # Public-safe report catalog example
config/report_api_catalog.example.json
config/column_mappings.example.json
config/report_names.example.json
sql/schema_cloudsql.sql
scripts/cloud_scheduler_setup.example.sh
scripts/deploy_cloud_run_cloudsql.example.sh
scripts/sync_reports_to_onedrive.example.ps1
Dockerfile.portal
Dockerfile.sql_loader
```

## Local setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python app.py
```

Open:

```text
http://127.0.0.1:8080/healthz
```

## Security notes

This public version intentionally removes:

- real `users.json`;
- `.env` files;
- service-account files;
- secret values;
- internal project IDs;
- real provider endpoints;
- backup files;
- compiled `__pycache__` files;
- real report payloads.

For production, secrets should be injected with Secret Manager or environment variables, never committed to Git.

## Business impact

This architecture reduces manual handling of recurring financial reports, centralizes report history, improves auditability, and creates a cleaner path from operational files to BI-ready SQL tables.

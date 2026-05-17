# Session Log — BI Platform V2 Foundation

Date: 2026-05-17  
Project: Financial Report Ingestion / BI Platform V2

## Executive Summary

This session evolved the existing financial report ingestion architecture into the foundation of a parallel BI Platform V2.

The goal was to preserve the current production portal while creating a more robust self-service BI foundation with:

- API layer;
- worker-based mart refresh;
- frontend dashboard builder;
- SQL semantic mart;
- RBAC and audit structure;
- daily snapshot semantics;
- scheduler automation;
- dashboard/widget persistence.

The result is a validated V2 foundation that can evolve into a self-service analytical platform.

---

## Current Validated State

### Database V2

New logical schemas were created in the application database:

| Layer | Purpose |
|---|---|
| `app` | Application objects such as dashboards, tabs and widgets. |
| `sec` | Users, roles, permissions and scope rules. |
| `dw` | Data warehouse / normalized source layer. |
| `mart` | Semantic and analytical views. |
| `audit` | Events, jobs, execution logs and traceability. |

Initial objects created:

- users and roles;
- RBAC permissions;
- scope rules;
- report catalog;
- dataset catalog;
- field catalog;
- dashboards;
- tabs;
- widgets;
- worker load events;
- daily snapshot control;
- mart dimensions and facts.

Initial master user was created in the private environment and validated with a global scope.

> Public note: real e-mails, user identifiers and credentials are intentionally omitted from this repository.

---

### API V2

A new API service was created to support:

- readiness checks;
- authentication;
- current user permissions;
- report catalog;
- dataset catalog;
- field catalog;
- dashboard creation;
- tab creation;
- widget creation;
- dataset query endpoint.

Validated capabilities:

- API health/readiness;
- login flow;
- permission lookup;
- catalog endpoints;
- dashboard persistence;
- tab persistence;
- widget persistence;
- query endpoint for current positions.

---

### Worker V2

A worker service was created to refresh the semantic mart.

Validated responsibilities:

- run incremental mart refresh;
- update dimensions;
- update facts;
- refresh current-position semantic view;
- refresh profitability fact layer;
- register load events;
- preserve daily snapshot logic.

Validated output categories:

- account dimension;
- advisor dimension;
- product dimension;
- historical positions fact;
- current positions semantic view;
- profitability fact;
- dashboard KPI values.

> Public note: production row counts and financial values are intentionally not included in this public-safe version.

---

### Scheduler

A scheduler job was created to trigger the mart refresh during the operating window.

Recommended configuration:

```text
schedule: 30 7-20 * * *
timezone: America/Sao_Paulo
attemptDeadline: 900s
maxRetryAttempts: 0
```

Why:

- the worker may take longer than the default deadline;
- retries can overlap executions if a previous refresh is still running;
- mart refresh jobs should be auditable and controlled.

---

### Frontend V2

A frontend dashboard builder was created as the initial UI foundation.

Validated features:

- login screen;
- authenticated dashboard access;
- dashboard list;
- Excel-like tabs;
- initial widgets;
- KPI cards;
- chart widgets;
- layout rendering.

Initial limitations observed:

- created widgets were not yet deletable through the UI;
- created dashboards/models were not yet deletable through the UI;
- the self-service builder still needed semantic layer expansion.

---

## Major Problems Found and Fixes Applied

### 1. Cloud SQL connection variable empty

Problem:

```text
could not parse resource []
```

Cause: database instance variable was empty.

Fix: explicitly set the project, instance and database variables before running database commands.

---

### 2. Database password mismatch

Problem: authentication failed for the admin database user.

Resolution: used the operational loader user and existing secret-managed password instead of changing production credentials.

Public-safe rule: never document or commit actual database passwords.

---

### 3. Cloud SQL proxy port already in use

Problem:

```text
listen tcp 127.0.0.1:<port>: bind: address already in use
```

Fix: stopped old proxy processes and used alternate local ports when needed.

---

### 4. Bootstrap password variable not visible to Python

Problem: a shell variable existed in the terminal but was not exported to child processes.

Fix:

```bash
export NEW_BI_PASSWORD
```

Public-safe rule: do not commit the real password or bootstrap value.

---

### 5. Bootstrap token invalid

Problem: setup token mismatch, likely caused by newline or secret version behavior.

Fix: created a clean token without newline and redeployed the API.

---

### 6. Password hashing failed

Problem: API returned `500` during password bootstrap.

Likely cause: compatibility issue between password hashing library and dependency version.

Fix: pinned the compatible dependency version and redeployed.

---

### 7. Dashboard ID extraction failed

Problem: `dashboard_id` was extracted from the wrong JSON level.

Cause: API returned the ID inside a nested `dashboard` object.

Fix: updated the extraction path.

---

### 8. Widget creation route mismatch

Problem: the frontend or test command used the wrong route shape.

Correct pattern:

```text
POST /dashboards/tabs/{tab_id}/widgets
```

---

### 9. Worker accidentally deployed over API service

Problem: the service name variable still pointed to the API service.

Fix: forced the worker service name in the worker deploy script.

---

### 10. SQLAlchemy / psycopg multi-command issue

Problem:

```text
cannot insert multiple commands into a prepared statement
```

Fix: converted multi-command SQL blocks into a single statement using CTEs.

---

### 11. PostgreSQL ambiguous parameter type

Problem:

```text
could not determine data type of parameter
```

Fix: explicitly cast ambiguous parameters, such as:

```sql
CAST(:batch_key AS text)
```

---

### 12. Duplicated total exposure / PL

Problem: summing across multiple snapshots duplicated total exposure.

Fix:

- keep historical facts in the fact table;
- expose current dashboard values through a current-position semantic view;
- preserve separate daily/historical views for time series analysis.

---

## What Was Completed

```text
BI V2 foundation completed:
- Parallel API, worker and frontend services created
- Database V2 schema design validated
- RBAC and master user flow initialized
- API login and dashboard endpoints validated
- Worker refresh validated with private production data
- Scheduler created and enabled
- Initial frontend dashboard builder deployed
- Current-position total exposure validated through API and UI
```

---

## Public-Safe Notes

This session log intentionally removes:

- real project IDs;
- real service URLs;
- real user e-mails;
- real production row counts;
- real financial totals;
- tokens;
- passwords;
- JWTs;
- worker keys;
- raw logs;
- database credentials.

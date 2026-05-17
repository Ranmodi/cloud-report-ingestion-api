# Troubleshooting — BI Platform V2

This document records public-safe troubleshooting notes for the BI Platform V2 foundation.

---

## Cloud SQL proxy port already in use

Symptom:

```text
listen tcp 127.0.0.1:<port>: bind: address already in use
```

Fix:

```bash
pkill -f "cloud-sql-proxy" || true
pkill -f "cloud_sql_proxy" || true
```

Use another local port if needed:

```bash
export DB_PORT="9475"
```

---

## Database instance variable empty

Symptom:

```text
could not parse resource []
```

Cause: the database instance variable was empty.

Fix:

```bash
export INSTANCE="your-database-instance"
```

---

## Dashboard ID extraction returns empty

Symptom:

```bash
DASHBOARD_ID=
```

Cause: API returns `dashboard_id` inside a nested object.

Correct extraction pattern:

```bash
export DASHBOARD_ID="$(echo "$DASHBOARD_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['dashboard']['dashboard_id'])")"
```

---

## Widget creation route

Correct endpoint pattern:

```text
POST /dashboards/tabs/{tab_id}/widgets
```

Incorrect pattern:

```text
POST /dashboards/{dashboard_id}/tabs/{tab_id}/widgets
```

---

## Bootstrap password variable not visible to Python

Cause: shell variable was not exported.

Fix:

```bash
export NEW_BI_PASSWORD
```

Public-safe rule: never commit the actual password.

---

## Setup token invalid

Possible cause: newline mismatch in secret value.

Fix:

- recreate the secret without a trailing newline;
- redeploy the API;
- validate with a fresh token.

Do not commit the token.

---

## Password hashing error

Possible cause: dependency compatibility issue.

Fix:

- pin a compatible hashing dependency version;
- redeploy;
- validate bootstrap flow again.

---

## Numeric overflow in profitability or percentage columns

Cause: malformed, extreme or incorrectly parsed percentages.

Fix:

- sanitize values before insert;
- use `NULL` for invalid/extreme percentages;
- preserve original payload in an `attributes` or raw column.

---

## Total exposure / PL duplicated

Cause: summing multiple position snapshots.

Fix:

- keep historical positions in fact tables;
- expose current dashboard values through a current-position semantic view;
- expose daily history through a separate daily view;
- expose full history through a separate historical dataset.

---

## Worker deployed over API service

Cause: service name variable pointed to the API service.

Fix:

```bash
export SERVICE_NAME="bi-platform-worker"
```

Also patch the worker deployment script to force the service name.

---

## SQLAlchemy / psycopg multiple commands error

Symptom:

```text
cannot insert multiple commands into a prepared statement
```

Fix: convert multi-command SQL into a single statement using CTEs.

---

## PostgreSQL cannot determine parameter type

Symptom:

```text
could not determine data type of parameter
```

Fix: cast ambiguous parameters explicitly:

```sql
CAST(:batch_key AS text)
```

---

## Scheduler deadline too short

Initial scheduler deadlines may be too short for mart refresh jobs.

Recommended:

```bash
gcloud scheduler jobs update http "$JOB_NAME" \
  --project="$PROJECT_ID" \
  --location="$REGION" \
  --attempt-deadline="900s" \
  --max-retry-attempts=0
```

---

## Security warning

Never commit:

- worker keys;
- JWT tokens;
- database passwords;
- API client secrets;
- raw logs containing headers;
- `.env` files;
- database dumps;
- private scheduler output.

Rotate any secret that was pasted into logs or committed by accident.

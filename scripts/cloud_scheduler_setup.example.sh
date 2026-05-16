#!/usr/bin/env bash
set -euo pipefail

# Ajuste as variáveis antes de rodar.
PROJECT_ID="${PROJECT_ID:-seu-projeto-gcp}"
REGION="${REGION:-southamerica-east1}"
PORTAL_URL="${PORTAL_URL:-https://your-cloud-run-url.run.app}"
SQL_LOADER_URL="${SQL_LOADER_URL:-https://your-cloud-run-url.run.app}"
MANAGE_API_KEY="${MANAGE_API_KEY:-troque-esta-chave}"

# Habilita Cloud Scheduler.
gcloud services enable cloudscheduler.googleapis.com --project "$PROJECT_ID"

# Dispara todos os relatórios todo dia, de hora em hora, das 07h às 20h, horário de Brasília.
gcloud scheduler jobs create http report-ingestion-trigger-hourly \
  --project "$PROJECT_ID" \
  --location "$REGION" \
  --schedule "0 7-20 * * *" \
  --time-zone "America/Sao_Paulo" \
  --uri "${PORTAL_URL%/}/admin/trigger-all" \
  --http-method POST \
  --headers "x-manage-key=${MANAGE_API_KEY}" \
  --attempt-deadline "30m" || \
gcloud scheduler jobs update http report-ingestion-trigger-hourly \
  --project "$PROJECT_ID" \
  --location "$REGION" \
  --schedule "0 7-20 * * *" \
  --time-zone "America/Sao_Paulo" \
  --uri "${PORTAL_URL%/}/admin/trigger-all" \
  --http-method POST \
  --headers "x-manage-key=${MANAGE_API_KEY}" \
  --attempt-deadline "30m"

# Processa a fila SQL a cada 5 minutos no horário útil. O webhook cria job rápido;
# este scheduler faz a carga pesada sem travar o portal.
gcloud scheduler jobs create http report-ingestion-sql-process \
  --project "$PROJECT_ID" \
  --location "$REGION" \
  --schedule "*/5 7-21 * * *" \
  --time-zone "America/Sao_Paulo" \
  --uri "${SQL_LOADER_URL%/}/jobs/process" \
  --http-method POST \
  --headers "Content-Type=application/json" \
  --message-body '{"limit":3}' \
  --attempt-deadline "30m" || \
gcloud scheduler jobs update http report-ingestion-sql-process \
  --project "$PROJECT_ID" \
  --location "$REGION" \
  --schedule "*/5 7-21 * * *" \
  --time-zone "America/Sao_Paulo" \
  --uri "${SQL_LOADER_URL%/}/jobs/process" \
  --http-method POST \
  --headers "Content-Type=application/json" \
  --message-body '{"limit":3}' \
  --attempt-deadline "30m"

echo "Schedulers configurados."

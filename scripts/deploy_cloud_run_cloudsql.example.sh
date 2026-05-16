#!/usr/bin/env bash
set -euo pipefail

# Ajuste estes valores antes de rodar.
PROJECT_ID="${PROJECT_ID:-seu-projeto-gcp}"
REGION="${REGION:-southamerica-east1}"
SERVICE_NAME="${SERVICE_NAME:-report-ingestion}"
SQL_INSTANCE="${SQL_INSTANCE:-report-ingestion-sql}"
DB_NAME="${DB_NAME:-reports_db}"
DB_USER="${DB_USER:-report_loader}"
GCS_BUCKET="${GCS_BUCKET:-seu-bucket-report-ingestion}"
IMAGE="gcr.io/${PROJECT_ID}/${SERVICE_NAME}:v2"

# Segredos: crie antes com:
# printf 'SEU_CLIENT_ID' | gcloud secrets create provider-client-id --data-file=- --replication-policy=automatic
# printf 'SEU_CLIENT_SECRET' | gcloud secrets create provider-client-secret --data-file=- --replication-policy=automatic
# printf 'SENHA_FORTE_DO_DB' | gcloud secrets create provider-db-pass --data-file=- --replication-policy=automatic

PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
RUN_SA="${PROJECT_NUMBER}user@example.com"

# APIs necessárias
gcloud services enable run.googleapis.com sqladmin.googleapis.com secretmanager.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com storage.googleapis.com --project "$PROJECT_ID"

# Cloud SQL PostgreSQL. Pule se a instância já existir.
gcloud sql instances describe "$SQL_INSTANCE" --project "$PROJECT_ID" >/dev/null 2>&1 || \
  gcloud sql instances create "$SQL_INSTANCE" \
    --project "$PROJECT_ID" \
    --database-version=POSTGRES_16 \
    --tier=db-g1-small \
    --region="$REGION" \
    --storage-type=SSD \
    --storage-size=20GB \
    --availability-type=zonal

# Banco e usuário. Se já existirem, os comandos podem retornar erro; ajuste conforme necessário.
gcloud sql databases create "$DB_NAME" --instance="$SQL_INSTANCE" --project "$PROJECT_ID" || true
DB_PASS=$(gcloud secrets versions access latest --secret=provider-db-pass --project "$PROJECT_ID")
gcloud sql users create "$DB_USER" --instance="$SQL_INSTANCE" --password="$DB_PASS" --project "$PROJECT_ID" || true

# Permissões para Cloud Run acessar Secret Manager e Cloud SQL.
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${RUN_SA}" \
  --role="roles/secretmanager.secretAccessor"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${RUN_SA}" \
  --role="roles/cloudsql.client"

# Build da imagem.
gcloud builds submit \
  --project "$PROJECT_ID" \
  --tag "$IMAGE" \
  --file Dockerfile_v2 .

INSTANCE_CONNECTION_NAME="${PROJECT_ID}:${REGION}:${SQL_INSTANCE}"

# Deploy Cloud Run conectado ao Cloud SQL e usando secrets.
gcloud run deploy "$SERVICE_NAME" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --image "$IMAGE" \
  --platform managed \
  --allow-unauthenticated \
  --add-cloudsql-instances "$INSTANCE_CONNECTION_NAME" \
  --set-env-vars "GCS_BUCKET=${GCS_BUCKET},GCS_PREFIX=report-ingestion,INSTANCE_CONNECTION_NAME=${INSTANCE_CONNECTION_NAME},DB_NAME=${DB_NAME},DB_USER=${DB_USER},AUTO_INIT_DB=true" \
  --set-secrets "PROVIDER_CLIENT_ID=provider-client-id:latest,PROVIDER_CLIENT_SECRET=provider-client-secret:latest,DB_PASS=provider-db-pass:latest"

SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" --project "$PROJECT_ID" --region "$REGION" --format='value(status.url)')
echo "Deploy concluído: ${SERVICE_URL}"
echo "Webhook padrão: ${SERVICE_URL}/webhook/provider/<report_key>"
echo "Healthcheck: ${SERVICE_URL}/healthz"

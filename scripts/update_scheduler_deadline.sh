#!/usr/bin/env bash
set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID before running this script}"
: "${REGION:?Set REGION before running this script}"
: "${JOB_NAME:?Set JOB_NAME before running this script}"

gcloud scheduler jobs update http "$JOB_NAME" \
  --project="$PROJECT_ID" \
  --location="$REGION" \
  --attempt-deadline="900s" \
  --max-retry-attempts=0

gcloud scheduler jobs describe "$JOB_NAME" \
  --project="$PROJECT_ID" \
  --location="$REGION" \
  --format="yaml(name,schedule,timeZone,state,attemptDeadline,retryConfig.maxRetryAttempts,httpTarget.uri,lastAttemptTime)"

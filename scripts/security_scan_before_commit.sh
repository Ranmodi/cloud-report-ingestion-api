#!/usr/bin/env bash
set -euo pipefail

echo "Running staged diff security scan..."

PATTERN='x-worker-key|access_token|refresh_token|id_token|jwt|password|passwd|secret|client_secret|db_pass|database_url|authorization:|bearer |private key|api_key|apikey|token='

if git diff --cached --name-only | grep -E '(^|/)(\.env|.*\.pem|.*\.key|.*service-account.*\.json|credentials/|secrets/)' >/dev/null; then
  echo "Blocked: staged files include environment, key or credential-like files."
  git diff --cached --name-only | grep -E '(^|/)(\.env|.*\.pem|.*\.key|.*service-account.*\.json|credentials/|secrets/)'
  exit 1
fi

if git diff --cached | grep -Ein "$PATTERN" >/tmp/security_scan_hits.txt; then
  echo "Potential sensitive content found in staged diff:"
  cat /tmp/security_scan_hits.txt
  echo ""
  echo "Review and remove sensitive values before committing."
  exit 1
fi

echo "Security scan passed."

# GitHub Update Notes — BI Platform V2

## Suggested commit title for public repository

```text
docs: add BI Platform V2 foundation notes and roadmap
```

## Suggested commit body

```text
- document BI Platform V2 architecture with API, worker, frontend and semantic mart layers
- document database schema strategy for app, security, warehouse, mart and audit layers
- document RBAC model and initial master-user validation flow
- document worker refresh process and daily snapshot policy
- document smart numeric normalization for US/BR financial formats
- document current-position semantic view strategy to avoid duplicated totals
- document Cloud Scheduler configuration and worker refresh cadence
- document frontend validation and self-service BI roadmap
- document troubleshooting issues encountered and fixes applied
- add continuation prompt for the next development session
```

---

## Suggested README section

Copy the content from:

```text
docs/README_BI_V2_SECTION.md
```

into the main repository `README.md`.

---

## Recommended files to add

```text
docs/SESSION_LOG_BI_V2_FOUNDATION.md
docs/NEXT_STEPS_BI_V2.md
docs/TROUBLESHOOTING_BI_V2.md
docs/GITHUB_UPDATE_NOTES.md
docs/README_BI_V2_SECTION.md
docs/STATUS_BI_V2.md
docs/SECURITY_REVIEW_BI_V2.md
prompts/NEXT_CHAT_PROMPT_BI_V2.md
scripts/update_scheduler_deadline.sh
scripts/security_scan_before_commit.sh
CHANGELOG_BI_V2.md
```

---

## Suggested commands

```bash
git status

git checkout -b docs/bi-platform-v2-foundation

mkdir -p docs prompts scripts

# Copy the sanitized files into the repository.
# Then review all changes:
git diff

# Stage files:
git add docs prompts scripts CHANGELOG_BI_V2.md README.md

# Security scan:
bash scripts/security_scan_before_commit.sh

# Commit:
git commit -m "docs: add BI Platform V2 foundation notes and roadmap"

# Push:
git push origin docs/bi-platform-v2-foundation
```

---

## Security checklist before push

```bash
git diff --cached | grep -Ei "x-worker-key|access_token|jwt|password|secret|client_secret|DB_PASS|API_KEY|PRIVATE KEY" || true
```

If anything sensitive appears, remove it before committing.

---

## Do not commit

```text
.env
*.secret
*token*
*password*
logs with worker keys
logs with JWT
database dumps with client data
Cloud Scheduler output containing secret headers
service account files
```

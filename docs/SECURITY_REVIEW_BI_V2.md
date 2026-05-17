# Security Review — BI Platform V2 GitHub Update

This update pack was sanitized for public GitHub use.

## Removed or generalized

- real project IDs;
- real service URLs;
- real user e-mails;
- real database names where sensitive;
- real service names where sensitive;
- production row counts;
- production financial totals;
- tokens;
- passwords;
- JWTs;
- worker keys;
- raw Cloud Scheduler output;
- database credentials;
- client/account data.

## Public-safe conventions used

| Private concept | Public-safe replacement |
|---|---|
| Real project ID | `PROJECT_ID` |
| Real region | `REGION` |
| Real API service | `bi-platform-api` |
| Real worker service | `bi-platform-worker` |
| Real frontend service | `bi-platform-web` |
| Real e-mail | `master.user@example.com` |
| Real schema prefix | generic `app`, `sec`, `dw`, `mart`, `audit` |
| Real row counts | omitted or described qualitatively |
| Real financial totals | omitted or described qualitatively |

## Pre-commit security scan

Run:

```bash
bash scripts/security_scan_before_commit.sh
```

## Manual review

Also run:

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

## If a secret was committed

1. Remove it from the repository.
2. Rotate the secret immediately.
3. Review git history.
4. Consider using repository secret scanning.
5. Force-push only if the repository policy allows it and the team agrees.

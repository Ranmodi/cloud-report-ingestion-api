# Security Review

Sanitization actions applied before publishing:

- Removed `users.json` from the original project and replaced it with `config/users.example.json`.
- Removed backup files and `__pycache__` compiled files.
- Replaced provider/company-specific naming with generic placeholders.
- Replaced public examples of provider URLs with `https://api.example-provider.com`.
- Replaced project, bucket, SQL and service names with placeholders.
- Removed hardcoded user names and password-like values.
- Moved report catalogs to public-safe examples.

Before making any derivative repository public, run your own review again and verify the Git history does not contain secrets.

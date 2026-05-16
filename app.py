import os
import io
import csv
import json
import uuid
import time
import random
import base64
import hashlib
import logging
import traceback
import re
import zipfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import wraps
from typing import Optional, Dict, Tuple, List
from zoneinfo import ZoneInfo

import requests
from flask import (
    Flask, jsonify, request, abort, send_file, redirect, url_for,
    session, render_template_string, flash
)
from werkzeug.security import check_password_hash
from google.cloud import storage
from report_column_normalizer import (
    load_json_mapping, normalize_csv_for_download,
    friendly_report_filename, safe_blob_component,
)

UTC = timezone.utc
BRT = ZoneInfo("America/Sao_Paulo")
APP_NAME = "report-ingestion"

CLIENT_ID = (os.getenv("PROVIDER_CLIENT_ID") or "").strip()
CLIENT_SECRET = (os.getenv("PROVIDER_CLIENT_SECRET") or "").strip()
TOKEN_URL = (os.getenv("PROVIDER_TOKEN_URL") or "https://api.example-provider.com/iaas-auth/api/v1/authorization/oauth2/accesstoken").strip()

GCS_BUCKET = (os.getenv("GCS_BUCKET") or "").strip()
GCS_PREFIX = (os.getenv("GCS_PREFIX") or "managed-reports").strip().strip("/")
SAVE_DIR = Path((os.getenv("SAVE_DIR") or "/tmp").strip())
SAVE_DIR.mkdir(parents=True, exist_ok=True)

PORT = int((os.getenv("PORT") or "8080").strip())
HTTP_TIMEOUT_S = int((os.getenv("HTTP_TIMEOUT_S") or "60").strip())
DOWNLOAD_TIMEOUT_S = int((os.getenv("DOWNLOAD_TIMEOUT_S") or "120").strip())
BACKOFF_BASE_S = float((os.getenv("BACKOFF_BASE_S") or "3").strip())
BACKOFF_MAX_S = float((os.getenv("BACKOFF_MAX_S") or "45").strip())

GCS_UPLOAD_TIMEOUT_S = int((os.getenv("GCS_UPLOAD_TIMEOUT_S") or "180").strip())
GCS_UPLOAD_MAX_ATTEMPTS = int((os.getenv("GCS_UPLOAD_MAX_ATTEMPTS") or "5").strip())
GCS_UPLOAD_BACKOFF_BASE_S = float((os.getenv("GCS_UPLOAD_BACKOFF_BASE_S") or "2").strip())
GCS_UPLOAD_BACKOFF_MAX_S = float((os.getenv("GCS_UPLOAD_BACKOFF_MAX_S") or "30").strip())
GCS_UPLOAD_CHUNK_MB = int((os.getenv("GCS_UPLOAD_CHUNK_MB") or "8").strip())

WEBHOOK_API_KEY_NAME = (os.getenv("WEBHOOK_API_KEY_NAME") or "").strip()
WEBHOOK_API_KEY_VALUE = (os.getenv("WEBHOOK_API_KEY_VALUE") or "").strip()
MANAGE_API_KEY = (os.getenv("MANAGE_API_KEY") or "").strip()
TRIGGER_ON_START = (os.getenv("TRIGGER_ON_START") or "false").lower() in {"1", "true", "yes"}

# Espelhamento opcional dos webhooks recebidos pelo Portal para a API SQL.
# Mantém o PROVIDER apontando para a URL antiga do Portal e, ao mesmo tempo,
# alimenta o serviço report-ingestion-api / Cloud SQL.
SQL_MIRROR_WEBHOOK_BASE = (os.getenv("SQL_MIRROR_WEBHOOK_BASE") or "").strip().rstrip("/")
SQL_MIRROR_TIMEOUT_S = int((os.getenv("SQL_MIRROR_TIMEOUT_S") or "30").strip())
SQL_MIRROR_API_KEY_NAME = (os.getenv("SQL_MIRROR_API_KEY_NAME") or "").strip()
SQL_MIRROR_API_KEY_VALUE = (os.getenv("SQL_MIRROR_API_KEY_VALUE") or "").strip()

REPORTS_CONFIG_FILE = (os.getenv("REPORTS_CONFIG_FILE") or "reports.txt").strip()
REPORTS_CONFIG_GCS_BLOB = (os.getenv("REPORTS_CONFIG_GCS_BLOB") or "").strip()

COLUMN_MAPPING_FILE = (os.getenv("COLUMN_MAPPING_FILE") or "column_mappings.json").strip()
COLUMN_MAPPING_GCS_BLOB = (os.getenv("COLUMN_MAPPING_GCS_BLOB") or "config/column_mappings.json").strip()
VISIBLE_REPORTS_GCS_BLOB = (os.getenv("VISIBLE_REPORTS_GCS_BLOB") or "config/visible_reports.json").strip()
HISTORY_GCS_PREFIX = (os.getenv("HISTORY_GCS_PREFIX") or "HISTORICO").strip().strip("/")
ONEDRIVE_EXPORT_GCS_PREFIX = (os.getenv("ONEDRIVE_EXPORT_GCS_PREFIX") or "drive-sync/Relatórios atualizados").strip().strip("/")
TRIGGER_ALL_DELAY_S = float((os.getenv("TRIGGER_ALL_DELAY_S") or "1.5").strip())
TRIGGER_ALL_REPORTS = [x.strip() for x in (os.getenv("TRIGGER_ALL_REPORTS") or "").split(",") if x.strip()]

USERS_FILE = (os.getenv("USERS_FILE") or "users.json").strip()
USERS_GCS_BLOB = (os.getenv("USERS_GCS_BLOB") or "").strip()
USERS_JSON = (os.getenv("USERS_JSON") or "").strip()

MONETARY_COLUMNS = {c.strip().lower() for c in (os.getenv("MONETARY_COLUMNS") or "").split(",") if c.strip()}
MONEY_HINT = re.compile(r"(valor|vlr|amount|saldo|pre(ç|c)o|price|rate|juros|multa|taxa|bruto|liquido|líquido)$", re.I)
LOG_LEVEL = (os.getenv("LOG_LEVEL") or "INFO").upper()

app = Flask(__name__)
app.secret_key = (os.getenv("APP_SESSION_SECRET") or "troque-esta-chave").strip()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=True,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
)

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(APP_NAME)

LOGIN_TEMPLATE = """
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <title>PROVIDER Reports | Login</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root{
      --bg:#071327;
      --card:#0c1a33;
      --line:#243b66;
      --muted:#9bb2d7;
      --text:#ecf3ff;
      --primary:#2f6df6;
      --danger-bg:#781c1c;
      --danger-text:#ffd5d5;
    }
    *{box-sizing:border-box}
    body { font-family: Arial, sans-serif; background:linear-gradient(180deg,#061124 0%, #08162c 100%); color:var(--text); margin:0; }
    .wrap { min-height:100vh; display:flex; align-items:center; justify-content:center; padding:24px; }
    .card { width:100%; max-width:460px; background:var(--card); border:1px solid var(--line); border-radius:18px; padding:28px; box-shadow:0 14px 34px rgba(0,0,0,.28);}
    h1 { margin:0 0 8px; font-size:22px; }
    p { color:var(--muted); margin:0 0 18px; }
    input { width:100%; margin:8px 0 14px; padding:12px; border-radius:10px; border:1px solid #3b5c98; background:#081225; color:#fff; }
    button { width:100%; padding:12px; border:none; border-radius:10px; background:var(--primary); color:#fff; font-weight:bold; cursor:pointer; }
    .flash { background:var(--danger-bg); color:var(--danger-text); padding:10px 12px; border-radius:10px; margin-bottom:14px; }
    .hint { margin-top:16px; font-size:12px; color:#6f8fc2; }
  </style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <h1>PROVIDER Reports</h1>
    <p>Faça login para solicitar e baixar relatórios.</p>
    {% with msgs = get_flashed_messages() %}
      {% if msgs %}
        {% for msg in msgs %}
          <div class="flash">{{ msg }}</div>
        {% endfor %}
      {% endif %}
    {% endwith %}
    <form method="post">
      <label>Usuário</label>
      <input type="text" name="username" autocomplete="username" required>
      <label>Senha</label>
      <input type="password" name="password" autocomplete="current-password" required>
      <button type="submit">Entrar</button>
    </form>
    <div class="hint">Acesso protegido. Downloads e disparos só após autenticação.</div>
  </div>
</div>
</body>
</html>
"""

DASHBOARD_TEMPLATE = """
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <title>PROVIDER Reports | Portal</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root{
      --bg:#061124;
      --card:#0b1830;
      --line:#23406f;
      --muted:#9bb2d7;
      --text:#edf4ff;
      --primary:#2f6df6;
      --secondary:#132543;
      --await-bg:#5a3b05;
      --await-text:#ffe19c;
      --flash-bg:#0f5132;
      --flash-text:#d1f7df;
      --warn-bg:#5b250f;
      --warn-text:#ffd0ad;
    }
    *{box-sizing:border-box}
    body { font-family: Arial, sans-serif; background:var(--bg); color:var(--text); margin:0; }
    header { padding:18px 24px; border-bottom:1px solid var(--line); display:flex; justify-content:space-between; align-items:center; gap:16px; }
    .brand { font-size:22px; font-weight:700; margin-bottom:4px; }
    .sub { color:var(--muted); font-size:14px; }
    main { padding:20px 24px 40px; max-width:1320px; margin:0 auto; }
    .toolbar { display:flex; flex-wrap:wrap; gap:12px; align-items:center; margin-bottom:16px; }
    .toolbar .group { display:flex; flex-wrap:wrap; gap:10px; align-items:center; }
    .btn, button, select { border-radius:10px; padding:10px 14px; font-weight:600; }
    .btn, button { border:none; cursor:pointer; text-decoration:none; display:inline-flex; align-items:center; justify-content:center; }
    .btn-primary { background:var(--primary); color:#fff; }
    .btn-secondary { background:var(--secondary); color:var(--text); border:1px solid var(--line); }
    .sort-select, .format-select { background:#081225; color:var(--text); border:1px solid #35558b; }
    .grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(360px, 1fr)); gap:16px; }
    .card { background:var(--card); border:1px solid var(--line); border-radius:18px; padding:18px; display:flex; flex-direction:column; gap:10px; }
    .card-top { display:flex; gap:12px; align-items:flex-start; }
    .card-top input[type="checkbox"] { transform:scale(1.2); margin-top:5px; }
    .title { font-size:17px; font-weight:700; margin:0; }
    .observation { color:var(--muted); font-size:13px; line-height:1.45; margin-top:6px; }
    .info-label { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.05em; }
    .info-value { font-size:15px; }
    .badge-await { display:inline-flex; width:max-content; background:var(--await-bg); color:var(--await-text); border-radius:999px; padding:6px 10px; font-size:12px; font-weight:700; }
    .actions { display:flex; gap:10px; flex-wrap:wrap; align-items:center; }
    .flash { background:var(--flash-bg); color:var(--flash-text); padding:12px; border-radius:12px; margin-bottom:14px; }
    .warn { background:var(--warn-bg); color:var(--warn-text); padding:12px; border-radius:12px; margin-bottom:14px; }
    .muted { color:var(--muted); }
    .top-right a { color:#d7e6ff; text-decoration:none; }
    .empty { color:#7f98bf; }
    details.menu { position:relative; }
    details.menu summary { list-style:none; }
    details.menu summary::-webkit-details-marker { display:none; }
    .menu-body {
      position:absolute; top:44px; left:0; min-width:180px; z-index:10;
      background:#0b1830; border:1px solid var(--line); border-radius:12px;
      padding:8px; box-shadow:0 12px 28px rgba(0,0,0,.28);
    }
    .menu-body a {
      display:block; padding:10px 12px; color:var(--text); text-decoration:none;
      border-radius:8px;
    }
    .menu-body a:hover { background:#102345; }
    .hint { color:var(--muted); font-size:12px; }
    @media (max-width: 760px){
      .toolbar { align-items:stretch; }
      .toolbar .group { width:100%; }
      .grid { grid-template-columns:1fr; }
    }
  </style>
  <script>
    function toggleAll(source) {
      const checks = document.querySelectorAll('input[name="reports"]');
      checks.forEach(c => c.checked = source.checked);
    }

    function changeSort(value) {
      const url = new URL(window.location.href);
      url.searchParams.set('sort', value);
      window.location.href = url.toString();
    }
  </script>
</head>
<body>
<header>
  <div>
    <div class="brand">Portal PROVIDER Reports</div>
    <div class="sub">Usuário: {{ full_name }}</div>
  </div>
  <div class="top-right"><a href="{{ url_for('logout') }}">Sair</a></div>
</header>

<main>
  {% with msgs = get_flashed_messages() %}
    {% if msgs %}
      {% for msg in msgs %}<div class="flash">{{ msg }}</div>{% endfor %}
    {% endif %}
  {% endwith %}

  {% if warning %}<div class="warn">{{ warning }}</div>{% endif %}

  <form method="post" id="reports-form">
    <div class="toolbar">
      <div class="group">
        <label class="muted"><input type="checkbox" onclick="toggleAll(this)"> Selecionar todos</label>
        <button class="btn btn-primary" type="submit" formaction="{{ url_for('ui_trigger_selected') }}">Solicitar selecionados</button>
      </div>

      <div class="group">
        <select name="download_format" class="format-select">
          <option value="excel">Baixar selecionados em Excel</option>
          <option value="raw">Baixar selecionados em CSV bruto</option>
          <option value="meta">Baixar selecionados em Metadados</option>
        </select>
        <button class="btn btn-secondary" type="submit" formaction="{{ url_for('download_selected') }}">Baixar selecionados</button>
      </div>

      <div class="group">
        <a class="btn btn-secondary" href="{{ url_for('visibility_settings') }}">Relatórios da tela</a>
        {% if hidden_count and hidden_count > 0 %}
          <span class="hint">{{ hidden_count }} oculto(s)</span>
        {% endif %}
      </div>

      <div class="group">
        <label class="hint">Ordenar por</label>
        <select class="sort-select" onchange="changeSort(this.value)">
          <option value="recent_desc" {% if sort_mode == 'recent_desc' %}selected{% endif %}>Mais recentes primeiro</option>
          <option value="recent_asc" {% if sort_mode == 'recent_asc' %}selected{% endif %}>Mais antigos primeiro</option>
        </select>
        <a class="btn btn-secondary" href="{{ url_for('dashboard', sort=sort_mode) }}">Atualizar</a>
      </div>
    </div>

    <div class="grid">
      {% for r in reports %}
      <div class="card">
        <div class="card-top">
          <input type="checkbox" name="reports" value="{{ r.report_key }}">
          <div>
            <div class="title">{{ r.display_name }}</div>
            {% if r.observation %}
              <div class="observation">{{ r.observation }}</div>
            {% endif %}
          </div>
        </div>

        {% if r.pending_notice %}
          <div class="badge-await">Aguardando próxima janela do PROVIDER</div>
          {% if r.pending_message %}
            <div class="muted">{{ r.pending_message }}</div>
          {% endif %}
        {% endif %}

        {% if r.latest %}
          <div>
            <div class="info-label">Última atualização</div>
            <div class="info-value">{{ r.latest_display }}</div>
          </div>

          <div class="actions">
            <details class="menu">
              <summary class="btn btn-secondary">Baixar</summary>
              <div class="menu-body">
                <a href="{{ url_for('download_one', report_key=r.report_key) }}?format=excel">Excel</a>
                <a href="{{ url_for('download_one', report_key=r.report_key) }}?format=raw">CSV bruto</a>
                <a href="{{ url_for('download_one', report_key=r.report_key) }}?format=meta">Metadados</a>
              </div>
            </details>
          </div>
        {% else %}
          {% if r.status_display %}
            <div>
              <div class="info-label">Última tentativa</div>
              <div class="info-value">{{ r.status_display }}</div>
            </div>
          {% endif %}
          {% if not r.pending_notice %}
            <div class="empty">Sem arquivo disponível ainda.</div>
          {% endif %}
        {% endif %}
      </div>
      {% endfor %}
    </div>
  </form>
</main>
</body>

</html>
"""

VISIBILITY_TEMPLATE = """
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <title>PROVIDER Reports | Relatórios da tela</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root{--bg:#061124;--card:#0b1830;--line:#23406f;--muted:#9bb2d7;--text:#edf4ff;--primary:#2f6df6;--secondary:#132543;}
    *{box-sizing:border-box} body{font-family:Arial,sans-serif;background:var(--bg);color:var(--text);margin:0}
    header{padding:18px 24px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center}
    main{padding:20px 24px 40px;max-width:1100px;margin:0 auto}.brand{font-size:22px;font-weight:700}.sub,.muted{color:var(--muted)}
    .toolbar{display:flex;gap:12px;flex-wrap:wrap;margin:0 0 16px}.btn,button{border:none;border-radius:10px;padding:10px 14px;font-weight:700;text-decoration:none;color:#fff;cursor:pointer}.btn-primary{background:var(--primary)}.btn-secondary{background:var(--secondary);border:1px solid var(--line)}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:10px}.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px}.card label{display:flex;gap:10px;align-items:flex-start}.obs{font-size:12px;color:var(--muted);margin-top:4px;line-height:1.35}
  </style>
  <script>
    function setAll(v){document.querySelectorAll('input[name="visible_reports"]').forEach(c=>c.checked=v)}
  </script>
</head>
<body>
<header><div><div class="brand">Relatórios visíveis na tela</div><div class="sub">Usuário: {{ full_name }}</div></div><a class="btn btn-secondary" href="{{ url_for('dashboard') }}">Voltar</a></header>
<main>
  <p class="muted">Marque apenas os relatórios que devem aparecer na tela principal. Os demais continuam disponíveis no backend e podem voltar a ser exibidos quando você marcar novamente.</p>
  <form method="post">
    <div class="toolbar">
      <button type="button" class="btn btn-secondary" onclick="setAll(true)">Marcar todos</button>
      <button type="button" class="btn btn-secondary" onclick="setAll(false)">Desmarcar todos</button>
      <button class="btn btn-primary" type="submit">Salvar tela principal</button>
    </div>
    <div class="grid">
      {% for r in reports %}
      <div class="card">
        <label>
          <input type="checkbox" name="visible_reports" value="{{ r.report_key }}" {% if r.visible %}checked{% endif %}>
          <span><strong>{{ r.display_name }}</strong><div class="obs">{{ r.observation }}</div></span>
        </label>
      </div>
      {% endfor %}
    </div>
  </form>
</main>
</body>
</html>
"""


def new_uuid() -> str:
    return str(uuid.uuid4())


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_text(resp: requests.Response, limit: int = 1200) -> str:
    try:
        return (resp.text or "")[:limit]
    except Exception:
        return "<non-text body>"


def basic_auth_header(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("utf-8")


def user_display() -> str:
    return session.get("username", "")


def user_full_name() -> str:
    return session.get("full_name") or session.get("username", "")


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("username"):
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper


_gcs_client = None

def gcs_client():
    global _gcs_client
    if _gcs_client is None:
        _gcs_client = storage.Client()
    return _gcs_client


def gcs_download_text(blob_path: str) -> str:
    bucket = gcs_client().bucket(GCS_BUCKET)
    blob = bucket.blob(blob_path)
    if not blob.exists():
        raise FileNotFoundError(f"Blob não encontrado: gs://{GCS_BUCKET}/{blob_path}")
    return blob.download_as_text(encoding="utf-8")


def gcs_download_bytes(blob_path: str) -> bytes:
    bucket = gcs_client().bucket(GCS_BUCKET)
    blob = bucket.blob(blob_path)
    if not blob.exists():
        raise FileNotFoundError(f"Blob não encontrado: gs://{GCS_BUCKET}/{blob_path}")
    return blob.download_as_bytes()


def upload_to_gcs(
    data: bytes,
    blob_path: str,
    content_type: str,
    *,
    critical: bool = True,
    attempts: Optional[int] = None,
) -> Optional[str]:
    if not GCS_BUCKET:
        raise RuntimeError("GCS_BUCKET não configurado.")

    attempts = attempts or GCS_UPLOAD_MAX_ATTEMPTS
    size = len(data)
    last_exc = None

    for attempt in range(1, attempts + 1):
        try:
            client = gcs_client()
            bucket = client.bucket(GCS_BUCKET)
            blob = bucket.blob(blob_path)

            if size >= 5 * 1024 * 1024:
                blob.chunk_size = GCS_UPLOAD_CHUNK_MB * 1024 * 1024

            blob.upload_from_string(
                data,
                content_type=content_type,
                timeout=GCS_UPLOAD_TIMEOUT_S,
            )

            uri = f"gs://{GCS_BUCKET}/{blob_path}"
            logger.info("GCS upload ok: %s (%d bytes, tentativa=%d)", uri, size, attempt)
            return uri

        except Exception as exc:
            last_exc = exc
            if attempt >= attempts:
                msg = f"Falha no upload GCS após {attempts} tentativas: gs://{GCS_BUCKET}/{blob_path} | erro={exc}"
                if critical:
                    logger.error(msg)
                    raise RuntimeError(msg) from exc
                logger.warning(msg)
                return None

            sleep_s = min(
                GCS_UPLOAD_BACKOFF_BASE_S * (2 ** (attempt - 1)) + random.uniform(0, 1.2),
                GCS_UPLOAD_BACKOFF_MAX_S,
            )
            logger.warning(
                "Falha no upload GCS (%d/%d): gs://%s/%s | erro=%s | retry em %.1fs",
                attempt,
                attempts,
                GCS_BUCKET,
                blob_path,
                exc,
                sleep_s,
            )
            time.sleep(sleep_s)

    if critical and last_exc:
        raise RuntimeError(f"Falha no upload GCS: {last_exc}") from last_exc
    return None


def save_local(relative_path: str, data: bytes) -> Path:
    path = SAVE_DIR / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    logger.info("Arquivo salvo localmente: %s (%d bytes sha256=%s)", path, len(data), sha256_bytes(data))
    return path


def delete_gcs_blob(blob_path: str) -> None:
    if not GCS_BUCKET:
        return
    try:
        bucket = gcs_client().bucket(GCS_BUCKET)
        blob = bucket.blob(blob_path)
        if blob.exists():
            blob.delete()
    except Exception as exc:
        logger.warning("Falha ao remover blob '%s': %s", blob_path, exc)


def remove_local(relative_path: str) -> None:
    try:
        path = SAVE_DIR / relative_path
        if path.exists():
            path.unlink()
    except Exception as exc:
        logger.warning("Falha ao remover arquivo local '%s': %s", relative_path, exc)


def require_webhook_key() -> None:
    expected = (WEBHOOK_API_KEY_VALUE or "").strip()
    if not expected:
        return

    candidate_names = []
    if WEBHOOK_API_KEY_NAME:
        candidate_names.append(WEBHOOK_API_KEY_NAME)

    candidate_names.extend([
        "x-webhook-key",
        "x-api-key",
        "apikey",
        "api_key",
        "authorization",
        "x-authorization",
    ])

    checked_names = []

    def matches(raw: str) -> bool:
        if raw is None:
            return False
        raw = str(raw).strip()
        if not raw:
            return False
        if raw == expected:
            return True
        parts = raw.split()
        if len(parts) >= 2 and parts[-1] == expected:
            return True
        return False

    for name in dict.fromkeys([n for n in candidate_names if n]):
        value = request.headers.get(name)
        if value is not None:
            checked_names.append(name)
            if matches(value):
                logger.info("[WEBHOOK AUTH] Header aceito: %s", name)
                return

    for name, value in request.headers.items():
        checked_names.append(name)
        if matches(value):
            logger.info("[WEBHOOK AUTH] Header aceito: %s", name)
            return

    logger.warning("[WEBHOOK AUTH] Chave inválida. Headers recebidos=%s", sorted(set(checked_names)))
    abort(401, description="Webhook API key inválida.")


def require_manage_key() -> None:
    if MANAGE_API_KEY:
        actual = request.headers.get("x-manage-key")
        if actual != MANAGE_API_KEY:
            abort(401, description="Manage API key inválida.")


def mirror_webhook_to_sql_api(report_key: str, raw: bytes, content_type: str) -> dict:
    """
    Envia uma cópia do webhook recebido pelo Portal para a API SQL.

    A ideia é manter uma única URL cadastrada no PROVIDER: a URL antiga do Portal.
    O Portal continua salvando/servindo os arquivos normalmente e, em paralelo,
    espelha o mesmo payload para a API de ingestão SQL.

    A falha no espelhamento nunca derruba o webhook principal do Portal.
    """
    if not SQL_MIRROR_WEBHOOK_BASE:
        return {"enabled": False, "skipped": True, "reason": "SQL_MIRROR_WEBHOOK_BASE não configurado"}

    if request.headers.get("x-sql-mirror-source"):
        return {"enabled": True, "skipped": True, "reason": "payload já é espelhado"}

    if not raw:
        return {"enabled": True, "skipped": True, "reason": "payload vazio"}

    url = f"{SQL_MIRROR_WEBHOOK_BASE}/webhook/provider/{report_key}"
    headers = {
        "Content-Type": content_type or "application/octet-stream",
        "x-sql-mirror-source": "portal-report-ingestion",
    }

    if SQL_MIRROR_API_KEY_NAME and SQL_MIRROR_API_KEY_VALUE:
        headers[SQL_MIRROR_API_KEY_NAME] = SQL_MIRROR_API_KEY_VALUE

    try:
        response = requests.post(url, data=raw, headers=headers, timeout=SQL_MIRROR_TIMEOUT_S)
        body_preview = safe_text(response, 800)
        result = {
            "enabled": True,
            "skipped": False,
            "url": url,
            "status": response.status_code,
            "ok": response.status_code < 400,
            "body_preview": body_preview,
        }

        if response.status_code >= 400:
            logger.warning(
                "[SQL MIRROR %s] Falha HTTP status=%s body~=%s",
                report_key,
                response.status_code,
                body_preview,
            )
        else:
            logger.info(
                "[SQL MIRROR %s] OK status=%s body~=%s",
                report_key,
                response.status_code,
                body_preview[:300],
            )
        return result

    except Exception as exc:
        logger.warning("[SQL MIRROR %s] Falha ao espelhar webhook: %s", report_key, exc)
        return {
            "enabled": True,
            "skipped": False,
            "url": url,
            "ok": False,
            "error": str(exc),
        }


def load_users() -> Dict[str, dict]:
    raw = None
    if USERS_JSON:
        raw = USERS_JSON
    elif USERS_GCS_BLOB and GCS_BUCKET:
        raw = gcs_download_text(USERS_GCS_BLOB)
    else:
        p = Path(USERS_FILE)
        if p.exists():
            raw = p.read_text(encoding="utf-8")
    if not raw:
        return {}
    payload = json.loads(raw)
    users = {}
    for item in payload:
        username = str(item.get("username", "")).strip().lower()
        if username:
            users[username] = item
    return users


def load_reports_config() -> Dict[str, dict]:
    """
    Lê reports.txt.

    Formato novo:
    report_key|endpoint|display_name|observation|method|body_json

    Compatível com formato antigo:
    report_key|endpoint|display_name|observation
    """
    text = None
    if REPORTS_CONFIG_GCS_BLOB and GCS_BUCKET:
        text = gcs_download_text(REPORTS_CONFIG_GCS_BLOB)
    else:
        p = Path(REPORTS_CONFIG_FILE)
        if p.exists():
            text = p.read_text(encoding="utf-8")

    reports: Dict[str, dict] = {}
    if not text:
        return reports

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        lower = line.lower()
        if lower.startswith("report_key|endpoint|display_name"):
            continue

        parts = [x.strip() for x in line.split("|")]
        if len(parts) < 3:
            continue

        while len(parts) < 6:
            parts.append("")

        report_key, endpoint, display_name, observation, method, body_template = parts[:6]

        # Corrige typo recorrente sem quebrar histórico.
        if report_key == "managed-reports-montly-tir":
            report_key = "managed-reports-monthly-tir"

        reports[report_key] = {
            "report_key": report_key,
            "endpoint": endpoint,
            "display_name": display_name,
            "observation": observation,
            "method": (method or "GET").upper(),
            "body_template": body_template or "",
        }

    return reports


def load_column_mapping() -> Dict[str, str]:
    try:
        if COLUMN_MAPPING_GCS_BLOB and GCS_BUCKET:
            return load_json_mapping_from_text(gcs_download_text(COLUMN_MAPPING_GCS_BLOB))
    except Exception as exc:
        logger.warning("Falha ao carregar mapa de colunas no GCS; usando arquivo local. %s", exc)
    try:
        return load_json_mapping(COLUMN_MAPPING_FILE)
    except Exception as exc:
        logger.warning("Falha ao carregar mapa de colunas local '%s': %s", COLUMN_MAPPING_FILE, exc)
        return {}


def load_json_mapping_from_text(text: str) -> Dict[str, str]:
    from report_column_normalizer import normalize_mapping
    payload = json.loads(text or "{}")
    return normalize_mapping(payload if isinstance(payload, dict) else {})


def load_visibility_config() -> Dict[str, list]:
    try:
        raw = None
        if VISIBLE_REPORTS_GCS_BLOB and GCS_BUCKET:
            try:
                raw = gcs_download_text(VISIBLE_REPORTS_GCS_BLOB)
            except FileNotFoundError:
                return {}
        else:
            p = SAVE_DIR / "config" / "visible_reports.json"
            if p.exists():
                raw = p.read_text(encoding="utf-8")
        if not raw:
            return {}
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {}
    except Exception as exc:
        logger.warning("Falha ao ler configuração de relatórios visíveis: %s", exc)
        return {}


def save_visibility_config(payload: Dict[str, list]) -> None:
    data = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if VISIBLE_REPORTS_GCS_BLOB and GCS_BUCKET:
        upload_to_gcs(data, VISIBLE_REPORTS_GCS_BLOB, "application/json", critical=True)
    else:
        save_local("config/visible_reports.json", data)


def current_visible_keys(config: Optional[Dict[str, dict]] = None) -> Optional[set]:
    visibility = load_visibility_config()
    username = user_display() or "default"
    keys = visibility.get(username)
    if keys is None:
        keys = visibility.get("default")
    if keys is None:
        return None  # Sem preferência salva: mostra tudo para não esconder relatório sem querer.
    valid = set((config or load_reports_config()).keys())
    return {k for k in keys if k in valid}


def display_name_for_report(report_key: str) -> str:
    meta = load_reports_config().get(report_key, {})
    return meta.get("display_name") or report_key.replace("managed-reports-", "").replace("-", " ").title()

def latest_meta_from_storage(report_key: str) -> Optional[dict]:
    try:
        if GCS_BUCKET:
            data = gcs_download_bytes(f"{GCS_PREFIX}/{report_key}/latest/_latest.json")
            return json.loads(data.decode("utf-8"))
        local_path = SAVE_DIR / report_key / "latest" / "_latest.json"
        if local_path.exists():
            return json.loads(local_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Falha ao ler latest meta de '%s': %s", report_key, exc)
    return None


def latest_status_from_storage(report_key: str) -> Optional[dict]:
    try:
        if GCS_BUCKET:
            data = gcs_download_bytes(f"{GCS_PREFIX}/{report_key}/latest/_status.json")
            return json.loads(data.decode("utf-8"))
        local_path = SAVE_DIR / report_key / "latest" / "_status.json"
        if local_path.exists():
            return json.loads(local_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return None


def format_dt_brasilia(value: Optional[str]) -> str:
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        dt = dt.astimezone(BRT)
        return dt.strftime("%d/%m/%Y - %H:%M:%S")
    except Exception:
        return str(value)


def parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        return None


def status_message_from_payload(metadata: dict) -> Optional[str]:
    errors = metadata.get("errors") if isinstance(metadata, dict) else None
    if isinstance(errors, list) and errors:
        first = errors[0] or {}
        msg = (first.get("message") or "").strip()
        if msg:
            return msg
    return None


def is_awaiting_next_window(metadata: dict) -> bool:
    msg = (status_message_from_payload(metadata) or "").lower()
    if "próxima janela" in msg or "proxima janela" in msg:
        return True
    response = metadata.get("response") if isinstance(metadata, dict) else None
    if isinstance(response, dict):
        url = response.get("url") or response.get("fileUrl")
        errors = metadata.get("errors") or []
        if not url and errors:
            first = errors[0] or {}
            if str(first.get("code")) == "404":
                return True
    return False


def save_status_snapshot(report_key: str, metadata: dict, meta_bytes: bytes, meta_name: str, local_meta: Path) -> dict:
    now_iso = datetime.now(UTC).isoformat()
    message = status_message_from_payload(metadata) or "Aguardando próxima janela do PROVIDER."
    status_payload = {
        "report_key": report_key,
        "state": "awaiting_window",
        "message": message,
        "updated_at": now_iso,
        "local": {"meta": str(local_meta)},
        "gcs": None,
    }

    status_bytes = (json.dumps(status_payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    local_status = save_local(f"{report_key}/latest/_status.json", status_bytes)
    status_payload["local"]["status"] = str(local_status)

    if GCS_BUCKET:
        meta_uri = upload_to_gcs(meta_bytes, f"{GCS_PREFIX}/{report_key}/meta/{meta_name}", "application/json", critical=True)
        status_uri = upload_to_gcs(status_bytes, f"{GCS_PREFIX}/{report_key}/latest/_status.json", "application/json", critical=True)
        status_payload["gcs"] = {"meta": meta_uri, "status": status_uri}
        status_bytes = (json.dumps(status_payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        local_status.write_bytes(status_bytes)
        upload_to_gcs(status_bytes, f"{GCS_PREFIX}/{report_key}/latest/_status.json", "application/json", critical=True)

    return status_payload


def clear_status_snapshot(report_key: str) -> None:
    remove_local(f"{report_key}/latest/_status.json")
    delete_gcs_blob(f"{GCS_PREFIX}/{report_key}/latest/_status.json")



def maybe_extract_csv_from_zip_bytes(data: bytes, file_name: str = None):
    """
    Alguns relatórios do PROVIDER chegam como ZIP contendo CSV, mesmo quando o fluxo
    final deveria ser tabular. Antes de normalizar/salvar como CSV, extraímos
    o primeiro .csv/.txt interno.
    """
    import io, zipfile

    if not data:
        return data, file_name

    raw = data
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]

    if not raw.startswith(b"PK"):
        return data, file_name

    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names = [n for n in z.namelist() if not n.endswith("/")]
            preferred = [
                n for n in names
                if n.lower().endswith((".csv", ".txt"))
            ]
            target = preferred[0] if preferred else (names[0] if names else None)

            if not target:
                return data, file_name

            extracted = z.read(target)
            logger.info("ZIP detectado. Extraído arquivo interno: %s (%d bytes)", target, len(extracted))
            return extracted, target
    except Exception as exc:
        logger.warning("Falha ao extrair ZIP; mantendo bytes originais. erro=%s", exc)
        return data, file_name

def decode_text(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    raise UnicodeError("Falha ao decodificar CSV.")


def csv_to_xml_bytes(csv_bytes: bytes) -> bytes:
    text = decode_text(csv_bytes)
    reader = csv.DictReader(io.StringIO(text, newline=''))
    headers = reader.fieldnames or []

    def esc(value: str) -> str:
        return (value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace('"', "&quot;").replace("'", "&apos;"))

    lines = ['<?xml version="1.0" encoding="UTF-8"?>', f'<report generated_at="{datetime.now(UTC).isoformat()}">']
    for row in reader:
        lines.append("  <row>")
        for header in headers:
            value = "" if row.get(header) is None else str(row.get(header))
            lines.append(f'    <col name="{esc(header)}">{esc(value)}</col>')
        lines.append("  </row>")
    lines.append("</report>")
    return "\n".join(lines).encode("utf-8")


def _looks_money_col(column_name: str) -> bool:
    c = (column_name or "").strip().lower()
    return c in MONETARY_COLUMNS or bool(MONEY_HINT.search(c))


def _parse_number_any(value: str) -> Optional[Decimal]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if "," in text and "." in text:
        normalized = text.replace(".", "").replace(",", ".")
    elif "," in text:
        normalized = text.replace(".", "").replace(",", ".")
    else:
        normalized = text
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def normalize_csv_br(csv_bytes: bytes) -> bytes:
    text = decode_text(csv_bytes)
    reader = csv.DictReader(io.StringIO(text, newline=''))
    headers = reader.fieldnames or []
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=headers)
    writer.writeheader()

    for row in reader:
        new_row = {}
        for header in headers:
            value = row.get(header)
            if value is None:
                new_row[header] = ""
                continue
            if _looks_money_col(header):
                number = _parse_number_any(value)
                if number is not None:
                    quantized = number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    formatted = f"{quantized:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    new_row[header] = formatted
                else:
                    new_row[header] = value
            else:
                new_row[header] = value
        writer.writerow(new_row)

    return output.getvalue().encode("utf-8-sig")


def pick_base_name(file_name: Optional[str], last_modified: Optional[str], fallback: str) -> str:
    if file_name:
        return Path(file_name).stem
    if last_modified:
        try:
            dt = datetime.fromisoformat(last_modified.replace("Z", "+00:00"))
            return f"{fallback}_{dt.strftime('%Y%m%d')}"
        except Exception:
            pass
    return fallback


def http_get_with_retry(url: str, headers: Optional[dict] = None, max_attempts: int = 5) -> bytes:
    attempt = 0
    while True:
        attempt += 1
        try:
            response = requests.get(url, headers=headers or {}, timeout=DOWNLOAD_TIMEOUT_S)
            if response.status_code in (500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {response.status_code} servidor")
            response.raise_for_status()
            return response.content or b""
        except Exception as exc:
            if attempt >= max_attempts:
                logger.error("Falha no download após %d tentativas: %s", attempt, exc)
                raise
            backoff = min(BACKOFF_BASE_S * (2 ** (attempt - 1)) + random.uniform(0, 1.3), BACKOFF_MAX_S)
            logger.warning("Erro no download (tentativa %d/%d). Retry em %.1fs. %s", attempt, max_attempts, backoff, exc)
            time.sleep(backoff)


class TokenCache:
    def __init__(self):
        self.value: Optional[str] = None
        self.expiry: datetime = datetime.now(UTC) - timedelta(seconds=1)

    def get(self) -> str:
        if not self.value or datetime.now(UTC) >= self.expiry:
            self.refresh()
        return self.value

    def refresh(self) -> None:
        missing = [name for name, value in {
            "PROVIDER_CLIENT_ID": CLIENT_ID,
            "PROVIDER_CLIENT_SECRET": CLIENT_SECRET,
            "PROVIDER_TOKEN_URL": TOKEN_URL,
        }.items() if not value]
        if missing:
            raise RuntimeError(f"Variáveis obrigatórias ausentes: {', '.join(missing)}")

        headers = {
            "Authorization": basic_auth_header(CLIENT_ID, CLIENT_SECRET),
            "x-id-partner-request": new_uuid(),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "*/*",
        }
        response = requests.post(TOKEN_URL, headers=headers, data={"grant_type": "client_credentials"}, timeout=HTTP_TIMEOUT_S)
        response.raise_for_status()

        token = None
        for header_name in ("access_token", "Access-Token", "ACCESS_TOKEN", "X-Access-Token"):
            token = response.headers.get(header_name)
            if token:
                break

        if not token:
            raise RuntimeError("Token endpoint não retornou access_token no header.")

        self.value = token
        self.expiry = datetime.now(UTC) + timedelta(minutes=14, seconds=30)
        logger.info("Access token obtido; válido até %s", self.expiry.isoformat())


TOKEN = TokenCache()


def render_trigger_template(template: str) -> str:
    """
    Substitui placeholders simples em body_json do reports.txt.

    Placeholders disponíveis:
    {today}, {yesterday}, {d_minus_1}, {d_minus_2}, {d_minus_3}
    {current_month}, {current_year}, {prev_month}, {prev_year}
    """
    today = datetime.now(BRT).date()
    first_this_month = today.replace(day=1)
    prev_month_date = first_this_month - timedelta(days=1)

    values = {
        "today": today.strftime("%Y-%m-%d"),
        "yesterday": (today - timedelta(days=1)).strftime("%Y-%m-%d"),
        "d_minus_1": (today - timedelta(days=1)).strftime("%Y-%m-%d"),
        "d_minus_2": (today - timedelta(days=2)).strftime("%Y-%m-%d"),
        "d_minus_3": (today - timedelta(days=3)).strftime("%Y-%m-%d"),
        "current_month": today.strftime("%m"),
        "current_year": today.strftime("%Y"),
        "prev_month": prev_month_date.strftime("%m"),
        "prev_year": prev_month_date.strftime("%Y"),
    }

    out = template or ""
    for key, value in values.items():
        out = out.replace("{" + key + "}", value)

    return out


def build_trigger_body(report_key: str, meta: dict) -> Optional[dict]:
    body_template = (meta.get("body_template") or "").strip()
    if not body_template:
        return None

    rendered = render_trigger_template(body_template)

    try:
        return json.loads(rendered)
    except Exception as exc:
        raise RuntimeError(
            f"Body JSON inválido para relatório '{report_key}'. "
            f"Template={body_template!r} Rendered={rendered!r} Erro={exc}"
        )


def trigger_one(report_key: str) -> Tuple[str, int, str]:
    reports = load_reports_config()
    if report_key not in reports:
        raise RuntimeError(f"Relatório '{report_key}' não encontrado no arquivo de configuração.")

    meta = reports[report_key]
    report_url = meta["endpoint"]
    method = (meta.get("method") or "GET").upper()
    body = build_trigger_body(report_key, meta)

    def do_request():
        headers = {
            "accept": "*/*",
            "x-id-partner-request": new_uuid(),
            "access_token": TOKEN.get(),
        }

        if method == "GET":
            logger.info("Disparando %r via GET URL=%s", report_key, report_url)
            return requests.get(report_url, headers=headers, timeout=HTTP_TIMEOUT_S)

        if method == "POST":
            headers["Content-Type"] = "application/json"
            logger.info("Disparando %r via POST URL=%s body=%s", report_key, report_url, body or {})
            return requests.post(report_url, headers=headers, json=body or {}, timeout=HTTP_TIMEOUT_S)

        raise RuntimeError(f"Método HTTP não suportado para '{report_key}': {method}")

    response = do_request()

    if response.status_code == 401:
        TOKEN.refresh()
        response = do_request()

    status = response.status_code
    body_text = safe_text(response, 1200)

    if 200 <= status < 300:
        logger.info("Disparo aceito — '%s' status=%s body~=%s", report_key, status, body_text)
    elif status == 429:
        logger.error("Rate limit ao disparar '%s'. status=%s body~=%s", report_key, status, body_text)
    elif status >= 400:
        logger.error("Falha ao disparar '%s'. status=%s body~=%s", report_key, status, body_text)

    return report_key, status, body_text

def startup_trigger():
    if not TRIGGER_ON_START:
        return
    for report_key in load_reports_config().keys():
        try:
            trigger_one(report_key)
        except Exception as exc:
            logger.error("Falha no startup trigger de '%s': %s", report_key, exc)


def build_dashboard_reports(sort_mode: str, visible_only: bool = False) -> List[dict]:
    items = []
    config = load_reports_config()
    visible_keys = current_visible_keys(config) if visible_only else None

    for report_key, meta in config.items():
        if visible_keys is not None and report_key not in visible_keys:
            continue
        latest = latest_meta_from_storage(report_key)
        status = latest_status_from_storage(report_key)

        latest_updated = parse_dt((latest or {}).get("updated_at"))
        status_updated = parse_dt((status or {}).get("updated_at"))

        pending_notice = False
        pending_message = None
        if status and status.get("state") == "awaiting_window":
            if latest_updated is None or (status_updated and status_updated >= latest_updated):
                pending_notice = True
                pending_message = status.get("message") or "Aguardando próxima janela do PROVIDER."

        items.append({
            **meta,
            "latest": latest,
            "status": status,
            "latest_display": format_dt_brasilia((latest or {}).get("updated_at")) if latest else None,
            "status_display": format_dt_brasilia((status or {}).get("updated_at")) if status else None,
            "pending_notice": pending_notice,
            "pending_message": pending_message,
            "_sort_dt": latest_updated or status_updated or datetime(1970, 1, 1, tzinfo=UTC),
        })

    reverse = sort_mode != "recent_asc"
    items.sort(key=lambda x: x["_sort_dt"], reverse=reverse)
    return items


def download_bytes_for_format(report_key: str, fmt: str) -> Tuple[bytes, str, str]:
    fmt = (fmt or "excel").lower()
    latest = latest_meta_from_storage(report_key)
    if not latest:
        raise FileNotFoundError(f"Nenhum latest disponível para '{report_key}'.")

    if fmt == "excel":
        if GCS_BUCKET:
            data = gcs_download_bytes(f"{GCS_PREFIX}/{report_key}/latest/latest_br.csv")
        else:
            data = Path(latest["local"]["csv_br"]).read_bytes()
        filename = latest.get("friendly_latest_name") or friendly_report_filename(display_name_for_report(report_key), include_time=False)
        return data, "text/csv; charset=utf-8", filename

    if fmt == "raw":
        if GCS_BUCKET:
            data = gcs_download_bytes(f"{GCS_PREFIX}/{report_key}/latest/latest_raw.csv")
        else:
            data = Path(latest["local"]["csv"]).read_bytes()
        return data, "text/csv; charset=utf-8", f"{safe_blob_component(display_name_for_report(report_key))} - bruto.csv"

    if fmt == "meta":
        data = (json.dumps(latest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        return data, "application/json", f"{safe_blob_component(display_name_for_report(report_key))} - metadados.json"

    raise ValueError("Formato de download inválido.")


@app.get("/")
def root():
    return redirect(url_for("dashboard"))


@app.get("/healthz")
def healthz():
    return "ok", 200


@app.get("/favicon.ico")
def favicon():
    return "", 204


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        users = load_users()
        username = (request.form.get("username") or "").strip().lower()
        password = request.form.get("password") or ""
        user = users.get(username)

        if not user or not check_password_hash(user.get("password_hash", ""), password):
            flash("Usuário ou senha inválidos.")
            return render_template_string(LOGIN_TEMPLATE), 401

        session.permanent = True
        session["username"] = username
        session["full_name"] = user.get("full_name") or username
        logger.info("Login portal: %s", username)
        return redirect(request.args.get("next") or url_for("dashboard"))

    return render_template_string(LOGIN_TEMPLATE)


@app.get("/logout")
def logout():
    username = user_display()
    session.clear()
    if username:
        logger.info("Logout portal: %s", username)
    return redirect(url_for("login"))


@app.get("/app")
@login_required
def dashboard():
    sort_mode = (request.args.get("sort") or "recent_desc").strip().lower()
    if sort_mode not in {"recent_desc", "recent_asc"}:
        sort_mode = "recent_desc"

    all_config = load_reports_config()
    visible_keys = current_visible_keys(all_config)
    items = build_dashboard_reports(sort_mode, visible_only=True)
    hidden_count = 0 if visible_keys is None else max(len(all_config) - len(visible_keys), 0)
    warning = None if items else "Nenhum relatório visível. Clique em 'Relatórios da tela' e marque os relatórios desejados."

    return render_template_string(
        DASHBOARD_TEMPLATE,
        reports=items,
        full_name=user_full_name(),
        warning=warning,
        sort_mode=sort_mode,
        hidden_count=hidden_count,
    )


@app.route("/app/visibility", methods=["GET", "POST"])
@login_required
def visibility_settings():
    config = load_reports_config()
    username = user_display() or "default"
    if request.method == "POST":
        selected = request.form.getlist("visible_reports")
        payload = load_visibility_config()
        payload[username] = [k for k in selected if k in config]
        save_visibility_config(payload)
        flash("Tela principal atualizada com sucesso.")
        return redirect(url_for("dashboard"))

    visible = current_visible_keys(config)
    reports = []
    for key, meta in config.items():
        reports.append({**meta, "visible": True if visible is None else key in visible})
    return render_template_string(VISIBILITY_TEMPLATE, reports=reports, full_name=user_full_name())


@app.post("/app/trigger")
@login_required
def ui_trigger_selected():
    selected = request.form.getlist("reports")
    if not selected:
        flash("Selecione ao menos um relatório.")
        return redirect(url_for("dashboard"))

    accepted, failed = [], []
    for report_key in selected:
        try:
            _, status, _ = trigger_one(report_key)
            if 200 <= int(status) < 300:
                accepted.append(report_key)
            else:
                failed.append(report_key)
        except Exception as exc:
            logger.error("Falha no trigger do relatório '%s': %s", report_key, exc)
            failed.append(report_key)

    logger.info("Portal trigger por '%s' | ok=%s | fail=%s", user_display(), accepted, failed)

    if accepted:
        flash("Disparo solicitado para: " + ", ".join(accepted))
    if failed:
        flash("Falha em: " + ", ".join(failed))

    return redirect(url_for("dashboard", sort=request.args.get("sort") or "recent_desc"))


@app.post("/app/download-selected")
@login_required
def download_selected():
    selected = request.form.getlist("reports")
    fmt = (request.form.get("download_format") or "excel").strip().lower()

    if not selected:
        flash("Selecione ao menos um relatório para baixar.")
        return redirect(url_for("dashboard", sort=request.args.get("sort") or "recent_desc"))

    zip_buffer = io.BytesIO()
    included, skipped = [], []

    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for report_key in selected:
            try:
                data, _, filename = download_bytes_for_format(report_key, fmt)
                zf.writestr(filename, data)
                included.append(report_key)
            except Exception:
                skipped.append(report_key)

        if skipped:
            zf.writestr(
                "LEIA_ME.txt",
                "Os relatórios abaixo não tinham arquivo latest disponível:\n\n" + "\n".join(skipped) + "\n",
            )

    if not included:
        flash("Nenhum dos relatórios selecionados possui arquivo disponível para download.")
        return redirect(url_for("dashboard", sort=request.args.get("sort") or "recent_desc"))

    zip_buffer.seek(0)
    timestamp = datetime.now(BRT).strftime("%Y%m%d_%H%M%S")
    return send_file(
        zip_buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"reports_db_{fmt}_{timestamp}.zip",
    )


@app.get("/download/<report_key>")
@login_required
def download_one(report_key: str):
    fmt = (request.args.get("format") or "excel").strip().lower()
    data, mimetype, filename = download_bytes_for_format(report_key, fmt)
    return send_file(io.BytesIO(data), mimetype=mimetype, as_attachment=True, download_name=filename)


@app.get("/admin/trigger/<report_key>")
def admin_trigger_by_path(report_key: str):
    require_manage_key()
    key, status, body = trigger_one(report_key)
    return jsonify({"report": key, "status": status, "body": body}), (200 if status < 500 else 502)


@app.route("/admin/trigger-all", methods=["GET", "POST"])
def admin_trigger_all():
    require_manage_key()
    config = load_reports_config()
    payload = request.get_json(silent=True) or {}
    requested = payload.get("reports") or request.args.get("reports") or TRIGGER_ALL_REPORTS
    if isinstance(requested, str):
        keys = [k.strip() for k in requested.split(",") if k.strip()]
    elif requested:
        keys = [str(k).strip() for k in requested if str(k).strip()]
    else:
        keys = list(config.keys())
    keys = [k for k in keys if k in config]

    results = []
    for i, report_key in enumerate(keys):
        try:
            key, status, body = trigger_one(report_key)
            results.append({"report": key, "status": status, "ok": 200 <= int(status) < 300, "body": body[:500]})
        except Exception as exc:
            logger.error("Falha no trigger-all de '%s': %s", report_key, exc)
            results.append({"report": report_key, "ok": False, "error": str(exc)})
        if TRIGGER_ALL_DELAY_S > 0 and i < len(keys) - 1:
            time.sleep(TRIGGER_ALL_DELAY_S)

    return jsonify({"ok": True, "count": len(results), "results": results})


@app.get("/api/reports")
@login_required
def api_reports():
    payload = build_dashboard_reports("recent_desc")
    return jsonify({"reports": payload})


@app.post("/webhook/<report_key>")
@app.post("/webhook/provider/<report_key>")
def webhook_handler(report_key: str):
    sql_mirror_result = None
    try:
        require_webhook_key()
        content_type = (request.headers.get("Content-Type") or "").lower()
        raw = request.data or b""
        logger.info("[WEBHOOK %s] Recebido. content-type=%s bytes=%d", report_key, content_type, len(raw))


        metadata = {}
        if content_type.startswith("application/json") and raw:
            try:
                metadata = request.get_json(force=True, silent=True) or {}
            except Exception:
                metadata = {}

        meta_bytes = (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8") if metadata else b"{}\n"

        file_bytes = b""
        file_name = None
        last_modified = None
        source_mode = None

        if "text/csv" in content_type or (raw and not content_type.startswith("application/json")):
            file_bytes = raw
            source_mode = "csv-inline"
        else:
            node = metadata.get("response", metadata) if isinstance(metadata, dict) else {}
            signed_url = node.get("url") or node.get("fileUrl")
            file_name = node.get("fileName")
            last_modified = node.get("lastModified")
            source_mode = "json-url"

            if not signed_url:
                logger.warning("[WEBHOOK %s] JSON sem url/fileUrl. Salvando somente metadados.", report_key)
                meta_name = f"{report_key}_{datetime.now(BRT).strftime('%Y%m%d_%H%M%S')}.json"
                local_meta = save_local(f"{report_key}/meta/{meta_name}", meta_bytes)

                if is_awaiting_next_window(metadata):
                    status_payload = save_status_snapshot(report_key, metadata, meta_bytes, meta_name, local_meta)
                    return jsonify({"ack": True, "note": "aguardando próxima janela", "status": status_payload, "sql_mirror": sql_mirror_result}), 200

                if GCS_BUCKET:
                    upload_to_gcs(meta_bytes, f"{GCS_PREFIX}/{report_key}/meta/{meta_name}", "application/json", critical=True)

                return jsonify({"ack": True, "note": "payload sem url", "meta": str(local_meta), "sql_mirror": sql_mirror_result}), 200

            try:
                file_bytes = http_get_with_retry(signed_url)
            except Exception as first_exc:
                logger.warning("[WEBHOOK %s] GET direto falhou. Tentando com access_token. %s", report_key, first_exc)
                file_bytes = http_get_with_retry(
                    signed_url,
                    headers={"accept": "*/*", "x-id-partner-request": new_uuid(), "access_token": TOKEN.get()},
                    max_attempts=3,
                )

        if not file_bytes:
            return jsonify({"ack": True, "warning": "sem conteúdo útil", "sql_mirror": sql_mirror_result}), 200

        clear_status_snapshot(report_key)

        base_name = pick_base_name(file_name, last_modified, report_key)
        timestamp = datetime.now(BRT).strftime("%Y%m%d_%H%M%S")
        final_name = f"{base_name}_{timestamp}"
        day_path = datetime.now(BRT).strftime("%Y/%m/%d")

        try:
            file_bytes, file_name = maybe_extract_csv_from_zip_bytes(file_bytes, locals().get("file_name"))
        except Exception as exc:
            logger.warning("[WEBHOOK %s] Falha não bloqueante ao verificar ZIP: %s", report_key, exc)

        csv_raw = file_bytes

        # Espelha para a API SQL usando o CSV já baixado pelo Portal.
        # Isso evita que a API SQL tenha que baixar novamente a URL assinada do PROVIDER.
        # REMOVIDO: chamada duplicada do SQL Mirror antes do latest
        display_name = display_name_for_report(report_key)
        friendly_history_name = friendly_report_filename(display_name, datetime.now(BRT), ext="csv", include_time=True)
        friendly_latest_name = friendly_report_filename(display_name, datetime.now(BRT), ext="csv", include_time=False)

        csv_br = normalize_csv_for_download(csv_raw, load_column_mapping())
        xml_bytes = csv_to_xml_bytes(csv_raw)

        local_meta = save_local(f"{report_key}/meta/{final_name}.json", meta_bytes)
        local_csv = save_local(f"{report_key}/raw/{final_name}.csv", csv_raw)
        local_csv_br = save_local(f"{report_key}/excel/{friendly_history_name}", csv_br)
        local_xml = save_local(f"{report_key}/xml/{final_name}.xml", xml_bytes)

        latest_index = {
            "report_key": report_key,
            "updated_at": datetime.now(UTC).isoformat(),
            "source_mode": source_mode,
            "display_name": display_name,
            "friendly_history_name": friendly_history_name,
            "friendly_latest_name": friendly_latest_name,
            "local": {
                "meta": str(local_meta),
                "csv": str(local_csv),
                "csv_br": str(local_csv_br),
                "xml": str(local_xml),
            },
            "gcs": None,
        }

        if GCS_BUCKET:
            version_base = f"{GCS_PREFIX}/{report_key}/{day_path}/{final_name}"
            latest_base = f"{GCS_PREFIX}/{report_key}/latest"

            g_meta = upload_to_gcs(meta_bytes, f"{version_base}.json", "application/json", critical=True)
            g_csv = upload_to_gcs(csv_raw, f"{version_base}.csv", "text/csv", critical=True)
            g_csv_br = upload_to_gcs(csv_br, f"{version_base}_br.csv", "text/csv", critical=True)
            g_xml = upload_to_gcs(xml_bytes, f"{version_base}.xml", "application/xml", critical=False)

            latest_meta_uri = upload_to_gcs(meta_bytes, f"{latest_base}/latest_meta.json", "application/json", critical=True)
            latest_csv_uri = upload_to_gcs(csv_raw, f"{latest_base}/latest_raw.csv", "text/csv", critical=True)
            latest_csv_br_uri = upload_to_gcs(csv_br, f"{latest_base}/latest_br.csv", "text/csv", critical=True)
            latest_xml_uri = upload_to_gcs(xml_bytes, f"{latest_base}/latest.xml", "application/xml", critical=False)

            friendly_folder = safe_blob_component(display_name)
            history_uri = upload_to_gcs(
                csv_br,
                f"{GCS_PREFIX}/{HISTORY_GCS_PREFIX}/{friendly_folder}/{friendly_history_name}",
                "text/csv; charset=utf-8",
                critical=True,
            )
            drive_latest_uri = upload_to_gcs(
                csv_br,
                f"{GCS_PREFIX}/{ONEDRIVE_EXPORT_GCS_PREFIX}/{friendly_latest_name}",
                "text/csv; charset=utf-8",
                critical=False,
            )

            latest_index["gcs"] = {
                "versioned": {"meta": g_meta, "csv": g_csv, "csv_br": g_csv_br, "xml": g_xml},
                "latest": {"meta": latest_meta_uri, "csv": latest_csv_uri, "csv_br": latest_csv_br_uri, "xml": latest_xml_uri},
                "friendly_history": history_uri,
                "onedrive_export_latest": drive_latest_uri,
            }

            latest_index_bytes = (json.dumps(latest_index, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            latest_index_uri = upload_to_gcs(latest_index_bytes, f"{latest_base}/_latest.json", "application/json", critical=True)
            latest_index["gcs"]["latest"]["index"] = latest_index_uri

        local_latest_path = save_local(
            f"{report_key}/latest/_latest.json",
            (json.dumps(latest_index, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )

        # SQL Mirror deve rodar SOMENTE depois que o Portal já salvou o latest.
        # Assim, o Portal atualiza primeiro; o SQL pode demorar sem travar a visualização do relatório.
        sql_mirror_result = None
        try:
            sql_mirror_result = None

            try:

                # Loader v3: cria job rápido usando o arquivo salvo no GCS.

                # O processamento pesado roda depois em /jobs/process.

                gcs_uri_for_sql = locals().get("latest_csv_uri")

                if SQL_MIRROR_WEBHOOK_BASE and gcs_uri_for_sql:

                    job_url = SQL_MIRROR_WEBHOOK_BASE.rstrip("/") + "/jobs/create"

                    resp = requests.post(

                        job_url,

                        json={"report_key": report_key, "gcs_uri": gcs_uri_for_sql},

                        timeout=15,

                    )

                    sql_mirror_result = {"status": resp.status_code, "body": resp.text[:500]}

                    logger.info("[SQL JOB %s] create status=%s body~=%s", report_key, resp.status_code, resp.text[:300])

            except Exception as exc:

                logger.warning("[SQL JOB %s] Falha não bloqueante ao criar job: %s", report_key, exc)
        except Exception as exc:
            logger.warning("[SQL MIRROR %s] Falha não bloqueante após latest do Portal: %s", report_key, exc)

        logger.info("[WEBHOOK %s] OK csv=%s csv_br=%s xml=%s", report_key, local_csv, local_csv_br, local_xml)
        return jsonify({"ack": True, "latest_index": str(local_latest_path), "local": latest_index["local"], "gcs": latest_index["gcs"], "sql_mirror": sql_mirror_result}), 200

    except Exception as exc:
        logger.error("[WEBHOOK %s] exceção: %s\n%s", report_key, exc, traceback.format_exc())
        return jsonify({"ack": True, "error": str(exc)}), 200


@app.get("/files/<report_key>/latest/meta")
@login_required
def latest_meta(report_key: str):
    meta = latest_meta_from_storage(report_key)
    if not meta:
        abort(404, description="Nenhum arquivo latest encontrado.")
    return jsonify(meta)


@app.get("/files/<report_key>/latest")
@login_required
def download_latest_csv_br(report_key: str):
    data, mimetype, filename = download_bytes_for_format(report_key, "excel")
    return send_file(io.BytesIO(data), mimetype=mimetype, as_attachment=True, download_name=filename)


@app.get("/files/<report_key>/latest/raw")
@login_required
def download_latest_csv_raw(report_key: str):
    data, mimetype, filename = download_bytes_for_format(report_key, "raw")
    return send_file(io.BytesIO(data), mimetype=mimetype, as_attachment=True, download_name=filename)


@app.after_request
def add_headers(resp):
    resp.headers["Cache-Control"] = "no-store"
    return resp


if __name__ == "__main__":
    logger.info("Iniciando serviço. Bucket=%s Prefix=%s SAVE_DIR=%s", GCS_BUCKET, GCS_PREFIX, SAVE_DIR)
    startup_trigger()
    app.run(host="0.0.0.0", port=PORT)

"""PROVIDER Managed Reports service v2.

Fluxo:
1. Solicita relatórios PROVIDER (GET/POST, síncronos ou assíncronos) usando catálogo configurável.
2. Recebe webhooks do PROVIDER com CSV direto, JSON direto, ZIP/PDF ou URL assinada.
3. Salva o arquivo bruto no GCS.
4. Grava landing/raw no Cloud SQL/PostgreSQL.
5. Cria/atualiza tabelas largas em report_bi.<report_key> para uso em Power BI/Power Query.

Variáveis obrigatórias em produção:
- PROVIDER_CLIENT_ID
- PROVIDER_CLIENT_SECRET
- GCS_BUCKET
- DB_NAME, DB_USER, DB_PASS e INSTANCE_CONNECTION_NAME (Cloud SQL Connector)
  OU DATABASE_URL para conexão PostgreSQL tradicional.

Nunca coloque client_id/client_secret fixos no código.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import random
import re
import time
import traceback
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import requests
from dateutil import parser as dtparser
from flask import Flask, jsonify, request

UTC = timezone.utc

# ===================== CONFIG =====================
PROVIDER_CLIENT_ID = (os.getenv("PROVIDER_CLIENT_ID") or "").strip()
PROVIDER_CLIENT_SECRET = (os.getenv("PROVIDER_CLIENT_SECRET") or "").strip()
PROVIDER_TOKEN_URL = (
    os.getenv("PROVIDER_TOKEN_URL")
    or "https://api.example-provider.com/iaas-auth/api/v1/authorization/oauth2/accesstoken"
).strip()

GCS_BUCKET = (os.getenv("GCS_BUCKET") or "").strip()
GCS_PREFIX = (os.getenv("GCS_PREFIX") or "report-ingestion").strip().strip("/")
SAVE_DIR = Path(os.getenv("SAVE_DIR", "/tmp"))
SAVE_DIR.mkdir(parents=True, exist_ok=True)

CATALOG_FILE = Path(os.getenv("PROVIDER_API_CATALOG_FILE", "report_api_catalog.json"))
HTTP_TIMEOUT_S = int(os.getenv("HTTP_TIMEOUT_S", "60"))
BACKOFF_BASE_S = float(os.getenv("BACKOFF_BASE_S", "3"))
BACKOFF_MAX_S = float(os.getenv("BACKOFF_MAX_S", "45"))
AUTO_INIT_DB = (os.getenv("AUTO_INIT_DB", "true").lower() in {"1", "true", "yes", "sim"})
STRICT_DB = (os.getenv("STRICT_DB", "false").lower() in {"1", "true", "yes", "sim"})

# Cloud SQL/Postgres
DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip()
INSTANCE_CONNECTION_NAME = (os.getenv("INSTANCE_CONNECTION_NAME") or "").strip()
DB_USER = (os.getenv("DB_USER") or "").strip()
DB_PASS = (os.getenv("DB_PASS") or "").strip()
DB_NAME = (os.getenv("DB_NAME") or "").strip()
DB_ENABLE_IAM_AUTH = (os.getenv("DB_ENABLE_IAM_AUTH", "false").lower() in {"1", "true", "yes"})

# Configuração de conversão
MONETARY_COLUMNS = {
    c.strip().lower()
    for c in (os.getenv("MONETARY_COLUMNS") or "").split(",")
    if c.strip()
}

NUMERIC_HINT = re.compile(
    r"(^|_)(valor|vlr|amount|saldo|preco|preço|price|rate|taxa|juros|multa|bruto|liquido|líquido|"
    r"quantidade|quantity|qtd|volume|financeiro|resultado|rentabilidade|cdi|tir|yield|nav|pl|"
    r"patrimonio|patrimônio|percent|pct|perc|porcentagem|provento|dividendo|strike|limit|limite)(_|$)",
    re.I,
)
DATE_HINT = re.compile(r"(^|_)(data|date|dt|vencimento|maturity|fixing|emissao|emissão|liquidacao|liquidação)(_|$)", re.I)
TEXT_ID_HINT = re.compile(
    r"(^|_)(conta|account|cpf|cnpj|document|documento|codigo|código|code|id|ticker|ativo|symbol|"
    r"isin|email|e_mail|mail|nome|name|assessor|status|side|tipo|type|telefone|phone)(_|$)",
    re.I,
)

app = Flask(__name__)

# ===================== UTIL =====================
def now_utc() -> datetime:
    return datetime.now(UTC)


def uuid4() -> str:
    return str(uuid.uuid4())


def log(level: str, msg: str, *args: Any) -> None:
    ts = now_utc().isoformat()
    print(f"{ts} | {level.upper()} | " + (msg % args if args else msg), flush=True)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_dumps(value: Any) -> str:
    def default(o: Any) -> Any:
        if isinstance(o, Decimal):
            return str(o)
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        return str(o)

    return json.dumps(value, ensure_ascii=False, default=default)


def basic_auth_header(client_id: str, client_secret: str) -> str:
    token = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def safe_resp_text(resp: requests.Response, limit: int = 1200) -> str:
    try:
        return (resp.text or "")[:limit]
    except Exception:
        return "<non-text-body>"


def normalize_key(name: str, max_len: int = 55) -> str:
    name = (name or "col").strip()
    name = name.replace("%", " pct ").replace("R$", " valor ")
    name = re.sub(r"[áàâãä]", "a", name, flags=re.I)
    name = re.sub(r"[éèêë]", "e", name, flags=re.I)
    name = re.sub(r"[íìîï]", "i", name, flags=re.I)
    name = re.sub(r"[óòôõö]", "o", name, flags=re.I)
    name = re.sub(r"[úùûü]", "u", name, flags=re.I)
    name = re.sub(r"ç", "c", name, flags=re.I)
    name = re.sub(r"[^0-9a-zA-Z]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_").lower()
    if not name:
        name = "col"
    if name[0].isdigit():
        name = f"c_{name}"
    return name[:max_len]


def unique_names(headers: Sequence[str]) -> Dict[str, str]:
    used: Dict[str, int] = {}
    mapping: Dict[str, str] = {}
    for idx, header in enumerate(headers):
        base = normalize_key(header or f"col_{idx+1}")
        count = used.get(base, 0)
        used[base] = count + 1
        mapping[header] = base if count == 0 else f"{base}_{count + 1}"
    return mapping


def qident(identifier: str) -> str:
    # Identificadores já saneados; ainda assim escapamos aspas.
    return '"' + identifier.replace('"', '""') + '"'


def table_name_for_report(report_key: str) -> str:
    return normalize_key(report_key, max_len=48)


def decode_bytes(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


# ===================== CATALOG =====================
def load_catalog() -> Dict[str, Dict[str, Any]]:
    catalog: Dict[str, Dict[str, Any]] = {}

    # Arquivo JSON versionado no container
    if CATALOG_FILE.exists():
        try:
            catalog.update(json.loads(CATALOG_FILE.read_text(encoding="utf-8")))
        except Exception as exc:
            log("ERROR", "Falha lendo PROVIDER_API_CATALOG_FILE=%s: %s", CATALOG_FILE, exc)

    # JSON em variável de ambiente: sobrepõe arquivo
    raw_json = (os.getenv("PROVIDER_API_CATALOG_JSON") or "").strip()
    if raw_json:
        try:
            catalog.update(json.loads(raw_json))
        except Exception as exc:
            log("ERROR", "Falha lendo PROVIDER_API_CATALOG_JSON: %s", exc)

    # Compatibilidade com versão antiga: {"key":"url"}
    raw_map = (os.getenv("PROVIDER_REPORT_MAP") or "").strip()
    if raw_map:
        try:
            old_map = json.loads(raw_map)
            for key, url in old_map.items():
                if key not in catalog and url:
                    catalog[key] = {
                        "description": "Endpoint legado importado de PROVIDER_REPORT_MAP",
                        "method": "GET",
                        "url": url,
                        "async": True,
                    }
        except Exception as exc:
            log("ERROR", "Falha lendo PROVIDER_REPORT_MAP legado: %s", exc)

    return catalog


CATALOG = load_catalog()


def resolve_report_config(report_key: str) -> Dict[str, Any]:
    if report_key in CATALOG:
        return dict(CATALOG[report_key])

    # Convenção para Managed Reports: managed-reports-<slug>
    # Ex.: managed-reports-account-base => /api/v1/managed-reports/account-base
    if report_key.startswith("managed-reports-"):
        slug = report_key.replace("managed-reports-", "", 1)
        return {
            "description": f"Managed Reports - {slug}",
            "method": "GET",
            "base_url": "https://api.example-provider.com/api-managed-reports",
            "path": f"/api/v1/managed-reports/{slug}",
            "async": True,
            "webhook_name": slug,
        }

    raise KeyError(f"Relatório/API '{report_key}' não está no catálogo.")


# ===================== TOKEN =====================
class TokenCache:
    def __init__(self) -> None:
        self.value: Optional[str] = None
        self.expiry: datetime = now_utc() - timedelta(seconds=1)

    def get(self) -> str:
        if not self.value or now_utc() >= self.expiry:
            self.refresh()
        assert self.value
        return self.value

    def refresh(self) -> None:
        missing = [
            name
            for name, value in {
                "PROVIDER_CLIENT_ID": PROVIDER_CLIENT_ID,
                "PROVIDER_CLIENT_SECRET": PROVIDER_CLIENT_SECRET,
                "PROVIDER_TOKEN_URL": PROVIDER_TOKEN_URL,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError("Variáveis ausentes: " + ", ".join(missing))

        headers = {
            "Authorization": basic_auth_header(PROVIDER_CLIENT_ID, PROVIDER_CLIENT_SECRET),
            "x-id-partner-request": uuid4(),
            "Content-Type": "application/x-www-form-urlencoded",
        }
        log("INFO", "Solicitando access_token PROVIDER…")
        resp = requests.post(
            PROVIDER_TOKEN_URL,
            headers=headers,
            data={"grant_type": "client_credentials"},
            timeout=HTTP_TIMEOUT_S,
        )
        try:
            resp.raise_for_status()
        except Exception:
            log("ERROR", "Falha token PROVIDER: status=%s body~=%s", resp.status_code, safe_resp_text(resp, 800))
            raise

        token = None
        for key in ("access_token", "Access-Token", "ACCESS_TOKEN", "X-Access-Token"):
            token = resp.headers.get(key)
            if token:
                break
        if not token:
            raise RuntimeError("Token endpoint não retornou access_token no header.")

        self.value = token
        self.expiry = now_utc() + timedelta(minutes=14, seconds=30)
        log("INFO", "Access token obtido; expira em %s", self.expiry.isoformat())


TOKEN = TokenCache()


# ===================== GCS =====================
_gcs_client = None


def gcs_client():
    global _gcs_client
    if _gcs_client is None:
        from google.cloud import storage

        _gcs_client = storage.Client()
    return _gcs_client


def gcs_upload_bytes(data: bytes, blob_path: str, content_type: str) -> Optional[str]:
    if not GCS_BUCKET:
        return None
    client = gcs_client()
    blob = client.bucket(GCS_BUCKET).blob(blob_path)
    blob.upload_from_string(data, content_type=content_type)
    uri = f"gs://{GCS_BUCKET}/{blob_path}"
    log("INFO", "GCS upload ok: %s (%d bytes)", uri, len(data))
    return uri


# ===================== DB =====================
_engine = None
_connector = None


def db_configured() -> bool:
    return bool(DATABASE_URL or (INSTANCE_CONNECTION_NAME and DB_USER and DB_NAME and (DB_PASS or DB_ENABLE_IAM_AUTH)))


def get_engine():
    global _engine, _connector
    if _engine is not None:
        return _engine

    if not db_configured():
        if STRICT_DB:
            raise RuntimeError("Banco não configurado. Defina DATABASE_URL ou INSTANCE_CONNECTION_NAME/DB_USER/DB_PASS/DB_NAME.")
        log("WARN", "Banco não configurado; serviço operará apenas com GCS/local.")
        return None

    from sqlalchemy import create_engine

    if DATABASE_URL:
        _engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
        return _engine

    from google.cloud.sql.connector import Connector, IPTypes

    _connector = Connector()

    def getconn():
        return _connector.connect(
            INSTANCE_CONNECTION_NAME,
            "pg8000",
            user=DB_USER,
            password=DB_PASS or None,
            db=DB_NAME,
            enable_iam_auth=DB_ENABLE_IAM_AUTH,
            ip_type=IPTypes.PUBLIC,
        )

    _engine = create_engine("postgresql+pg8000://", creator=getconn, pool_pre_ping=True, future=True)
    return _engine


def init_db() -> None:
    engine = get_engine()
    if engine is None:
        return
    from sqlalchemy import text

    sql_path = Path(os.getenv("PROVIDER_SCHEMA_FILE", "schema_cloudsql.sql"))
    if sql_path.exists():
        ddl = sql_path.read_text(encoding="utf-8")
    else:
        ddl = """
        CREATE SCHEMA IF NOT EXISTS report_raw;
        CREATE SCHEMA IF NOT EXISTS report_bi;
        CREATE TABLE IF NOT EXISTS report_raw.report_files (
            file_id UUID PRIMARY KEY,
            report_key TEXT NOT NULL,
            content_type TEXT,
            source_file_name TEXT,
            gcs_path TEXT,
            gcs_meta_path TEXT,
            sha256 TEXT,
            byte_size BIGINT,
            row_count INTEGER DEFAULT 0,
            received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            meta JSONB NOT NULL DEFAULT '{}'::jsonb
        );
        CREATE TABLE IF NOT EXISTS report_raw.report_rows (
            row_id UUID PRIMARY KEY,
            file_id UUID NOT NULL REFERENCES report_raw.report_files(file_id) ON DELETE CASCADE,
            report_key TEXT NOT NULL,
            row_number INTEGER NOT NULL,
            payload_raw JSONB NOT NULL,
            payload_norm JSONB NOT NULL DEFAULT '{}'::jsonb,
            payload_br JSONB NOT NULL DEFAULT '{}'::jsonb,
            loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS report_raw.api_requests (
            request_id UUID PRIMARY KEY,
            report_key TEXT NOT NULL,
            method TEXT NOT NULL,
            url TEXT NOT NULL,
            request_body JSONB,
            response_status INTEGER,
            response_body_preview TEXT,
            x_id_partner_request TEXT,
            requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS report_raw.webhook_events (
            event_id UUID PRIMARY KEY,
            report_key TEXT NOT NULL,
            content_type TEXT,
            raw_preview TEXT,
            headers JSONB,
            received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """

    with engine.begin() as conn:
        # pg8000/SQLAlchemy aceita múltiplos statements quando separados aqui.
        for statement in [s.strip() for s in ddl.split(";") if s.strip()]:
            conn.execute(text(statement))
    log("INFO", "DDL base verificado/criado.")


# ===================== NORMALIZAÇÃO =====================
def clean_number_text(value: str) -> str:
    text = str(value).strip()
    neg = False
    if text.startswith("(") and text.endswith(")"):
        neg = True
        text = text[1:-1]
    text = text.replace("R$", "").replace("%", "").replace("\u00a0", " ")
    text = re.sub(r"[^0-9,\.\-]", "", text)
    if text.count("-") > 1:
        text = text.replace("-", "")
    if neg and not text.startswith("-"):
        text = "-" + text
    return text


def parse_decimal_any(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None

    text = clean_number_text(str(value))
    if text in {"", "-", ".", ","}:
        return None

    if "," in text and "." in text:
        # O separador decimal é o último que aparecer.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(".", "").replace(",", ".")

    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def parse_date_any(value: Any) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    # Evita interpretar conta/código numérico como data.
    if re.fullmatch(r"\d{1,6}", text):
        return None
    try:
        # dayfirst ajuda padrão BR, mas ISO continua funcionando.
        return dtparser.parse(text, dayfirst=True, fuzzy=False).date()
    except Exception:
        return None


def br_number(value: Decimal, decimals: int = 2) -> str:
    q = value.quantize(Decimal("1." + ("0" * decimals)), rounding=ROUND_HALF_UP)
    return f"{q:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def br_date(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def should_treat_numeric(col: str, value: Any) -> bool:
    col_norm = normalize_key(col)
    if TEXT_ID_HINT.search(col_norm) and not NUMERIC_HINT.search(col_norm):
        return False
    if col_norm.lower() in MONETARY_COLUMNS:
        return True
    if NUMERIC_HINT.search(col_norm):
        return parse_decimal_any(value) is not None
    text = str(value or "")
    # Só infere número automaticamente quando há separador decimal ou símbolo financeiro.
    return bool(re.search(r"R\$|%|\d+[,.]\d+", text)) and parse_decimal_any(value) is not None


def should_treat_date(col: str, value: Any) -> bool:
    col_norm = normalize_key(col)
    return bool(DATE_HINT.search(col_norm) and parse_date_any(value) is not None)


def normalize_row(row: Mapping[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, str]]:
    norm: Dict[str, Any] = {}
    br: Dict[str, Any] = {}
    mapping = unique_names(list(row.keys()))

    for original, value in row.items():
        key = mapping[original]
        if value is None:
            norm[key] = None
            br[key] = ""
            continue

        if should_treat_date(original, value):
            d = parse_date_any(value)
            if d:
                norm[key] = d.isoformat()
                br[key] = br_date(d)
                continue

        if should_treat_numeric(original, value):
            dec = parse_decimal_any(value)
            if dec is not None:
                norm[key] = str(dec)
                br[key] = br_number(dec)
                continue

        text = str(value).strip()
        norm[key] = text
        br[key] = text

    return norm, br, mapping


# ===================== PARSERS =====================
def sniff_csv_reader(text: str) -> csv.DictReader:
    """
    Detecta delimitador de CSV de forma robusta.

    O PROVIDER costuma enviar alguns relatórios separados por ';'.
    O csv.Sniffer pode falhar quando o arquivo tem cabeçalhos grandes,
    campos com vírgula no texto ou codificação com BOM. Se a detecção
    automática gerar apenas 1 coluna, forçamos uma segunda tentativa
    escolhendo o delimitador mais presente na primeira linha útil.
    """
    sample = text[:32768]

    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        if reader.fieldnames and len(reader.fieldnames) > 1:
            return reader
    except Exception:
        pass

    first_line = ""
    for line in text.splitlines():
        if line.strip():
            first_line = line
            break

    candidates = [",", ";", "\t", "|"]
    delimiter = max(candidates, key=lambda d: first_line.count(d)) if first_line else ","

    # Se mesmo assim não houver separador detectado, tenta ';' como fallback,
    # porque é o padrão mais comum em CSV exportado para ambiente BR.
    if first_line and first_line.count(delimiter) == 0:
        delimiter = ";"

    return csv.DictReader(io.StringIO(text), delimiter=delimiter)

def rows_from_csv_bytes(data: bytes) -> List[Dict[str, Any]]:
    text = decode_bytes(data)
    reader = sniff_csv_reader(text)
    rows: List[Dict[str, Any]] = []
    for row in reader:
        rows.append({str(k): ("" if v is None else v) for k, v in row.items() if k is not None})
    return rows


def flatten_json(obj: Any, prefix: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            new_key = f"{prefix}_{key}" if prefix else str(key)
            if isinstance(value, (Mapping, list)):
                out.update(flatten_json(value, new_key))
            else:
                out[new_key] = value
    elif isinstance(obj, list):
        # Lista de escalares vira texto; lista de objetos é tratada em extract_json_rows.
        if all(not isinstance(x, (Mapping, list)) for x in obj):
            out[prefix or "value"] = ", ".join(map(str, obj))
        else:
            for i, value in enumerate(obj, 1):
                out.update(flatten_json(value, f"{prefix}_{i}" if prefix else f"item_{i}"))
    else:
        out[prefix or "value"] = obj
    return out


def first_list_of_dicts(obj: Any) -> Optional[List[Dict[str, Any]]]:
    if isinstance(obj, list) and obj and all(isinstance(x, Mapping) for x in obj):
        return [dict(x) for x in obj]
    if isinstance(obj, Mapping):
        for preferred in ("data", "items", "result", "results", "accounts", "positions", "response"):
            value = obj.get(preferred)
            found = first_list_of_dicts(value)
            if found:
                return found
        for value in obj.values():
            found = first_list_of_dicts(value)
            if found:
                return found
    return None


def rows_from_json_payload(payload: Any) -> List[Dict[str, Any]]:
    found = first_list_of_dicts(payload)
    if found:
        return [flatten_json(x) for x in found]
    if isinstance(payload, Mapping):
        return [flatten_json(payload)]
    if isinstance(payload, list):
        return [flatten_json({"value": payload})]
    return [{"value": payload}]


def detect_content_type(content_type: str, data: bytes, filename: Optional[str] = None) -> str:
    ct = (content_type or "").lower()
    fname = (filename or "").lower()
    head = data[:20].lstrip()
    if "zip" in ct or fname.endswith(".zip") or data[:4] == b"PK\x03\x04":
        return "zip"
    if "pdf" in ct or fname.endswith(".pdf") or data[:4] == b"%PDF":
        return "pdf"
    if "csv" in ct or fname.endswith(".csv"):
        return "csv"
    if "json" in ct or fname.endswith(".json") or head.startswith(b"{") or head.startswith(b"["):
        return "json"
    # PROVIDER às vezes manda CSV com octet-stream.
    try:
        text = decode_bytes(data[:2048])
        if "\n" in text and ("," in text or ";" in text or "\t" in text):
            return "csv"
    except Exception:
        pass
    return "binary"


# ===================== DB LOAD =====================
def ensure_dynamic_table(report_key: str, rows: Sequence[Mapping[str, Any]]) -> Tuple[str, Dict[str, str], Dict[str, str]]:
    engine = get_engine()
    if engine is None or not rows:
        return "", {}, {}
    from sqlalchemy import text

    headers: List[str] = []
    seen = set()
    for row in rows:
        for h in row.keys():
            if h not in seen:
                headers.append(str(h))
                seen.add(h)

    col_map = unique_names(headers)
    table = table_name_for_report(report_key)
    table_sql = f"report_bi.{qident(table)}"

    # Decide colunas tipadas por amostragem.
    typed_cols: Dict[str, str] = {}
    for original in headers:
        col = col_map[original]
        sample_values = [r.get(original) for r in rows[:200] if r.get(original) not in (None, "")]
        if sample_values and any(should_treat_date(original, v) for v in sample_values):
            typed_cols[f"{col}__date"] = "DATE"
        if sample_values and any(should_treat_numeric(original, v) for v in sample_values):
            typed_cols[f"{col}__num"] = "NUMERIC"

    base_columns = """
        report_row_id UUID PRIMARY KEY,
        file_id UUID NOT NULL,
        report_key TEXT NOT NULL,
        source_row_number INTEGER NOT NULL,
        received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        payload_raw JSONB NOT NULL,
        payload_norm JSONB NOT NULL,
        payload_br JSONB NOT NULL
    """

    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS report_bi"))
        conn.execute(text(f"CREATE TABLE IF NOT EXISTS {table_sql} ({base_columns})"))
        conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table}_file_id ON {table_sql} (file_id)"))
        conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table}_report_key ON {table_sql} (report_key)"))
        for col in col_map.values():
            conn.execute(text(f"ALTER TABLE {table_sql} ADD COLUMN IF NOT EXISTS {qident(col)} TEXT"))
        for col, sql_type in typed_cols.items():
            conn.execute(text(f"ALTER TABLE {table_sql} ADD COLUMN IF NOT EXISTS {qident(col)} {sql_type}"))

        # View latest: facilita Power BI pegando apenas última carga de cada relatório.
        latest_view = f"report_bi.{qident(table + '_latest')}"
        conn.execute(text(f"""
            CREATE OR REPLACE VIEW {latest_view} AS
            SELECT t.*
            FROM {table_sql} t
            JOIN (
                SELECT report_key, MAX(received_at) AS max_received_at
                FROM {table_sql}
                GROUP BY report_key
            ) m ON m.report_key = t.report_key AND m.max_received_at = t.received_at
        """))

    return table_sql, col_map, typed_cols



def insert_report_data(
    report_key: str,
    rows: Sequence[Mapping[str, Any]],
    *,
    file_id: str,
    content_type: str,
    source_file_name: Optional[str],
    gcs_path: Optional[str],
    gcs_meta_path: Optional[str],
    data: bytes,
    meta: Mapping[str, Any],
) -> Dict[str, Any]:
    engine = get_engine()
    if engine is None:
        return {"db": False, "row_count": len(rows)}

    from sqlalchemy import text

    if AUTO_INIT_DB:
        init_db()

    received_at = now_utc()
    row_count = len(rows)
    sha = sha256_bytes(data)

    table_sql = ""
    col_map: Dict[str, str] = {}
    typed_cols: Dict[str, str] = {}

    if rows:
        table_sql, col_map, typed_cols = ensure_dynamic_table(report_key, rows)

    batch_size = int(os.getenv("DB_BATCH_SIZE", "1000") or "1000")

    def chunks(seq, size):
        for i in range(0, len(seq), size):
            yield seq[i:i + size]

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO report_raw.report_files
                    (file_id, report_key, content_type, source_file_name, gcs_path, gcs_meta_path,
                     sha256, byte_size, row_count, received_at, meta)
                VALUES
                    (:file_id, :report_key, :content_type, :source_file_name, :gcs_path, :gcs_meta_path,
                     :sha256, :byte_size, :row_count, :received_at, CAST(:meta AS jsonb))
                ON CONFLICT (file_id) DO NOTHING
                """
            ),
            {
                "file_id": file_id,
                "report_key": report_key,
                "content_type": content_type,
                "source_file_name": source_file_name,
                "gcs_path": gcs_path,
                "gcs_meta_path": gcs_meta_path,
                "sha256": sha,
                "byte_size": len(data),
                "row_count": row_count,
                "received_at": received_at,
                "meta": json_dumps(meta),
            },
        )

        raw_batch = []
        dyn_batch = []

        dyn_columns = [
            "report_row_id",
            "file_id",
            "report_key",
            "source_row_number",
            "received_at",
            "payload_raw",
            "payload_norm",
            "payload_br",
        ]

        if table_sql:
            for original, col in col_map.items():
                dyn_columns.append(col)

                num_col = f"{col}__num"
                if num_col in typed_cols:
                    dyn_columns.append(num_col)

                date_col = f"{col}__date"
                if date_col in typed_cols:
                    dyn_columns.append(date_col)

            placeholders = []
            for c in dyn_columns:
                if c in ("payload_raw", "payload_norm", "payload_br"):
                    placeholders.append(f"CAST(:{c} AS jsonb)")
                else:
                    placeholders.append(f":{c}")

            dyn_insert_sql = text(
                f"INSERT INTO {table_sql} "
                f"({', '.join(qident(c) for c in dyn_columns)}) "
                f"VALUES ({', '.join(placeholders)})"
            )
        else:
            dyn_insert_sql = None

        for idx, row in enumerate(rows, 1):
            row_id = uuid4()
            norm, br, _ = normalize_row(row)

            raw_payload = json_dumps(row)
            norm_payload = json_dumps(norm)
            br_payload = json_dumps(br)

            raw_batch.append(
                {
                    "row_id": row_id,
                    "file_id": file_id,
                    "report_key": report_key,
                    "row_number": idx,
                    "payload_raw": raw_payload,
                    "payload_norm": norm_payload,
                    "payload_br": br_payload,
                }
            )

            if table_sql:
                dyn_values: Dict[str, Any] = {
                    "report_row_id": row_id,
                    "file_id": file_id,
                    "report_key": report_key,
                    "source_row_number": idx,
                    "received_at": received_at,
                    "payload_raw": raw_payload,
                    "payload_norm": norm_payload,
                    "payload_br": br_payload,
                }

                for original, col in col_map.items():
                    raw_val = row.get(original)
                    dyn_values[col] = None if raw_val is None else str(raw_val)

                    num_col = f"{col}__num"
                    if num_col in typed_cols:
                        dec = parse_decimal_any(raw_val)
                        dyn_values[num_col] = None if dec is None else str(dec)

                    date_col = f"{col}__date"
                    if date_col in typed_cols:
                        d = parse_date_any(raw_val)
                        dyn_values[date_col] = None if d is None else d

                dyn_batch.append(dyn_values)

        raw_insert_sql = text(
            """
            INSERT INTO report_raw.report_rows
                (row_id, file_id, report_key, row_number, payload_raw, payload_norm, payload_br)
            VALUES
                (:row_id, :file_id, :report_key, :row_number,
                 CAST(:payload_raw AS jsonb), CAST(:payload_norm AS jsonb), CAST(:payload_br AS jsonb))
            """
        )

        for part in chunks(raw_batch, batch_size):
            conn.execute(raw_insert_sql, part)

        if dyn_insert_sql is not None:
            for part in chunks(dyn_batch, batch_size):
                conn.execute(dyn_insert_sql, part)

    if table_sql:
        try:
            ensure_powerbi_view_for_report(report_key)
        except Exception as exc:
            log("WARN", "Falha ao atualizar view Power BI de %s: %s", report_key, exc)

    return {"db": True, "row_count": row_count, "file_id": file_id, "bi_table": table_sql or None}


# ===================== PROCESSAMENTO =====================
def http_get_with_retry(url: str, headers: Optional[dict] = None, max_attempts: int = 5) -> Tuple[bytes, str, Optional[str]]:
    attempt = 0
    while True:
        attempt += 1
        try:
            resp = requests.get(url, headers=headers or {}, timeout=120)
            if resp.status_code in {500, 502, 503, 504}:
                raise requests.HTTPError(f"HTTP {resp.status_code} servidor")
            resp.raise_for_status()
            filename = None
            disp = resp.headers.get("content-disposition") or resp.headers.get("Content-Disposition")
            if disp:
                match = re.search(r'filename="?([^";]+)', disp)
                if match:
                    filename = match.group(1)
            return resp.content or b"", resp.headers.get("content-type", ""), filename
        except Exception as exc:
            if attempt >= max_attempts:
                log("ERROR", "Falha download URL assinada (%d/%d): %s", attempt, max_attempts, exc)
                raise
            wait_s = min(BACKOFF_BASE_S * (2 ** (attempt - 1)) + random.uniform(0, 1.3), BACKOFF_MAX_S)
            log("WARN", "Erro download URL assinada (%d/%d). Retry em %.1fs: %s", attempt, max_attempts, wait_s, exc)
            time.sleep(wait_s)


def extract_signed_url(payload: Mapping[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    candidates = [payload]
    for key in ("response", "data", "result", "file", "report"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            candidates.append(value)
    for node in candidates:
        url = node.get("url") or node.get("fileUrl") or node.get("signedUrl") or node.get("signedURL")
        filename = node.get("fileName") or node.get("filename") or node.get("name")
        last_modified = node.get("lastModified") or node.get("last_modified")
        if url:
            return str(url), (str(filename) if filename else None), (str(last_modified) if last_modified else None)
    return None, None, None


def make_blob_base(report_key: str, source_file_name: Optional[str]) -> str:
    day = now_utc().strftime("%Y/%m/%d")
    stem = Path(source_file_name).stem if source_file_name else report_key
    stem = normalize_key(stem, max_len=80)
    ts = now_utc().strftime("%Y%m%d_%H%M%S")
    return f"{GCS_PREFIX}/{report_key}/{day}/{stem}_{ts}_{uuid.uuid4().hex[:8]}"


def save_local(data: bytes, filename: str) -> str:
    path = SAVE_DIR / filename
    path.write_bytes(data)
    log("INFO", "Arquivo local salvo: %s (%d bytes)", path, len(data))
    return str(path)


def process_payload_bytes(
    report_key: str,
    data: bytes,
    *,
    content_type: str = "",
    source_file_name: Optional[str] = None,
    meta: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    meta = dict(meta or {})
    file_id = uuid4()
    kind = detect_content_type(content_type, data, source_file_name)
    extension = {
        "csv": ".csv",
        "json": ".json",
        "zip": ".zip",
        "pdf": ".pdf",
        "binary": ".bin",
    }.get(kind, ".bin")
    blob_base = make_blob_base(report_key, source_file_name)
    gcs_path = gcs_upload_bytes(data, blob_base + extension, content_type or "application/octet-stream")
    gcs_meta_path = gcs_upload_bytes(json_dumps(meta).encode("utf-8"), blob_base + ".meta.json", "application/json")
    save_local(data, Path(blob_base).name + extension)

    rows: List[Dict[str, Any]] = []
    parse_note = ""
    try:
        if kind == "csv":
            rows = rows_from_csv_bytes(data)
        elif kind == "json":
            payload = json.loads(decode_bytes(data))
            rows = rows_from_json_payload(payload)
        elif kind == "zip":
            parse_note = "ZIP/PDF salvo para auditoria; sem carga tabular automática."
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    for name in zf.namelist():
                        lower = name.lower()
                        if lower.endswith(".csv"):
                            rows.extend(rows_from_csv_bytes(zf.read(name)))
                        elif lower.endswith(".json"):
                            rows.extend(rows_from_json_payload(json.loads(decode_bytes(zf.read(name)))))
            except Exception as exc:
                parse_note = f"ZIP salvo, mas não foi possível extrair conteúdo tabular: {exc}"
        else:
            parse_note = f"Tipo {kind} salvo para auditoria; sem parser tabular."
    except Exception as exc:
        log("ERROR", "Falha parse %s/%s: %s", report_key, kind, exc)
        parse_note = f"Falha parse: {exc}"
        rows = []

    db_result = insert_report_data(
        report_key,
        rows,
        file_id=file_id,
        content_type=content_type or kind,
        source_file_name=source_file_name,
        gcs_path=gcs_path,
        gcs_meta_path=gcs_meta_path,
        data=data,
        meta={**meta, "kind": kind, "parse_note": parse_note},
    )
    return {
        "file_id": file_id,
        "report_key": report_key,
        "kind": kind,
        "row_count": len(rows),
        "gcs_path": gcs_path,
        "gcs_meta_path": gcs_meta_path,
        "parse_note": parse_note,
        **db_result,
    }


def record_webhook_event(report_key: str, content_type: str, raw_preview: str, headers: Mapping[str, Any]) -> None:
    engine = get_engine()
    if engine is None:
        return
    from sqlalchemy import text

    if AUTO_INIT_DB:
        init_db()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO report_raw.webhook_events
                    (event_id, report_key, content_type, raw_preview, headers)
                VALUES
                    (:event_id, :report_key, :content_type, :raw_preview, CAST(:headers AS jsonb))
                """
            ),
            {
                "event_id": uuid4(),
                "report_key": report_key,
                "content_type": content_type,
                "raw_preview": raw_preview[:4000],
                "headers": json_dumps(dict(headers)),
            },
        )


# ===================== TRIGGER =====================
def render_template(value: Any, params: Mapping[str, Any], drop_empty: bool = False) -> Any:
    if isinstance(value, str):
        def repl(match: re.Match) -> str:
            key = match.group(1)
            val = params.get(key, "")
            return "" if val is None else str(val)

        rendered = re.sub(r"\{([^{}]+)\}", repl, value)
        return rendered
    if isinstance(value, Mapping):
        out = {}
        for k, v in value.items():
            rv = render_template(v, params, drop_empty=drop_empty)
            if drop_empty and (rv is None or rv == ""):
                continue
            out[k] = rv
        return out
    if isinstance(value, list):
        out_list = [render_template(v, params, drop_empty=drop_empty) for v in value]
        return [v for v in out_list if not (drop_empty and (v is None or v == ""))]
    return value


def build_url(config: Mapping[str, Any], params: Mapping[str, Any]) -> str:
    if config.get("url"):
        url = str(config["url"])
    else:
        base = str(config.get("base_url") or "").rstrip("/")
        path = str(config.get("path") or "")
        url = base + path
    for key, value in params.items():
        url = url.replace("{" + key + "}", str(value))
    missing = re.findall(r"\{([^{}]+)\}", url)
    if missing:
        raise ValueError(f"Parâmetros ausentes na URL: {', '.join(missing)}")
    return url


def validate_required(config: Mapping[str, Any], params: Mapping[str, Any]) -> None:
    required = config.get("required_params") or []
    missing = [key for key in required if params.get(key) in (None, "")]
    if missing:
        raise ValueError("Parâmetros obrigatórios ausentes: " + ", ".join(missing))

    max_days = config.get("max_days")
    if max_days and params.get("startDate") and params.get("endDate"):
        start = parse_date_any(params["startDate"])
        end = parse_date_any(params["endDate"])
        if start and end and (end - start).days > int(max_days):
            raise ValueError(f"Janela máxima excedida para {config.get('description')}: {max_days} dias")


def build_headers(config: Mapping[str, Any], params: Mapping[str, Any]) -> Dict[str, str]:
    headers = {
        "accept": "application/json, text/csv, application/zip, */*",
        "x-id-partner-request": uuid4(),
        "access_token": TOKEN.get(),
    }
    optional_headers = config.get("optional_headers") or {}
    for key, template in optional_headers.items():
        value = render_template(template, params)
        if value not in (None, ""):
            headers[key] = str(value)
    return headers


def record_api_request(report_key: str, method: str, url: str, body: Optional[Mapping[str, Any]], status: int, preview: str, x_id: str) -> None:
    engine = get_engine()
    if engine is None:
        return
    from sqlalchemy import text

    if AUTO_INIT_DB:
        init_db()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO report_raw.api_requests
                    (request_id, report_key, method, url, request_body, response_status, response_body_preview, x_id_partner_request)
                VALUES
                    (:request_id, :report_key, :method, :url, CAST(:request_body AS jsonb), :response_status, :response_body_preview, :xid)
                """
            ),
            {
                "request_id": uuid4(),
                "report_key": report_key,
                "method": method,
                "url": url,
                "request_body": json_dumps(body or {}),
                "response_status": status,
                "response_body_preview": preview[:2000],
                "xid": x_id,
            },
        )


def trigger_one(report_key: str, params: Mapping[str, Any]) -> Dict[str, Any]:
    config = resolve_report_config(report_key)
    validate_required(config, params)
    method = str(config.get("method", "GET")).upper()
    url = build_url(config, params)
    headers = build_headers(config, params)
    body = None
    if method in {"POST", "PUT", "PATCH"}:
        body_template = config.get("body_template")
        if body_template is not None:
            body = render_template(body_template, params, drop_empty=bool(config.get("drop_empty_body_values")))
        else:
            body = {k: v for k, v in params.items() if k not in {"report", "reports"}}
        headers["Content-Type"] = "application/json"

    log("INFO", "Disparando %s %s", method, url)
    resp = requests.request(method, url, headers=headers, json=body, timeout=HTTP_TIMEOUT_S)
    if resp.status_code == 401:
        log("WARN", "401 no disparo %s; renovando token e tentando novamente.", report_key)
        TOKEN.refresh()
        headers = build_headers(config, params)
        if method in {"POST", "PUT", "PATCH"}:
            headers["Content-Type"] = "application/json"
        resp = requests.request(method, url, headers=headers, json=body, timeout=HTTP_TIMEOUT_S)

    content_type = resp.headers.get("content-type", "")
    preview = safe_resp_text(resp, 2000)
    record_api_request(report_key, method, url, body, resp.status_code, preview, headers.get("x-id-partner-request", ""))

    result: Dict[str, Any] = {
        "report": report_key,
        "method": method,
        "url": url,
        "status": resp.status_code,
        "async": bool(config.get("async")),
        "body_preview": preview[:600],
    }

    if resp.status_code in {200, 201} and resp.content:
        kind = detect_content_type(content_type, resp.content)
        if kind in {"csv", "json", "zip", "pdf"}:
            processed = process_payload_bytes(
                report_key,
                resp.content,
                content_type=content_type,
                source_file_name=f"{report_key}_sync",
                meta={"source": "sync-response", "url": url, "status": resp.status_code},
            )
            result["processed"] = processed
    elif resp.status_code == 202:
        result["message"] = "Requisição aceita. Aguardando entrega via webhook."
    elif resp.status_code >= 400:
        log("ERROR", "Falha ao disparar %s: HTTP %s body~=%s", report_key, resp.status_code, preview[:800])

    return result


# ===================== ROUTES =====================
@app.get("/")
def root():
    return jsonify(
        {
            "service": "report-ingestion-v2",
            "status": "ok",
            "now": now_utc().isoformat(),
            "gcs_bucket": GCS_BUCKET,
            "gcs_prefix": GCS_PREFIX,
            "db_configured": db_configured(),
            "reports_count": len(CATALOG),
            "reports": sorted(CATALOG.keys()),
        }
    )


@app.get("/healthz")
def healthz():
    return "ok", 200


@app.get("/reports")
def reports():
    return jsonify(CATALOG)


@app.post("/admin/init-db")
def admin_init_db():
    init_db()
    return jsonify({"ok": True})


@app.route("/trigger", methods=["GET", "POST"])
def trigger():
    try:
        if request.method == "POST":
            payload = request.get_json(silent=True) or {}
            if "reports" in payload:
                jobs = payload["reports"]
            else:
                jobs = [{"key": payload.get("report") or payload.get("key"), "params": payload.get("params") or payload}]
        else:
            args = dict(request.args.items())
            reports_param = args.pop("report", "")
            keys = [x.strip() for x in reports_param.split(",") if x.strip()] or list(CATALOG.keys())
            jobs = [{"key": key, "params": args} for key in keys]

        results = []
        for job in jobs:
            key = job.get("key") or job.get("report")
            if not key:
                raise ValueError("Informe o campo report/key.")
            params = dict(job.get("params") or {})
            # parâmetros de topo também podem ser aproveitados no POST simples
            for k, v in job.items():
                if k not in {"key", "report", "params"} and k not in params:
                    params[k] = v
            results.append(trigger_one(str(key), params))

        http_status = 200 if all(int(r.get("status", 500)) < 500 for r in results) else 502
        return jsonify({"results": results}), http_status
    except Exception as exc:
        log("ERROR", "trigger exception: %s\n%s", exc, traceback.format_exc())
        return jsonify({"error": str(exc)}), 400


@app.post("/webhook/provider/<report_key>")
def webhook_provider(report_key: str):
    try:
        content_type = request.headers.get("Content-Type", "")
        raw = request.data or b""
        preview = decode_bytes(raw[:4000]) if raw else ""
        record_webhook_event(report_key, content_type, preview, dict(request.headers))
        log("INFO", "Webhook %s CT=%s len=%d", report_key, content_type, len(raw))

        kind = detect_content_type(content_type, raw)
        if kind == "json" and raw:
            payload = json.loads(decode_bytes(raw))
            url, filename, last_modified = extract_signed_url(payload if isinstance(payload, Mapping) else {})
            if url:
                try:
                    data, dl_ct, dl_filename = http_get_with_retry(url)
                except Exception as exc1:
                    log("WARN", "Download direto falhou; tentando com access_token. Erro: %s", exc1)
                    headers = {"x-id-partner-request": uuid4(), "access_token": TOKEN.get(), "accept": "*/*"}
                    data, dl_ct, dl_filename = http_get_with_retry(url, headers=headers, max_attempts=3)
                result = process_payload_bytes(
                    report_key,
                    data,
                    content_type=dl_ct,
                    source_file_name=dl_filename or filename,
                    meta={"webhook_payload": payload, "last_modified": last_modified, "source": "webhook-signed-url"},
                )
                return jsonify({"ack": True, "processed": result}), 200

            # JSON sem URL: pode ser retorno síncrono do próprio webhook ou payload tabular.
            result = process_payload_bytes(
                report_key,
                raw,
                content_type=content_type,
                source_file_name=f"{report_key}_webhook.json",
                meta={"source": "webhook-json"},
            )
            return jsonify({"ack": True, "processed": result}), 200

        if raw:
            result = process_payload_bytes(
                report_key,
                raw,
                content_type=content_type,
                source_file_name=f"{report_key}_webhook",
                meta={"source": "webhook-raw"},
            )
            return jsonify({"ack": True, "processed": result}), 200

        return jsonify({"ack": True, "note": "empty webhook"}), 200
    except Exception as exc:
        log("ERROR", "Webhook exception %s: %s\n%s", report_key, exc, traceback.format_exc())
        # Retorna 200 para evitar reentrega infinita do provedor. O erro fica em log.
        return jsonify({"ack": True, "error": str(exc)}), 200


# Alias legado: /webhook/provider/<report_key> é o recomendado.
@app.post("/webhook/<report_key>")
def webhook_legacy(report_key: str):
    return webhook_provider(report_key)



@app.post("/admin/refresh-powerbi-views")
def admin_refresh_powerbi_views():
    try:
        result = refresh_all_powerbi_views()
        return jsonify({"ok": True, **result}), 200
    except Exception as exc:
        log("ERROR", "refresh_powerbi_views exception: %s\n%s", exc, traceback.format_exc())
        return jsonify({"ok": False, "error": str(exc)}), 500

# ===================== MAIN =====================
def main() -> None:
    missing = [
        name
        for name, value in {
            "PROVIDER_CLIENT_ID": PROVIDER_CLIENT_ID,
            "PROVIDER_CLIENT_SECRET": PROVIDER_CLIENT_SECRET,
            "GCS_BUCKET": GCS_BUCKET,
        }.items()
        if not value
    ]
    if missing:
        log("WARN", "Variáveis ausentes: %s", ", ".join(missing))
    log("INFO", "Relatórios configurados: %s", sorted(CATALOG.keys()))
    if AUTO_INIT_DB:
        try:
            init_db()
        except Exception as exc:
            if STRICT_DB:
                raise
            log("WARN", "Não foi possível inicializar DB agora: %s", exc)
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()

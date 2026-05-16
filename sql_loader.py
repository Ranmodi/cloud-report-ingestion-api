import csv, hashlib, io, json, os, re, traceback, uuid, zipfile
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from flask import Flask, jsonify, request

import psycopg2

from report_column_normalizer import load_json_mapping, normalize_header, canonical_key, safe_blob_component

app = Flask(__name__)
UTC = timezone.utc

GCS_BUCKET = (os.getenv("GCS_BUCKET") or "example-project-report-ingestion").strip()
GCS_PREFIX = (os.getenv("GCS_PREFIX") or "report-ingestion").strip().strip("/")
INSTANCE_CONNECTION_NAME = (os.getenv("INSTANCE_CONNECTION_NAME") or "").strip()
DB_NAME = (os.getenv("DB_NAME") or "reports_db").strip()
DB_USER = (os.getenv("DB_USER") or "report_loader").strip()
DB_PASS = (os.getenv("DB_PASS") or "").strip()
DB_HOST = (os.getenv("DB_HOST") or "").strip()
DB_PORT = int(os.getenv("DB_PORT", "5432") or "5432")
POWERBI_USER = (os.getenv("POWERBI_USER") or "powerbi_reader").strip()
MAX_SAMPLE_ROWS = int(os.getenv("MAX_SAMPLE_ROWS", "800") or "800")
BRT = ZoneInfo("America/Sao_Paulo")
COLUMN_MAPPING_FILE = (os.getenv("COLUMN_MAPPING_FILE") or "column_mappings.json").strip()
REPORT_NAMES_FILE = (os.getenv("REPORT_NAMES_FILE") or "report_names.json").strip()

TECH_COLS = {"report_row_id", "file_id", "report_key", "source_row_number", "received_at", "extraction_label"}

FRIENDLY_REPORT_NAMES = {
    "managed-reports-account-base": "Account Base",
    "managed-reports-registration-data": "Dados Cadastrais",
    "managed-reports-position": "Posições",
    "managed-reports-monthly-tir": "TIR Mensal",
    "managed-reports-orders": "Ordens de RV",
    "stock-orders": "Ordens de RV",
}

FRIENDLY_COLUMNS = {
    "nr_conta": "Conta",
    "conta": "Conta",
    "cod_carteira": "Conta",
    "nome_completo": "Nome Completo",
    "nm_cliente": "Nome Completo",
    "cliente": "Cliente",
    "email": "E-mail",
    "email_assessor": "E-mail Assessor",
    "nm_officer": "Officer",
    "nm_partner": "Assessor",
    "assessor": "Assessor",
    "cge_officer": "CGE Officer",
    "cge_partner": "CGE Assessor",
    "tipo_cliente": "Tipo Cliente",
    "tipo_parceiro": "Tipo Parceiro",
    "dt_abertura": "Data Abertura",
    "dt_nascimento": "Data Nascimento",
    "dt_primeiro_investimento": "Data Primeiro Investimento",
    "dt_ultimo_aporte": "Data Último Aporte",
    "reference_month": "Mês Referência",
    "reference_date": "Data Referência",
    "auc_end": "AUC Final",
    "inflow_and_outflow": "Entradas e Saídas",
    "taxes_paid_mtd": "Taxas Pagas MTD",
    "taxes_paid_ytd": "Taxas Pagas YTD",
    "dt_interface": "Data Interface",
    "dt_movimentacao": "Data Movimentação",
    "mercado": "Mercado",
    "sub_mercado": "Submercado",
    "produto": "Produto",
    "ativo": "Ativo",
    "emissor": "Emissor",
    "indexador": "Indexador",
    "cnpj_fundo": "CNPJ Fundo",
    "cge_fundo": "CGE Fundo",
    "tipo": "Tipo",
    "tipo_opcao": "Tipo Opção",
    "quantidade": "Quantidade",
    "vl_custo": "Valor Custo",
    "vl_bruto": "Valor Bruto",
    "vl_ir": "IR",
    "vl_iof": "IOF",
    "vl_taxa": "Taxa",
    "vl_taxa_compra": "Taxa Compra",
    "taxa_indicativa": "Taxa Indicativa",
    "received_at": "Atualizado em",
    "extraction_label": "Nome da Extração",
}

_COLUMN_MAP_CACHE = None
_REPORT_NAMES_CACHE = None

def get_column_map() -> Dict[str, str]:
    global _COLUMN_MAP_CACHE
    if _COLUMN_MAP_CACHE is None:
        try:
            _COLUMN_MAP_CACHE = load_json_mapping(COLUMN_MAPPING_FILE)
        except Exception as exc:
            log("WARN", "Falha ao carregar COLUMN_MAPPING_FILE=%s: %s", COLUMN_MAPPING_FILE, exc)
            _COLUMN_MAP_CACHE = {}
    return _COLUMN_MAP_CACHE


def get_report_names() -> Dict[str, str]:
    global _REPORT_NAMES_CACHE
    if _REPORT_NAMES_CACHE is None:
        payload = {}
        try:
            from pathlib import Path
            p = Path(REPORT_NAMES_FILE)
            if p.exists():
                payload = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            log("WARN", "Falha ao carregar REPORT_NAMES_FILE=%s: %s", REPORT_NAMES_FILE, exc)
        names = dict(FRIENDLY_REPORT_NAMES)
        if isinstance(payload, dict):
            names.update({str(k): str(v) for k, v in payload.items() if v})
        _REPORT_NAMES_CACHE = names
    return _REPORT_NAMES_CACHE

NUM_HINT = re.compile(
    r"(^|_)(vl|valor|amount|saldo|pl|auc|inflow|outflow|tax|taxes|taxa|preco|price|bruto|liquido|custo|ir|iof|tir|rentabilidade|performance|quantity|quantidade|qtd|qtde|pu|financeiro)(_|$)",
    re.I,
)
DATE_HINT = re.compile(r"(^|_)(dt|data|date|reference_date|created_at|updated_at|vencimento|movimentacao|interface)(_|$)", re.I)
TEXT_FORCE = re.compile(r"(conta|cod_carteira|cpf|cnpj|cge|id|email|cep|telefone)", re.I)


def log(level: str, msg: str, *args: Any) -> None:
    print(f"{datetime.now(UTC).isoformat()} | {level} | " + (msg % args if args else msg), flush=True)


def now_utc():
    return datetime.now(UTC)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def sanitize_identifier(name: str, fallback: str) -> str:
    s = (name or "").strip().lower().replace("\ufeff", "")
    tr = str.maketrans("áàãâäéèêëíìîïóòõôöúùûüçñ", "aaaaaeeeeiiiiooooouuuucn")
    s = s.translate(tr)
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    if not s:
        s = fallback
    if re.match(r"^[0-9]", s):
        s = "c_" + s
    return s[:55]


def unique_names(headers: Sequence[str]) -> List[str]:
    seen = {}
    out = []
    for idx, h in enumerate(headers, 1):
        base = sanitize_identifier(h, f"col_{idx}")
        name = base
        n = 2
        while name in seen:
            name = f"{base}_{n}"
            n += 1
        seen[name] = 1
        out.append(name)
    return out


def table_name_for_report(report_key: str) -> str:
    return sanitize_identifier(report_key, "report")


def friendly_report_name(report_key: str) -> str:
    return get_report_names().get(report_key, report_key.replace("managed-reports-", "").replace("-", " ").title())


def friendly_column_name(col: str) -> str:
    base = col
    if base.endswith("__num"):
        base = base[:-5]
    if base.endswith("__date"):
        base = base[:-6]
    if base in FRIENDLY_COLUMNS:
        return FRIENDLY_COLUMNS[base]
    mapped = normalize_header(base, get_column_map())
    return mapped


def decode_bytes(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            return data.decode(enc)
        except Exception:
            pass
    return data.decode("latin-1", errors="replace")


def maybe_extract_zip(data: bytes) -> bytes:
    raw = data[3:] if data.startswith(b"\xef\xbb\xbf") else data
    if not raw.startswith(b"PK"):
        return data
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        preferred = [n for n in names if n.lower().endswith((".csv", ".txt"))]
        target = preferred[0] if preferred else names[0]
        extracted = z.read(target)
        log("INFO", "ZIP detectado. Extraído %s (%d bytes)", target, len(extracted))
        return extracted


def flatten_json(obj: Any, prefix: str = "") -> Dict[str, Any]:
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}_{k}" if prefix else str(k)
            if isinstance(v, (dict, list)):
                out.update(flatten_json(v, key))
            else:
                out[key] = "" if v is None else v
    elif isinstance(obj, list):
        if all(not isinstance(x, (dict, list)) for x in obj):
            out[prefix or "value"] = ", ".join(map(str, obj))
        else:
            for i, v in enumerate(obj, 1):
                out.update(flatten_json(v, f"{prefix}_{i}" if prefix else f"item_{i}"))
    else:
        out[prefix or "value"] = "" if obj is None else obj
    return out


def first_list_of_dicts(obj: Any):
    if isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj):
        return obj
    if isinstance(obj, dict):
        for key in ("data", "items", "result", "results", "orders", "response", "content"):
            if key in obj:
                found = first_list_of_dicts(obj[key])
                if found:
                    return found
        for v in obj.values():
            found = first_list_of_dicts(v)
            if found:
                return found
    return None


def json_to_csv_bytes(payload: Any) -> bytes:
    rows_src = first_list_of_dicts(payload)
    rows = [flatten_json(x) for x in rows_src] if rows_src else [flatten_json(payload)]
    headers = []
    seen = set()
    for row in rows:
        for h in row.keys():
            if h not in seen:
                headers.append(h)
                seen.add(h)
    out = io.StringIO(newline="")
    w = csv.DictWriter(out, fieldnames=headers, extrasaction="ignore")
    w.writeheader()
    for row in rows:
        w.writerow(row)
    return out.getvalue().encode("utf-8")


def payload_to_csv_bytes(data: bytes, content_type: str = "") -> bytes:
    data = maybe_extract_zip(data)
    stripped = data.lstrip()
    ct = (content_type or "").lower()
    if "json" in ct or stripped.startswith(b"{") or stripped.startswith(b"["):
        payload = json.loads(decode_bytes(data))
        signed_url = None
        if isinstance(payload, dict):
            for k in ("url", "fileUrl", "fileURL", "signedUrl", "downloadUrl"):
                if payload.get(k):
                    signed_url = payload[k]
                    break
        if signed_url:
            import requests
            r = requests.get(signed_url, timeout=180)
            r.raise_for_status()
            return payload_to_csv_bytes(r.content, r.headers.get("content-type", ""))
        return json_to_csv_bytes(payload)
    return data


def detect_delimiter(text: str) -> str:
    first = text.splitlines()[0] if text.splitlines() else ""
    if first.count("\t") > max(first.count(";"), first.count(",")):
        return "\t"
    return ";" if first.count(";") > first.count(",") else ","


def csv_info(data: bytes):
    text = decode_bytes(data).replace("\r\n", "\n").replace("\r", "\n")
    delimiter = detect_delimiter(text)
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter)
    headers = reader.fieldnames or []
    sample = []
    for i, row in enumerate(reader, 1):
        sample.append({k: ("" if v is None else str(v)) for k, v in row.items() if k is not None})
        if i >= MAX_SAMPLE_ROWS:
            break
    return text, delimiter, headers, sample


def looks_numeric(values: Sequence[str], col: str) -> bool:
    if TEXT_FORCE.search(col):
        return False
    vals = [v.strip() for v in values if v and v.strip()]
    if not vals:
        return False
    ok = 0
    for v in vals[:200]:
        t = re.sub(r"[^0-9,.\-]", "", v)
        if t and t not in {"-", ".", ","}:
            ok += 1
    return ok / max(len(vals[:200]), 1) >= 0.75 and (NUM_HINT.search(col) is not None or ok >= 10)


def looks_date(values: Sequence[str], col: str) -> bool:
    if not DATE_HINT.search(col):
        return False
    vals = [v.strip() for v in values if v and v.strip()]
    if not vals:
        return False
    ok = 0
    for v in vals[:200]:
        if re.match(r"^\d{4}-\d{2}-\d{2}", v) or re.match(r"^\d{2}/\d{2}/\d{4}", v) or re.match(r"^\d{8}$", v):
            ok += 1
    return ok / max(len(vals[:200]), 1) >= 0.50


def column_types(safe_cols, headers, sample):
    num_cols, date_cols = set(), set()
    for original, safe in zip(headers, safe_cols):
        values = [row.get(original, "") for row in sample]
        if looks_date(values, safe):
            date_cols.add(safe)
        elif looks_numeric(values, safe):
            num_cols.add(safe)
    return num_cols, date_cols


def get_conn():
    if DB_HOST:
        return psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASS, host=DB_HOST, port=DB_PORT)
    if not INSTANCE_CONNECTION_NAME:
        raise RuntimeError("INSTANCE_CONNECTION_NAME não configurado")
    return psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASS, host=f"/cloudsql/{INSTANCE_CONNECTION_NAME}")


def init_db():
    sql = """
    CREATE SCHEMA IF NOT EXISTS report_raw;
    CREATE SCHEMA IF NOT EXISTS report_bi;
    CREATE SCHEMA IF NOT EXISTS report_history;
    CREATE SCHEMA IF NOT EXISTS relatorios;
    CREATE SCHEMA IF NOT EXISTS relatorios_historico;
    CREATE SCHEMA IF NOT EXISTS provider_jobs;

    CREATE EXTENSION IF NOT EXISTS pgcrypto;

    CREATE TABLE IF NOT EXISTS report_raw.report_files (
        file_id text PRIMARY KEY,
        report_key text NOT NULL,
        content_type text,
        source_file_name text,
        gcs_path text,
        gcs_meta_path text,
        sha256 text,
        byte_size bigint,
        row_count bigint,
        received_at timestamptz DEFAULT now(),
        meta jsonb DEFAULT '{}'::jsonb
    );

    CREATE TABLE IF NOT EXISTS provider_jobs.load_jobs (
        job_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        report_key text NOT NULL,
        gcs_uri text NOT NULL,
        status text NOT NULL DEFAULT 'pending',
        created_at timestamptz NOT NULL DEFAULT now(),
        started_at timestamptz,
        finished_at timestamptz,
        row_count bigint,
        result jsonb,
        error text
    );

    CREATE OR REPLACE FUNCTION relatorios.to_numeric_br_safe(v text)
    RETURNS numeric
    LANGUAGE plpgsql
    IMMUTABLE
    AS $$
    DECLARE
        t text;
        last_comma int;
        last_dot int;
    BEGIN
        t := trim(coalesce(v, ''));
        t := regexp_replace(t, '[^0-9,.\\-]', '', 'g');
        IF t IS NULL OR t = '' OR t = '-' THEN RETURN NULL; END IF;
        last_comma := CASE WHEN strpos(reverse(t), ',') > 0 THEN length(t) - strpos(reverse(t), ',') + 1 ELSE 0 END;
        last_dot   := CASE WHEN strpos(reverse(t), '.') > 0 THEN length(t) - strpos(reverse(t), '.') + 1 ELSE 0 END;
        IF last_comma > 0 AND last_dot > 0 THEN
            IF last_comma > last_dot THEN
                t := replace(replace(t, '.', ''), ',', '.');
            ELSE
                t := replace(t, ',', '');
            END IF;
        ELSIF last_comma > 0 THEN
            t := replace(t, ',', '.');
        END IF;
        RETURN t::numeric;
    EXCEPTION WHEN others THEN
        RETURN NULL;
    END;
    $$;

    CREATE OR REPLACE FUNCTION relatorios.to_date_br_safe(v text)
    RETURNS date
    LANGUAGE plpgsql
    IMMUTABLE
    AS $$
    DECLARE
        t text;
    BEGIN
        t := trim(coalesce(v, ''));
        IF t = '' THEN RETURN NULL; END IF;
        IF t ~ '^\\d{4}-\\d{2}-\\d{2}' THEN RETURN substring(t from 1 for 10)::date; END IF;
        IF t ~ '^\\d{2}/\\d{2}/\\d{4}$' THEN RETURN to_date(t, 'DD/MM/YYYY'); END IF;
        IF t ~ '^\\d{8}$' THEN RETURN to_date(t, 'YYYYMMDD'); END IF;
        RETURN NULL;
    EXCEPTION WHEN others THEN
        RETURN NULL;
    END;
    $$;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    return {"ok": True}


def gcs_download(uri: str) -> bytes:
    from google.cloud import storage
    path = uri[5:]
    bucket, blob = path.split("/", 1)
    client = storage.Client()
    return client.bucket(bucket).blob(blob).download_as_bytes()


def gcs_upload(data: bytes, report_key: str, name: str, content_type: str) -> str:
    from google.cloud import storage
    blob_path = f"{GCS_PREFIX}/{report_key}/sql_loader/{name}"
    storage.Client().bucket(GCS_BUCKET).blob(blob_path).upload_from_string(data, content_type=content_type)
    return f"gs://{GCS_BUCKET}/{blob_path}"


def _table_columns_with_types(cur, schema: str, table: str) -> List[Tuple[str, str]]:
    cur.execute(
        """
        SELECT a.attname, pg_catalog.format_type(a.atttypid, a.atttypmod)
        FROM pg_catalog.pg_attribute a
        JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname=%s AND c.relname=%s AND a.attnum > 0 AND NOT a.attisdropped
        ORDER BY a.attnum
        """,
        (schema, table),
    )
    return [(r[0], r[1]) for r in cur.fetchall()]


def _ensure_history_table(cur, table: str) -> None:
    cur.execute(f"CREATE TABLE IF NOT EXISTS report_history.{qident(table)} (LIKE report_bi.{qident(table)} INCLUDING ALL)")
    latest_cols = _table_columns_with_types(cur, "report_bi", table)
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema='report_history' AND table_name=%s
        """,
        (table,),
    )
    hist_cols = {r[0] for r in cur.fetchall()}
    for col, typ in latest_cols:
        if col not in hist_cols:
            cur.execute(f"ALTER TABLE report_history.{qident(table)} ADD COLUMN {qident(col)} {typ}")


def append_history(cur, report_table: str) -> None:
    _ensure_history_table(cur, report_table)
    latest_cols = [c for c, _ in _table_columns_with_types(cur, "report_bi", report_table)]
    hist_cols = {c for c, _ in _table_columns_with_types(cur, "report_history", report_table)}
    common = [c for c in latest_cols if c in hist_cols]
    if common:
        cols = ", ".join(qident(c) for c in common)
        cur.execute(f"INSERT INTO report_history.{qident(report_table)} ({cols}) SELECT {cols} FROM report_bi.{qident(report_table)}")


def create_powerbi_view(
    cur,
    report_key: str,
    table: str,
    all_cols: Sequence[str],
    num_cols: set,
    date_cols: set,
    *,
    source_schema: str = "report_bi",
    target_schema: str = "relatorios",
    include_history_cols: bool = False,
):
    view_name = friendly_report_name(report_key)
    aliases_seen = set()
    select_parts = []

    skip_base = set(num_cols) | set(date_cols)

    # No histórico, a primeira leitura deve facilitar linha do tempo no Power BI.
    if include_history_cols:
        preferred = [
            ("extraction_label", "Nome da Extração"),
            ("received_at", "Data de Extração"),
            ("file_id", "ID Arquivo"),
            ("source_row_number", "Linha Origem"),
        ]
        available = set(all_cols)
        for col, alias in preferred:
            if col in available:
                aliases_seen.add(alias)
                select_parts.append(f"{qident(col)} AS {qident(alias)}")

    for col in all_cols:
        if col in {"report_row_id", "report_key"}:
            continue
        if not include_history_cols and col in TECH_COLS:
            continue
        if include_history_cols and col in {"extraction_label", "received_at", "file_id", "source_row_number"}:
            continue
        if col in skip_base:
            continue

        alias = friendly_column_name(col)
        base_alias = alias
        n = 2
        while alias in aliases_seen:
            alias = f"{base_alias} {n}"
            n += 1
        aliases_seen.add(alias)
        select_parts.append(f"{qident(col)} AS {qident(alias)}")

    if not select_parts:
        return

    cur.execute(f"CREATE SCHEMA IF NOT EXISTS {qident(target_schema)}")
    cur.execute(f"DROP VIEW IF EXISTS {qident(target_schema)}.{qident(view_name)}")
    cur.execute(f"CREATE OR REPLACE VIEW {qident(target_schema)}.{qident(view_name)} AS SELECT {', '.join(select_parts)} FROM {qident(source_schema)}.{qident(table)}")
    cur.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s) THEN EXECUTE 'GRANT USAGE ON SCHEMA ' || quote_ident(%s) || ' TO ' || quote_ident(%s); END IF; END $$;",
        (POWERBI_USER, target_schema, POWERBI_USER),
    )
    cur.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s) THEN EXECUTE 'GRANT SELECT ON ' || quote_ident(%s) || '.' || quote_ident(%s) || ' TO ' || quote_ident(%s); END IF; END $$;",
        (POWERBI_USER, target_schema, view_name, POWERBI_USER),
    )


def load_csv_bytes(report_key: str, data: bytes, content_type: str = "text/csv", source_name: Optional[str] = None, gcs_uri: Optional[str] = None):
    init_db()

    csv_bytes = payload_to_csv_bytes(data, content_type)
    text, delimiter, headers, sample = csv_info(csv_bytes)

    if not headers:
        raise RuntimeError("CSV sem cabeçalho")

    safe_cols = unique_names(headers)
    num_cols, date_cols = column_types(safe_cols, headers, sample)

    report_table = table_name_for_report(report_key)
    staging = f"stg_{report_table}_{uuid.uuid4().hex[:8]}"
    file_id = str(uuid.uuid4())
    received_at = now_utc()
    sha = sha256_bytes(csv_bytes)

    col_defs = ", ".join(f"{qident(c)} text" for c in safe_cols)
    clean_uri = gcs_upload(csv_bytes, report_key, f"{file_id}_clean.csv", "text/csv") if GCS_BUCKET else None

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '55min'")
            cur.execute("CREATE SCHEMA IF NOT EXISTS report_raw")
            cur.execute("CREATE SCHEMA IF NOT EXISTS report_bi")
            cur.execute("CREATE SCHEMA IF NOT EXISTS relatorios")
            cur.execute(f"CREATE TEMP TABLE {qident(staging)} ({col_defs}) ON COMMIT DROP")

            copy_sql = (
                f"COPY {qident(staging)} ({', '.join(qident(c) for c in safe_cols)}) "
                f"FROM STDIN WITH (FORMAT CSV, HEADER TRUE, DELIMITER {repr(delimiter)}, QUOTE '\"')"
            )
            cur.copy_expert(copy_sql, io.StringIO(text, newline=""))

            cur.execute("SELECT count(*) FROM " + qident(staging))
            row_count = int(cur.fetchone()[0])

            cur.execute(
                """
                INSERT INTO report_raw.report_files
                    (file_id, report_key, content_type, source_file_name, gcs_path, sha256, byte_size, row_count, received_at, meta)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (file_id) DO NOTHING
                """,
                (
                    file_id,
                    report_key,
                    content_type,
                    source_name,
                    gcs_uri or clean_uri,
                    sha,
                    len(csv_bytes),
                    row_count,
                    received_at,
                    json.dumps({"delimiter": delimiter, "headers": headers}, ensure_ascii=False),
                ),
            )

            extraction_label = f"{friendly_report_name(report_key)} - {received_at.astimezone(BRT).strftime('%d.%m.%Y - %Hh%M')}"
            select_parts = [
                "gen_random_uuid()::text AS report_row_id",
                f"{repr(file_id)}::text AS file_id",
                f"{repr(report_key)}::text AS report_key",
                f"{repr(extraction_label)}::text AS extraction_label",
                "row_number() OVER ()::bigint AS source_row_number",
                "now()::timestamptz AS received_at",
            ]
            final_cols = ["report_row_id", "file_id", "report_key", "extraction_label", "source_row_number", "received_at"]

            for c in safe_cols:
                select_parts.append(f"{qident(c)}")
                final_cols.append(c)

                if c in num_cols:
                    select_parts.append(f"relatorios.to_numeric_br_safe({qident(c)}) AS {qident(c + '__num')}")
                    final_cols.append(c + "__num")

                if c in date_cols:
                    select_parts.append(f"relatorios.to_date_br_safe({qident(c)}) AS {qident(c + '__date')}")
                    final_cols.append(c + "__date")

            # Primeiro derruba a view amigável do Power BI.
            # Ela pode depender da view/tabela técnica antiga.
            cur.execute(f"DROP VIEW IF EXISTS relatorios.{qident(friendly_report_name(report_key))} CASCADE")

            # Depois derruba objetos técnicos antigos.
            cur.execute(f"DROP VIEW IF EXISTS report_bi.{qident(report_table + '_latest')} CASCADE")
            cur.execute(f"DROP TABLE IF EXISTS report_bi.{qident(report_table)} CASCADE")
            cur.execute(f"CREATE TABLE report_bi.{qident(report_table)} AS SELECT {', '.join(select_parts)} FROM {qident(staging)}")
            cur.execute(f"CREATE OR REPLACE VIEW report_bi.{qident(report_table + '_latest')} AS SELECT * FROM report_bi.{qident(report_table)}")

            append_history(cur, report_table)
            create_powerbi_view(cur, report_key, report_table, final_cols, num_cols, date_cols, source_schema="report_bi", target_schema="relatorios", include_history_cols=False)
            create_powerbi_view(cur, report_key, report_table, final_cols, num_cols, date_cols, source_schema="report_history", target_schema="relatorios_historico", include_history_cols=True)

        conn.commit()

    log("INFO", "Carga concluída: %s rows=%s table=report_bi.%s", report_key, row_count, report_table)

    return {
        "ok": True,
        "report_key": report_key,
        "row_count": row_count,
        "table": f"report_bi.{report_table}",
        "view": f'relatorios.{friendly_report_name(report_key)}',
        "gcs_clean": clean_uri,
    }


def create_job(report_key: str, gcs_uri: str):
    init_db()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO provider_jobs.load_jobs (report_key, gcs_uri, status)
                VALUES (%s, %s, 'pending')
                RETURNING job_id
                """,
                (report_key, gcs_uri),
            )
            job_id = str(cur.fetchone()[0])
        conn.commit()
    return job_id


def process_pending_jobs(limit: int = 1):
    init_db()
    processed = []

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT job_id, report_key, gcs_uri
                FROM provider_jobs.load_jobs
                WHERE status = 'pending'
                ORDER BY created_at
                LIMIT %s
                FOR UPDATE SKIP LOCKED
                """,
                (limit,),
            )
            jobs = cur.fetchall()

            for job_id, report_key, gcs_uri in jobs:
                cur.execute(
                    "UPDATE provider_jobs.load_jobs SET status='processing', started_at=now(), error=NULL WHERE job_id=%s",
                    (job_id,),
                )

        conn.commit()

    for job_id, report_key, gcs_uri in jobs:
        try:
            data = gcs_download(gcs_uri)
            result = load_csv_bytes(report_key, data, "application/octet-stream", source_name=gcs_uri.split("/")[-1], gcs_uri=gcs_uri)

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE provider_jobs.load_jobs
                        SET status='done', finished_at=now(), row_count=%s, result=%s::jsonb
                        WHERE job_id=%s
                        """,
                        (result.get("row_count"), json.dumps(result, ensure_ascii=False), job_id),
                    )
                conn.commit()

            processed.append({"job_id": str(job_id), "report_key": report_key, "ok": True, "row_count": result.get("row_count")})

        except Exception as exc:
            err = str(exc)
            log("ERROR", "Job %s erro: %s\n%s", job_id, exc, traceback.format_exc())

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE provider_jobs.load_jobs
                        SET status='error', finished_at=now(), error=%s
                        WHERE job_id=%s
                        """,
                        (err[:4000], job_id),
                    )
                conn.commit()

            processed.append({"job_id": str(job_id), "report_key": report_key, "ok": False, "error": err})

    return processed


@app.get("/")
def root():
    return jsonify({"status": "ok", "service": "provider-sql-loader-v3", "db": DB_NAME, "bucket": GCS_BUCKET})


@app.post("/admin/init-db")
def admin_init_db():
    return jsonify(init_db())


@app.post("/jobs/create")
def jobs_create():
    payload = request.get_json(silent=True) or {}
    report_key = payload.get("report_key")
    gcs_uri = payload.get("gcs_uri")
    if not report_key or not gcs_uri:
        return jsonify({"ok": False, "error": "Informe report_key e gcs_uri"}), 400

    try:
        job_id = create_job(report_key, gcs_uri)
        return jsonify({"ok": True, "job_id": job_id, "report_key": report_key, "gcs_uri": gcs_uri}), 202
    except Exception as exc:
        log("ERROR", "jobs/create erro: %s\n%s", exc, traceback.format_exc())
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/jobs/process")
def jobs_process():
    payload = request.get_json(silent=True) or {}
    limit = int(payload.get("limit") or 1)
    try:
        processed = process_pending_jobs(limit=limit)
        return jsonify({"ok": True, "processed": processed}), 200
    except Exception as exc:
        log("ERROR", "jobs/process erro: %s\n%s", exc, traceback.format_exc())
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/admin/load-from-gcs")
def admin_load_from_gcs():
    payload = request.get_json(silent=True) or {}
    report_key = payload.get("report_key")
    gcs_uri = payload.get("gcs_uri")
    if not report_key or not gcs_uri:
        return jsonify({"ok": False, "error": "Informe report_key e gcs_uri"}), 400

    try:
        data = gcs_download(gcs_uri)
        result = load_csv_bytes(report_key, data, "application/octet-stream", source_name=gcs_uri.split("/")[-1], gcs_uri=gcs_uri)
        return jsonify(result), 200
    except Exception as exc:
        log("ERROR", "load-from-gcs erro: %s\n%s", exc, traceback.format_exc())
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/webhook/<report_key>")
@app.post("/webhook/provider/<report_key>")
def webhook_loader(report_key: str):
    try:
        data = request.get_data() or b""
        content_type = request.headers.get("Content-Type", "application/octet-stream")
        result = load_csv_bytes(report_key, data, content_type, source_name=request.headers.get("X-Source-File"))
        return jsonify(result), 200
    except Exception as exc:
        log("ERROR", "webhook erro %s: %s\n%s", report_key, exc, traceback.format_exc())
        return jsonify({"ok": False, "error": str(exc), "report_key": report_key}), 500


@app.post("/admin/refresh-powerbi-views")
def refresh_powerbi_views():
    init_db()
    refreshed = []

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema='report_bi'
                  AND table_type='BASE TABLE'
                ORDER BY table_name
                """
            )
            rows = cur.fetchall()

            for (table,) in rows:
                report_key = table.replace("_", "-")
                if not report_key.startswith("managed-reports-"):
                    report_key = "managed-reports-" + report_key

                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema='report_bi'
                      AND table_name=%s
                    ORDER BY ordinal_position
                    """,
                    (table,),
                )
                cols = [r[0] for r in cur.fetchall()]
                num_cols = {c[:-5] for c in cols if c.endswith("__num")}
                date_cols = {c[:-6] for c in cols if c.endswith("__date")}

                create_powerbi_view(cur, report_key, table, cols, num_cols, date_cols)
                refreshed.append(friendly_report_name(report_key))

        conn.commit()

    return jsonify({"ok": True, "views": refreshed})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)

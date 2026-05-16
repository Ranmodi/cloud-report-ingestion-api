import csv
import io
import json
import re
import unicodedata
from datetime import datetime, date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

ACRONYMS = {
    "cdi", "cpf", "cnpj", "cge", "id", "pl", "ir", "iof", "tir", "rf", "rv", "cep", "ipca", "igpm",
    "pme", "nm", "nnm", "auc", "mtd", "ytd", "ttd", "pnl", "pu", "dt", "cod", "xp", "provider"
}
TEXT_FORCE_RE = re.compile(r"(conta|carteira|cpf|cnpj|cge|id|email|cep|telefone|celular|documento|codigo|cod_|^cod$|certificado|agencia|banco|isin|ticker)", re.I)
DATE_HINT_RE = re.compile(r"(^|_)(dt|data|date|vencimento|nascimento|abertura|encerramento|timestamp|created|updated|write|interface|movimentacao)(_|$)", re.I)
MONEY_HINT_RE = re.compile(r"(^|_)(vl|valor|amount|saldo|financeiro|preco|preço|price|bruto|liquido|líquido|custo|ir|iof|multa|juros|pl|auc|patrimonio|patrimônio)(_|$)", re.I)
NUM_HINT_RE = re.compile(r"(^|_)(vl|valor|amount|saldo|pl|auc|inflow|outflow|tax|taxes|taxa|preco|price|bruto|liquido|custo|ir|iof|tir|rentabilidade|performance|quantity|quantidade|qtd|qtde|pu|financeiro|percent|percentage|yield|cdi|dolar|ibov|volatility)(_|$)", re.I)
PERCENT_HINT_RE = re.compile(r"(%|percent|percentage|taxa|tir|rentabilidade|performance|yield|cdi|dolar|ibov|volatility)", re.I)


def strip_accents(value: str) -> str:
    value = "" if value is None else str(value)
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def canonical_key(name: str) -> str:
    text = strip_accents(name).replace("\ufeff", "").strip().lower()
    text = re.sub(r"[^a-z0-9%]+", "_", text)
    text = text.replace("%", "percentual")
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def normalize_mapping(mapping: Optional[Mapping[str, str]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key, value in (mapping or {}).items():
        ckey = canonical_key(key)
        if ckey and value is not None:
            out[ckey] = str(value).strip()
    return out


def load_json_mapping(path: str) -> Dict[str, str]:
    p = Path(path)
    if not p.exists():
        return {}
    payload = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        # Aceita lista [{"raw":..., "friendly":...}] se um dia preferir assim.
        tmp = {}
        for item in payload:
            if isinstance(item, dict):
                raw = item.get("raw") or item.get("Nome coluna relatório") or item.get("source")
                friendly = item.get("friendly") or item.get("Nome normalizado") or item.get("target")
                if raw and friendly:
                    tmp[str(raw)] = str(friendly)
        payload = tmp
    if not isinstance(payload, dict):
        return {}
    return normalize_mapping(payload)


def humanize_header(raw: str) -> str:
    original = "" if raw is None else str(raw).replace("\ufeff", "").strip()
    # Remove símbolos que normalmente não agregam, preservando % e R$.
    cleaned = re.sub(r"[_\-.]+", " ", original)
    cleaned = re.sub(r"[^\w\s%$/]+", " ", cleaned, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        cleaned = "Coluna"
    words = []
    for word in cleaned.split(" "):
        plain = canonical_key(word)
        if plain in ACRONYMS or len(word) <= 3 and word.isupper():
            words.append(strip_accents(word).upper())
        elif re.fullmatch(r"\d+[a-zA-Z]*", word):
            words.append(word.upper())
        else:
            words.append(word[:1].upper() + word[1:].lower())
    return " ".join(words)


def normalize_header(raw: str, column_map: Optional[Mapping[str, str]] = None) -> str:
    cmap = normalize_mapping(column_map)
    key = canonical_key(raw)
    if key in cmap:
        return cmap[key]
    return humanize_header(raw)


def unique_headers(headers: Sequence[str]) -> List[str]:
    seen: Dict[str, int] = {}
    out: List[str] = []
    for header in headers:
        base = header or "Coluna"
        n = seen.get(base, 0) + 1
        seen[base] = n
        out.append(base if n == 1 else f"{base} {n}")
    return out


def detect_delimiter(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            counts = {";": line.count(";"), ",": line.count(","), "\t": line.count("\t")}
            return max(counts, key=counts.get) if max(counts.values()) > 0 else ","
    return ","


def decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            return data.decode(enc)
        except Exception:
            continue
    return data.decode("latin-1", errors="replace")


def parse_decimal_any(value: object) -> Optional[Decimal]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    neg = False
    if text.startswith("(") and text.endswith(")"):
        neg = True
        text = text[1:-1]
    text = text.replace("R$", "").replace("%", "").replace(" ", "")
    text = re.sub(r"[^0-9,.-]", "", text)
    if text in {"", "-", ",", "."}:
        return None
    last_comma = text.rfind(",")
    last_dot = text.rfind(".")
    if last_comma >= 0 and last_dot >= 0:
        if last_comma > last_dot:
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif last_comma >= 0:
        text = text.replace(".", "").replace(",", ".")
    else:
        # Se tiver muitos pontos, assume pontos de milhar exceto o último.
        if text.count(".") > 1:
            parts = text.split(".")
            text = "".join(parts[:-1]) + "." + parts[-1]
    try:
        number = Decimal(text)
        return -number if neg else number
    except InvalidOperation:
        return None


def looks_numeric(values: Sequence[str], canonical_col: str) -> bool:
    if TEXT_FORCE_RE.search(canonical_col) or DATE_HINT_RE.search(canonical_col):
        return False
    vals = [str(v).strip() for v in values if v is not None and str(v).strip()]
    if not vals:
        return False
    ok = sum(1 for v in vals[:200] if parse_decimal_any(v) is not None)
    return ok / max(len(vals[:200]), 1) >= 0.70 and (NUM_HINT_RE.search(canonical_col) is not None or ok >= 10)


def looks_date(values: Sequence[str], canonical_col: str) -> bool:
    if not DATE_HINT_RE.search(canonical_col):
        return False
    vals = [str(v).strip() for v in values if v is not None and str(v).strip()]
    if not vals:
        return False
    ok = 0
    for v in vals[:200]:
        if parse_date_any(v) is not None:
            ok += 1
    return ok / max(len(vals[:200]), 1) >= 0.50


def parse_date_any(value: object) -> Optional[datetime]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    formats = [
        "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y", "%d-%m-%Y", "%Y%m%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(text[:26] if "%f" in fmt and len(text) > 26 and "+" not in text else text, fmt)
        except Exception:
            pass
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def format_decimal_br(value: Decimal, places: int = 2, trim: bool = False) -> str:
    q = Decimal("1") if places <= 0 else Decimal("1").scaleb(-places)
    value = value.quantize(q, rounding=ROUND_HALF_UP)
    s = f"{value:,.{places}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if trim and "," in s:
        s = s.rstrip("0").rstrip(",")
    return s


def format_date_br(dt: datetime) -> str:
    has_time = any([dt.hour, dt.minute, dt.second])
    return dt.strftime("%d/%m/%Y %H:%M:%S" if has_time else "%d/%m/%Y")


def classify_columns(headers: Sequence[str], rows: Sequence[Mapping[str, str]]) -> Dict[str, str]:
    kinds: Dict[str, str] = {}
    for header in headers:
        ckey = canonical_key(header)
        sample = [row.get(header, "") for row in rows[:300]]
        if TEXT_FORCE_RE.search(ckey):
            kinds[header] = "text"
        elif looks_date(sample, ckey):
            kinds[header] = "date"
        elif looks_numeric(sample, ckey):
            kinds[header] = "money" if MONEY_HINT_RE.search(ckey) else "number"
        else:
            kinds[header] = "text"
    return kinds


def normalize_csv_for_download(csv_bytes: bytes, column_map: Optional[Mapping[str, str]] = None) -> bytes:
    text = decode_text(csv_bytes).replace("\r\n", "\n").replace("\r", "\n")
    delimiter = detect_delimiter(text)
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter)
    raw_headers = reader.fieldnames or []
    rows = [{k: ("" if v is None else v) for k, v in row.items() if k is not None} for row in reader]
    kinds = classify_columns(raw_headers, rows)
    normalized_headers = unique_headers([normalize_header(h, column_map) for h in raw_headers])
    header_pairs = list(zip(raw_headers, normalized_headers))

    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=normalized_headers, delimiter=";", extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        new_row = {}
        for raw_h, new_h in header_pairs:
            value = row.get(raw_h, "")
            kind = kinds.get(raw_h, "text")
            if value is None or str(value).strip() == "":
                new_row[new_h] = ""
            elif kind == "date":
                dt = parse_date_any(value)
                new_row[new_h] = format_date_br(dt) if dt else value
            elif kind == "money":
                num = parse_decimal_any(value)
                new_row[new_h] = format_decimal_br(num, 2) if num is not None else value
            elif kind == "number":
                num = parse_decimal_any(value)
                if num is not None:
                    ckey = canonical_key(raw_h)
                    # percentuais e taxas podem ter muitas casas; não força símbolo para não alterar semântica.
                    new_row[new_h] = format_decimal_br(num, 6, trim=True if PERCENT_HINT_RE.search(ckey) else False)
                else:
                    new_row[new_h] = value
            else:
                new_row[new_h] = value
        writer.writerow(new_row)
    return out.getvalue().encode("utf-8-sig")


def safe_blob_component(value: str, default: str = "Relatorio") -> str:
    text = "" if value is None else str(value).strip()
    text = re.sub(r"[\\/:*?\"<>|]+", "-", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or default


def friendly_report_filename(display_name: str, dt: Optional[datetime] = None, ext: str = "csv", include_time: bool = True) -> str:
    dt = dt or datetime.now()
    base = safe_blob_component(display_name)
    if include_time:
        stamp = dt.strftime("%d.%m.%Y - %Hh%M")
        return f"{base} - {stamp}.{ext.lstrip('.')}"
    return f"{base}.{ext.lstrip('.')}"

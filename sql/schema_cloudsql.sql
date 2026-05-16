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

CREATE INDEX IF NOT EXISTS ix_report_files_key_received
    ON report_raw.report_files (report_key, received_at DESC);

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

CREATE INDEX IF NOT EXISTS ix_report_rows_file_id
    ON report_raw.report_rows (file_id);
CREATE INDEX IF NOT EXISTS ix_report_rows_report_key
    ON report_raw.report_rows (report_key);
CREATE INDEX IF NOT EXISTS ix_report_rows_payload_norm_gin
    ON report_raw.report_rows USING GIN (payload_norm);

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

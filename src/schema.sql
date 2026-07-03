-- ============================================================
-- Paluck Kirloskar PW VoiceBot — PostgreSQL Schema
-- Idempotent: safe to run on every server startup.
-- All statements use IF NOT EXISTS — existing tables are untouched.
-- ============================================================


-- ==================== CALLS ====================
CREATE TABLE IF NOT EXISTS calls (
    id                          BIGSERIAL PRIMARY KEY,
    record_id                   TEXT UNIQUE NOT NULL,
    cube_call_number            INTEGER,
    phone_number                TEXT,
    customer_name               TEXT,
    company_name                TEXT,
    campaign_id                 TEXT,
    call_status                 TEXT DEFAULT 'initiated',
    call_initiated_at           TIMESTAMPTZ DEFAULT NOW(),
    call_ended_at               TIMESTAMPTZ,
    call_duration_seconds       INTEGER,
    recording_url               TEXT,
    recording_duration_seconds  INTEGER,
    crm_lead_id                 TEXT,
    crm_activity_id             TEXT,
    metadata                    JSONB,
    created_at                  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_calls_phone        ON calls (phone_number);
CREATE INDEX IF NOT EXISTS idx_calls_status       ON calls (call_status);
CREATE INDEX IF NOT EXISTS idx_calls_initiated_at ON calls (call_initiated_at DESC);
CREATE INDEX IF NOT EXISTS idx_calls_cube_number  ON calls (cube_call_number);
CREATE INDEX IF NOT EXISTS idx_calls_record_id    ON calls (record_id);

-- WhatsApp fallback status for not-connected calls: 'sent' | 'failed' | NULL
ALTER TABLE calls ADD COLUMN IF NOT EXISTS whatsapp_status TEXT;

-- Real-time Cube call-status webhook (GET /getCallStatus) timestamps.
-- cube_connected_at  : set when Cube reports Status=Connected (customer picked up)
-- cube_disconnected_at: set when Cube reports Status=Disconnected (line closed)
-- Both NULL = Cube webhook never fired for this call (used by the 250s safety net).
ALTER TABLE calls ADD COLUMN IF NOT EXISTS cube_connected_at    TIMESTAMPTZ;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS cube_disconnected_at TIMESTAMPTZ;

-- Raw Status string Cube sent on /getCallStatus for the not-connected branch
-- (e.g. "NOANSWER", "Not Connected", or any future value we haven't mapped yet).
-- Surfaced on the dashboard as "No Answer: <cube_status_raw>" instead of a
-- generic "NOT CONNECTED" label, so the team can see exactly what Cube reported.
ALTER TABLE calls ADD COLUMN IF NOT EXISTS cube_status_raw TEXT;

-- When a call was fired by an automated campaign, this holds the campaigns.id
-- that launched it (NULL for manual Leads-page / inbound calls). Lets Call
-- History / Leads views show a "Campaign" badge and the Campaign page bridge
-- back to the rich post-call data in this row.
ALTER TABLE calls ADD COLUMN IF NOT EXISTS campaign_db_id BIGINT;

-- Post-call analysis results (written by _faber_lead_writeback after every call).
-- Stored here so each call has its own row — avoids data loss when the same lead
-- is called multiple times (previously only stored in lead_file_rows which gets
-- overwritten on each re-call).
ALTER TABLE calls ADD COLUMN IF NOT EXISTS installation_status        TEXT;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS installation_status_reason TEXT;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS disposition                TEXT;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS disposition_reason         TEXT;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS sentiment                  TEXT;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS call_summary               TEXT;


-- ==================== CONVERSATION LOGS ====================
CREATE TABLE IF NOT EXISTS conversation_logs (
    id            BIGSERIAL PRIMARY KEY,
    call_id       BIGINT REFERENCES calls(id) ON DELETE CASCADE,
    record_id     TEXT NOT NULL,
    speaker       TEXT NOT NULL,
    message       TEXT,
    message_type  TEXT DEFAULT 'speech',
    metadata      JSONB,
    timestamp     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conv_logs_record_id ON conversation_logs (record_id);
CREATE INDEX IF NOT EXISTS idx_conv_logs_call_id   ON conversation_logs (call_id);


-- ==================== CONSOLE LOGS ====================
CREATE TABLE IF NOT EXISTS console_logs (
    id          BIGSERIAL PRIMARY KEY,
    call_id     BIGINT REFERENCES calls(id) ON DELETE CASCADE,
    record_id   TEXT,
    log_level   TEXT DEFAULT 'INFO',
    message     TEXT,
    details     JSONB,
    timestamp   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_console_logs_record_id ON console_logs (record_id);
CREATE INDEX IF NOT EXISTS idx_console_logs_level     ON console_logs (log_level);


-- ==================== LEADS ====================
CREATE TABLE IF NOT EXISTS leads (
    id           BIGSERIAL PRIMARY KEY,
    phone_number TEXT,
    name         TEXT,
    lead_data    JSONB,
    status       TEXT DEFAULT 'pending',
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_leads_phone  ON leads (phone_number);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads (status);


-- ==================== CAMPAIGNS ====================
CREATE TABLE IF NOT EXISTS campaigns (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    state           TEXT NOT NULL DEFAULT 'running',
    total           INTEGER DEFAULT 0,
    called          INTEGER DEFAULT 0,
    failed          INTEGER DEFAULT 0,
    skipped         INTEGER DEFAULT 0,
    remaining       INTEGER DEFAULT 0,
    filters_used    TEXT,
    delay_seconds   INTEGER DEFAULT 30,
    max_concurrent  INTEGER DEFAULT 2,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_campaigns_state      ON campaigns (state);
CREATE INDEX IF NOT EXISTS idx_campaigns_started_at ON campaigns (started_at DESC);


-- ==================== CAMPAIGN LEADS (per-lead outcomes) ====================
CREATE TABLE IF NOT EXISTS campaign_leads (
    id                BIGSERIAL PRIMARY KEY,
    campaign_id       BIGINT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    phone             TEXT NOT NULL,
    name              TEXT,
    status            TEXT DEFAULT 'pending',
    attempt           INTEGER DEFAULT 0,
    call_started_at   TIMESTAMPTZ,
    call_completed_at TIMESTAMPTZ,
    error             TEXT,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_campaign_leads_unique ON campaign_leads (campaign_id, phone, attempt);
CREATE INDEX IF NOT EXISTS idx_campaign_leads_campaign_id ON campaign_leads (campaign_id);
CREATE INDEX IF NOT EXISTS idx_campaign_leads_phone       ON campaign_leads (phone);

ALTER TABLE campaign_leads ADD COLUMN IF NOT EXISTS outcome    TEXT;
ALTER TABLE campaign_leads ADD COLUMN IF NOT EXISTS conclusion TEXT;

-- Bridges a campaign lead to its real call + rich Excel row, so the campaign
-- table can show the true post-call outcome (disposition / installation_status /
-- sentiment) that post-call analysis writes to calls + lead_file_rows.
ALTER TABLE campaign_leads ADD COLUMN IF NOT EXISTS record_id        TEXT;
ALTER TABLE campaign_leads ADD COLUMN IF NOT EXISTS lead_file_row_id BIGINT;


-- ==================== LEAD FILES (uploaded Excel — history index) ====================
-- The ORIGINAL uploaded xlsx is preserved untouched on disk at stored_path.
-- The editable "working copy" lives in lead_file_rows (DB). Download can return
-- either the pristine original or a freshly-exported xlsx of the working copy.
CREATE TABLE IF NOT EXISTS lead_files (
    id             BIGSERIAL PRIMARY KEY,
    original_name  TEXT NOT NULL,           -- name as uploaded, e.g. "Calling data 20 - Jun.xlsx"
    stored_name    TEXT NOT NULL,           -- stamped on-disk name, e.g. "2026-06-23_Tuesday_Calling-data-20-Jun.xlsx"
    stored_path    TEXT NOT NULL,           -- absolute/relative path to the PRISTINE original
    uploaded_at    TIMESTAMPTZ DEFAULT NOW(),
    day_of_week    TEXT,                    -- e.g. "Tuesday" (denormalised for the history label)
    row_count      INTEGER DEFAULT 0,
    uploaded_by    TEXT,
    active         BOOLEAN DEFAULT TRUE,    -- soft-delete / archive flag
    created_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lead_files_uploaded_at ON lead_files (uploaded_at DESC);
CREATE INDEX IF NOT EXISTS idx_lead_files_active      ON lead_files (active);


-- ==================== LEAD FILE ROWS (the editable working copy) ====================
-- One row per Excel data row. Mirrors the Faber calling-list columns plus
-- tracking/writeback fields. Voice BOT calls update call_status/called_by and,
-- after the call, write back installation_status/remarks/sentiment/transcript/call_summary.
CREATE TABLE IF NOT EXISTS lead_file_rows (
    id                      BIGSERIAL PRIMARY KEY,
    file_id                 BIGINT NOT NULL REFERENCES lead_files(id) ON DELETE CASCADE,
    row_index               INTEGER NOT NULL,        -- 0-based position within the file
    -- ── mirrored Excel columns ──
    product_name            TEXT,
    mobile                  TEXT,
    dealer_name             TEXT,
    service_request_number  TEXT,
    asc_name                TEXT,
    installation_status     TEXT,
    remarks                 TEXT,
    sentiment               TEXT,
    transcript              TEXT,
    call_summary            TEXT,
    -- ── tracking / writeback ──
    call_status             TEXT DEFAULT 'pending',  -- pending|calling|initiated|called|failed
    called_by               TEXT,                    -- e.g. 'VoiceBOT'
    call_record_id          TEXT,                    -- links to calls.record_id for post-call writeback
    updated_at              TIMESTAMPTZ DEFAULT NOW(),
    created_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lead_file_rows_file_id ON lead_file_rows (file_id, row_index);
CREATE INDEX IF NOT EXISTS idx_lead_file_rows_mobile  ON lead_file_rows (mobile);
CREATE INDEX IF NOT EXISTS idx_lead_file_rows_record  ON lead_file_rows (call_record_id);

-- Standardized post-call disposition (also appended into remarks)
ALTER TABLE lead_file_rows ADD COLUMN IF NOT EXISTS disposition TEXT;

-- Customer name from the Excel "Customer Name" column — used for WhatsApp
-- template {{1}} (in place of ASC Name) and available for voice-call personalisation.
ALTER TABLE lead_file_rows ADD COLUMN IF NOT EXISTS customer_name TEXT;

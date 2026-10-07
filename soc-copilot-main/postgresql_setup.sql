-- ============================================================
-- SECURITY LOG ANALYZER — PostgreSQL Schema (mejorado)
-- Idempotente / apto para Docker init y DBeaver
-- ============================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'user_role') THEN
        CREATE TYPE user_role AS ENUM ('admin', 'analyst', 'viewer');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'log_source_type') THEN
        CREATE TYPE log_source_type AS ENUM (
            'siem', 'firewall', 'ids_ips', 'endpoint', 'cloud',
            'web_server', 'manual', 'api', 'other'
        );
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'log_format_type') THEN
        CREATE TYPE log_format_type AS ENUM (
            'syslog', 'cef', 'leef', 'json', 'csv',
            'windows_event', 'plain_text', 'unknown'
        );
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'pipeline_status') THEN
        CREATE TYPE pipeline_status AS ENUM ('pending', 'analyzing', 'analyzed', 'failed', 'archived');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'severity_level') THEN
        CREATE TYPE severity_level AS ENUM ('critical', 'high', 'medium', 'low', 'info', 'unknown');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'effort_level') THEN
        CREATE TYPE effort_level AS ENUM ('immediate', '<1h', '1-4h', '1d', '>1d');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'action_category') THEN
        CREATE TYPE action_category AS ENUM (
            'containment', 'eradication', 'recovery',
            'investigation', 'hardening', 'notification', 'other'
        );
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'execution_status') THEN
        CREATE TYPE execution_status AS ENUM ('pending', 'in_progress', 'completed', 'failed', 'skipped');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'chat_role_type') THEN
        CREATE TYPE chat_role_type AS ENUM ('user', 'assistant', 'system');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'incident_status') THEN
        CREATE TYPE incident_status AS ENUM ('open', 'investigating', 'contained', 'resolved', 'closed');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username        CITEXT      NOT NULL UNIQUE,
    email           CITEXT      NOT NULL UNIQUE,
    password_hash   TEXT        NOT NULL,
    role            user_role   NOT NULL DEFAULT 'analyst',
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS log_sources (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(120)    NOT NULL UNIQUE,
    source_type log_source_type NOT NULL,
    description TEXT,
    metadata    JSONB           NOT NULL DEFAULT '{}'::jsonb,
    is_active   BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS security_logs (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id         UUID REFERENCES log_sources(id) ON DELETE SET NULL,
    submitted_by      UUID REFERENCES users(id) ON DELETE SET NULL,
    raw_content       TEXT            NOT NULL,
    content_hash      CHAR(64)        NOT NULL UNIQUE,
    log_format        log_format_type NOT NULL DEFAULT 'unknown',
    event_timestamp   TIMESTAMPTZ,
    source_ip         INET,
    destination_ip    INET,
    source_port       INTEGER CHECK (source_port BETWEEN 0 AND 65535),
    destination_port  INTEGER CHECK (destination_port BETWEEN 0 AND 65535),
    hostname          VARCHAR(255),
    username_in_log   VARCHAR(120),
    severity_raw      VARCHAR(40),
    status            pipeline_status NOT NULL DEFAULT 'pending',
    created_at        TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS analysis_results (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    log_id              UUID NOT NULL UNIQUE REFERENCES security_logs(id) ON DELETE CASCADE,
    plain_explanation   TEXT           NOT NULL,
    incident_summary    TEXT,
    severity            severity_level NOT NULL DEFAULT 'unknown',
    confidence_score    NUMERIC(5,2)   CHECK (confidence_score BETWEEN 0 AND 100),
    attack_category     VARCHAR(120),
    attack_subcategory  VARCHAR(120),
    is_false_positive   BOOLEAN,
    false_positive_reason TEXT,
    identified_ips      INET[]         NOT NULL DEFAULT '{}'::inet[],
    identified_hosts    TEXT[]         NOT NULL DEFAULT '{}'::text[],
    identified_users    TEXT[]         NOT NULL DEFAULT '{}'::text[],
    ai_model            VARCHAR(80),
    ai_raw_response     JSONB          NOT NULL DEFAULT '{}'::jsonb,
    tokens_used         INTEGER CHECK (tokens_used >= 0),
    analysis_duration_ms INTEGER CHECK (analysis_duration_ms >= 0),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mitre_techniques (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    technique_id    VARCHAR(20)  NOT NULL UNIQUE,
    name            VARCHAR(255) NOT NULL,
    tactic          VARCHAR(80)  NOT NULL,
    sub_technique   BOOLEAN      NOT NULL DEFAULT FALSE,
    parent_id       VARCHAR(20),
    description     TEXT,
    url             TEXT,
    platforms       TEXT[]       NOT NULL DEFAULT '{}'::text[],
    data_sources    TEXT[]       NOT NULL DEFAULT '{}'::text[],
    mitigations     TEXT[]       NOT NULL DEFAULT '{}'::text[],
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    last_updated    DATE,
    CONSTRAINT fk_mitre_parent
        FOREIGN KEY (parent_id) REFERENCES mitre_techniques(technique_id)
        ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE IF NOT EXISTS analysis_mitre_mappings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_id     UUID NOT NULL REFERENCES analysis_results(id) ON DELETE CASCADE,
    technique_id    UUID NOT NULL REFERENCES mitre_techniques(id) ON DELETE CASCADE,
    confidence      NUMERIC(5,2) CHECK (confidence BETWEEN 0 AND 100),
    evidence        TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_analysis_technique UNIQUE (analysis_id, technique_id)
);

CREATE TABLE IF NOT EXISTS recommended_actions (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_id       UUID NOT NULL REFERENCES analysis_results(id) ON DELETE CASCADE,
    priority          SMALLINT        NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
    category          action_category NOT NULL,
    action_text       TEXT            NOT NULL,
    rationale         TEXT,
    estimated_effort  effort_level,
    is_automated      BOOLEAN         NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS executed_actions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recommended_id      UUID REFERENCES recommended_actions(id) ON DELETE SET NULL,
    log_id              UUID REFERENCES security_logs(id) ON DELETE CASCADE,
    executed_by         UUID REFERENCES users(id) ON DELETE SET NULL,
    action_description  TEXT             NOT NULL,
    outcome             TEXT,
    status              execution_status NOT NULL DEFAULT 'pending',
    executed_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_exec_has_ref CHECK (recommended_id IS NOT NULL OR log_id IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    log_id          UUID REFERENCES security_logs(id) ON DELETE SET NULL,
    user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
    title           VARCHAR(255),
    context_summary TEXT,
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID           NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role            chat_role_type NOT NULL,
    content         TEXT           NOT NULL,
    tokens_used     INTEGER CHECK (tokens_used >= 0),
    ai_model        VARCHAR(80),
    metadata        JSONB          NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS incidents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           VARCHAR(255)   NOT NULL,
    description     TEXT,
    severity        severity_level NOT NULL DEFAULT 'unknown',
    status          incident_status NOT NULL DEFAULT 'open',
    assigned_to     UUID REFERENCES users(id) ON DELETE SET NULL,
    created_by      UUID REFERENCES users(id) ON DELETE SET NULL,
    opened_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_resolved_after_opened CHECK (resolved_at IS NULL OR resolved_at >= opened_at)
);

CREATE TABLE IF NOT EXISTS incident_logs (
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    log_id      UUID NOT NULL REFERENCES security_logs(id) ON DELETE CASCADE,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (incident_id, log_id)
);

CREATE TABLE IF NOT EXISTS analyst_notes (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    log_id      UUID REFERENCES security_logs(id) ON DELETE CASCADE,
    incident_id UUID REFERENCES incidents(id) ON DELETE CASCADE,
    author_id   UUID REFERENCES users(id) ON DELETE SET NULL,
    content     TEXT        NOT NULL,
    is_pinned   BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (log_id IS NOT NULL OR incident_id IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGSERIAL PRIMARY KEY,
    user_id     UUID REFERENCES users(id) ON DELETE SET NULL,
    action      VARCHAR(80) NOT NULL,
    table_name  VARCHAR(80),
    record_id   UUID,
    old_values  JSONB,
    new_values  JSONB,
    ip_address  INET,
    user_agent  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_logs_status           ON security_logs(status);
CREATE INDEX IF NOT EXISTS idx_logs_source           ON security_logs(source_id);
CREATE INDEX IF NOT EXISTS idx_logs_submitted_by     ON security_logs(submitted_by);
CREATE INDEX IF NOT EXISTS idx_logs_event_ts         ON security_logs(event_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_logs_source_ip        ON security_logs(source_ip);
CREATE INDEX IF NOT EXISTS idx_logs_raw_content_gin  ON security_logs USING GIN (to_tsvector('simple', raw_content));
CREATE INDEX IF NOT EXISTS idx_analysis_severity     ON analysis_results(severity);
CREATE INDEX IF NOT EXISTS idx_analysis_ai_raw_gin   ON analysis_results USING GIN (ai_raw_response);
CREATE INDEX IF NOT EXISTS idx_mitre_tactic          ON mitre_techniques(tactic);
CREATE INDEX IF NOT EXISTS idx_mitre_mapping_analysis ON analysis_mitre_mappings(analysis_id);
CREATE INDEX IF NOT EXISTS idx_rec_actions_analysis  ON recommended_actions(analysis_id);
CREATE INDEX IF NOT EXISTS idx_rec_actions_priority  ON recommended_actions(priority);
CREATE INDEX IF NOT EXISTS idx_exec_actions_log      ON executed_actions(log_id);
CREATE INDEX IF NOT EXISTS idx_exec_actions_status   ON executed_actions(status);
CREATE INDEX IF NOT EXISTS idx_chat_session_log      ON chat_sessions(log_id);
CREATE INDEX IF NOT EXISTS idx_chat_session_user     ON chat_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_msg_session_role ON chat_messages(session_id, role);
CREATE INDEX IF NOT EXISTS idx_audit_user            ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_table           ON audit_log(table_name);
CREATE INDEX IF NOT EXISTS idx_audit_ts              ON audit_log(created_at DESC);

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'users','security_logs','analysis_results',
        'executed_actions','chat_sessions','incidents','analyst_notes'
    ] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS trg_%s_updated_at ON %s', t, t);
        EXECUTE format(
            'CREATE TRIGGER trg_%s_updated_at
             BEFORE UPDATE ON %s
             FOR EACH ROW EXECUTE FUNCTION set_updated_at()',
            t, t
        );
    END LOOP;
END $$;

CREATE OR REPLACE FUNCTION set_log_hash()
RETURNS TRIGGER AS $$
BEGIN
    NEW.content_hash := encode(digest(NEW.raw_content, 'sha256'), 'hex');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_set_log_hash ON security_logs;
CREATE TRIGGER trg_set_log_hash
BEFORE INSERT OR UPDATE OF raw_content ON security_logs
FOR EACH ROW EXECUTE FUNCTION set_log_hash();

CREATE OR REPLACE FUNCTION upsert_security_log(
    p_raw_content   TEXT,
    p_source_id     UUID    DEFAULT NULL,
    p_submitted_by  UUID    DEFAULT NULL,
    p_log_format    log_format_type DEFAULT 'unknown',
    p_event_ts      TIMESTAMPTZ DEFAULT NULL,
    p_source_ip     INET    DEFAULT NULL,
    p_dest_ip       INET    DEFAULT NULL
)
RETURNS TABLE (log_id UUID, is_duplicate BOOLEAN) AS $$
DECLARE
    v_hash TEXT;
BEGIN
    v_hash := encode(digest(p_raw_content, 'sha256'), 'hex');

    INSERT INTO security_logs (
        raw_content, content_hash, source_id, submitted_by,
        log_format, event_timestamp, source_ip, destination_ip
    )
    VALUES (
        p_raw_content, v_hash, p_source_id, p_submitted_by,
        p_log_format, p_event_ts, p_source_ip, p_dest_ip
    )
    ON CONFLICT (content_hash) DO NOTHING
    RETURNING id INTO log_id;

    IF log_id IS NULL THEN
        SELECT id INTO log_id FROM security_logs WHERE content_hash = v_hash;
        RETURN QUERY SELECT log_id, TRUE;
    ELSE
        RETURN QUERY SELECT log_id, FALSE;
    END IF;
END;
$$ LANGUAGE plpgsql;

INSERT INTO mitre_techniques
    (technique_id, name, tactic, sub_technique, parent_id, description, url, platforms)
VALUES
    ('T1110', 'Brute Force', 'Credential Access', FALSE, NULL,
     'Adversaries may use brute force to gain access.',
     'https://attack.mitre.org/techniques/T1110', ARRAY['Windows','Linux','macOS','Cloud']),
    ('T1110.001', 'Password Guessing', 'Credential Access', TRUE, 'T1110',
     'Attackers guess credentials without prior knowledge.',
     'https://attack.mitre.org/techniques/T1110/001', ARRAY['Windows','Linux','macOS']),
    ('T1059', 'Command and Scripting Interpreter', 'Execution', FALSE, NULL,
     'Abuse of command-line interfaces and scripting languages.',
     'https://attack.mitre.org/techniques/T1059', ARRAY['Windows','Linux','macOS']),
    ('T1059.001', 'PowerShell', 'Execution', TRUE, 'T1059',
     'Malicious use of PowerShell.',
     'https://attack.mitre.org/techniques/T1059/001', ARRAY['Windows']),
    ('T1566', 'Phishing', 'Initial Access', FALSE, NULL,
     'Spear phishing messages to gain access.',
     'https://attack.mitre.org/techniques/T1566', ARRAY['Windows','Linux','macOS'])
ON CONFLICT (technique_id) DO NOTHING;

INSERT INTO log_sources (name, source_type, description)
VALUES
    ('Manual Upload', 'manual', 'Logs subidos manualmente por analistas'),
    ('Firewall-Core', 'firewall', 'Firewall perimetral principal'),
    ('EDR-Endpoints', 'endpoint', 'Agente EDR en endpoints corporativos'),
    ('SIEM-Central', 'siem', 'SIEM centralizado')
ON CONFLICT (name) DO NOTHING;

CREATE OR REPLACE VIEW v_log_analysis_overview AS
SELECT
    sl.id AS log_id,
    sl.status,
    sl.raw_content,
    sl.event_timestamp,
    sl.source_ip,
    sl.destination_ip,
    sl.created_at AS submitted_at,
    ar.severity,
    ar.plain_explanation,
    ar.attack_category,
    ar.confidence_score,
    ar.is_false_positive,
    array_agg(DISTINCT mt.technique_id) FILTER (WHERE mt.technique_id IS NOT NULL) AS mitre_technique_ids,
    array_agg(DISTINCT mt.name) FILTER (WHERE mt.name IS NOT NULL) AS mitre_technique_names
FROM security_logs sl
LEFT JOIN analysis_results ar ON ar.log_id = sl.id
LEFT JOIN analysis_mitre_mappings amm ON amm.analysis_id = ar.id
LEFT JOIN mitre_techniques mt ON mt.id = amm.technique_id
GROUP BY sl.id, ar.id;

CREATE OR REPLACE VIEW v_threat_stats_by_tactic AS
SELECT
    mt.tactic,
    COUNT(DISTINCT amm.analysis_id) AS detections,
    ROUND(AVG(ar.confidence_score), 1) AS avg_confidence,
    COUNT(DISTINCT CASE WHEN ar.severity = 'critical' THEN amm.analysis_id END) AS critical_count
FROM mitre_techniques mt
JOIN analysis_mitre_mappings amm ON amm.technique_id = mt.id
JOIN analysis_results ar ON ar.id = amm.analysis_id
GROUP BY mt.tactic
ORDER BY detections DESC;

CREATE OR REPLACE VIEW v_open_incidents_summary AS
SELECT
    i.id, i.title, i.severity, i.status,
    u.username AS assigned_to,
    COUNT(il.log_id) AS log_count,
    i.opened_at,
    NOW() - i.opened_at AS age
FROM incidents i
LEFT JOIN users u ON u.id = i.assigned_to
LEFT JOIN incident_logs il ON il.incident_id = i.id
WHERE i.status NOT IN ('resolved', 'closed')
GROUP BY i.id, u.username
ORDER BY
    CASE i.severity
        WHEN 'critical' THEN 1 WHEN 'high' THEN 2
        WHEN 'medium' THEN 3 WHEN 'low' THEN 4 ELSE 5
    END,
    i.opened_at;

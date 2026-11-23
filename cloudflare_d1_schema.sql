-- ============================================================
-- LUMINA AI — D1 VERİTABANI ŞEMA TASARIMI
-- cloudflare_d1_schema.sql
--
-- Mevcut yerel JSON depolama (lumina_memory.json) için D1 karşılığı.
-- Bu şema yalnızca tasarım aşamasındadır — henüz uygulanmamıştır.
--
-- Kullanım: npx wrangler d1 execute lumina-db --file=cloudflare_d1_schema.sql
-- ============================================================

-- ============================================================
-- KULLANICI PROFİLLERİ
-- Mevcut: lumina_memory.json > "profiles" > {uid: profile_dict}
-- ============================================================
CREATE TABLE IF NOT EXISTS profiles (
    uid                      TEXT    PRIMARY KEY,
    name                     TEXT,
    email                    TEXT,
    subscription_tier        TEXT    NOT NULL DEFAULT 'standart',
    subscription_status      TEXT    NOT NULL DEFAULT 'active',
    subscription_inherited_from TEXT,
    created_at               INTEGER NOT NULL,
    updated_at               INTEGER NOT NULL,
    -- Özel plan yapılandırması (JSON)
    custom_plan_config       TEXT,
    -- Aile üyeleri listesi (JSON array)
    family_members           TEXT    DEFAULT '[]',
    -- Abonelik olay geçmişi (JSON array, son 100)
    subscription_events      TEXT    DEFAULT '[]',
    -- Kullanıcı hafıza bilgisi (JSON array)
    facts                    TEXT    DEFAULT '[]'
);

-- ============================================================
-- GÜNLÜK KULLANIM KOTASI
-- Mevcut: profile["daily_usage"] = {date, messages, images}
-- ============================================================
CREATE TABLE IF NOT EXISTS daily_usage (
    uid          TEXT    NOT NULL,
    date         TEXT    NOT NULL,  -- "YYYY-MM-DD" formatı
    messages     INTEGER NOT NULL DEFAULT 0,
    images       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (uid, date)
);

-- ============================================================
-- SOHBET GEÇMİŞİ
-- Mevcut: lumina_memory.json > {uid: [{user, bot, timestamp}, ...]}
-- ============================================================
CREATE TABLE IF NOT EXISTS chat_history (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    uid              TEXT    NOT NULL,
    conversation_id  TEXT,
    user_message     TEXT    NOT NULL,
    bot_response     TEXT    NOT NULL,
    timestamp        INTEGER NOT NULL,
    created_at       INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE INDEX IF NOT EXISTS idx_chat_history_uid ON chat_history(uid, timestamp DESC);

-- ============================================================
-- GROQ API ANAHTAR ATAMASI
-- Mevcut: api_allocation.py + lumina_memory.json > "api_assignments"
-- ============================================================
CREATE TABLE IF NOT EXISTS api_assignments (
    uid        TEXT    PRIMARY KEY,
    key_id     TEXT    NOT NULL,
    assigned_at INTEGER NOT NULL,
    fails      INTEGER NOT NULL DEFAULT 0
);

-- ============================================================
-- KONUM TERCİHLERİ
-- Mevcut: location_permission_service.py (bellekte)
-- ============================================================
CREATE TABLE IF NOT EXISTS location_preferences (
    uid              TEXT    PRIMARY KEY,
    permission_state TEXT    NOT NULL DEFAULT 'unset',  -- unset|granted|denied|manual|off
    manual_city      TEXT,
    manual_lat       REAL,
    manual_lon       REAL,
    updated_at       INTEGER NOT NULL DEFAULT (unixepoch())
);

-- ============================================================
-- SES TERCİHLERİ
-- Mevcut: main.py > /api/v1/voice/preference endpoint'i
-- ============================================================
CREATE TABLE IF NOT EXISTS voice_preferences (
    uid        TEXT    PRIMARY KEY,
    voice_id   TEXT    NOT NULL,
    updated_at INTEGER NOT NULL DEFAULT (unixepoch())
);

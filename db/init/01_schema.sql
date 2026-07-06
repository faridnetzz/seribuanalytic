-- =====================================================================
-- SIGAP — Skema database analitik CCTV Bandar Lampung
-- Dijalankan otomatis oleh entrypoint PostgreSQL saat container pertama.
-- =====================================================================

SET timezone = 'Asia/Jakarta';

-- ---------------------------------------------------------------------
-- Referensi: modul analitik AI
-- ---------------------------------------------------------------------
CREATE TABLE modules (
    code        TEXT PRIMARY KEY,            -- pedestrian | waste | water | parking
    name        TEXT NOT NULL,
    description TEXT,
    accent      TEXT,                         -- warna aksen untuk UI
    model_name  TEXT,                         -- nama model inferensi
    accuracy    NUMERIC(5,2),                 -- akurasi model (%)
    enabled     BOOLEAN NOT NULL DEFAULT TRUE
);

-- ---------------------------------------------------------------------
-- Kamera CCTV (titik pengawasan)
-- ---------------------------------------------------------------------
CREATE TABLE cameras (
    id          TEXT PRIMARY KEY,            -- CAM-01 ...
    name        TEXT NOT NULL,
    area        TEXT,                         -- kelurahan / kawasan
    lat         DOUBLE PRECISION,
    lng         DOUBLE PRECISION,
    rtsp_url    TEXT,
    -- modul aktif pada kamera ini, mis. {pedestrian,parking}
    modules     TEXT[] NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'online',  -- online | offline | degraded
    last_seen   TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- Log event mentah (semua modul) — sumber kebenaran untuk agregasi
-- payload menyimpan field spesifik modul (lihat tabel turunan).
-- ---------------------------------------------------------------------
CREATE TABLE detection_events (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    camera_id   TEXT NOT NULL REFERENCES cameras(id),
    module      TEXT NOT NULL REFERENCES modules(code),
    event_type  TEXT NOT NULL,                -- detection | violation | reading | track
    confidence  NUMERIC(4,3),
    payload     JSONB NOT NULL DEFAULT '{}',
    ts          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_events_ts        ON detection_events (ts DESC);
CREATE INDEX idx_events_module_ts ON detection_events (module, ts DESC);
CREATE INDEX idx_events_camera_ts ON detection_events (camera_id, ts DESC);
CREATE INDEX idx_events_payload   ON detection_events USING GIN (payload);

-- ---------------------------------------------------------------------
-- MODUL 1 — Pedestrian Attribute Recognition + Re-ID tracking
-- ---------------------------------------------------------------------
CREATE TABLE pedestrian_tracks (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    track_id    BIGINT NOT NULL,             -- ID lokal tracker per kamera
    global_id   BIGINT,                       -- ID lintas-kamera (ReID), NULL bila belum match
    camera_id   TEXT NOT NULL REFERENCES cameras(id),
    -- 11 atribut PAR: gender, age_group, upper_color, lower_color,
    -- helmet, bag, footwear, rider, glasses, hat, sleeve ...
    attributes  JSONB NOT NULL DEFAULT '{}',
    bbox        JSONB,                        -- {x,y,w,h} ternormalisasi 0..1
    par_score   NUMERIC(4,3),
    reid_score  NUMERIC(4,3),
    first_seen  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_ped_camera   ON pedestrian_tracks (camera_id, last_seen DESC);
CREATE INDEX idx_ped_global   ON pedestrian_tracks (global_id);
CREATE UNIQUE INDEX idx_ped_track_cam ON pedestrian_tracks (camera_id, track_id);

-- ---------------------------------------------------------------------
-- MODUL 2 — Deteksi sampah (segmentasi)
-- ---------------------------------------------------------------------
CREATE TABLE waste_detections (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    camera_id     TEXT NOT NULL REFERENCES cameras(id),
    severity      TEXT NOT NULL DEFAULT 'low',  -- low | medium | high | critical
    volume_level  TEXT,                          -- kecil | sedang | besar
    area_ratio    NUMERIC(5,4),                  -- proporsi area frame tersegmentasi
    bbox          JSONB,
    is_floating   BOOLEAN DEFAULT FALSE,         -- sampah mengambang di sungai
    snapshot_url  TEXT,
    confidence    NUMERIC(4,3),
    ts            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_waste_camera_ts ON waste_detections (camera_id, ts DESC);
CREATE INDEX idx_waste_severity  ON waste_detections (severity, ts DESC);

-- Tumpukan sampah sbg EPISODE (occupancy spasial): 1 baris = 1 tumpukan dari muncul
-- s/d diangkut. Sumber persistensi, status kebersihan, alert "belum diangkut", SLA,
-- heatmap jam, ranking. Upsert per pile_uid (= sid foto).
CREATE TABLE waste_piles (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    camera_id     TEXT NOT NULL REFERENCES cameras(id),
    pile_uid      TEXT UNIQUE,
    severity      TEXT,
    area_ratio    NUMERIC(5,4),
    bbox          JSONB,
    snapshot_url  TEXT,
    status        TEXT NOT NULL DEFAULT 'active',   -- active | cleared
    reported      BOOLEAN NOT NULL DEFAULT false,
    alerted       BOOLEAN NOT NULL DEFAULT false,
    first_seen    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen     TIMESTAMPTZ NOT NULL DEFAULT now(),
    cleared_at    TIMESTAMPTZ,
    duration_seconds INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_waste_piles_cam    ON waste_piles (camera_id, first_seen DESC);
CREATE INDEX idx_waste_piles_status ON waste_piles (status, last_seen DESC);

-- ---------------------------------------------------------------------
-- MODUL 3 — Debit air sungai (virtual staff gauge)
-- ---------------------------------------------------------------------
CREATE TABLE water_levels (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    camera_id       TEXT NOT NULL REFERENCES cameras(id),
    level_m         NUMERIC(5,3) NOT NULL,        -- ketinggian air (meter)
    status          TEXT NOT NULL DEFAULT 'aman',  -- aman | waspada | siaga | bahaya
    trend_cm_30min  NUMERIC(6,2),                  -- perubahan 30 menit terakhir (cm)
    flow_estimate   NUMERIC(8,2),                  -- estimasi debit (m3/s), opsional
    confidence      NUMERIC(4,3),
    ts              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_water_camera_ts ON water_levels (camera_id, ts DESC);

-- ---------------------------------------------------------------------
-- MODUL 4 — Deteksi parkir liar (zona + dwell time)
-- ---------------------------------------------------------------------
CREATE TABLE parking_zones (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    camera_id   TEXT NOT NULL REFERENCES cameras(id),
    name        TEXT NOT NULL,                 -- "Dilarang Parkir", "Marka Kuning"
    polygon     JSONB NOT NULL,                -- [[x,y],...] ternormalisasi 0..1
    dwell_limit_s INTEGER NOT NULL DEFAULT 300 -- ambang pelanggaran (detik)
);

CREATE TABLE parking_violations (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    camera_id     TEXT NOT NULL REFERENCES cameras(id),
    zone_id       BIGINT REFERENCES parking_zones(id),
    zone_name     TEXT,
    track_id      BIGINT,                        -- ID tracker kendaraan (referensi)
    violation_uid TEXT UNIQUE,                   -- kunci 1 pelanggaran (= sid snapshot); upsert heartbeat
    vehicle_type  TEXT,                          -- motor | mobil | pickup | truk
    plate         TEXT,                          -- opsional (LPR)
    dwell_seconds INTEGER NOT NULL DEFAULT 0,
    bbox          JSONB,
    status        TEXT NOT NULL DEFAULT 'active', -- active | cleared
    snapshot_url  TEXT,                          -- = sid snapshot (foto /snap-img/<sid>)
    confidence    NUMERIC(4,3),
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    ts            TIMESTAMPTZ NOT NULL DEFAULT now()  -- update terakhir (heartbeat) -> deteksi "aktif"
);
CREATE INDEX idx_park_camera_ts ON parking_violations (camera_id, ts DESC);
CREATE INDEX idx_park_status    ON parking_violations (status, ts DESC);

-- ---------------------------------------------------------------------
-- Alert lintas-modul (umpan notifikasi dashboard)
-- ---------------------------------------------------------------------
CREATE TABLE alerts (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    module        TEXT NOT NULL REFERENCES modules(code),
    camera_id     TEXT REFERENCES cameras(id),
    severity      TEXT NOT NULL DEFAULT 'info', -- info | warn | crit
    title         TEXT NOT NULL,
    meta          JSONB NOT NULL DEFAULT '[]',  -- ["CAM-01 · Pasar", "Durasi 6 mnt"]
    event_id      BIGINT,                        -- referensi ke detection_events.id
    acknowledged  BOOLEAN NOT NULL DEFAULT FALSE,
    acknowledged_by TEXT,
    ts            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_alerts_ts       ON alerts (ts DESC);
CREATE INDEX idx_alerts_sev_ts   ON alerts (severity, ts DESC);
CREATE INDEX idx_alerts_ack      ON alerts (acknowledged, ts DESC);

-- ---------------------------------------------------------------------
-- VIEW — agregasi per jam (dipakai chart "Volume Deteksi per Jam")
-- ---------------------------------------------------------------------
CREATE VIEW v_hourly_volume AS
SELECT
    date_trunc('hour', ts) AS hour,
    module,
    count(*)               AS total
FROM detection_events
GROUP BY 1, 2;

-- VIEW — kontribusi per modul hari ini (donut chart)
CREATE VIEW v_module_contribution_today AS
SELECT
    module,
    count(*) AS total
FROM detection_events
WHERE ts >= date_trunc('day', now())
GROUP BY module;

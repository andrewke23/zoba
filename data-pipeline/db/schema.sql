-- Zoba data layer schema (PostgreSQL 16 + PostGIS)
-- Run: psql "$DATABASE_URL" -f db/schema.sql

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()

-- ---------------------------------------------------------------------------
-- Place catalog (owned by the data pipeline)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS city (
    city_id     TEXT PRIMARY KEY,                -- e.g. 'chicago'
    name        TEXT NOT NULL,
    bbox        GEOMETRY(Polygon, 4326) NOT NULL,
    timezone    TEXT NOT NULL                    -- IANA, e.g. 'America/Chicago'
);

-- One canonical row per real-world place, after entity resolution.
CREATE TABLE IF NOT EXISTS destination (
    destination_id      UUID PRIMARY KEY,
    city_id             TEXT NOT NULL REFERENCES city(city_id),
    name                TEXT NOT NULL,
    geom                GEOGRAPHY(Point, 4326) NOT NULL,
    category            TEXT NOT NULL,           -- Zoba taxonomy (pipeline/categories.py)
    address             TEXT,
    website             TEXT,
    phone               TEXT,
    wikidata_id         TEXT,
    description         TEXT,                    -- Wikivoyage/Wikidata (later)
    admission_cost_usd  NUMERIC(8,2),            -- F16; NULL = unknown
    est_duration_min    INTEGER,                 -- F14 prior; NULL = use category default
    hours_raw           TEXT,                    -- original opening_hours string
    hours_status        TEXT NOT NULL DEFAULT 'missing'
                        CHECK (hours_status IN ('ok','partial','unparseable','missing')),
    curated             BOOLEAN NOT NULL DEFAULT FALSE,  -- hand-checked seed record
    field_sources       JSONB NOT NULL DEFAULT '{}',     -- {"name":"osm","category":"fsq",...}
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS destination_geom_idx ON destination USING GIST (geom);
CREATE INDEX IF NOT EXISTS destination_city_cat_idx ON destination (city_id, category);

-- Raw source records and which canonical destination they resolved to.
CREATE TABLE IF NOT EXISTS destination_source (
    source          TEXT NOT NULL,               -- 'osm' | 'fsq' | 'wikidata'
    source_id       TEXT NOT NULL,
    destination_id  UUID REFERENCES destination(destination_id) ON DELETE SET NULL,
    match_score     REAL,                        -- score that merged it (NULL for cluster seed)
    raw             JSONB NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, source_id)
);

-- Parsed weekly hours. weekday: 0=Mon..6=Sun. Minutes since local midnight.
-- close_min may exceed 1440 for windows that run past midnight (e.g. 18:00-02:00 -> 1080..1560).
CREATE TABLE IF NOT EXISTS destination_hours (
    destination_id  UUID NOT NULL REFERENCES destination(destination_id) ON DELETE CASCADE,
    weekday         SMALLINT NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    open_min        SMALLINT NOT NULL CHECK (open_min BETWEEN 0 AND 1440),
    close_min       SMALLINT NOT NULL CHECK (close_min > open_min AND close_min <= 2880),
    PRIMARY KEY (destination_id, weekday, open_min)
);

-- Cached travel times (OSRM / OTP), consumed by the solver.
CREATE TABLE IF NOT EXISTS travel_time (
    origin_id       UUID NOT NULL REFERENCES destination(destination_id) ON DELETE CASCADE,
    dest_id         UUID NOT NULL REFERENCES destination(destination_id) ON DELETE CASCADE,
    mode            TEXT NOT NULL CHECK (mode IN ('drive','walk','transit')),
    seconds         INTEGER NOT NULL,
    meters          INTEGER,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (origin_id, dest_id, mode)
);

-- ---------------------------------------------------------------------------
-- App entities (SRS 4.3) — shared with the rest of the team; adjust as needed
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS app_user (
    user_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS trip (
    trip_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organizer_id    UUID NOT NULL REFERENCES app_user(user_id),
    city_id         TEXT NOT NULL REFERENCES city(city_id),
    name            TEXT NOT NULL DEFAULT '',       -- app column (backend startup migration on old volumes)
    start_date      DATE NOT NULL,
    end_date        DATE NOT NULL CHECK (end_date >= start_date),
    day_start       TIME NOT NULL,
    day_end         TIME NOT NULL CHECK (day_end > day_start),
    home_base       GEOGRAPHY(Point, 4326) NOT NULL,
    home_base_label TEXT NOT NULL DEFAULT '',       -- app column (backend startup migration on old volumes)
    invite_token    TEXT UNIQUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS membership (
    trip_id         UUID NOT NULL REFERENCES trip(trip_id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES app_user(user_id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('organizer','member')),
    status          TEXT NOT NULL DEFAULT 'invited' CHECK (status IN ('invited','joined','left')),
    PRIMARY KEY (trip_id, user_id)
);

CREATE TABLE IF NOT EXISTS preference (
    trip_id         UUID NOT NULL,
    user_id         UUID NOT NULL,
    destination_id  UUID NOT NULL REFERENCES destination(destination_id),
    points          INTEGER CHECK (points >= 0),
    rank            INTEGER CHECK (rank >= 1),
    hard_no         BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (trip_id, user_id, destination_id),
    FOREIGN KEY (trip_id, user_id) REFERENCES membership(trip_id, user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS comparison (
    comparison_id   BIGSERIAL PRIMARY KEY,
    trip_id         UUID NOT NULL,
    user_id         UUID NOT NULL,
    dest_a          UUID NOT NULL REFERENCES destination(destination_id),
    dest_b          UUID NOT NULL REFERENCES destination(destination_id),
    chosen          UUID NOT NULL REFERENCES destination(destination_id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (dest_a <> dest_b AND chosen IN (dest_a, dest_b)),
    FOREIGN KEY (trip_id, user_id) REFERENCES membership(trip_id, user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS itinerary_stop (
    trip_id         UUID NOT NULL REFERENCES trip(trip_id) ON DELETE CASCADE,
    day_index       SMALLINT NOT NULL,
    seq             SMALLINT NOT NULL,
    destination_id  UUID NOT NULL REFERENCES destination(destination_id),
    start_ts        TIMESTAMPTZ NOT NULL,
    end_ts          TIMESTAMPTZ NOT NULL CHECK (end_ts > start_ts),
    locked          BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (trip_id, day_index, seq)
);

CREATE TABLE IF NOT EXISTS task (
    task_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trip_id         UUID NOT NULL REFERENCES trip(trip_id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    due_date        DATE,
    status          TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','done'))
);

CREATE TABLE IF NOT EXISTS expense (
    expense_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trip_id         UUID NOT NULL REFERENCES trip(trip_id) ON DELETE CASCADE,
    payer_id        UUID NOT NULL REFERENCES app_user(user_id),
    amount_cents    INTEGER NOT NULL CHECK (amount_cents > 0),
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS expense_share (
    expense_id      UUID NOT NULL REFERENCES expense(expense_id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES app_user(user_id),
    share_cents     INTEGER NOT NULL CHECK (share_cents >= 0),
    PRIMARY KEY (expense_id, user_id)
);

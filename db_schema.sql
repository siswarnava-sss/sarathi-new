CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS government_schemes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'All',
    gender TEXT NOT NULL DEFAULT 'All',
    age_min INTEGER NOT NULL DEFAULT 0,
    age_max INTEGER NOT NULL DEFAULT 120,
    category TEXT[] NOT NULL DEFAULT ARRAY['General'],
    income_limit_inr INTEGER NOT NULL DEFAULT 9999999,
    apply_url TEXT NOT NULL,
    source_url TEXT,
    source_portal TEXT,
    language TEXT DEFAULT 'en',
    search_text TEXT NOT NULL,
    embedding vector(1024),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_scraped_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS government_schemes_filters_idx
ON government_schemes (state, gender, age_min, age_max, income_limit_inr);

CREATE INDEX IF NOT EXISTS government_schemes_category_idx
ON government_schemes USING GIN (category);

CREATE INDEX IF NOT EXISTS government_schemes_embedding_idx
ON government_schemes USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

CREATE TABLE IF NOT EXISTS app_users (
    username TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    profile JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ
);

-- PostgreSQL schema for the Java web catalog.
-- The Python collector may continue using its independent SQLite database.
CREATE TABLE IF NOT EXISTS opportunities (
    id TEXT PRIMARY KEY,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    location_text TEXT NOT NULL DEFAULT '',
    workplace_type TEXT,
    employment_type TEXT,
    published_at TEXT,
    canonical_url TEXT,
    updated_at TEXT NOT NULL,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS source_postings (
    source TEXT NOT NULL,
    source_job_id TEXT NOT NULL,
    opportunity_id TEXT NOT NULL REFERENCES opportunities(id),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    url TEXT,
    last_seen_at TEXT,
    PRIMARY KEY(source, source_job_id)
);
CREATE INDEX IF NOT EXISTS idx_pg_source_postings_opportunity
    ON source_postings(opportunity_id);

CREATE TABLE IF NOT EXISTS opportunity_course_scores (
    opportunity_id TEXT NOT NULL REFERENCES opportunities(id),
    course_id TEXT NOT NULL,
    score INTEGER NOT NULL CHECK(score BETWEEN 0 AND 100),
    PRIMARY KEY(opportunity_id, course_id)
);

CREATE TABLE IF NOT EXISTS opportunity_intents (
    opportunity_id TEXT NOT NULL REFERENCES opportunities(id),
    intent_id TEXT NOT NULL,
    PRIMARY KEY(opportunity_id, intent_id)
);

-- Optional supporting indexes for the large non-demo catalog.
CREATE INDEX IF NOT EXISTS idx_pg_opportunities_published
    ON opportunities(published_at DESC, updated_at DESC, id);
CREATE INDEX IF NOT EXISTS idx_pg_opportunities_location
    ON opportunities(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_pg_scores_opportunity_score
    ON opportunity_course_scores(opportunity_id, score DESC);

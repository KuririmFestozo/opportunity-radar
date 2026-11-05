-- Tables owned by the MVC module. Never alter Python collector tables.
CREATE TABLE IF NOT EXISTS web_favorites (
  id TEXT PRIMARY KEY NOT NULL,
  opportunity_id TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
);
CREATE TABLE IF NOT EXISTS web_applications (
  id TEXT PRIMARY KEY NOT NULL,
  opportunity_id TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL CHECK (status IN ('PLANNED','APPLIED','INTERVIEW','OFFER','REJECTED')),
  notes TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL,
  FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
);
CREATE INDEX IF NOT EXISTS idx_web_applications_status ON web_applications(status);


-- Performance indexes on the *dedicated MVC snapshot*, not on the collector DB.
-- Without the composite index, SQLite may choose idx_source_postings_active
-- for a correlated EXISTS and scan thousands of postings for EACH opportunity.
CREATE INDEX IF NOT EXISTS idx_web_postings_opp_active_source
  ON source_postings(opportunity_id, is_active, source);

-- Avoid a full sort of the opportunity catalog for each page.
CREATE INDEX IF NOT EXISTS idx_web_opportunities_updated
  ON opportunities(updated_at DESC);

-- The course drop-down otherwise scans/sorts all course-score rows.
CREATE INDEX IF NOT EXISTS idx_web_course_scores_course_score
  ON opportunity_course_scores(course_id, score, opportunity_id);

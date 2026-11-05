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

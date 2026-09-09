-- Optional spatial projection of persisted versioned JSON plans.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS spot_geometry (
  plan_id TEXT NOT NULL,
  spot_id TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('camera', 'entrance', 'subject')),
  location GEOGRAPHY(POINT, 4326) NOT NULL,
  precision_label TEXT NOT NULL,
  PRIMARY KEY(plan_id, spot_id, role)
);
CREATE INDEX IF NOT EXISTS spot_geometry_gist ON spot_geometry USING GIST(location);
INSERT INTO schema_migrations(version) VALUES(1) ON CONFLICT DO NOTHING;

-- ============================================================================
-- Search Typeahead System — PostgreSQL schema
-- ============================================================================
-- The `queries` table stores each distinct search query and its popularity
-- counters. The typeahead does a prefix range scan; trending reads the
-- counters; the batch writer upserts increments.

CREATE TABLE IF NOT EXISTS queries (
    id            SERIAL PRIMARY KEY,
    query         TEXT   UNIQUE NOT NULL,   -- normalised query text
    count         BIGINT NOT NULL DEFAULT 0,  -- all-time popularity
    recent_count  BIGINT NOT NULL DEFAULT 0,  -- popularity in the recent window
    last_searched TIMESTAMP WITH TIME ZONE DEFAULT now()
);

-- Prefix searches (query LIKE 'iph%') use a btree index. For large datasets a
-- text_pattern_ops index makes prefix scans index-only and case-sensitive; we
-- pair it with a lower() functional index for case-insensitive ILIKE prefix
-- matching.
CREATE INDEX IF NOT EXISTS ix_queries_query
    ON queries (query text_pattern_ops);

CREATE INDEX IF NOT EXISTS ix_queries_query_lower
    ON queries (lower(query) text_pattern_ops);

-- Trending / popularity ordering.
CREATE INDEX IF NOT EXISTS ix_queries_count
    ON queries (count DESC);

CREATE INDEX IF NOT EXISTS ix_queries_recent
    ON queries ((count + recent_count * 10) DESC);

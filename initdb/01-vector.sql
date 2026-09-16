-- Phase 2: enable pgvector. Runs on fresh init; existing volumes get the
-- extension via CREATE EXTENSION IF NOT EXISTS in database.init_db().
CREATE EXTENSION IF NOT EXISTS vector;

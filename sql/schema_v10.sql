-- Schema v10: related-item feedback (directional down-rank)

CREATE TABLE IF NOT EXISTS recommendation_feedback (
    from_raw_id  INTEGER NOT NULL REFERENCES raw_items(id) ON DELETE CASCADE,
    to_raw_id    INTEGER NOT NULL REFERENCES raw_items(id) ON DELETE CASCADE,
    action       TEXT NOT NULL DEFAULT 'less_relevant'
        CHECK (action IN ('less_relevant')),
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (from_raw_id, to_raw_id)
);

CREATE INDEX IF NOT EXISTS idx_recommendation_feedback_from
    ON recommendation_feedback (from_raw_id);

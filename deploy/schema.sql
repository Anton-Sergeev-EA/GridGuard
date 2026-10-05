CREATE TABLE IF NOT EXISTS telemetry (
    event_id text NOT NULL,
    sample_time timestamptz NOT NULL,
    payload jsonb NOT NULL,
    assessment jsonb NOT NULL,
    PRIMARY KEY (event_id, sample_time)
);

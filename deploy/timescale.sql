CREATE EXTENSION IF NOT EXISTS timescaledb;
SELECT create_hypertable('telemetry', 'sample_time', if_not_exists => TRUE);

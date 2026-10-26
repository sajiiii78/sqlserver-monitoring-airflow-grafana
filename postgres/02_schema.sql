-- Run connected to sqlmon_staging AS sqlmon_etl:
--   psql -h localhost -U sqlmon_etl -d sqlmon_staging -f 02_schema.sql
-- Column names here MUST match the column aliases in airflow/dags/sqlmon/queries/*.sql
-- (the loader inserts by column name). server_name + collected_at are added by the loader.

CREATE SCHEMA IF NOT EXISTS mon;

-- ---------- audit / run log ----------
CREATE TABLE IF NOT EXISTS mon.etl_run_log (
    id           bigserial PRIMARY KEY,
    dag_id       text,
    metric       text        NOT NULL,
    server_name  text        NOT NULL,
    collected_at timestamptz NOT NULL,      -- logical time of the run (data_interval_end)
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    status       text        NOT NULL CHECK (status IN ('RUNNING','SUCCESS','PARTIAL','FAILED')),
    rows_loaded  integer,
    attempt      integer,
    error_text   text
);
CREATE INDEX IF NOT EXISTS ix_etl_run_log_metric ON mon.etl_run_log (metric, collected_at DESC);

-- ---------- hardware / instance ----------
CREATE TABLE IF NOT EXISTS mon.cpu_usage (
    server_name text NOT NULL, collected_at timestamptz NOT NULL,
    sql_cpu_pct numeric(5,2), other_cpu_pct numeric(5,2), idle_pct numeric(5,2),
    max_sql_cpu_pct integer, samples integer, cpu_count integer
);

CREATE TABLE IF NOT EXISTS mon.memory_usage (
    server_name text NOT NULL, collected_at timestamptz NOT NULL,
    os_total_mb bigint, os_available_mb bigint, os_memory_state text,
    sql_memory_used_mb bigint, sql_memory_util_pct integer, sql_memory_low integer,
    max_server_memory_mb bigint, total_server_memory_mb bigint, target_server_memory_mb bigint,
    ple_seconds bigint
);

CREATE TABLE IF NOT EXISTS mon.disk_volume (
    server_name text NOT NULL, collected_at timestamptz NOT NULL,
    volume_mount_point text, logical_volume_name text,
    total_mb bigint, free_mb bigint, free_pct numeric(5,2)
);

CREATE TABLE IF NOT EXISTS mon.perf_counter (       -- cumulative counters: compute deltas in Grafana
    server_name text NOT NULL, collected_at timestamptz NOT NULL,
    counter_name text, cntr_value bigint
);

CREATE TABLE IF NOT EXISTS mon.wait_stats (         -- cumulative since instance start
    server_name text NOT NULL, collected_at timestamptz NOT NULL,
    wait_type text, waiting_tasks_count bigint, wait_time_ms bigint, signal_wait_time_ms bigint
);

-- ---------- databases ----------
CREATE TABLE IF NOT EXISTS mon.db_inventory (
    server_name text NOT NULL, collected_at timestamptz NOT NULL,
    db_name text, database_id integer, state_desc text, recovery_model text,
    compatibility_level integer, is_read_only integer, log_reuse_wait text,
    create_date timestamp, total_size_mb numeric(18,2), data_size_mb numeric(18,2), log_size_mb numeric(18,2),
    last_full_backup timestamp, last_log_backup timestamp
);

CREATE TABLE IF NOT EXISTS mon.db_file_usage (
    server_name text NOT NULL, collected_at timestamptz NOT NULL,
    db_name text, file_id integer, file_name text, file_type text,
    filegroup_name text, filegroup_type text, physical_name text,
    size_mb numeric(18,2), used_mb numeric(18,2), max_size_mb numeric(18,2), growth_desc text
);

CREATE TABLE IF NOT EXISTS mon.db_log_usage (
    server_name text NOT NULL, collected_at timestamptz NOT NULL,
    db_name text, total_log_mb numeric(18,2), used_log_mb numeric(18,2), used_log_pct numeric(5,2)
);

CREATE TABLE IF NOT EXISTS mon.table_usage (
    server_name text NOT NULL, collected_at timestamptz NOT NULL,
    db_name text, schema_name text, table_name text,
    row_count bigint, reserved_mb numeric(18,2), data_mb numeric(18,2), index_mb numeric(18,2)
);

CREATE TABLE IF NOT EXISTS mon.index_fragmentation (
    server_name text NOT NULL, collected_at timestamptz NOT NULL,
    db_name text, schema_name text, table_name text, index_name text, index_type text,
    page_count bigint, size_mb numeric(18,2), avg_fragmentation_pct numeric(5,2)
);

-- ---------- HA ----------
CREATE TABLE IF NOT EXISTS mon.ha_status (
    server_name text NOT NULL, collected_at timestamptz NOT NULL,
    ag_name text, replica_server_name text, role_desc text, operational_state_desc text,
    connected_state_desc text, replica_sync_health text, db_name text,
    db_sync_state text, db_sync_health text,
    log_send_queue_kb bigint, redo_queue_kb bigint, is_suspended integer
);

-- ---------- indexes (time-series access pattern) ----------
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['cpu_usage','memory_usage','disk_volume','perf_counter','wait_stats',
                           'db_inventory','db_file_usage','db_log_usage','table_usage',
                           'index_fragmentation','ha_status']
  LOOP
    EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON mon.%I (server_name, collected_at DESC)', 'ix_'||t||'_time', t);
  END LOOP;
END $$;

CREATE INDEX IF NOT EXISTS ix_db_file_usage_db ON mon.db_file_usage      (server_name, db_name, collected_at DESC);
CREATE INDEX IF NOT EXISTS ix_table_usage_db   ON mon.table_usage        (server_name, db_name, collected_at DESC);
CREATE INDEX IF NOT EXISTS ix_index_frag_db    ON mon.index_fragmentation (server_name, db_name, collected_at DESC);

-- ---------- retention ----------
CREATE OR REPLACE FUNCTION mon.purge_old(p_days integer) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['cpu_usage','memory_usage','disk_volume','perf_counter','wait_stats',
                           'db_inventory','db_file_usage','db_log_usage','table_usage',
                           'index_fragmentation','ha_status','etl_run_log']
  LOOP
    EXECUTE format('DELETE FROM mon.%I WHERE collected_at < now() - make_interval(days => %s)', t, p_days);
  END LOOP;
END $$;

-- ---------- freshness view (for the "is the pipeline alive?" panel) ----------
CREATE OR REPLACE VIEW mon.v_data_freshness AS
SELECT server_name, metric,
       max(collected_at) FILTER (WHERE status IN ('SUCCESS','PARTIAL')) AS last_ok_at,
       now() - max(collected_at) FILTER (WHERE status IN ('SUCCESS','PARTIAL')) AS age,
       count(*) FILTER (WHERE status = 'FAILED' AND started_at > now() - interval '24 hours') AS failures_24h
FROM mon.etl_run_log
GROUP BY server_name, metric;

-- ---------- Grafana read-only access ----------
GRANT USAGE ON SCHEMA mon TO grafana_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA mon TO grafana_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA mon GRANT SELECT ON TABLES TO grafana_ro;

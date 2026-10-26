-- Removes rows written by runs that started > 3 hours after their stamped time (late runs of the old
-- collector, and manual `airflow tasks test` runs with made-up dates), and flags those runs as FAILED.
DO $$
DECLARE r record; t text; n int; total int := 0;
BEGIN
  FOR r IN SELECT id, metric, server_name, collected_at FROM mon.etl_run_log
           WHERE status IN ('SUCCESS','PARTIAL') AND started_at - collected_at > interval '3 hours'
  LOOP
    t := CASE r.metric
           WHEN 'cpu' THEN 'cpu_usage'            WHEN 'memory' THEN 'memory_usage'
           WHEN 'disk_volume' THEN 'disk_volume'  WHEN 'db_inventory' THEN 'db_inventory'
           WHEN 'workload' THEN 'perf_counter'    WHEN 'waits' THEN 'wait_stats'
           WHEN 'ha' THEN 'ha_status'             WHEN 'db_files' THEN 'db_file_usage'
           WHEN 'db_log' THEN 'db_log_usage'      WHEN 'tables' THEN 'table_usage'
           WHEN 'fragmentation' THEN 'index_fragmentation' END;
    CONTINUE WHEN t IS NULL;
    EXECUTE format('DELETE FROM mon.%I WHERE server_name = $1 AND collected_at = $2', t)
      USING r.server_name, r.collected_at;
    GET DIAGNOSTICS n = ROW_COUNT; total := total + n;
    UPDATE mon.etl_run_log
       SET status = 'FAILED', error_text = 'late run: rows removed (stamped with an old time)'
     WHERE id = r.id;
  END LOOP;
  RAISE NOTICE 'removed % mislabeled rows', total;
END $$;

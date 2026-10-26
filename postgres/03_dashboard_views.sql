-- Run AS sqlmon_etl:  psql -h localhost -U sqlmon_etl -d sqlmon_staging -f 03_dashboard_views.sql
-- Alerts are COMPUTED from the latest snapshots (nothing stored): an alert "closes" by itself
-- when the condition disappears. Thresholds live in this file; the dashboard colours use the SAME numbers
-- (constants at the top of grafana/build_dashboard.py - build_dashboard.py refuses to build if they differ).

-- ---------------------------------------------------------------------------------------
-- Collection health: is the pipeline alive for each server?
-- ---------------------------------------------------------------------------------------
CREATE OR REPLACE VIEW mon.v_collection_health AS
SELECT s.server_name,
       s.last_sample_at,
       extract(epoch FROM now() - s.last_sample_at)::int      AS sample_age_seconds,
       r.last_run_status,
       COALESCE(f.runs_24h, 0)                                AS runs_24h,
       COALESCE(f.failures_24h, 0)                            AS failures_24h,
       CASE WHEN now() - s.last_sample_at > interval '35 minutes' THEN 'STALE'
            WHEN COALESCE(f.failures_1h, 0) > 0                   THEN 'DEGRADED'
            ELSE 'HEALTHY' END                                AS health_state
FROM (SELECT server_name, max(collected_at) AS last_sample_at
      FROM mon.cpu_usage GROUP BY server_name) s            -- cpu = heartbeat of the 15-minute tier
LEFT JOIN LATERAL (
      SELECT l.status AS last_run_status
      FROM mon.etl_run_log l WHERE l.server_name = s.server_name
      ORDER BY l.started_at DESC LIMIT 1) r ON true
LEFT JOIN LATERAL (
      SELECT count(*) FILTER (WHERE l.started_at > now() - interval '24 hours')                          AS runs_24h,
             count(*) FILTER (WHERE l.status = 'FAILED' AND l.started_at > now() - interval '24 hours')  AS failures_24h,
             count(*) FILTER (WHERE l.status = 'FAILED' AND l.started_at > now() - interval '1 hour')    AS failures_1h
      FROM mon.etl_run_log l WHERE l.server_name = s.server_name) f ON true;

-- ---------------------------------------------------------------------------------------
-- Active alerts (computed)
-- ---------------------------------------------------------------------------------------
CREATE OR REPLACE VIEW mon.v_active_alerts AS
-- 1. disk space: warning < 20 % free, critical < 10 %
SELECT d.server_name, d.collected_at AS alerted_at, 'Disk space low'::text AS metric_name,
       (CASE WHEN d.free_pct < 10 THEN 'critical' ELSE 'warning' END)::text AS severity,
       COALESCE(NULLIF(d.volume_mount_point, ''), 'data volume')::text AS object_name,
       format('Free space %s%% (%s GB free of %s GB)', d.free_pct,
              round(d.free_mb / 1024.0, 1), round(d.total_mb / 1024.0, 1)) AS message
FROM mon.disk_volume d
WHERE d.collected_at = (SELECT max(x.collected_at) FROM mon.disk_volume x WHERE x.server_name = d.server_name)
  AND d.free_pct < 20

UNION ALL
-- 2. CPU (SQL + other processes): average of the last 45 minutes, warning > 80 %, critical > 90 %
SELECT c.server_name, max(c.collected_at), 'CPU high',
       CASE WHEN avg(c.sql_cpu_pct + c.other_cpu_pct) > 90 THEN 'critical' ELSE 'warning' END, 'cpu',
       format('Average CPU %s%% over the last 45 minutes', round(avg(c.sql_cpu_pct + c.other_cpu_pct), 1))
FROM mon.cpu_usage c
WHERE c.collected_at > now() - interval '45 minutes'
GROUP BY c.server_name
HAVING avg(c.sql_cpu_pct + c.other_cpu_pct) > 80

UNION ALL
-- 3. memory pressure: PLE < 300 s (warning) or SQL process reports low memory (critical)
SELECT m.server_name, m.collected_at, 'Memory pressure',
       CASE WHEN m.sql_memory_low = 1 THEN 'critical' ELSE 'warning' END, 'memory',
       format('Page life expectancy %s s, process memory low = %s', m.ple_seconds, m.sql_memory_low)
FROM mon.memory_usage m
WHERE m.collected_at = (SELECT max(x.collected_at) FROM mon.memory_usage x WHERE x.server_name = m.server_name)
  AND (m.ple_seconds < 300 OR m.sql_memory_low = 1)

UNION ALL
-- 4. transaction log: warning > 80 %, critical > 90 %
SELECT l.server_name, l.collected_at, 'Log file nearly full',
       CASE WHEN l.used_log_pct > 90 THEN 'critical' ELSE 'warning' END, l.db_name,
       format('Log used %s%% of %s MB', l.used_log_pct, l.total_log_mb)
FROM mon.db_log_usage l
WHERE l.collected_at = (SELECT max(x.collected_at) FROM mon.db_log_usage x WHERE x.server_name = l.server_name)
  AND l.used_log_pct > 80

UNION ALL
-- 5. backups: no full backup, or older than 26 h (tempdb excluded).
--    NOTE: last_full_backup is SQL Server local time (no time zone); it is compared with this
--    Postgres session's local time. A few hours of offset is absorbed by the 26 h threshold.
SELECT i.server_name, i.collected_at, 'Backup too old', 'critical', i.db_name,
       CASE WHEN i.last_full_backup IS NULL THEN 'No full backup recorded'
            ELSE format('Last full backup %s hours ago',
                        round(extract(epoch FROM localtimestamp - i.last_full_backup) / 3600)) END
FROM mon.db_inventory i
WHERE i.collected_at = (SELECT max(x.collected_at) FROM mon.db_inventory x WHERE x.server_name = i.server_name)
  AND i.state_desc = 'ONLINE' AND i.db_name <> 'tempdb'
  AND (i.last_full_backup IS NULL OR i.last_full_backup < localtimestamp - interval '26 hours')

UNION ALL
-- 6. database not online
SELECT i.server_name, i.collected_at, 'Database not online', 'critical', i.db_name,
       format('State: %s', i.state_desc)
FROM mon.db_inventory i
WHERE i.collected_at = (SELECT max(x.collected_at) FROM mon.db_inventory x WHERE x.server_name = i.server_name)
  AND i.state_desc <> 'ONLINE'

UNION ALL
-- 7. Always On health
SELECT h.server_name, h.collected_at, 'Availability Group unhealthy', 'critical',
       COALESCE(h.ag_name, '') || ' / ' || COALESCE(h.replica_server_name, '') ||
       CASE WHEN h.db_name IS NULL THEN '' ELSE ' / ' || h.db_name END,
       format('Replica health: %s, DB health: %s, suspended: %s',
              h.replica_sync_health, COALESCE(h.db_sync_health, '-'), COALESCE(h.is_suspended, 0))
FROM mon.ha_status h
WHERE h.collected_at = (SELECT max(x.collected_at) FROM mon.ha_status x WHERE x.server_name = h.server_name)
  AND (COALESCE(h.replica_sync_health, 'HEALTHY') <> 'HEALTHY'
       OR (h.db_name IS NOT NULL AND COALESCE(h.db_sync_health, 'HEALTHY') <> 'HEALTHY')
       OR COALESCE(h.is_suspended, 0) = 1)

UNION ALL
-- 8. a collector stopped delivering data (stale beyond 2 intervals)
SELECT f.server_name, f.last_ok_at, 'Collection stale', 'critical', f.metric,
       format('No successful run for %s minutes', round(extract(epoch FROM f.age) / 60))
FROM mon.v_data_freshness f
WHERE f.age > CASE
        WHEN f.metric IN ('cpu','memory','disk_volume','db_inventory','workload','waits','ha') THEN interval '35 minutes'
        WHEN f.metric IN ('db_files','db_log','tables')                                        THEN interval '95 minutes'
        ELSE interval '26 hours' END;

GRANT SELECT ON mon.v_collection_health, mon.v_active_alerts TO grafana_ro;

SET NOCOUNT ON;
-- Cumulative counters (take deltas in Grafana) + a few instantaneous values.
SELECT RTRIM(counter_name) AS counter_name, cntr_value
FROM sys.dm_os_performance_counters
WHERE (object_name LIKE N'%SQL Statistics%'    AND counter_name IN (N'Batch Requests/sec', N'SQL Compilations/sec', N'SQL Re-Compilations/sec'))
   OR (object_name LIKE N'%General Statistics%' AND counter_name IN (N'User Connections', N'Processes blocked'))
   OR (object_name LIKE N'%Buffer Manager%'     AND counter_name IN (N'Page reads/sec', N'Page writes/sec', N'Lazy writes/sec'))
   OR (object_name LIKE N'%Memory Manager%'     AND counter_name = N'Memory Grants Pending')
UNION ALL
SELECT N'Active User Sessions', COUNT_BIG(*) FROM sys.dm_exec_sessions WHERE is_user_process = 1
UNION ALL
SELECT N'Blocked Requests', COUNT_BIG(*) FROM sys.dm_exec_requests WHERE blocking_session_id <> 0;

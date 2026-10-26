SET NOCOUNT ON;
-- Average SQL / other-process / idle CPU over the last 15 minutes (ring buffer holds ~1 sample per minute).
;WITH rb AS (
    SELECT [timestamp], CONVERT(xml, record) AS rec
    FROM sys.dm_os_ring_buffers
    WHERE ring_buffer_type = N'RING_BUFFER_SCHEDULER_MONITOR'
      AND record LIKE N'%<SystemHealth>%'
), s AS (
    SELECT DATEADD(ms, -1 * ((SELECT ms_ticks FROM sys.dm_os_sys_info) - [timestamp]), GETDATE()) AS event_time,
           rec.value('(./Record/SchedulerMonitorEvent/SystemHealth/ProcessUtilization)[1]', 'int') AS sql_cpu,
           rec.value('(./Record/SchedulerMonitorEvent/SystemHealth/SystemIdle)[1]', 'int')        AS idle
    FROM rb
)
SELECT CAST(AVG(sql_cpu * 1.0)             AS decimal(5,2)) AS sql_cpu_pct,
       CAST(AVG((100 - sql_cpu - idle) * 1.0) AS decimal(5,2)) AS other_cpu_pct,
       CAST(AVG(idle * 1.0)                AS decimal(5,2)) AS idle_pct,
       MAX(sql_cpu)                                         AS max_sql_cpu_pct,
       COUNT(*)                                             AS samples,
       (SELECT cpu_count FROM sys.dm_os_sys_info)           AS cpu_count
FROM s
WHERE event_time >= DATEADD(MINUTE, -15, GETDATE());

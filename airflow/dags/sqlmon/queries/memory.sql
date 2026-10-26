SET NOCOUNT ON;
SELECT
    sm.total_physical_memory_kb     / 1024 AS os_total_mb,
    sm.available_physical_memory_kb / 1024 AS os_available_mb,
    sm.system_memory_state_desc            AS os_memory_state,
    pm.physical_memory_in_use_kb    / 1024 AS sql_memory_used_mb,
    pm.memory_utilization_percentage       AS sql_memory_util_pct,
    CAST(pm.process_physical_memory_low AS int) AS sql_memory_low,
    (SELECT CAST(value_in_use AS bigint) FROM sys.configurations WHERE name = N'max server memory (MB)') AS max_server_memory_mb,
    (SELECT TOP (1) cntr_value / 1024 FROM sys.dm_os_performance_counters WHERE counter_name = N'Total Server Memory (KB)') AS total_server_memory_mb,
    (SELECT TOP (1) cntr_value / 1024 FROM sys.dm_os_performance_counters WHERE counter_name = N'Target Server Memory (KB)') AS target_server_memory_mb,
    (SELECT TOP (1) cntr_value FROM sys.dm_os_performance_counters
      WHERE counter_name = N'Page life expectancy' AND object_name LIKE N'%Buffer Manager%') AS ple_seconds
FROM sys.dm_os_sys_memory AS sm
CROSS JOIN sys.dm_os_process_memory AS pm;

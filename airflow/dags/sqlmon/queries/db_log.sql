SET NOCOUNT ON;
SELECT
    DB_NAME() AS db_name,
    CAST(total_log_size_in_bytes / 1048576.0 AS decimal(18,2)) AS total_log_mb,
    CAST(used_log_space_in_bytes / 1048576.0 AS decimal(18,2)) AS used_log_mb,
    CAST(used_log_space_in_percent AS decimal(5,2))            AS used_log_pct
FROM sys.dm_db_log_space_usage;

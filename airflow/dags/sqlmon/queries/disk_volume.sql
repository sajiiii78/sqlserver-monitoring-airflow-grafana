SET NOCOUNT ON;
-- Free space of every volume that hosts at least one database file.
SELECT DISTINCT
    vs.volume_mount_point,
    vs.logical_volume_name,
    vs.total_bytes     / 1048576 AS total_mb,
    vs.available_bytes / 1048576 AS free_mb,
    CAST(vs.available_bytes * 100.0 / NULLIF(vs.total_bytes, 0) AS decimal(5,2)) AS free_pct
FROM sys.master_files AS mf
CROSS APPLY sys.dm_os_volume_stats(mf.database_id, mf.file_id) AS vs;

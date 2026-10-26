SET NOCOUNT ON;
-- HEAVY: run off-peak (daily). LIMITED mode, skip tiny indexes, keep the 200 worst per database.
SELECT TOP (200)
    DB_NAME()                               AS db_name,
    OBJECT_SCHEMA_NAME(ips.object_id)       AS schema_name,
    OBJECT_NAME(ips.object_id)              AS table_name,
    i.name                                  AS index_name,
    i.type_desc                             AS index_type,
    ips.page_count,
    CAST(ips.page_count * 8 / 1024.0 AS decimal(18,2))          AS size_mb,
    CAST(ips.avg_fragmentation_in_percent AS decimal(5,2))      AS avg_fragmentation_pct
FROM sys.dm_db_index_physical_stats(DB_ID(), NULL, NULL, NULL, 'LIMITED') AS ips
JOIN sys.indexes AS i ON i.object_id = ips.object_id AND i.index_id = ips.index_id
WHERE ips.index_id > 0
  AND ips.page_count >= 1000
  AND ips.alloc_unit_type_desc = 'IN_ROW_DATA'
ORDER BY ips.avg_fragmentation_in_percent DESC;

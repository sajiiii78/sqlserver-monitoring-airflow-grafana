SET NOCOUNT ON;
-- Top 100 tables per database by reserved space (bounds the row volume in Postgres).
SELECT TOP (100)
    DB_NAME()  AS db_name,
    s.name     AS schema_name,
    t.name     AS table_name,
    SUM(CASE WHEN ps.index_id IN (0, 1) THEN ps.row_count ELSE 0 END) AS row_count,
    CAST(SUM(ps.reserved_page_count) * 8 / 1024.0 AS decimal(18,2))   AS reserved_mb,
    CAST(SUM(CASE WHEN ps.index_id IN (0, 1)
                  THEN ps.in_row_data_page_count + ps.lob_used_page_count + ps.row_overflow_used_page_count
                  ELSE 0 END) * 8 / 1024.0 AS decimal(18,2))          AS data_mb,
    CAST((SUM(ps.used_page_count) - SUM(CASE WHEN ps.index_id IN (0, 1)
                  THEN ps.in_row_data_page_count + ps.lob_used_page_count + ps.row_overflow_used_page_count
                  ELSE 0 END)) * 8 / 1024.0 AS decimal(18,2))         AS index_mb
FROM sys.dm_db_partition_stats AS ps
JOIN sys.tables  AS t ON t.object_id = ps.object_id
JOIN sys.schemas AS s ON s.schema_id = t.schema_id
WHERE t.is_ms_shipped = 0
GROUP BY s.name, t.name
ORDER BY SUM(ps.reserved_page_count) DESC;

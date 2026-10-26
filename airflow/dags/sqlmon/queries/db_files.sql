SET NOCOUNT ON;
-- Files, filegroups (incl. FILESTREAM filegroups), allocated vs used space.
SELECT
    DB_NAME()                         AS db_name,
    f.file_id,
    f.name                            AS file_name,
    f.type_desc                       AS file_type,
    COALESCE(fg.name, N'(log)')       AS filegroup_name,
    fg.type_desc                      AS filegroup_type,
    f.physical_name,
    CAST(CAST(f.size AS bigint) * 8 / 1024.0 AS decimal(18,2))                          AS size_mb,
    CAST(CAST(FILEPROPERTY(f.name, 'SpaceUsed') AS bigint) * 8 / 1024.0 AS decimal(18,2)) AS used_mb,
    CASE WHEN f.max_size IN (-1, 268435456) THEN NULL
         ELSE CAST(CAST(f.max_size AS bigint) * 8 / 1024.0 AS decimal(18,2)) END        AS max_size_mb,
    CASE WHEN f.is_percent_growth = 1 THEN CAST(f.growth AS varchar(10)) + '%'
         ELSE CAST(CAST(f.growth AS bigint) * 8 / 1024 AS varchar(20)) + ' MB' END      AS growth_desc
FROM sys.database_files AS f
LEFT JOIN sys.filegroups AS fg ON fg.data_space_id = f.data_space_id;

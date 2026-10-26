SET NOCOUNT ON;
-- One row per database: state, recovery model, size, last backups.
SELECT
    d.name                              AS db_name,
    d.database_id,
    d.state_desc,
    d.recovery_model_desc               AS recovery_model,
    d.compatibility_level,
    CAST(d.is_read_only AS int)         AS is_read_only,
    d.log_reuse_wait_desc               AS log_reuse_wait,
    d.create_date,
    CAST((SELECT SUM(CAST(mf.size AS bigint)) FROM sys.master_files mf WHERE mf.database_id = d.database_id) * 8 / 1024.0 AS decimal(18,2)) AS total_size_mb,
    CAST((SELECT SUM(CAST(mf.size AS bigint)) FROM sys.master_files mf WHERE mf.database_id = d.database_id AND mf.type = 0) * 8 / 1024.0 AS decimal(18,2)) AS data_size_mb,
    CAST((SELECT SUM(CAST(mf.size AS bigint)) FROM sys.master_files mf WHERE mf.database_id = d.database_id AND mf.type = 1) * 8 / 1024.0 AS decimal(18,2)) AS log_size_mb,
    (SELECT MAX(b.backup_finish_date) FROM msdb.dbo.backupset b
      WHERE b.database_name = d.name COLLATE DATABASE_DEFAULT AND b.type = 'D') AS last_full_backup,
    (SELECT MAX(b.backup_finish_date) FROM msdb.dbo.backupset b
      WHERE b.database_name = d.name COLLATE DATABASE_DEFAULT AND b.type = 'L') AS last_log_backup
FROM sys.databases AS d;

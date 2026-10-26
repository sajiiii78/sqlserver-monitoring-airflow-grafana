SET NOCOUNT ON;
-- Always On Availability Groups. Returns 0 rows on instances without AGs (that is fine).
SELECT
    ag.name                                AS ag_name,
    ar.replica_server_name,
    ars.role_desc,
    ars.operational_state_desc,
    ars.connected_state_desc,
    ars.synchronization_health_desc        AS replica_sync_health,
    DB_NAME(drs.database_id)               AS db_name,
    drs.synchronization_state_desc         AS db_sync_state,
    drs.synchronization_health_desc        AS db_sync_health,
    drs.log_send_queue_size                AS log_send_queue_kb,
    drs.redo_queue_size                    AS redo_queue_kb,
    CAST(drs.is_suspended AS int)          AS is_suspended
FROM sys.availability_groups AS ag
JOIN sys.availability_replicas AS ar ON ar.group_id = ag.group_id
JOIN sys.dm_hadr_availability_replica_states AS ars ON ars.replica_id = ar.replica_id
LEFT JOIN sys.dm_hadr_database_replica_states AS drs
       ON drs.replica_id = ars.replica_id AND drs.group_id = ars.group_id;

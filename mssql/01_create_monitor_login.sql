-- Creates (or repairs) the read-only monitoring login. Safe to run repeatedly.
--
-- sqlcmd : sqlcmd -S <server> -U <admin> -P '<password>' -C -v MONITOR_PASSWORD='<strong password>' -i mssql/01_create_monitor_login.sql
-- SSMS   : enable  Query > SQLCMD Mode  and put  :setvar MONITOR_PASSWORD "<strong password>"  on the first line.
--
-- Do not use a single quote (') in the password. On production servers use CHECK_POLICY = ON.
USE master;
GO
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'sqlmon_reader')
    CREATE LOGIN sqlmon_reader WITH PASSWORD = N'$(MONITOR_PASSWORD)', CHECK_POLICY = OFF;
ELSE
    ALTER LOGIN sqlmon_reader WITH PASSWORD = N'$(MONITOR_PASSWORD)';
ALTER LOGIN sqlmon_reader ENABLE;
-- server-level, read-only: DMVs, metadata of every database (also future ones), connect to every database
GRANT VIEW SERVER STATE    TO sqlmon_reader;   -- SQL Server 2022+: VIEW SERVER PERFORMANCE STATE is enough
GRANT VIEW ANY DEFINITION  TO sqlmon_reader;
GRANT CONNECT ANY DATABASE TO sqlmon_reader;   -- SQL Server 2014+
GO
-- backup history lives in msdb
USE msdb;
GO
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'sqlmon_reader')
    CREATE USER sqlmon_reader FOR LOGIN sqlmon_reader;
GRANT SELECT ON dbo.backupset TO sqlmon_reader;
GO

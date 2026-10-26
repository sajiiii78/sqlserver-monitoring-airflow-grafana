-- Run as postgres superuser:  sudo -u postgres psql -f 01_create_db_and_roles.sql
-- CHANGE the passwords. Never commit real passwords to git.
CREATE ROLE sqlmon_etl LOGIN PASSWORD 'CHANGE_ME_etl';      -- used by Airflow (read/write)
CREATE ROLE grafana_ro LOGIN PASSWORD 'CHANGE_ME_grafana';  -- used by Grafana (read only)
CREATE DATABASE sqlmon_staging OWNER sqlmon_etl;

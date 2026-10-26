"""Static configuration. Keep this module LIGHT: the scheduler imports it on every DAG parse."""
import os
from dataclasses import dataclass
from pathlib import Path

QUERY_DIR = Path(__file__).resolve().parent / "queries"

# Airflow Connection IDs (create them in the UI or with `airflow connections add`; see README).
MSSQL_CONN_IDS = [c.strip() for c in os.getenv("SQLMON_MSSQL_CONNS", "mssql_monitor").split(",") if c.strip()]
PG_CONN_ID = os.getenv("SQLMON_PG_CONN", "pg_monitoring")

POOL = "sqlmon_mssql"                 # limits concurrent queries against the production SQL Server
TZ = os.getenv("SQLMON_TZ", "UTC")    # timezone used to interpret the cron expressions below
RETENTION_DAYS = int(os.getenv("SQLMON_RETENTION_DAYS", "90"))

MSSQL_LOGIN_TIMEOUT = 30              # seconds
MSSQL_QUERY_TIMEOUT = 900             # seconds, per query

SCHEDULES = {
    "fast":   "*/15 * * * *",         # CPU / RAM / disk free / waits / HA / DB state      (every 15 min)
    "hourly": "5 * * * *",            # file usage, log usage, table sizes                 (hourly, 24x7)
    "daily":  "30 2 * * *",           # index fragmentation (heavy)                        (once a night)
    "maintenance": "30 3 * * *",      # retention purge
}


@dataclass(frozen=True)
class Metric:
    name: str                 # task id = collect_<name>
    sql_file: str             # file inside queries/
    table: str                # target table in schema mon
    tier: str                 # fast | hourly | daily
    scope: str                # "instance" (run once) | "database" (run inside every user database)
    include_system_dbs: bool = False
    timeout_min: int = 10     # Airflow execution_timeout


METRICS = [
    # ---- fast: every 15 minutes ----
    Metric("cpu",          "cpu.sql",          "cpu_usage",    "fast", "instance"),
    Metric("memory",       "memory.sql",       "memory_usage", "fast", "instance"),
    Metric("disk_volume",  "disk_volume.sql",  "disk_volume",  "fast", "instance"),
    Metric("db_inventory", "db_inventory.sql", "db_inventory", "fast", "instance"),
    Metric("workload",     "workload.sql",     "perf_counter", "fast", "instance"),
    Metric("waits",        "waits.sql",        "wait_stats",   "fast", "instance"),
    Metric("ha",           "ha.sql",           "ha_status",    "fast", "instance"),
    # ---- hourly ----
    Metric("db_files",     "db_files.sql",     "db_file_usage", "hourly", "database", include_system_dbs=True),
    Metric("db_log",       "db_log.sql",       "db_log_usage",  "hourly", "database", include_system_dbs=True),
    Metric("tables",       "table_size.sql",   "table_usage",   "hourly", "database", timeout_min=30),
    # ---- daily (heavy) ----
    Metric("fragmentation", "fragmentation.sql", "index_fragmentation", "daily", "database", timeout_min=180),
]

METRICS_BY_NAME = {m.name: m for m in METRICS}

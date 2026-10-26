"""SQL Server -> Postgres staging. Imported lazily by the DAG tasks (not at DAG parse time)."""
from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import psycopg2
import psycopg2.extras
import pyodbc
from airflow.hooks.base import BaseHook
from psycopg2 import sql

from .config import (METRICS_BY_NAME, MSSQL_CONN_IDS, MSSQL_LOGIN_TIMEOUT, MSSQL_QUERY_TIMEOUT,
                     PG_CONN_ID, QUERY_DIR, RETENTION_DAYS)
from .logger import get_logger

log = get_logger()


# --------------------------------------------------------------------------- connections
@contextmanager
def _pg():
    c = BaseHook.get_connection(PG_CONN_ID)
    cn = psycopg2.connect(host=c.host, port=c.port or 5432, dbname=c.schema, user=c.login,
                          password=c.password, connect_timeout=15, application_name="sqlmon-airflow")
    try:
        yield cn
        cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cn.close()


@contextmanager
def _mssql(conn, database: str | None = None):
    x = conn.extra_dejson
    pwd = (conn.password or "").replace("}", "}}")
    cs = (f"DRIVER={{{x.get('driver', 'ODBC Driver 18 for SQL Server')}}};"
          f"SERVER={conn.host},{conn.port or 1433};"
          f"DATABASE={database or conn.schema or 'master'};"
          f"UID={conn.login};PWD={{{pwd}}};"
          f"Encrypt={x.get('encrypt', 'yes')};"
          f"TrustServerCertificate={x.get('trust_server_certificate', 'yes')};"
          "APP=sqlmon-airflow;")
    cn = pyodbc.connect(cs, autocommit=True, timeout=MSSQL_LOGIN_TIMEOUT)
    cn.timeout = MSSQL_QUERY_TIMEOUT
    try:
        yield cn
    finally:
        cn.close()


# --------------------------------------------------------------------------- audit table
def _audit_start(dag_id, metric, server, collected_at, attempt):
    try:
        with _pg() as cn, cn.cursor() as cur:
            cur.execute(
                "INSERT INTO mon.etl_run_log (dag_id, metric, server_name, collected_at, status, attempt) "
                "VALUES (%s, %s, %s, %s, 'RUNNING', %s) RETURNING id",
                (dag_id, metric, server, collected_at, attempt))
            return cur.fetchone()[0]
    except Exception as exc:  # the file log is the fallback when Postgres is unreachable
        log.error("AUDIT_UNAVAILABLE stage=start metric=%s error=%s", metric, exc)
        return None


def _audit_finish(run_id, status, rows, error=None):
    if run_id is None:
        return
    try:
        with _pg() as cn, cn.cursor() as cur:
            cur.execute("UPDATE mon.etl_run_log SET status=%s, rows_loaded=%s, error_text=%s, finished_at=now() "
                        "WHERE id=%s", (status, rows, (error or "")[:2000] or None, run_id))
    except Exception as exc:
        log.error("AUDIT_UNAVAILABLE stage=finish run_id=%s error=%s", run_id, exc)


# --------------------------------------------------------------------------- extract
def _run_query(cn, query: str):
    cur = cn.cursor()
    cur.execute(query)
    while cur.description is None:          # skip row-count-only results
        if not cur.nextset():
            return [], []
    cols = [c[0].lower() for c in cur.description]
    return cols, [tuple(r) for r in cur.fetchall()]


def _list_databases(cn, include_system: bool) -> list[str]:
    extra = "" if include_system else "AND d.database_id > 4"
    cols, rows = _run_query(cn, (
        "SET NOCOUNT ON; SELECT d.name FROM sys.databases d "
        "WHERE d.state = 0 AND d.source_database_id IS NULL AND HAS_DBACCESS(d.name) = 1 "
        f"{extra} ORDER BY d.name;"))
    return [r[0] for r in rows]


def _extract(metric, conn):
    query = (QUERY_DIR / metric.sql_file).read_text(encoding="utf-8")
    failed: list[str] = []
    if metric.scope == "instance":
        with _mssql(conn) as cn:
            cols, rows = _run_query(cn, query)
        return cols, rows, failed

    with _mssql(conn) as master:
        dbs = _list_databases(master, metric.include_system_dbs)
    cols, rows = [], []
    for db in dbs:
        try:
            with _mssql(conn, db) as cn:
                c, r = _run_query(cn, query)
            cols = cols or c
            rows.extend(r)
        except Exception as exc:            # one broken database must not kill the whole metric
            failed.append(db)
            log.warning("DB_SKIPPED metric=%s db=%s error=%s", metric.name, db, exc)
    if dbs and len(failed) == len(dbs):
        raise RuntimeError(f"all {len(dbs)} databases failed for metric {metric.name}")
    return cols, rows, failed


# --------------------------------------------------------------------------- load (idempotent)
def _load(table, server, collected_at, cols, rows) -> int:
    """Delete + insert in ONE transaction: a retry of the same run never duplicates rows."""
    with _pg() as cn, cn.cursor() as cur:
        cur.execute(sql.SQL("DELETE FROM mon.{} WHERE server_name = %s AND collected_at = %s")
                    .format(sql.Identifier(table)), (server, collected_at))
        if rows and cols:
            stmt = sql.SQL("INSERT INTO mon.{} (server_name, collected_at, {}) VALUES %s").format(
                sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, cols))).as_string(cur)
            psycopg2.extras.execute_values(cur, stmt, [(server, collected_at, *r) for r in rows], page_size=1000)
    return len(rows)


# --------------------------------------------------------------------------- orchestration
def _collect_one(metric, conn_id, collected_at, dag_id, attempt) -> int:
    conn = BaseHook.get_connection(conn_id)
    server = conn.extra_dejson.get("server_name") or conn.host
    ctx = (f"dag={dag_id} metric={metric.name} server={server} "
           f"collected_at={collected_at.isoformat()} try={attempt}")
    log.info("RUN_START %s", ctx)
    run_id = _audit_start(dag_id, metric.name, server, collected_at, attempt)
    t0 = time.monotonic()
    try:
        cols, rows, failed = _extract(metric, conn)
        n = _load(metric.table, server, collected_at, cols, rows)
    except Exception as exc:
        log.error("RUN_FAIL %s duration_s=%.1f error=%s", ctx, time.monotonic() - t0, exc)
        _audit_finish(run_id, "FAILED", 0, str(exc))
        raise
    status = "PARTIAL" if failed else "SUCCESS"
    msg = f"{ctx} rows={n} duration_s={time.monotonic() - t0:.1f}"
    if failed:
        log.warning("RUN_PARTIAL %s failed_dbs=%s", msg, ",".join(failed))
    else:
        log.info("RUN_OK %s", msg)
    _audit_finish(run_id, status, n, f"failed dbs: {', '.join(failed)}" if failed else None)
    return n


def collect(metric_name: str, **context):
    """PythonOperator entry point."""
    metric = METRICS_BY_NAME[metric_name]
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    planned = context.get("data_interval_end")
    # A late run (retry, or Airflow was down) must NOT be stamped with its planned time: a DMV snapshot
    # describes "now". On-time runs keep the aligned timestamp.
    collected_at = planned if planned and abs(now - planned) <= timedelta(minutes=10) else now
    if planned and collected_at is now:
        log.warning("RUN_LATE metric=%s planned=%s actual=%s", metric_name, planned.isoformat(), now.isoformat())
    dag_id = context["dag"].dag_id if context.get("dag") else "manual"
    attempt = context["ti"].try_number if context.get("ti") else 1
    errors = []
    for conn_id in MSSQL_CONN_IDS:
        try:
            _collect_one(metric, conn_id, collected_at, dag_id, attempt)
        except Exception as exc:
            errors.append(f"{conn_id}: {exc}")
    if errors:
        raise RuntimeError("; ".join(errors))


def purge_old(**_context):
    with _pg() as cn, cn.cursor() as cur:
        cur.execute("SELECT mon.purge_old(%s)", (RETENTION_DAYS,))
    log.info("PURGE_OK retention_days=%s", RETENTION_DAYS)

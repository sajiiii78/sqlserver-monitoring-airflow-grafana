"""DAG factory: one DAG per schedule tier, one task per metric (failures are isolated per metric)."""
from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.operators.python import PythonOperator

from sqlmon.config import METRICS, POOL, SCHEDULES, TZ

DEFAULT_ARGS = {
    "owner": "data-engineering",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=2),
}


def _run_metric(metric_name, **context):
    from sqlmon.collector import collect          # lazy import: keeps DAG parsing fast
    return collect(metric_name, **context)


def _run_purge(**context):
    from sqlmon.collector import purge_old
    return purge_old(**context)


def _dag(dag_id, schedule, description):
    return DAG(
        dag_id=dag_id,
        description=description,
        start_date=pendulum.datetime(2026, 10, 1, tz=TZ),
        schedule=schedule,
        catchup=False,          # DMV data is a point-in-time snapshot: missed runs cannot be back-filled
        max_active_runs=1,      # never overlap two runs of the same DAG
        default_args=DEFAULT_ARGS,
        tags=["sqlmon"],
    )


def _metric_dag(dag_id, tier, description):
    dag = _dag(dag_id, SCHEDULES[tier], description)
    for m in (m for m in METRICS if m.tier == tier):
        PythonOperator(
            task_id=f"collect_{m.name}",
            python_callable=_run_metric,
            op_kwargs={"metric_name": m.name},
            pool=POOL,
            execution_timeout=timedelta(minutes=m.timeout_min),
            dag=dag,
        )
    return dag


sqlmon_fast_15min = _metric_dag("sqlmon_fast_15min", "fast", "CPU/RAM/disk/waits/HA/DB state every 15 min")
sqlmon_hourly     = _metric_dag("sqlmon_hourly",     "hourly", "File/log/table usage, hourly 24x7")
sqlmon_daily      = _metric_dag("sqlmon_daily",      "daily", "Index fragmentation (heavy), nightly")

sqlmon_maintenance = _dag("sqlmon_maintenance", SCHEDULES["maintenance"], "Retention purge in Postgres")
PythonOperator(task_id="purge_old", python_callable=_run_purge, dag=sqlmon_maintenance)

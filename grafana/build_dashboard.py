#!/usr/bin/env python3
"""Generates grafana/sqlmon_dashboard.json  (Grafana 9.5+, PostgreSQL data source).

    python3 build_dashboard.py            # writes sqlmon_dashboard.json next to this file
Import in Grafana:  Dashboards > New > Import > Upload JSON > pick your PostgreSQL data source.
Every panel query is plain SQL against schema `mon`; edit them here and re-generate.
"""
import json
from pathlib import Path

DS = {"type": "postgres", "uid": "${DS_PG}"}
_next_id = 0


def _id():
    global _next_id
    _next_id += 1
    return _next_id


def _steps(*pairs):
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for c, v in pairs]}


def _target(sql, fmt):
    return {"datasource": DS, "editorMode": "code", "format": fmt, "rawQuery": True,
            "rawSql": sql.strip(), "refId": "A"}


# ----------------------------------------------------------------------------- layout
class Layout:
    def __init__(self):
        self.x = self.y = self.row_h = 0
        self.panels = []

    def row(self, title):
        self.y += self.row_h
        self.x = self.row_h = 0
        self.panels.append({"id": _id(), "type": "row", "title": title, "collapsed": False,
                            "gridPos": {"h": 1, "w": 24, "x": 0, "y": self.y}, "panels": []})
        self.y += 1

    def add(self, panel, w, h):
        if self.x + w > 24:
            self.y += self.row_h
            self.x = self.row_h = 0
        panel["gridPos"] = {"h": h, "w": w, "x": self.x, "y": self.y}
        self.panels.append(panel)
        self.x += w
        self.row_h = max(self.row_h, h)


# ----------------------------------------------------------------------------- panel factories
def timeseries(title, sql, unit="short", desc="", vmin=None, vmax=None, bars=False, stack=False,
               fill=12, thresholds=None):
    d = {"unit": unit,
         "custom": {"drawStyle": "bars" if bars else "line", "lineWidth": 1, "fillOpacity": fill,
                    "showPoints": "never", "spanNulls": 7200000, "lineInterpolation": "linear",
                    "stacking": {"mode": "normal" if stack else "none", "group": "A"}}}
    if vmin is not None:
        d["min"] = vmin
    if vmax is not None:
        d["max"] = vmax
    if thresholds:
        d["thresholds"] = thresholds
        d["custom"]["thresholdsStyle"] = {"mode": "line"}
    return {"id": _id(), "type": "timeseries", "title": title, "description": desc, "datasource": DS,
            "targets": [_target(sql, "time_series")],
            "fieldConfig": {"defaults": d, "overrides": []},
            "options": {"legend": {"displayMode": "table", "placement": "bottom", "showLegend": True,
                                   "calcs": ["lastNotNull", "max"]},
                        "tooltip": {"mode": "multi", "sort": "desc"}}}


def stat(title, sql, thresholds, unit="short"):
    return {"id": _id(), "type": "stat", "title": title, "datasource": DS,
            "targets": [_target(sql, "table")],
            "fieldConfig": {"defaults": {"unit": unit, "thresholds": thresholds, "noValue": "0",
                                         "color": {"mode": "thresholds"}}, "overrides": []},
            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                        "colorMode": "background", "graphMode": "none", "textMode": "value_and_name",
                        "justifyMode": "center", "orientation": "auto"}}


def bargauge(title, sql, thresholds, unit="percent", desc=""):
    return {"id": _id(), "type": "bargauge", "title": title, "description": desc, "datasource": DS,
            "targets": [_target(sql, "table")],
            "fieldConfig": {"defaults": {"unit": unit, "min": 0, "max": 100, "thresholds": thresholds,
                                         "color": {"mode": "thresholds"}}, "overrides": []},
            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": True},
                        "orientation": "horizontal", "displayMode": "gradient", "showUnfilled": True}}


def table(title, sql, overrides=None, desc=""):
    return {"id": _id(), "type": "table", "title": title, "description": desc, "datasource": DS,
            "targets": [_target(sql, "table")],
            "fieldConfig": {"defaults": {"custom": {"align": "auto", "displayMode": "auto",
                                                    "filterable": True}},
                            "overrides": overrides or []},
            "options": {"showHeader": True, "footer": {"show": False}, "cellHeight": "sm"}}


def _map(pairs):
    opts = {text: {"color": color, "index": i, "text": text} for i, (text, color) in enumerate(pairs)}
    return [{"type": "value", "options": opts}]


def col_color(name, mapping=None, thresholds=None, unit=None):
    props = [{"id": "custom.displayMode", "value": "color-background"}]
    if mapping:
        props.append({"id": "mappings", "value": _map(mapping)})
    if thresholds:
        props.append({"id": "thresholds", "value": thresholds})
        props.append({"id": "color", "value": {"mode": "thresholds"}})
    if unit:
        props.append({"id": "unit", "value": unit})
    return {"matcher": {"id": "byName", "options": name}, "properties": props}


def col_unit(name, unit, width=None):
    props = [{"id": "unit", "value": unit}]
    if width:
        props.append({"id": "custom.width", "value": width})
    return {"matcher": {"id": "byName", "options": name}, "properties": props}


HEALTH = [("HEALTHY", "green"), ("DEGRADED", "orange"), ("STALE", "red")]
SEVERITY = [("critical", "red"), ("warning", "orange"), ("info", "blue")]
OKBAD = [("HEALTHY", "green"), ("NOT_HEALTHY", "red"), ("PARTIALLY_HEALTHY", "orange")]
DBSTATE = [("ONLINE", "green"), ("OFFLINE", "red"), ("RESTORING", "orange"), ("RECOVERING", "orange"),
           ("SUSPECT", "red"), ("EMERGENCY", "red")]
# ---- THRESHOLDS: one place. They must equal the numbers in postgres/03_dashboard_views.sql ----
CPU_WARN, CPU_CRIT = 80, 90              # % busy               (higher is worse)
DISK_FREE_WARN, DISK_FREE_CRIT = 20, 10  # % free space         (lower is worse)
PLE_CRIT = 300                           # page life expectancy, seconds (lower is worse)
LOG_WARN, LOG_CRIT = 80, 90              # % of transaction log used (higher is worse)
FILE_WARN, FILE_CRIT = 80, 95            # % of an allocated data file used (dashboard only)
FRAG_WARN, FRAG_CRIT = 10, 30            # % index fragmentation (dashboard only)


def high_is_bad(warn, crit):
    return _steps(("green", None), ("orange", warn), ("red", crit))


def low_is_bad(warn, crit):
    return _steps(("red", None), ("orange", crit), ("green", warn))


DISK_STEPS = low_is_bad(DISK_FREE_WARN, DISK_FREE_CRIT)
FRAG = high_is_bad(FRAG_WARN, FRAG_CRIT)
GOOD_ZERO = _steps(("green", None), ("red", 1))
ORANGE_ONE = _steps(("green", None), ("orange", 1))
BLUE = _steps(("blue", None))

S = "server_name = '$server'"                                     # server filter
DBF = "db_name = ANY(string_to_array('${db:csv}', ','))"          # multi-select database filter
T = "$__timeFilter(collected_at)"


def latest(tbl):
    return f"collected_at = (SELECT max(collected_at) FROM mon.{tbl} WHERE {S})"


# ----------------------------------------------------------------------------- dashboard
L = Layout()

# ---- Overview -------------------------------------------------------------------------
L.row("Overview")
L.add(table("Instance availability & collection health",
            """SELECT server_name, last_sample_at, sample_age_seconds, last_run_status,
                      runs_24h, failures_24h, health_state
               FROM mon.v_collection_health ORDER BY server_name""",
            [col_color("health_state", HEALTH), col_unit("sample_age_seconds", "s")],
            "One row per monitored instance. STALE = no sample for more than 35 minutes; "
            "DEGRADED = at least one failed collector run in the last hour."), 24, 4)

L.add(stat("Platform health issues",
           "SELECT count(*) AS \"Issues\" FROM mon.v_collection_health WHERE health_state <> 'HEALTHY'",
           GOOD_ZERO), 4, 5)
L.add(stat("Critical alerts",
           f"SELECT count(*) AS \"Critical\" FROM mon.v_active_alerts WHERE {S} AND severity = 'critical'",
           GOOD_ZERO), 4, 5)
L.add(stat("Warning alerts",
           f"SELECT count(*) AS \"Warnings\" FROM mon.v_active_alerts WHERE {S} AND severity = 'warning'",
           ORANGE_ONE), 4, 5)
L.add(stat("Collection runs (24h)",
           f"SELECT runs_24h AS \"Runs\" FROM mon.v_collection_health WHERE {S}", BLUE), 4, 5)
L.add(stat("Collector errors (24h)",
           f"SELECT failures_24h AS \"Errors\" FROM mon.v_collection_health WHERE {S}", GOOD_ZERO), 4, 5)
L.add(stat("Databases",
           f"SELECT count(*) AS \"Databases\" FROM mon.db_inventory WHERE {S} AND {latest('db_inventory')}",
           BLUE), 4, 5)

L.add(table("Active alerts",
            f"""SELECT alerted_at, severity, metric_name, object_name, message
                FROM mon.v_active_alerts WHERE {S}
                ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, alerted_at DESC""",
            [col_color("severity", SEVERITY)],
            "Computed from the latest snapshots (see postgres/03_dashboard_views.sql). "
            "An alert disappears by itself when the condition clears."), 14, 9)
L.add(timeseries("CPU %",
                 f"""SELECT collected_at AS time, sql_cpu_pct AS "SQL Server", other_cpu_pct AS "Other processes"
                     FROM mon.cpu_usage WHERE {T} AND {S} ORDER BY 1""",
                 "percent", vmin=0, vmax=100, stack=True, fill=25,
                 thresholds=high_is_bad(CPU_WARN, CPU_CRIT)), 10, 9)

# ---- Hardware -------------------------------------------------------------------------
L.row("Hardware")
L.add(timeseries("Memory (MB)",
                 f"""SELECT collected_at AS time, os_total_mb - os_available_mb AS "OS used",
                            sql_memory_used_mb AS "SQL Server", max_server_memory_mb AS "max server memory"
                     FROM mon.memory_usage WHERE {T} AND {S} ORDER BY 1""", "mbytes"), 8, 8)
L.add(timeseries("Page life expectancy",
                 f"""SELECT collected_at AS time, ple_seconds AS "PLE"
                     FROM mon.memory_usage WHERE {T} AND {S} ORDER BY 1""", "s",
                 desc="Seconds a page stays in the buffer pool. Sustained values below 300 s indicate memory pressure.",
                 thresholds=_steps(("red", None), ("green", PLE_CRIT))), 8, 8)
L.add(timeseries("Disk free %",
                 f"""SELECT collected_at AS time, COALESCE(NULLIF(volume_mount_point, ''), 'data volume') AS metric,
                            free_pct AS value
                     FROM mon.disk_volume WHERE {T} AND {S} ORDER BY 1""", "percent", vmin=0, vmax=100,
                 thresholds=DISK_STEPS), 8, 8)
L.add(bargauge("Disk free now",
               f"""SELECT COALESCE(NULLIF(volume_mount_point, ''), 'data volume') AS volume, free_pct AS "Free %"
                   FROM mon.disk_volume WHERE {S} AND {latest('disk_volume')}""", DISK_STEPS), 8, 6)
L.add(timeseries("Disk free (GB)",
                 f"""SELECT collected_at AS time, COALESCE(NULLIF(volume_mount_point, ''), 'data volume') AS metric,
                            free_mb / 1024.0 AS value
                     FROM mon.disk_volume WHERE {T} AND {S} ORDER BY 1""", "decgbytes"), 8, 6)
L.add(timeseries("Memory grants pending & blocked requests",
                 f"""SELECT collected_at AS time, counter_name AS metric, cntr_value AS value
                     FROM mon.perf_counter
                     WHERE {T} AND {S} AND counter_name IN ('Memory Grants Pending', 'Blocked Requests')
                     ORDER BY 1""", "short", bars=True), 8, 6)

# ---- Databases ------------------------------------------------------------------------
L.row("Databases")
L.add(table("Databases now",
            f"""SELECT db_name, state_desc, recovery_model, total_size_mb, data_size_mb, log_size_mb,
                       last_full_backup, last_log_backup, log_reuse_wait
                FROM mon.db_inventory WHERE {S} AND {latest('db_inventory')} AND {DBF}
                ORDER BY total_size_mb DESC NULLS LAST""",
            [col_color("state_desc", DBSTATE), col_unit("total_size_mb", "mbytes"),
             col_unit("data_size_mb", "mbytes"), col_unit("log_size_mb", "mbytes")]), 24, 7)
L.add(timeseries("Database size (MB)",
                 f"""SELECT collected_at AS time, db_name AS metric, total_size_mb AS value
                     FROM mon.db_inventory WHERE {T} AND {S} AND {DBF} ORDER BY 1""", "mbytes"), 12, 8)
L.add(timeseries("Filegroup used space (MB)",
                 f"""SELECT collected_at AS time, db_name || ' / ' || filegroup_name AS metric, sum(used_mb) AS value
                     FROM mon.db_file_usage
                     WHERE {T} AND {S} AND {DBF} AND filegroup_name <> '(log)'
                     GROUP BY 1, 2 ORDER BY 1""", "mbytes",
                 desc="Data filegroups, including FILESTREAM filegroups (hourly)."), 12, 8)
L.add(table("Files & filegroups now",
            f"""SELECT db_name, filegroup_name, filegroup_type, file_name, file_type, size_mb, used_mb,
                       round(100.0 * used_mb / NULLIF(size_mb, 0), 1) AS used_pct, max_size_mb, growth_desc,
                       physical_name
                FROM mon.db_file_usage WHERE {S} AND {latest('db_file_usage')} AND {DBF}
                ORDER BY db_name, filegroup_name, file_name""",
            [col_unit("size_mb", "mbytes"), col_unit("used_mb", "mbytes"), col_unit("max_size_mb", "mbytes"),
             col_color("used_pct", thresholds=high_is_bad(FILE_WARN, FILE_CRIT),
                       unit="percent")]), 24, 8)
L.add(timeseries("Transaction log used %",
                 f"""SELECT collected_at AS time, db_name AS metric, used_log_pct AS value
                     FROM mon.db_log_usage WHERE {T} AND {S} AND {DBF} ORDER BY 1""",
                 "percent", vmin=0, vmax=100, thresholds=high_is_bad(LOG_WARN, LOG_CRIT)), 8, 8)
L.add(table("Biggest tables now",
            f"""SELECT db_name, schema_name || '.' || table_name AS "table", row_count, reserved_mb, data_mb, index_mb
                FROM mon.table_usage WHERE {S} AND {latest('table_usage')} AND {DBF}
                ORDER BY reserved_mb DESC LIMIT 25""",
            [col_unit("reserved_mb", "mbytes"), col_unit("data_mb", "mbytes"), col_unit("index_mb", "mbytes")]),
        8, 8)
L.add(timeseries("Growth of the 10 biggest tables (MB)",
                 f"""SELECT collected_at AS time, db_name || '.' || table_name AS metric, reserved_mb AS value
                     FROM mon.table_usage
                     WHERE {T} AND {S} AND {DBF}
                       AND (db_name, schema_name, table_name) IN (
                           SELECT db_name, schema_name, table_name FROM mon.table_usage
                           WHERE {S} AND {latest('table_usage')} ORDER BY reserved_mb DESC LIMIT 10)
                     ORDER BY 1""", "mbytes"), 8, 8)
L.add(table("Fragmented indexes (latest nightly scan)",
            f"""SELECT db_name, schema_name || '.' || table_name AS "table", index_name, index_type,
                       page_count, size_mb, avg_fragmentation_pct
                FROM mon.index_fragmentation
                WHERE {S} AND {latest('index_fragmentation')} AND {DBF} AND avg_fragmentation_pct >= 10
                ORDER BY avg_fragmentation_pct DESC, page_count DESC LIMIT 50""",
            [col_color("avg_fragmentation_pct", thresholds=FRAG, unit="percent"), col_unit("size_mb", "mbytes")],
            "Rule of thumb: 10-30 % reorganize, above 30 % rebuild. Indexes under 1000 pages are skipped."), 12, 8)
L.add(timeseries("Average fragmentation per database",
                 f"""SELECT collected_at AS time, db_name AS metric, avg(avg_fragmentation_pct) AS value
                     FROM mon.index_fragmentation WHERE {T} AND {S} AND {DBF}
                     GROUP BY 1, 2 ORDER BY 1""", "percent",
                 desc="One point per nightly scan - widen the time range to 7 days."), 12, 8)

# ---- Workload -------------------------------------------------------------------------
L.row("Workload")
L.add(timeseries("Batch requests / sec",
                 f"""SELECT time, CASE WHEN dv >= 0 THEN dv / NULLIF(ds, 0) END AS "batch requests/sec"
                     FROM (SELECT collected_at AS time,
                                  cntr_value - lag(cntr_value) OVER w AS dv,
                                  extract(epoch FROM collected_at - lag(collected_at) OVER w) AS ds
                           FROM mon.perf_counter
                           WHERE {T} AND {S} AND counter_name = 'Batch Requests/sec'
                           WINDOW w AS (ORDER BY collected_at)) x
                     ORDER BY 1""", "ops",
                 desc="The counter is cumulative; this panel plots the delta between two samples."), 8, 8)
L.add(timeseries("Sessions & blocking",
                 f"""SELECT collected_at AS time, counter_name AS metric, cntr_value AS value
                     FROM mon.perf_counter
                     WHERE {T} AND {S} AND counter_name IN ('Active User Sessions', 'User Connections', 'Blocked Requests')
                     ORDER BY 1""", "short"), 8, 8)
L.add(timeseries("Page reads / writes per sample",
                 f"""SELECT time, counter_name AS metric, CASE WHEN dv >= 0 THEN dv END AS value
                     FROM (SELECT collected_at AS time, counter_name,
                                  cntr_value - lag(cntr_value) OVER (PARTITION BY counter_name ORDER BY collected_at) AS dv
                           FROM mon.perf_counter
                           WHERE {T} AND {S} AND counter_name IN ('Page reads/sec', 'Page writes/sec', 'Lazy writes/sec')) x
                     WHERE dv IS NOT NULL ORDER BY 1""", "short",
                 desc="Cumulative counters, shown as the delta between two 15-minute samples."), 8, 8)
L.add(timeseries("Wait time per interval (top 8 waits, seconds)",
                 f"""SELECT time, wait_type AS metric, CASE WHEN dv >= 0 THEN dv / 1000.0 END AS value
                     FROM (SELECT collected_at AS time, wait_type,
                                  wait_time_ms - lag(wait_time_ms) OVER (PARTITION BY wait_type ORDER BY collected_at) AS dv
                           FROM mon.wait_stats WHERE {T} AND {S}) x
                     WHERE dv IS NOT NULL
                       AND wait_type IN (SELECT wait_type FROM mon.wait_stats
                                         WHERE {S} AND {latest('wait_stats')}
                                         ORDER BY wait_time_ms DESC LIMIT 8)
                     ORDER BY 1""", "s", bars=True, stack=True, fill=70,
                 desc="sys.dm_os_wait_stats is cumulative since instance start, so raw values only ever grow. "
                      "This panel shows the time actually spent waiting in each interval."), 24, 9)

# ---- High availability ------------------------------------------------------------------
L.row("High availability")
L.add(table("Availability groups (latest)",
            f"""WITH cur AS (
                    SELECT ag_name, replica_server_name, role_desc, connected_state_desc, replica_sync_health,
                           db_name, db_sync_state, db_sync_health, log_send_queue_kb, redo_queue_kb, is_suspended
                    FROM mon.ha_status WHERE {S} AND {latest('ha_status')})
                SELECT * FROM cur
                UNION ALL
                SELECT 'No Availability Groups configured on this instance'::text, NULL::text, NULL::text, NULL::text,
                       NULL::text, NULL::text, NULL::text, NULL::text, NULL::bigint, NULL::bigint, NULL::integer
                WHERE NOT EXISTS (SELECT 1 FROM cur)
                ORDER BY ag_name, replica_server_name, db_name""",
            [col_color("replica_sync_health", OKBAD), col_color("db_sync_health", OKBAD),
             col_color("connected_state_desc", [("CONNECTED", "green"), ("DISCONNECTED", "red")]),
             col_unit("log_send_queue_kb", "deckbytes"), col_unit("redo_queue_kb", "deckbytes")],
            "Shows one explanatory row on instances that do not use Always On Availability Groups."), 24, 6)

# ---- Collection pipeline ----------------------------------------------------------------
L.row("Collection pipeline")
L.add(timeseries("Failed collector runs",
                 f"""SELECT g.t AS time, COALESCE(f.n, 0) AS "failed runs"
                     FROM generate_series(date_bin(interval '15 minutes', $__timeFrom()::timestamptz, TIMESTAMPTZ '2000-01-01'),
                                          $__timeTo()::timestamptz, interval '15 minutes') AS g(t)
                     LEFT JOIN (SELECT date_bin(interval '15 minutes', collected_at, TIMESTAMPTZ '2000-01-01') AS b, count(*) AS n
                                FROM mon.etl_run_log WHERE {T} AND {S} AND status = 'FAILED' GROUP BY 1) f ON f.b = g.t
                     ORDER BY 1""", "short", bars=True, fill=80, vmin=0,
                 desc="Zero-filled: a flat line at 0 means no collector failures in the selected range."), 8, 7)
L.add(timeseries("Collector duration (s)",
                 f"""SELECT collected_at AS time, metric, extract(epoch FROM finished_at - started_at) AS value
                     FROM mon.etl_run_log WHERE {T} AND {S} AND finished_at IS NOT NULL ORDER BY 1""", "s"), 8, 7)
L.add(timeseries("Rows loaded per run",
                 f"""SELECT collected_at AS time, metric, rows_loaded AS value
                     FROM mon.etl_run_log WHERE {T} AND {S} AND status IN ('SUCCESS', 'PARTIAL') ORDER BY 1""",
                 "short"), 8, 7)
L.add(table("Last successful run per metric",
            f"""SELECT metric, last_ok_at, round(extract(epoch FROM age)) AS age_seconds, failures_24h
                FROM mon.v_data_freshness WHERE {S} ORDER BY metric""",
            [col_unit("age_seconds", "s"), col_color("failures_24h", thresholds=GOOD_ZERO)]), 24, 8)

dashboard = {
    "__inputs": [{"name": "DS_PG", "label": "PostgreSQL (sqlmon_staging)", "description": "",
                  "type": "datasource", "pluginId": "postgres", "pluginName": "PostgreSQL"}],
    "__requires": [{"type": "grafana", "id": "grafana", "name": "Grafana", "version": "9.5.0"},
                   {"type": "datasource", "id": "postgres", "name": "PostgreSQL", "version": "1.0.0"}],
    "uid": "sqlmon-overview", "title": "SQL Server Monitoring - Overview", "tags": ["sqlmon", "sql-server"],
    "timezone": "browser", "schemaVersion": 38, "version": 1, "editable": True,
    "graphTooltip": 1,                      # shared crosshair across panels
    "refresh": "1m", "time": {"from": "now-6h", "to": "now"},
    "templating": {"list": [
        {"name": "server", "label": "Server", "type": "query", "datasource": DS, "refresh": 2, "sort": 1,
         "query": "SELECT DISTINCT server_name FROM mon.etl_run_log ORDER BY 1",
         "definition": "SELECT DISTINCT server_name FROM mon.etl_run_log ORDER BY 1",
         "includeAll": False, "multi": False},
        {"name": "db", "label": "Database", "type": "query", "datasource": DS, "refresh": 2, "sort": 1,
         "query": "SELECT DISTINCT db_name FROM mon.db_inventory WHERE server_name = '$server' "
                  "AND collected_at > now() - interval '1 day' ORDER BY 1",
         "definition": "SELECT DISTINCT db_name FROM mon.db_inventory WHERE server_name = '$server' "
                       "AND collected_at > now() - interval '1 day' ORDER BY 1",
         "includeAll": True, "multi": True, "current": {"selected": True, "text": ["All"], "value": ["$__all"]}},
    ]},
    "annotations": {"list": []},
    "panels": L.panels,
}

def provisioned(d):
    """Same dashboard for Grafana file provisioning: fixed data source uid, no import-time inputs."""
    d = json.loads(json.dumps(d).replace("${DS_PG}", "sqlmon-pg"))
    d.pop("__inputs", None)
    d.pop("__requires", None)
    return d


def check_sync():
    """Fail the build if the dashboard thresholds and the alert-view thresholds ever drift apart."""
    import re
    sql = (Path(__file__).resolve().parents[1] / "postgres" / "03_dashboard_views.sql").read_text(encoding="utf-8")

    def num(pattern):
        m = re.search(pattern, sql)
        if not m:
            raise SystemExit(f"threshold check: pattern not found in 03_dashboard_views.sql: {pattern}")
        return int(m.group(1))

    expect = {
        "CPU_WARN": (CPU_WARN, num(r"HAVING avg\([^)]*\+[^)]*\) > (\d+)")),
        "CPU_CRIT": (CPU_CRIT, num(r"CASE WHEN avg\([^)]*\+[^)]*\) > (\d+) THEN 'critical'")),
        "DISK_FREE_WARN": (DISK_FREE_WARN, num(r"AND d\.free_pct < (\d+)")),
        "DISK_FREE_CRIT": (DISK_FREE_CRIT, num(r"d\.free_pct < (\d+) THEN 'critical'")),
        "PLE_CRIT": (PLE_CRIT, num(r"m\.ple_seconds < (\d+)")),
        "LOG_WARN": (LOG_WARN, num(r"AND l\.used_log_pct > (\d+)")),
        "LOG_CRIT": (LOG_CRIT, num(r"l\.used_log_pct > (\d+) THEN 'critical'")),
    }
    bad = {k: v for k, v in expect.items() if v[0] != v[1]}
    if bad:
        raise SystemExit("threshold mismatch (dashboard, alert view): " + str(bad))
    print("thresholds in sync with 03_dashboard_views.sql:", {k: v[0] for k, v in expect.items()})


if __name__ == "__main__":
    check_sync()
    here = Path(__file__).parent
    (here / "sqlmon_dashboard.json").write_text(json.dumps(dashboard, indent=1, ensure_ascii=False), encoding="utf-8")
    prov = here / "provisioning" / "dashboards-json"
    prov.mkdir(parents=True, exist_ok=True)
    (prov / "sqlmon_dashboard.json").write_text(json.dumps(provisioned(dashboard), indent=1, ensure_ascii=False),
                                                encoding="utf-8")
    n = sum(1 for p in L.panels if p["type"] != "row")
    print(f"wrote sqlmon_dashboard.json (import) and provisioning/dashboards-json/sqlmon_dashboard.json ({n} panels)")

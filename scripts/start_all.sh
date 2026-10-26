#!/usr/bin/env bash
# Development helper: bring the whole lab up after a reboot (WSL / Linux).
#   Docker + PostgreSQL -> containers -> monitoring login -> Airflow scheduler + webserver
# Configuration comes from ./.env (copy .env.example). Not meant for production hosts (use systemd there).
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$ROOT/.env" ]; then set -a; . "$ROOT/.env"; set +a; fi

: "${COMPOSE_DIR:?set COMPOSE_DIR in .env (folder of the docker-compose.yml)}"
: "${AIRFLOW_VENV:?set AIRFLOW_VENV in .env (path to .../bin/activate)}"
: "${SA_PASSWORD:?set SA_PASSWORD in .env}"
: "${MONITOR_PASSWORD:?set MONITOR_PASSWORD in .env}"
SQL_CONTAINER="${SQL_CONTAINER:-sql_server_sales}"
COMPOSE_SERVICES="${COMPOSE_SERVICES:-sql_server_sales grafana}"
EXTRA_CONTAINERS="${EXTRA_CONTAINERS:-}"

sql() { sudo docker exec -i "$SQL_CONTAINER" /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$SA_PASSWORD" -C "$@"; }

echo "[1/5] Docker + PostgreSQL"
sudo service docker start >/dev/null 2>&1
sudo service postgresql start >/dev/null 2>&1
for _ in $(seq 1 30); do pg_isready -q -h localhost && break; sleep 2; done

echo "[2/5] containers"
( cd "$COMPOSE_DIR" && sudo docker compose up -d $COMPOSE_SERVICES )
[ -n "$EXTRA_CONTAINERS" ] && sudo docker start $EXTRA_CONTAINERS >/dev/null 2>&1

echo "[3/5] waiting for SQL Server"
for _ in $(seq 1 60); do sql -l 3 -Q "SELECT 1" >/dev/null 2>&1 && break; sleep 3; done

echo "[4/5] monitoring login (idempotent)"
sql -v MONITOR_PASSWORD="$MONITOR_PASSWORD" < "$ROOT/mssql/01_create_monitor_login.sql"
sql -h -1 -W -Q "SET NOCOUNT ON; SELECT 'sqlmon_reader exists: ' + CAST(COUNT(*) AS varchar(5)) FROM sys.server_principals WHERE name = N'sqlmon_reader'"

echo "[5/5] Airflow"
# shellcheck disable=SC1090
source "$AIRFLOW_VENV"
mkdir -p "$HOME/airflow"
pgrep -f "airflow scheduler" >/dev/null || setsid nohup airflow scheduler > "$HOME/airflow/scheduler.out" 2>&1 &
pgrep -f "airflow webserver" >/dev/null || setsid nohup airflow webserver -p 8080 > "$HOME/airflow/webserver.out" 2>&1 &
sleep 3
echo "done.  Airflow: http://localhost:8080   Grafana: http://localhost:3000 (or your mapped port)"

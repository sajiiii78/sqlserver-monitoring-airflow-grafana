"""File logger. Independent of Postgres and of Airflow's own task logs, so it survives both going down.

Every run writes one RUN_START and exactly one RUN_OK / RUN_PARTIAL / RUN_FAIL line:
    grep -E "RUN_(OK|PARTIAL|FAIL)" ~/sqlmon_logs/sqlmon.log | tail -50
"""
import logging
import os
from logging.handlers import WatchedFileHandler

LOG_DIR = os.getenv("SQLMON_LOG_DIR", os.path.expanduser("~/sqlmon_logs"))


def get_logger() -> logging.Logger:
    logger = logging.getLogger("sqlmon")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        # WatchedFileHandler is safe with several Airflow task processes + logrotate (see README).
        fh = WatchedFileHandler(os.path.join(LOG_DIR, "sqlmon.log"), encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        logger.addHandler(fh)
    except OSError:
        pass  # still logs through Airflow's task log (propagates to the root logger)
    return logger

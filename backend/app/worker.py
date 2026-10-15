"""Dedicated sync service: periodic (15 min) + on-demand via LISTEN ghost_sync."""
import logging
import select
import threading
import time

import psycopg2

from .config import get_settings
from .db import get_engine
from .jira import JiraClient
from .sync import NOTIFY_CHANNEL, connect_listener, run_sync

log = logging.getLogger("ghost.worker")
INTERVAL = 15 * 60
KEEPALIVE = 60.0  # max idle time of the LISTEN connection


def drain(conn) -> int:
    """Consume pending notifications; returns how many were waiting."""
    conn.poll()
    n = len(conn.notifies)
    del conn.notifies[:]
    return n


class Worker:
    def __init__(self, database_url: str, sync_fn, interval: float = INTERVAL,
                 reconnect_delay: float = 5.0):
        self.database_url = database_url
        self.sync_fn = sync_fn
        self.interval = interval
        self.reconnect_delay = reconnect_delay
        self.stop = threading.Event()
        self.syncs_run = 0

    def _listen(self):
        conn = connect_listener(self.database_url)
        with conn.cursor() as cur:
            cur.execute("LISTEN %s" % NOTIFY_CHANNEL)
        return conn

    def _run_one(self, conn):
        try:
            self.sync_fn()
            self.syncs_run += 1
        except Exception:  # noqa: BLE001
            log.exception("sync crashed")
        drain(conn)  # a burst of notifications yields at most one extra sync

    def run_forever(self):
        next_run = time.monotonic()  # sync once at startup
        conn = None
        while not self.stop.is_set():
            try:
                if conn is None:
                    conn = self._listen()
                    log.info("listening on %s", NOTIFY_CHANNEL)
                wait = max(0.0, next_run - time.monotonic())
                ready = select.select([conn], [], [], min(wait, KEEPALIVE))[0]
                notified = bool(ready) and drain(conn) > 0
                if not ready:
                    with conn.cursor() as cur:  # keeps the idle connection alive, detects a drop
                        cur.execute("SELECT 1")
                    notified = drain(conn) > 0
                if notified or time.monotonic() >= next_run:
                    drain(conn)
                    self._run_one(conn)
                    next_run = time.monotonic() + self.interval
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as exc:
                log.warning("listener connection lost (%s); reconnecting", exc)
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:  # noqa: BLE001
                        pass
                conn = None
                self.stop.wait(self.reconnect_delay)
        if conn is not None:
            conn.close()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    s = get_settings()
    engine = get_engine()
    jira = JiraClient(s)
    Worker(s.database_url, lambda: run_sync(engine, jira, s)).run_forever()


if __name__ == "__main__":
    main()

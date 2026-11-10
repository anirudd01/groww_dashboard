"""A tiny HTTP trigger for the daily jobs, run next to Streamlit in the Railway container.

    POST /run             start ``scripts/daily.py --scheduled`` in the background; 202 at once, 409 if one is going
    GET  /status          the current or last run: start, end, exit code and the end of its log
    POST /capture         start ``scripts/debug/capture_auctions.py`` (it waits for the next auction window)
    GET  /capture/status  the same for the capture

The capture is a research recorder for docs/PLAN_PRE_MARKET.md, started by the ``auction-capture`` cron
service. It has its own runner, so a capture and the daily jobs never block each other.

Every request needs the header ``X-Job-Secret: $JOB_TRIGGER_SECRET`` (401 otherwise). The server
starts only when that variable is set (deploy/railway/start.sh).

Why it lives in the dashboards container: the database is on a Railway volume, and a volume
attaches to one service only. The caller is the ``daily-jobs`` cron service in the same project.

Reachability: it listens on ``JOB_TRIGGER_PORT`` (default 8090) on ``::``, which Railway's private
network (``dashboards.railway.internal``) reaches over IPv4 and IPv6. The public domain forwards
only to Streamlit's ``$PORT``, so this port is not on the internet; the secret is the second lock.

The jobs run in a child process: each run logs in to the brokers afresh (a Groww token minted
yesterday has expired) and returns its memory when it ends. Its output goes to the container log,
prefixed ``[jobs]``, and to ``data/jobs/last_run.log`` on the volume. Read-only against the brokers.
"""

import hmac
import json
import os
import socket
import subprocess
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(ROOT, "data", "jobs")
LOG_PATH = os.path.join(LOG_DIR, "last_run.log")
CAPTURE_LOG_PATH = os.path.join(LOG_DIR, "last_capture.log")
SECRET_ENV, PORT_ENV = "JOB_TRIGGER_SECRET", "JOB_TRIGGER_PORT"
#: A run that takes longer than this is stuck (a normal run takes 2-5 minutes).
TIMEOUT_S = 45 * 60
TAIL_LINES = 40


class Runner:
    """At most one run at a time; remembers the last one."""

    def __init__(self, command, log_path=None, prefix="jobs"):
        self.command = command
        self.log_path = log_path  # None: the module's LOG_PATH, read when used
        self.prefix = prefix
        self.lock = threading.Lock()
        self.state = {"running": False, "started": None, "ended": None, "exit_code": None}

    def start(self) -> bool:
        with self.lock:
            if self.state["running"]:
                return False
            self.state = {"running": True, "started": now(), "ended": None, "exit_code": None}
        threading.Thread(target=self._run, daemon=True).start()
        return True

    def _run(self) -> None:
        code = None
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            with open(self._log_path(), "w", encoding="utf-8") as log:
                log.write(f"started {self.state['started']}\n")
                proc = subprocess.Popen(self.command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding="utf-8", errors="replace",
                                        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
                timer = threading.Timer(TIMEOUT_S, proc.kill)
                timer.start()
                for line in proc.stdout:
                    log.write(line)
                    log.flush()
                    print(f"[{self.prefix}] {line}", end="", flush=True)
                code = proc.wait()
                timer.cancel()
                log.write(f"ended {now()} exit {code}\n")
        except Exception as exc:  # noqa: BLE001 - recorded, never kills the server
            print(f"[{self.prefix}] could not run: {exc}", flush=True)
            code = -1
        finally:
            with self.lock:
                self.state.update(running=False, ended=now(), exit_code=code)
            print(f"[{self.prefix}] run finished, exit code {code}", flush=True)

    def _log_path(self) -> str:
        return self.log_path or LOG_PATH

    def status(self) -> dict:
        with self.lock:
            state = dict(self.state)
        try:
            with open(self._log_path(), encoding="utf-8") as log:
                state["log_tail"] = log.read().splitlines()[-TAIL_LINES:]
        except OSError:
            state["log_tail"] = []
        return state


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def make_handler(runner: Runner, secret: str, capture: Runner = None):
    class Handler(BaseHTTPRequestHandler):
        def _authorised(self) -> bool:
            given = self.headers.get("X-Job-Secret") or ""
            return hmac.compare_digest(given.encode(), secret.encode())

        def _reply(self, status: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):  # noqa: N802 - http.server's naming
            if not self._authorised():
                return self._reply(401, {"error": "unauthorised"})
            target = {"/run": runner, "/capture": capture}.get(self.path)
            if target is None:
                return self._reply(404, {"error": "not found"})
            if target.start():
                return self._reply(202, {**target.status(), "accepted": True})
            return self._reply(409, {**target.status(), "accepted": False, "error": "a run is already going"})

        def do_GET(self):  # noqa: N802
            if not self._authorised():
                return self._reply(401, {"error": "unauthorised"})
            target = {"/status": runner, "/capture/status": capture}.get(self.path)
            if target is None:
                return self._reply(404, {"error": "not found"})
            return self._reply(200, target.status())

        def log_message(self, fmt, *args):  # one line per request, never the headers
            print(f"[trigger] {self.address_string()} {fmt % args}", flush=True)

    return Handler


class DualStackServer(ThreadingHTTPServer):
    """Listens on ``::`` for IPv6 and IPv4 alike (Railway's private network may use either)."""

    address_family = socket.AF_INET6

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


def main() -> int:
    secret = (os.getenv(SECRET_ENV) or "").strip()
    if len(secret) < 16:
        print(f"[trigger] {SECRET_ENV} is unset or shorter than 16 characters - not starting.", flush=True)
        return 1
    port = int(os.getenv(PORT_ENV) or 8090)
    runner = Runner([sys.executable, os.path.join(ROOT, "scripts", "daily.py"), "--scheduled"])
    capture = Runner([sys.executable, os.path.join(ROOT, "scripts", "debug", "capture_auctions.py")],
                     log_path=CAPTURE_LOG_PATH, prefix="capture")
    server = DualStackServer(("::", port), make_handler(runner, secret, capture))
    print(f"[trigger] listening on [::]:{port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

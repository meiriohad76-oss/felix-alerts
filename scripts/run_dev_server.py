from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from sentinel_core.http_api import create_server


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "sentinel_dev.sqlite3"
DEFAULT_STATIC_DIR = ROOT / "frontend"
DEFAULT_PID_FILE = ROOT / ".sentinel_dev_server.pid"
DEFAULT_LOG_FILE = ROOT / "sentinel_dev_server.log"
LOCAL_NO_PROXY_HOSTS = ("127.0.0.1", "localhost", "::1")


def ensure_local_no_proxy(host: str) -> None:
    hosts = list(LOCAL_NO_PROXY_HOSTS)
    if host and host not in ("0.0.0.0", "::") and host not in hosts:
        hosts.append(host)
    for key in ("NO_PROXY", "no_proxy"):
        current = [item.strip() for item in os.environ.get(key, "").split(",") if item.strip()]
        for value in hosts:
            if value not in current:
                current.append(value)
        os.environ[key] = ",".join(current)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Sentinel development server.")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8765")))
    parser.add_argument("--db-path", default=os.environ.get("SENTINEL_DB_PATH", str(DEFAULT_DB_PATH)))
    parser.add_argument("--static-dir", default=os.environ.get("SENTINEL_STATIC_DIR", str(DEFAULT_STATIC_DIR)))
    parser.add_argument("--daemon", action="store_true", help="Start the server in the background.")
    parser.add_argument("--stop", action="store_true", help="Stop the background server from the PID file.")
    parser.add_argument("--status", action="store_true", help="Print background server status.")
    parser.add_argument("--pid-file", default=os.environ.get("SENTINEL_PID_FILE", str(DEFAULT_PID_FILE)))
    parser.add_argument("--log-file", default=os.environ.get("SENTINEL_LOG_FILE", str(DEFAULT_LOG_FILE)))
    parser.add_argument("--startup-timeout", type=float, default=5.0)
    args = parser.parse_args(argv)
    selected_modes = sum(1 for mode in (args.daemon, args.stop, args.status) if mode)
    if selected_modes > 1:
        parser.error("choose only one of --daemon, --stop, or --status")
    return args


def run_server(*, host: str, port: int, db_path: Path, static_dir: Path) -> None:
    try:
        server = create_server(db_path=db_path, host=host, port=port, static_dir=static_dir)
    except OSError as exc:
        if exc.errno == 48:
            print(
                "Port %s is already in use. Stop the existing server with "
                "`lsof -iTCP:%s -sTCP:LISTEN -n -P` then `kill <PID>`, "
                "or run with another port, for example `PORT=8766 PYTHONPATH=backend python3 scripts/run_dev_server.py`."
                % (port, port),
                file=sys.stderr,
            )
            raise SystemExit(1) from exc
        raise
    host, port = server.server_address
    print("Sentinel dev server running at http://%s:%s" % (host, port))
    print("Database: %s" % db_path)
    server.serve_forever()


def process_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def pid_from_file(pid_file: Path) -> int | None:
    try:
        raw = pid_file.read_text().strip()
    except OSError:
        return None
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def wait_until_healthy(host: str, port: int, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urlopen("http://%s:%s/health" % (host, port), timeout=0.5) as response:
                if response.status == 200:
                    return True
        except (OSError, URLError):
            pass
        time.sleep(0.1)
    return False


def start_daemon(args: argparse.Namespace) -> int:
    pid_file = Path(args.pid_file)
    log_file = Path(args.log_file)
    existing_pid = pid_from_file(pid_file)
    if existing_pid and process_is_running(existing_pid):
        print(
            "Sentinel dev server is already running with PID %s. "
            "Use --stop first or choose a different --pid-file." % existing_pid,
            file=sys.stderr,
        )
        return 1
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--db-path",
        args.db_path,
        "--static-dir",
        args.static_dir,
    ]
    with log_file.open("ab") as log:
        process = subprocess.Popen(
            command,
            cwd=str(ROOT),
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    pid_file.write_text(str(process.pid))
    time.sleep(0.1)
    if process.poll() is not None:
        pid_file.unlink(missing_ok=True)
        print("Sentinel dev server failed to start. See %s." % log_file, file=sys.stderr)
        return int(process.returncode or 1)
    if not wait_until_healthy(args.host, args.port, args.startup_timeout):
        try:
            os.kill(process.pid, signal.SIGTERM)
        except OSError:
            pass
        pid_file.unlink(missing_ok=True)
        print("Sentinel dev server did not become healthy. See %s." % log_file, file=sys.stderr)
        return 1
    print("Sentinel dev server started at http://%s:%s" % (args.host, args.port))
    print("PID: %s" % process.pid)
    print("Log: %s" % log_file)
    return 0


def stop_daemon(args: argparse.Namespace) -> int:
    pid_file = Path(args.pid_file)
    pid = pid_from_file(pid_file)
    if not pid:
        print("No Sentinel dev server PID file found at %s." % pid_file)
        return 0
    if not process_is_running(pid):
        pid_file.unlink(missing_ok=True)
        print("Removed stale Sentinel dev server PID file: %s" % pid_file)
        return 0
    os.kill(pid, signal.SIGTERM)
    deadline = time.time() + 5
    while process_is_running(pid) and time.time() < deadline:
        time.sleep(0.1)
    if process_is_running(pid):
        print("Sent SIGTERM to PID %s, but it is still running." % pid, file=sys.stderr)
        return 1
    pid_file.unlink(missing_ok=True)
    print("Stopped Sentinel dev server PID %s." % pid)
    return 0


def print_status(args: argparse.Namespace) -> int:
    pid_file = Path(args.pid_file)
    pid = pid_from_file(pid_file)
    if pid and process_is_running(pid):
        print("Sentinel dev server is running with PID %s." % pid)
        return 0
    if pid:
        print("Sentinel dev server is not running; stale PID file: %s." % pid_file)
        return 1
    print("Sentinel dev server is not running.")
    return 1


def main(argv: list[str] | None = None) -> None:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    ensure_local_no_proxy(args.host)
    if args.daemon:
        raise SystemExit(start_daemon(args))
    if args.stop:
        raise SystemExit(stop_daemon(args))
    if args.status:
        raise SystemExit(print_status(args))
    run_server(
        host=args.host,
        port=args.port,
        db_path=Path(args.db_path),
        static_dir=Path(args.static_dir),
    )


if __name__ == "__main__":
    main()

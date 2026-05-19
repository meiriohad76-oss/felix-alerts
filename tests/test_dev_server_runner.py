from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen
from unittest.mock import patch

from scripts import run_dev_server


ROOT = Path(__file__).resolve().parents[1]


def unused_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    try:
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def process_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def wait_for_health(port: int, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urlopen("http://127.0.0.1:%s/health" % port, timeout=0.5) as response:
                if response.status == 200:
                    return
        except (OSError, URLError) as exc:
            last_error = exc
        time.sleep(0.1)
    raise AssertionError("server did not become healthy: %r" % (last_error,))


class DevServerRunnerTests(unittest.TestCase):
    def test_local_health_checks_are_excluded_from_proxy_env(self):
        with patch.dict(
            os.environ,
            {
                "HTTP_PROXY": "http://proxy.example.com:80",
                "HTTPS_PROXY": "http://proxy.example.com:80",
                "NO_PROXY": "example.com",
                "no_proxy": "",
            },
        ):
            run_dev_server.ensure_local_no_proxy("127.0.0.1")

            self.assertIn("127.0.0.1", os.environ["NO_PROXY"].split(","))
            self.assertIn("localhost", os.environ["NO_PROXY"].split(","))
            self.assertIn("127.0.0.1", os.environ["no_proxy"].split(","))
            self.assertIn("localhost", os.environ["no_proxy"].split(","))

    def test_daemon_mode_returns_pid_serves_health_and_stops(self):
        port = unused_port()
        env = os.environ.copy()
        env["PYTHONPATH"] = "backend"

        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp, "sentinel.pid")
            log_file = Path(tmp, "sentinel.log")
            db_path = Path(tmp, "sentinel.sqlite3")

            command = [
                sys.executable,
                "scripts/run_dev_server.py",
                "--daemon",
                "--port",
                str(port),
                "--db-path",
                str(db_path),
                "--pid-file",
                str(pid_file),
                "--log-file",
                str(log_file),
            ]

            result = subprocess.run(
                command,
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(pid_file.exists(), result.stdout + result.stderr)

            pid = int(pid_file.read_text().strip())
            try:
                self.assertTrue(process_is_running(pid))
                wait_for_health(port)
            finally:
                subprocess.run(
                    [
                        sys.executable,
                        "scripts/run_dev_server.py",
                        "--stop",
                        "--pid-file",
                        str(pid_file),
                    ],
                    cwd=ROOT,
                    env=env,
                    text=True,
                    capture_output=True,
                    timeout=5,
                )
                deadline = time.time() + 5
                while process_is_running(pid) and time.time() < deadline:
                    time.sleep(0.1)
                if process_is_running(pid):
                    os.kill(pid, signal.SIGTERM)
            self.assertFalse(process_is_running(pid))


if __name__ == "__main__":
    unittest.main()

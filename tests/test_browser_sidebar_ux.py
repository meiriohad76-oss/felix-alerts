from __future__ import annotations

import http.client
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from datetime import date
from pathlib import Path
from uuid import UUID

from sentinel_core.http_api import create_server
from sentinel_core.market_data import InMemoryMarketDataProvider
from tests.factories import flat_bars, make_bar


ROOT = Path(__file__).resolve().parents[1]
BROWSER_SCRIPT = ROOT / "tests" / "browser" / "sidebar_ux_cdp_test.mjs"
FRONTEND_DIR = ROOT / "frontend"
MAC_CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def request(server, method, path, payload=None):
    host, port = server.server_address
    conn = http.client.HTTPConnection(host, port, timeout=5)
    body = json.dumps(payload or {})
    conn.request(method, path, body=body, headers={"Content-Type": "application/json"})
    response = conn.getresponse()
    data = json.loads(response.read().decode("utf-8"))
    conn.close()
    return response.status, data


def browser_test_available() -> tuple[bool, str]:
    if not shutil.which("node"):
        return False, "node is not installed"
    if not os.environ.get("CHROME_BIN") and not MAC_CHROME.exists():
        return False, "Chrome is not installed and CHROME_BIN is not set"
    try:
        completed = subprocess.run(
            ["node", "-p", "typeof WebSocket"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"node WebSocket check failed: {exc}"
    if completed.stdout.strip() != "function":
        return False, "node does not expose a WebSocket implementation"
    return True, ""


def clustered_alert_bars():
    bars = list(flat_bars(149, close=100, volume=1000))
    bars.append(make_bar(date(2025, 5, 30), close=101, open_price=101, volume=1000))
    bars.append(make_bar(date(2025, 5, 31), close=90, open_price=105, high=106, low=89, volume=6500))
    return tuple(bars)


class BrowserSidebarUxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        available, reason = browser_test_available()
        if not available:
            raise unittest.SkipTest(reason)

    def test_sidebar_routes_tooltips_and_chart_markers_in_real_browser(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = create_server(
                db_path=Path(tmp) / "sentinel-browser.sqlite3",
                port=0,
                static_dir=FRONTEND_DIR,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                status, data = request(server, "POST", "/portfolios", {"name": "Browser UX Portfolio"})
                self.assertEqual(status, 201)
                portfolio_id = data["portfolio"]["portfolio_id"]
                UUID(portfolio_id)

                csv_text = (
                    "ticker,type,shares,entry_price,current_profit_lock\n"
                    "AAPL,investor,10,110,95\n"
                    "AAOI,investor,5,178.60,\n"
                )
                status, _ = request(server, "POST", f"/portfolios/{portfolio_id}/import", {"csv_text": csv_text})
                self.assertEqual(status, 200)

                workspace = server.RequestHandlerClass.api.workspace
                workspace.backfill_market_data(
                    portfolio_id=UUID(portfolio_id),
                    provider=InMemoryMarketDataProvider.from_items([("AAPL", clustered_alert_bars())]),
                    end=date(2025, 5, 31),
                )
                status, data = request(server, "POST", f"/portfolios/{portfolio_id}/evaluate", {"asof": "2025-05-31"})
                self.assertEqual(status, 200)
                self.assertGreaterEqual(len(data["alerts"]), 1)

                host, port = server.server_address
                completed = subprocess.run(
                    [
                        "node",
                        str(BROWSER_SCRIPT),
                        "--base-url",
                        f"http://{host}:{port}",
                        "--portfolio-id",
                        portfolio_id,
                        "--ticker",
                        "AAPL",
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=45,
                )
                self.assertEqual(
                    completed.returncode,
                    0,
                    "Browser UX test failed.\nSTDOUT:\n%s\nSTDERR:\n%s"
                    % (completed.stdout, completed.stderr),
                )
                metrics = json.loads(completed.stdout)
                self.assertGreaterEqual(metrics["markers"]["count"], 3)
                self.assertEqual(metrics["markers"]["overlapCount"], 0)
                self.assertGreaterEqual(metrics["tooltip"]["fontSize"], 15)
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()

import { spawn } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { existsSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import http from "node:http";
import net from "node:net";

function parseArgs(argv) {
  const args = {};
  for (let index = 2; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith("--") || value === undefined) {
      throw new Error(`Invalid argument near ${key || "end of arguments"}`);
    }
    args[key.slice(2)] = value;
  }
  return args;
}

function chromePath() {
  const candidates = [
    process.env.CHROME_BIN,
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
  ].filter(Boolean);
  return candidates.find((candidate) => existsSync(candidate));
}

function getJson(url, options = {}) {
  return new Promise((resolve, reject) => {
    const request = http.request(url, options, (response) => {
      let body = "";
      response.setEncoding("utf8");
      response.on("data", (chunk) => {
        body += chunk;
      });
      response.on("end", () => {
        if (response.statusCode < 200 || response.statusCode >= 300) {
          reject(new Error(`${options.method || "GET"} ${url} returned ${response.statusCode}: ${body}`));
          return;
        }
        try {
          resolve(JSON.parse(body));
        } catch (error) {
          reject(new Error(`Invalid JSON from ${url}: ${error.message}`));
        }
      });
    });
    request.on("error", reject);
    request.end();
  });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function freePort() {
  return await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close(() => resolve(address.port));
    });
  });
}

function waitForProcessExit(child, timeoutMs = 3000) {
  if (child.exitCode !== null || child.signalCode !== null) {
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      resolve();
    }, timeoutMs);
    child.once("exit", () => {
      clearTimeout(timer);
      resolve();
    });
  });
}

async function waitForChrome(port, timeoutMs = 8000) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      return await getJson(`http://127.0.0.1:${port}/json/version`);
    } catch (error) {
      lastError = error;
      await sleep(120);
    }
  }
  throw new Error(`Chrome DevTools endpoint did not become ready: ${lastError?.message || "timeout"}`);
}

class CdpClient {
  constructor(wsUrl) {
    this.wsUrl = wsUrl;
    this.nextId = 1;
    this.pending = new Map();
    this.eventHandlers = new Map();
  }

  async connect() {
    this.ws = new WebSocket(this.wsUrl);
    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error("Timed out opening DevTools websocket")), 5000);
      this.ws.addEventListener("open", () => {
        clearTimeout(timeout);
        resolve();
      }, { once: true });
      this.ws.addEventListener("error", () => {
        clearTimeout(timeout);
        reject(new Error("Failed to open DevTools websocket"));
      }, { once: true });
    });
    this.ws.addEventListener("message", (message) => {
      const data = JSON.parse(message.data);
      if (data.id && this.pending.has(data.id)) {
        const { resolve, reject } = this.pending.get(data.id);
        this.pending.delete(data.id);
        if (data.error) {
          reject(new Error(`${data.error.message}: ${data.error.data || ""}`));
        } else {
          resolve(data.result || {});
        }
        return;
      }
      if (data.method && this.eventHandlers.has(data.method)) {
        for (const handler of this.eventHandlers.get(data.method)) {
          handler(data.params || {});
        }
      }
    });
  }

  on(method, handler) {
    if (!this.eventHandlers.has(method)) {
      this.eventHandlers.set(method, []);
    }
    this.eventHandlers.get(method).push(handler);
  }

  send(method, params = {}) {
    const id = this.nextId++;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
    });
  }

  async close() {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.close();
    }
  }
}

async function createTarget(port) {
  const url = `http://127.0.0.1:${port}/json/new?${encodeURIComponent("about:blank")}`;
  try {
    return await getJson(url, { method: "PUT" });
  } catch {
    return await getJson(url);
  }
}

async function evaluate(client, expression) {
  const result = await client.send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true
  });
  if (result.exceptionDetails) {
    const text = result.exceptionDetails.exception?.description || result.exceptionDetails.text || "Runtime exception";
    throw new Error(text);
  }
  return result.result?.value;
}

async function waitForEvaluation(client, description, expression, timeoutMs = 12000) {
  const deadline = Date.now() + timeoutMs;
  let lastValue;
  while (Date.now() < deadline) {
    lastValue = await evaluate(client, expression);
    if (lastValue) {
      return lastValue;
    }
    await sleep(180);
  }
  const pageState = await evaluate(client, `(() => ({
    href: location.href,
    ready: document.readyState,
    activeDisplay: document.body?.dataset?.activeDisplay || "",
    title: document.querySelector("#tickerDetailTitle")?.textContent || "",
    badge: document.querySelector("#tickerDetailBadge")?.textContent || "",
    hasChartSvg: Boolean(document.querySelector(".chart-svg")),
    markerCount: document.querySelectorAll(".chart-marker-group").length,
    bodyStart: document.body?.innerText?.slice(0, 800) || ""
  }))()`);
  throw new Error(`Timed out waiting for ${description}. Last value: ${JSON.stringify(lastValue)}. Page state: ${JSON.stringify(pageState)}`);
}

async function navigate(client, url) {
  await client.send("Page.navigate", { url });
  await waitForEvaluation(
    client,
    `document ready at ${url}`,
    `location.href === ${jsString(url)} && document.readyState === "complete"`
  );
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function jsString(value) {
  return JSON.stringify(String(value));
}

async function runBrowserChecks({ baseUrl, portfolioId, ticker }) {
  const browser = chromePath();
  assert(browser, "No supported Chrome-compatible browser was found for browser UX tests.");
  assert(typeof WebSocket === "function", "Node WebSocket support is required for CDP browser UX tests.");

  const port = await freePort();
  const userDataDir = await mkdtemp(path.join(tmpdir(), "sentinel-browser-test-"));
  const chrome = spawn(browser, [
    "--headless=new",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--no-first-run",
    "--no-default-browser-check",
    `--user-data-dir=${userDataDir}`,
    `--remote-debugging-port=${port}`,
    "about:blank"
  ], { stdio: ["ignore", "ignore", "pipe"] });

  let client;
  try {
    await waitForChrome(port);
    const target = await createTarget(port);
    client = new CdpClient(target.webSocketDebuggerUrl);
    await client.connect();
    await client.send("Page.enable");
    await client.send("Runtime.enable");
    await client.send("Emulation.setDeviceMetricsOverride", {
      width: 1440,
      height: 1100,
      deviceScaleFactor: 1,
      mobile: false
    });

    const holdingsUrl = `${baseUrl}/?view=holdings&portfolio=${encodeURIComponent(portfolioId)}`;
    await navigate(client, holdingsUrl);
    const holdingsState = await waitForEvaluation(client, "holdings route portfolio selection", `(() => {
      const portfolioSelect = document.querySelector("#portfolioSelect");
      const rows = [...document.querySelectorAll(".compact-position-row")];
      const links = [...document.querySelectorAll("a.ticker-button")].map((link) => link.getAttribute("href"));
      return document.body.dataset.activeDisplay === "holdings" && portfolioSelect?.value === ${jsString(portfolioId)} && rows.length >= 2
        ? { activeDisplay: document.body.dataset.activeDisplay, selectedPortfolio: portfolioSelect.value, rowCount: rows.length, links }
        : null;
    })()`);
    assert(
      holdingsState.links.some((href) => href.includes(`portfolio=${encodeURIComponent(portfolioId)}`) && href.includes(`ticker=${encodeURIComponent(ticker)}`)),
      "Holdings ticker links must preserve portfolio and ticker route parameters."
    );

    const stockUrl = `${baseUrl}/?view=stock&portfolio=${encodeURIComponent(portfolioId)}&ticker=${encodeURIComponent(ticker)}`;
    const clickedTickerLink = await evaluate(client, `(() => {
      const link = [...document.querySelectorAll("a.ticker-button")]
        .find((candidate) => candidate.href === ${jsString(stockUrl)});
      if (!link) return false;
      link.click();
      return true;
    })()`);
    assert(clickedTickerLink, "Holdings view must expose a clickable ticker detail link for the selected ticker.");
    await waitForEvaluation(client, "stock route after ticker click", `location.href === ${jsString(stockUrl)} && document.body.dataset.activeDisplay === "stock"`);
    const chartState = await waitForEvaluation(client, "stock detail chart rendering", `(() => {
      const svg = document.querySelector(".chart-svg");
      const markers = [...document.querySelectorAll(".chart-marker-group")];
      const title = document.querySelector("#tickerDetailTitle")?.textContent || "";
      const kpiText = document.querySelector(".chart-kpis")?.textContent || "";
      return document.body.dataset.activeDisplay === "stock" && title.includes(${jsString(ticker)}) && svg && markers.length >= 3
        ? {
            activeDisplay: document.body.dataset.activeDisplay,
            title,
            markerCount: markers.length,
            preserveAspectRatio: svg.getAttribute("preserveAspectRatio"),
            kpiText
          }
        : null;
    })()`, 20000);
    assert(chartState.preserveAspectRatio === "xMidYMid meet", "Chart SVG must preserve aspect ratio instead of stretching.");
    assert(chartState.kpiText.includes("Volume") || document.body.innerText.includes("Volume"), "Stock chart must expose volume context.");

    const tooltipMetrics = await waitForEvaluation(client, "readable visible HTML tooltip", `(() => {
      const wraps = [...document.querySelectorAll(".tooltip-wrap")].filter((candidate) => {
        const rect = candidate.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && candidate.closest(".display-panel.active");
      });
      const wrap = wraps[0];
      const content = wrap?.querySelector(".tooltip-content");
      if (!wrap || !content) return null;
      wrap.focus();
      const style = getComputedStyle(content);
      const rect = content.getBoundingClientRect();
      if (parseFloat(style.opacity) < 0.95) return null;
      return {
        fontSize: parseFloat(style.fontSize),
        lineHeight: parseFloat(style.lineHeight),
        opacity: parseFloat(style.opacity),
        width: rect.width,
        height: rect.height,
        right: rect.right,
        bottom: rect.bottom,
        viewportWidth: innerWidth,
        viewportHeight: innerHeight
      };
    })()`);
    assert(tooltipMetrics.fontSize >= 15, `HTML tooltip font is too small: ${tooltipMetrics.fontSize}`);
    assert(tooltipMetrics.lineHeight >= 20, `HTML tooltip line height is too small: ${tooltipMetrics.lineHeight}`);
    assert(tooltipMetrics.opacity >= 0.95, "Focused HTML tooltip should become visible.");
    assert(tooltipMetrics.width <= 400, `HTML tooltip is wider than expected: ${tooltipMetrics.width}`);
    assert(tooltipMetrics.right <= tooltipMetrics.viewportWidth + 2, "HTML tooltip should not overflow the viewport horizontally.");

    await evaluate(client, `(() => {
      document.querySelector(".chart-svg")?.scrollIntoView({ block: "center", inline: "center" });
      return true;
    })()`);
    await sleep(180);

    const markerHoverPoint = await waitForEvaluation(client, "chart marker hover point", `(() => {
      const group = document.querySelector(".chart-marker-group");
      const shape = group?.querySelector(".chart-marker-shape");
      if (!shape) return null;
      const rect = shape.getBoundingClientRect();
      return {
        x: rect.x + rect.width / 2,
        y: rect.y + rect.height / 2
      };
    })()`);
    await client.send("Input.dispatchMouseEvent", {
      type: "mouseMoved",
      x: markerHoverPoint.x,
      y: markerHoverPoint.y
    });
    await sleep(180);

    const markerMetrics = await waitForEvaluation(client, "decluttered chart markers", `(() => {
      const groups = [...document.querySelectorAll(".chart-marker-group")];
      if (groups.length < 3) return null;
      const shapeRects = groups.map((group) => {
        const shape = group.querySelector(".chart-marker-shape");
        const rect = shape.getBoundingClientRect();
        return {
          index: group.getAttribute("data-marker-index"),
          date: group.getAttribute("data-marker-date"),
          aria: group.getAttribute("aria-label") || "",
          className: group.getAttribute("class") || "",
          x: rect.x,
          y: rect.y,
          width: rect.width,
          height: rect.height,
          right: rect.right,
          bottom: rect.bottom
        };
      });
      const sameDateDates = shapeRects.reduce((map, rect) => {
        map[rect.date] = (map[rect.date] || 0) + 1;
        return map;
      }, {});
      const overlaps = [];
      for (let i = 0; i < shapeRects.length; i += 1) {
        for (let j = i + 1; j < shapeRects.length; j += 1) {
          const a = shapeRects[i];
          const b = shapeRects[j];
          const overlapX = Math.max(0, Math.min(a.right, b.right) - Math.max(a.x, b.x));
          const overlapY = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.y, b.y));
          if (overlapX * overlapY > 4) {
            overlaps.push({ a: a.index, b: b.index, area: overlapX * overlapY });
          }
        }
      }
      const tooltip = groups[0].querySelector(".chart-marker-tooltip");
      const tooltipText = tooltip?.querySelector("text");
      const tooltipRect = tooltip?.querySelector("rect");
      const tooltipStyle = tooltip ? getComputedStyle(tooltip) : null;
      const tooltipTextStyle = tooltipText ? getComputedStyle(tooltipText) : null;
      const tooltipRectStyle = tooltipRect ? getComputedStyle(tooltipRect) : null;
      const tooltipBox = tooltipRect?.getBBox();
      const uniqueY = new Set(shapeRects.map((rect) => Math.round(rect.y)));
      const firstShape = groups[0].querySelector(".chart-marker-shape");
      const firstRect = firstShape.getBoundingClientRect();
      const hoverElement = document.elementFromPoint(firstRect.x + firstRect.width / 2, firstRect.y + firstRect.height / 2);
      return {
        count: groups.length,
        shapeRects,
        sameDateDates,
        overlaps,
        uniqueYCount: uniqueY.size,
        groupHover: groups[0].matches(":hover"),
        shapeHover: firstShape.matches(":hover"),
        hoverElement: hoverElement?.getAttribute("class") || hoverElement?.tagName || "",
        hoveredTooltipOpacity: tooltipStyle ? parseFloat(tooltipStyle.opacity) : 0,
        tooltipFontSize: tooltipTextStyle ? parseFloat(tooltipTextStyle.fontSize) : 0,
        tooltipBoxWidth: tooltipBox?.width || 0,
        tooltipBackgroundOpacity: tooltipRectStyle ? parseFloat(tooltipRectStyle.fillOpacity) : 0,
        tooltipText: tooltip?.textContent || ""
      };
    })()`);
    assert(markerMetrics.count >= 3, `Expected at least 3 chart markers; got ${markerMetrics.count}`);
    assert(markerMetrics.overlaps.length === 0, `Chart marker shapes overlap: ${JSON.stringify(markerMetrics.overlaps)}`);
    assert(markerMetrics.uniqueYCount >= Math.min(3, markerMetrics.count), "Clustered chart markers should occupy separate visual lanes.");
    assert(markerMetrics.shapeRects.every((rect) => rect.index !== null && rect.aria.length > 80), "Every chart marker needs index metadata and an explanatory aria label.");
    assert(markerMetrics.hoveredTooltipOpacity >= 0.95, `Hovered SVG marker tooltip should become visible: ${JSON.stringify(markerMetrics)}`);
    assert(markerMetrics.tooltipFontSize >= 16, `SVG marker tooltip font is too small: ${markerMetrics.tooltipFontSize}`);
    assert(markerMetrics.tooltipBoxWidth >= 500, `SVG marker tooltip box is too narrow: ${markerMetrics.tooltipBoxWidth}`);
    assert(markerMetrics.tooltipBackgroundOpacity >= 0.9, `SVG marker tooltip background is too transparent: ${JSON.stringify(markerMetrics)}`);
    assert(!markerMetrics.tooltipText.includes("..."), `SVG marker tooltip text should not be truncated: ${markerMetrics.tooltipText}`);

    const result = {
      holdings: holdingsState,
      chart: chartState,
      tooltip: tooltipMetrics,
      markers: {
        count: markerMetrics.count,
        uniqueYCount: markerMetrics.uniqueYCount,
        overlapCount: markerMetrics.overlaps.length,
        tooltipFontSize: markerMetrics.tooltipFontSize,
        tooltipBoxWidth: markerMetrics.tooltipBoxWidth
      }
    };
    console.log(JSON.stringify(result, null, 2));
  } finally {
    await client?.close();
    chrome.kill("SIGTERM");
    await waitForProcessExit(chrome);
    await rm(userDataDir, { recursive: true, force: true });
  }
}

const args = parseArgs(process.argv);
await runBrowserChecks({
  baseUrl: args["base-url"],
  portfolioId: args["portfolio-id"],
  ticker: args.ticker || "AAPL"
});

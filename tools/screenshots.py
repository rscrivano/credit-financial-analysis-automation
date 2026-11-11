"""Capture report/slide screenshots of the running app with headless Edge or Chrome (no AI tokens).

    python tools/screenshots.py --out ../docs/evidence/screenshots

Starts the app with CFAA_CACHE_ONLY=1 (cached AI work only, never a new AI call), drives it through the Chrome
DevTools Protocol, and saves full-width PNGs. Every wait has a timeout and each step runs once: a failed step is
reported and skipped, never retried in a loop. Needs `pip install websocket-client` (dev only).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websocket

ROOT = Path(__file__).resolve().parent.parent
BROWSERS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe"]
APP = "http://127.0.0.1:8050/"
W = 1440


class CDP:
    def __init__(self, ws_url):
        self.ws, self.n = websocket.create_connection(ws_url, timeout=60, suppress_origin=True), 0

    def send(self, method, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error'].get('message')}")
                return msg.get("result", {})

    def js(self, expr):
        r = self.send("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        return r.get("result", {}).get("value")

    def wait(self, cond, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            if self.js(f"!!({cond})"):
                return True
            time.sleep(0.5)
        raise TimeoutError(f"timed out waiting for {cond}")

    def nav(self, url):
        self.send("Page.navigate", url=url)
        time.sleep(1.5)
        self.wait("document.readyState === 'complete'", 30)

    def type_into(self, selector, text):
        self.js(f"(() => {{ const e = document.querySelector({json.dumps(selector)}); e.focus(); e.select && e.select(); }})()")
        self.send("Input.insertText", text=text)
        for t in ("keyDown", "keyUp"):
            self.send("Input.dispatchKeyEvent", type=t, key="Tab", code="Tab", windowsVirtualKeyCode=9)

    def click_text(self, selector, text):
        ok = self.js(f"""(() => {{ const el = [...document.querySelectorAll({json.dumps(selector)})]
            .find(x => x.innerText.trim().toUpperCase().startsWith({json.dumps(text.upper())})); if (el) el.click(); return !!el; }})()""")
        if not ok:
            raise RuntimeError(f"no {selector} starting with {text!r}")
        time.sleep(1.2)

    def shot(self, path, max_h=3200, selector=None):
        if selector:
            box = self.js(f"""(() => {{ const r = document.querySelector({json.dumps(selector)}).getBoundingClientRect();
                return [r.left + scrollX, r.top + scrollY, r.width, r.height]; }})()""")
            clip = {"x": max(box[0] - 8, 0), "y": max(box[1] - 8, 0), "width": min(box[2] + 16, W), "height": min(box[3] + 16, max_h), "scale": 1}
        else:
            h = self.js("document.documentElement.scrollHeight")
            clip = {"x": 0, "y": 0, "width": W, "height": min(h, max_h), "scale": 1}
        data = self.send("Page.captureScreenshot", format="png", captureBeyondViewport=True, clip=clip)["data"]
        Path(path).write_bytes(base64.b64decode(data))


def up(url, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=3)
            return True
        except OSError:
            time.sleep(1)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT.parent / "docs" / "evidence" / "screenshots"))
    ap.add_argument("--ticker", default="NVDA", help="a company whose AI analysis is already cached")
    ap.add_argument("--compare", default="LUV,ULCC,DAL")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "CFAA_CACHE_ONLY": "1", "OPENAI_MODEL": os.environ.get("OPENAI_MODEL") or "gpt-6-luna"}
    app = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    prof = tempfile.mkdtemp(prefix="cfaa_shots_")
    exe = next(b for b in BROWSERS if Path(b).is_file())
    br = subprocess.Popen([exe, "--headless=new", "--remote-debugging-port=9333", f"--user-data-dir={prof}",
                           f"--window-size={W},1000", "--hide-scrollbars", "about:blank"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    done, failed = [], []
    try:
        if not (up(APP) and up("http://127.0.0.1:9333/json/version")):
            raise SystemExit("app or browser did not start")
        page = next(t for t in json.loads(urllib.request.urlopen("http://127.0.0.1:9333/json").read()) if t["type"] == "page")
        c = CDP(page["webSocketDebuggerUrl"])
        c.send("Page.enable")
        c.send("Emulation.setDeviceMetricsOverride", width=W, height=1000, deviceScaleFactor=1, mobile=False)

        def step(name, fn):
            try:
                fn()
                done.append(name)
            except Exception as e:  # one attempt per step: report and move on
                failed.append(f"{name}: {type(e).__name__}: {str(e)[:120]}")

        def landing():
            c.nav(APP)
            c.wait("document.querySelector('.steps')")
            c.shot(out / "01_start_page.png", 1250)

        def company():
            c.type_into("#ticker", a.ticker)
            c.js("document.getElementById('go').click()")
            c.wait("document.querySelector('.kpis')", 120)
            time.sleep(2)
            c.shot(out / "02_summary.png", 2600, selector="#results")
            for tab, fn in (("2 SWOT", "03_swot"), ("3 CREDIT", "04_credit"), ("4 DEBT", "05_debt_structure"),
                            ("7 SECTOR", "06_sector_peers"), ("11 AGENTS", "07_agents")):
                c.click_text(".tab", tab)
                c.js("scrollTo(0, 0)")
                c.shot(out / f"{fn}.png", 2600, selector="#results")

        def chat():
            c.js("document.getElementById('{\"i\":0,\"type\":\"chip\"}').click()")
            time.sleep(1)
            c.js("document.getElementById('chat-go').click()")
            c.wait("document.querySelector('.chat-a')", 30)
            c.shot(out / "08_chat_starter_answer.png", selector="#chat-wrap")

        def export_bar():
            c.shot(out / "09_export_bar.png", selector="#actions")

        def compare():
            c.click_text("#pub-mode label", "Compare")
            tickers = a.compare.split(",")
            for _ in tickers[2:]:
                c.js("document.getElementById('cmp-add').click()")
                time.sleep(1)
            for i, t in enumerate(tickers):
                c.type_into(f"[id='{{\"i\":{i},\"type\":\"cmp\"}}']", t)
            c.js("document.getElementById('cmp-go').click()")
            c.wait("document.querySelector('#pick-wrap') && getComputedStyle(document.querySelector('#pick-wrap')).display !== 'none'", 180)
            time.sleep(2)
            c.shot(out / "10_comparison.png", 3200, selector="#results")

        def private():
            c.click_text("#mode label", "Private")
            doc = c.send("DOM.getDocument")
            node = c.send("DOM.querySelector", nodeId=doc["root"]["nodeId"], selector="#upload input[type=file]")
            c.send("DOM.setFileInputFiles", nodeId=node["nodeId"],
                   files=[str(ROOT / "data" / "samples" / "sample_private_reviewed_statements.pdf")])
            c.wait("[...document.querySelectorAll('h3')].some(h => h.innerText.toUpperCase().includes('CONFIRM WHAT'))", 60)
            time.sleep(1)
            c.shot(out / "11_private_review.png", 2600, selector="#review")
            c.js("document.querySelector('#sector input').focus()")
            c.send("Input.insertText", text="Airlines")
            time.sleep(0.8)
            for t in ("keyDown", "keyUp"):
                c.send("Input.dispatchKeyEvent", type=t, key="Enter", code="Enter", windowsVirtualKeyCode=13)
            time.sleep(1)
            c.js("document.getElementById('{\"name\":\"map-confirm\",\"type\":\"btn\"}').click()")
            c.wait("document.querySelector('.kpis')", 120)
            c.click_text(".tab", "8 ACCOUNTING")
            c.js("scrollTo(0, 0)")
            c.shot(out / "12_private_red_flags.png", 2600, selector="#results")

        def docs():
            for f, n in (("agent_design.html", "13_agent_design_diagram"), ("user_guide.html", "14_user_guide")):
                c.nav((ROOT / "docs" / f).as_uri())
                c.shot(out / f"{n}.png", 1500)

        for name, fn in (("start page", landing), ("company tabs", company), ("chat", chat), ("export bar", export_bar),
                         ("comparison", compare), ("private upload", private), ("documents", docs)):
            step(name, fn)
    finally:
        subprocess.run(["taskkill", "/PID", str(br.pid), "/T", "/F"], capture_output=True)  # whole browser tree
        subprocess.run(["powershell", "-NoProfile", "-Command",  # helpers that outlive the tree (only this run's profile)
                        "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*cfaa_shots_*' } | "
                        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"], capture_output=True)
        subprocess.run(["taskkill", "/PID", str(app.pid), "/T", "/F"], capture_output=True)
        shutil.rmtree(prof, ignore_errors=True)
    print("done:", ", ".join(done))
    print("failed:", "; ".join(failed) or "none")


if __name__ == "__main__":
    main()

"""Credit/Financial Analysis Automation — web app (Dash).

Run:  python app.py   then open http://127.0.0.1:8050
"""
from __future__ import annotations

import base64
import hashlib
import json
import tempfile
from pathlib import Path

import openpyxl
from dash import ALL, Dash, Input, Output, Patch, State, ctx, dcc, html, no_update

from credit_engine.compare import MAX_COMPANIES, run_comparison
from credit_engine.edgar import EdgarError, normalize_ticker
from credit_engine.ingest import ingest
from credit_engine.llm import get_model
from credit_engine.mapper import FIELD_NAMES, build_periods
from credit_engine.pipeline import run, run_periods, run_workbook
from credit_engine.pipeline import STATEMENT_LINES
from credit_engine.security import (Rejected, ai_allowed_today, bad_agency_entries, check_upload, harden_server,
                                     rate_limit, sanitize_choices, sanitize_overrides)
from credit_engine.sector import sector_options
from credit_engine.team import map_labels
from credit_engine import chat as chatmod
from credit_engine import export, watch
from views import chat_log, comparison_view, landing, report_view, review_view, swot_items, watch_table

APP_NAME = "Credit/Financial Analysis Automation"
MAX_UPLOAD_BYTES = 10_000_000
PINK = "#ffa028"  # terminal amber

app = Dash(__name__, title=APP_NAME, suppress_callback_exceptions=True,
           meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}])
server = app.server
harden_server(server)  # security headers, request-size cap, optional APP_PASSWORD
SECTOR_KEYS = {o["value"] for o in sector_options()}
STATEMENT_FIELDS = {f for f, _ in STATEMENT_LINES}

CHIPS = ["Why did it get this rating?", "What are the biggest credit risks?", "How does it compare with its peers?",
         "What would move the rating up or down?"]


def _cmp_input(i, placeholder=""):
    return html.Div(className="cmd", children=[html.Span(f"{i + 1}>", className="prompt"),
                                                dcc.Input(id={"type": "cmp", "i": i}, type="text", placeholder=placeholder,
                                                          maxLength=10, debounce=True, name=f"ticker{i + 1}")])


app.layout = html.Div(className="wrap", children=[
    html.Header(className="topbar", children=[
        html.Div([html.Span("CFAA", className="brand"), html.Span("Credit/Financial Analysis Automation", className="title")]),
        html.Div("CREDIT · SECTOR · MACRO", className="tagbar")]),
    html.Div(className="hero", children=[
        html.H2("Turn SEC filings or a private company's statements into a full credit, industry and economic analysis in minutes."),
        html.P("An add-on for credit and investment analysts. Code calculates every number and rating; a team of AI analysts "
               "writes the narrative, and every figure they cite is checked against the data.", className="sub")]),
    html.Details(className="guide", children=[
        html.Summary("? HOW TO USE THIS APP"),
        html.Ol([html.Li("Choose Public company (SEC data by ticker) or Private company (upload statements)."),
                 html.Li("Public: Single ticker → type a ticker → GO. Or Compare companies → enter 2+ tickers → COMPARE."),
                 html.Li("Private: upload Excel/PDF statements → check the lines the app read → pick the sector → Confirm & analyze."),
                 html.Li("Read tab 1 SUMMARY first, then go deeper: each tab starts with a line explaining what it shows."),
                 html.Li("Fix anything: edit statements (tab 5), answer open decisions (tab 10), add your Analyst case (tab 3)."),
                 html.Li("Ask the analyst at the bottom; EXPORT to Excel or a credit memo; + Watchlist to track new filings."),
                 html.Li("Untick AI analyst team to explore for free (ratings and data still work).")], className="small")]),
    dcc.RadioItems(id="mode", value="public", className="segment", inline=True,
                   options=[{"label": "Public company", "value": "public"}, {"label": "Private company", "value": "private"}]),
    html.Div(className="card", children=[
        html.Div(className="instruct", children=[
            html.Span("TO START", className="instruct-tag"),
            html.Span([html.B("1"), " Type the ticker of the company you want to research", html.Span(" → ", className="arrow"),
                       html.B("2"), " Press GO", html.Span(" → ", className="arrow"),
                       html.B("3"), " Check the industry sector it detected; if it's wrong, pick the right one and the analysis updates",
                       html.Span("   (Private company: upload the statements, then pick the sector)", className="muted")])]),
        dcc.RadioItems(id="pub-mode", value="single", className="segment small-seg", inline=True,
                       options=[{"label": "Single ticker", "value": "single"}, {"label": "Compare companies", "value": "compare"}]),
        html.Div(id="cmp-in", style={"display": "none"}, children=[
            html.Div(id="cmp-list", className="cmp-list", children=[_cmp_input(0, "LUV"), _cmp_input(1, "ULCC")]),
            html.Div(className="opts", style={"marginTop": "8px"}, children=[
                html.Button("+ Add company", id="cmp-add", className="btn ghost", n_clicks=0),
                html.Button("COMPARE", id="cmp-go", className="btn", n_clicks=0),
                html.Span(f"Up to {MAX_COMPANIES} companies. Figures for each company use code only; one AI call writes "
                          "the comparison.", className="muted small")])]),
        html.Div(id="public-in", className="controls", children=[
            html.Div([html.Label("Step 1 · Ticker of the company to research", htmlFor="ticker"),
                      html.Div(className="cmd", children=[html.Span(">", className="prompt"),
                                                          dcc.Input(id="ticker", type="text", placeholder="LUV", maxLength=10, n_submit=0)])]),
            html.Button("GO", id="go", className="btn", n_clicks=0),
            html.Div(className="muted small", children="Pulls the latest 10-K/10-Q and XBRL financials from SEC EDGAR.")]),
        html.Div(id="private-in", style={"display": "none"}, children=[
            html.Span("Upload the company's financial statements (Excel or PDF, including notes)", className="label"),
            dcc.Upload(id="upload", className="upload", max_size=MAX_UPLOAD_BYTES, accept=".xlsx,.pdf",
                       children=html.Div(["Drop audited, reviewed or management statements here, or ", html.A("browse")])),
            html.Div(className="muted small", style={"marginTop": "6px"},
                     children="The app reads the statements and notes, shows you what it read to confirm, then analyzes. "
                              "You can correct any number in the app afterwards.")]),
        html.Div(className="controls", style={"marginTop": "12px", "gridTemplateColumns": "1.4fr 1fr"}, children=[
            html.Div([html.Label("Step 3 · Industry sector (detected after GO for public companies; check it and change if needed. Pick one for private)",
                                 htmlFor="sector"),
                      dcc.Dropdown(id="sector", options=sector_options(), placeholder="Select a sector", className="dd")]),
            html.Div(className="opts", style={"marginTop": "18px"}, children=[
                dcc.Checklist(id="use-ai", options=[{"label": "AI analyst team (writes the analysis; uses tokens)", "value": "ai"}],
                              value=["ai"], inline=True),
                dcc.RadioItems(id="view", inline=True, value="all",
                               options=[{"label": "All periods", "value": "all"}, {"label": "Annual", "value": "Annual"},
                                        {"label": "Quarterly", "value": "Quarter"}])]),
        ]),
    ]),
    dcc.Store(id="report"), dcc.Store(id="request"), dcc.Store(id="mapping"), dcc.Store(id="compare"),
    dcc.Store(id="watch", storage_type="local"), dcc.Store(id="chat-hist"), dcc.Download(id="dl"),
    html.Div(id="actions", className="actions", style={"display": "none"}, children=[
        html.Span("EXPORT", className="label"),
        html.Button("Excel", id="exp-xlsx", className="btn ghost", n_clicks=0),
        html.Button("Memo (Word)", id="exp-docx", className="btn ghost", n_clicks=0),
        html.Button("Memo (PDF)", id="exp-pdf", className="btn ghost", n_clicks=0),
        html.Button("+ Watchlist", id="watch-add", className="btn ghost", n_clicks=0)]),
    html.Div(id="pick-wrap", style={"display": "none"}, children=[
        html.Span("VIEW", className="label"),
        dcc.RadioItems(id="cmp-pick", className="segment", inline=True, options=[], value="CMP")]),
    dcc.Loading(html.Div(id="status"), type="dot", color=PINK),
    html.Div(id="rerun-wrap", className="alert info", style={"display": "none"}, children=[
        html.Span(id="rerun-text"), " ", html.Button("Re-run analysts", id="rerun", className="btn ghost", n_clicks=0)]),
    html.Div(id="review"),
    html.Div(id="results"),
    html.Div(id="chat-wrap", className="card chat", style={"display": "none"}, children=[
        html.H3("ASK THE ANALYST"),
        html.Div(className="opts", children=[
            html.Button(q, id={"type": "chip", "i": i}, className="btn ghost tiny", n_clicks=0)
            for i, q in enumerate(CHIPS)]),
        dcc.Loading(html.Div(id="chat-log"), type="dot", color=PINK),
        html.Div(className="chat-in", children=[
            html.Span(">", className="prompt"),
            dcc.Textarea(id="chat-q", placeholder="Ask a question about this analysis…", maxLength=600, rows=2),
            html.Button("ASK", id="chat-go", className="btn", n_clicks=0)]),
        html.Div(id="chat-msg")]),
    html.Details(className="card watch", children=[
        html.Summary(id="watch-title", children="WATCHLIST"),
        html.Div(className="opts", children=[
            html.Button("Check for new filings", id="watch-check", className="btn ghost", n_clicks=0),
            html.Span("Checks SEC for a newer 10-K / 10-Q; companies with one are re-scored (code only, no AI tokens). "
                      "The list is saved in this browser.", className="muted small")]),
        dcc.Loading(html.Div(id="watch-msg"), type="dot", color=PINK),
        html.Div(id="watch-table")]),
    html.P("Implied ratings, not official S&P ratings. Some of the weighting benchmarks in the analysis are drawn "
           "from S&P's rating methodology.", className="disclaimer"),
])


@app.callback(Output("public-in", "style"), Output("private-in", "style"), Output("pub-mode", "style"),
              Output("cmp-in", "style"), Output("pick-wrap", "style"),
              Input("mode", "value"), Input("pub-mode", "value"), Input("compare", "data"))
def toggle_mode(mode, pub, cmp):
    hide, pub_on, cmp_on = {"display": "none"}, mode == "public", mode == "public" and pub == "compare"
    return ({"display": "grid"} if pub_on and not cmp_on else hide, hide if pub_on else {"display": "block"},
            {"display": "flex"} if pub_on else hide, {"display": "block"} if cmp_on else hide,
            {"display": "flex"} if cmp_on and cmp else hide)


@app.callback(Output("cmp-list", "children"), Input("cmp-add", "n_clicks"), State({"type": "cmp", "i": ALL}, "id"),
              prevent_initial_call=True)
def add_company(_n, ids):
    if len(ids) >= MAX_COMPANIES:
        return no_update
    p = Patch()
    p.append(_cmp_input(max(i["i"] for i in ids) + 1))
    return p


@app.callback(Output("compare", "data"), Output("cmp-pick", "options"), Output("cmp-pick", "value"),
              Output("status", "children", allow_duplicate=True),
              Input("cmp-go", "n_clicks"), State({"type": "cmp", "i": ALL}, "value"), State("use-ai", "value"),
              prevent_initial_call=True)
def compare(_n, values, use_ai):
    nu = no_update
    try:
        tickers = []
        for v in values or []:
            if (v or "").strip():
                t = normalize_ticker(v)  # forged or malformed input never reaches a URL
                if t not in tickers:
                    tickers.append(t)
        if len(tickers) < 2:
            return nu, nu, nu, html.Div("Enter at least two different tickers.", className="alert err")
        if len(tickers) > MAX_COMPANIES:
            raise Rejected(f"Compare up to {MAX_COMPANIES} companies at a time.")
        from flask import request as http
        client = http.remote_addr or "local"
        rate_limit(client)
        ai_on = "ai" in (use_ai or [])
        if ai_on:
            if not ai_allowed_today():
                ai_on = False
            else:
                rate_limit(client, "ai")
        c = run_comparison(tickers, use_ai=ai_on)
        if len(c["metrics"]) < 2:
            return nu, nu, nu, html.Div(" ".join(f"{t}: {e}" for t, e in c["errors"].items()) or
                                        "Fewer than two companies could be rated.", className="alert err")
        opts = [{"label": "COMPARISON", "value": "CMP"}] + [{"label": m["ticker"], "value": m["ticker"]} for m in c["metrics"]]
        return c, opts, "CMP", None
    except (EdgarError, Rejected) as e:
        return nu, nu, nu, html.Div(str(e), className="alert err")
    except Exception as e:  # never show a stack trace
        return nu, nu, nu, html.Div(f"Something went wrong: {type(e).__name__}. Try again.", className="alert err")


@app.callback(Output("report", "data", allow_duplicate=True), Output("request", "data", allow_duplicate=True),
              Input("cmp-pick", "value"), State("compare", "data"), prevent_initial_call=True)
def pick_company(pick, c):
    if not c or pick not in (c.get("reports") or {}):
        return no_update, no_update
    return c["reports"][pick], {"mode": "ticker", "ticker": pick, "choices": {}, "overrides": {}}


# ---------- helpers ----------

def _is_template(path: str) -> bool:
    try:
        wb = openpyxl.load_workbook(path, read_only=True)
        return "Inputs" in wb.sheetnames and str(wb["Inputs"]["B7"].value).strip() == "Revenue"
    except Exception:
        return False


def _choices(values, ids, base):
    ch = json.loads(json.dumps(base or {}))
    for v, i in zip(values, ids):
        key = i["key"]
        if key.startswith("obs_include."):
            ch.setdefault("obs_include", {})[key.split(".", 1)[1]] = float(v)
        elif key in ("lease_interest_share", "floating_share"):
            ch[key] = float(v)
        else:
            ch[key] = v
    return ch


def _apply_edits(mapping, tables, values):
    t = {i["name"]: d for d, i in zip(*tables)}
    v = {i["name"]: d for d, i in zip(*values)}
    m = json.loads(json.dumps(mapping))
    for row in t.get("rows", []):
        m["rows"][row["i"]]["field"] = row.get("field") or None
    by = {p["key"]: p for p in t.get("periods", [])}
    for p in m["periods"]:
        e = by.get(p["key"], {})
        p["end"], p["months"] = e.get("end", p["end"]), int(e.get("months") or p["months"])
        p["quality"] = v.get("quality") or m.get("quality") or "Management"
    m["quality"] = v.get("quality") or m.get("quality")
    m["company"] = v.get("company") or m.get("company")
    m["flip"] = "flip" in (v.get("flip") or [])
    return m


def _run(req, use_ai, run_analysts):
    from flask import request as http
    client = http.remote_addr or "local"
    rate_limit(client)
    if use_ai and run_analysts:
        if not ai_allowed_today():
            raise Rejected("Today's AI token ceiling for this app has been reached; ratings and data still work with AI off.")
        rate_limit(client, "ai")
    req["choices"] = sanitize_choices(req.get("choices"), SECTOR_KEYS)  # browser values can be forged: re-validate
    ch, ov = req["choices"], req.get("overrides", {})
    kw = dict(use_ai=use_ai, choices=ch, run_analysts=run_analysts, overrides=ov)
    if req["mode"] == "ticker":
        return run(req["ticker"], **kw)
    if req["mode"] == "workbook":
        return run_workbook(req["path"], **kw)
    m = req["mapping"]
    periods, notes = build_periods(m, flip_signs=m.get("flip", True))
    meta = {"sector": ch.get("sector"), "notes_excerpt": m.get("notes_excerpt", ""), "quality": m.get("quality"),
            "unit_note": m.get("unit_note"), "text_flags": m.get("text_flags", {})}
    rep = run_periods(m.get("company") or "Private company", periods, meta=meta,
                      source=f"uploaded statements ({m.get('source_file', 'file')})", **kw)
    for n in notes + [m.get("unit_note", "")]:
        if n:
            rep["uncertainties"].append({"id": "mapping", "severity": "info", "area": "Statements", "title": "How the file was read",
                                         "detail": n, "impact": "", "options": [], "choice_key": None, "chosen": None})
    return rep


def _carry(rep, prev):
    """Option changes and edits re-score with code; the analysts' previous text is kept (marked stale)."""
    if prev and prev.get("team"):
        acc = (prev["team"].get("outputs") or {}).get("accounting")
        rep["team"] = prev["team"]
        if acc and not rep["off_balance_sheet"]["items"]:
            rep["off_balance_sheet"]["items"] = acc.get("obs_items", [])
    return rep


# ---------- main callback ----------

@app.callback(
    Output("report", "data"), Output("request", "data"), Output("status", "children"), Output("mapping", "data"),
    Output("sector", "value"),
    Input("go", "n_clicks"), Input("ticker", "n_submit"), Input("upload", "contents"),
    Input({"type": "choice", "key": ALL}, "value"), Input("rerun", "n_clicks"), Input("sector", "value"),
    Input({"type": "btn", "name": ALL}, "n_clicks"),
    State("upload", "filename"), State("ticker", "value"), State("use-ai", "value"), State("request", "data"),
    State("report", "data"), State("mapping", "data"), State({"type": "choice", "key": ALL}, "id"),
    State({"type": "micro", "key": ALL}, "value"), State({"type": "micro", "key": ALL}, "id"),
    State({"type": "mapt", "name": ALL}, "data"), State({"type": "mapt", "name": ALL}, "id"),
    State({"type": "mapv", "name": ALL}, "value"), State({"type": "mapv", "name": ALL}, "id"),
    State({"type": "stmt", "name": ALL}, "data"),
    State({"type": "agency", "key": ALL}, "value"), State({"type": "agency", "key": ALL}, "id"),
    State({"type": "case", "key": ALL}, "value"), State({"type": "case", "key": ALL}, "id"),
    prevent_initial_call=True)
def analyze(_go, _submit, upload, choice_values, _rerun, sector, _btns, filename, ticker, use_ai, req, prev, mapping,
            choice_ids, micro_vals, micro_ids, map_data, map_tids, map_vals, map_vids, stmt_data, agency_vals, agency_ids,
            case_vals, case_ids):
    trig = ctx.triggered_id
    ai_on = "ai" in (use_ai or [])
    nu = no_update
    btn = trig.get("name") if isinstance(trig, dict) and trig.get("type") == "btn" else None
    if isinstance(trig, dict) and trig.get("type") == "btn" and not any(_btns or []):
        return nu, nu, nu, nu, nu  # buttons just rendered, not clicked
    try:
        if trig in ("go", "ticker"):
            if not (ticker or "").strip():
                return nu, nu, html.Div("Enter a ticker first.", className="alert err"), nu, nu
            req = {"mode": "ticker", "ticker": ticker.strip(), "choices": {}, "overrides": {}}
            rep = _run(req, ai_on, True)
            return rep, req, None, None, rep.get("sector_key")

        if trig == "upload":
            ext = Path(filename or "").suffix.lower()
            if ext not in (".xlsx", ".pdf"):
                return nu, nu, html.Div("Please upload an Excel (.xlsx) or PDF file.", className="alert err"), nu, nu
            raw = base64.b64decode(upload.split(",", 1)[1])
            check_upload(raw, ext)  # real file type, size, zip bombs, macros, PDF scripts
            path = Path(tempfile.gettempdir()) / f"cfaa_{hashlib.sha256(raw).hexdigest()[:12]}{ext}"
            path.write_bytes(raw)
            if ext == ".xlsx" and _is_template(str(path)):
                req = {"mode": "workbook", "path": str(path), "choices": {"sector": sector} if sector else {}, "overrides": {}}
                rep = _run(req, ai_on, True)
                return rep, req, None, None, rep.get("sector_key")
            m = json.loads(json.dumps(ingest(str(path), filename), default=str))
            if not m["periods"] or not m["rows"]:
                return nu, nu, html.Div("Couldn't find statement lines with period columns (years or dates) in this file. "
                                        "Scanned PDFs (images) aren't supported yet; use a text PDF or Excel.", className="alert err"), nu, nu
            return None, {"mode": "review"}, None, m, nu

        if btn in ("map-ai", "map-confirm"):
            if not mapping:
                return nu, nu, nu, nu, nu
            m = _apply_edits(mapping, (map_data, map_tids), (map_vals, map_vids))
            if btn == "map-ai":
                if not ai_on:
                    return nu, nu, html.Div("Turn on the AI analyst team to map lines automatically.", className="alert err"), nu, nu
                from flask import request as http
                if not ai_allowed_today():
                    raise Rejected("Today's AI token ceiling for this app has been reached; map the lines by hand.")
                rate_limit(http.remote_addr or "local", "ai")
                ai = {"usage": [], "tasks": []}
                todo = sorted({r["label"] for r in m["rows"] if not r["field"]})
                out, esc = map_labels(get_model(), ai, todo, FIELD_NAMES)
                got = {x.label: x.field for x in (out.mappings if out else []) if x.field in FIELD_NAMES}
                for r in m["rows"]:
                    if not r["field"] and got.get(r["label"]):
                        r.update(field=got[r["label"]], method="Accounting Analyst")
                used = sum(u["input_tokens"] + u["output_tokens"] for u in ai["usage"])
                msg = f"Accounting Analyst mapped {len(got)} line(s) ({used:,} tokens). Review and confirm." if out else \
                    f"The Accounting Analyst couldn't map these after 3 attempts: {esc[0]['issue'] if esc else ''}. Map them by hand."
                return nu, nu, html.Div(msg, className="alert info"), m, nu
            if not sector:
                return nu, nu, html.Div("Pick the company's sector first (dropdown above).", className="alert err"), nu, nu
            req = {"mode": "mapped", "mapping": m, "choices": {"sector": sector}, "overrides": {}}
            return _run(req, ai_on, True), req, None, None, nu

        if not req or req.get("mode") == "review" or not prev:
            return nu, nu, nu, nu, nu

        req = json.loads(json.dumps(req))
        if trig == "rerun":
            rep = _run(req, ai_on, True)
            return rep, req, None, nu, nu

        if btn in ("recalc", "undo"):
            if btn == "undo":
                req["overrides"] = {}
            else:
                base = {row["field"]: row for row in prev["statements"]["rows"]}
                for row in (r for table in (stmt_data or []) for r in table if r.get("field") in base):  # P&L, BS, CF
                    for period in prev["statements"]["periods"]:
                        new, old = row.get(period), base.get(row["field"], {}).get(period)
                        if new != old:
                            req["overrides"].setdefault(period, {})[row["field"]] = new
                req["overrides"] = sanitize_overrides(req["overrides"], set(prev["statements"]["periods"]), STATEMENT_FIELDS)
            return _carry(_run(req, ai_on, False), prev), req, None, nu, nu

        # Options: only those the user actually changed (new option buttons also fire this callback)
        shown = {u["choice_key"]: (u["chosen"] if u["chosen"] is not None else (u["options"] or [{}])[0].get("value"))
                 for u in prev.get("uncertainties", []) if u.get("choice_key")}
        changed = [(v, i) for v, i in zip(choice_values, choice_ids) if v != shown.get(i["key"])]
        if isinstance(trig, dict) and trig.get("type") == "choice" and not changed:
            return nu, nu, nu, nu, nu
        req["choices"] = _choices([v for v, _ in changed], [i for _, i in changed], req.get("choices"))
        if trig == "sector":
            if not sector or sector == prev.get("sector_key"):
                return nu, nu, nu, nu, nu
            req["choices"]["sector"] = sector
            req["choices"].pop("business_risk", None)
        if btn == "micro":
            req["choices"]["micro"] = {i["key"]: v for v, i in zip(micro_vals, micro_ids) if v not in (None, "")}
        if btn == "case":
            req["choices"]["analyst_case"] = {i["key"]: v for v, i in zip(case_vals, case_ids) if v not in (None, "")}
            if not req["choices"]["analyst_case"]:
                return nu, nu, html.Div("Enter at least one adjustment first.", className="alert err"), nu, nu
        if btn == "case-clear":
            req["choices"].pop("analyst_case", None)
        if btn == "agency":
            entries = {i["key"]: (v or "").strip() for v, i in zip(agency_vals, agency_ids) if (v or "").strip()}
            bad = bad_agency_entries(entries)
            if bad:
                return nu, nu, html.Div("Not a valid rating: " + ", ".join(bad) + ". Use the agency's scale (e.g. BBB-, Baa3).",
                                        className="alert err"), nu, nu
            req["choices"]["agency_ratings"] = entries
        return _carry(_run(req, ai_on, False), prev), req, None, nu, nu
    except (EdgarError, Rejected) as e:
        return nu, nu, html.Div(str(e), className="alert err"), nu, nu
    except Exception as e:  # never show a stack trace (could leak paths)
        return nu, nu, html.Div(f"Something went wrong: {type(e).__name__}. Try again.", className="alert err"), nu, nu


@app.callback(Output("rerun-wrap", "style"), Output("rerun-text", "children"), Output("rerun", "children"),
              Input("report", "data"))
def rerun_visible(r):
    if r and r["ai"].get("cache_only_missing"):
        return {"display": "block"}, ("Figures, ratings and checks are complete. The AI analyst team hasn't written this "
                                      "company's analysis yet (comparisons skip it to save tokens)."), "Run AI analyst team"
    show = r and r["ai"].get("analysts_skipped") and (r.get("team") or {}).get("outputs", {}).get("writer")
    return ({"display": "block"} if show else {"display": "none"}), (
        "Figures or assumptions changed: ratings and tables are updated (code, no tokens). The analysts' text reflects the "
        "earlier version."), "Re-run analysts"


@app.callback(Output("review", "children"), Input("mapping", "data"))
def show_review(m):
    return review_view(m, [{"label": f, "value": f} for f in FIELD_NAMES]) if m else None


@app.callback(Output("results", "children"), Input("report", "data"), Input("view", "value"), Input("cmp-pick", "value"),
              Input("mode", "value"), Input("pub-mode", "value"), Input("compare", "data"))
def render(r, view, pick, mode, pub, cmp):
    if mode == "public" and pub == "compare":
        if not cmp:
            return html.Div(note_compare(), className="card")
        if pick == "CMP":
            return comparison_view(cmp)
    if not r:
        return landing()
    if not r.get("primary"):
        return html.Div("No period could be rated from this data.", className="alert err")
    return report_view(r, view)


def _subject(r, c, pick, mode, pub):
    """What is on screen: the comparison, or one company's report."""
    if mode == "public" and pub == "compare" and c and pick == "CMP":
        return "cmp", c
    return ("rep", r) if r and r.get("primary") else (None, None)


@app.callback(Output("actions", "style"), Output("chat-wrap", "style"),
              Input("report", "data"), Input("compare", "data"), Input("cmp-pick", "value"), Input("mode", "value"),
              Input("pub-mode", "value"))
def actions_visible(r, c, pick, mode, pub):
    kind, _ = _subject(r, c, pick, mode, pub)
    return ({"display": "flex"} if kind else {"display": "none"}), ({"display": "block"} if kind else {"display": "none"})


@app.callback(Output("dl", "data"), Output("status", "children", allow_duplicate=True),
              Input("exp-xlsx", "n_clicks"), Input("exp-docx", "n_clicks"), Input("exp-pdf", "n_clicks"),
              State("report", "data"), State("compare", "data"), State("cmp-pick", "value"), State("mode", "value"),
              State("pub-mode", "value"), prevent_initial_call=True)
def download(_x, _d, _p, r, c, pick, mode, pub):
    kind, obj = _subject(r, c, pick, mode, pub)
    if not kind or not ctx.triggered_id:
        return no_update, no_update
    try:
        from flask import request as http
        rate_limit(http.remote_addr or "local", "export")
        name = ("comparison_" + "_".join(c["tickers"])) if kind == "cmp" else \
            "".join(ch for ch in (obj.get("ticker") or obj["company"]) if ch.isalnum() or ch in "-_")[:40]
        if ctx.triggered_id == "exp-xlsx":
            data = export.comparison_xlsx(obj) if kind == "cmp" else export.report_xlsx(obj)
            return dcc.send_bytes(data, f"{name}_credit_analysis.xlsx"), None
        blocks = export.comparison_blocks(obj) if kind == "cmp" else export.memo_blocks(obj, swot_items(obj))
        if ctx.triggered_id == "exp-docx":
            return dcc.send_bytes(export.to_docx(blocks), f"{name}_credit_memo.docx"), None
        return dcc.send_bytes(export.to_pdf(blocks), f"{name}_credit_memo.pdf"), None
    except Rejected as e:
        return no_update, html.Div(str(e), className="alert err")
    except Exception as e:  # never show a stack trace
        return no_update, html.Div(f"Export failed: {type(e).__name__}.", className="alert err")


@app.callback(Output("watch", "data"), Output("watch-msg", "children"),
              Input("watch-add", "n_clicks"), Input("watch-check", "n_clicks"), Input({"type": "wrm", "t": ALL}, "n_clicks"),
              State("watch", "data"), State("report", "data"), prevent_initial_call=True)
def watchlist(_a, _c, _rm, items, r):
    trig = ctx.triggered_id
    items = [i for i in (items or []) if isinstance(i, dict) and isinstance(i.get("ticker"), str)][:watch.MAX_WATCH]
    try:
        if isinstance(trig, dict):
            if not any(_rm or []):
                return no_update, no_update
            return [i for i in items if i["ticker"] != trig["t"]], None
        from flask import request as http
        if trig == "watch-add":
            if not r or not r.get("ticker"):
                return no_update, html.Div("Analyze a public company first (watchlists track SEC filings).", className="alert err")
            if any(i["ticker"] == r["ticker"] for i in items):
                return no_update, html.Div(f"{r['ticker']} is already on the watchlist.", className="alert info")
            if len(items) >= watch.MAX_WATCH:
                raise Rejected(f"The watchlist holds up to {watch.MAX_WATCH} companies.")
            return items + [watch.entry(r)], html.Div(f"Added {r['ticker']} to the watchlist.", className="alert info")
        if not items:
            return no_update, html.Div("The watchlist is empty.", className="alert info")
        rate_limit(http.remote_addr or "local")
        for i in items:
            normalize_ticker(i["ticker"])  # values from browser storage can be forged
        new = watch.check(items)
        n = sum(1 for i in new if i.get("status", "").startswith("New"))
        return new, html.Div(f"Checked {len(new)} companies: {n} with a new filing.", className="alert info")
    except (EdgarError, Rejected) as e:
        return no_update, html.Div(str(e), className="alert err")
    except Exception as e:
        return no_update, html.Div(f"Watchlist check failed: {type(e).__name__}.", className="alert err")


@app.callback(Output("watch-table", "children"), Output("watch-title", "children"), Input("watch", "data"))
def show_watch(items):
    return watch_table(items or []), f"WATCHLIST ({len(items or [])})"


@app.callback(Output("chat-q", "value", allow_duplicate=True), Input({"type": "chip", "i": ALL}, "n_clicks"),
              prevent_initial_call=True)
def chip(_n):
    if not any(_n or []) or not isinstance(ctx.triggered_id, dict):
        return no_update
    return CHIPS[ctx.triggered_id["i"]] if 0 <= ctx.triggered_id["i"] < len(CHIPS) else no_update


@app.callback(Output("chat-hist", "data"), Output("chat-q", "value"), Output("chat-msg", "children"),
              Input("chat-go", "n_clicks"), State("chat-q", "value"), State("chat-hist", "data"), State("report", "data"),
              State("compare", "data"), State("cmp-pick", "value"), State("mode", "value"), State("pub-mode", "value"),
              prevent_initial_call=True)
def ask(_n, q, hist, r, c, pick, mode, pub):
    nu = no_update
    q = " ".join((q or "").split())[:600]
    if not q:
        return nu, nu, html.Div("Type a question first.", className="alert err")
    kind, obj = _subject(r, c, pick, mode, pub)
    if not kind:
        return nu, nu, html.Div("Run an analysis first.", className="alert err")
    subject = _subject_key(kind, obj)
    turns = (hist or {}).get("turns", []) if (hist or {}).get("subject") == subject else []
    inst = chatmod.instant_answer(obj, q) if kind == "rep" else None
    if inst:  # starter questions: answered by code from the computed data, no AI call
        turns = (turns + [{"q": q, "a": inst["answer"], "where": inst["where_to_look"],
                           "meta": "Answered by code from the computed data (0 tokens)."}])[-8:]
        return {"subject": subject, "turns": turns}, "", None
    try:
        from flask import request as http
        if not ai_allowed_today():
            raise Rejected("Today's AI token ceiling for this app has been reached.")
        rate_limit(http.remote_addr or "local", "chat")
        context = chatmod.comparison_context(obj) if kind == "cmp" else chatmod.report_context(obj)
        ai = {"usage": [], "tasks": []}
        out, esc = chatmod.ask(get_model(), ai, context, turns, q)
        if out is None:
            return nu, nu, html.Div("The analyst couldn't answer from this data after 3 attempts"
                                    + (f": {esc[0]['issue'][:160]}" if esc else "") + ". Try rephrasing.", className="alert err")
        u = ai["usage"][-1] if ai["usage"] else {}
        meta = "Cached answer (0 tokens)." if u.get("cached") else f"{u.get('input_tokens', 0) + u.get('output_tokens', 0):,} tokens."
        turns = (turns + [{"q": q, "a": out.answer, "where": out.where_to_look, "meta": meta}])[-8:]
        return {"subject": subject, "turns": turns}, "", None
    except (Rejected, EdgarError) as e:
        return nu, nu, html.Div(str(e), className="alert err")
    except Exception as e:
        return nu, nu, html.Div(f"Chat failed: {type(e).__name__}. Is an AI key configured?", className="alert err")


def _subject_key(kind, obj):
    if kind == "cmp":
        return "CMP:" + ",".join(obj["tickers"])
    return f"{obj.get('ticker') or obj['company']}|{(obj.get('primary') or {}).get('label')}" if kind else None


@app.callback(Output("chat-log", "children"), Input("chat-hist", "data"), Input("report", "data"), Input("compare", "data"),
              Input("cmp-pick", "value"), Input("mode", "value"), Input("pub-mode", "value"))
def show_chat(hist, r, c, pick, mode, pub):
    same = (hist or {}).get("subject") == _subject_key(*_subject(r, c, pick, mode, pub))
    return chat_log(hist if same else None)  # a new company or comparison starts a fresh conversation


def note_compare():
    return html.P(["Enter two or more tickers (e.g. ", html.Code("LUV"), " and ", html.Code("ULCC"),
                   ") and press COMPARE. Use + Add company for more."], className="muted")


if __name__ == "__main__":
    # debug off / no reloader: one process, no orphan servers (workspace rule)
    app.run(host="127.0.0.1", port=8050, debug=False)

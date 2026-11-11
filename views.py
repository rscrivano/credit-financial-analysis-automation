"""Dash view builders (no callbacks). One function per section of the report."""
from __future__ import annotations

import plotly.graph_objects as go
from dash import dash_table, dcc, html
from dash.dash_table.Format import Format, Scheme

from credit_engine.pipeline import QUESTIONS
from credit_engine.sector import LABELS as SECTOR_LABELS
from credit_engine.sector import fmt as sfmt

PINK, PURPLE, MUTED, GRID = "#ffa028", "#4fc3f7", "#8a8a8a", "#222222"  # amber, cyan (terminal palette)
TIER = {"Strong": "good", "Normal": "info", "Struggling": "bad", "Unusual": "review", "Data is Missing": "missing"}
DARK = {"backgroundColor": "#0a0a0a", "color": "#e8e8e8", "border": "1px solid #222", "fontSize": 13,
        "fontFamily": "Consolas, 'IBM Plex Mono', 'Courier New', monospace", "padding": "4px 8px"}
HEAD = {**DARK, "color": "#ffa028", "fontWeight": 700, "textTransform": "uppercase", "fontSize": 12}


def notch(n):
    return html.Span(n or "–", className="notch")


def money(v):
    return "–" if v is None else f"{v:,.0f}"


def note(text):
    return html.P(text, className="muted small")


def table(head, rows, num_cols=()):
    return html.Div(html.Table([
        html.Thead(html.Tr([html.Th(h, className="num" if i in num_cols else None) for i, h in enumerate(head)])),
        html.Tbody([html.Tr([html.Td(c, className="num" if i in num_cols else None) for i, c in enumerate(r)]) for r in rows])]),
        className="tbl")


def card(title, *children, cls=""):
    return html.Div([html.H3(title) if title else None, *children], className=f"card {cls}")


def bullets(items, empty="None noted."):
    return html.Ul([html.Li(x) for x in items]) if items else note(empty)


def fmt_ratio(r):
    if r["value"] is None:
        return html.Span(r["message"] or "n/a", className=f"pill {r['status']}")
    return f"{r['value']:.1%}" if "(%)" in r["name"] else f"{r['value']:.2f}x"


def _out(r, k):
    return ((r.get("team") or {}).get("outputs") or {}).get(k)


def _stale(r):
    return html.Div("Assumptions or figures changed since the analysts wrote this. Use 'Re-run analysts' above to "
                    "refresh their text (ratings and tables are already up to date).", className="alert info small") \
        if r["ai"].get("analysts_skipped") and _out(r, "writer") else None


# ---------- header ----------

def kpis(r):
    p = r["primary"]
    cs = r.get("credit_score") or {}
    out0 = [html.Div([html.Div("Credit score", className="label"),
                      html.Div([f"{cs['score']}", html.Span("/100", className="s")] if cs.get("score") is not None else "n/a", className="v"),
                      html.Div(f"{cs.get('rating') or 'n/a'} · {cs.get('coverage', 0):.0%} of scorecard", className="s"),
                      html.Div(cs.get("coverage_label", ""), className="s " + ("good-t" if cs.get("coverage", 0) >= 0.9 else "warn-t"))],
                     className="kpi")]
    cards = [("Reported rating", p["reported"]), ("Lease-adjusted", p["lease_adjusted"])]
    if r.get("obs_adjusted"):
        cards.append(("+ Off-balance-sheet", r["obs_adjusted"]))
    out = [html.Div([html.Div(lbl, className="label"), html.Div(b["rating"] or "n/a", className="v"),
                     html.Div(f"Score {b['score']:.2f}" if b.get("score") is not None else (b.get("message") or ""), className="s")],
                    className="kpi") for lbl, b in cards]
    out = out0 + out
    spv = r.get("sp_anchor") or {}
    if spv.get("anchor"):
        out.append(html.Div([html.Div("S&P-style (indicative)", className="label"), html.Div(spv.get("final") or spv["anchor"], className="v"),
                             html.Div(f"{spv['business_risk']} × {spv['financial_risk']['category']}"
                                      + (f" · liquidity cap {spv['cap']}" if spv.get("cap") else ""), className="s")], className="kpi"))
    ag = r.get("agency_ratings") or {}
    out.append(html.Div([html.Div("Agency ratings", className="label")] +
                        [html.Div([html.Span(a, className="ag"), html.Span((ag[a]["rating"] if a in ag else "n.d."),
                                                                           className="agv" if a in ag else "muted")])
                         for a in ("S&P", "Moody's", "Fitch")] +
                        [html.Div("as disclosed in filings" if any(v["source"] != "Entered by user" for v in ag.values())
                                  else ("entered by you" if ag else "not disclosed; enter in Credit tab"), className="s")],
                        className="kpi"))
    sec, meta = r.get("sector") or {}, r.get("meta") or {}
    out.append(html.Div([html.Div("Period · sector", className="label"), html.Div(p["label"], style={"fontWeight": 700}),
                         html.Div((sec.get("sector") or "Sector not set") + (f" · {sec['overall']}" if sec.get("overall") else ""), className="s"),
                         html.Div(("Private · " + (meta.get("quality") or "statements")) if meta.get("mode") == "private"
                                  else f"Public · SEC {r['data_source']}", className="s")], className="kpi"))
    red = [f for f in r.get("integrity", []) if f["severity"] == "red"]
    n_dec = sum(u["severity"] == "decision" for u in r["uncertainties"])
    banners = []
    if red:
        banners.append(html.Div([html.B(f"{len(red)} data red flag(s): "), "; ".join(f["title"] for f in red),
                                 ". The numbers were not changed; see Accounting & GAAP."], className="alert err"))
    if n_dec:
        banners.append(html.Div([f"{n_dec} decision(s) waiting in ", html.B("Assumptions"), "."], className="alert info"))
    return html.Div([html.H2(r["company"], style={"margin": "18px 0 0"}), html.Div(out, className="kpis", style={"marginTop": "10px"}),
                     *banners])


# ---------- sections ----------

def summary_view(r):
    w, credit = _out(r, "writer"), _out(r, "credit")
    if w:
        s = w["swot"]
        head = [html.H3(w["headline"]), html.P(w["executive_summary"])]
        swot = {"Strengths": s["strengths"], "Weaknesses": s["weaknesses"], "Opportunities": s["opportunities"], "Threats": s["threats"]}
        concerns = w.get("key_concerns", [])
        src = "Written by the Report Writer from the analysts' work; every number checked against the computed data."
    else:  # AI off or unavailable: computed SWOT from the data alone
        sec = r.get("sector") or {}
        strong = [f"{x['name']}: {sfmt(x['value'], x['unit'])} (sector median {sfmt(x['p50'], x['unit'])})"
                  for x in sec.get("rows", []) if x["tier"] == "Strong"]
        weak = [f"{x['name']}: {sfmt(x['value'], x['unit'])} (sector median {sfmt(x['p50'], x['unit'])})"
                for x in sec.get("rows", []) if x["tier"] == "Struggling"]
        st = r.get("stress") or {}
        threats = [f["title"] for f in r.get("integrity", []) if f["severity"] == "red"] + \
                  [f"{s['name']}: Reported {s['reported']}" for s in st.get("scenarios", [])
                   if s.get("reported") and s["reported"] != (st.get("base") or {}).get("reported")][:3]
        head = [html.H3(f"{r['company']}: Reported {r['primary']['reported']['rating']}, "
                        f"S&P-style {(r.get('sp_anchor') or {}).get('anchor') or 'n/a'}")]
        swot = {"Strengths": strong, "Weaknesses": weak, "Opportunities": [], "Threats": threats}
        concerns = [u["title"] for u in r["uncertainties"] if u["severity"] in ("decision", "review")][:4]
        src = "Computed from the data (AI analysts off). Turn on AI for a written summary."
    grid = html.Div([html.Div([html.H4(k), bullets(v)], className=f"swot swot-{k.lower()}") for k, v in swot.items()],
                    className="swot-grid")
    outlook = html.P([html.B("Outlook: "), f"{credit['outlook'].title()}. {credit.get('outlook_reason', '')}"]) if credit else None
    return html.Div([_stale(r), card(None, *head, outlook), grid, card("Key points of concern", bullets(concerns)), note(src)])


def ratio_table(p):
    rows = [[a["name"], fmt_ratio(a), notch(a["notch"]), fmt_ratio(b) if b else "–", notch(b["notch"]) if b else "–", f"{a['weight']:.0%}"]
            for a, b in zip(p["reported"]["ratios"], p["lease_adjusted"]["ratios"] or [None] * 9)]
    return table(["Ratio (credit scorecard)", "Reported", "Notch", "Lease-adj.", "Notch", "Weight"], rows, (1, 3, 5))


def credit_view(r, view):
    c, p, a, st = _out(r, "credit"), r["primary"], r.get("sp_anchor") or {}, r.get("stress") or {}
    analyst = card("Financial / Credit Analyst",
                   html.P(c["rating_rationale"]),
                   html.Div([html.Div([html.H4("Strengths"), bullets(c["strengths"])]),
                             html.Div([html.H4("Weaknesses"), bullets(c["weaknesses"])])], className="grid2"),
                   html.P(c.get("liquidity_and_leverage", "")),
                   html.P([html.B("Outlook: "), c["outlook"].title(), ". ", c.get("outlook_reason", "")])) \
        if c else note("Credit Analyst not run (AI off, or not yet run for this company).")
    fin = a.get("financial_risk") or {}
    sp = sp_card(r)
    rev = st.get("reverse") or {}
    rev_txt = rev.get("note") or "; ".join(f"EBITDA can fall {v:.0%} before the Reported rating reaches {k}" if v
                                         else (f"Already at or below {k}" if v == 0 else f"{k}: not reached") for k, v in rev.items())
    stress = card("Stress tests", table(["Scenario", "Reported", "Lease-adj."],
                                        [[s["name"], notch(s["reported"]), notch(s["lease_adjusted"])] for s in st.get("scenarios", [])]),
                  html.P(rev_txt, className="small"))
    return html.Div([_stale(r), agency_card(r), analyst, card("Scorecard", ratio_table(p)), case_card(r), sp, stress,
                     card("Ratings by period", periods_chart(r, view))])


def agency_card(r):
    ag, p, a = r.get("agency_ratings") or {}, r["primary"], r.get("sp_anchor") or {}
    rows = [[n, html.B(ag[n]["rating"]) if n in ag else html.Span("Not disclosed", className="muted"),
             (ag[n].get("outlook") or "–") if n in ag else "–", ag[n]["source"] if n in ag else "–"] for n in ("S&P", "Moody's", "Fitch")]
    quotes = [html.Div([html.Span(n, className="pill info"), " ", html.Q(v["quote"])], className="passage small")
              for n, v in ag.items() if v.get("quote")]
    entry = html.Div(className="agency-entry", children=[
        html.Div([html.Label(n, className="small"), dcc.Input(id={"type": "agency", "key": n}, type="text", maxLength=6,
                                                             placeholder="e.g. BBB-" if n != "Moody's" else "e.g. Baa3",
                                                             value=(ag[n]["rating"] if n in ag and ag[n]["source"] == "Entered by user" else None),
                                                             className="num-in")]) for n in ("S&P", "Moody's", "Fitch")] +
        [html.Button("Apply", id={"type": "btn", "name": "agency"}, className="btn ghost", n_clicks=0)])
    return card("Agency ratings vs. implied",
                table(["Agency", "Rating", "Outlook", "Source"], rows),
                html.P(["Implied: Reported ", notch(p["reported"]["rating"]), "  Lease-adjusted ", notch(p["lease_adjusted"]["rating"]),
                        "  S&P-style anchor ", notch(a.get("anchor"))], className="small"),
                *quotes,
                note("Agency ratings are licensed data, so they are taken only from what the company states in its own "
                     "10-K/10-Q (exact sentence shown). Statements can be dated; enter current ratings below if you have them."),
                entry)


def periods_chart(r, view):
    ps = [x for x in r["periods"] if view == "all" or x["kind"] in (view, "LTM")]
    fig = go.Figure()
    for basis, color in (("reported", PINK), ("lease_adjusted", PURPLE)):
        pts = [(x["label"], x[basis]["score"]) for x in reversed(ps) if x[basis].get("score") is not None]
        if pts:
            fig.add_trace(go.Scatter(x=[a for a, _ in pts], y=[b for _, b in pts], mode="lines+markers",
                                     name="Reported" if basis == "reported" else "Lease-adjusted", line={"color": color, "width": 3}))
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=280,
                      margin={"l": 40, "r": 10, "t": 10, "b": 40}, font={"color": MUTED},
                      yaxis={"title": "Score (lower = stronger)", "autorange": "reversed", "gridcolor": GRID},
                      legend={"orientation": "h", "y": 1.12})
    rows = [[x["label"], x["kind"], money(x["ebitda"]["ebitda"]), notch(x["reported"]["rating"]), notch(x["lease_adjusted"]["rating"])]
            for x in ps]
    return html.Div([dcc.Graph(figure=fig, config={"displayModeBar": False}),
                     table(["Period", "Type", "EBITDA", "Reported", "Lease-adj."], rows, (2,))])


# ---------- 3 FINANCIALS: summary + detailed P&L / Balance Sheet / Cash Flows ----------

def _vals(r):
    st = r["statements"]
    v = {row["field"]: {p: row.get(p) for p in st["periods"]} for row in st["rows"]}

    def g(f, p, zero=False):
        x = v.get(f, {}).get(p)
        return 0.0 if (x is None and zero) else x
    return st["periods"], g


def _calc(fn, periods):
    out = {}
    for p in periods:
        try:
            x = fn(p)
            out[p] = None if x is None else round(x, 1)
        except (TypeError, ZeroDivisionError):
            out[p] = None
    return out


def _statement_specs(g):
    """(kind, label, field-or-formula). kind: hdr, line (reported, editable), total (reported subtotal, editable),
    calc (derived by code), pct (derived %), memo."""
    da = lambda p: g("depreciation", p)  # noqa: E731
    ebitda = lambda p: g("operating_income", p) + da(p)  # noqa: E731
    pl = [("hdr", "Income statement", None),
          ("line", "Revenue", "revenue"), ("line", "Cost of goods sold", "cogs"),
          ("calc", "Gross profit", lambda p: g("revenue", p) - g("cogs", p)),
          ("pct", "Gross margin (%)", lambda p: (g("revenue", p) - g("cogs", p)) / g("revenue", p) * 100),
          ("line", "SG&A", "sga"), ("line", "Depreciation & amortization", "depreciation"),
          ("calc", "Total operating expenses (revenue − EBIT)", lambda p: g("revenue", p) - g("operating_income", p)),
          ("calc", "Other operating expense (net)", lambda p: g("revenue", p) - g("cogs", p) - g("sga", p) - da(p) - g("operating_income", p)),
          ("total", "Operating income (EBIT)", "operating_income"),
          ("calc", "EBITDA", ebitda), ("pct", "EBITDA margin (%)", lambda p: ebitda(p) / g("revenue", p) * 100),
          ("line", "Interest expense, net", "interest_expense"),
          ("calc", "Pre-tax income (EBIT − interest)", lambda p: g("operating_income", p) - g("interest_expense", p)),
          ("line", "Income tax", "tax_expense"),
          ("calc", "Other non-operating items", lambda p: g("net_income", p) - (g("operating_income", p) - g("interest_expense", p) - g("tax_expense", p, True))),
          ("total", "Net income", "net_income"), ("pct", "Net margin (%)", lambda p: g("net_income", p) / g("revenue", p) * 100),
          ("hdr", "Memo", None), ("line", "Operating lease cost", "operating_lease_cost"),
          ("calc", "EBITDAR (EBITDA + lease cost)", lambda p: ebitda(p) + g("operating_lease_cost", p))]
    bs = [("hdr", "Assets", None),
          ("line", "Cash & equivalents", "cash"), ("line", "Accounts receivable", "receivables"), ("line", "Inventory", "inventory"),
          ("calc", "Other current assets", lambda p: g("total_current_assets", p) - g("cash", p) - g("receivables", p, True) - g("inventory", p, True)),
          ("total", "Total current assets", "total_current_assets"),
          ("line", "PP&E, net", "fixed_assets"), ("line", "Goodwill", "goodwill"), ("line", "Other intangibles", "other_intangibles"),
          ("calc", "Other long-term assets", lambda p: g("total_assets", p) - g("total_current_assets", p) - g("fixed_assets", p, True)
           - g("goodwill", p, True) - g("other_intangibles", p, True)),
          ("total", "Total assets", "total_assets"),
          ("hdr", "Liabilities", None),
          ("line", "Accounts payable", "accounts_payable"), ("line", "Short-term debt & current maturities", "st_debt"),
          ("calc", "Other current liabilities", lambda p: g("total_current_liabilities", p) - g("accounts_payable", p, True) - g("st_debt", p, True)),
          ("total", "Total current liabilities", "total_current_liabilities"),
          ("line", "Long-term debt", "lt_debt"), ("line", "Operating lease liabilities", "operating_lease_liabilities"),
          ("line", "Deferred tax liability", "deferred_tax_liability"),
          ("calc", "Other long-term liabilities", lambda p: g("total_liabilities", p) - g("total_current_liabilities", p) - g("lt_debt", p, True)
           - g("operating_lease_liabilities", p, True) - g("deferred_tax_liability", p, True)),
          ("total", "Total liabilities", "total_liabilities"),
          ("hdr", "Equity", None), ("total", "Shareholders' equity", "total_equity"),
          ("calc", "Total liabilities & equity", lambda p: g("total_liabilities", p) + g("total_equity", p)),
          ("check", "Balance check (assets − liabilities − equity)", lambda p: g("total_assets", p) - g("total_liabilities", p) - g("total_equity", p)),
          ("hdr", "Memo", None),
          ("calc", "Total debt", lambda p: g("lt_debt", p) + g("st_debt", p, True)),
          ("calc", "Net debt (debt − cash)", lambda p: g("lt_debt", p) + g("st_debt", p, True) - g("cash", p)),
          ("calc", "Lease-adjusted debt", lambda p: g("lt_debt", p) + g("st_debt", p, True) + g("operating_lease_liabilities", p, True))]
    cf = [("hdr", "Operating activities", None),
          ("calc", "Net income (from P&L)", lambda p: g("net_income", p)),
          ("calc", "Depreciation & amortization (from P&L)", lambda p: da(p)),
          ("line", "Deferred taxes", "deferred_taxes"),
          ("calc", "Working capital & other items", lambda p: g("cfo", p) - g("net_income", p) - da(p) - g("deferred_taxes", p, True)),
          ("total", "Cash flow from operations", "cfo"),
          ("hdr", "Investing activities", None),
          ("line", "Purchases of PP&E (gross capex)", "capex_gross"), ("line", "Proceeds from asset sales", "asset_sales"),
          ("line", "Capital expenditures, net", "capex"),
          ("line", "Acquisitions (net of cash acquired)", "acquisitions"), ("line", "Divestitures", "divestitures"),
          ("line", "Purchases of investments", "inv_purchases"), ("line", "Sales / maturities of investments", "inv_sales"),
          ("calc", "Net investment activity (sales − purchases)", lambda p: g("inv_sales", p, True) + g("inv_purchases", p, True)
           if g("inv_sales", p) is not None or g("inv_purchases", p) is not None else None),
          ("calc", "Other investing", lambda p: g("cfi", p) - g("capex", p, True) - g("acquisitions", p, True) - g("divestitures", p, True)
           - g("inv_purchases", p, True) - g("inv_sales", p, True)),
          ("total", "Net cash from investing", "cfi"),
          ("hdr", "Financing activities", None),
          ("line", "Debt issued", "debt_issued"), ("line", "Debt repaid (incl. finance-lease principal)", "debt_repaid"),
          ("calc", "Net borrowing (repayment)", lambda p: g("debt_issued", p, True) + g("debt_repaid", p, True)
           if g("debt_issued", p) is not None or g("debt_repaid", p) is not None else None),
          ("line", "Share buybacks", "buybacks"), ("line", "Dividends / distributions", "dividends"),
          ("calc", "Other financing (incl. company-specific items)", lambda p: g("cff", p) - g("debt_issued", p, True) - g("debt_repaid", p, True)
           - g("buybacks", p, True) - g("dividends", p, True)),
          ("total", "Net cash from financing", "cff"),
          ("hdr", "Summary", None),
          ("calc", "Net change in cash (CFO + investing + financing)", lambda p: g("cfo", p) + g("cfi", p) + g("cff", p)),
          ("calc", "Free cash flow (CFO + capex)", lambda p: g("cfo", p) + g("capex", p, True)),
          ("calc", "Discretionary cash flow (FCF − dividends)", lambda p: g("cfo", p) + g("capex", p, True) + g("dividends", p, True))]
    return {"pl": pl, "bs": bs, "cf": cf}


def _statement_table(name, spec, periods, g, r):
    rows = []
    for i, (kind, label, src) in enumerate(spec):
        if kind == "hdr":
            rows.append({"field": f"_hdr{i}", "kind": kind, "line": label.upper(), **{p: None for p in periods}})
        elif isinstance(src, str):
            rows.append({"field": src, "kind": kind, "line": label, **{p: g(src, p) for p in periods}})
        else:
            rows.append({"field": f"_calc{i}", "kind": kind, "line": label, **_calc(src, periods)})
    st = r["statements"]
    num = Format(precision=1, scheme=Scheme.fixed).group(True)
    cols = [{"name": ["", "US$ millions"], "id": "line", "editable": False}] + \
           [{"name": [st["kinds"].get(p, "").split(" · ")[0], p], "id": p, "type": "numeric", "format": num, "editable": True}
            for p in periods]
    edited = {(e["period"], e["field"]) for e in r.get("edits", [])}
    cond = [{"if": {"filter_query": '{kind} = "hdr"'}, "color": "#ffa028", "fontWeight": 700, "backgroundColor": "#000",
             "borderTop": "1px solid #ffa028"},
            {"if": {"filter_query": '{kind} = "total"'}, "fontWeight": 700, "borderTop": "1px solid #555"},
            {"if": {"filter_query": '{kind} = "calc" || {kind} = "pct"'}, "color": "#9a9a9a", "fontStyle": "italic"},
            {"if": {"filter_query": '{kind} = "check"'}, "fontWeight": 700, "color": "#2fd26a"}]
    cond += [{"if": {"filter_query": f'{{kind}} = "check" && ({{{p}}} > 0.5 || {{{p}}} < -0.5)', "column_id": p},
              "color": "#ff4d4d", "backgroundColor": "rgba(255,77,77,.12)"} for p in periods]
    cond += [{"if": {"filter_query": f'{{field}} = "{f}"', "column_id": p}, "backgroundColor": "rgba(255,160,40,.25)"}
             for p, f in edited]
    return dash_table.DataTable(id={"type": "stmt", "name": name}, data=rows, columns=cols, merge_duplicate_headers=True,
                                style_cell=DARK, style_header=HEAD, style_table={"overflowX": "auto"},
                                style_cell_conditional=[{"if": {"column_id": "line"}, "textAlign": "left", "minWidth": "260px"}],
                                style_data_conditional=cond)


def financials_summary(r):
    periods, g = _vals(r)
    st = r["statements"]
    kinds = {p: st["kinds"].get(p, "") for p in periods}
    ebitda = lambda p: g("operating_income", p) + g("depreciation", p)  # noqa: E731
    debt = lambda p: g("lt_debt", p) + g("st_debt", p, True)  # noqa: E731
    lines = [("Revenue", lambda p: g("revenue", p), "m"), ("EBITDA", ebitda, "m"),
             ("EBITDA margin", lambda p: ebitda(p) / g("revenue", p), "%"), ("Net income", lambda p: g("net_income", p), "m"),
             ("Cash flow from operations", lambda p: g("cfo", p), "m"),
             ("Free cash flow", lambda p: g("cfo", p) + g("capex", p, True), "m"),
             ("Cash & equivalents", lambda p: g("cash", p), "m"), ("Total debt", debt, "m"),
             ("Net debt", lambda p: debt(p) - g("cash", p), "m"), ("Shareholders' equity", lambda p: g("total_equity", p), "m"),
             ("Debt / EBITDA (12-month periods)", lambda p: debt(p) / ebitda(p) if kinds[p].startswith("Annual") and ebitda(p) > 0 else None, "x"),
             ("Current ratio", lambda p: g("total_current_assets", p) / g("total_current_liabilities", p), "x")]

    def fmtv(x, u):
        if x is None:
            return "–"
        return f"{x:.1%}" if u == "%" else f"{x:.2f}x" if u == "x" else f"{x:,.0f}"
    rows = []
    for label, fn, u in lines:
        vals = {}
        for p in periods:
            try:
                vals[p] = fn(p)
            except (TypeError, ZeroDivisionError):
                vals[p] = None
        rows.append([label, *[fmtv(vals[p], u) for p in periods]])
    annual = [p for p in periods if kinds[p].startswith("Annual")][::-1]
    fig = go.Figure()
    for name, fn, color in (("Revenue", lambda p: g("revenue", p), PINK), ("EBITDA", ebitda, PURPLE)):
        ys = []
        for p in annual:
            try:
                ys.append(fn(p))
            except TypeError:
                ys.append(None)
        fig.add_trace(go.Bar(x=annual, y=ys, name=name, marker_color=color))
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=240, barmode="group",
                      margin={"l": 50, "r": 10, "t": 10, "b": 30}, font={"color": MUTED, "family": "Consolas, monospace"},
                      yaxis={"gridcolor": GRID, "title": "US$ m"}, legend={"orientation": "h", "y": 1.15})
    red = [f for f in r.get("integrity", []) if f["severity"] == "red"]
    return html.Div([
        html.Div([html.B(f"{len(red)} red flag(s): "), "; ".join(f["title"] for f in red)], className="alert err") if red else None,
        card("Key financials (US$ millions)", table(["", *[f"{p}" for p in periods]], rows, tuple(range(1, len(periods) + 1))),
             note("Columns: " + " · ".join(f"{p} = {kinds[p]}" for p in periods))),
        card("Revenue and EBITDA by fiscal year", dcc.Graph(figure=fig, config={"displayModeBar": False})) if annual else None])


def financials_detailed(r):
    periods, g = _vals(r)
    specs = _statement_specs(g)
    red = [f for f in r.get("integrity", []) if f["severity"] == "red"]
    return html.Div([
        html.Div([html.B(f"{len(red)} red flag(s): "), "; ".join(f["title"] for f in red)], className="alert err") if red else None,
        note("White lines are reported figures: click to correct, then Recalculate (code only, no AI). Grey italic lines are "
             "calculated from them. Edited cells are highlighted and listed under Assumptions."),
        card("P&L", _statement_table("pl", specs["pl"], periods, g, r),
             note("Gross profit appears when the company reports cost of goods sold; airlines and many service businesses "
                  "report total operating expenses instead (shown above), so it is left blank rather than estimated.")),
        card("Balance Sheet", _statement_table("bs", specs["bs"], periods, g, r),
             note("'Other' lines are the difference between a reported subtotal and the lines broken out above it. The "
                  "balance check turns red when total assets ≠ total liabilities + equity.")),
        card("Cash Flows", _statement_table("cf", specs["cf"], periods, g, r),
             note("'Other' lines reconcile the detail to the reported investing and financing totals. Some companies "
                  "report items such as debt repayments under their own XBRL tags, which SEC's standardized data doesn't "
                  "break out; those land in 'Other financing' (e.g., Southwest's 2025 repayments).")),
        html.Div(style={"display": "flex", "gap": "10px", "marginTop": "12px"}, children=[
            html.Button("Recalculate with my edits", id={"type": "btn", "name": "recalc"}, className="btn", n_clicks=0),
            html.Button("Undo all edits", id={"type": "btn", "name": "undo"}, className="btn ghost", n_clicks=0)
            if r.get("edits") else None])])


def statements_view(r):
    return dcc.Tabs([dcc.Tab(financials_summary(r), label="SUMMARY", value="fsum", className="tab subtab",
                             selected_className="tab--selected"),
                     dcc.Tab(financials_detailed(r), label="DETAILED: P&L · BALANCE SHEET · CASH FLOWS", value="fdet",
                             className="tab subtab", selected_className="tab--selected")],
                    id="fin-tabs", value="fsum", persistence=True, persistence_type="session", mobile_breakpoint=0,
                    parent_className="tab-parent")


def economic_view(r):
    m = _out(r, "macro")
    macro_rows = [[x["label"], "–" if x.get("value") is None else f"{x['value']:.2f}",
                   "–" if x.get("year_ago") is None else f"{x['year_ago']:.2f}", "–" if x.get("change") is None else f"{x['change']:+.2f}",
                   x.get("as_of", "")] for x in r.get("macro") or [] if x.get("available")]
    ind_rows = [[x["key"], "–" if x.get("value") is None else f"{x['value']:,.2f}",
                 "–" if x.get("pct_change") is None else f"{x['pct_change']:+.1f}%", x.get("as_of", "")]
                for x in r.get("industry") or [] if x.get("available")]
    rec = (r.get("sector") or {}).get("recession_2020") or {}
    analyst = card("Macro Economic Analyst", html.P(m["summary"]),
                   html.Div([html.Div([html.H4("Opportunities"), bullets(m["opportunities"])]),
                             html.Div([html.H4("Threats"), bullets(m["threats"])])], className="grid2")) if m else \
        note("Macro Analyst not run (AI off, or not yet run for this company).")
    return html.Div([_stale(r), analyst,
                     card("Macro indicators (FRED)", table(["Indicator", "Latest", "Year ago", "Change", "As of"], macro_rows, (1, 2, 3))),
                     card("Industry indicators (FRED)", table(["Indicator", "Latest", "1-yr change", "As of"], ind_rows, (1, 2))
                          if ind_rows else note("Pick a sector.")),
                     card("Sector recession history",
                          html.P(f"In 2020 the sector's median company saw revenue change {rec['revenue_change_p50']:+.0%} and operating margin "
                                 f"{rec['op_margin_change_p50'] * 100:+.1f} points (n={rec['n']}). This scenario is applied in the stress test.")
                          if rec.get("revenue_change_p50") is not None else note("Not available for this sector."))])


def sector_view(r):
    mi, sec = _out(r, "micro"), r.get("sector") or {}
    if not sec.get("available"):
        return note((sec.get("reason") or "No sector") + " Choose one in the sector dropdown above.")
    analyst = card("Micro Economic (Sector) Analyst", html.P(mi["positioning"]),
                   html.H4("Versus competitors") if mi["peer_comparison"] else None,
                   html.Ul([html.Li([html.B(x["peer"] + ": "), x["point"]]) for x in mi["peer_comparison"]]),
                   html.H4("Performance drivers"), bullets(mi["drivers"]),
                   html.Div([html.Div([html.H4("Opportunities"), bullets(mi["opportunities"])]),
                             html.Div([html.H4("Threats"), bullets(mi["threats"])])], className="grid2")) if mi else \
        note("Micro Analyst not run (AI off, or not yet run for this company).")
    keys = r.get("peer_keys") or []
    peer_rows = [[html.B(x["name"]) if "(this company)" in x["name"] else x["name"], money(x["revenue"]),
                  *[x.get(k) or "–" for k in keys]] for x in r.get("peers", [])]
    comp = card("Named competitors (SEC filings, fiscal 2025)",
                table(["Company", "Revenue $m", *[SECTOR_LABELS[k][0] for k in keys]], peer_rows, tuple(range(1, len(keys) + 2))),
                note("The sector's three largest companies plus the five closest in size. Ratios use the same definitions for "
                     "every company."))
    rows = [[x["name"], sfmt(x["value"], x["unit"]) if x["value"] is not None else "–",
             html.Span(x["tier"], className=f"pill {TIER.get(x['tier'], 'info')}"), sfmt(x["p25"], x["unit"]), sfmt(x["p50"], x["unit"]),
             sfmt(x["p75"], x["unit"])] for x in sec["rows"]]
    tiers = card(f"{sec['sector']}: position against {sec['companies']} public filers (overall: {sec.get('overall') or 'n/a'})",
                 table(["Ratio", "Company", "Tier", "25th", "Median", "75th"], rows, (1, 3, 4, 5)),
                 note("Strong = better than 75% of the sector; Struggling = worse than 75%. Sector norms differ widely (e.g., "
                      "inventory turnover), so the comparison is always within the company's own sector."))
    return html.Div([_stale(r), peer_vs_card(r), analyst, comp, tiers, micro_form(r)])


def peer_vs_card(r):
    """This company against the median of its named public competitors (works for private companies too)."""
    agg = r.get("peer_aggregate") or {}
    if not agg.get("names"):
        return None
    good = {True: html.Span("better", className="pill good"), False: html.Span("weaker", className="pill bad"),
            None: html.Span("–", className="muted")}
    rows = []
    for m in agg["metrics"]:
        u = m["unit"]
        f = money if u == "m" else (lambda v, u=u: sfmt(v, u))
        diff = None if m["company"] is None or m["peer_median"] is None else m["company"] - m["peer_median"]
        d = "–" if diff is None else (f"{diff:+,.0f}" if u == "m" else f"{diff:+.1%}" if u == "pct" else
                                      f"{diff:+.0f} days" if u == "days" else f"{diff:+.2f}x")
        rows.append([m["name"], f(m["company"]), f(m["peer_median"]), d, good[m["better"]], str(m["n"])])
    better = sum(1 for m in agg["metrics"] if m["better"])
    scored = sum(1 for m in agg["metrics"] if m["better"] is not None)
    return card(f"{r['company']} vs publicly traded competitors",
                html.P(["Compared with the median of: ", html.B(", ".join(agg["names"])), "."]),
                table(["Metric", r["company"][:28], "Peer median", "Difference", "", "Peers with data"], rows, (1, 2, 3, 5)),
                note(f"Better than the peer median on {better} of {scored} comparable metrics. Peer figures come from the "
                     "competitors' SEC filings (fiscal 2025) and use the same ratio definitions as this company."))


# ---------- multi-company comparison ----------

def comparison_view(c):
    from credit_engine.compare import show
    ms, best = c["metrics"], c.get("best") or {}
    errs = [html.Div(f"{t}: {e}", className="alert err") for t, e in (c.get("errors") or {}).items()]
    if len(ms) < 2:
        return html.Div(errs + [html.Div("At least two companies are needed for a comparison.", className="alert err")])
    head = ["Metric", *[f"{m['ticker']} · {m['company'][:22]}" for m in ms]]
    rows = []
    for key, label, unit in c["rows"]:
        cells = []
        for m in ms:
            v = show(m.get(key), unit)
            cells.append(html.B(v, className="good-t") if best.get(key) == m["company"] else v)
        rows.append([label, *cells])
    agency = ["Agency ratings (disclosed)", *[", ".join(f"{a} {v}" for a, v in m["agency"].items()) or "none disclosed" for m in ms]]
    rows.insert(4, agency)
    fig = go.Figure(go.Bar(x=[m["ticker"] for m in ms], y=[m["credit_score"] or 0 for m in ms], marker_color=PINK,
                           text=[f"{m['credit_score']} · {m['reported_rating'] or '–'}" for m in ms], textposition="outside"))
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=260,
                      margin={"l": 40, "r": 10, "t": 20, "b": 30}, font={"color": MUTED},
                      yaxis={"title": "Credit score (higher = stronger)", "range": [0, 105], "gridcolor": GRID})
    w = c.get("writeup") or {}
    src = "AI comparison writer (numbers checked against the data)" if w.get("source") == "ai" else \
        "Written by code from the computed figures (AI off or unavailable)"
    rank = [[str(x["rank"]), x["company"], x["rationale"]] for x in w.get("ranking", [])]
    colors = {"Strengths": "good", "Weaknesses": "bad", "Opportunities": "info", "Threats": "review"}
    swot_cols = []
    for m in ms:
        S = swot_items(c["reports"][m["ticker"]])
        swot_cols.append(html.Div([html.H4(m["ticker"])] + [
            html.Div([html.Span(q, className=f"pill {colors[q]}"),
                      html.Ul([html.Li(x["text"]) for x in items[:3]]) if items else note("None identified.")])
            for q, items in S.items()], className="card"))
    eco = []
    for m in ms:
        r = c["reports"][m["ticker"]]
        sec, st = r.get("sector") or {}, r.get("stress") or {}
        rec = sec.get("recession_2020") or {}
        scen = [f"{s['name']}: {s['reported'] or '–'}" for s in (st.get("scenarios") or [])][:3]
        eco.append([m["ticker"], sec.get("sector") or "–", sec.get("overall") or "–",
                    "–" if rec.get("revenue_change_p50") is None else f"{rec['revenue_change_p50']:.0%}",
                    "; ".join(scen) or "–"])
    used = sum(u.get("input_tokens", 0) + u.get("output_tokens", 0) for u in (c.get("ai") or {}).get("usage", []))
    missing = [m["ticker"] for m in ms if c["reports"][m["ticker"]]["ai"].get("cache_only_missing")]
    return html.Div(errs + [
        card(w.get("headline") or "Comparison", html.P(w.get("overall", "")), note(f"{src}. Tokens for this comparison: {used:,}.")),
        card("Side by side (best in each row highlighted)", table(head, rows, tuple(range(1, len(ms) + 1))),
             note("Each company's latest period with complete data (LTM where available). Ratings use the same scorecard and "
                  "S&P-style method for every company.")),
        card("Credit score", dcc.Graph(figure=fig, config={"displayModeBar": False})),
        card("Ranking: strongest to weakest credit", table(["#", "Company", "Why"], rank)),
        card("Financial comparison", html.P(w.get("financial", ""))),
        card("SWOT comparison", html.P(w.get("swot", "")), html.Div(swot_cols, className="cmp-grid")),
        card("Economic comparison", html.P(w.get("economic", "")),
             table(["Ticker", "Sector", "Position vs sector", "Sector revenue, 2020 recession", "Stress tests (reported rating)"], eco)),
        note("Pick a company in the toggle above to review it in depth across every tab. "
             + (f"The AI analyst team hasn't run yet for {', '.join(missing)}; open the company and click 'Run AI analyst team' "
                "for its written analysis (figures and ratings are already complete)." if missing else "")),
    ])


def micro_form(r):
    ans = (r.get("choices") or {}).get("micro", {})
    fields = []
    for k, q in QUESTIONS.items():
        if k in ("pricing_power", "sponsor_owned"):
            ctl = dcc.Dropdown(id={"type": "micro", "key": k}, options=["yes", "partly", "no"] if k == "pricing_power" else ["yes", "no"],
                               value=ans.get(k), clearable=True, className="dd")
        else:
            ctl = dcc.Input(id={"type": "micro", "key": k}, type="number", min=0, max=100, value=ans.get(k), className="num-in")
        fields.append(html.Div([html.Label(q, className="small"), ctl], style={"marginBottom": "10px"}))
    flags = [html.Div([html.H4([html.Span(f["severity"], className=f"pill {f['severity']}"), " ", f["title"]]),
                       html.Div(f["detail"], className="small")], className="unc review") for f in r.get("micro") or []]
    return card("Company factors (optional)", note("What the financials don't show. Answers become flags and inform the Micro "
                                                    "Analyst; they don't change the ratios."),
                html.Div(fields, className="grid2"),
                html.Button("Apply answers", id={"type": "btn", "name": "micro"}, className="btn ghost", n_clicks=0), *flags)


def accounting_view(r):
    acc = _out(r, "accounting")
    sev = {"red": "bad", "review": "review", "info": "info"}
    gaap = [html.Div([html.H4([html.Span(g["severity"], className=f"pill {sev[g['severity']]}"), " ", g["topic"]]),
                      html.Div(g["finding"], className="small"), html.Div(html.Q(g["quote"]), className="small muted")],
                     className=f"unc {sev[g['severity']]}") for g in (acc or {}).get("gaap_findings", [])]
    integ = [html.Div([html.H4([html.Span("RED" if f["severity"] == "red" else "review",
                                          className="pill bad" if f["severity"] == "red" else "pill review"), " ", f["title"]]),
                       html.Div(f["detail"], className="small"),
                       html.Div("Periods: " + ", ".join(f.get("periods") or [f.get("period", "")]), className="small muted")],
                      className="unc " + ("bad" if f["severity"] == "red" else "review")) for f in r.get("integrity", [])]
    o = r["off_balance_sheet"]
    obs_rows = [[i["category"].replace("_", " "), i["description"], money(i["amount_musd"]), i["confidence"]] for i in o["items"]]
    return html.Div([
        card("Accounting Analyst", html.P((acc or {}).get("data_quality_note") or "Not run (AI off or no source text)."),
             html.H4("GAAP / reporting observations") if gaap else None, *gaap),
        card("Data integrity checks (code)", *(integ or [note("No issues: subtotals tie, signs are as expected and the balance "
                                                              "sheet balances where equity was provided.")])),
        card("Off-balance-sheet and debt-like items",
             table(["Category", "Item", "US$m", "Confidence"], obs_rows, (2,)) if obs_rows else note("None found."),
             note("Quotes verified against the source. Nothing is added to debt unless you choose it under Assumptions.")),
        card("Accounting flags (code)", bullets([f"{f['title']}: {f['detail']}" for f in r.get("flags", [])]))])


def detailed_view(r):
    w = _out(r, "writer")
    sections = [card(t, html.P(w[k])) for t, k in (("Credit", "credit_section"), ("Economic", "economic_section"),
                                                   ("Sector", "sector_section"), ("Accounting", "accounting_section")) if w and w.get(k)]
    passages = []
    for line in (r.get("source_excerpt") or "").splitlines():
        if line.startswith("[") and "] " in line:
            tag, text = line[1:].split("] ", 1)
            passages.append(html.Div([html.Span(tag.split("#")[0].replace("_", " "), className="pill info"), " ", text],
                                     className="passage small"))
    f = r.get("filing")
    src = card(f"Source passages: {r.get('source_label') or 'none'}",
               html.P(["Full filing: ", html.A(f"{f['form']} filed {f['filed']}", href=f["url"], target="_blank")], className="small") if f else None,
               *(passages or [note("No source text (public: filing unavailable; private: no notes found in the upload).")]),
               note("These short excerpts are all the AI read; the full document is never sent."))
    sources = card("Where every number came from", html.Div([html.Details([html.Summary(label), table(["Field", "Source"], [
        [k, html.Span("; ".join(v) if isinstance(v, list) else str(v), className="small muted")]
        for k, v in fields.items() if not k.startswith("_")])]) for label, fields in r["sources"].items()]))
    return html.Div([_stale(r), *sections, src, sources])


def uncertainty_view(r):
    order = {"decision": 0, "review": 1, "info": 2}
    out = []
    for u in sorted(r["uncertainties"], key=lambda u: order[u["severity"]]):
        ctl = None
        if u["options"] and u["choice_key"] and u["choice_key"] != "sector":
            ctl = dcc.RadioItems(id={"type": "choice", "key": u["choice_key"]},
                                 options=[{"label": o["label"], "value": o["value"]} for o in u["options"]],
                                 value=u["chosen"] if u["chosen"] is not None else u["options"][0]["value"],
                                 labelStyle={"display": "block", "margin": "4px 0"}, inputStyle={"accentColor": PINK})
        out.append(html.Div([html.H4([html.Span(u["severity"], className=f"pill {u['severity']}"), " ", u["title"]]),
                             html.Div(u["detail"], className="small"), html.Div(u["impact"], className="impact") if u["impact"] else None, ctl],
                            className=f"unc {u['severity']}"))
    return html.Div([note("Every judgment call. Changing an option re-scores with code (no AI tokens).")] + out)


def agents_view(r):
    ai, tm = r["ai"], r.get("team") or {}
    if not ai.get("enabled"):
        return note(ai.get("reason") or "AI was off: 0 tokens.")
    flow = html.Div(className="flow", children=[
        html.Div("Accounting Analyst", className="node"), html.Div("→", className="arrow"),
        html.Div([html.Div("Credit Analyst", className="node"), html.Div("Macro Analyst", className="node"),
                  html.Div("Micro (Sector) Analyst", className="node")], className="stack"),
        html.Div("→", className="arrow"), html.Div("Manager (one review)", className="node mgr"), html.Div("→", className="arrow"),
        html.Div("Report Writer", className="node")])
    usage = {u["agent"]: u for u in ai["usage"]}
    rows = [[t["agent"], t["status"], str(t["attempts"]) if t["attempts"] else "–",
             f"{usage.get(t['agent'], {}).get('input_tokens', 0):,}", f"{usage.get(t['agent'], {}).get('output_tokens', 0):,}",
             f"{usage.get(t['agent'], {}).get('saved_tokens', 0):,}" if usage.get(t["agent"], {}).get("saved_tokens") else ""]
            for t in ai.get("tasks", [])]
    t = ai["totals"]
    rows.append([html.B("This run"), "", "", f"{t['input_tokens']:,}", f"{t['output_tokens']:,}",
                 f"{sum(u.get('saved_tokens', 0) for u in ai['usage']):,}"])
    mgr = (tm.get("outputs") or {}).get("manager")
    esc = [html.Li([html.B(e["analyst"]), f": {e['issue']} → Manager: {e['manager_decision']}",
                    f" ({e['manager_note']})" if e["manager_note"] else ""]) for e in tm.get("escalations", [])]
    return html.Div([
        card("How the team works", flow,
             note("Code does all the math. Each analyst gets a short brief for its area only. Each task gets at most 3 attempts "
                  "(a failed check sends feedback and retries); after that it escalates to the Manager, who decides once. A "
                  "per-run token budget stops further calls, and results are cached so repeats cost 0.")),
        card("Tasks this run", table(["Agent", "Status", "Attempts", "Input", "Output", "Saved by cache"], rows, (2, 3, 4, 5)),
             note(f"Model: {ai.get('model')}. Budget: {tm.get('budget', 0):,} tokens per run.")),
        card("Manager review", html.P(mgr["guidance_for_writer"]) if mgr else note("Manager not run."),
             bullets(mgr.get("conflicts", []), "No conflicts between analysts.") if mgr else None,
             html.H4("Escalations") if esc else None, html.Ul(esc) if esc else note("No escalations.")),
        card("Checks", bullets(ai.get("problems", []), "All AI outputs passed their checks."))])


# ---------- SWOT (assembled from work already done and checked: no extra AI calls) ----------

IG_MOODYS = {"Aaa", "Aa1", "Aa2", "Aa3", "A1", "A2", "A3", "Baa1", "Baa2", "Baa3"}


def _notch_no(rating):
    from credit_engine.scorecard import Scorecard
    return Scorecard.load().notch_scale.get((rating or "").split(" / ")[0].upper()) if rating else None


def swot_items(r) -> dict:
    S = {"Strengths": [], "Weaknesses": [], "Opportunities": [], "Threats": []}

    def add(q, text, source):
        if text and not any(text.strip().lower() == x["text"].strip().lower() for x in S[q]):
            S[q].append({"text": text, "source": source})
    p, sec, st = r["primary"], r.get("sector") or {}, r.get("stress") or {}
    # Ratings
    rep = p["reported"]["rating"]
    n = _notch_no(rep)
    if n is not None:
        if n <= 11:
            add("Strengths", f"Implied investment-grade profile: Reported {rep}, Lease-adjusted {p['lease_adjusted']['rating'] or 'n/a'}, "
                             f"S&P-style anchor {(r.get('sp_anchor') or {}).get('anchor') or 'n/a'}.", "Ratings")
        elif n >= 15:
            add("Weaknesses", f"Speculative-grade implied profile: Reported {rep}, S&P-style anchor "
                              f"{(r.get('sp_anchor') or {}).get('anchor') or 'n/a'}.", "Ratings")
    for a, v in (r.get("agency_ratings") or {}).items():
        rt = v["rating"]
        ig = rt == "Investment grade" or rt in IG_MOODYS or (_notch_no(rt) or 99) <= 11
        add("Strengths" if ig else "Weaknesses", f"{a}: {rt}" + (f", {v['outlook']} outlook" if v.get("outlook") else "")
            + f" ({v['source']}).", "Agency rating")
    # Sector position (numbers from SEC peers)
    for x in sec.get("rows", []):
        if x["value"] is None or x["tier"] not in ("Strong", "Struggling"):
            continue
        txt = (f"{x['name']} {sfmt(x['value'], x['unit'])} vs. sector median {sfmt(x['p50'], x['unit'])} "
               f"({'top' if x['tier'] == 'Strong' else 'bottom'} quartile of {sec.get('companies')} {sec.get('sector')} filers).")
        add("Strengths" if x["tier"] == "Strong" else "Weaknesses", txt, "Sector data")
    # Scorecard notches at the extremes
    for x in p["reported"]["ratios"]:
        nn = _notch_no(x["notch"])
        if x["value"] is not None and nn is not None and nn >= 19:
            add("Weaknesses", f"{x['name']} {fmt_ratio(x)} scores {x['notch']} on the credit scorecard.", "Scorecard")
        elif x["value"] is not None and nn is not None and nn <= 4:
            add("Strengths", f"{x['name']} {fmt_ratio(x)} scores {x['notch']} on the credit scorecard.", "Scorecard")
    # Stress tests
    rev = st.get("reverse") or {}
    if rev.get("B-") is not None and rev["B-"] > 0:
        add("Strengths" if rev["B-"] >= 0.4 else "Weaknesses",
            f"EBITDA could fall {rev['B-']:.0%} before the Reported rating reaches B-.", "Stress test")
    base_n = _notch_no((st.get("base") or {}).get("reported"))
    for s in st.get("scenarios", []):
        sn = _notch_no(s.get("reported"))
        if base_n is not None and sn is not None and sn - base_n >= 2:
            add("Threats", f"{s['name']}: Reported rating falls from {st['base']['reported']} to {s['reported']}.", "Stress test")
    # Data quality and accounting
    for f in r.get("integrity", []):
        if f["severity"] == "red":
            add("Weaknesses", f"{f['title']} ({', '.join(f.get('periods') or [])}): {f['detail']}", "Data checks")
    acc = _out(r, "accounting") or {}
    for gf in acc.get("gaap_findings", []):
        if gf["severity"] in ("red", "review"):
            add("Weaknesses" if gf["severity"] == "red" else "Threats", f"{gf['topic']}: {gf['finding']}", "Accounting Analyst")
    for i in (r.get("off_balance_sheet") or {}).get("items", []):
        amt = f" (${i['amount_musd']:,.0f}m)" if i.get("amount_musd") else ""
        add("Threats", f"Off-balance-sheet: {i['description']}{amt}.", "10-K / notes")
    for m in r.get("micro") or []:
        add("Threats" if m["severity"] == "review" else "Weaknesses", f"{m['title']}: {m['detail']}", "Questionnaire")
    # Macro data
    for m in r.get("macro") or []:
        if m.get("key") == "UST10" and (m.get("change") or 0) >= 0.25:
            add("Threats", f"10-year Treasury yield up {m['change']:.2f} pts in a year to {m['value']:.2f}% (refinancing cost).", "Macro data")
        if m.get("key") == "HY_OAS" and (m.get("change") or 0) >= 0.25:
            add("Threats", f"High-yield spreads wider by {m['change']:.2f} pts in a year to {m['value']:.2f}%.", "Macro data")
    # Analysts (already number-checked)
    for k, src in (("credit", "Credit Analyst"),):
        c = _out(r, k)
        if c:
            for x in c.get("strengths", []):
                add("Strengths", x, src)
            for x in c.get("weaknesses", []):
                add("Weaknesses", x, src)
    for k, src in (("macro", "Macro Analyst"), ("micro", "Micro Analyst")):
        o = _out(r, k)
        if o:
            for x in o.get("opportunities", []):
                add("Opportunities", x, src)
            for x in o.get("threats", []):
                add("Threats", x, src)
    w = _out(r, "writer")
    if w:
        for q, key in (("Strengths", "strengths"), ("Weaknesses", "weaknesses"), ("Opportunities", "opportunities"), ("Threats", "threats")):
            for x in w["swot"].get(key, []):
                add(q, x, "Report Writer")
    return S


def swot_view(r):
    S = swot_items(r)
    colors = {"Strengths": "good", "Weaknesses": "bad", "Opportunities": "info", "Threats": "review"}
    quads = [html.Div([html.H4(f"{q} ({len(items)})"),
                       html.Ul([html.Li([html.Span(x["source"], className=f"pill {colors[q]}"), " ", x["text"]]) for x in items])
                       if items else note("None identified.")], className=f"swot swot-{q.lower()}") for q, items in S.items()]
    w = _out(r, "writer")
    concerns = (w or {}).get("key_concerns") or [u["title"] for u in r["uncertainties"] if u["severity"] == "decision"][:4]
    return html.Div([
        card("SWOT analysis", note("Every item is tagged with its source. Computed items (ratings, sector data, scorecard, "
                                   "stress tests, data checks, macro data) come straight from code; analyst items passed the "
                                   "number and quote checks. Building this view uses no additional AI tokens.")),
        html.Div(quads, className="swot-grid"),
        card("Key points of concern", bullets(concerns))])


SECTIONS = [("summary", "1 SUMMARY"), ("swot", "2 SWOT"), ("credit", "3 CREDIT"), ("debt", "4 DEBT STRUCTURE"),
            ("statements", "5 FINANCIALS"), ("economic", "6 MACRO"), ("sector", "7 SECTOR/COMPS"), ("accounting", "8 ACCOUNTING/GAAP"),
            ("detail", "9 DETAIL"), ("unc", "10 ASSUMPTIONS"), ("agents", "11 AGENTS")]


def report_view(r, view):
    n_dec = sum(u["severity"] != "info" for u in r["uncertainties"])
    builders = {"summary": lambda: summary_view(r), "swot": lambda: swot_view(r), "credit": lambda: credit_view(r, view),
                "debt": lambda: debt_view(r),
                "statements": lambda: statements_view(r),
                "economic": lambda: economic_view(r), "sector": lambda: sector_view(r), "accounting": lambda: accounting_view(r),
                "detail": lambda: detailed_view(r), "unc": lambda: uncertainty_view(r), "agents": lambda: agents_view(r)}
    tabs = [dcc.Tab(html.Div([tab_help(v), builders[v]()]), label=(f"{l} ({n_dec})" if v == "unc" and n_dec else l), value=v,
                    className="tab", selected_className="tab--selected") for v, l in SECTIONS]
    return html.Div([kpis(r), dcc.Tabs(tabs, id="tabs", value="summary", persistence=True, persistence_type="session",
                                       mobile_breakpoint=0, parent_className="tab-parent")])


# ---------- mapping review (private upload) ----------

def review_view(m, field_options):
    per_rows = [{"key": p["key"], "header": p["header"], "end": str(p["end"]), "months": p["months"], "note": p.get("note", "")}
                for p in m["periods"]]
    rows = [{"i": i, "label": r["label"], "field": r["field"] or "", "method": r["method"],
             **{p["header"]: r["values"].get(p["key"]) for p in m["periods"]}} for i, r in enumerate(m["rows"])]
    n_un = sum(1 for r in m["rows"] if not r["field"])
    return card("Confirm what the app read",
                note(f"From {m.get('source_file', 'your file')}: {len(m['rows'])} lines, {len(m['periods'])} periods. "
                     f"{m.get('unit_note', '')} Statement type detected: {m.get('quality', 'Management')}. Change a line's "
                     "field, leave it blank to ignore it, or fix period dates. Nothing is scored until you confirm."),
                html.Div(className="grid2", children=[
                    html.Div([html.Label("Company name", className="small"),
                              dcc.Input(id={"type": "mapv", "name": "company"}, type="text", value=m.get("company") or "Private company",
                                        style={"textTransform": "none"})]),
                    html.Div([html.Label("Statement type", className="small"),
                              dcc.Dropdown(id={"type": "mapv", "name": "quality"}, value=m.get("quality", "Management"), clearable=False,
                                           className="dd", options=["Audited", "Reviewed", "Compiled", "Management"])])]),
                html.H4("Periods"),
                dash_table.DataTable(id={"type": "mapt", "name": "periods"}, data=per_rows, editable=True,
                                     columns=[{"name": "Header", "id": "header", "editable": False}, {"name": "Period end (YYYY-MM-DD)", "id": "end"},
                                              {"name": "Months", "id": "months", "type": "numeric"},
                                              {"name": "How it was read", "id": "note", "editable": False}],
                                     style_cell=DARK, style_header=HEAD, style_table={"overflowX": "auto"}),
                html.H4(f"Lines ({n_un} not matched)" if n_un else "Lines (all matched)"),
                dash_table.DataTable(id={"type": "mapt", "name": "rows"}, data=rows, editable=True, page_size=80,
                                     columns=[{"name": "Label in file", "id": "label", "editable": False},
                                              {"name": "Template field", "id": "field", "presentation": "dropdown"},
                                              {"name": "Matched by", "id": "method", "editable": False}]
                                     + [{"name": p["header"], "id": p["header"], "editable": False, "type": "numeric"} for p in m["periods"]],
                                     dropdown={"field": {"options": [{"label": "(ignore)", "value": ""}] + field_options}},
                                     style_cell=DARK, style_header=HEAD, style_table={"overflowX": "auto"},
                                     style_data_conditional=[{"if": {"filter_query": '{field} = ""'}, "color": "#ffc857"}]),
                dcc.Checklist(id={"type": "mapv", "name": "flip"}, value=["flip"], className="opts",
                              options=[{"label": "Apply the sign convention (expenses positive, capex negative); changes are listed after analysis",
                                        "value": "flip"}]),
                html.Div(style={"display": "flex", "gap": "10px", "marginTop": "12px", "flexWrap": "wrap"}, children=[
                    html.Button(f"Ask the Accounting Analyst to map {n_un} line(s) (~300 tokens)", id={"type": "btn", "name": "map-ai"},
                                className="btn ghost", n_clicks=0) if n_un else None,
                    html.Button("Confirm & analyze", id={"type": "btn", "name": "map-confirm"}, className="btn", n_clicks=0)]))



# ---------- S&P-style rating detail ----------

def sp_card(r):
    a = r.get("sp_anchor") or {}
    if not a:
        return note("Not available.")
    fin, adj, liq = a.get("financial_risk") or {}, a.get("adjusted") or {}, a.get("liquidity") or {}
    build = [["Debt (" + (a.get("basis") or "") + " basis)", money(adj.get("reported_basis_debt"))],
             ["+ Pension deficit, after tax", money(adj.get("pension_after_tax")) if adj.get("pension_after_tax") else "–"],
             ["− Surplus cash netted", money(adj.get("surplus_cash_netted")) if adj.get("surplus_cash_netted") else "– (not netted)"],
             [html.B("= S&P-adjusted debt"), html.B(money(adj.get("adjusted_debt")))],
             ["EBITDA, 12 months (lease-adjusted)", money(adj.get("ebitda_12m"))], ["FFO, 12 months", money(adj.get("ffo_12m"))]]
    core = [["FFO / debt", "–" if a.get("ffo_to_debt") is None else f"{a['ffo_to_debt']:.1%}", fin.get("ffo_cat") or "–"],
            ["Debt / EBITDA", "n.m. (EBITDA ≤ 0)" if a.get("ebitda_negative") else ("–" if a.get("debt_to_ebitda") is None else f"{a['debt_to_ebitda']:.2f}x"),
             fin.get("lev_cat") or "–"]]
    supp = [[x["name"], "–" if x["value"] is None else (f"{x['value']:.1%}" if "(%)" in x["name"] else f"{x['value']:.2f}x"), x["category"]]
            for x in a.get("supplementary", [])]
    steps = [["Business risk profile", a.get("business_risk") or "n/a",
              "chosen by you" if a.get("business_overridden") else (a.get("business_suggestion") or {}).get("rule", "")],
             ["Financial risk profile", fin.get("category") or "n/a",
              f"{a.get('table', 'standard')} volatility table; " + ("FFO/debt primary" if a.get("fin_rule") == "ffo" else f"{a.get('fin_rule')} of the two core ratios")
              + ("; financial-sponsor owned → highly leveraged" if fin.get("sponsor_override") else "")],
             ["Anchor", a.get("anchor") or "n/a", "business × financial risk matrix"],
             ["Liquidity modifier", liq.get("assessment") or "n/a",
              (f"sources/uses {liq['ratio']:.2f}x" if liq.get("ratio") else "") + (f" → caps rating at {a['cap']}" if a.get("cap") else "")],
             [html.B("Indicative S&P-style rating"), html.B(a.get("final") or a.get("anchor") or "n/a"), ""]]
    return card("S&P-style rating (indicative)",
                table(["Step", "Result", "Basis"], steps),
                html.Div(className="grid2", children=[
                    html.Div([html.H4("S&P-adjusted debt (US$ m)"), table(["", ""], build, (1,))]),
                    html.Div([html.H4("Core ratios (adjusted)"), table(["Ratio", "Value", "Category"], core, (1,)),
                              html.H4("Supplementary ratios"), table(["Ratio", "Value", "Category"], supp, (1,))])]),
                note("Follows the structure of S&P's corporate methodology: adjusted debt, core and supplementary ratios on the "
                     "sector's volatility table, the business × financial risk anchor, then financial-policy and liquidity "
                     "modifiers. Not modeled: comparable-ratings analysis, diversification, management/governance, group support, "
                     "S&P's normalization of one-off items, and deconsolidation of captive finance arms. Not an official S&P rating."))


# ---------- Debt structure ----------

def debt_view(r):
    ds = r.get("debt_structure") or {}
    a = r.get("sp_anchor") or {}
    p = r["primary"]
    liq = a.get("liquidity") or {}
    lad, opl, finl = ds.get("debt") or {}, ds.get("op_lease") or {}, ds.get("fin_lease") or {}
    from credit_engine.debt import BUCKETS
    total_m = sum(lad.values()) if lad else None
    fig = go.Figure()
    for name, d, color in (("Debt principal", lad, PINK), ("Finance leases", finl, "#ffd23f"), ("Operating leases", opl, PURPLE)):
        if d:
            fig.add_trace(go.Bar(x=[lbl for _, lbl in BUCKETS], y=[d.get(k) for k, _ in BUCKETS], name=name, marker_color=color))
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=280, barmode="stack",
                      margin={"l": 50, "r": 10, "t": 10, "b": 30}, font={"color": MUTED, "family": "Consolas, monospace"},
                      yaxis={"gridcolor": GRID, "title": "US$ m"}, legend={"orientation": "h", "y": 1.15})
    rows = [[lbl, money(lad.get(k)), money(finl.get(k)), money(opl.get(k)),
             "–" if not total_m or lad.get(k) is None else f"{lad[k] / total_m:.0%}"] for k, lbl in BUCKETS]
    rows.append([html.B("Total"), html.B(money(total_m)), money(sum(finl.values()) if finl else None),
                 money(sum(opl.values()) if opl else None), "100%" if total_m else "–"])
    near = (lad.get("Y1", 0) + lad.get("Y2", 0)) if lad else None
    cash = None
    for x in r["statements"]["rows"]:
        if x["field"] == "cash":
            cash = next((x.get(pp) for pp in r["statements"]["periods"] if x.get(pp) is not None), None)
    kp = [("Reported debt", money(p["reported"]["total_debt"])), ("Lease-adjusted debt", money(p["lease_adjusted"]["total_debt"])),
          ("S&P-adjusted debt", money((a.get("adjusted") or {}).get("adjusted_debt"))),
          ("Revolver available", (money(ds["revolver_available"]) + (f" of {money(ds['revolver_capacity'])}" if ds.get("revolver_capacity") else ""))
           if ds.get("revolver_available") is not None else (f"n.d. (facility {money(ds['revolver_capacity'])})" if ds.get("revolver_capacity") else "n.d.")),
          ("Wtd. avg. interest rate", f"{ds['weighted_rate']:.2%}" if ds.get("weighted_rate") else "–"),
          ("Fair value of debt", money(ds.get("fair_value")))]
    tiles = html.Div([html.Div([html.Div(k, className="label"), html.Div(v, className="v", style={"fontSize": "18px"})], className="kpi")
                      for k, v in kp], className="kpis")
    refi = []
    if lad and total_m:
        refi.append(f"{near / total_m:.0%} of scheduled principal ({money(near)}) is due within 2 years; {money(lad.get('Y1'))} within 12 months.")
        if cash is not None and lad.get("Y1"):
            cover = (cash + (ds.get("revolver_available") or 0)) / lad["Y1"]
            refi.append(f"Cash{' plus revolver availability' if ds.get('revolver_available') else ''} covers the next 12 months of "
                        f"maturities {cover:.1f}x.")
        if ds.get("fair_value") and ds.get("total_ltd"):
            refi.append(f"Debt trades at {ds['fair_value'] / ds['total_ltd']:.0%} of book value (fair value disclosure).")
        if ds.get("after5_derived"):
            refi.append("'Thereafter' is derived as total debt less years 1–5 (the filing doesn't tag it separately).")
    liq_rows = [[k, money(v)] for k, v in (liq.get("sources") or {}).items()] + \
               [[html.B("Total sources"), html.B(money(sum((liq.get("sources") or {}).values())))]] + \
               [[k, money(v)] for k, v in (liq.get("uses") or {}).items()] + \
               [[html.B("Total uses"), html.B(money(sum((liq.get("uses") or {}).values())))]]
    acc = _out(r, "accounting") or {}
    inst = [[i["name"], money(i.get("amount_musd")), i.get("rate") or "–", i.get("maturity") or "–",
             {True: "Secured", False: "Unsecured"}.get(i.get("secured"), "–")] for i in acc.get("debt_instruments", [])]
    covenants = [g for g in acc.get("gaap_findings", []) if "covenant" in (g["topic"] + g["finding"]).lower()]
    cov_pass = [ln.split("] ", 1)[1] for ln in (r.get("source_excerpt") or "").splitlines() if ln.startswith("[debt_covenants")]
    src = "; ".join(f"{k}: {v}" for k, v in (ds.get("sources") or {}).items() if k in ("debt", "op_lease", "revolver_available"))
    return html.Div([
        tiles,
        card("Maturity ladder (US$ millions)",
             dcc.Graph(figure=fig, config={"displayModeBar": False}) if (lad or opl or finl) else
             note("No maturity schedule in the filing's standard data (private companies: add the debt note's maturity table "
                  "to the upload)."),
             table(["Due", "Debt principal", "Finance leases", "Operating leases", "% of debt"], rows, (1, 2, 3, 4)) if lad or opl else None,
             note("Source: " + (src or "–"))),
        card("Refinancing risk", bullets(refi, "No maturity data.")),
        card("Liquidity: sources and uses, next 12 months (S&P-style)",
             html.P([html.B(f"{liq.get('assessment', 'n/a')}"), f" — sources / uses {liq['ratio']:.2f}x" if liq.get("ratio") else ""]),
             table(["", "US$ m"], liq_rows, (1,)) if liq else None,
             note("S&P thresholds: Exceptional ≥ 2.0x, Strong ≥ 1.5x, Adequate ≥ 1.2x, Less than adequate ≥ 1.0x, Weak < 1.0x. "
                  "Less than adequate caps the indicative rating at BB+, weak at B-. Without disclosed revolver availability the "
                  "assessment is marked Undetermined and no cap is applied.")),
        card("Debt instruments (from the 10-K / notes)",
             table(["Instrument", "Amount US$ m", "Rate", "Maturity", "Security"], inst, (1,)) if inst else
             note("Not extracted (AI off, or no instrument detail in the excerpt)."),
             note("Read by the Accounting Analyst; each line's quote was verified against the filing text.")),
        card("Covenants", *([html.Div([html.H4(c["topic"]), html.Div(c["finding"], className="small"),
                                       html.Div(html.Q(c["quote"]), className="small muted")], className="unc review") for c in covenants]
                            + [html.Div(x, className="passage small") for x in cov_pass]
                            or [note("No covenant terms found in the excerpt.")]))])


# ---------- analyst case (your own adjustments, shown beside Reported) ----------
CASE_FIELDS = [("ebitda_adj", "EBITDA adjustment, US$ m a year (+ add-back / − deduction)"),
               ("debt_adj", "Debt adjustment, US$ m (+ add / − remove)"),
               ("rev_growth", "Projected revenue growth, % (next 12 months)"),
               ("ebitda_margin", "Projected EBITDA margin, % (blank = today's margin)")]


def case_card(r):
    ac = r.get("analyst_case") or {}
    inputs = ((r.get("choices") or {}).get("analyst_case")) or {}
    form = html.Div([html.Div([html.Label(lbl, className="small"),
                               dcc.Input(id={"type": "case", "key": k}, type="number", value=inputs.get(k), className="num-in",
                                         debounce=True)], style={"marginBottom": "8px"}) for k, lbl in CASE_FIELDS], className="grid2")
    body = []
    if ac.get("error"):
        body.append(html.Div(ac["error"], className="alert err"))
    elif ac.get("case"):
        rep, cs = ac["reported"], ac["case"]
        body += [html.Div(className="kpis", style={"gridTemplateColumns": "repeat(2, 1fr)"}, children=[
                     html.Div([html.Div("Reported", className="k"), html.Div(rep["rating"] or "–", className="v"),
                               html.Div(f"Credit score {rep['credit_score']}", className="s")], className="kpi"),
                     html.Div([html.Div("Analyst case", className="k"), html.Div(cs["rating"] or "–", className="v"),
                               html.Div(f"Credit score {cs['credit_score']} · lease-adj. {cs['lease_adjusted'] or '–'}", className="s")],
                              className="kpi")]),
                 note("; ".join(ac["notes"]) + "."),
                 table(["Ratio", "Reported", "Notch", "Analyst case", "Notch"],
                       [[x["name"], x["base"], notch(x["base_notch"]), x["case"], notch(x["case_notch"])] for x in ac["ratios"]], (1, 3))]
    return card("Analyst case (your adjustments)",
                note("Your own view beside the Reported figures: add-backs, debt adjustments or a one-year projection. "
                     "Reported results never change; this case is labeled as your assumption in exports and the memo."),
                form, html.Div([html.Button("Apply analyst case", id={"type": "btn", "name": "case"}, className="btn ghost", n_clicks=0),
                                html.Button("Clear", id={"type": "btn", "name": "case-clear"}, className="btn ghost", n_clicks=0)],
                               className="opts"), *body)


def watch_table(items):
    if not items:
        return note("No companies yet. Analyze a public company, then press + WATCHLIST.")
    rows = [[html.B(i["ticker"]), i.get("company", "")[:30], f"{i.get('form') or '–'} {i.get('filed') or ''}",
             notch(i.get("rating")), notch(i.get("sp_style")), str(i.get("credit_score") if i.get("credit_score") is not None else "–"),
             html.Span(i.get("status", ""), className="warn-t" if i.get("changed") else None), i.get("checked", ""),
             html.Button("×", id={"type": "wrm", "t": i["ticker"]}, className="btn ghost tiny", n_clicks=0, title=f"Remove {i['ticker']}")]
            for i in items]
    return table(["Ticker", "Company", "Latest filing", "Reported", "S&P-style", "Score", "Status", "Checked", ""], rows)


def chat_log(hist):
    turns = (hist or {}).get("turns", [])
    if not turns:
        return note("Ask about anything on screen: why a rating came out as it did, what drives leverage, how the company "
                    "compares with peers, what the stress tests mean. Answers use only this analysis's data.")
    out = []
    for t in turns:
        out += [html.Div([html.Span("YOU ", className="prompt"), t["q"]], className="chat-q"),
                html.Div([html.Span("ANALYST ", className="label"), t["a"],
                          html.Div((f"See tab {t['where']}. " if t.get("where") else "") + t.get("meta", ""), className="muted small")],
                         className="chat-a")]
    return html.Div(out)


# ---------- first-time user: landing page, guide, tab help ----------
TAB_HELP = {
    "summary": "Headline view: credit score, ratings, key ratios and the AI-written summary. Start here.",
    "swot": "Strengths, weaknesses, opportunities and threats. Each item is tagged with where it came from.",
    "credit": "The scorecard behind the rating, the S&P-style view, stress tests, agency ratings and your own Analyst case.",
    "debt": "Debt maturities by year, leases, credit lines, liquidity sources versus uses, and debt instruments from the filing.",
    "statements": "P&L, balance sheet and cash flows. Edit any number and press Recalculate with my edits; edits are tracked and can be undone.",
    "economic": "Macro and industry indicators (FRED) and what they mean for this company.",
    "sector": "This company against its sector and named public competitors (peer median). Optional company questionnaire.",
    "accounting": "Accounting and GAAP findings with quotes from the filing, data red flags and off-balance-sheet items.",
    "detail": "Every ratio for every period, with the inputs used.",
    "unc": "Every judgment call the app made. Change an option and the ratings update instantly (no AI cost).",
    "agents": "What each AI analyst did, attempts, escalations to the Manager, and the tokens used.",
}

START = [
    ("1", "Analyze a public company", ["Keep ", html.B("Public company"), " and ", html.B("Single ticker"), ", type a ticker such as ",
                                        html.Code("LUV"), " and press ", html.B("GO"), ". About 10–30 seconds."]),
    ("2", "Compare competitors", ["Click ", html.B("Compare companies"), ", enter two tickers (", html.Code("LUV"), ", ",
                                  html.Code("ULCC"), "), use ", html.B("+ Add company"), " for more, press ", html.B("COMPARE"),
                                  ". Use the VIEW toggle to open any one company in depth."]),
    ("3", "Analyze a private company", ["Click ", html.B("Private company"), ", upload its statements (Excel or PDF with notes), "
                                        "check what the app read, pick the sector, press ", html.B("Confirm & analyze"), ". Sample: ",
                                        html.Code("data/samples/sample_private_reviewed_statements.pdf"), "."]),
    ("4", "Review, ask, export", ["Work through tabs 1–11, ", html.B("Ask the analyst"), " questions at the bottom, then ",
                                 html.B("EXPORT"), " to Excel or a Word/PDF credit memo. ", html.B("+ Watchlist"),
                                 " tracks new SEC filings."]),
]


def landing():
    steps = [html.Div([html.Div(n, className="step-n"), html.Div([html.H4(t), html.P(body, className="small")])],
                      className="step") for n, t, body in START]
    gets = [html.Li([html.B(l + ": "), TAB_HELP[k]]) for k, l in SECTIONS]
    return html.Div([
        html.H3("START HERE", className="section-h"),
        html.Div(steps, className="steps"),
        html.Div(className="grid2", children=[
            card("What you get (11 tabs)", html.Ul(gets, className="small")),
            card("Good to know", html.Ul([
                html.Li([html.B("AI analyst team"), " checkbox: on = written analysis (about 13k tokens for a company's "
                         "first run; repeats are free from the cache). Off = ratings, data and checks only, no AI cost."]),
                html.Li([html.B("Ratings: "), "Reported first, then Lease-adjusted, plus an indicative S&P-style rating. "
                         "Credit score 0–100: higher is stronger."]),
                html.Li([html.B("Red flags "), "appear when the numbers don't add up (e.g., the balance sheet doesn't balance)."]),
                html.Li([html.B("Assumptions tab "), "lists every judgment call with options; nothing is silently assumed."]),
                html.Li(["Full guide: ", html.Code("docs/user_guide.html"), " in the project folder."])], className="small"))]),
    ])


def tab_help(key):
    return html.P(TAB_HELP.get(key, ""), className="tab-help")

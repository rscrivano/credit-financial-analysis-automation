"""Downloads: Excel workbook of the analysis, and a credit memo as Word (.docx) or PDF.

Everything here is built from the finished report dict, so exports cost no AI tokens.
"""
from __future__ import annotations

import io
import zipfile
from datetime import date
from typing import Optional
from xml.sax.saxutils import escape

from .sector import fmt as sfmt

DISCLAIMER = ("Implied ratings, not official S&P ratings. Some of the weighting benchmarks in the analysis are drawn "
              "from S&P's rating methodology. Figures are calculated by code from the source data; AI-written text was "
              "checked against those figures.")


def _v(x, unit=""):
    if x is None:
        return "–"
    if isinstance(x, (int, float)):
        if unit == "pct":
            return f"{x:.1%}"
        if unit == "x":
            return f"{x:.2f}x"
        return f"{x:,.0f}" if abs(x) >= 100 else f"{x:,.2f}"
    return str(x)


def _writer(r) -> dict:
    return (((r.get("team") or {}).get("outputs") or {}).get("writer")) or {}


def _ratio(x: dict) -> str:
    if x.get("value") is None:
        return x.get("message") or "–"
    return f"{x['value']:.1%}" if "(%)" in x["name"] else f"{x['value']:.2f}x"


# ---------- shared content (memo blocks) ----------

def rating_rows(r) -> list[list[str]]:
    p, sp, cs = r.get("primary") or {}, r.get("sp_anchor") or {}, r.get("credit_score") or {}
    liq = (sp.get("liquidity") or {}).get("assessment")
    rows = [["Credit score (0–100)", f"{cs.get('score', '–')} · {cs.get('coverage_label', '')} ({(cs.get('coverage') or 0):.0%} of scorecard)"],
            ["Reported rating", (p.get("reported") or {}).get("rating") or "–"],
            ["Lease-adjusted rating", (p.get("lease_adjusted") or {}).get("rating") or "–"],
            ["S&P-style (indicative)", f"{sp.get('final') or '–'} (anchor {sp.get('anchor') or '–'}; business "
                                       f"{sp.get('business_risk') or '–'}, financial {(sp.get('financial_risk') or {}).get('category', '–') if isinstance(sp.get('financial_risk'), dict) else sp.get('financial_risk') or '–'})"],
            ["Liquidity (S&P-style)", liq or "–"],
            ["Agency ratings (disclosed)", ", ".join(f"{a} {v['rating']}" for a, v in (r.get("agency_ratings") or {}).items())
             or "None disclosed"]]
    ac = r.get("analyst_case")
    if ac and ac.get("case"):
        rows.append(["Analyst case (your adjustments)", f"{ac['case']['rating'] or '–'} · credit score {ac['case']['credit_score']}"])
    return rows


def swot_from_report(r) -> dict:
    w = _writer(r).get("swot")
    if w:
        return {"Strengths": w.get("strengths", []), "Weaknesses": w.get("weaknesses", []),
                "Opportunities": w.get("opportunities", []), "Threats": w.get("threats", [])}
    rows = (r.get("sector") or {}).get("rows", [])
    return {"Strengths": [f"{x['name']} {sfmt(x['value'], x['unit'])} vs sector median {sfmt(x['p50'], x['unit'])}"
                          for x in rows if x.get("tier") == "Strong"],
            "Weaknesses": [f"{x['name']} {sfmt(x['value'], x['unit'])} vs sector median {sfmt(x['p50'], x['unit'])}"
                           for x in rows if x.get("tier") == "Struggling"] +
                          [f["title"] for f in r.get("integrity", []) if f.get("severity") == "red"],
            "Opportunities": [], "Threats": []}


def memo_blocks(r, swot: Optional[dict] = None) -> list[tuple]:
    p, w = r.get("primary") or {}, _writer(r)
    b: list[tuple] = [("h1", f"Credit memo: {r['company']}" + (f" ({r['ticker']})" if r.get("ticker") else "")),
                      ("p", f"Prepared {date.today():%B %d, %Y} with Credit/Financial Analysis Automation. Period analyzed: "
                            f"{p.get('label', '–')}. Source: {('SEC EDGAR XBRL (' + r['data_source'] + ')') if r.get('ticker') else r.get('data_source', '')}"
                            + (f"; {r['filing']['form']} filed {r['filing']['filed']}" if r.get("filing") else "") + ". US$ millions."),
                      ("h2", "1. Ratings"), ("table", ["Measure", "Result"], rating_rows(r))]
    b += [("h2", "2. Executive summary"),
          ("p", w.get("executive_summary") or "AI analyst team not run; this memo uses the computed results only.")]
    if w.get("key_concerns"):
        b.append(("bullets", w["key_concerns"]))
    ac = r.get("analyst_case")
    if ac and ac.get("case"):
        b += [("h2", "Analyst case"), ("p", "; ".join(ac.get("notes", []))),
              ("table", ["Ratio", "Reported", "Analyst case"], [[x["name"], x["base"], x["case"]] for x in ac.get("ratios", [])])]
    b += [("h2", "3. Credit scorecard (reported basis)"),
          ("table", ["Ratio", "Value", "Notch", "Weight"],
           [[x["name"], _ratio(x), x.get("notch") or "–", f"{x['weight']:.0%}"] for x in (p.get("reported") or {}).get("ratios", [])])]
    if w.get("credit_section"):
        b.append(("p", w["credit_section"]))
    S = swot or swot_from_report(r)
    b.append(("h2", "4. SWOT"))
    for q, items in S.items():
        b += [("h3", q), ("bullets", [i["text"] if isinstance(i, dict) else i for i in items][:6] or ["None identified."])]
    ds = r.get("debt_structure") or {}
    lad = ds.get("debt") or {}
    b.append(("h2", "5. Debt structure and liquidity"))
    if lad:
        b.append(("table", ["Due", "US$ m"], [[k.replace("Y", "Year "), _v(v)] for k, v in lad.items()]))
    else:
        b.append(("p", "No maturity table found in the filings."))
    liq = (r.get("sp_anchor") or {}).get("liquidity") or {}
    if liq:
        b.append(("p", f"Liquidity assessment: {liq.get('assessment', '–')}"
                       + (f"; sources/uses {liq['ratio']:.2f}x" if isinstance(liq.get("ratio"), (int, float)) else "") + "."))
    agg = r.get("peer_aggregate") or {}
    b.append(("h2", "6. Sector and competitors"))
    if agg.get("names"):
        b += [("p", f"Compared with the median of: {', '.join(agg['names'])}."),
              ("table", ["Metric", r["company"][:30], "Peer median"],
               [[m["name"], _v(m["company"]) if m["unit"] == "m" else sfmt(m["company"], m["unit"]),
                 _v(m["peer_median"]) if m["unit"] == "m" else sfmt(m["peer_median"], m["unit"])] for m in agg["metrics"]])]
    if w.get("sector_section"):
        b.append(("p", w["sector_section"]))
    st = r.get("stress") or {}
    b.append(("h2", "7. Economic view and stress tests"))
    if w.get("economic_section"):
        b.append(("p", w["economic_section"]))
    if st.get("scenarios"):
        b.append(("table", ["Scenario", "Reported", "Lease-adjusted"],
                  [[s["name"], s.get("reported") or "–", s.get("lease_adjusted") or "–"] for s in st["scenarios"]]))
    reds = [f["title"] for f in r.get("integrity", []) if f.get("severity") == "red"]
    b += [("h2", "8. Data checks and accounting"), ("bullets", reds or ["No red flags in the data checks."])]
    if w.get("accounting_section"):
        b.append(("p", w["accounting_section"]))
    dec = [f"{u['title']}: {u['detail'][:220]}" for u in r.get("uncertainties", []) if u.get("severity") != "info"]
    b += [("h2", "9. Assumptions and open decisions"), ("bullets", dec[:10] or ["None."]), ("small", DISCLAIMER)]
    return b


def comparison_blocks(c) -> list[tuple]:
    from .compare import show
    ms, w = c["metrics"], c.get("writeup") or {}
    head = ["Metric", *[m["ticker"] for m in ms]]
    rows = [[label, *[show(m.get(k), u) for m in ms]] for k, label, u in c["rows"]]
    return [("h1", "Comparison: " + " vs ".join(m["ticker"] for m in ms)),
            ("p", f"Prepared {date.today():%B %d, %Y}. " + "; ".join(f"{m['ticker']} = {m['company']} ({m['period']})" for m in ms) + "."),
            ("h2", w.get("headline") or "Overview"), ("p", w.get("overall", "")),
            ("h2", "Side by side"), ("table", head, rows),
            ("h2", "Ranking"), ("table", ["#", "Company", "Why"], [[str(x["rank"]), x["company"], x["rationale"]] for x in w.get("ranking", [])]),
            ("h2", "Financial comparison"), ("p", w.get("financial", "")),
            ("h2", "SWOT comparison"), ("p", w.get("swot", "")),
            ("h2", "Economic comparison"), ("p", w.get("economic", "")), ("small", DISCLAIMER)]


# ---------- Word (.docx, written directly: no extra dependency) ----------

def _run(text, bold=False, size=None, color=None):
    pr = ("<w:b/>" if bold else "") + (f'<w:color w:val="{color}"/>' if color else "") + \
         (f'<w:sz w:val="{size}"/>' if size else "")
    return f'<w:r>{f"<w:rPr>{pr}</w:rPr>" if pr else ""}<w:t xml:space="preserve">{escape(str(text))}</w:t></w:r>'


def _para(text, bold=False, size=None, color=None, space_before=0, bullet=False):
    ppr = f'<w:pPr><w:spacing w:before="{space_before}" w:after="80"/>' + ('<w:ind w:left="360" w:hanging="220"/>' if bullet else "") + "</w:pPr>"
    return f"<w:p>{ppr}{_run(('• ' if bullet else '') + str(text), bold, size, color)}</w:p>"


def _table(head, rows):
    border = "".join(f'<w:{s} w:val="single" w:sz="4" w:color="999999"/>' for s in ("top", "left", "bottom", "right", "insideH", "insideV"))
    out = [f'<w:tbl><w:tblPr><w:tblW w:w="5000" w:type="pct"/><w:tblBorders>{border}</w:tblBorders></w:tblPr>']
    for i, row in enumerate([head] + rows):
        cells = "".join(f'<w:tc><w:tcPr>{"<w:shd w:val=\"clear\" w:fill=\"F2F2F2\"/>" if i == 0 else ""}</w:tcPr>'
                        f'<w:p>{_run(c, bold=i == 0, size=18)}</w:p></w:tc>' for c in row)
        out.append(f"<w:tr>{cells}</w:tr>")
    out.append("</w:tbl>" + _para(""))
    return "".join(out)


def to_docx(blocks) -> bytes:
    body = []
    for blk in blocks:
        kind = blk[0]
        if kind == "h1":
            body.append(_para(blk[1], True, 36, "C55A11"))
        elif kind == "h2":
            body.append(_para(blk[1], True, 26, "1F1F1F", space_before=200))
        elif kind == "h3":
            body.append(_para(blk[1], True, 22, "404040", space_before=80))
        elif kind == "p":
            body.append(_para(blk[1], size=21))
        elif kind == "small":
            body.append(_para(blk[1], size=16, color="666666", space_before=200))
        elif kind == "bullets":
            body += [_para(x, size=21, bullet=True) for x in blk[1]]
        elif kind == "table":
            body.append(_table(blk[1], blk[2]))
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
           + "".join(body) + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
           '<w:pgMar w:top="1080" w:right="1080" w:bottom="1080" w:left="1080" w:header="720" w:footer="720" w:gutter="0"/>'
           "</w:sectPr></w:body></w:document>")
    types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="xml" ContentType="application/xml"/>'
             '<Override PartName="/word/document.xml" '
             'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/></Relationships>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)
    return buf.getvalue()


# ---------- PDF (fpdf2) ----------
_LATIN = str.maketrans({"–": "-", "—": "-", "−": "-", "‑": "-", "×": "x", "≥": ">=", "≤": "<=", "’": "'", "‘": "'",
                        "“": '"', "”": '"', "…": "...", "•": "-", "→": "->", "·": "-"})


def _lat(s) -> str:
    return str(s).translate(_LATIN).encode("latin-1", "replace").decode("latin-1")


def to_pdf(blocks) -> bytes:
    from fpdf import FPDF
    pdf = FPDF(format="Letter")
    pdf.set_margins(16, 14, 16)
    pdf.set_auto_page_break(True, 14)
    pdf.add_page()
    for blk in blocks:
        kind = blk[0]
        if kind == "h1":
            pdf.set_font("Helvetica", "B", 16)
            pdf.set_text_color(197, 90, 17)
            pdf.multi_cell(0, 8, _lat(blk[1]), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
        elif kind in ("h2", "h3"):
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 12 if kind == "h2" else 10)
            pdf.multi_cell(0, 6, _lat(blk[1]), new_x="LMARGIN", new_y="NEXT")
        elif kind in ("p", "small"):
            pdf.set_font("Helvetica", "", 9 if kind == "p" else 7)
            pdf.multi_cell(0, 4.6 if kind == "p" else 3.6, _lat(blk[1]), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)
        elif kind == "bullets":
            pdf.set_font("Helvetica", "", 9)
            for x in blk[1]:
                pdf.multi_cell(0, 4.6, _lat("- " + str(x)), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)
        elif kind == "table":
            pdf.set_font("Helvetica", "", 7.5)
            n = len(blk[1])
            widths = (40, *([60 / max(n - 1, 1)] * (n - 1))) if n > 3 else None
            with pdf.table(col_widths=widths, line_height=4.2, first_row_as_headings=True,
                           headings_style=__import__("fpdf").FontFace(emphasis="BOLD", fill_color=(242, 242, 242))) as t:
                for row in [blk[1]] + blk[2]:
                    tr = t.row()
                    for c in row:
                        tr.cell(_lat(c))
            pdf.ln(2)
    return bytes(pdf.output())


# ---------- Excel ----------

def _sheet(wb, title, head, rows, widths=None):
    from openpyxl.styles import Font, PatternFill
    ws = wb.create_sheet(title[:31])
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F1F1F")
    for r in rows:
        ws.append(list(r))
    ws.freeze_panes = "B2"
    for i, w in enumerate(widths or [], start=1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = w
    return ws


def report_xlsx(r) -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    p = r.get("primary") or {}
    _sheet(wb, "Summary", ["Measure", "Result"],
           [["Company", r["company"]], ["Ticker", r.get("ticker") or "private"], ["Period", p.get("label")],
            ["Source", r.get("data_source")], *rating_rows(r), ["Note", DISCLAIMER]], [32, 90])
    rows = []
    for basis in ("reported", "lease_adjusted"):
        for x in (p.get(basis) or {}).get("ratios", []):
            rows.append([basis.replace("_", "-"), x["name"], x["value"], x.get("message") or "", x.get("notch"), x["weight"]])
    _sheet(wb, "Scorecard", ["Basis", "Ratio", "Value", "Status", "Notch", "Weight"], rows, [14, 40, 12, 22, 8, 8])
    stt = r.get("statements") or {}
    _sheet(wb, "Statements (US$ m)", ["Line", *stt.get("periods", [])],
           [[row["line"], *[row.get(per) for per in stt.get("periods", [])]] for row in stt.get("rows", [])], [36] + [13] * 12)
    _sheet(wb, "Periods", ["Period", "Type", "EBITDA", "Reported", "Reported score", "Lease-adjusted", "Lease-adj. score"],
           [[x["label"], x["kind"], x["ebitda"]["ebitda"], x["reported"]["rating"], x["reported"]["score"],
             x["lease_adjusted"]["rating"], x["lease_adjusted"]["score"]] for x in r.get("periods", [])], [14, 10, 12, 10, 12, 14, 14])
    agg = r.get("peer_aggregate") or {}
    if r.get("peers"):
        keys = r.get("peer_keys") or []
        _sheet(wb, "Peers", ["Company", "Revenue", *keys], [[x["name"], x.get("revenue"), *[x.get(k) for k in keys]] for x in r["peers"]],
               [40, 12] + [14] * len(keys))
    if agg.get("metrics"):
        _sheet(wb, "Vs peer median", ["Metric", "Company", "Peer median", "Better?", "Peers with data"],
               [[m["name"], m["company"], m["peer_median"], {True: "better", False: "weaker"}.get(m["better"], ""), m["n"]]
                for m in agg["metrics"]], [28, 14, 14, 10, 14])
    ds = r.get("debt_structure") or {}
    drows = [["Debt maturity", k, v] for k, v in (ds.get("debt") or {}).items()] + \
            [["Operating leases", k, v] for k, v in (ds.get("op_lease") or {}).items()] + \
            [["Finance leases", k, v] for k, v in (ds.get("fin_lease") or {}).items()] + \
            [["Other", k, ds[k]] for k in ("revolver_capacity", "revolver_available", "commercial_paper", "total_ltd", "fair_value",
                                         "weighted_rate", "pension_funded", "pension_liability") if ds.get(k) is not None]
    _sheet(wb, "Debt structure", ["Item", "Bucket", "US$ m"], drows, [18, 22, 12])
    st = r.get("stress") or {}
    _sheet(wb, "Stress", ["Scenario", "Reported", "Lease-adjusted"],
           [[s["name"], s.get("reported"), s.get("lease_adjusted")] for s in st.get("scenarios", [])], [50, 12, 14])
    _sheet(wb, "Red flags", ["Severity", "Title", "Detail"],
           [[f["severity"], f["title"], f["detail"]] for f in r.get("integrity", [])], [10, 40, 100])
    _sheet(wb, "Assumptions", ["Severity", "Area", "Title", "Detail", "Your choice"],
           [[u["severity"], u["area"], u["title"], u["detail"], u.get("chosen")] for u in r.get("uncertainties", [])], [10, 14, 40, 100, 14])
    ac = r.get("analyst_case")
    if ac and ac.get("ratios"):
        _sheet(wb, "Analyst case", ["Ratio", "Reported", "Analyst case"], [[x["name"], x["base"], x["case"]] for x in ac["ratios"]]
               + [["Rating", ac["reported"]["rating"], ac["case"]["rating"]], ["Notes", "; ".join(ac.get("notes", [])), ""]], [40, 16, 16])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def comparison_xlsx(c) -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ms = c["metrics"]
    _sheet(wb, "Comparison", ["Metric", *[f"{m['ticker']} {m['company']}" for m in ms], "Best"],
           [[label, *[m.get(k) for m in ms], (c.get("best") or {}).get(k)] for k, label, _ in c["rows"]], [36] + [24] * len(ms) + [24])
    w = c.get("writeup") or {}
    _sheet(wb, "Ranking", ["#", "Company", "Why"], [[x["rank"], x["company"], x["rationale"]] for x in w.get("ranking", [])], [5, 36, 110])
    _sheet(wb, "Write-up", ["Section", "Text"], [[k.title(), w.get(k, "")] for k in ("headline", "overall", "financial", "swot", "economic")],
           [14, 140])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

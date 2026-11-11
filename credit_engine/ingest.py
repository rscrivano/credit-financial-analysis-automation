"""Private-company statement ingestion: Excel or PDF -> mapping for review (+ notes excerpt).

PDF: text is read with pypdf; statement lines ("Net sales  28,063  27,483") are parsed by code;
the notes are cut to short keyword passages (same extractor as 10-K filings) for the Accounting
Analyst. Units (thousands / millions / dollars) and the accountant's report type (audited,
reviewed, compiled) are detected and shown on the review screen. No AI here.
"""
from __future__ import annotations

import re
from datetime import date

from .filings import CATEGORIES, extract, sanitize

# Notes to private financial statements: the usual OBS items plus what a private-credit reviewer reads first.
NOTE_CATEGORIES = {**CATEGORIES,
                   "leases": r"\blease|ASC 842",
                   "debt_covenants": r"covenant|credit facility|term loan|revolv",
                   "related_party": r"related part|affiliate|management fee",
                   "going_concern": r"going concern|substantial doubt",
                   "accountant_report": r"review report|auditor|compilation|opinion"}
from .mapper import match_label, parse_period, read_statements
from .security import check_pdf_pages, clean_text

NUM = r"\(?-?\$?\s?\d[\d,]*(?:\.\d+)?\)?|—|-(?=\s|$)"
LINE = re.compile(rf"^(?P<label>[A-Za-z][A-Za-z0-9 ,&'’/().\-:]*?[A-Za-z):])\s+(?P<nums>(?:(?:{NUM})\s*){{1,6}})$")


def statement_row(line: str):
    """A short label followed by numbers (not a wrapped sentence from the notes)."""
    m = LINE.match(line)
    if not m:
        return None
    label = m.group("label").strip(" :")
    if len(label) > 60 or label.lower().startswith("note") or label.count(" ") > 8:
        return None
    return m


def _num(tok: str):
    t = tok.strip()
    if t in ("—", "-"):
        return 0.0
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").replace("$", "").replace(",", "").strip()
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def statement_quality(text: str) -> str:
    t = text.lower()
    if "review report" in t or "reviewed the accompanying" in t:
        return "Reviewed"
    if "compilation" in t and ("compiled" in t or "compilation report" in t):
        return "Compiled"
    if "auditor" in t and ("opinion" in t or "audited the accompanying" in t):
        return "Audited"
    return "Management"


def detect_scale(text: str, values: list[float]) -> tuple[float, str]:
    t = text.lower()
    if re.search(r"in thousands|\(\$?000s?\)|\$000|thousands of", t):
        return 0.001, "Statements are in thousands; converted to US$ millions."
    if re.search(r"in millions|us\$ ?millions|\$ ?millions", t):
        return 1.0, "Statements are in millions."
    big = max((abs(v) for v in values if v), default=0)
    if big >= 100_000:
        return 1e-6, ("No unit stated and figures are large, so whole dollars assumed; converted to millions. "
                      "Confirm on the review screen.")
    return 1.0, "No unit stated; figures treated as US$ millions. Confirm on the review screen."


def read_pdf(path: str) -> dict:
    from pypdf import PdfReader
    reader = PdfReader(path)
    check_pdf_pages(len(reader.pages))
    pages = [p.extract_text() or "" for p in reader.pages]
    text = "\n".join(pages)
    periods: dict[str, dict] = {}
    rows, cols = [], []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        heads = [parse_period(m) for m in re.findall(r"(?:FY\s?)?(?:Q[1-4]\s)?20\d\d", line)]
        heads = [h for h in heads if h]
        if heads and not statement_row(line) and len(line) < 90:
            cols = heads  # new statement header: period columns in order
            for h in heads:
                periods.setdefault(f"{h['end']}|{h['months']}", {**h, "key": f"{h['end']}|{h['months']}", "header": str(h["end"].year)})
            continue
        m = statement_row(line)
        if m and cols:
            nums = [_num(x) for x in re.findall(NUM, m.group("nums"))]
            nums = nums[-len(cols):]
            if len(nums) != len(cols):
                continue
            label = m.group("label").strip(" :")
            field, method, conf = match_label(label)
            rows.append({"sheet": "PDF", "row": len(rows) + 1, "label": label, "field": field, "method": method,
                         "confidence": conf,
                         "values": {f"{c['end']}|{c['months']}": v for c, v in zip(cols, nums)}})
    # Notes: paragraphs of prose (long lines joined), for the Accounting Analyst
    paras, buf = [], []
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            if buf:
                paras.append(" ".join(buf))
                buf = []
            continue
        if statement_row(re.sub(r"\s+", " ", s)):
            if buf:
                paras.append(" ".join(buf))
                buf = []
            continue
        if re.match(r"^note\s*\d+", s, re.I) and buf:  # each note starts a new paragraph
            paras.append(" ".join(buf))
            buf = []
        buf.append(s)
        if s.endswith(".") and sum(len(x) for x in buf) > 300:
            paras.append(" ".join(buf))
            buf = []
    if buf:
        paras.append(" ".join(buf))
    paras = [p for p in paras if len(p) >= 120]
    company = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")[:80]
    return {"company": company, "periods": sorted(periods.values(), key=lambda p: (p["end"], p["months"]), reverse=True),
            "rows": rows, "_text": text, "_paras": paras}


def ingest(path: str, filename: str) -> dict:
    """Returns a mapping (for the review screen) plus notes excerpt, units and statement type."""
    if filename.lower().endswith(".pdf"):
        m = read_pdf(path)
        text, paras = m.pop("_text"), m.pop("_paras")
    else:
        m = read_statements(path)
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True)
        text = "\n".join(str(c) for ws in wb.worksheets for row in ws.iter_rows(values_only=True) for c in row
                         if isinstance(c, str))
        paras = [t for t in text.split("\n") if len(t) >= 120]
    m["company"] = clean_text(m.get("company"), 80)
    for r in m["rows"]:
        r["label"] = clean_text(r["label"])
    values = [v for r in m["rows"] for v in r["values"].values() if v is not None]
    scale, unit_note = detect_scale(text, values)
    passages, removed, flags = extract(paras, per_category=2, max_chars=8000, categories=NOTE_CATEGORIES)
    notes = "\n".join(f"[{c}#{i}] {p}" for c, ps in passages.items() for i, p in enumerate(ps, 1))
    quality = statement_quality(text)
    for p in m["periods"]:
        p["quality"] = quality
        p["end"] = str(p["end"]) if isinstance(p["end"], date) else p["end"]
    m.update(scale=scale, unit_note=unit_note, quality=quality, notes_excerpt=notes,
             notes_removed=len(removed), text_flags=flags, source_file=filename)
    return m

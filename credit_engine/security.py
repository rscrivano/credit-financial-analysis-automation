"""Hardening against bots, forged requests, hostile files and cost abuse.

Everything a browser sends to a Dash callback can be forged by a script, so every value is
re-validated here against an allow-list before it reaches the model or the scoring code.
"""
from __future__ import annotations

import json
import re
import threading
import time
import zipfile
from collections import defaultdict, deque
from datetime import date
from pathlib import Path

from .config import REPO_ROOT
from .filings import INJECTION

# ---------- limits ----------
MAX_UPLOAD_BYTES = 10_000_000
MAX_XLSX_UNZIPPED = 60_000_000      # zip-bomb guard
MAX_PDF_PAGES = 80
RATE_LIMIT = (12, 600)              # 12 analyses per 10 minutes per visitor
AI_RATE_LIMIT = (6, 3600)           # 6 AI team runs per hour per visitor
CHAT_RATE_LIMIT = (30, 3600)        # 30 chat questions per hour per visitor
MAX_QUESTION = 600
DAILY_TOKEN_CAP = 400_000           # whole app, all visitors, per day
TOKEN_LOG = REPO_ROOT / "data" / "logs" / "token_usage.jsonl"


class Rejected(Exception):
    """Input refused for safety; the message is safe to show the user."""


# ---------- uploads ----------

def check_upload(raw: bytes, ext: str) -> None:
    if len(raw) > MAX_UPLOAD_BYTES:
        raise Rejected("File is larger than 10 MB.")
    if ext == ".pdf":
        if not raw.startswith(b"%PDF-"):
            raise Rejected("That file is not a real PDF.")
        if b"/JavaScript" in raw or b"/JS " in raw or b"/Launch" in raw:
            raise Rejected("PDF contains embedded scripts or launch actions; refusing to open it.")
    elif ext == ".xlsx":
        if not raw.startswith(b"PK"):
            raise Rejected("That file is not a real Excel workbook.")
        import io
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                names = z.namelist()
                if sum(i.file_size for i in z.infolist()) > MAX_XLSX_UNZIPPED:
                    raise Rejected("Workbook expands to an unusually large size; refusing to open it.")
                if any(n.lower().endswith("vbaproject.bin") for n in names):
                    raise Rejected("Workbook contains macros; save it as a plain .xlsx and try again.")
                if "[Content_Types].xml" not in names:
                    raise Rejected("That file is not a valid Excel workbook.")
        except zipfile.BadZipFile as e:
            raise Rejected("That file is not a valid Excel workbook.") from e
    else:
        raise Rejected("Only .xlsx and .pdf files are accepted.")


def check_pdf_pages(n: int) -> None:
    if n > MAX_PDF_PAGES:
        raise Rejected(f"PDF has {n} pages; the limit is {MAX_PDF_PAGES}. Upload the statements and notes only.")


def clean_text(s, limit: int = 120) -> str:
    """Labels and names from uploaded files: strip control characters and anything that reads like an
    instruction to an AI; cap the length."""
    s = re.sub(r"[\x00-\x1f\x7f]", " ", str(s or ""))[:limit]
    return "[removed: looked like an instruction]" if INJECTION.search(s) else s.strip()


# ---------- forged callback values ----------
SP_FITCH = re.compile(r"^(AAA|AA[+-]?|A[+-]?|BBB[+-]?|BB[+-]?|B[+-]?|CCC[+-]?|CC|C|D|SD|RD)$")
MOODYS = re.compile(r"^(Aaa|Aa[123]|A[123]|Baa[123]|Ba[123]|B[123]|Caa[123]|Ca|C)$")
ALLOWED = {
    "lease_interest_share": {0.25, 0.5, round(1 / 3, 6)},
    "floating_share": {0.0, 0.5, 1.0},
    "lease_basis": {"on", "off"},
    "fin_risk_rule": {"weaker", "stronger", "middle", "ffo"},
    "business_risk": {"Excellent", "Strong", "Satisfactory", "Fair", "Weak", "Vulnerable"},
    "volatility_table": {"standard", "medial", "low"},
    "cash_netting": {"on", "off"},
}
OBS_CATEGORIES = {"guarantee", "purchase_obligation", "unconsolidated_entity", "receivables_financing", "pension_opeb",
                  "contingency", "other_commitment"}
MICRO = {"top_customer_pct": (0, 100), "top_supplier_pct": (0, 100), "recurring_pct": (0, 100),
         "pricing_power": {"yes", "partly", "no"}, "sponsor_owned": {"yes", "no"}}


def sanitize_choices(ch: dict, sector_keys: set) -> dict:
    """Keep only known keys with allowed values; drop everything else silently."""
    out = {}
    for k, v in (ch or {}).items():
        if k == "sector" and v in sector_keys:
            out[k] = v
        elif k in ("lease_interest_share", "floating_share"):
            try:
                f = round(float(v), 6)
            except (TypeError, ValueError):
                continue
            if f in ALLOWED[k]:
                out[k] = f
        elif k in ALLOWED and v in ALLOWED[k]:
            out[k] = v
        elif k == "obs_include" and isinstance(v, dict):
            out[k] = {c: (1.0 if float(x) >= 0.5 else 0.0) for c, x in v.items() if c in OBS_CATEGORIES
                      and isinstance(x, (int, float))}
        elif k == "micro" and isinstance(v, dict):
            m = {}
            for q, a in v.items():
                rule = MICRO.get(q)
                if isinstance(rule, tuple):
                    try:
                        f = float(a)
                    except (TypeError, ValueError):
                        continue
                    if rule[0] <= f <= rule[1]:
                        m[q] = f
                elif rule and a in rule:
                    m[q] = a
            out[k] = m
        elif k == "analyst_case" and isinstance(v, dict):
            from .stress import CASE_KEYS
            c = {}
            for q, a in v.items():
                try:
                    f = float(a)
                except (TypeError, ValueError):
                    continue
                if q in CASE_KEYS and f == f and CASE_KEYS[q][0] <= f <= CASE_KEYS[q][1]:
                    c[q] = f
            if c:
                out[k] = c
        elif k == "agency_ratings" and isinstance(v, dict):
            out[k] = {a: r.strip() for a, r in v.items() if isinstance(r, str) and
                      ((a == "Moody's" and MOODYS.match(r.strip())) or (a in ("S&P", "Fitch") and SP_FITCH.match(r.strip().upper())))}
    return out


def bad_agency_entries(entries: dict) -> list[str]:
    bad = []
    for a, r in (entries or {}).items():
        r = (r or "").strip()
        if r and not ((a == "Moody's" and MOODYS.match(r)) or (a in ("S&P", "Fitch") and SP_FITCH.match(r.upper()))):
            bad.append(f"{a} '{r[:8]}'")
    return bad


def sanitize_overrides(ov: dict, period_labels: set, fields: set) -> dict:
    """Statement edits: only real periods and fields, finite numbers within a sane range."""
    out = {}
    for p, edits in (ov or {}).items():
        if p not in period_labels or not isinstance(edits, dict):
            continue
        for f, v in edits.items():
            if f not in fields:
                continue
            if v in (None, ""):
                out.setdefault(p, {})[f] = None
                continue
            try:
                x = float(v)
            except (TypeError, ValueError):
                continue
            if x == x and abs(x) < 1e9:  # not NaN, < $1 quadrillion in millions
                out.setdefault(p, {})[f] = x
    return out


# ---------- rate limits and the daily token ceiling ----------
_hits: dict = defaultdict(deque)
_lock = threading.Lock()


def rate_limit(client: str, kind: str = "run") -> None:
    limit, window = {"ai": AI_RATE_LIMIT, "chat": CHAT_RATE_LIMIT}.get(kind, RATE_LIMIT)
    now = time.time()
    with _lock:
        q = _hits[(client, kind)]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            raise Rejected(f"Too many requests from this browser; try again in {int(window - (now - q[0])) // 60 + 1} min.")
        q.append(now)


def tokens_used_today() -> int:
    if not TOKEN_LOG.is_file():
        return 0
    today, total = date.today().isoformat(), 0
    for line in TOKEN_LOG.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if str(r.get("ts", "")).startswith(today):
            total += int(r.get("input_tokens", 0)) + int(r.get("output_tokens", 0))
    return total


def ai_allowed_today() -> bool:
    return tokens_used_today() < DAILY_TOKEN_CAP


# ---------- HTTP layer ----------

def harden_server(server, password_env: str = "APP_PASSWORD") -> None:
    """Security headers, request-size cap, and optional password (for when the app is hosted online)."""
    import os
    from flask import Response, request

    server.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # base64 uploads are ~1.33x the file

    @server.after_request
    def _headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = "frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return resp

    pw = os.environ.get(password_env, "").strip()
    if pw:
        import hmac

        @server.before_request
        def _auth():
            a = request.authorization
            if not (a and hmac.compare_digest(a.password or "", pw)):
                return Response("Login required", 401, {"WWW-Authenticate": 'Basic realm="CFAA"'})

"""S&P, Moody's and Fitch ratings as disclosed in the company's own SEC filings (code only, no AI).

Agency ratings themselves are licensed data, so the app does not scrape the agencies. Many
issuers state their ratings (or at least whether they are investment grade) in the 10-K/10-Q;
this finds those statements and returns the exact sentence as the source. Private companies:
the user enters ratings by hand.
"""
from __future__ import annotations

import re
from typing import Optional

AGENCIES = {"S&P": re.compile(r"S&P|Standard\s*(?:&|and)\s*Poor", re.I), "Moody's": re.compile(r"Moody", re.I),
            "Fitch": re.compile(r"\bFitch\b", re.I)}
SP_FITCH = re.compile(r"(?<![A-Za-z])(AAA|AA[+-]?|A[+-]|BBB[+-]?|BB[+-]?|B[+-]|CCC[+-]?|CC)(?![A-Za-z0-9])")
MOODYS = re.compile(r"(?<![A-Za-z])(Aaa|Aa[123]|A[123]|Baa[123]|Ba[123]|B[123]|Caa[123]|Ca)(?![A-Za-z0-9])")
OUTLOOK = re.compile(r"\b(stable|positive|negative|developing)\b(?=[^.]{0,40}outlook)|outlook[^.]{0,40}\b(stable|positive|negative|developing)\b", re.I)
IG = re.compile(r"(below|non|sub)[- ]investment[- ]grade|speculative[- ]grade|investment[- ]grade", re.I)


def _sentences(paragraphs: list[str]):
    for p in paragraphs:
        for s in re.split(r"(?<=[.;])\s+(?=[A-Z])", p):
            if 30 <= len(s) <= 900:
                yield s


def find_ratings(paragraphs: list[str], source: str) -> dict:
    """{agency: {"rating", "outlook", "quote", "source", "kind"}}; kind = "letter" or "category"."""
    found: dict = {}
    for s in _sentences(paragraphs):
        if not re.search(r"rat(ing|ed)|investment[- ]grade|outlook", s, re.I):
            continue
        mentions = [(a, m.start()) for a, rx in AGENCIES.items() for m in rx.finditer(s)]
        if not mentions:
            continue
        outlook_of = {}  # each outlook phrase belongs to the agency named nearest to it
        for ol in OUTLOOK.finditer(s):
            nearest = min(mentions, key=lambda m: abs(m[1] - ol.start()))[0]
            outlook_of.setdefault(nearest, (ol.group(1) or ol.group(2)).title())
        for agency, pos in mentions:
            outlook = outlook_of.get(agency)
            rx = MOODYS if agency == "Moody's" else SP_FITCH
            toks = [(abs(m.start() - pos), m.group(1)) for m in rx.finditer(s)]
            if toks:  # nearest grade of the right scale to this agency's name
                rating = min(toks)[1]
                cur = found.get(agency)
                if not cur or cur["kind"] != "letter":
                    found[agency] = {"rating": rating, "outlook": outlook, "quote": s.strip(), "source": source, "kind": "letter"}
            elif agency not in found:
                ig = IG.search(s)
                if ig:
                    label = "Below investment grade" if re.match(r"(below|non|sub|speculative)", ig.group(0), re.I) else "Investment grade"
                    found[agency] = {"rating": label, "outlook": outlook, "quote": s.strip(), "source": source, "kind": "category"}
    return found


def merge(primary: dict, fallback: dict) -> dict:
    """Prefer the newer filing's statement; keep the older one only where the newer is silent."""
    out = dict(fallback)
    for k, v in primary.items():
        if k not in out or v["kind"] == "letter" or out[k]["kind"] != "letter":
            out[k] = v
    return out


def manual(entries: Optional[dict]) -> dict:
    return {a: {"rating": r.strip(), "outlook": None, "quote": "", "source": "Entered by user", "kind": "letter"}
            for a, r in (entries or {}).items() if r and str(r).strip()}

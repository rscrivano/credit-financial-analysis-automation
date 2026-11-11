"""Fetch the latest 10-K text and cut it down to the passages the agents need.

No LLM here. The extractor keeps only paragraphs that mention off-balance-sheet
style items AND contain amounts, capped at ~12k characters (~3k tokens), and
strips sentences that look like instructions aimed at an AI (prompt injection).
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from .edgar import CACHE_DIR, EdgarError, _user_agent, submissions

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
MAX_EXCERPT_CHARS = 12000

CATEGORIES = {
    "guarantee": r"guarantee|letters? of credit|surety",
    "purchase_obligation": r"purchase (?:commitment|obligation)|take-or-pay|firm (?:aircraft )?orders?|commitments? to (?:purchase|acquire)|(?:aircraft|engine) (?:purchase )?commitments?",
    "unconsolidated_entity": r"variable interest entit|unconsolidated|joint venture|equity method",
    "receivables_financing": r"factoring|securitiz|supplier finance|supply chain financ",
    "pension_opeb": r"pension|postretirement|funded status|underfunded",
    "contingency": r"litigation|contingenc|legal proceedings|loss contingenc",
    "other_commitment": r"off-balance sheet|earn-?out|unfunded commitment|leases? (?:that )?ha(?:ve|s) not (?:yet )?commenced",
    "debt_instruments": r"senior (?:unsecured |secured )?notes|notes due|term loan|revolving credit|credit (?:facility|agreement)|debentures|equipment notes|equipment trust|convertible notes|bonds due",
}
INJECTION = re.compile(
    r"(ignore|disregard|forget)\s+(all|any|the|previous|prior|above)[^.]{0,40}(instruction|prompt|rule)"
    r"|you are (now )?(an?|the) (ai|assistant|model)|system prompt|as an ai\b|assign (a|an|the) rating"
    r"|rate (this|the) (company|issuer)|<\s*/?\s*(system|assistant|user)\s*>", re.I)
# Specific wording only, so boilerplate risk-factor language doesn't trigger a flag.
TEXT_FLAGS = {
    "going_concern": re.compile(r"substantial doubt (?:about|regarding) (?:the company's|our|its) ability to continue as a going concern(?! (?:is|was) alleviated)", re.I),
    "material_weakness": re.compile(r"(?:identified|existence of|there (?:is|was)) an? material weakness(?:es)? in (?:our|the company's) internal control", re.I),
    "restatement": re.compile(r"restatement of (?:our|the company's|its) previously (?:issued|reported)|(?:have|has) been restated to", re.I),
}
AMOUNT = re.compile(r"\$\s?\d|\d[\d,.]*\s*(million|billion)", re.I)
QUANTITY = re.compile(r"\$\s?\d|\b\d{2,}\b")  # commitments are often stated in units (e.g., 168 aircraft)


class _Text(HTMLParser):
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "table", "section"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_paragraphs(raw: str) -> list[str]:
    p = _Text()
    p.feed(raw)
    text = html.unescape("".join(p.parts)).replace("\xa0", " ")
    paras = [re.sub(r"\s+", " ", x).strip() for x in re.split(r"\n\s*\n|\n", text)]
    return [x for x in paras if len(x) >= 120]


@dataclass
class FilingExcerpt:
    form: str
    accession: str
    filed: str
    url: str
    text: str                       # what the agent sees
    passages: dict = field(default_factory=dict)  # category -> list of passages
    removed_injections: list = field(default_factory=list)
    keyword_flags: dict = field(default_factory=dict)  # flag -> evidence sentence


def latest_filing(cik: int, forms=("10-K",)) -> dict:
    sub = submissions(cik)
    r = sub["filings"]["recent"]
    for i, form in enumerate(r["form"]):
        if form in forms:
            return {"form": form, "accession": r["accessionNumber"][i], "filed": r["filingDate"][i],
                    "doc": r["primaryDocument"][i]}
    raise EdgarError(f"No {'/'.join(forms)} filing found.")


def _fetch_text(url: str) -> str:
    import gzip
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": _user_agent(), "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
    return data.decode("utf-8", errors="replace")


def sanitize(passage: str) -> tuple[str, list[str]]:
    """Drop sentences that read like instructions to an AI. Returns (clean text, removed sentences)."""
    kept, removed = [], []
    for s in re.split(r"(?<=[.!?])\s+", passage):
        (removed if INJECTION.search(s) else kept).append(s)
    return " ".join(kept), removed


def extract(paragraphs: list[str], per_category: int = 3, max_chars: int = MAX_EXCERPT_CHARS, categories=None):
    passages, removed, used, budget = {}, [], set(), max_chars
    for cat, pat in (categories or CATEGORIES).items():
        rx = re.compile(pat, re.I)
        # Commitments are often stated in units; note categories (covenants, related parties, the accountant's
        # report, going concern) matter with or without an amount.
        need = (QUANTITY if cat in ("purchase_obligation", "other_commitment") else
                re.compile(".") if cat in ("debt_covenants", "related_party", "going_concern", "accountant_report", "leases")
                else AMOUNT)
        hits = [p for p in paragraphs if rx.search(p) and need.search(p) and p not in used]
        hits.sort(key=lambda p: (-len(rx.findall(p)), len(p)))
        for p in hits[:per_category]:
            clean, bad = sanitize(p[:1800])
            removed += bad
            if clean and len(clean) <= budget:
                passages.setdefault(cat, []).append(clean)
                used.add(p)
                budget -= len(clean)
    flags = {}
    for name, rx in TEXT_FLAGS.items():
        for p in paragraphs:
            m = rx.search(p)
            if m:
                flags[name] = p[max(0, m.start() - 150): m.end() + 150]
                break
    return passages, removed, flags


def build_excerpt(meta: dict, paragraphs: list[str], url: str = "") -> FilingExcerpt:
    passages, removed, flags = extract(paragraphs)
    lines = []
    for cat, ps in passages.items():
        for j, p in enumerate(ps, 1):
            lines.append(f"[{cat}#{j}] {p}")
    return FilingExcerpt(meta["form"], meta["accession"], meta["filed"], url, "\n".join(lines),
                         passages, removed, flags)


def get_excerpt(cik: int) -> FilingExcerpt:
    meta, paragraphs, url = filing_paragraphs(cik, ("10-K",))
    return build_excerpt(meta, paragraphs, url)


def filing_paragraphs(cik: int, forms=("10-K",)) -> tuple[dict, list[str], str]:
    """Latest filing of the given form(s) as text paragraphs, cached by accession number."""
    meta = latest_filing(cik, forms)
    acc = meta["accession"].replace("-", "")
    path = CACHE_DIR / "filings" / f"{acc}.txt"
    url = DOC_URL.format(cik=cik, acc=acc, doc=meta["doc"])
    if path.is_file():
        paragraphs = path.read_text(encoding="utf-8").split("\n")
    else:
        paragraphs = html_to_paragraphs(_fetch_text(url))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(paragraphs), encoding="utf-8")
    return meta, paragraphs, url

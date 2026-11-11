# Credit/Financial Analysis Automation

Credit, sector and economic analysis for **public companies** (ticker → SEC filings) and **private companies**
(upload their financial statements as Excel or PDF, including notes). A toggle switches between the two.

- **Ratings:** the author's credit spread scorecard (Reported and Lease-adjusted bases) plus an
  S&P-methodology anchor (business risk × financial risk). Code does all the math.
- **Private statements:** read from Excel or PDF (units and audit/review/compilation status detected), shown to the user
  to confirm, then editable in the app with tracked edits. Data-integrity red flags (e.g., balance sheet doesn't balance).
- **Sector & competitors:** 22 sectors benchmarked on 8,900+ SEC filers; named competitors; Strong/Normal/Struggling tiers.
- **Economic:** FRED macro and industry indicators; stress tests (rate shock, the sector's 2020 recession, reverse stress).
- **AI analyst team:** Accounting, Financial/Credit, Macro, Micro (sector) analysts → Manager (one review) → Report Writer
  (SWOT summary and detailed sections). Each task has at most 3 attempts, then escalates to the Manager; a per-run token
  budget and caching keep cost low. Every quote and number the AI writes is checked against the source data.
- **Assumptions & Uncertainties:** every judgment call is listed with options; changing one re-scores with code.

**New here?** Open [`docs/user_guide.html`](docs/user_guide.html) (how to use every feature) and
[`docs/agent_design.html`](docs/agent_design.html) (how the AI analyst team is organized, with a traced run). The app's
start page and the **? HOW TO USE THIS APP** panel give the same quick start inside the app.

## Run the web app (about 5 minutes from a fresh clone)
Needs Python 3.10+.
```bash
python -m venv .venv
.venv\Scripts\activate        # Windows (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:8050. **Public company:** type a ticker (try `LUV`, `ULCC`, `DAL`). **Private company:** switch the
toggle, upload the statements, confirm what the app read, pick the sector. To try it without real data, upload
`data/samples/sample_private_reviewed_statements.pdf` (illustrative; built from public numbers, with a deliberate
balance-sheet error so the red flag shows) or `data/samples/sample_private_company_statements.xlsx`.
AI needs `PORTKEY_API_KEY` (or `OPENAI_API_KEY`) in `.env` here or one folder up; without it the app still
rates the company and lists every assumption, and skips the AI sections. No other keys are needed: the model
defaults to `gpt-6-luna` and the SEC contact is built in.

If `pip install` fails on Windows with a "No such file or directory" error inside `.venv`, the folder path is too
long for Windows (260-character limit): clone into a shorter path such as `C:\work\`.

Tested from a fresh copy on 2026-11-10 with `.env` one folder up containing only `PORTKEY_API_KEY`: install took
4 min 41 s, all 79 tests passed, a live SEC analysis (DAL) took 6 s, and the AI chat answered on `gpt-6-luna`.
If your `.env` sets `OPENAI_MODEL`, that model is used instead of `gpt-6-luna`; leave it out with the course key.

Stop the app with Ctrl+C.

## Layout
| Path | What |
|---|---|
| `credit_engine/engine.py` | App scoring: EBITDA section, Reported and Lease-adjusted bases, "Ratio is Infinite" / "Data is Missing", LTM |
| `credit_engine/template_mode.py` | Exact reproduction of the Excel template (used to prove the port matches) |
| `credit_engine/scorecard.py` | Ratio → notch → score → rating |
| `credit_engine/config/ryan_template_scorecard.json` | Weights, notch scale, threshold grid (extracted from the workbook by `tools/extract_scorecard.py`) |
| `credit_engine/workbook_import.py` | Load any workbook built on the template |
| `credit_engine/edgar.py` | SEC EDGAR client (ticker → CIK → XBRL facts), disk cache, offline fallback |
| `credit_engine/xbrl_map.py` | XBRL tags → spread lines; annual, YTD, quarterly periods; source trace |
| `credit_engine/cli.py` | Command-line run |
| `app.py` + `assets/style.css` | Dash web app: start page and guide, 11 tabs, compare mode, exports, watchlist, analyst chat |
| `views.py` | Screens: tabs, comparison view, landing page, tab help |
| `docs/user_guide.html`, `docs/agent_design.html` | First-time user guide; agent organization, guardrails and a traced run |
| `credit_engine/compare.py`, `chat.py`, `export.py`, `watch.py` | Comparison, analyst chat, Excel/Word/PDF exports, watchlist |
| `credit_engine/integrity.py` | Data-integrity red flags (balance sheet, subtotals, signs, swings, YTD tie-out) |
| `credit_engine/sector.py`, `config/sectors.json`, `data/benchmarks/` | 22 sectors, SEC-derived percentiles, health tiers |
| `credit_engine/sp_method.py` | S&P-style anchor: business x financial risk |
| `credit_engine/macro.py`, `credit_engine/stress.py` | FRED macro/industry indicators; stress tests |
| `credit_engine/mapper.py` | Any-format Excel to template mapping (code first, AI for leftovers) |
| `credit_engine/workbook_export.py`, `data/templates/` | Blank private-company template; export a spread to it |
| `tools/build_benchmarks.py`, `tools/logic_test_private.py` | Rebuild benchmarks; private-path logic test |
| `views.py` | Report views for the web app |
| `credit_engine/team.py` | Manager + 5 analysts, 3-attempt cap, escalation, token budget, cache |
| `credit_engine/ingest.py` | Private statements from Excel/PDF: lines, units, statement type, notes excerpt |
| `credit_engine/pipeline.py` | Full run: data → ratings → AI agents → checks → report |
| `credit_engine/agents.py` | Filing Analyst + Credit Writer agents, quote and number verification |
| `credit_engine/filings.py` | Latest 10-K → short excerpt (~1.5k tokens), prompt-injection screen |
| `credit_engine/accounting.py` | Rule-based accounting flags |
| `credit_engine/uncertainty.py` | Assumptions & Uncertainties register with re-scored options |
| `credit_engine/llm.py` | Portkey/OpenAI model, per-agent token caps, token log (`data/logs/`) |
| `data/sample/` | Offline sample (Southwest `LUV`, Frontier `ULCC`) used when SEC is unreachable |
| `tests/` | Regression tests vs. the two workbooks + rule tests |

## Run the tests
```bash
python -m venv .venv
.venv\Scripts\activate        # Windows (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
python -m pytest -q
```

## Run from the command line
```bash
python -m credit_engine.cli LUV
```
SEC requires a contact in the request header. The project's contact is built in, so any ticker works from a
fresh clone with no extra setup. To use your own, set it in `.env` (the app looks in this folder, then one folder up):
```
SEC_USER_AGENT=Your App Name your.email@example.com
```
If SEC can't be reached, the app uses its local cache, then the bundled offline sample (LUV and ULCC).

## Security
- Uploads are checked by content (real PDF/XLSX), with caps on size, PDF pages and unzipped size. PDFs with scripts and
  macro workbooks are refused, and text from uploads and filings is screened for instructions aimed at the AI.
- Every value the browser sends is re-validated on the server against an allow-list (forged requests are dropped).
- Per-visitor rate limits and an app-wide daily AI token ceiling stop cost abuse; each AI task is capped at 3 attempts.
- Security headers (no framing, nosniff, restrictive CSP), a request-size cap, and no stack traces in errors.
- If you host it online, set `APP_PASSWORD` in `.env` to require a password. Locally it only listens on 127.0.0.1.

## Analyst add-ons

- **Compare companies.** Choose *Public company → Compare companies*. Enter two or more tickers (use **+ Add company**, up to 10) and press **COMPARE**. You get a side-by-side table, a ranking, and financial, SWOT and economic write-ups. Toggle to any single company to review it in depth.
- **Export.** **Excel** gives the full analysis (scorecard, statements, peers, debt, stress, red flags, assumptions). **Memo (Word)** and **Memo (PDF)** give a credit memo. Exports use no AI tokens.
- **Watchlist.** **+ Watchlist** saves the company in this browser. **Check for new filings** looks for a newer 10-K or 10-Q and re-scores only the companies that have one (code only).
- **Analyst case.** In the *3 CREDIT* tab, enter EBITDA add-backs, debt adjustments or a one-year projection. Your case's rating is shown beside Reported, which never changes.
- **Ask the analyst.** A chat that answers questions using only the analysis on screen. Numbers in answers are checked against the data, and repeat questions are answered free from the cache. Limited to 30 questions per hour per browser.

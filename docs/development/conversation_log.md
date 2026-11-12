# Conversation Log — MGMT 409 Final Project (AI Credit Analysis App)

Running record of planning and build conversations for this assignment. Newest session at the bottom.
Source PDF of the earlier session: `docs/background/credit_app_conversation.pdf`.

---

## Session 0 — Earlier Claude account (exported 2026-11-08)
Summary of the prior chat (full text in the PDF):

- **Idea:** AI-automated credit analysis tool. Enter a ticker (public) or upload financials (private credit). Pulls filings, computes credit metrics, adds qualitative/macro context, flags possible accounting errors, stress tests distance to distress, and outputs two ratings:
  1. **Full implied rating** — S&P/Moody's-style scorecard weights incl. macro, trend, volatility.
  2. **Strictly financial rating** — fundamentals only.
- **Agreed features:** quarterly/annual/both toggle with date ranges; accounting flags (Beneish M, Altman Z, Piotroski F, accruals, tie-outs) framed as "flags for review"; reverse stress test; lease-adjusted debt (finance + operating leases into ST/LT debt, EBITDA adjusted to avoid double penalty, reported vs. adjusted side by side; private fallback = 8x rent capitalization labeled as estimate); off-balance-sheet lens (purchase obligations, guarantees/LCs, unconsolidated VIEs/JV debt, factoring/securitization/SCF, pension/OPEB, contingencies, earnouts/unfunded commitments) with source excerpt, classification, probability-weighted debt equivalent, and before/after toggle; private upload with a mapping review screen and custom covenant definitions; source trace on every number.
- **Eight drill-down layers:** Summary · Financial profile · Debt & leases · Off-balance-sheet · Accounting flags · Macro & qualitative · Stress test · Source trace.
- **Design principles:** numbers from deterministic code, LLM only for qualitative extraction/classification/narrative with citations; call output an "implied credit score," not an agency rating (NRSRO caution).
- **Competitors named:** S&P Capital IQ, Bloomberg, Moody's CreditLens, Fitch Solutions, AI filings-analysis startups. Edge: price, speed, integrated one-click output for smaller funds, community-bank credit analysts, independent investors.
- **Open item:** user to share their existing credit spread model (inputs/outputs or spreadsheet) so it becomes the calculation core.
- **Planned build order:** public-ticker MVP + lease adjustment → spread model → off-balance-sheet lens → stress test → private uploads with review screen.

---

## Session 1 — 2026-11-08 (Claude Code, desktop app)

**User request:** Save everything for this assignment under `Final Exam Project`; catch Claude up from the PDF; keep a record of the conversation.

**Done this session:**
- Created `Final Exam Project/docs/` with:
  - `assignment_brief.md` — the MGMT 409 final project requirements, deliverables, rules, and rubric.
  - `conversation_log.md` — this file.
  - `background/credit_app_conversation.pdf` — copy of the earlier session export.

**Observations raised to the user:**
- Due date is **Mon Nov 16, 2026** — 8 days out. Scope needs to fit: a working public-ticker MVP with a multi-agent design, measured tokens, and a demonstrated safety defense beats a broad app that half-works.
- The earlier session assumed no access to SEC EDGAR. This project runs locally on the user's machine, so the app can call EDGAR's free XBRL "companyfacts" API and FRED directly.
- Model ID mismatch: brief says `gpt-6-luna` on the course Portkey key; workspace AGENTS.md says `gpt-5.6-luna`. Keep it in `OPENAI_MODEL` and confirm.
- Private-credit uploads and the full eight layers are likely "next steps" for the report unless time allows.
- Tier 3 requires a real user test (e.g., a credit analyst timing a manual tearsheet vs. the app).

**Open items / waiting on user:**
- The credit spread model (spreadsheet or inputs/outputs).
- Scope decision for the Nov 16 deadline.
- A real user (analyst colleague) for the impact test.

---

## Session 1 (cont.) — 2026-11-08: Spread template received

**User:** Shared two manual credit workbooks from the MGMT 410 group project (`Credit Spread Frontier.xlsx`, `Credit Spread Southwest.xlsx`) as the credit spread template to integrate. **Deadline extended to Mon Nov 23, 2026** (disregard Nov 16).

**Done:**
- Copied both workbooks to `docs/background/spread_model/`.
- Reverse-engineered the template into `docs/spread_model_spec.md`: the input rows, derived metrics (FFO, FCF, DCF), the nine weighted ratios, the S&P 2006–08 median threshold grid, notch scoring, and the score-to-rating lookup.
- Updated the deadline in `assignment_brief.md` and in Claude's memory.

**Key findings (details in the spec):**
- The template is a spreading template plus an S&P-median scorecard that outputs an implied rating per period. It does not output a spread in bps.
- Results as spread: Southwest 9M YTD **BBB**, FY25 **BB**; Frontier 9M YTD **CC**, FY24 **B**.
- Issues to confirm:
  1. N/A ratios drop out without re-weighting, which improves the score (Southwest FY25 is BB as shown, CCC+ if re-weighted, BB if net interest income scores AAA).
  2. The lookup table makes BB+ impossible to output (BBB-/BB+ rows swapped). Southwest Q2 26 and FY23 should be BB+.
  3. EBITDA = operating income in both spreads because D&A was left in COGS. Southwest 9M EBITDA is 994 vs. 2,192 corrected; Debt/EBITDA 4.6x → 2.1x.
  4. The empty FY22 column still shows B+.
  5. Lease treatment isn't a rule.
  6. The commentary text is stale and copied between the two workbooks.
  7. The benchmarks are old and sector-blind.
  8. Quarterly annualization is volatile; LTM is the better view.
- Plan: port the template to a deterministic Python engine. Use the two workbooks as regression tests ("template-faithful" mode must match Excel exactly), then add a "corrected" mode with each fix labeled. These two workbooks also give "before" evidence for the report: a manual spread and its errors vs. the app.

**Open decisions for Ryan:** how to treat negative net interest / N/A ratios; whether EBITDA in the template was intentionally EBIT; whether operating leases go into Total Debt by default (earlier agreed: yes).

---

## Session 1 (cont.) — 2026-11-08: Scoring rules decided

Discussed the open questions on the spread template. **Ryan's decisions:**
1. Unscorable ratios show a clear message: **"Ratio is Infinite"** (scored top notch) or **"Data is Missing"** (excluded and re-weighted, with the share of the scorecard used shown).
2. Add an **EBITDA result section** (Operating Income + D&A). Don't over-analyze the existing template.
3. Show the **Reported basis first, then the Lease-adjusted basis**.
4. Agreed: **LTM** is the primary period view, and the **template benchmarks/weights stay the default** (sector grids are a next step).

Recorded in `spread_model_spec.md` → "Decisions". Next: build the deterministic Python scoring engine, with the two workbooks as regression tests.

---

## Session 1 (cont.) — 2026-11-08: Scoring engine built

**User:** "Yes, start building."

**Built** in `Final Exam Project/credit_app/` (the future GitHub repo):
- `credit_engine/` — Python scoring engine.
  - `template_mode.py` reproduces the Excel workbook formula for formula.
  - `engine.py` applies the agreed rules: EBITDA section (OI + D&A); "Ratio is Infinite" (scored top notch when good for the credit, bottom notch when bad, e.g. negative EBITDA leverage); "Data is Missing" (re-weighted; no rating if more than 1/3 of the weight is missing); Reported basis then Lease-adjusted basis (debt + operating lease liabilities, EBITDA + lease cost, 1/3 of lease cost treated as interest); LTM as the primary period when buildable.
- `config/ryan_template_scorecard.json` — weights, notch scale and threshold grid, pulled straight from the workbook by `tools/extract_scorecard.py` (identical in both workbooks).
- `workbook_import.py` — loads any workbook built on the template. This doubles as a private-credit input path.
- Tests: **25/25 pass.** 14 regression tests match every ratio, notch, score and rating in both workbooks exactly; 11 tests cover the decision rules.
- `requirements.txt`, `.gitignore`, starter `README.md`.

**Two more template issues found while porting** (added to the spec as #10–11): return on capital is annualized twice (9M overstated ~1.33x, quarters ~4x), and the FCF working-capital change uses the adjacent column instead of the opening balance sheet.

**Workbook vs. app (Reported basis)** — evidence for the report's Impact section:

| Period | Southwest: workbook → app | Frontier: workbook → app |
|---|---|---|
| 9M YTD Sep-26 | BBB → BBB+ | CC → CC |
| Q3-26 | BBB → BBB | CC → CC |
| Q2-26 | BBB- → BB+ | CC+ → CC+ |
| Q1-26 | A- → A- | CC → CC |
| FY25 | BB → BB+ | CC → CC |
| FY24 | BB- → BB | B → B+ |
| FY23 | BB → BB+ (91% scored) | CC+ → CCC (91% scored) |

LTM can't be built from these workbooks (no prior-year 9M), so the latest period is primary; LTM will work once EDGAR quarterly data is wired in. Lease-adjusted shows "Data is Missing" because the template has no lease inputs; EDGAR will supply them.

**Not done yet:** no virtual environment (tests ran from a temporary package folder; per AGENTS.md, create `.venv` with OneDrive paused); no git repo yet; SEC EDGAR data agent, LLM agents and UI are next.

---

## Session 1 (cont.) — 2026-11-08: SEC EDGAR data pull built

**User:** "Yes, EDGAR next." For SEC's required User-Agent contact, Ryan chose **ryanscrivano@gmail.com**. It's stored as `SEC_USER_AGENT` in `credit_app/.env` (gitignored), not in code.

**Built** (in `credit_app/credit_engine/`):
- `edgar.py` — ticker → CIK → SEC XBRL company facts. Validates the ticker before it touches a URL, rate-limits, caches to disk (`data/cache/`, gitignored), and falls back to the bundled sample when offline or when no `SEC_USER_AGENT` is set.
- `xbrl_map.py` — maps XBRL tags to the template lines with fallbacks, keeping a source for every number (tag, form, filing date, accession). Builds annual, YTD, prior-year YTD and quarterly periods. Quarterly cash flows and Q4 are derived from year-to-date figures. Total liabilities are derived when they aren't tagged. Interest follows Ryan's net convention (gross − capitalized − interest income). Lease cost that's only tagged annually is estimated pro rata and labeled as an estimate.
- `config.py` — loads `.env` from the repo folder, then one folder up (the course's submission layout).
- `engine.py` — now takes opening balance sheets separately and tolerates 52/53-week fiscal calendars.
- `cli.py` — `python -m credit_engine.cli LUV`.
- `data/sample/` — trimmed SEC data for Southwest and Frontier (~0.4 MB) for offline runs and tests.
- Tests: **38/38 pass** (14 template regression, 11 rule tests, 13 SEC-mapping tests, including ticker-injection inputs and the offline fallback).

**Results from live SEC data (LTM Sep-26 is now the primary view):**
- Southwest: **BBB-** Reported / **BB+** Lease-adjusted.
- Frontier: **CC** Reported / **B-** Lease-adjusted.

**Validation vs. Ryan's hand spreads** (`docs/validation_edgar_vs_workbook.md`): 33 of 48 lines match exactly. Every income statement line, total assets, total liabilities and cash ties. The rest:
- **Debt:** the workbooks put operating leases inside debt. FY25 ties to the dollar once the app adds them, and the hand spreads did this inconsistently between periods.
- **Interest:** capitalized interest isn't in SEC's standard tags.
- **Hand-entry errors:** Frontier's 9M capex was entered with the wrong sign, and its Q3 CFO looks like a typo (−1 vs. −41).

**Flagged for Ryan:**
- Frontier's lease-adjusted rating is *better* than reported. With negative EBITDA, the reported basis treats leverage as unbounded (C), while adding back $1B of rent makes EBITDAR positive. This is mathematically consistent and the same effect the rating agencies see, but the UI should explain it.
- The teaching staff's `.env` will only have `PORTKEY_API_KEY` and `OPENAI_API_KEY`, so without `SEC_USER_AGENT` they'd be limited to the LUV/ULCC sample. Decide whether to ship a default contact in code.

---

## Session 1 (cont.) — 2026-11-08: SEC contact, Delta fix, efficiency goal

- **SEC contact:** after discussing the exposure risk, Ryan chose his rarely used **ryanscrivano1@gmail.com**. It's built in as the default User-Agent (`edgar.DEFAULT_USER_AGENT`) so graders can pull any ticker from a fresh clone; `SEC_USER_AGENT` in `.env` overrides it. Verified with a live pull and no `.env`.
- **Mapping fix found by testing more tickers:** Delta reports only net interest (`InterestIncomeExpenseNonoperatingNet`) and got "Insufficient data". Added that tag as a fallback. Live LTM Sep-26 Reported / Lease-adjusted: Delta A- / BBB, United BB / BB, American CCC+ / CCC+, JetBlue CC / CC, Alaska CCC+ / CCC+. 38/38 tests pass.
- **New principle from Ryan: be token-efficient, both while building and in the app's runtime use, for environmental reasons.** Design rules adopted:
  1. All math stays in deterministic Python. The LLM never calculates.
  2. Agents receive compact computed summaries (ratios, flagged items, short filing excerpts), never whole filings.
  3. Cache every result keyed by the filing's accession number, so a company is analyzed once per new filing.
  4. Agents run only when the user opens the layer that needs them, not all at once.
  5. Capped output lengths, structured outputs, a stable prompt prefix for provider prompt caching, and the smallest adequate model.
  6. Token counts are logged per run, which also feeds the report's Tokenomics section.

- **App name set by Ryan (2026-11-08): "Credit/Financial Analysis Automation".** Applied to the README title, CLI help and SEC User-Agent (`Credit-Financial-Analysis-Automation`, since "/" has a special meaning in User-Agent strings). The code folder stays `credit_app/` because "/" can't appear in folder names.

---

## Session 1 (cont.) — 2026-11-08: AI agents built

**User:** "start the agents." Mid-build, Ryan added a requirement: **the app must flag every uncertainty in its modeling/analysis and must not plug in assumptions that aren't logical. Where something is uncertain, either flag it after the output or ask the user what to do, with options to work around it.**

**Model:** the course Portkey key accepts both `gpt-6-luna` and `gpt-5.6-luna`. The brief allows only `gpt-6-luna`, so that's the default (the graders' `.env` has no `OPENAI_MODEL`).

**Built** (`credit_app/credit_engine/`):
- `filings.py` (no AI) — latest 10-K → keyword passages that state amounts, capped at ~12k characters (Southwest ~1.9k tokens, Frontier ~1.5k vs. ~150k+ for the full 10-K). A prompt-injection screen removes sentences that read like instructions to an AI. Going-concern / material-weakness / restatement flags need specific wording and show their evidence (an earlier loose version produced false positives and was tightened).
- `agents.py` — two agents, both schema-bound with capped output:
  - **Filing Analyst:** off-balance-sheet items and qualitative risks, each with an exact quote.
  - **Credit Writer:** a short memo built from the computed results only.
  
  Code checks both: quotes must appear in the filing (else dropped), amounts must appear in their quote (else cleared), and every number in the memo must exist in the data the writer was given (else flagged). Neither agent calculates or sets a rating.
- `accounting.py` (no AI) — accruals, profit-without-cash, receivables vs. sales, negative equity, plus the 10-K text flags.
- `uncertainty.py` (no AI) — the **Assumptions & Uncertainties register** answering Ryan's requirement. Each item has a severity (info / review / decision), the reason, the rating impact re-scored by code, and options. A choice only becomes a "decision" when an option would change the rating.
  - **Off-balance-sheet items are never added to debt automatically.** Every category is a user decision with its impact shown, because an AI-extracted amount (e.g., a total pension obligation vs. the underfunded amount) shouldn't be assumed.
- `pipeline.py` — runs everything cheapest-first. AI results are cached per filing and input, so a repeat run costs 0 tokens. If AI fails, the deterministic ratings still deliver and the failure is listed.
- `llm.py` — Portkey routing, per-agent caps (requests, total tokens, output tokens), low reasoning effort, and a token log in `data/logs/token_usage.jsonl`.
- **Fixes found live:** `gpt-6-luna` on the course key rejects function tools, so the agents use native JSON-schema output (also fewer tokens). Reasoning tokens count against the output cap, so reasoning is set to low and the caps were raised.
- Tests: **45/45 pass** with a fake model (zero tokens): injection screen, quote/amount checks, the memo number check, caching, injection-can't-change-ratings, and a misbehaving model.

**Live results (LTM Sep-26)**, saved as `docs/runs/LUV_run1.json` and `ULCC_run1.json`:
- **Southwest:** BBB- Reported / BB+ Lease-adjusted. The analyst found $272M of letters of credit, **$4.2B of firm aircraft commitments**, and an $18.5M litigation settlement, all quotes verified. These are presented as decisions; counting the aircraft commitments as debt → **BB-**.
- **Frontier:** CC / B-. Its commitments are stated in aircraft units (dollars sit in a table), so they're flagged "found, no amount stated" rather than guessed.

**Measured tokens (first run):**
- Filing Analyst: 4,732 in (1,990 cached) / 1,601 out for LUV; 3,760 in (1,710 cached) / 757 out for ULCC.
- Writer: ~570–1,900 in / 240–610 out.
- Repeat run: **0** tokens.

**Next optimizations:** the Filing Analyst used 2 requests on both runs (first answer failed validation, so a retry), which roughly doubles its cost. Find and fix the cause. Shorter schema descriptions would also trim input tokens.

**Not done yet:** web UI, venv, git repo, cost pricing for the Tokenomics section.

---

## Session 1 (cont.) — 2026-11-08: Retry fix (token cost cut ~55%)

**Cause:** the schema had hard maximum lengths on text fields (quote ≤ 400/300 characters, etc.). JSON-schema output doesn't enforce those, so the model wrote a slightly longer quote, validation failed, and PydanticAI paid for a full second request.

**Fix:** text and list fields are trimmed after parsing instead of rejected (a trimmed quote is still exact filing text, so quote verification still works). Shorter schema descriptions and a "one-sentence quotes" instruction. `PROMPT_VERSION` → v2 so old cached outputs aren't reused.

**Measured (live, gpt-6-luna)** — same findings, one request per agent:

| Run | Filing Analyst in / out | Writer in / out | Total tokens |
|---|---|---|---|
| Southwest before | 4,732 / 1,601 (2 requests) | 1,883 / 613 (2 requests) | 8,829 |
| Southwest after | 1,976 / 928 (1) | 689 / 351 (1) | **3,944 (−55%)** |
| Frontier before | 3,760 / 757 (2) | 568 / 238 (1) | 5,323 |
| Frontier after | 1,696 / 626 (1) | 589 / 264 (1) | **3,175 (−40%)** |

Good Tokenomics evidence: one cost cut, measured before and after, with no loss in quality (identical items found). Runs saved as `docs/runs/*_run2.json`. 45/45 tests pass.

---

## Session 1 (cont.) — 2026-11-08: Web UI built

**User:** "Yes, start UI."

**Built:** `credit_app/app.py` (Dash, black-and-pink per AGENTS.md, debug off with no reloader) and `assets/style.css`.
- **Inputs:** ticker box (Enter or Analyze), AI on/off, period filter (All / Annual / Quarterly / YTD), and **upload a workbook built on Ryan's template**. This is the private-credit path: same scoring and uncertainty register, no AI because there's no filing (`pipeline.run_workbook`).
- **Top of the page:** Reported, Lease-adjusted and (when chosen) "+ Off-balance-sheet" rating cards, the period, a banner counting decisions and review items, and the AI credit memo.
- **Nine tabs:** Scorecard (both bases side by side with notches and weights) · Periods (score chart + table) · EBITDA build · Debt & leases · Off-balance sheet (verified quotes, filing link) · Accounting flags · **Assumptions & Uncertainties** (options as radio buttons) · Sources (every number's XBRL tag and filing) · **Tokens** (the app shows its own token usage and what the cache saved).
- **Changing an option re-scores with code at zero tokens.** The memo is not re-generated automatically; a "Regenerate memo (~1k tokens)" button appears instead (token-efficiency rule). The open tab persists across re-renders.
- Errors show short messages, never stack traces. Uploads are limited to `.xlsx` and 5 MB.

**Verified in the browser:**
- LUV → BBB- / BB+ with memo and 3 decisions.
- Choosing "Include purchase commitments at 100%" → new **+ Off-balance-sheet BB-** card, regenerate prompt shown, no AI call.
- ULCC → CC / B-; Tokens tab shows 0 tokens (served from cache).
- Phone width: layout stacks with no sideways scroll.

**Fixes found while testing:** checkbox/radio labels were invisible (dark on dark); re-render jumped back to the first tab; the memo mentioned "JSON" (writer prompt tightened, `PROMPT_VERSION` v3).

**Dev setup note:** the preview server runs through a scratchpad launcher that adds the scratch package folder and loads `PORTKEY_API_KEY` from the course `.env` (`.claude/launch.json` → `cfaa-app`). The real `.venv` is still to be created, with OneDrive paused.

**Next:** venv + git repo + fresh-clone dry run (10-minute rule), real-user test for the Impact section, report and slides.

---

## Session 1 (cont.) — 2026-11-08: venv, git, fresh-clone dry run (passed)

**User:** paused OneDrive.

- Created `credit_app/.venv` and installed `requirements.txt` (openpyxl, pydantic-ai-slim[openai] 2.66.0, dash 4.5.0, pytest). 45/45 tests pass in the venv.
- `git init` with everything staged. Checked that `.env`, `.venv`, `data/cache`, `data/results` and `data/logs` are **not** staged, and no API-key patterns appear in tracked files. **Not committed yet** (waiting for Ryan).
- **Dry run following the graders' setup:** copied exactly the git-tracked files into a fresh `submissions/credit_app/`, with a `.env` one folder up holding only `PORTKEY_API_KEY` / `OPENAI_API_KEY`. Followed the README: venv + install + tests in ~4 minutes (inside the 10-minute rule), 45/45 passing. A live run on a new ticker (Delta) worked with just that `.env`, using the defaults (gpt-6-luna, built-in SEC contact): A- / BBB, $15.4B aircraft commitments found, 4 decisions, ~3.3k tokens, 19 s. `python app.py` served the page (HTTP 200) and was then stopped with its whole process tree.
- **Found:** a first attempt in a very deep folder failed to install because of the Windows 260-character path limit (a long PydanticAI file path). README now says to clone into a short path if that happens. Also added Python 3.10+ and the venv steps to the README.
- The dry-run folder, which held a copy of the key, was deleted.

**Next:** commit and push to GitHub (private repo + `zlisto` collaborator, or public), then a real-user test for Impact, then report.html and slides.html.


---

## Session 1 (cont.) — 2026-11-08: Private companies, sector, S&P-style, macro/micro (major build)

**User (after reviewing the app before commit):** asked whether the app supports uploading private-company financials for credit, industry and economic (macro + micro) analysis. It only partly did. Ryan said **"do all the above"** and added:
- Derive the private input template from his two credit spread workbooks, with the values blank (Southwest/Frontier were working examples).
- Add a **sector dropdown** so the AI knows what it's dealing with. Ratios like inventory turnover differ by sector and by health level (normal / advanced / struggling).
- No private financials are available, so run the **logic test on public companies' financials**.
- Rate private companies using **his model's logic plus S&P's approach**. "The finances are the finances": never change them; **red-flag anything unusual** (often unaudited). Key quick check from his private credit career: **Total Assets ≠ Total Liabilities + Shareholders' Equity**.
- Ryan **paused** the commit/push to GitHub to review first. Nothing committed yet.

**Built:**
- **Blank private template** (`data/templates/private_company_template.xlsx`, by `tools/make_blank_template.py`): Ryan's Southwest workbook with every input cleared, formulas and Credit Rating sheet kept, stale commentary removed. Added rows: shareholders' equity (for the balance check), inventory, operating leases, floating-rate %, a **sector dropdown**, an agency rating (for comparison), statement type (Audited / Reviewed / Compiled / Management), and an Instructions sheet. Downloadable from the app.
- **Data-integrity red flags** (`integrity.py`): balance sheet doesn't balance (RED); subtotals exceeding totals; impossible negatives; positive capex; large items below operating income; implied interest rate > 20%; D&A > fixed assets; ±50% swings; quarters not adding to YTD; unaudited statements; and values far outside the sector's range. Repeated findings are merged; numbers are never changed. On Ryan's workbooks it caught Frontier's positive capex in 4 periods.
- **22 sectors with SEC-derived benchmarks** (`config/sectors.json`, `tools/build_benchmarks.py` → `data/benchmarks/sector_benchmarks.json`):
  - Built from SEC XBRL "frames" for **8,925 public filers**, grouped by SEC SIC code (23–478 companies per sector).
  - For 14 ratios (inventory turnover, DSO, DPO, margins, leverage, coverage, …), each sector has its 10th/25th/50th/75th/90th percentiles, plus its median 2020 recession change in revenue and margin.
  - Tiers: Strong = better than the 75th percentile, Normal = the middle half, Struggling = worse than the 25th (direction depends on the ratio).
  - Real sector differences confirmed, e.g. median inventory turnover is 24.8x for restaurants, 5.1x for retail and 3.3x for industrial manufacturing.
  - Public tickers get their sector automatically from SEC's SIC code; private companies pick from the dropdown.
- **S&P-style anchor** (`sp_method.py`), using the structure of S&P's corporate methodology:
  - Financial risk comes from FFO/debt and debt/EBITDA (standard-volatility table, lease-adjusted basis).
  - The anchor comes from the business × financial risk matrix.
  - Business risk is S&P judgment, so the app **suggests** it with a disclosed rule (sector percentiles of scale and margin, capped for cyclical sectors), and the user can override it.
  - Modifiers aren't applied, and that's listed. Shown beside Ryan's template rating.
- **Macro & industry** (`macro.py`): FRED (no key needed) for fed funds, 10-year Treasury, BBB/HY spreads, GDP, CPI and unemployment, plus 2 indicators per sector (e.g., airlines: jet fuel, revenue passenger miles), each verified to exist.
- **Stress tests** (`stress.py`), all re-scored with Ryan's template, no AI:
  - +200 bp on floating debt (shown at 0/50/100% if the share is unknown, with a decision to pick the real share).
  - The **sector's actual 2020 recession**, from SEC data (disclosed as a pandemic shock).
  - Reverse stress: how far EBITDA can fall before the rating reaches B- / CCC+.
- **Micro questionnaire:** customer/supplier concentration, recurring revenue, pricing power, sponsor ownership → flags (no ratio changes).
- **Any-format Excel upload** (`mapper.py`) with a **review screen**:
  - Finds periods (years, dates, Q3 2026, 9M 2026) and matches labels by synonym/fuzzy match in code. An optional AI Mapper handles leftovers and sees labels only, never numbers.
  - The user confirms fields, dates and months before anything is scored.
  - The sign convention is detected for the **whole file**. A per-cell rule misread Southwest's net interest income and was fixed.
  - Sample file: `data/samples/sample_private_company_statements.xlsx`.
- **Economist agent** (on demand, ~1.5k tokens): industry / macro / micro sections from compact computed data, with the number check. The memo now also runs for private uploads.
- **UI:** sector dropdown, template download, review screen, and new tabs (S&P-style, Data integrity, Sector, Macro & stress, Micro). A banner shows red flags. Tabs wrap into rows; the dark dropdown was fixed for Dash 4.

**Logic test (Ryan's request), `docs/logic_test_private.md`: PASS.** Southwest, Frontier and Delta SEC data were written into the blank template as if private, then uploaded:
- **All 21 shared periods got identical ratings** on both bases, and the S&P-style anchor matched.
- **Equity mis-keyed +5% → "Balance sheet doesn't balance" red flag every time** (e.g., Southwest difference −399.1).
- Clean uploads → zero false red flags.
- The company-format sample Excel also reproduces Southwest's public FY2024/FY2025 scores exactly.

**Browser-verified:**
- **Private flow:** upload own-format Excel → review (26 lines, 3 periods, all matched by code) → pick sector → confirm → BB+ (11.82, same as public FY2025), S&P anchor BBB/BBB-, AI memo.
- **LUV:** sector auto-detected; S&P anchor BBB/BBB-; the Economist output was grounded and stated which data was missing.
- **Frontier:** CC / B- / anchor B (Fair × Highly leveraged), Struggling vs. peers.

**Tests: 55/55 pass.**

**Still open:** commit and push to the private GitHub repo (waiting on Ryan's review), real-user test, report.html, slides.html.


---

## Session 1 (cont.) — 2026-11-08: Redesign — upload-first private flow, section navigation, analyst team with a manager

**User direction:**
- No template to fill in Excel. The user uploads private financial statements and the AI sets them up in a clean view that can be **interacted with and modified inside the tool**.
- Add a **public/private toggle** and **sections** to move between: economic analysis, a **Summary tab with SWOT**, and a **Detailed section** drawn from the financials and the 10-K/10-Q (public) or the **notes to reviewed/audited statements** (private).
- **Build the agent team:** a **Manager** overseeing a **Financial/Credit Analyst**, an **Accounting Analyst** (gathers the financials into the model and checks GAAP), a **Macro Economic Analyst**, a **Micro Economic Analyst** (sector, named competitors, performance drivers), and a **Report Writer**.
  - The Manager reviews and applies input without micromanaging.
  - Analysts go to the Manager when stuck.
  - **Cap of 3 tries per situation**, then escalate.
  - No endless loops; keep tokens low.
- "Don't keep running loops on this buildout."

**Built:**
- **Agent team** (`credit_engine/team.py`): Accounting → (Credit ‖ Macro ‖ Micro, in parallel) → Manager (one review) → Writer.
  - Every task gets a compact domain brief and a schema-bound output.
  - Deterministic checks run on each output: quotes must be in the source, and numbers must be in the brief.
  - A failed check sends feedback and retries, up to **3 attempts**. After that the task **escalates to the Manager**, who decides once (use partial / omit / ask the user), with no ping-pong.
  - A **per-run token budget** (40k) applies, with per-task caps and caching by input. **Tokens from failed attempts are counted** (a gap found and fixed during the build).
- **Private ingestion** (`credit_engine/ingest.py`): Excel or **PDF**. It parses statement lines, detects units (thousands → millions) and the **accountant's report type** (Audited / Reviewed / Compiled), and builds a **notes excerpt** (leases, covenants, commitments, contingencies, related parties, going concern, accountant's report) for the Accounting Analyst.
  - The user confirms what was read on a review screen. The Accounting Analyst can map unmatched lines on request (labels only).
- **Editable financial statements in the app:** every standard line, blanks included. Recalculate re-scores with code (no AI). Edits are highlighted, listed under Assumptions, and **Undo** is available. A "Re-run analysts" banner offers to refresh the written analysis instead of re-running it automatically.
- **Named competitors:** the benchmarks now store every SEC filer's ratios by sector. The Sector tab shows a table of the company vs. the sector's 3 largest + 5 closest-in-size peers. Airlines was narrowed to SIC 4512/4522 (FedEx, an air courier, had been included and moved to Transportation).
- **UI sections:** Summary (SWOT + key concerns + outlook) · Credit & financial · Financial statements · Economic (macro) · Sector & competitors · Accounting & GAAP · Detailed findings (writer sections + the exact source passages + per-number sources) · Assumptions · Agents & tokens (flow diagram, per-task status/attempts/tokens, Manager guidance, escalations). The template download was removed from the UI (the template is still used by the logic test).
- **Sample private PDF** (`data/samples/sample_private_reviewed_statements.pdf`, `tools/make_sample_pdf.py`): an illustrative reviewed-statements PDF built from Southwest's public numbers, in thousands, with notes. **FY2024 equity is deliberately mis-keyed** to demonstrate the red flag.

**Found and fixed during live runs:**
1. Over-strict number check → macro/writer escalations. The first symptom was "the 10-year rose 0.67" (changes are now in the brief).
2. The **"19" in "COVID‑19"** (written with a non-breaking hyphen) was treated as a figure. The check now ignores codes (COVID-19, ASC 842, Note 7, Q3, FY2025) and normalizes Unicode dashes. A regression test was added.
3. Writer brief duplicated raw macro/micro data → slimmed down.
4. Failed attempts weren't counted in tokens → now counted and logged as "(escalated)".
5. Shell patches twice turned `\b` regex markers into control characters → fixed and scanned all files.

**Live results (gpt-6-luna):**
- Southwest and Frontier: **all six agents complete with zero escalations**. Frontier's Macro Analyst passed on its 2nd attempt (retry-with-feedback working).
- Earlier runs showed the escalation path working as designed: the Manager ruled "omit" / "ask the user" with reasons.
- The Southwest SWOT cites real figures (debt/EBITDA 1.99x Strong, current ratio 0.47x vs. sector 0.55x).

**Browser-verified:**
- **Public:** toggle; LUV with sector auto-detected; Summary/SWOT renders.
- **Private:** PDF upload → "22 lines, all matched; thousands converted; Reviewed" → confirm → BB+ / S&P-style BBB/BBB- / **red flag: balance sheet doesn't balance**.
- **Editing:** typed the $346M lease cost from the notes into the Financial statements tab → Recalculate → **Lease-adjusted BB appeared**, the cell was highlighted, the edit was tracked, and the re-run banner showed.

**Token log (team calls so far, incl. development runs):** writer and manager re-ran most during the fixes. Per company, a clean first run is roughly 4–6k input / 2–3k output for the analysts plus ~3k for the writer, and repeats are 0. Exact per-run numbers are in `docs/runs/*_team_final.json` and `data/logs/token_usage.jsonl`.

**Tests: 58/58 pass** (fake model, zero tokens), including the 3-attempt cap → escalation → Manager decision, the token budget, the private PDF, user edits, and the injection screen.

**Still open:** commit and push to the private GitHub repo with `zlisto` (Ryan to review first), real-user test, report.html, slides.html.

- **2026-11-09:** Ryan asked to simplify the footer. It now reads: "Implied ratings intended to mirror benchmarks used in S&P's rating and analysis methodology." (`app.py`)
- **2026-11-09:** Ryan clarified the results are not official S&P ratings, though some weighting benchmarks come from how S&P rates. Footer now reads: "Implied ratings, not official S&P ratings. Some of the weighting benchmarks in the analysis are drawn from S&P's rating methodology."


---

## Session 2 — 2026-11-09: Tagline, terminal design, agency ratings, security hardening

**User:**
1. Asked why the tagline said the AI analysts "never do the math themselves." It meant that every figure comes from tested code and the AI only reads and writes, but the wording was awkward.
2. Wants a **Bloomberg-terminal** look.
3. Wants **S&P, Moody's and Fitch ratings pulled** where available.
4. Mid-build: **"make sure this app is well protected so outside bots or attackers can't override it and create an issue."**

**Done:**
- **Tagline:** "An AI analyst team writes the analysis; every figure is calculated by tested code." The footer (set earlier today) reads: "Implied ratings, not official S&P ratings. Some of the weighting benchmarks in the analysis are drawn from S&P's rating methodology."
- **Terminal design** (`assets/style.css` rewritten; pink theme backed up to the scratchpad):
  - Black background, amber monospace text, CFAA top bar, a `>` command-line ticker box with a GO button.
  - Dense bordered KPI tiles, numbered function-key tabs (1 SUMMARY … 9 AGENTS), zebra-striped tables, a green/red/cyan/yellow status palette, and amber/cyan charts.
  - Ryan's request overrides the workspace's pink default.
- **Agency ratings** (`credit_engine/agency.py`). Agency ratings are licensed data, so the app doesn't scrape the agencies. Instead, code (no AI) searches the company's **own latest 10-K and 10-Q** for statements naming S&P, Moody's or Fitch:
  - It extracts the letter grade (each agency's scale), assigns the outlook to the nearest agency named, or records "investment grade" / "below investment grade" when no letter is given. The newer filing wins.
  - The exact sentence is shown as the source. Users can enter current ratings by hand (validated against each agency's scale), which also covers private companies.
  - Shown as a KPI tile and an "Agency ratings vs. implied" panel in 2 CREDIT, and passed to the Credit Analyst and Writer.
  - Live: **Southwest**: investment grade by all three (10-Q Oct 2026). **Delta**: **Moody's Baa2**, quote: "Moody's credit rating agency upgraded its rating for Delta to Baa2". Frontier, United, American: none disclosed.
- **Security hardening** (`credit_engine/security.py`, wired into `app.py` and `ingest.py`):
  - **Uploads:** checked by content, not filename (real PDF/XLSX signatures); PDFs with embedded JavaScript or launch actions refused; macro workbooks refused; **zip-bomb guard** (unzipped size cap); 10 MB and 80-page caps.
  - **Hostile text in uploads:** labels and company names stripped of control characters and screened for AI instructions (same screen as SEC filings).
  - **Forged requests:** every value a browser can send (option choices, sector, statement edits, questionnaire answers, agency ratings) is re-validated against an allow-list on the server. Unknown keys are dropped, and numbers must be finite and within bounds.
  - **Cost abuse:** per-visitor rate limits (12 analyses per 10 min; 6 AI team runs per hour) plus an **app-wide daily token ceiling** (400k). Above it, AI switches off and code-only analysis continues.
  - **HTTP:** `X-Frame-Options: DENY` (anti-clickjacking), `nosniff`, a restrictive CSP (`frame-ancestors 'none'`, `object-src 'none'`), no-referrer, permissions policy, and a 16 MB request cap. An **optional password** (`APP_PASSWORD`, constant-time check) for hosting online. The server still binds to 127.0.0.1 with debug off, and errors stay generic.
  - Already in place: ticker validation, the prompt-injection screen on filing text, quote/number checks on AI output, per-agent token caps, the 3-attempt limit, and secrets kept out of the repo.

**Verified:**
- **Tests: 67/67 pass**, 8 new security tests:
  - an .exe renamed .pdf, a PDF with JavaScript, a macro workbook and a zip bomb are all rejected;
  - injected labels are neutralized;
  - forged choices and edits are dropped or bounded;
  - invalid agency ratings are refused;
  - the rate limit blocks bursts;
  - the daily ceiling holds;
  - headers and password work.
- **In the browser:** headers present, Southwest runs normally, and a fake "statements.pdf" was rejected with "That file is not a real PDF."

---

## Session 2 (cont.) — 2026-11-09: 3 FINANCIALS redesign

**User:** The financials section needs a better layout: a P&L titled P&L, a Balance Sheet with a thorough breakdown, reported Cash Flows, and both a summarized and a detailed Financials tab.

**Built** (`views.py`; recalculate now reads all three statement tables in `app.py`):
- **3 FINANCIALS → SUMMARY:** key figures across all periods: revenue, EBITDA and margin, net income, CFO, free cash flow, cash, total debt, net debt, equity, debt/EBITDA (12-month periods), current ratio. Plus a revenue/EBITDA bar chart by fiscal year.
- **3 FINANCIALS → DETAILED**, three titled, editable statements:
  - **P&L:** revenue, COGS, gross profit and margin, SG&A, D&A, other operating expense, EBIT, EBITDA and margin, interest, pre-tax, tax, other non-operating, net income and margin; memo lease cost and EBITDAR.
  - **Balance Sheet:** Assets (cash, AR, inventory, other current, total current, PP&E, goodwill, intangibles, other long-term, total) / Liabilities (AP, short-term debt, other current, total current, long-term debt, operating leases, deferred tax, other long-term, total) / Equity, total liabilities & equity, and a **balance check row** (red when non-zero). Memo: total debt, net debt, lease-adjusted debt.
  - **Cash Flows:** operating (net income, D&A, deferred taxes, working capital & other, CFO), investing (capex, free cash flow), financing (distributions, discretionary cash flow).
  - Reported lines are white and editable; calculated lines are grey italic; section headers are amber; edited cells are highlighted.
- **Checked:** Southwest FY2025 ties (balance check 0; lease-adjusted debt 5,981 = Ryan's workbook). In the browser, editing equity +100 in the Balance Sheet → Recalculate → check row −100.0 in red plus the "Balance sheet doesn't balance" flag; Undo cleared it. 67/67 tests pass.

- **2026-11-09 (cont.): financing and investing lines added** (Ryan: "fix those variables to be included").
  - **New fields:** debt issued, debt repaid (incl. finance-lease principal), share buybacks, net cash from investing, net cash from financing. Mapped from multiple SEC tags each, plus synonyms for private-statement uploads (outflows stored negative).
  - **Cash Flows now shows:**
    - Investing: capex, other investing, net cash from investing.
    - Financing: debt issued, debt repaid, net borrowing, buybacks, dividends, other financing, net cash from financing.
    - Summary: net change in cash, FCF, discretionary cash flow.
  - **P&L:** gained "Total operating expenses (revenue − EBIT)". Gross profit stays blank when no COGS is reported (airlines), with a note, rather than being estimated.
  - **Delta FY2025:** debt issued 2,215; repaid −4,941; net borrowing −2,726; other financing 90; net cash from financing −3,076.
  - **Southwest** files its 2025 debt repayments under a company-specific XBRL tag that SEC's standardized data doesn't include, so they sit in "Other financing (incl. company-specific items)" and still reconcile to the reported total. This is disclosed on screen.
  - Offline sample data refreshed with the new tags. 67/67 tests pass.

- **2026-11-09 (cont.): investing detail + SWOT tab.**
  - **Ryan:** break investing cash flows into more detail; add a thorough SWOT tab.
  - **Investing:** new fields for purchases of PP&E (gross), proceeds from asset sales, acquisitions, divestitures, purchases of investments, sales/maturities of investments, plus net investment activity and other investing, reconciling to net cash from investing. Mapped from several SEC tags each and private-statement synonyms. For uploads that give only gross PP&E purchases, net capex is derived and disclosed. Southwest FY2025: PP&E −2,673; investments bought −470 / sold +1,693 (net +1,223); other 21; net investing −1,429 (ties).
  - **SWOT tab** (now **2 SWOT**; tabs renumbered 1–10): four quadrants with item counts. Every item is tagged with its source: Ratings, Agency rating, Sector data, Scorecard, Stress test, Data checks, Accounting Analyst, 10-K/notes, Questionnaire, Macro data, Credit/Macro/Micro Analyst, Report Writer. It is assembled from work already computed and checked, so **no extra AI calls** (covered by a test). Southwest: 15 strengths / 9 weaknesses / 5 opportunities / 16 threats.
  - 68/68 tests pass; verified in the browser.

---

## Session 2 (cont.) — 2026-11-09: Credit score, information coverage, public-company completeness

**Ryan:**
- "Ryan template" should not be referenced in the app.
- A credit score should come from the Reported field, with a note when only a limited % of information is available.
- Public companies should have enough information for a thorough rating.

**Done:**
- **No "Ryan template" anywhere user-facing:** it's labeled the *credit scorecard* in the UI, the Assumptions text and the AI briefs (`TEAM_VERSION` t2 so analysts re-write with neutral wording).
- **Credit score:** 0–100 from the Reported weighted score (AAA = 100, C = 0), shown as the first KPI tile with the rating, the % of the scorecard used, and a coverage label: **Full opinion** (≥90%), **Substantial information** (67–90%), **Limited information (provisional)** (<67%).
  - The old rule (no rating below 2/3 coverage) was replaced: an opinion is always given from what's available and clearly labeled.
  - The credit score and coverage are also passed to the analysts.
- **Public-company coverage audit** of 12 companies; before → after:
  - **52/53-week calendars** (Coca-Cola, Home Depot): dates in a month's first week now count as the prior month-end, so LTM, opening balances and FCF work. Both went from 91% to 100%.
  - **No operating-income line** (Pfizer): EBIT = pre-tax income + net interest, disclosed. 53% → 100%.
  - **Interest only in company-specific tags** (Caterpillar): cash interest paid is used as a labeled proxy. **The headline period is now the most recent period with complete data** (Caterpillar, Duke, Ford use FY2025), with a note naming what the newer period lacks. Caterpillar 10% → 100%; Duke 62% → 100%.
  - **Sector ratios:** added receivables/payables fallback tags (DSO for Delta and Walmart), plus revenue growth from the latest YTD vs. the prior-year YTD for LTM/YTD periods.
  - **ExxonMobil:** XOM now maps to a newly registered "ExxonMobil Holdings Corp" with no full fiscal year; a clear message replaces the error.
  - **Accuracy catch — Ford:** Ford tags none of its debt in SEC standard data. The app had treated $0.9B of finance leases as total debt, giving a false **A+**. Now leases alone never count as total debt; debt shows "Data is Missing" with guidance to enter it from the 10-K. A new red flag, **"Debt looks incomplete"**, compares gross interest with reported debt. Ford now shows **41/100, B+, 36% of scorecard, Limited information (provisional)** instead of a wrong A+.
  - **Result:** all 11 public companies with a full year of data reach **100% scorecard coverage** except Ford (debt not tagged; flagged with instructions). No false "debt incomplete" flags on the others.
- **Tests:** 69/69 pass (new: limited-information labeling, credit-score scale).

---

## Session 2 (cont.) — 2026-11-09: Closer to S&P's method + Debt Structure tab

**Ryan:**
1. Improve the credit analysis to be more in line with how S&P rates.
2. Add an in-depth Debt-Structure tab (debt maturities are in the 10-K detail).

**S&P method upgrades** (`credit_engine/sp_method.py`, `credit_engine/debt.py`, `pipeline._sp_anchor`):
- **S&P-adjusted debt:** lease-adjusted debt + after-tax (21%) pension deficit (funded-status tag) − surplus cash. Cash netting defaults to **off**; S&P nets only surplus cash, which can't be measured reliably from filings.
- **Volatility tables:** standard / medial / low core-ratio thresholds, assigned by sector (utilities → low; food & beverage, consumer products, telecom, healthcare services → medial). For low-volatility issuers FFO/debt is primary. Changeable under Assumptions.
- **Supplementary ratios:** CFO/debt, FOCF/debt, DCF/debt, (FFO + cash interest)/cash interest, EBITDA/interest, each with its category.
- **Modifiers:**
  - Financial-sponsor ownership (questionnaire) → highly leveraged.
  - **Liquidity** sources/uses over 12 months: cash + revolver availability + FFO vs. debt maturities, finance-lease payments, capex, dividends. Exceptional ≥2.0x, Strong ≥1.5x, Adequate ≥1.2x, Less than adequate ≥1.0x (caps at BB+), Weak <1.0x (caps at B-). If revolver availability isn't disclosed, liquidity is "Undetermined" and no cap applies (the first version wrongly capped Duke at B- for that reason; fixed).
- **Result** is an **indicative S&P-style rating** (anchor → modifiers), shown as the KPI tile and as a step-by-step table on 3 CREDIT.
- **Calibration check vs. ratings disclosed in the companies' own filings:**
  - Coca-Cola: app **A+ / A** vs. disclosed **S&P A+, Moody's A1**.
  - Delta: **BBB / BBB-** vs. Moody's **Baa2**.
  - Southwest: **BBB / BBB-** vs. investment grade at all three.
  - Microsoft AAA; Duke A- / BBB+.
  - Known gaps, disclosed in-app: Pfizer comes out low (S&P normalizes one-off charges such as impairments) and Caterpillar somewhat low (S&P deconsolidates the captive finance arm).

**Debt Structure tab (4 DEBT STRUCTURE; tabs renumbered 1–11):**
- Tiles: reported, lease-adjusted and S&P-adjusted debt; revolver available/capacity; weighted-average rate; fair value.
- **Maturity ladder** chart and table (next 12 months, years 2–5, thereafter) for debt principal, finance leases and operating leases, from the 10-K's standardized maturity tables. "Thereafter" is derived and labeled when not tagged.
- **Refinancing risk:** % due within 2 years; coverage of the 12-month maturities by cash (+ revolver); fair value vs. book.
- **Liquidity sources/uses table.**
- **Debt instruments** read by the Accounting Analyst from the 10-K debt note, each quote-verified. Southwest: $1.5B revolver (Aug 2028); $750M 4.375% notes 2028; $750M 5.25% notes 2035 (swapped to floating).
- **Covenants:** from GAAP findings and note passages.

**Also fixed:** an offline-test leak. The model-name lookup loaded `.env`, so "offline" tests began fetching live SEC data. The fixture now blocks it. The offline sample now includes maturity-table tags. **Tests: 71/71 pass.**

## 2026-11-09 (evening): Competitor comparison

**Request:** add a competitor comparison (e.g., Southwest vs Frontier). The public view gets a Single ticker / Compare companies toggle. Compare mode starts with two ticker fields and an "+ Add company" button, and shows a thorough write-up comparing the companies financially, by SWOT and economically. A toggle opens any one company in depth across all tabs. Private companies are compared with named public competitors (aggregated).

**Built:**
- `credit_engine/compare.py`: runs each ticker through the normal pipeline with code-only maths and *cached* AI work only (no new analyst calls). It then makes one AI call (the "comparison" writer, 3-try cap, number check) for the write-up and ranking. Without AI, it falls back to a comparison written by code. The soft cap is 10 companies per comparison, to limit SEC pulls and cost.
- Side-by-side table (credit score, ratings, agency ratings, business/financial risk, liquidity, margins, leverage, coverage, adjusted FFO/debt, debt due within 2 years, reverse stress, sector position, red flags), with the best value in each row highlighted. Also a credit-score chart, ranking, financial/SWOT/economic write-ups, a per-company SWOT matrix, and an economic table.
- Company toggle (COMPARISON | LUV | ULCC | ...): opens the full 11-tab analysis for that company. A "Run AI analyst team" button appears there because comparisons skip per-company analyst calls to save tokens.
- Peer aggregate (public and private): the Sector/Comps tab now opens with "<Company> vs publicly traded competitors". It names the peers, shows the peer median, the difference, and better/weaker per metric. Revenue growth is now included.

**Live test:** LUV vs ULCC vs DAL. The comparison write-up cost 2,471 tokens. Delta ranked #1 (score 68, A-), Southwest #2 (56, BBB-), Frontier #3 (7, CC). Fix after the test: brief numbers are now rounded and formatted, because the model had quoted raw floats such as -0.5145.

**Tests:** 73 passing (new: comparison makes exactly one AI call and reuses the cache; code fallback; private peer aggregate).

## 2026-11-10: Analyst add-ons and chat

**Positioning (user):** an add-on to existing tools (Bloomberg, CapIQ, the rating agencies), not a replacement. It gives a thorough company and industry analysis from public and private data.

**Request:** build the four add-ons (Excel export, credit memo in Word/PDF, watchlist with new-filing check, analyst adjusted case) plus an AI chat for analysts reviewing the output.

**Built:**
- `credit_engine/export.py`:
  - Excel workbook for a company (Summary, Scorecard, Statements, Periods, Peers, Vs peer median, Debt structure, Stress, Red flags, Assumptions, Analyst case) and for a comparison.
  - Credit memo with nine sections (ratings, summary, scorecard, SWOT, debt and liquidity, sector and peers, economic and stress, data checks and accounting, assumptions).
  - The Word file is written directly, with no new package; the PDF uses fpdf2. No tokens.
- `credit_engine/watch.py`: the watchlist is stored in the browser. "Check for new filings" reads SEC's filing list (cached at most 1 hour) and re-scores only companies with a new 10-K or 10-Q. It reports rating moves, e.g. "reported BBB- → BB+".
- `stress.analyst_case`: EBITDA add-back, debt adjustment, revenue growth and EBITDA margin projection. It is re-scored on the same scorecard and shown beside Reported, which is unchanged. Inputs are checked on the server against allowed ranges.
- `credit_engine/chat.py` plus the "chat" task: answers come only from a compact context (about 1.5k tokens) of the computed data and the analysts' verified text.
  - Numbers in answers are checked against the data, with the 3-try cap.
  - Each answer points to the tab where the figure appears.
  - The conversation resets when the company changes.
  - Limits: 30 questions per hour per browser, and the daily token ceiling still applies.

**Live check:**
- LUV with a +500m EBITDA add-back: Reported BBB- (score 56), Analyst case BBB+ (score 64).
- The watchlist added LUV and its check found no new filing.
- The Word export downloaded without errors.
- Chat answered "Why did it get this rating?" correctly from the scorecard, using 2,246 tokens.

**Tests:** 78 passing. New: analyst case, input checks, valid xlsx/docx/pdf, watchlist re-scores only on a new filing, chat rejects an invented number then answers and caches.

## 2026-11-10: Cheaper analyst chat

**Finding:** chat questions cost about 2,100–2,700 tokens, over 90% of it input. Every question was sent the full company context.

**Changes:**
1. **Topic routing.** Every question gets a core (ratings and scorecard). Other sections (statements, debt and liquidity, peers, sector, stress, macro, flags, analyst text, analyst case) are added only when the question mentions them. A question that matches no topic gets the full context, so quality is protected.
2. **Trimmed context.** Statements now cover the headline period plus the latest fiscal year only. Only the previous question and answer are sent with a follow-up.
3. **Code answers for three starter questions, at 0 tokens:**
   - *Why did it get this rating?* Strongest and weakest scorecard ratios, lease-adjusted and S&P-style explanation.
   - *What would move the rating up or down?* New `stress.notch_moves`: the EBITDA change for one notch up or down, plus reverse stress.
   - *How does it compare with its peers?* Better/weaker against the named peer median.
4. **Liquidity sources and uses** added to the debt section. The live test showed the chat couldn't confirm coverage without them. An undisclosed revolver is now noted rather than shown as 0.
5. **Retry reasons** are now written to the token log, to tune the checks.

**Live result (LUV):**
- Starter question: 0 tokens.
- "How much debt matures in two years, and can liquidity cover it?": 874 tokens, one attempt (was about 2,200).
- "Biggest credit risks?": two attempts (the first failed the number check), 2,376 tokens in all, about 1,000 input per attempt.

**Tests:** 79 passing.

## 2026-11-10: First-time user experience, documents, staff dry run

**Request:** make the product clear to a first-time user (in the app and in a guide), pass "Staff can run it", improve the look and feel, and write a separate agent-design document. **The user is a real user:** they have used the app for economic and individual company analysis (e.g., the NVDA run on 2026-11-10 in the token log). This is Impact evidence for the report; still to capture: a before/after time and a quote.

**In the app:**
- A headline at the top saying what the product does.
- A "? HOW TO USE THIS APP" panel with 7 steps.
- A start page with four "Start here" cards (public, compare, private, review/ask/export), a "What you get (11 tabs)" list and "Good to know" notes.
- A one-line description at the top of every tab.
- The AI checkbox now says it uses tokens.
- The watchlist moved below the results.
- Fixed mobile layout: viewport meta tag, controls stack on phones, no horizontal scroll.

**Documents:**
- `credit_app/docs/user_guide.html`: 12 sections, every button name checked against the app.
- `credit_app/docs/agent_design.html`: SVG diagram of the agents and handoffs, a table of agents (reads, schema, check, caps), the model and why, guardrails, a traced LUV run (13,015 tokens, six agents, every check passed first time), ULCC escalations, and on-demand agent costs.

**Staff dry run:** copied the 70 files git would publish (secret scan clean) to `C:\cfaa_dry`, with `.env` one folder up holding only `PORTKEY_API_KEY`.
- Fresh venv plus install: 4 min 41 s. 79/79 tests passed.
- `python app.py` served the page. DAL analyzed live in 6 s.
- The chat answered on `gpt-6-luna` in 789 tokens.

**Found:** the course-folder `.env` sets `OPENAI_MODEL=gpt-5.6-luna`, which overrides the app default. Staff's `.env` doesn't, so staff get `gpt-6-luna`. Noted in the README; the user's `.env` was not changed.

## 2026-11-10 (night): GitHub, impact evidence, screenshots, tokenomics

- **GitHub:** committed 70 files (secret scan clean, no `.env`, caches or logs) on branch `main`. Created the **private** repo `rscrivano/credit-financial-analysis-automation` and invited `zlisto` as a collaborator. GitHub gives personal-repo collaborators write access; read-only isn't offered. The invite is pending until zlisto accepts.
- **Impact:** the user's quote and usage are recorded in `docs/evidence/impact.md` and `usage.md`. A before/after time is still optional to add.
- **Screenshots, 0 AI tokens:** `tools/screenshots.py` drives headless Edge through the DevTools protocol.
  - The new `CFAA_CACHE_ONLY=1` switch guarantees no new AI calls.
  - Every wait has a timeout and each step runs once, so nothing can loop.
  - 14 PNGs in `docs/evidence/screenshots/`: start page, NVDA summary/SWOT/credit/debt/sector/agents, chat, export bar, LUV-ULCC-DAL comparison, private upload review and red flags, agent diagram, user guide.
  - The token log didn't change during the run.
- **Tokenomics and safety:** `tools/evidence.py` builds `tokenomics.md` from the log and `safety_tests.txt` (17 tests passing).
  - Measured: 12 full runs, median 11,479 tokens. Comparisons about 1,900–2,500. Chat 789–874 after routing; starter questions 0.
  - Costs use **placeholder prices** until the course key's real `gpt-6-luna` prices are given. Re-run: `python tools/evidence.py --price-in X --price-cached Y --price-out Z`.

- **Impact, before/after (user, 2026-11-10):** a thorough manual review and credit spread takes up to 3 hours; with the app, seconds to a few minutes, and the user's time goes to reviewing and understanding the company and the economics. Added to `docs/evidence/impact.md`. The gpt-6-luna price is still unknown.
- **Tokenomics:** costs are now based on the measured, optimized token counts. Price = labeled reference (OpenAI GPT-5 list price, $1.25 / $0.125 cached / $10 per 1M) because the gpt-6-luna course price isn't published. 287k tokens per analyst-month ≈ $1.21; 100 users ≈ $121/mo; 10,000 users ≈ $12.1k/mo.

## 2026-11-10 (late): report.html and slides.html drafted
- **report.html:** 8 required sections, 14 printed pages, 8 embedded screenshots, and the agent diagram. Built from `docs/src/report_src.html` by `tools/build_docs.py`, with no AI.
- **slides.html:** reveal.js from a CDN, 10 slides, same style.
- Screenshots were re-captured, cropped to the results area, with 0 AI tokens. Stale headless Edge processes caused one failed run; the script now cleans up the whole browser tree.
- Both files are pushed to GitHub and are waiting for the user's review.

## 2026-11-11: Report readability
- The user found the report images too small. Screenshots were re-captured at 1000 px wide (`docs/evidence/screenshots_report/`, 0 AI tokens).
- Every image is now full width and cropped to its key section (e.g., the SWOT quadrants without the repeated ratings header).
- The report prints to **15 pages**, within the brief's 10–15, so the user's 17-page allowance wasn't needed. Pushed to GitHub.

- **Report (2026-11-11):** a plain-language value statement now opens the report (in-depth company understanding in minutes; financial position, credit risk, debt structure, macro/micro; informed decisions incl. unrated private companies). Section 8 (Limits and next steps) removed at the user's request. Note: the brief lists it as a required section.
- **Report:** a short section 8 was restored (credit quality, not pricing; indicative ratings; then a roadmap) so all 8 required sections are present. Pushed.

## 2026-11-11: Final touches
- The user approved the report and decided against a video.
- Removed `OPENAI_MODEL=gpt-5.6-luna` from the course `.env`, which now holds only `PORTKEY_API_KEY`. The app now uses `gpt-6-luna`, the same as staff.
- zlisto's invite (sent 2026-11-11) is still pending; GitHub invites expire after 7 days, so re-send it if it isn't accepted by 2026-11-18.
- App: a 'TO START' strip (1 type the ticker, 2 press GO, 3 check the detected industry sector and change it if wrong). The fields are labeled Step 1 and Step 3, and the start-page card matches. 79 tests pass. Pushed.
- **Report:** screenshots refreshed to show the TO START instruction (0 AI tokens). Still 14 pages. Pushed.

## 2026-11-11: Public repo, second user
- The repo was made **public** at the user's request (secret scan clean first).
- **Second user:** the user's wife (finance/investment background; not named in the report) tested the app and found it highly effective and useful for time efficiency and information quality. Added to `impact.md`, the report's Impact section, and the impact slide.
- The report prints to 15 pages. Pushed.

- **What's new (2026-11-11):** rewritten in the report (section 3) and on slide 3 around CFAA's own enhancements and the time saved. Competitors are now a short closing note, kept because the rubric asks for named competitors. The chat screenshot was dropped to stay at 15 pages. Pushed.

## 2026-11-11: Final push and conversation record
- Verified GitHub is in sync (local = origin/main, nothing uncommitted).
- Exported the full development conversation (every user message and assistant reply, in order; tool calls omitted) to `docs/full_conversation.md` with `tools/export_conversation.py`: 122 messages from 2026-11-08 onward, secret check clean.
- Copied both records (this log and the full conversation) into the repo under `docs/development/` so the development build-out is submitted with the code.
- Remaining: final fresh-clone check (around Nov 21–22) and submission by Nov 23, 11:59 PM.
- Added the earlier conversation PDF (other Claude account, 5 pages, secret scan clean) to `docs/development/` at the user's request. Pushed.
- **Comparison restored (2026-11-11):** the user wants a clear comparison with market products (it's in the instructions). Report section 3 now has the enhancements table plus a capability matrix comparing Bloomberg, S&P Capital IQ, bank spreading tools, general AI and CFAA (11 capabilities, plus time and cost). Slide 3 is the matrix. Report 15 pages, 10 slides.

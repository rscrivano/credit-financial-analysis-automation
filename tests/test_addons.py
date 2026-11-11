"""Exports, analyst case, watchlist and analyst chat (offline, fake model, zero tokens)."""
import io
import json
import zipfile
from xml.dom import minidom

import openpyxl
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from credit_engine import chat, export, pipeline, watch
from credit_engine.security import sanitize_choices
from tests.test_agents_pipeline import offline  # noqa: F401  (fixture)


def test_analyst_case_beside_reported(offline):  # noqa: F811
    base = pipeline.run("LUV", use_ai=False)
    r = pipeline.run("LUV", use_ai=False, choices={"analyst_case": {"ebitda_adj": 500, "rev_growth": 5}})
    ac = r["analyst_case"]
    assert r["primary"]["reported"]["rating"] == base["primary"]["reported"]["rating"]  # Reported never changes
    assert ac["reported"]["rating"] == base["primary"]["reported"]["rating"]
    assert ac["case"]["credit_score"] > ac["reported"]["credit_score"]  # add-backs + growth strengthen the case
    assert any("+500m" in n for n in ac["notes"])


def test_case_inputs_are_sanitized():
    ch = sanitize_choices({"analyst_case": {"ebitda_adj": "250", "rev_growth": 9999, "evil": 1, "debt_adj": "x"}}, set())
    assert ch == {"analyst_case": {"ebitda_adj": 250.0}}


def test_exports_are_valid_files(offline):  # noqa: F811
    r = pipeline.run("LUV", use_ai=False, choices={"analyst_case": {"ebitda_adj": 100}})
    wb = openpyxl.load_workbook(io.BytesIO(export.report_xlsx(r)))
    assert {"Summary", "Scorecard", "Statements (US$ m)", "Analyst case"} <= set(wb.sheetnames)
    blocks = export.memo_blocks(r)
    with zipfile.ZipFile(io.BytesIO(export.to_docx(blocks))) as z:
        doc = z.read("word/document.xml").decode()
    minidom.parseString(doc)  # well-formed XML
    assert "Credit memo" in doc and "Analyst case" in doc
    assert export.to_pdf(blocks).startswith(b"%PDF")


def test_watchlist_rescore_only_on_new_filing(offline, monkeypatch):  # noqa: F811
    r = pipeline.run("LUV", use_ai=False)
    filing = {"form": "10-Q", "accession": "A1", "filed": "2026-10-22"}
    monkeypatch.setattr(watch, "latest", lambda cik, h=1: filing)
    monkeypatch.setattr(watch, "company_facts", lambda cik, max_age_hours=24: ({}, "cache"))
    e = watch.entry(r)
    assert e["accession"] == "A1" and e["rating"] == r["primary"]["reported"]["rating"]
    assert watch.check([e])[0]["status"] == "No new filing"
    filing = {"form": "10-K", "accession": "A2", "filed": "2027-02-05"}
    monkeypatch.setattr(watch, "latest", lambda cik, h=1: filing)
    out = watch.check([{**e, "rating": "B"}])[0]
    assert out["status"].startswith("New 10-K filed 2027-02-05") and out["changed"] and out["accession"] == "A2"


def test_chat_answers_from_context_and_checks_numbers(offline):  # noqa: F811
    r = pipeline.run("LUV", use_ai=False)
    ctx = chat.report_context(r)
    rating = ctx["ratings"]["reported"]
    replies = iter([{"answer": "Leverage is 987.65x.", "where_to_look": "3 CREDIT"},  # invented number -> retried
                    {"answer": f"The reported rating is {rating}.", "where_to_look": "3 CREDIT"}])

    def respond(messages, info: AgentInfo):
        return ModelResponse(parts=[TextPart(json.dumps(next(replies)))])
    ai = {"usage": [], "tasks": []}
    out, esc = chat.ask(FunctionModel(respond), ai, ctx, [], "Why this rating?")
    assert out.answer.endswith(f"{rating}.") and not esc and ai["tasks"][0]["attempts"] == 2
    out2, _ = chat.ask(FunctionModel(respond), ai, ctx, [], "Why this rating?")  # same question: served from cache
    assert out2.answer == out.answer and ai["tasks"][-1]["status"] == "cached"


def test_chat_sends_only_relevant_sections_and_answers_starters_free(offline):  # noqa: F811
    r = pipeline.run("LUV", use_ai=False)
    ctx = chat.report_context(r)
    small = chat.select(ctx, "How much debt matures soon?")
    assert "debt_maturities" in small and "macro" not in small and "ratings" in small  # core always kept
    assert chat.select(ctx, "Tell me something") == ctx  # no topic recognized: full context
    assert chat.context_size(small) < chat.context_size(ctx) / 2
    why = chat.instant_answer(r, "Why did it get this rating?")
    assert r["primary"]["reported"]["rating"] in why["answer"] and "Weakest" in why["answer"]
    move = chat.instant_answer(r, "What would move the rating up or down?")["answer"]
    assert "one notch" in move
    assert chat.instant_answer(r, "What is capex?") is None  # free-form questions still go to the AI

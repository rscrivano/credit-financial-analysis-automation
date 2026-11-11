"""The Python port must reproduce Ryan's Excel workbooks exactly in template mode.

Checks every scored ratio, notch, total score and final rating for every
populated period in both workbooks against the values Excel saved.
"""
from pathlib import Path

import pytest

from credit_engine.scorecard import Scorecard
from credit_engine.template_mode import template_rating
from credit_engine.workbook_import import load_template_workbook, read_template_outputs

FIXTURES = Path(__file__).parent / "fixtures"
WORKBOOKS = ["southwest_template.xlsx", "frontier_template.xlsx"]
SC = Scorecard.load()


def _cases():
    for wb in WORKBOOKS:
        path = str(FIXTURES / wb)
        _, periods = load_template_workbook(path)
        expected = read_template_outputs(path)
        for i, p in enumerate(periods):
            col = p.sources["_column"]
            if col not in expected:
                continue
            adjacent = periods[i + 1] if i + 1 < len(periods) else None
            yield pytest.param(p, adjacent, expected[col], id=f"{wb.split('_')[0]}-{p.label}")


@pytest.mark.parametrize("period,adjacent,expected", list(_cases()))
def test_matches_workbook(period, adjacent, expected):
    got = template_rating(period, adjacent, SC)
    for key, exp in expected["ratios"].items():
        val = got["ratios"][key]
        if exp == "N/A":
            assert val is None, f"{key}: expected N/A, got {val}"
        else:
            assert val == pytest.approx(exp, rel=1e-9, abs=1e-12), key
        exp_notch = expected["notches"][key]
        assert (got["notches"][key] or "N/A") == exp_notch, key
    assert got["score"] == pytest.approx(expected["score"], abs=1e-9)
    assert got["rating"] == expected["rating"]

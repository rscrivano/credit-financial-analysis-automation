"""Ratio -> notch mapping and score -> rating lookup, driven by the JSON scorecard."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

DEFAULT_SCORECARD = Path(__file__).parent / "config" / "ryan_template_scorecard.json"


class Scorecard:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.name = cfg["name"]
        self.notch_scale: dict[str, float] = cfg["notch_scale"]
        self.label_order: list[str] = cfg["ratio_label_order"]
        self.ratios: dict[str, dict] = cfg["ratios"]
        self.top_notch = min(self.notch_scale, key=self.notch_scale.get)
        self.bottom_notch = max(self.notch_scale, key=self.notch_scale.get)

    @classmethod
    def load(cls, path: Path | str = DEFAULT_SCORECARD) -> "Scorecard":
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))

    def notch_for(self, key: str, value: float) -> str:
        """Map a ratio value to a rating notch, mirroring the template's nested IFs.

        Percent ratios are compared on a x100 scale, as in the workbook.
        """
        r = self.ratios[key]
        x = value * 100 if r["percent"] else value
        th = r["thresholds"]
        if r["direction"] == "higher":
            if x < r["c_cutoff"]:
                return "C"
            if x < r["cc_cutoff"]:
                return "CC"
            for label in self.label_order:
                if x > th[label]:
                    return label
            return "CCC-"
        # lower is better (leverage)
        if "negative_floor" in r and x < r["negative_floor"]:
            return "C"
        if x > r["c_cutoff"]:
            return "C"
        if x > r["cc_cutoff"]:
            return "CC"
        for label in self.label_order:
            if x < th[label]:
                return label
        return "CCC-"

    def rating_for_score(self, score: float) -> str:
        """Correct lookup: the notch whose number is nearest the score (ties go to the worse notch)."""
        ordered = sorted(self.notch_scale.items(), key=lambda kv: kv[1])
        for label, num in ordered:
            if score < num + 0.5:
                return label
        return ordered[-1][0]

    def rating_for_score_template(self, score: float) -> Optional[str]:
        """The workbook's lookup (D21), reproduced exactly, including its row order.

        Cutoffs are midpoints between consecutive rows of the notch table as the
        rows appear in the sheet (BB+ is listed before BBB-), so BB+ is unreachable.
        """
        sheet_rows = ["AAA", "AAA-", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB",
                      "BB+", "BBB-", "BB", "BB-", "B+", "B", "B-", "CCC+", "CCC", "CCC-",
                      "CC+", "CC", "CC-", "C"]
        n = [self.notch_scale[l] for l in sheet_rows]
        # AM column: AM(i) = average of AL(i-1), AL(i), except the template's AM19/AM20/AM21.
        am = {i: (n[i - 1] + n[i]) / 2 for i in range(1, len(n))}
        am[10] = n[10]                       # AM19 = AVERAGE(AL19:AL19)
        am[11] = (n[9] + n[10] + n[11]) / 3  # AM20 = AVERAGE(AL18:AL20)
        am[12] = (n[10] + n[11] + n[12]) / 3  # AM21 = AVERAGE(AL19:AL21)
        am[len(n)] = n[-1] + 0.5             # AM33 = 24.5
        # D21 test order: rows 10..18, then 20, 19, 21.. (sheet order quirk)
        sequence = [(am[i], sheet_rows[i - 1]) for i in range(1, 10)]
        sequence += [(am[11], "BBB"), (am[10], "BBB-"), (am[12], "BB+")]
        sequence += [(am[i], sheet_rows[i - 1]) for i in range(13, len(n) + 1)]
        for cutoff, label in sequence:
            if score < cutoff:
                return label
        return None  # "error" in the workbook

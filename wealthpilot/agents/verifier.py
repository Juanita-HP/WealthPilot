"""Verifier: deterministic checks on an agent's answer before the user sees it.

1. Evidence: every number in the answer must sit in a sentence that cites a
   receipt ([R3]), and the number must appear in that receipt's output or
   inputs (allowing for the rounding shown). Handles English and French number
   formats (28.9% / 28,9 %, 75,294 / 75 294).
2. Governance: no instruction to buy or sell, no guaranteed returns, no
   certain predictions. Simulation-only boundary of the brief.

The checks are code, not a language model, so they cannot be talked out of a
failure.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from .ledger import Ledger, numbers_in

RECEIPT = re.compile(r"\[(R\d+)(?:\s*,\s*(R\d+))*\]")
RECEIPT_IDS = re.compile(r"R\d+")
SPACES = "    "
NUMBER = re.compile(
    r"(?<![\w.])(?P<sign>[-−–]?)(?P<num>\d{1,3}(?:[" + SPACES + r",]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
    r"(?P<unit>\s?%|\s?\$|\s?k\$|\s?M\$)?"
)


@dataclass
class Claim:
    sentence: str
    text: str
    value: float
    is_percent: bool
    receipts: list[str]
    status: str  # verified | no_citation | not_found

    def to_dict(self):
        return asdict(self)


@dataclass
class Report:
    claims: list[Claim] = field(default_factory=list)
    governance: list[dict] = field(default_factory=list)

    @property
    def unverified(self) -> list[Claim]:
        return [c for c in self.claims if c.status != "verified"]

    @property
    def coverage(self) -> float:
        return 1.0 if not self.claims else 1 - len(self.unverified) / len(self.claims)

    @property
    def passed(self) -> bool:
        return not self.unverified and not self.governance

    def to_dict(self):
        return {"coverage": self.coverage, "passed": self.passed, "n_claims": len(self.claims),
                "unverified": [c.to_dict() for c in self.unverified], "governance": self.governance}


def _parse(num: str) -> tuple[float, int]:
    """Value and number of decimals shown, for '75,294' '75 294' '28,9' '28.9' '1,234.5'."""
    s = num
    for sp in SPACES:
        s = s.replace(sp, "")
    if "," in s and "." in s:
        s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = s.replace(",", "") if len(tail) == 3 and re.fullmatch(r"\d{1,3}(,\d{3})*", s) else head.replace(",", "") + "." + tail
    decimals = len(s.split(".")[1]) if "." in s else 0
    return float(s), decimals


def _skip(value: float, unit: str, sentence: str, start: int) -> bool:
    if unit:
        return False
    if start > 0 and sentence[start - 1] == "/" and value in {5, 10, 20, 100}:  # scale denominators (e.g. 63/100)
        return True
    prefix = sentence[max(0, start - 12):start].upper()
    if value in {60, 100, 500, 2000} and any( prefix.endswith(p) for p in ("S&P ", "TSX ", "NASDAQ-", "NASDAQ ", "RUSSELL ") ):
        return True
    if value.is_integer() and 1900 <= value <= 2100:   # years
        return True
    return value.is_integer() and value <= 12            # counts, list markers, months, levels


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-ZÀ-Ý*\-#])|\n+", text)
    return [p.strip() for p in parts if p.strip()]


def check_numbers(answer: str, ledger: Ledger) -> list[Claim]:
    claims: list[Claim] = []
    for sent in sentences(answer):
        cited = RECEIPT_IDS.findall(" ".join(m.group(0) for m in RECEIPT.finditer(sent)))
        bare = RECEIPT.sub("", sent)
        pool: list[float] = []
        for rid in cited:
            r = ledger.get(rid)
            if r is not None and r.error is None:
                pool += numbers_in(r.output) + numbers_in(r.inputs)
        for mt in NUMBER.finditer(bare):
            unit = (mt.group("unit") or "").strip()
            value, dec = _parse(mt.group("num"))
            if _skip(value, unit, bare, mt.start()):
                continue
            is_pct = unit == "%"
            if not cited:
                status = "no_citation"
            else:
                tol = 0.5 * 10 ** (-dec) + 1e-9
                if unit in {"k$", "M$"}:
                    value *= 1_000 if unit == "k$" else 1_000_000
                    tol *= 1_000 if unit == "k$" else 1_000_000
                targets = [abs(value)] + ([abs(value) / 100] if is_pct else [])
                tols = [tol] + ([tol / 100] if is_pct else [])
                ok = any(abs(abs(c) - t) <= tl for c in pool for t, tl in zip(targets, tols))
                status = "verified" if ok else "not_found"
            claims.append(Claim(sent, mt.group(0).strip(), value, is_pct, cited, status))
    return claims


GOVERNANCE_RULES = [
    ("DIRECTIVE_TO_TRADE", r"\b(you should|you must|vous devriez|tu devrais|il faut)\s+(buy|sell|acheter|vendre)\b"),
    ("DIRECTIVE_TO_TRADE", r"\b(buy|sell|achetez|vendez|achète|vends)\s+(now|today|maintenant|aujourd'hui)\b"),
    ("GUARANTEE", r"(?<!not )(?<!no )(?<!pas )(?<!aucun )\b(guaranteed (return|gain|profit)s?|rendements? garantis?)\b"),
    ("CERTAIN_PREDICTION", r"\b(will (definitely|certainly|surely) (rise|go up|double|outperform)|"
                           r"va (forcément|certainement) (monter|doubler))\b"),
]


def check_governance(answer: str) -> list[dict]:
    issues = []
    low = answer.lower()
    for code, pattern in GOVERNANCE_RULES:
        for mt in re.finditer(pattern, low):
            issues.append({"code": code, "excerpt": answer[max(0, mt.start() - 40): mt.end() + 40]})
    return issues


def verify(answer: str, ledger: Ledger) -> Report:
    return Report(check_numbers(answer, ledger), check_governance(answer))

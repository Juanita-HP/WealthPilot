"""Long-term return assumptions used to judge whether a goal is reachable.

These are planning HYPOTHESES, not forecasts. They come from the 2026
Projection Assumption Guidelines published jointly by FP Canada and the
Institute of Financial Planning (effective 2026-04-30), the reference used by
Canadian financial planners for projections of 10 years or more.

Source: https://institutpf.org/en/projection-assumption-guidelines
Retrieved: 2026-11-14. Returns are nominal, annual, before fees.
"""

SOURCE = {
    "name": "FP Canada / Institute of Financial Planning, Projection Assumption Guidelines 2026",
    "url": "https://institutpf.org/en/projection-assumption-guidelines",
    "effective": "2026-04-30",
    "retrieved": "2026-11-14",
    "note": "Long-term (10+ years) planning assumptions, nominal, before fees. Not a forecast.",
}

INFLATION = 0.021

# Expected long-term nominal returns by building block.
RETURNS = {
    "canadian_equity": 0.064,
    "us_equity": 0.066,             # guideline: U.S. and developed international equities
    "international_equity": 0.066,  # same guideline line as U.S. equities (developed markets)
    "emerging_equity": 0.075,
    "fixed_income": 0.032,
    "short_term": 0.024,
}

# Asset classes the guidelines do not cover. We refuse to invent a number for
# them: they contribute no assumed return, and any result that depends on them
# is flagged as uncertain.
NO_ASSUMPTION = {"crypto", "gold"}


def blended_return(mix: dict[str, float]) -> tuple[float, float]:
    """Weighted return of a mix of building blocks.

    Returns (assumed_return, share_without_assumption). Blocks listed in
    NO_ASSUMPTION are counted at 0% and reported separately.
    """
    total, uncovered = 0.0, 0.0
    for block, weight in mix.items():
        if block in RETURNS:
            total += weight * RETURNS[block]
        elif block in NO_ASSUMPTION:
            uncovered += weight
        else:
            raise KeyError(f"unknown building block {block!r}")
    return total, uncovered

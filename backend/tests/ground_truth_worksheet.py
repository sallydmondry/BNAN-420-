"""Independent take-home worksheet used to create ground truth for the sample offers.

This deliberately does NOT import the app's tax engine or processed data. Every constant below was
typed by hand from the primary documents, so it independently checks both the data pipeline
(PDF/XLSX parsing) and the tax math:

  * IRS Rev. Proc. 2025-32, Sec. 4.01 Table 3 (TY2026 single brackets) and Sec. 4.15 ($16,100 std deduction)
  * IRS Publication 15 (2026): SS 6.2% up to $184,500; Medicare 1.45%
  * IRS Notice 2025-67: 401(k) elective deferral limit $24,500
  * Tax Foundation "State Individual Income Tax Rates and Brackets, 2026" (single columns)
  * NYS DTF IT-201-I (NYC resident schedule, single); pittsburghpa.gov (EIT 3% + $52 LST); Denver OPT FAQ ($5.75/mo)

Same model assumptions as the product: single filer, standard deduction, W-2 wages only, resident of office city,
6% pre-tax 401(k) unless stated, $1,440/yr pre-tax health premium (KFF 2025 average) unless the offer states one.
"""

from __future__ import annotations

FED_STD = 16_100
FED = [(0, 0.10), (12_400, 0.12), (50_400, 0.22), (105_700, 0.24), (201_775, 0.32), (256_225, 0.35), (640_600, 0.37)]
SS_RATE, SS_BASE, MED_RATE = 0.062, 184_500, 0.0145
K401_LIMIT = 24_500

STATES = {
    # state: (std_deduction, exemption, credit, brackets, taxes_401k)
    "AZ": (8_350, 0, 0, [(0, 0.025)], False),
    "CO": (16_100, 0, 0, [(0, 0.044)], False),
    "TX": None, "WA": None, "TN": None,
    "CA": (5_540, 0, 153, [(0, .01), (11_079, .02), (26_264, .04), (41_452, .06), (57_542, .08), (72_724, .093),
                           (371_479, .103), (445_771, .113), (742_953, .123), (1_000_000, .133)], False),
    "NY": (8_000, 0, 0, [(0, .039), (8_500, .044), (11_700, .0515), (13_900, .054), (80_650, .059), (215_400, .0685),
                         (1_077_550, .0965), (5_000_000, .103), (25_000_000, .109)], False),
    "NC": (12_750, 0, 0, [(0, 0.0399)], False),
    "IL": (0, 2_925, 0, [(0, 0.0495)], False),
    "PA": (0, 0, 0, [(0, 0.0307)], True),
}
NYC = [(0, 0.03078), (12_000, 0.03762), (25_000, 0.03819), (50_000, 0.03876)]


def progressive(income: float, brackets: list[tuple[float, float]]) -> float:
    """Tax on ``income`` for brackets [(lower_bound, rate), ...]."""
    tax = 0.0
    for i, (lo, rate) in enumerate(brackets):
        hi = brackets[i + 1][0] if i + 1 < len(brackets) else float("inf")
        if income > lo:
            tax += (min(income, hi) - lo) * rate
    return tax


def worksheet(gross: float, state: str, city: str, k401_pct: float = 6.0, health_annual: float = 1_440.0) -> dict:
    """Return each worksheet line and the resulting annual/monthly take-home."""
    k401 = min(gross * k401_pct / 100, K401_LIMIT)
    fed_wages = gross - k401 - health_annual
    fed_taxable = max(0.0, fed_wages - FED_STD)
    fed_tax = progressive(fed_taxable, FED)
    fica_wages = gross - health_annual
    ss = min(fica_wages, SS_BASE) * SS_RATE
    med = fica_wages * MED_RATE
    st = STATES[state]
    state_tax = state_taxable = 0.0
    if st:
        std, ex, credit, br, taxes_401k = st
        st_wages = (gross - health_annual) if taxes_401k else fed_wages
        state_taxable = max(0.0, st_wages - std - ex)
        state_tax = max(0.0, progressive(state_taxable, br) - credit)
    local = 0.0
    if state == "NY" and city == "New York":
        local = progressive(state_taxable, NYC)
    elif state == "PA" and city == "Pittsburgh":
        local = 0.03 * (gross - health_annual) + 52
    elif state == "CO" and city == "Denver":
        local = 5.75 * 12
    total = fed_tax + ss + med + state_tax + local
    take_home = gross - k401 - health_annual - total
    r2 = lambda x: round(x, 2)  # noqa: E731
    return {
        "gross": r2(gross), "pretax_401k": r2(k401), "pretax_health": r2(health_annual),
        "federal_taxable": r2(fed_taxable), "federal_tax": r2(fed_tax), "social_security": r2(ss), "medicare": r2(med),
        "state_taxable": r2(state_taxable), "state_tax": r2(state_tax), "local_tax": r2(local), "total_tax": r2(total),
        "take_home_annual": r2(take_home), "take_home_monthly": r2(take_home / 12),
    }

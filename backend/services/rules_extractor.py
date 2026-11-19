"""Local (no-LLM) offer-letter field extractor.

Approach:
1. Normalize the text and split it into *segments* (sentences, bullet lines, "Label: value" lines),
   so a number is only ever interpreted using words from its own segment.
2. Every dollar amount is classified by the nearest compensation keyword in its segment
   (base salary, signing bonus, relocation, HSA, equity, bonus, hourly...). Amounts next to
   words like "reimburse" or "tuition" are ignored.
3. Dedicated patterns read 401(k) match formulas, bonus %, PTO, start date and work arrangement.
4. Company, job title and office location use phrase patterns and the letterhead/signature.

A field the letter does not mention stays ``not_stated``. It is never guessed.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from functools import lru_cache
from typing import Optional

from backend.core.config import SIMULATED_DIR
from backend.core.models import EquityGrant, Extracted, Match401k, MatchTier, OfferFields
from backend.data import lookups as L

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
DATE_RE = rf"((?:{MONTHS})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s*\d{{4}}|\d{{1,2}}/\d{{1,2}}/\d{{2,4}}|\d{{4}}-\d{{2}}-\d{{2}})"
MONEY_RE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?\s*([kK](?![a-z])|[mM]illion)?")
PCT = r"(\d{1,3}(?:\.\d+)?)\s*%"

# Keyword classes for dollar amounts, checked in their own segment. Order matters only for ties.
MONEY_CLASSES: list[tuple[str, str]] = [
    ("ignore", r"reimburs|tuition|exam fee|course cost|wellness|gym|phone|internet|commuter|per diem|cap of|401\(k\) limit|referral"),
    ("signing", r"sign[\s-]?on|signing|hiring bonus|starting bonus|one-time bonus"),
    ("relocation", r"relocat|moving"),
    ("hsa", r"\bHSA\b|health savings"),
    ("equity", r"\bequity\b|\bRSUs?\b|restricted stock|stock option|\bshares\b"),
    ("bonus", r"(?<!signing )(?<!sign-on )(?<!sign on )(?<!hiring )(?<!starting )(?<!one-time )\bbonus\b|\bincentive\b"),
    ("base", r"base salary|base pay|\bbase\b|\bsalary\b|annual rate|\bwages?\b|compensation|\bpay\b|\bearn"),
]
HOURLY_AFTER = re.compile(r"^\s*(?:/\s*|per\s+|an?\s+)(?:hr|hour)\b", re.I)
MONTHLY_AFTER = re.compile(r"^\s*(?:/\s*|per\s+|a\s+|each\s+)(?:mo|month)\b", re.I)
YEARLY_AFTER = re.compile(r"^\s*(?:/\s*(?:yr|year)|per\s+year|annually|a\s+year|each\s+year|per\s+annum)", re.I)

SUFFIXES = re.compile(r",?\s+(?:LLC|L\.L\.C\.|Inc\.?|Incorporated|Corp\.?|Corporation|Ltd\.?|Co\.)$", re.I)
TITLE_WORDS = r"[A-Z][A-Za-z0-9&/+().'-]*"


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def _clean(text: str) -> str:
    t = text.replace("\r", "\n").replace("–", "-").replace("—", "-").replace("’", "'")
    t = t.replace(" ", " ").replace("•", "\n- ").replace("\t", " ")
    t = re.sub(r"[ ]{2,}", " ", t)
    # OCR often drops the space after a comma in dates ("March 11,2026").
    t = re.sub(r"(\d),(\d{4})\b", r"\1, \2", t)
    return t


_LABEL_LINE = re.compile(r"^\s*(?:[-*>]|\d+[.)])?\s*[A-Za-z0-9()][A-Za-z0-9() /&'.-]{1,40}?\s*(?::|\.{3,}|\s-\s)")


def segments(text: str) -> list[str]:
    """Split into sentence/bullet/label segments. Soft line wraps are joined back together."""
    lines = [ln.strip() for ln in _clean(text).split("\n")]
    segs: list[str] = []
    cur = ""
    for ln in lines:
        if not ln:
            if cur:
                segs.append(cur)
            cur = ""
            continue
        starts_new = bool(re.match(r"^[-*>]\s", ln)) or bool(_LABEL_LINE.match(ln)) or not cur or \
            cur.rstrip().endswith((".", "!", "?", ":")) and ln[:1].isupper()
        if starts_new and cur:
            segs.append(cur)
            cur = ln
        else:
            cur = f"{cur} {ln}".strip()
    if cur:
        segs.append(cur)
    out: list[str] = []
    for s in segs:
        # Sentence split (avoid decimals like $78,000.00 and abbreviations like "St.").
        parts = re.split(r"(?<=[a-z0-9)%])[.!?]\s+(?=[A-Z(])", s)
        out.extend(p.strip() for p in parts if p.strip())
    # Collapsed PDF lines like "Base Salary: $85,000 annually. Signing Bonus: $5,000" are split by sentence
    # above; lines that glue several "Label: value" pairs without periods are split on known labels.
    final: list[str] = []
    label_split = re.compile(r"(?<!signing)(?<!sign-on)(?<!annual)(?<!target)\s(?=(?:Annual\s+)?(?:Signing bonus|Sign-on bonus|Annual bonus|Bonus|401\(k\)|Paid time off|PTO|"
                             r"Time off|Relocation|Equity|HSA|Start date|Work arrangement)\s*:)", re.I)
    for s in out:
        final.extend(p.strip() for p in label_split.split(s) if p.strip())
    return final


def flat(text: str) -> str:
    """Single-line version of the text (soft wraps joined)."""
    return re.sub(r"\s+", " ", _clean(text))


def _money(m: re.Match) -> float:
    v = float(m.group(1).replace(",", ""))
    if m.group(2):
        v += float("0." + m.group(2))
    suf = (m.group(3) or "").lower()
    if suf == "k":
        v *= 1_000
    elif suf.startswith("m"):
        v *= 1_000_000
    return v


def _evidence(s: str, start: int = 0, end: Optional[int] = None, width: int = 120) -> str:
    end = len(s) if end is None else end
    if len(s) <= width:
        return s.strip()
    mid = (start + end) // 2
    lo = max(0, mid - width // 2)
    return ("…" if lo > 0 else "") + s[lo:lo + width].strip() + ("…" if lo + width < len(s) else "")


def _stated(value, evidence: str, note: Optional[str] = None) -> Extracted:
    return Extracted(value=value, status="stated", evidence=evidence[:160], note=note)


def _derived(value, evidence: str, note: str) -> Extracted:
    return Extracted(value=value, status="derived", evidence=evidence[:160], note=note)


# ---------------------------------------------------------------------------
# Dollar amounts
# ---------------------------------------------------------------------------


def _classify_money(seg: str, m: re.Match) -> str:
    before = seg[:m.start()]
    after = seg[m.end():]
    best, best_d = "unknown", 10**9
    for cls, pat in MONEY_CLASSES:
        for km in re.finditer(pat, before, re.I):
            d = len(before) - km.end()
            if d < best_d or (d == best_d and cls == "ignore"):
                best, best_d = cls, d
        km = re.search(pat, after[:60], re.I)
        if km and cls in ("hsa", "relocation", "equity", "ignore", "signing"):
            d = km.start() + 15  # following keywords count, but a little less than preceding ones
            if d < best_d:
                best, best_d = cls, d
    return best


def _amounts(segs: list[str]) -> dict[str, list[tuple[float, str, str]]]:
    """class -> [(amount, unit, evidence)] where unit is 'year' | 'hour' | 'month' | ''."""
    found: dict[str, list[tuple[float, str, str]]] = {}
    for seg in segs:
        for m in MONEY_RE.finditer(seg):
            amt = _money(m)
            after = seg[m.end():]
            unit = "hour" if HOURLY_AFTER.match(after) else "month" if MONTHLY_AFTER.match(after) else \
                "year" if YEARLY_AFTER.match(after) else ""
            cls = _classify_money(seg, m)
            if cls == "unknown" and unit == "hour":
                cls = "base"
            found.setdefault(cls, []).append((amt, unit, _evidence(seg, m.start(), m.end())))
    return found


# ---------------------------------------------------------------------------
# Specific fields
# ---------------------------------------------------------------------------


def parse_401k(text: str) -> Optional[tuple[Match401k, str]]:
    """Read tiered matches ('100% of the first 3% and 50% of the next 2%') and safe-harbor contributions."""
    f = flat(text)
    # Look only near 401(k)/retirement/match language.
    windows = [m.start() for m in re.finditer(r"401\s?\(?k\)?|retirement|\bmatch", f, re.I)]
    if not windows:
        return None
    lo = max(0, min(windows) - 200)
    hi = min(len(f), max(windows) + 260)
    zone = f[lo:hi]
    tier_re = re.compile(
        r"(?:(\d{1,3}(?:\.\d+)?)\s*%|(dollar[- ]for[- ]dollar))(?:\s+(?:company|employer))?(?:\s+match(?:es|ing)?)?"
        r"\s+(?:on|of)?\s*(?:the\s+)?(?:your\s+|employee\s+|what you\s+)?(?:401\s?\(?k\)?\s+)?"
        r"(?:contributions?|deferrals?|contribute|put in)?,?\s*(?:on\s+)?(?:the\s+)?(first|next|up to)\s+"
        r"(\d{1,2}(?:\.\d+)?)\s*%", re.I)
    tiers: list[MatchTier] = []
    ev = []
    for m in tier_re.finditer(zone):
        rate = 1.0 if m.group(2) else float(m.group(1)) / 100.0
        if rate > 3:  # "100%" style rates only; guards against stray numbers
            continue
        tiers.append(MatchTier(rate=rate, on_pct=float(m.group(4))))
        ev.append(m.group(0))
    if not tiers:
        sm = re.search(r"(\d{1,2}(?:\.\d+)?)\s*%\s+(?:employer|company)\s+match\b(?!\s+on)", zone, re.I)
        if sm:
            tiers.append(MatchTier(rate=1.0, on_pct=float(sm.group(1))))
            ev.append(sm.group(0) + " (read as 100% of the first " + sm.group(1) + "%)")
    non = 0.0
    nm = re.search(r"(?:safe[- ]harbor|non-?elective|profit[- ]sharing)[^.]{0,80}?" + PCT, zone, re.I) or \
        re.search(PCT + r"[^.]{0,80}?(?:whether or not you contribute|regardless of (?:whether|your contribution))", zone, re.I)
    if nm:
        non = float(nm.group(1))
        ev.append(nm.group(0))
    if not tiers and not non:
        if re.search(r"no (?:401\s?\(?k\)? )?match|does not (?:offer|provide) a match", zone, re.I):
            return Match401k(description="No employer match"), "no match"
        return None
    parts = [f"{t.rate * 100:g}% of the {'first' if i == 0 else 'next'} {t.on_pct:g}%" for i, t in enumerate(tiers)]
    if non:
        parts.append(f"{non:g}% of pay regardless of your contribution")
    vest = re.search(r"(vests? immediately|immediate vesting|\d-year (?:graded |cliff )?vesting)", zone, re.I)
    desc = "Employer contributes " + " and ".join(parts) + (f" ({vest.group(1)})" if vest else "")
    return Match401k(tiers=tiers, nonelective_pct=non, description=desc), "; ".join(ev)


def parse_bonus_pct(segs: list[str]) -> Optional[tuple[float, str]]:
    for seg in segs:
        if re.search(r"sign[\s-]?on|signing", seg, re.I) and not re.search(r"annual|target|incentive", seg, re.I):
            continue
        m = re.search(r"(?:bonus|incentive|award)[^%$]{0,70}?" + PCT, seg, re.I)
        if m and float(m.group(1)) <= 100:
            return float(m.group(1)), _evidence(seg, m.start(), m.end())
    return None


def parse_pto(f: str) -> tuple[Optional[tuple[float, str]], bool]:
    if re.search(r"unlimited (?:PTO|paid time off|vacation)|flexible\s*/\s*unlimited|(?:PTO|time off|vacation)[^.]{0,20}unlimited", f, re.I):
        return None, True
    pats = [
        r"(\d{1,2})\s+(?:days?\s+)?(?:of\s+)?(?:paid\s+time\s+off|PTO|vacation(?:\s+days)?|paid vacation)",
        r"(\d{1,2})\s+vacation\s+days",
        r"(?:PTO|paid time off|time off|vacation)\s*[:.\-]*\s*(\d{1,2})\s+days",
    ]
    for p in pats:
        m = re.search(p, f, re.I)
        if m:
            return (float(m.group(1)), _evidence(f, m.start(), m.end(), 90)), False
    return None, False


def _iso_date(s: str) -> Optional[str]:
    s = re.sub(r"(\d)(st|nd|rd|th)", r"\1", s.replace(".", "")).strip()
    s = re.sub(r"\s+", " ", s.replace(",", ", ")).replace(" ,", ",")
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y", "%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.replace(", ", ", ").replace("  ", " "), fmt).date().isoformat()
        except ValueError:
            continue
    s2 = s.replace("Sept", "Sep")
    for fmt in ("%b %d, %Y", "%b %d %Y"):
        try:
            return datetime.strptime(s2, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_start(f: str) -> Optional[tuple[str, str]]:
    m = re.search(r"(?:start(?:ing)?(?:\s+date)?|commencing(?:\s+on)?|beginning|first day(?:\s+will\s+be)?|join(?:ing)? us on)"
                  r"[^0-9A-Za-z]{0,3}(?:\s*(?:is|will be|of|on|date|would be))*\s*[:.\-]*\s*" + DATE_RE, f, re.I)
    if not m:
        return None
    iso = _iso_date(m.group(1))
    return (iso, _evidence(f, m.start(), m.end(), 90)) if iso else None


def parse_arrangement(f: str) -> Optional[tuple[str, str]]:
    checks = [
        ("remote", r"fully remote|100% remote|remote[- ]first|remote (?:role|position)|work from anywhere|this (?:role|position) is remote"),
        ("hybrid", r"hybrid|\d\s*days?\s*(?:a|per|/)\s*(?:week|wk)\s+in(?:\s+the)?\s+office|in(?:\s+the)?\s+office\s+\d\s*days|"
                   r"\d\s+days?\s+(?:remote|from home)|\bWFH\b"),
        ("onsite", r"on-?site|in-office role|in-person|in office five days|five days (?:per|a) week|5 days (?:per|a) week|fully in[- ]office"),
    ]
    for label, pat in checks:
        m = re.search(pat, f, re.I)
        if m:
            return label, _evidence(f, m.start(), m.end(), 90)
    return None


@lru_cache(maxsize=1)
def _known_companies() -> list[str]:
    p = SIMULATED_DIR / "reviews.json"
    if not p.exists():
        return []
    return [c["name"] for c in json.loads(p.read_text())["companies"]]


def _tidy_company(name: str) -> str:
    n = name.strip(" ,.-|:;\"'")
    if n.isupper() and len(n) > 4:
        n = " ".join(w if w in {"LLP", "LLC", "&", "USA", "US"} or len(w) <= 2 and w.isalpha() and w not in {"OF", "AT"}
                     else w.capitalize() for w in n.split())
    n = SUFFIXES.sub("", n).strip(" ,")
    return n


def parse_company(text: str) -> Optional[tuple[str, str]]:
    f = flat(text)
    low = f.lower()
    for name in sorted(_known_companies(), key=len, reverse=True):
        base = SUFFIXES.sub("", name).lower()
        i = low.find(base)
        if i >= 0:
            # keep a trailing LLP if the letter uses it
            m = re.match(re.escape(base) + r"(\s+llp)?", low[i:])
            full = name if not (m and m.group(1)) or name.lower().endswith("llp") else name + " LLP"
            return full, _evidence(f, i, i + len(base), 90)
    pats = [
        r"on behalf of ([A-Z][\w&.' -]{2,60}?)\s*(?:\(|,| I\b)",
        r"(?:^|[.!]\s+|,\s+)([A-Z][\w&.'-]*(?:\s[A-Z][\w&.'-]*){0,4}) (?:is|are) (?:happy|pleased|excited|thrilled|delighted) to (?:offer|extend)",
        r"join ([A-Z][\w&.' -]{2,60}?) as\b",
        r"offer (?:of employment )?from ([A-Z][\w&.' -]{2,60}?)(?:[!.,]|$)",
        r"position (?:of [^.]{3,60}? )?with ([A-Z][\w&.' -]{2,60}?)(?: in |[.,])",
        r"(?:position|role|job) (?:of|as) [^.]{3,60}? at ([A-Z][\w&.' -]{2,60}?)(?: in |,|\.| as )",
        r"\bat ([A-Z][\w&' -]{2,40}?) in our\b",
        r"Subject:\s*([A-Z][\w&.' ]{2,50}?)\s+-\s",
        r"(?:Recruiting|Talent(?: Team)?|People(?: Ops)?|HR)\s*[|,@-]\s*([A-Z][\w&.' ]{2,50})$",
        r"@\s*([A-Z][\w&.' ]{2,40}?)\s+recruiting",
    ]
    for p in pats:
        for m in re.finditer(p, f, re.M):
            name = _tidy_company(m.group(1))
            if name.lower() in {"we", "i", "our", "us", "our team", "the team", "the company", "you", "they"}:
                continue
            return name, _evidence(f, m.start(), m.end(), 90)
    for ln in _clean(text).split("\n")[:4]:
        ln = ln.strip()
        head = re.split(r"\s+(?:-{1,2}|\||//)\s+", ln)[0]
        if re.search(r"\b(?:offer|employment|letter|confidential|summary|details)\b", head, re.I) and not \
                re.search(r"\b(?:LLC|LLP|Inc|Corp)\b", head):
            continue
        if 3 <= len(head) <= 60 and not MONEY_RE.search(head) and not re.search(r"^(dear|hi|hello|from|date|to)\b", head, re.I):
            if head.isupper() or re.search(r"\b(?:LLC|LLP|Inc|Corp|Group|Partners|Bank|Capital|Software|Analytics)\b", head):
                return _tidy_company(head), head
    return None


ROLE_NOUNS = (r"analyst|associate|engineer|developer|consultant|accountant|auditor|specialist|manager|coordinator|"
              r"representative|assistant|scientist|designer|administrator|officer|advisor|adviser|planner|technician|"
              r"intern|trainee|executive|strategist|architect|programmer|nurse|teacher|paralegal|attorney|lawyer|"
              r"recruiter|generalist|buyer|underwriter|actuary|economist|statistician|researcher|director|lead|"
              r"supervisor|agent|clerk|controller|editor|writer|producer|marketer|operator|technologist|therapist|"
              r"pharmacist|chemist|biologist|fellow|apprentice|banker|trader|partner|copywriter|bookkeeper|examiner|"
              r"investigator|counselor|educator|instructor|tutor|liaison|ambassador|owner|head")
_ROLE_END = re.compile(rf"^(.*\b(?:{ROLE_NOUNS})s?\b(?:\s+(?:I{{1,3}}|IV|V|[1-5]))?(?:\s+-\s+[A-Za-z&]+(?:\s[A-Za-z&]+)?)?)",
                       re.I)
_TITLE_STOP = re.compile(r"\s+(?:in|at|with|on|for|reporting|based|located|to|within|where|starting|beginning|effective|"
                         r"who|which|that|from|under|and\s+(?:you|will|report|your)|you|your|position|role|job|opening)\b"
                         r"|[.;:(!?@]|,", re.I)
_TITLE_LEAD = re.compile(r"^(?:(?:an?|the|our|full[- ]time|part[- ]time|new|permanent|exempt|salaried|regular)\s+)+", re.I)
_X = r"([A-Za-z][A-Za-z&/'\-]*(?:\s+[A-Za-z0-9&/'\-]+){0,8})"


def _clean_title(raw: str) -> Optional[str]:
    """Trim a candidate to a plausible job title; None unless it ends in a real job word (Analyst, Engineer…)."""
    t = re.sub(r"\s+", " ", raw).strip(" ,.:;-")
    t = _TITLE_STOP.split(t)[0].strip(" -")
    t = _TITLE_LEAD.sub("", t)
    m = _ROLE_END.match(t)
    if not m:
        return None
    t = m.group(1).strip()
    if not 1 <= len(t.split()) <= 8 or MONEY_RE.search(t):
        return None
    keep = {"I", "II", "III", "IV", "V", "IT", "HR", "QA", "UX", "UI", "CPA", "FP&A", "AI", "ML", "SQL", "VP"}
    all_caps = t.isupper()
    t = " ".join(w if w in keep else (w.capitalize() if all_caps or w.islower() else w) for w in t.split())
    t = re.sub(r"\b(Of|And|For|The)\b", lambda m: m.group(1).lower(), t)
    return t


def parse_title(text: str) -> Optional[tuple[str, str]]:
    """Job title from labeled lines first, then common offer-letter sentences, then a guarded fallback."""
    lines = [ln.strip() for ln in _clean(text).split("\n") if ln.strip()]
    label = re.compile(r"^(?:[-*>]\s*)?(?:job\s+title|position\s+title|official\s+title|business\s+title|title|role|"
                       r"position|job)\b\s*(?::|\.{2,}|-|\|)?\s*(.{3,90})$", re.I)
    for ln in lines:
        m = label.match(ln)
        if m and (t := _clean_title(m.group(1))):
            return t, _evidence(ln, 0, len(ln), 90)
    f = flat(text)
    pats = [
        rf"(?i:title|position)\s+(?i:will\s+be|is)\s+(?i:that\s+of\s+)?(?:(?i:an?|the)\s+)?{_X}",
        rf"(?i:position|role|job|title)\s+(?i:of|as)\s+(?:(?i:an?|the)\s+)?{_X}",
        rf"(?i:offer|extend|hire|hiring)[^.]{{0,50}}?\b(?i:the|a|an|our)\s+{_X}\s+(?i:position|role|job|opening)\b",
        rf"\b(?i:as|be)\s+(?i:an?|our|the)\s+(?:(?i:new|full-time|part-time)\s+)?{_X}",
        rf"\b(?i:role|position|title)\s*:\s*{_X}",
        rf"(?i:offer)\s*[:\-]\s*{_X}",
        rf"(?i:for|into|fill)\s+(?i:the)\s+{_X}\s+(?i:position|role)\b",
    ]
    for p in pats:
        for m in re.finditer(p, f):
            if t := _clean_title(m.group(1)):
                return t, _evidence(f, m.start(), m.end(), 90)
    # Fallback: a capitalized phrase ending in a job word, inside a sentence about the offer (not a signature line).
    body = re.split(r"\n\s*(?:best|sincerely|regards|warm regards|kind regards|cheers|thanks|thank you|respectfully)\b[^\n]{0,20}\n",
                    _clean(text), maxsplit=1, flags=re.I)[0]
    for seg in segments(body):
        if re.search(r"\b(?:offer|position|role|join|hire|title)\b", seg, re.I):
            m = re.search(rf"\b((?:[A-Z][A-Za-z&/-]*\s+){{0,5}}(?i:{ROLE_NOUNS})s?)\b", seg)
            if m and (t := _clean_title(m.group(1))):
                return t, _evidence(seg, m.start(), m.end(), 90)
    return None


_STATE_NAME = r"(?:[A-Z]{2}\b|" + "|".join(sorted((n.title() for n in L.US_STATES), key=len, reverse=True)) + \
    "|" + "|".join(sorted((n.upper() for n in L.US_STATES), key=len, reverse=True)) + r")"
_CITY = r"([A-Z][A-Za-z.'-]+(?:\s[A-Z][A-Za-z.'-]+){0,3})"
_NOT_CITY = {"the", "our", "this", "your", "suite", "hybrid", "remote", "office", "main", "corporate", "downtown",
             "headquarters", "street", "st", "ave", "avenue", "road", "blvd", "floor", "building", "dear", "you", "we"}


def _city_ok(city: str, st: Optional[str]) -> Optional[tuple[str, Optional[str]]]:
    """Accept a candidate city only if it is a real place (with a state) or a supported metro (without one).

    Leading words are dropped one at a time so "Northbeam Minneapolis" still finds Minneapolis.
    """
    words = city.split()
    for i in range(len(words)):
        c = " ".join(words[i:])
        c = c.title() if c.isupper() else c
        if c.lower() in _NOT_CITY or len(c) < 3:
            continue
        alias = L.CITY_ALIASES.get(c.lower())
        if alias:
            return alias[0], st or alias[1]
        if not st and len(c.split()) > 1:
            c2, st2 = L.split_city_state(c)
            if st2 and c2 and L.geocode(f"{c2}, {st2}"):
                return c2, st2
        if st:
            if L.geocode(f"{c}, {st}"):
                return c, st
        else:
            r = L.resolve_city(c, None)
            if r.matched and r.method == "principal_city":
                return c, r.state
    return None


def parse_location(text: str) -> Optional[tuple[str, Optional[str], str]]:
    """(city, state, evidence). Labeled locations and office phrases win over letterhead addresses."""
    f = flat(text)
    lines = [ln.strip() for ln in _clean(text).split("\n") if ln.strip()]
    lab_kw = (r"(?i:primary\s+work\s+location|work\s*location|job\s+location|office\s+location|work\s*site|worksite|"
              r"duty\s+station|location|where|office|based\s+in|based\s+out\s+of)")
    label = rf"{lab_kw}\s*(?i:will\s+be|is)?\s*(?i:in|at)?\s*[:.\-|]*\s*(?i:our\s+)?(?:[^,\n]{{0,40}}\d[^,\n]{{0,40}},\s*)?{_CITY}(?:,\s*({_STATE_NAME}))?"
    pats = [
        (label, lines),
        (label, [f]),
        (rf"(?i:our\s+)?{_CITY}(?:,\s*({_STATE_NAME}))?\s+(?i:office|headquarters|hq|studio|location|campus|branch|site|hub)\b", [f]),
        (rf"(?i:located|based|work|working|position|role|job|team|relocate|relocating|move|moving)\s+(?i:is\s+|will\s+be\s+)?"
         rf"(?i:located\s+|based\s+)?(?i:in|to|out\s+of|at)\s+(?i:our\s+)?(?i:the\s+)?{_CITY}(?:,\s*({_STATE_NAME}))?", [f]),
        (rf"\b(?i:in|at|of)\s+(?i:our\s+)?{_CITY},\s*({_STATE_NAME})\b", [f]),
        (rf",\s*{_CITY},\s*([A-Z]{{2}})\s+\d{{5}}", [f]),
    ]
    for p, sources in pats:
        for src in sources:
            for m in re.finditer(p, src):
                st = L.normalize_state(m.group(2)) if m.lastindex and m.lastindex >= 2 and m.group(2) else None
                ok = _city_ok(m.group(1).strip(), st)
                if ok:
                    return ok[0], ok[1], _evidence(src, m.start(), m.end(), 90)
    return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

OFFER_SIGNALS = [r"\boffer\b", r"salary|base pay|compensation|\$\d", r"start(?:ing)? date|\bstart\b|commenc",
                 r"position|role|title", r"401\s?\(?k\)?|benefits|PTO|paid time off", r"congratulat|pleased|excited|welcome"]


def offer_likelihood(text: str) -> float:
    """Share of offer-letter signals present (0–1)."""
    return sum(1 for p in OFFER_SIGNALS if re.search(p, text, re.I)) / len(OFFER_SIGNALS)


def extract_fields(text: str) -> tuple[OfferFields, list[str]]:
    """Run every rule over the letter text. Returns (fields, log lines)."""
    log: list[str] = []
    segs = segments(text)
    f = flat(text)
    fields = OfferFields()
    amounts = _amounts(segs)

    # Base pay
    base_cands = amounts.get("base", [])
    annual = [(a, u, e) for a, u, e in base_cands if u in ("year", "") and a >= 15_000]
    hourly = [(a, u, e) for a, u, e in base_cands + amounts.get("unknown", []) if u == "hour" and a < 500]
    monthly = [(a, u, e) for a, u, e in base_cands if u == "month" and 1_000 <= a < 50_000]
    if annual:
        a, _, e = annual[0]
        fields.base_salary = _stated(a, e)
        fields.pay_basis = "annual"
    elif monthly:
        a, _, e = monthly[0]
        fields.base_salary = _derived(a * 12, e, f"${a:,.0f}/month × 12")
        fields.pay_basis = "monthly"
    elif hourly:
        a, _, e = hourly[0]
        fields.hourly_rate = _stated(a, e)
        hm = re.search(r"(\d{2})\s*hours?\s*(?:per|a|/)\s*week", f, re.I)
        hours = float(hm.group(1)) if hm else 40.0
        if hm:
            fields.hours_per_week = _stated(hours, _evidence(f, hm.start(), hm.end(), 60))
        fields.base_salary = _derived(a * hours * 52, e, f"${a:,.2f}/hr × {hours:g} hrs/week × 52 weeks"
                                      + ("" if hm else " (40 hrs/week assumed — not stated in offer)"))
        fields.pay_basis = "hourly"
    else:
        unk = [(a, u, e) for a, u, e in amounts.get("unknown", []) if a >= 25_000 and u in ("year", "")]
        if unk:
            a, _, e = max(unk, key=lambda x: x[0])
            fields.base_salary = _derived(a, e, "Largest annual amount in the letter; label unclear — please confirm.")
            fields.pay_basis = "annual"
            log.append("Base salary label was unclear; used the largest annual amount.")

    if m := amounts.get("signing"):
        fields.signing_bonus = _stated(m[0][0], m[0][2])
    elif nm := re.search(r"no (?:signing|sign-on) bonus|not (?:offer|include) a (?:signing|sign-on) bonus", f, re.I):
        fields.signing_bonus = _stated(0.0, _evidence(f, nm.start(), nm.end(), 80), "Offer says there is no signing bonus")
    if m := amounts.get("relocation"):
        fields.relocation = _stated(m[0][0], m[0][2])
    if m := amounts.get("hsa"):
        fields.hsa_employer_annual = _stated(m[0][0] * (12 if m[0][1] == "month" else 1), m[0][2])
    if m := amounts.get("equity"):
        a, _, e = m[0]
        vm = re.search(r"(?:over|vesting over|vest(?:s|ing)? over)\s+(\d+|four|three|two|five)\s+years", f, re.I)
        words = {"two": 2, "three": 3, "four": 4, "five": 5}
        years = None
        if vm:
            g = vm.group(1).lower()
            years = float(words.get(g, g)) if g in words or g.isdigit() else None
        fields.equity = _stated(EquityGrant(value_usd=a, vesting_years=years, description=e), e)
    bonus_amt = [x for x in amounts.get("bonus", []) if x[0] >= 500]
    if bp := parse_bonus_pct(segs):
        fields.bonus_target_pct = _stated(bp[0], bp[1])
    elif bonus_amt:
        fields.bonus_target_amount = _stated(bonus_amt[0][0], bonus_amt[0][2])
    elif nb := re.search(r"bonus\s*:\s*not part|no (?:annual |performance )?bonus|not (?:bonus|incentive)[- ]eligible|"
                         r"not eligible for (?:a |an )?(?:annual )?bonus", f, re.I):
        fields.bonus_target_pct = _stated(0.0, _evidence(f, nb.start(), nb.end(), 80), "Offer says there is no bonus")
    elif db := re.search(r"discretionary[^.]{0,60}bonus|bonus[^.]{0,40}discretionary", f, re.I):
        fields.bonus_target_pct = Extracted(value=None, status="not_stated", evidence=_evidence(f, db.start(), db.end(), 100),
                                            note="Discretionary bonus mentioned, but no target stated")

    if k := parse_401k(text):
        fields.match_401k = _stated(k[0], k[1])
    pto, unlimited = parse_pto(f)
    fields.pto_unlimited = unlimited
    if pto:
        fields.pto_days = _stated(pto[0], pto[1])
    if sd := parse_start(f):
        fields.start_date = _stated(sd[0], sd[1])
    if wa := parse_arrangement(f):
        fields.work_arrangement = _stated(wa[0], wa[1])
    if hp := re.search(r"(?:premium|you(?:r)? (?:pay|cost|contribution))[^.$]{0,40}" + MONEY_RE.pattern + r"\s*(?:/|per|a)\s*(?:mo|month)", f, re.I):
        mm = MONEY_RE.search(hp.group(0))
        if mm:
            fields.health_premium_monthly = _stated(_money(mm), _evidence(f, hp.start(), hp.end(), 90))
    if c := parse_company(text):
        fields.company = _stated(c[0], c[1])
    if t := parse_title(text):
        fields.job_title = _stated(t[0], t[1])
    if loc := parse_location(text):
        fields.office_city = _stated(loc[0], loc[2])
        if loc[1]:
            fields.office_state = _stated(loc[1], loc[2])
        elif am := re.search(re.escape(loc[0]) + r",\s*([A-Z]{2})\s+\d{5}", f):
            fields.office_state = _stated(am.group(1), _evidence(f, am.start(), am.end(), 80))
    log.append(f"Read {len(segs)} text segments and {sum(len(v) for v in amounts.values())} dollar amounts.")
    return fields, log

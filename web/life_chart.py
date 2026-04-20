"""Life Predictions Chart — simplified VedAstro-style engine.

Scope: Marriage + Career only (v1).

Approach:
  1. Analyse the natal chart once (ascendant, planet→house, house lords, dignities)
  2. Walk birth → +100y in time slices; for each slice find active Mahadasha
     and Antardasha lords and score the two topics as -3..+3
  3. Bucket the score into {Good, Neutral, Bad} = green/white/red

Rule descriptions are drawn from classical Vedic astrology (and align with
VedAstro's MIT-licensed rule set).
"""

from __future__ import annotations

from typing import List, Tuple

from jhora import const, utils
from jhora.horoscope.chart import charts
from jhora.horoscope.dhasa.graha import vimsottari
from jhora.panchanga import drik


SUN, MOON, MARS, MERCURY, JUPITER, VENUS, SATURN, RAHU, KETU = range(9)

SIGN_LORD = {
    0: MARS, 1: VENUS, 2: MERCURY, 3: MOON, 4: SUN, 5: MERCURY,
    6: VENUS, 7: MARS, 8: JUPITER, 9: SATURN, 10: SATURN, 11: JUPITER,
}
EXALT_SIGN = {SUN: 0, MOON: 1, MARS: 9, MERCURY: 5, JUPITER: 3,
              VENUS: 11, SATURN: 6, RAHU: 1, KETU: 7}
DEBIL_SIGN = {p: (s + 6) % 12 for p, s in EXALT_SIGN.items()}
BENEFICS = {JUPITER, VENUS, MERCURY, MOON}
MALEFICS = {SUN, MARS, SATURN, RAHU, KETU}


_SWE_PLANETS = {
    SUN: const._SUN, MOON: const._MOON, MARS: const._MARS,
    MERCURY: const._MERCURY, JUPITER: const._JUPITER,
    VENUS: const._VENUS, SATURN: const._SATURN,
    RAHU: const._RAHU, KETU: const._KETU,
}


def analyse_natal(jd: float, place) -> dict:
    """Return a dict describing house placement, lords, dignities for each planet."""
    rows = charts.rasi_chart(jd, place)
    asc_sign = rows[0][1][0]
    planets = {}  # planet_id -> {sign, longitude, house}
    for token, (sign_idx, deg) in rows:
        if token == "L":
            continue
        if not isinstance(token, int) or token > KETU:
            continue
        house = ((sign_idx - asc_sign) % 12) + 1
        planets[token] = {"sign": sign_idx, "long": deg, "house": house}
    house_lord = {h: SIGN_LORD[(asc_sign + h - 1) % 12] for h in range(1, 13)}
    return {"asc_sign": asc_sign, "planets": planets, "house_lord": house_lord,
            "moon_sign": planets.get(MOON, {}).get("sign", asc_sign)}


def transit_signs(jd: float, place, planets=(JUPITER, SATURN, RAHU, KETU)) -> dict:
    """Sidereal sign (0..11) of each planet at jd (local julian day)."""
    jd_utc = jd - place.timezone
    out = {}
    for p in planets:
        lon = drik.sidereal_longitude(jd_utc, _SWE_PLANETS[p])
        out[p] = int(lon / 30) % 12
    return out


def _house_from(sign_from: int, target_sign: int) -> int:
    """House number (1..12) counting from sign_from."""
    return ((target_sign - sign_from) % 12) + 1


def _dignity_bonus(natal: dict, planet: int) -> int:
    """+1 for exalted/own-sign, -1 for debilitated, else 0."""
    p = natal["planets"].get(planet)
    if not p:
        return 0
    if EXALT_SIGN.get(planet) == p["sign"]:
        return 1
    if DEBIL_SIGN.get(planet) == p["sign"]:
        return -1
    if planet in SIGN_LORD.values() and SIGN_LORD[p["sign"]] == planet:
        return 1
    return 0


def _house_placement_score(house: int, good: set, bad: set) -> int:
    if house in good:
        return 1
    if house in bad:
        return -1
    return 0


GOOD_HOUSES = {1, 4, 5, 9, 10, 11}
BAD_HOUSES = {6, 8, 12}


def score_marriage(natal: dict, md_lord: int, ad_lord: int) -> Tuple[int, List[str]]:
    """Score -3..+3. Returns (score, reasons)."""
    score = 0
    reasons = []

    lord7 = natal["house_lord"][7]
    lord7_house = natal["planets"].get(lord7, {}).get("house")
    venus = natal["planets"].get(VENUS, {})
    jupiter = natal["planets"].get(JUPITER, {})
    seventh_occupants = [p for p, v in natal["planets"].items() if v["house"] == 7]

    if lord7_house in GOOD_HOUSES:
        score += 1
        reasons.append(f"7th lord in {lord7_house}th (well placed)")
    elif lord7_house in BAD_HOUSES:
        score -= 1
        reasons.append(f"7th lord in {lord7_house}th (afflicted)")

    if venus.get("house") in {1, 4, 5, 7, 11}:
        score += 1
        reasons.append("Venus well placed for love")
    if venus.get("house") in BAD_HOUSES:
        score -= 1
        reasons.append("Venus afflicted")
    score += _dignity_bonus(natal, VENUS)

    if MARS in seventh_occupants:
        score -= 1
        reasons.append("Mars in 7th (Kuja dosha)")
    if SATURN in seventh_occupants:
        score -= 1
        reasons.append("Saturn in 7th (delays)")
    if RAHU in seventh_occupants or KETU in seventh_occupants:
        score -= 1
        reasons.append("Rahu/Ketu in 7th")
    if JUPITER in seventh_occupants or VENUS in seventh_occupants:
        score += 1
        reasons.append("Benefic in 7th")

    if md_lord == lord7:
        score += 2
        reasons.append("Mahadasha of 7th lord")
    if md_lord == VENUS:
        score += 1
        reasons.append("Venus Mahadasha")
    if md_lord == JUPITER and jupiter.get("house") in GOOD_HOUSES:
        score += 1
        reasons.append("Jupiter Mahadasha (Jupiter well placed)")
    if md_lord in {SATURN, RAHU, KETU} and md_lord in seventh_occupants:
        score -= 1
        reasons.append(f"{_name(md_lord)} Mahadasha (in 7th)")

    if ad_lord == lord7:
        score += 1
        reasons.append("Antardasha of 7th lord")
    if ad_lord == VENUS:
        score += 1
        reasons.append("Venus Antardasha")
    if ad_lord in {SATURN, RAHU} and ad_lord in seventh_occupants:
        score -= 1
        reasons.append(f"{_name(ad_lord)} Antardasha (in 7th)")

    return max(-3, min(3, score)), reasons


def score_career(natal: dict, md_lord: int, ad_lord: int) -> Tuple[int, List[str]]:
    score = 0
    reasons = []

    lord10 = natal["house_lord"][10]
    lord10_house = natal["planets"].get(lord10, {}).get("house")
    sun = natal["planets"].get(SUN, {})
    saturn = natal["planets"].get(SATURN, {})
    mercury = natal["planets"].get(MERCURY, {})
    tenth_occupants = [p for p, v in natal["planets"].items() if v["house"] == 10]

    if lord10_house in GOOD_HOUSES:
        score += 1
        reasons.append(f"10th lord in {lord10_house}th (well placed)")
    elif lord10_house in BAD_HOUSES:
        score -= 1
        reasons.append(f"10th lord in {lord10_house}th (afflicted)")

    if sun.get("house") in {1, 9, 10, 11}:
        score += 1
        reasons.append("Sun in Kendra/Trikona (strong authority)")
    score += _dignity_bonus(natal, SUN)

    if saturn.get("house") == 10:
        score += 1
        reasons.append("Saturn in 10th (disciplined career)")
    if mercury.get("house") in {1, 2, 5, 10, 11}:
        score += 1
        reasons.append("Mercury well placed (commerce/skill)")

    benefics_in_tenth = [p for p in tenth_occupants if p in BENEFICS]
    if benefics_in_tenth:
        score += 1
        reasons.append("Benefic in 10th")

    if md_lord == lord10:
        score += 2
        reasons.append("Mahadasha of 10th lord")
    if md_lord == SUN and sun.get("house") in GOOD_HOUSES:
        score += 1
        reasons.append("Sun Mahadasha (well placed)")
    if md_lord == SATURN and saturn.get("house") in {3, 6, 10, 11}:
        score += 1
        reasons.append("Saturn Mahadasha (Upachaya)")
    if md_lord == MERCURY and mercury.get("house") in GOOD_HOUSES:
        score += 1
        reasons.append("Mercury Mahadasha (skill / business)")
    if md_lord in BAD_HOUSES_OCCUPANTS(natal):
        score -= 1
        reasons.append(f"{_name(md_lord)} Mahadasha (in dusthana)")

    if ad_lord == lord10:
        score += 1
        reasons.append("Antardasha of 10th lord")
    if ad_lord == SUN:
        score += 0
    if ad_lord in {RAHU, KETU} and ad_lord in tenth_occupants:
        score -= 1
        reasons.append(f"{_name(ad_lord)} Antardasha (in 10th)")

    return max(-3, min(3, score)), reasons


def BAD_HOUSES_OCCUPANTS(natal: dict) -> set:
    """Set of planets sitting in 6/8/12."""
    return {p for p, v in natal["planets"].items() if v["house"] in BAD_HOUSES}


SATURN_GOOD_FROM_MOON = {3, 6, 11}
JUPITER_GOOD_FROM_MOON = {2, 5, 7, 9, 11}
NODES_GOOD_FROM_MOON = {3, 6, 11}


def score_marriage_transit(natal: dict, transit: dict) -> tuple:
    """Return (score_delta, reasons) from transits. Layered on natal+dasha."""
    score = 0
    reasons = []
    moon = natal["moon_sign"]
    asc = natal["asc_sign"]
    lord7 = natal["house_lord"][7]
    lord7_sign = natal["planets"].get(lord7, {}).get("sign")
    venus_sign = natal["planets"].get(VENUS, {}).get("sign")

    jup = transit.get(JUPITER)
    sat = transit.get(SATURN)
    rahu = transit.get(RAHU)
    ketu = transit.get(KETU)

    if jup is not None:
        if _house_from(moon, jup) in JUPITER_GOOD_FROM_MOON:
            score += 1
            reasons.append(f"Jupiter transit in {_house_from(moon, jup)}th from Moon (benefic gochara)")
        if _house_from(asc, jup) == 7:
            score += 1
            reasons.append("Jupiter transiting 7th house")
        if lord7_sign is not None and jup == lord7_sign:
            score += 1
            reasons.append("Jupiter transiting natal 7th lord")

    if sat is not None:
        if _house_from(asc, sat) == 7:
            score -= 1
            reasons.append("Saturn transiting 7th house (delays)")
        if lord7_sign is not None and sat == lord7_sign:
            score -= 1
            reasons.append("Saturn transiting natal 7th lord")
        sade_house = _house_from(moon, sat)
        if sade_house in {12, 1, 2}:
            score -= 1
            reasons.append(f"Sade Sati (Saturn in {sade_house}th from Moon)")

    for node, name in ((rahu, "Rahu"), (ketu, "Ketu")):
        if node is None:
            continue
        if _house_from(asc, node) == 7:
            score -= 1
            reasons.append(f"{name} transiting 7th house")
        if venus_sign is not None and node == venus_sign:
            score -= 1
            reasons.append(f"{name} conjunct natal Venus")

    return score, reasons


def score_career_transit(natal: dict, transit: dict) -> tuple:
    score = 0
    reasons = []
    moon = natal["moon_sign"]
    asc = natal["asc_sign"]
    lord10 = natal["house_lord"][10]
    lord10_sign = natal["planets"].get(lord10, {}).get("sign")

    jup = transit.get(JUPITER)
    sat = transit.get(SATURN)
    rahu = transit.get(RAHU)

    if jup is not None:
        h_asc = _house_from(asc, jup)
        if h_asc in {10, 11}:
            score += 1
            reasons.append(f"Jupiter transiting {h_asc}th (opportunity)")
        if lord10_sign is not None and jup == lord10_sign:
            score += 1
            reasons.append("Jupiter transiting natal 10th lord")
        if _house_from(moon, jup) in JUPITER_GOOD_FROM_MOON:
            score += 0  # already counted for marriage; keep career neutral
        else:
            score -= 0

    if sat is not None:
        sat_moon = _house_from(moon, sat)
        if sat_moon in SATURN_GOOD_FROM_MOON:
            score += 1
            reasons.append(f"Saturn transit in {sat_moon}th from Moon (favourable gochara)")
        if sat_moon in {12, 1, 2}:
            score -= 1
            reasons.append(f"Sade Sati (Saturn in {sat_moon}th from Moon)")
        if _house_from(asc, sat) == 10:
            score += 0  # Saturn in 10th is mixed — pressure, eventual reward
            reasons.append("Saturn transiting 10th (discipline / pressure)")

    if rahu is not None and lord10_sign is not None and rahu == lord10_sign:
        score -= 1
        reasons.append("Rahu transiting natal 10th lord")

    return score, reasons


def _name(pid: int) -> str:
    return ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"][pid]


def build_timeline(jd: float, place, years: int = 100, slice_days: int = 30) -> dict:
    """Return per-slice scores for Marriage and Career across `years` years."""
    natal = analyse_natal(jd, place)
    ad_result = vimsottari.get_vimsottari_dhasa_bhukthi(jd, place, dhasa_level_index=2)
    md_result = vimsottari.get_vimsottari_dhasa_bhukthi(jd, place, dhasa_level_index=1)

    md_ranges = []
    for entry in md_result[1]:
        md_ranges.append((_tuple_to_jd(entry[1]), entry[0][0], entry[2]))
    for i in range(len(md_ranges) - 1):
        md_ranges[i] = (md_ranges[i][0], md_ranges[i + 1][0], md_ranges[i][1])
    md_ranges[-1] = (md_ranges[-1][0], md_ranges[-1][0] + md_ranges[-1][2] * 365.25, md_ranges[-1][1])

    ad_ranges = []
    for entry in ad_result[1]:
        ad_ranges.append((_tuple_to_jd(entry[1]), entry[0][1], entry[2]))
    for i in range(len(ad_ranges) - 1):
        ad_ranges[i] = (ad_ranges[i][0], ad_ranges[i + 1][0], ad_ranges[i][1])
    ad_ranges[-1] = (ad_ranges[-1][0], ad_ranges[-1][0] + ad_ranges[-1][2] * 365.25, ad_ranges[-1][1])

    slices = []
    end_jd = jd + years * 365.25
    cur = jd
    base_cache = {}  # (md, ad) -> natal+dasha score & reasons
    explanations = {}  # keyed by signature including transit signature
    while cur < end_jd:
        md = _lord_at(md_ranges, cur, MOON)
        ad = _lord_at(ad_ranges, cur, md)
        base_key = (md, ad)
        if base_key not in base_cache:
            m_base, m_base_r = score_marriage(natal, md, ad)
            c_base, c_base_r = score_career(natal, md, ad)
            base_cache[base_key] = (m_base, m_base_r, c_base, c_base_r)
        m_base, m_base_r, c_base, c_base_r = base_cache[base_key]

        t = transit_signs(cur, place)
        t_sig = (t.get(JUPITER), t.get(SATURN), t.get(RAHU), t.get(KETU))
        full_key = f"{md}_{ad}_{t_sig[0]}_{t_sig[1]}_{t_sig[2]}_{t_sig[3]}"

        if full_key not in explanations:
            m_t, m_t_r = score_marriage_transit(natal, t)
            c_t, c_t_r = score_career_transit(natal, t)
            m_total = max(-3, min(3, m_base + m_t))
            c_total = max(-3, min(3, c_base + c_t))
            explanations[full_key] = {
                "md": md, "ad": ad,
                "md_name": _name(md), "ad_name": _name(ad),
                "marriage": m_total,
                "marriage_reasons": m_base_r + m_t_r,
                "career": c_total,
                "career_reasons": c_base_r + c_t_r,
                "transit": {
                    "jupiter": t.get(JUPITER),
                    "saturn": t.get(SATURN),
                    "rahu": t.get(RAHU),
                    "ketu": t.get(KETU),
                },
            }
        e = explanations[full_key]
        slices.append({
            "jd": cur,
            "md": md,
            "ad": ad,
            "key": full_key,
            "marriage": e["marriage"],
            "career": e["career"],
        })
        cur += slice_days

    return {"natal": natal, "slices": slices, "start_jd": jd,
            "end_jd": end_jd, "explanations": explanations}


def natal_summary(natal: dict) -> dict:
    """Flat dict describing chart features the scoring rules care about."""
    p = natal["planets"]
    asc = ["Aries","Taurus","Gemini","Cancer","Leo","Virgo","Libra",
           "Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"][natal["asc_sign"]]
    def describe(pid):
        v = p.get(pid)
        if not v:
            return {"house": None, "sign": None, "dignity": "—"}
        dg = _dignity_bonus(natal, pid)
        dignity = "exalted/own" if dg > 0 else ("debilitated" if dg < 0 else "—")
        return {"house": v["house"], "sign": v["sign"], "dignity": dignity}
    return {
        "ascendant": asc,
        "lord_7": _name(natal["house_lord"][7]),
        "lord_7_house": p.get(natal["house_lord"][7], {}).get("house"),
        "lord_10": _name(natal["house_lord"][10]),
        "lord_10_house": p.get(natal["house_lord"][10], {}).get("house"),
        "venus": describe(VENUS),
        "jupiter": describe(JUPITER),
        "sun": describe(SUN),
        "saturn": describe(SATURN),
        "mercury": describe(MERCURY),
        "seventh_occupants": [_name(pid) for pid, v in p.items() if v["house"] == 7],
        "tenth_occupants": [_name(pid) for pid, v in p.items() if v["house"] == 10],
    }


def _tuple_to_jd(t) -> float:
    y, m, d, h = t
    return utils.julian_day_number((y, m, d), _hours_to_hms(h))


def _hours_to_hms(hr: float):
    h = int(hr)
    mf = (hr - h) * 60
    mm = int(mf)
    ss = int((mf - mm) * 60)
    return (h, mm, ss)


def _lord_at(ranges, jd_val, default):
    for start, end, lord in ranges:
        if start <= jd_val < end:
            return lord
    return default


def render_svg(timeline: dict, subject: str = "") -> str:
    """Render timeline as horizontal coloured-bar SVG (Marriage + Career rows)."""
    slices = timeline["slices"]
    if not slices:
        return "<svg/>"

    start_jd = timeline["start_jd"]
    end_jd = timeline["end_jd"]
    total_days = end_jd - start_jd

    width = 1000
    left_pad = 70
    right_pad = 12
    top_pad = 28
    row_h = 42
    row_gap = 6
    axis_h = 18
    rows = [("Marriage", "marriage"), ("Career", "career")]
    height = top_pad + len(rows) * (row_h + row_gap) + axis_h + 14

    plot_w = width - left_pad - right_pad
    slice_days = (slices[1]["jd"] - slices[0]["jd"]) if len(slices) > 1 else 30
    slice_w = (slice_days / total_days) * plot_w

    def color_for(score: int) -> str:
        if score >= 2:
            return "#16a34a"
        if score == 1:
            return "#86efac"
        if score == 0:
            return "#f5f5f4"
        if score == -1:
            return "#fca5a5"
        return "#dc2626"

    def x_for(jd_val: float) -> float:
        return left_pad + (jd_val - start_jd) / total_days * plot_w

    birth_y0, birth_m0, birth_d0, _ = utils.jd_to_gregorian(start_jd)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'font-family="system-ui,sans-serif" font-size="11" '
        f'data-left-pad="{left_pad}" data-plot-w="{plot_w}" '
        f'data-total-days="{total_days:.4f}" '
        f'data-birth-date="{birth_y0:04d}-{birth_m0:02d}-{birth_d0:02d}" '
        f'data-row-top-pad="{top_pad}" data-row-h="{row_h}" data-row-gap="{row_gap}" '
        f'data-content-h="{top_pad + len(rows) * (row_h + row_gap)}">',
        f'<text x="{left_pad}" y="16" font-size="13" font-weight="600" fill="#334155">'
        f'Life Chart{(" · " + subject) if subject else ""}</text>',
    ]

    birth_y = utils.jd_to_gregorian(start_jd)[0]
    end_y = utils.jd_to_gregorian(end_jd)[0]
    for yr in range(birth_y, end_y + 1, 10):
        jd_yr = utils.julian_day_number((yr, 1, 1), (0, 0, 0))
        x = x_for(jd_yr)
        parts.append(
            f'<line class="yr-tick" x1="{x:.1f}" y1="{top_pad}" x2="{x:.1f}" '
            f'y2="{height - axis_h}" stroke="#e2e8f0" stroke-width="0.5"/>'
        )
        parts.append(
            f'<text class="yr-tick" x="{x:.1f}" y="{height - 4}" text-anchor="middle" '
            f'fill="#64748b">{yr}</text>'
        )

    for ri, (label, key) in enumerate(rows):
        y = top_pad + ri * (row_h + row_gap)
        parts.append(
            f'<text x="{left_pad - 8}" y="{y + row_h/2 + 4:.0f}" '
            f'text-anchor="end" fill="#475569" font-weight="500">{label}</text>'
        )
        for s in slices:
            x = x_for(s["jd"])
            c = color_for(s[key])
            parts.append(
                f'<rect x="{x:.2f}" y="{y}" width="{slice_w + 0.6:.2f}" '
                f'height="{row_h}" fill="{c}"/>'
            )

    parts.append("</svg>")
    return "".join(parts)

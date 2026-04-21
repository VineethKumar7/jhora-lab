"""Life Predictions Chart — layered Vedic scoring engine.

Scope: Marriage + Career (v2, 3-layer formula, range -10..+10).

Layers (classical Parashari):
  L1 — Natal potential          (±3)   topic house lord + karaka + aspects received
  L2 — Functional B/M multiplier        applied inline to every L1/L3 contribution
  L3 — Dasa period              (±4)   MD placement biases the whole Mahadasha
  L4 — Transit window           (±3)   aspects of transiting Ju/Sa/Ra/Ke

Total clamped to [-10, +10].
"""

from __future__ import annotations

from typing import Dict, List, Tuple

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

# Graha drishti — full-strength aspects (houses from the planet, self=1).
# Every graha aspects its 7th. Ma/Ju/Sa have special aspects. Ra/Ke treated
# as Jupiter-like (most common modern convention, BV Raman / KN Rao).
SPECIAL_ASPECTS = {
    SUN: (7,),  MOON: (7,), MERCURY: (7,), VENUS: (7,),
    MARS: (4, 7, 8),
    JUPITER: (5, 7, 9),
    SATURN: (3, 7, 10),
    RAHU: (5, 7, 9),
    KETU: (5, 7, 9),
}

KENDRA_HOUSES = {1, 4, 7, 10}
TRIKONA_HOUSES = {1, 5, 9}
DUSTHANA_HOUSES = {6, 8, 12}
UPACHAYA_HOUSES = {3, 6, 10, 11}

SIGN_NAMES = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
              "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]

_ORDINAL = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th", 6: "6th",
            7: "7th", 8: "8th", 9: "9th", 10: "10th", 11: "11th", 12: "12th"}


def aspected_signs(planet: int, from_sign: int) -> set:
    """Signs aspected by `planet` when placed in `from_sign` (full drishti only)."""
    return {(from_sign + (h - 1)) % 12 for h in SPECIAL_ASPECTS[planet]}


def _aspect_number(planet: int, from_sign: int, target_sign: int) -> int:
    """Which of the planet's special aspects (1..12) hits target, or 0 if none."""
    if target_sign not in aspected_signs(planet, from_sign):
        return 0
    n = ((target_sign - from_sign) % 12) + 1
    return n if n in SPECIAL_ASPECTS[planet] else 0


def planets_aspecting_sign(natal: dict, target_sign: int) -> set:
    """Set of planet IDs whose natal placement throws full drishti on target_sign."""
    out = set()
    for p, info in natal["planets"].items():
        if target_sign in aspected_signs(p, info["sign"]):
            out.add(p)
    return out


def compute_functional_nature(asc_sign: int) -> Dict[int, Tuple[str, float]]:
    """Functional nature per graha for a given lagna.

    Returns {planet: (label, multiplier)} where multiplier is applied to
    every Layer-1 and Layer-3 contribution of that planet:
        +1.5  yoga karaka   (kendra+trikona lord)
        +1.0  functional benefic (pure trikona lord, or natural malefic as
              pure kendra lord)
        +0.5  neutral (natural benefic as kendra lord — kendradhipati dosha,
              or sole 2/11 lord, etc.)
        -1.0  functional malefic (dusthana lord — 6/8/12 — or Ra/Ke default)

    Simplified Parashari classification. Rahu/Ketu default to malefic; refine
    later per dispositor if needed.
    """
    lordships: Dict[int, set] = {}
    for h in range(1, 13):
        lord = SIGN_LORD[(asc_sign + h - 1) % 12]
        lordships.setdefault(lord, set()).add(h)

    nature: Dict[int, Tuple[str, float]] = {}
    for planet in (SUN, MOON, MARS, MERCURY, JUPITER, VENUS, SATURN):
        houses = lordships.get(planet, set())
        if not houses:
            nature[planet] = ("neutral", 0.5)
            continue

        owns_asc = 1 in houses
        non_asc_houses = houses - {1}
        is_kendra = bool(non_asc_houses & (KENDRA_HOUSES - {1}))
        is_trikona = bool(non_asc_houses & (TRIKONA_HOUSES - {1}))
        is_dusthana = bool(houses & DUSTHANA_HOUSES)

        # Classical priorities:
        #   1. kendra + trikona → yoga karaka (overrides dusthana)
        #   2. trikona lordship overrides dusthana
        #   3. lagna lord is never purely malefic (asc is kendra + trikona)
        if (is_kendra and is_trikona) or (owns_asc and is_trikona):
            nature[planet] = ("yoga_karaka", 1.5)
        elif is_trikona:
            nature[planet] = ("benefic", 1.0)
        elif owns_asc and is_dusthana:
            nature[planet] = ("neutral", 0.5)  # lagna lord + dusthana = mixed
        elif owns_asc:
            nature[planet] = ("benefic", 1.0)  # lagna lord alone = benefic
        elif is_dusthana:
            nature[planet] = ("malefic", -1.0)
        elif is_kendra:
            if planet in {JUPITER, VENUS, MERCURY, MOON}:
                nature[planet] = ("neutral", 0.5)  # kendradhipati dosha
            else:
                nature[planet] = ("benefic", 1.0)  # natural malefic, kendra lord
        else:
            nature[planet] = ("neutral", 0.5)

    nature[RAHU] = ("malefic", -1.0)
    nature[KETU] = ("malefic", -1.0)
    return nature


def _mult(nature: Dict[int, Tuple[str, float]], planet: int) -> float:
    return nature.get(planet, ("neutral", 0.5))[1]


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
    house_sign = {h: (asc_sign + h - 1) % 12 for h in range(1, 13)}
    return {"asc_sign": asc_sign, "planets": planets, "house_lord": house_lord,
            "house_sign": house_sign,
            "moon_sign": planets.get(MOON, {}).get("sign", asc_sign),
            "functional": compute_functional_nature(asc_sign)}


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


def _house_lean(house: int) -> int:
    """+1 for good houses, -1 for dusthanas, 0 otherwise."""
    if house in GOOD_HOUSES:
        return 1
    if house in BAD_HOUSES:
        return -1
    return 0


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _natal_layer(natal: dict, topic_house: int, karaka: int) -> Tuple[float, List[str]]:
    """Layer 1 — Natal potential for a topic house + natural karaka.

    Contributions (each × functional multiplier of the contributing planet):
      • Topic house lord placement (house-lean ±1) + dignity
      • Karaka's placement (house-lean ±1) + dignity
      • Aspects received by topic house: benefic full drishti → +, malefic → −
      • Aspects received by karaka's sign: same
    Clamped to ±3.
    """
    planets = natal["planets"]
    nature = natal["functional"]
    lord = natal["house_lord"][topic_house]
    lord_info = planets.get(lord)
    karaka_info = planets.get(karaka)
    topic_sign = natal["house_sign"][topic_house]

    raw = 0.0
    reasons: List[str] = []

    if lord_info:
        lean = _house_lean(lord_info["house"])
        dign = _dignity_bonus(natal, lord)
        mult = _mult(nature, lord)
        contrib = (lean + dign) * mult
        if contrib:
            raw += contrib
            reasons.append(
                f"{_name(lord)} ({_ORDINAL[topic_house]} lord) in {_ORDINAL[lord_info['house']]}"
                f" [{nature[lord][0]} ×{mult:+.1f}, {contrib:+.1f}]"
            )

    if karaka_info:
        lean = _house_lean(karaka_info["house"])
        dign = _dignity_bonus(natal, karaka)
        mult = _mult(nature, karaka)
        contrib = (lean + dign) * mult
        if contrib:
            raw += contrib
            reasons.append(
                f"{_name(karaka)} (karaka) in {_ORDINAL[karaka_info['house']]}"
                f" [{nature[karaka][0]} ×{mult:+.1f}, {contrib:+.1f}]"
            )

    # Aspects received by topic house
    for p in planets_aspecting_sign(natal, topic_sign):
        mult = _mult(nature, p)
        if mult == 0:
            continue
        contrib = 0.5 * mult
        raw += contrib
        p_info = planets[p]
        aspn = _aspect_number(p, p_info["sign"], topic_sign)
        reasons.append(
            f"{_name(p)} in {_ORDINAL[p_info['house']]} ({SIGN_NAMES[p_info['sign']]}) "
            f"aspects {_ORDINAL[topic_house]} ({SIGN_NAMES[topic_sign]}) via {_ORDINAL[aspn]} drishti "
            f"[{contrib:+.1f}]"
        )

    # Aspects received by karaka's sign
    if karaka_info:
        k_sign = karaka_info["sign"]
        for p in planets_aspecting_sign(natal, k_sign):
            if p == karaka:
                continue
            mult = _mult(nature, p)
            if mult == 0:
                continue
            contrib = 0.3 * mult
            raw += contrib
            p_info = planets[p]
            aspn = _aspect_number(p, p_info["sign"], k_sign)
            reasons.append(
                f"{_name(p)} in {_ORDINAL[p_info['house']]} ({SIGN_NAMES[p_info['sign']]}) "
                f"aspects {_name(karaka)} karaka in {_ORDINAL[karaka_info['house']]} "
                f"({SIGN_NAMES[k_sign]}) via {_ORDINAL[aspn]} drishti [{contrib:+.1f}]"
            )

    return _clamp(raw, -3.0, 3.0), reasons


def _dasa_layer(
    natal: dict, topic_house: int, karaka: int, md_lord: int, ad_lord: int
) -> Tuple[float, List[str]]:
    """Layer 3 — Dasa period effect (±4).

    MD planet's own placement × functional nature → period baseline.
    If MD = topic house lord → amplify. If MD = karaka → amplify.
    AD blends: weighted average of AD's own effect and MD baseline (MD weight 2, AD 1).
    """
    planets = natal["planets"]
    nature = natal["functional"]
    topic_lord = natal["house_lord"][topic_house]

    def planet_baseline(p: int) -> Tuple[float, str]:
        info = planets.get(p)
        if not info:
            return 0.0, ""
        lean = _house_lean(info["house"])
        dign = _dignity_bonus(natal, p)
        mult = _mult(nature, p)
        base = (lean + dign) * mult
        amp = 0.0
        note = []
        if p == topic_lord:
            amp += 2.5 if base >= 0 else -2.5
            note.append(f"= {_ORDINAL[topic_house]} lord")
        if p == karaka:
            amp += 1.5 if base >= 0 else -1.5
            note.append("= karaka")
        total = base + amp
        suffix = f" [{', '.join(note)}]" if note else ""
        return total, (
            f"{_name(p)} in {_ORDINAL[info['house']]} "
            f"[{nature[p][0]} ×{mult:+.1f}, base {base:+.1f}{suffix}]"
        )

    md_val, md_desc = planet_baseline(md_lord)
    ad_val, ad_desc = planet_baseline(ad_lord)

    # AD blend: weighted avg (MD 2, AD 1). If AD == MD, just the MD value.
    if md_lord == ad_lord:
        combined = md_val
    else:
        combined = (2 * md_val + ad_val) / 3.0

    reasons: List[str] = []
    if md_desc:
        reasons.append(f"MD {md_desc}")
    if ad_desc and md_lord != ad_lord:
        reasons.append(f"AD {ad_desc}")

    return _clamp(combined, -4.0, 4.0), reasons


def score_marriage(natal: dict, md_lord: int, ad_lord: int) -> Tuple[float, List[str]]:
    """Natal + Dasa combined score for marriage (7th house, Venus karaka).

    Returns (score, reasons) with score clamped to [-7, +7].
    """
    l1, r1 = _natal_layer(natal, topic_house=7, karaka=VENUS)
    l3, r3 = _dasa_layer(natal, 7, VENUS, md_lord, ad_lord)
    total = _clamp(l1 + l3, -7.0, 7.0)
    reasons = [f"[Natal {l1:+.1f}] " + r for r in r1] + \
              [f"[Dasa {l3:+.1f}] " + r for r in r3]
    reasons.insert(0, f"Natal {l1:+.1f} + Dasa {l3:+.1f} = {total:+.1f}")
    return total, reasons


def score_career(natal: dict, md_lord: int, ad_lord: int) -> Tuple[float, List[str]]:
    """Natal + Dasa combined score for career (10th house, Sun karaka).

    Saturn and Mercury are secondary karakas but we stick with Sun as the
    primary per BPHS. The Layer-1 aspect walk catches Saturn/Mercury influence
    via drishti anyway.
    """
    l1, r1 = _natal_layer(natal, topic_house=10, karaka=SUN)
    l3, r3 = _dasa_layer(natal, 10, SUN, md_lord, ad_lord)
    total = _clamp(l1 + l3, -7.0, 7.0)
    reasons = [f"[Natal {l1:+.1f}] " + r for r in r1] + \
              [f"[Dasa {l3:+.1f}] " + r for r in r3]
    reasons.insert(0, f"Natal {l1:+.1f} + Dasa {l3:+.1f} = {total:+.1f}")
    return total, reasons


def BAD_HOUSES_OCCUPANTS(natal: dict) -> set:
    """Set of planets sitting in 6/8/12."""
    return {p for p, v in natal["planets"].items() if v["house"] in BAD_HOUSES}


SATURN_GOOD_FROM_MOON = {3, 6, 11}
JUPITER_GOOD_FROM_MOON = {2, 5, 7, 9, 11}
NODES_GOOD_FROM_MOON = {3, 6, 11}


def _transit_topic_score(
    natal: dict, transit: dict, topic_house: int, karaka: int
) -> Tuple[float, List[str]]:
    """Layer 4 — Transit window (±3), aspect-aware.

    For each slow transiting planet (Ju/Sa/Ra/Ke), count:
      (a) aspect on topic house from asc
      (b) aspect on topic house from Moon (gochara)
      (c) aspect on natal karaka's sign
    Each full-strength hit weights by the transiting planet's functional
    nature for this lagna (×1.0 benefic, ×0.5 neutral, ×−1.0 malefic).
    Conjunction (same sign) counts as a hit. Clamped to ±3.
    """
    planets = natal["planets"]
    nature = natal["functional"]
    asc = natal["asc_sign"]
    moon = natal["moon_sign"]
    topic_sign_asc = natal["house_sign"][topic_house]
    topic_sign_moon = (moon + topic_house - 1) % 12
    karaka_info = planets.get(karaka)
    karaka_sign = karaka_info["sign"] if karaka_info else None

    raw = 0.0
    reasons: List[str] = []

    for p in (JUPITER, SATURN, RAHU, KETU):
        t_sign = transit.get(p)
        if t_sign is None:
            continue
        mult = _mult(nature, p)
        if mult == 0:
            continue
        hit_signs = aspected_signs(p, t_sign) | {t_sign}  # include conjunction
        t_house = _house_from(asc, t_sign)  # transit planet's house from asc

        def _aspect_detail(target_sign: int) -> str:
            if target_sign == t_sign:
                return "conjunction"
            n = _aspect_number(p, t_sign, target_sign)
            return f"{_ORDINAL[n]} drishti" if n else "aspect"

        if topic_sign_asc in hit_signs:
            contrib = 0.6 * mult
            raw += contrib
            reasons.append(
                f"Transit {_name(p)} in {_ORDINAL[t_house]} ({SIGN_NAMES[t_sign]}) "
                f"{_aspect_detail(topic_sign_asc)} "
                f"{_ORDINAL[topic_house]} ({SIGN_NAMES[topic_sign_asc]}) from asc [{contrib:+.1f}]"
            )
        if topic_sign_moon in hit_signs:
            contrib = 0.4 * mult
            raw += contrib
            moon_h = _house_from(moon, t_sign)
            reasons.append(
                f"Transit {_name(p)} in {_ORDINAL[moon_h]} from Moon ({SIGN_NAMES[t_sign]}) "
                f"{_aspect_detail(topic_sign_moon)} "
                f"{_ORDINAL[topic_house]} from Moon ({SIGN_NAMES[topic_sign_moon]}) [{contrib:+.1f}]"
            )
        if karaka_sign is not None and karaka_sign in hit_signs:
            contrib = 0.4 * mult
            raw += contrib
            reasons.append(
                f"Transit {_name(p)} in {_ORDINAL[t_house]} ({SIGN_NAMES[t_sign]}) "
                f"{_aspect_detail(karaka_sign)} "
                f"natal {_name(karaka)} in {_ORDINAL[karaka_info['house']]} "
                f"({SIGN_NAMES[karaka_sign]}) [{contrib:+.1f}]"
            )

    # Named bonuses — Sade Sati (Saturn in 12/1/2 from Moon) preserved.
    sat = transit.get(SATURN)
    if sat is not None and _house_from(moon, sat) in {12, 1, 2}:
        sade_h = _house_from(moon, sat)
        raw -= 0.5
        reasons.append(
            f"Sade Sati — Saturn in {SIGN_NAMES[sat]} "
            f"({_ORDINAL[sade_h]} from natal Moon) [-0.5]"
        )

    return _clamp(raw, -3.0, 3.0), reasons


def score_marriage_transit(natal: dict, transit: dict) -> Tuple[float, List[str]]:
    return _transit_topic_score(natal, transit, topic_house=7, karaka=VENUS)


def score_career_transit(natal: dict, transit: dict) -> Tuple[float, List[str]]:
    return _transit_topic_score(natal, transit, topic_house=10, karaka=SUN)


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
            m_total = _clamp(m_base + m_t, -10.0, 10.0)
            c_total = _clamp(c_base + c_t, -10.0, 10.0)
            explanations[full_key] = {
                "md": md, "ad": ad,
                "md_name": _name(md), "ad_name": _name(ad),
                "marriage": round(m_total, 1),
                "marriage_reasons": m_base_r + m_t_r,
                "career": round(c_total, 1),
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

    def color_for(score: float) -> str:
        # Temporary 5-bucket binning for ±10 range. Real continuous HSL
        # gradient comes with the UI pass (Layer-5 from the plan).
        if score >= 5:
            return "#16a34a"
        if score >= 1:
            return "#86efac"
        if score > -1:
            return "#f5f5f4"
        if score > -5:
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

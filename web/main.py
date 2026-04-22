import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import pytz
import requests
from fastapi import FastAPI, Request, Form, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from timezonefinder import TimezoneFinder

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jhora import utils, const  # noqa: E402
from jhora.panchanga import drik  # noqa: E402
from jhora.horoscope.chart import charts  # noqa: E402
from jhora.horoscope.dhasa.graha import vimsottari  # noqa: E402

from web import db  # noqa: E402
from web import life_chart  # noqa: E402
from web import basics  # noqa: E402

utils.get_resource_lists()
db.init_db()

AYANAMSA_MODES = [
    "LAHIRI", "TRUE_CITRA", "TRUE_LAHIRI", "KP", "KP-SENTHIL",
    "RAMAN", "YUKTESHWAR", "USHASHASHI",
    "SURYASIDDHANTA", "ARYABHATA", "SS_CITRA", "TRUE_REVATI",
    "TRUE_PUSHYA", "TRUE_MULA", "FAGAN",
]
DEFAULT_AYANAMSA = "LAHIRI"


def _apply_ayanamsa(mode: Optional[str]) -> str:
    m = (mode or DEFAULT_AYANAMSA).upper()
    if m not in const.available_ayanamsa_modes:
        m = DEFAULT_AYANAMSA
    drik.set_ayanamsa_mode(m)
    return m
_tzfinder = TimezoneFinder()
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_HEADERS = {"User-Agent": "PyJHora-Web/1.0 (local use)"}

app = FastAPI(title="PyJHora Web")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


PLANET_LABELS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus",
                 "Saturn", "Rahu", "Ketu", "Uranus", "Neptune", "Pluto"]

VARGA_FACTORS = [
    (1,  "D-1 Rasi"),
    (2,  "D-2 Hora"),
    (3,  "D-3 Drekkana"),
    (4,  "D-4 Chaturthamsa"),
    (5,  "D-5 Panchamsa"),
    (6,  "D-6 Shashthamsa"),
    (7,  "D-7 Saptamsa"),
    (8,  "D-8 Ashtamsa"),
    (9,  "D-9 Navamsa"),
    (10, "D-10 Dasamsa"),
    (11, "D-11 Rudramsa"),
    (12, "D-12 Dwadasamsa"),
    (16, "D-16 Shodasamsa"),
    (20, "D-20 Vimsamsa"),
    (24, "D-24 Chaturvimsamsa"),
    (27, "D-27 Nakshatramsa"),
    (30, "D-30 Trimsamsa"),
    (40, "D-40 Khavedamsa"),
    (45, "D-45 Akshavedamsa"),
    (60, "D-60 Shashtiamsa"),
]


def _token_to_name(token) -> str:
    if token == "L":
        return "Asc"
    if isinstance(token, int) and 0 <= token < len(PLANET_LABELS):
        return PLANET_LABELS[token]
    return str(token)


def _houses_from_varga_rows(rasi_names, rows):
    houses = [{"sign": rasi_names[i], "sign_index": i, "planets": []} for i in range(12)]
    ascendant_sign = None
    for row in rows:
        token, (sign_idx, deg) = row
        is_asc = token == "L"
        if is_asc:
            ascendant_sign = sign_idx
        houses[sign_idx]["planets"].append({
            "name": _token_to_name(token),
            "deg": _deg_to_dms(deg),
            "is_asc": is_asc,
        })
    return ascendant_sign, houses


def _deg_to_dms(deg: float) -> str:
    d = int(deg)
    m_full = (deg - d) * 60
    m = int(m_full)
    s = int((m_full - m) * 60)
    return f"{d}°{m:02d}'{s:02d}\""


def _make_place_and_jd(date_str: str, time_str: str, lat: float, lon: float, tz: float):
    y, m, d = [int(x) for x in date_str.split("-")]
    hh, mm = [int(x) for x in time_str.split(":")]
    place = drik.Place("User", lat, lon, tz)
    jd = utils.julian_day_number((y, m, d), (hh, mm, 0))
    return place, jd, (y, m, d), (hh, mm)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


def _tz_offset_hours(lat: float, lon: float, at: Optional[datetime] = None) -> float:
    tz_name = _tzfinder.timezone_at(lat=lat, lng=lon)
    if not tz_name:
        return 0.0
    tz = pytz.timezone(tz_name)
    when = at or datetime.utcnow()
    offset = tz.utcoffset(when.replace(tzinfo=None)) or tz.utcoffset(datetime.utcnow())
    if offset is None:
        return 0.0
    return offset.total_seconds() / 3600.0


@app.get("/api/geocode")
async def geocode(q: str = Query(..., min_length=2), limit: int = Query(6, ge=1, le=10)):
    try:
        r = requests.get(
            NOMINATIM_URL,
            params={"q": q, "format": "json", "limit": limit, "addressdetails": 1},
            headers=NOMINATIM_HEADERS,
            timeout=6,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return JSONResponse({"error": str(e), "results": []}, status_code=502)

    results = []
    for row in data:
        try:
            lat = float(row["lat"])
            lon = float(row["lon"])
        except (KeyError, ValueError):
            continue
        tz_name = _tzfinder.timezone_at(lat=lat, lng=lon) or ""
        tz_offset = _tz_offset_hours(lat, lon) if tz_name else 0.0
        addr = row.get("address", {})
        label = row.get("display_name", "")
        short = addr.get("city") or addr.get("town") or addr.get("village") \
            or addr.get("county") or addr.get("state") or label.split(",")[0]
        country = addr.get("country", "")
        results.append({
            "label": label,
            "short": f"{short}, {country}".strip(", "),
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "timezone_name": tz_name,
            "timezone_offset": round(tz_offset, 2),
        })
    return {"results": results}


@app.get("/api/ayanamsa_list")
async def ayanamsa_list():
    return {"modes": AYANAMSA_MODES, "default": DEFAULT_AYANAMSA}


@app.get("/api/longitude_lookup")
async def longitude_lookup(q: str = Query(..., min_length=1, description="e.g. '94°19'', '25 Li 31', '5s 17° 45''")):
    try:
        data, canonical = basics.lookup(q)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"input": q, "canonical": canonical, **data}


def _sign_and_deg(abs_long: float, rasi_names):
    abs_long = abs_long % 360.0
    idx = int(abs_long // 30)
    return idx, rasi_names[idx], abs_long - idx * 30


@app.post("/api/house_references")
async def house_references(
    date: str = Form(...),
    time: str = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    timezone: float = Form(...),
    ayanamsa: Optional[str] = Form(None),
):
    """Compute houses from multiple reference points (Ch 1.3.3 + Ex. 2).

    References: Lagna, Chandra (Moon), Surya (Sun), Bhava Lagna, Hora Lagna, Ghati Lagna.
    """
    mode = _apply_ayanamsa(ayanamsa)
    place, jd, _, _ = _make_place_and_jd(date, time, latitude, longitude, timezone)
    rasi_names = utils.RAASI_LIST
    rasi_abbr = utils.RAASI_SHORT_LIST if hasattr(utils, "RAASI_SHORT_LIST") else [
        "Ar", "Ta", "Ge", "Cn", "Le", "Vi", "Li", "Sc", "Sg", "Cp", "Aq", "Pi"
    ]

    # Main rasi chart -> find Sun and Moon positions
    rasi_rows = charts.rasi_chart(jd, place)
    sun_sign, moon_sign = None, None
    sun_deg, moon_deg = 0.0, 0.0
    asc_sign, asc_deg = None, 0.0
    for token, (sign_idx, deg) in rasi_rows:
        if token == "L":
            asc_sign, asc_deg = sign_idx, deg
        elif token == 0:
            sun_sign, sun_deg = sign_idx, deg
        elif token == 1:
            moon_sign, moon_deg = sign_idx, deg

    # Special lagnas
    try:
        bhava = drik.special_ascendant(jd, place, lagna_rate_factor=0.25)
        hora  = drik.special_ascendant(jd, place, lagna_rate_factor=0.5)
        ghati = drik.special_ascendant(jd, place, lagna_rate_factor=1.25)
    except Exception:
        bhava, hora, ghati = None, None, None

    def _ref(key, label, sign_idx, deg_in_sign, note=""):
        if sign_idx is None:
            return None
        return {
            "key": key,
            "name": label,
            "sign_index": sign_idx,
            "sign": rasi_names[sign_idx],
            "abbr": rasi_abbr[sign_idx],
            "deg_in_sign": _deg_to_dms(deg_in_sign),
            "note": note,
        }

    refs = []
    refs.append(_ref("lagna", "Lagna (Ascendant)", asc_sign, asc_deg, "Default reference"))
    refs.append(_ref("moon",  "Chandra Lagna (Moon)", moon_sign, moon_deg))
    refs.append(_ref("sun",   "Surya Lagna (Sun)", sun_sign, sun_deg))
    if bhava: refs.append(_ref("bhava", "Bhava Lagna", bhava[0], bhava[1]))
    if hora:  refs.append(_ref("hora",  "Hora Lagna",  hora[0], hora[1]))
    if ghati: refs.append(_ref("ghati", "Ghati Lagna", ghati[0], ghati[1]))
    refs = [r for r in refs if r]

    # Build 12x|refs| matrix: for each house, the sign under every reference
    houses_matrix = []
    for h in range(1, 13):
        row = {"house": h, "signs": {}}
        for r in refs:
            s = (r["sign_index"] + h - 1) % 12
            row["signs"][r["key"]] = {
                "sign_index": s,
                "sign": rasi_names[s],
                "abbr": rasi_abbr[s],
            }
        houses_matrix.append(row)

    return {
        "ayanamsa": mode,
        "references": refs,
        "houses": houses_matrix,
    }


@app.post("/api/panchangam")
async def panchangam(
    date: str = Form(...),
    time: str = Form("12:00"),
    latitude: float = Form(50.3569),
    longitude: float = Form(7.5890),
    timezone: float = Form(1.0),
    ayanamsa: Optional[str] = Form(None),
):
    _apply_ayanamsa(ayanamsa)
    place, jd, _, _ = _make_place_and_jd(date, time, latitude, longitude, timezone)

    nak = drik.nakshatra(jd, place)
    tit = drik.tithi(jd, place)
    kar = drik.karana(jd, place)
    yog = drik.yogam(jd, place)
    vaara = drik.vaara(jd, place)
    sunrise = drik.sunrise(jd, place)
    sunset = drik.sunset(jd, place)
    moonrise = drik.moonrise(jd, place)
    moonset = drik.moonset(jd, place)

    nak_names = utils.NAKSHATRA_LIST
    tithi_names = utils.TITHI_LIST
    karana_names = utils.KARANA_LIST
    yoga_names = utils.YOGAM_LIST
    day_names = utils.DAYS_LIST

    return JSONResponse({
        "nakshatra": {
            "name": nak_names[nak[0] - 1] if nak[0] <= len(nak_names) else str(nak[0]),
            "number": nak[0],
            "pada": nak[1],
        },
        "tithi": {
            "name": tithi_names[tit[0] - 1] if tit[0] <= len(tithi_names) else str(tit[0]),
            "number": tit[0],
        },
        "karana": {
            "name": karana_names[kar[0] - 1] if kar[0] <= len(karana_names) else str(kar[0]),
            "number": kar[0],
        },
        "yoga": {
            "name": yoga_names[yog[0] - 1] if yog[0] <= len(yoga_names) else str(yog[0]),
            "number": yog[0],
        },
        "vaara": {
            "name": day_names[vaara - 1] if 1 <= vaara <= len(day_names) else str(vaara),
            "number": vaara,
        },
        "sunrise": sunrise[1],
        "sunset": sunset[1],
        "moonrise": moonrise[1] if moonrise else "-",
        "moonset": moonset[1] if moonset else "-",
    })


# Hora-of-the-hour (Ch 1.3.11): planetary lord of the current 1-hour slice after sunrise.
# Order of planets by decreasing geocentric speed (used to step from day-lord):
HORA_ORDER = ["Saturn", "Jupiter", "Mars", "Sun", "Venus", "Mercury", "Moon"]
# drik.vaara returns 0..6 where 0=Sunday. Map weekday index -> planetary day-lord:
WEEKDAY_LORD = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]


@app.post("/api/hora_hour")
async def hora_hour(
    date: str = Form(...),
    time: str = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    timezone: float = Form(...),
):
    place, jd, _, _ = _make_place_and_jd(date, time, latitude, longitude, timezone)
    hh, mm = [int(x) for x in time.split(":")[:2]]
    event_local_hours = hh + mm / 60.0

    sr = drik.sunrise(jd, place)
    sunrise_hours = sr[0]
    sunrise_label = sr[1]

    vaara_num = drik.vaara(jd, place)
    day_name = utils.DAYS_LIST[vaara_num] if 0 <= vaara_num < 7 else str(vaara_num)
    day_lord = WEEKDAY_LORD[vaara_num] if 0 <= vaara_num < 7 else "?"

    # Hours elapsed since sunrise (wrap to next-day if event is before sunrise,
    # treating pre-sunrise hours as belonging to the *previous* day's cycle).
    elapsed = event_local_hours - sunrise_hours
    if elapsed < 0:
        elapsed += 24.0
        prev_vaara = (vaara_num - 1) % 7
        day_name = utils.DAYS_LIST[prev_vaara] + " (previous sunrise)"
        day_lord = WEEKDAY_LORD[prev_vaara]

    hora_index = int(elapsed) + 1  # 1-based
    if hora_index > 24:
        hora_index = 24

    # Step `hora_index - 1` places forward in HORA_ORDER, starting at day_lord.
    try:
        start_pos = HORA_ORDER.index(day_lord)
    except ValueError:
        start_pos = 0
    lord_pos = (start_pos + hora_index - 1) % 7
    hora_lord = HORA_ORDER[lord_pos]

    sequence = []
    for i in range(24):
        pos = (start_pos + i) % 7
        sequence.append({"hora": i + 1, "lord": HORA_ORDER[pos], "is_current": (i + 1) == hora_index})

    return JSONResponse({
        "sunrise": sunrise_label,
        "weekday": day_name,
        "weekday_lord": day_lord,
        "event_time": f"{hh:02d}:{mm:02d}",
        "elapsed_hours": round(elapsed, 3),
        "hora_index": hora_index,
        "hora_lord": hora_lord,
        "hora_order": HORA_ORDER,
        "sequence": sequence,
    })


# Sanskrit lunar month names, indexed 1..12 (drik.lunar_month returns 1-based).
# The name is decided by the rasi in which the month's opening Sun-Moon conjunction
# falls (book Ch 1.3.9, Table 4). drik.lunar_month maps (this_solar_month+1)%12 + 1,
# so month 1 = Chaitra ↔ conjunction in Pisces (solar_month=11).
LUNAR_MONTH_NAMES = [
    "Chaitra", "Vaisaakha", "Jyeshtha", "Aashaadha", "Sraavana", "Bhaadrapada",
    "Aaswayuja", "Kaarteeka", "Maargasira", "Pushya", "Maagha", "Phaalguna",
]
LUNAR_MONTH_FULLMOON_NAK = [
    "Chitra", "Visaakha", "Jyeshtha", "Poorva/Uttara Aashaadha", "Sravana",
    "Poorva/Uttara Bhadrapada", "Aswini", "Krittika", "Mrigasira", "Pushyami",
    "Makha", "Poorva/Uttara Phalguni",
]
LUNAR_MONTH_CONJ_RASI = [
    "Pisces", "Aries", "Taurus", "Gemini", "Cancer", "Leo",
    "Virgo", "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius",
]


@app.post("/api/lunar_month")
async def lunar_month_api(
    date: str = Form(...),
    time: str = Form("12:00"),
    latitude: float = Form(...),
    longitude: float = Form(...),
    timezone: float = Form(...),
):
    place, jd, _, _ = _make_place_and_jd(date, time, latitude, longitude, timezone)
    lm = drik.lunar_month(jd, place)
    month_num, is_adhika = lm[0], bool(lm[1])
    idx = month_num - 1 if 1 <= month_num <= 12 else 0

    tithi_info = drik.tithi(jd, place)
    tithi_num = tithi_info[0]
    tithi_name = utils.TITHI_LIST[tithi_num - 1] if tithi_num and tithi_num <= len(utils.TITHI_LIST) else str(tithi_num)
    paksha_idx = 0 if tithi_num <= 15 else 1
    paksha_name = utils.PAKSHA_LIST[paksha_idx]

    return JSONResponse({
        "month_number": month_num,
        "month_name": LUNAR_MONTH_NAMES[idx],
        "is_adhika": is_adhika,
        "conjunction_rasi": LUNAR_MONTH_CONJ_RASI[idx],
        "full_moon_nakshatra": LUNAR_MONTH_FULLMOON_NAK[idx],
        "tithi_number": tithi_num,
        "tithi_name": tithi_name,
        "paksha": paksha_name,
        "month_table": [
            {
                "number": i + 1,
                "name": LUNAR_MONTH_NAMES[i],
                "conjunction_rasi": LUNAR_MONTH_CONJ_RASI[i],
                "full_moon_nakshatra": LUNAR_MONTH_FULLMOON_NAK[i],
                "is_current": (i + 1) == month_num,
            }
            for i in range(12)
        ],
    })


# Tithi lord cycle (Ch 1.3.8 Table 3): 8 lords, repeating every 8 tithis.
TITHI_LORDS_CYCLE = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu"]


@app.post("/api/tithi_view")
async def tithi_view(
    date: str = Form(...),
    time: str = Form("12:00"),
    latitude: float = Form(...),
    longitude: float = Form(...),
    timezone: float = Form(...),
    ayanamsa: Optional[str] = Form(None),
):
    _apply_ayanamsa(ayanamsa)
    place, jd, _, _ = _make_place_and_jd(date, time, latitude, longitude, timezone)
    rasi = charts.rasi_chart(jd, place)
    # rasi = [['L', (sign, deg)], [0, (sign, deg)], [1, (sign, deg)], ...]
    sun_sign, sun_deg = rasi[1][1]
    moon_sign, moon_deg = rasi[2][1]
    sun_lon = sun_sign * 30.0 + sun_deg
    moon_lon = moon_sign * 30.0 + moon_deg
    diff = (moon_lon - sun_lon) % 360.0

    tithi_num = int(diff // 12) + 1
    if tithi_num > 30:
        tithi_num = 30
    tithi_progress = (diff - (tithi_num - 1) * 12.0) / 12.0  # 0..1 within current tithi
    paksha = "Sukla Paksha" if tithi_num <= 15 else "Krishna Paksha"
    paksha_index = tithi_num if tithi_num <= 15 else (tithi_num - 15)

    tithi_name = utils.TITHI_LIST[tithi_num - 1] if tithi_num <= len(utils.TITHI_LIST) else str(tithi_num)
    lord = TITHI_LORDS_CYCLE[(tithi_num - 1) % 8]

    all_tithis = []
    for i in range(1, 31):
        nm = utils.TITHI_LIST[i - 1] if i <= len(utils.TITHI_LIST) else str(i)
        all_tithis.append({
            "number": i,
            "name": nm,
            "paksha": "Sukla" if i <= 15 else "Krishna",
            "lord": TITHI_LORDS_CYCLE[(i - 1) % 8],
            "is_current": i == tithi_num,
        })

    return JSONResponse({
        "tithi_number": tithi_num,
        "tithi_name": tithi_name,
        "tithi_progress": round(tithi_progress, 4),
        "tithi_lord": lord,
        "paksha": paksha,
        "paksha_day": paksha_index,
        "sun_longitude": round(sun_lon, 4),
        "moon_longitude": round(moon_lon, 4),
        "moon_minus_sun": round(diff, 4),
        "all_tithis": all_tithis,
    })


# Yoga meanings (Ch 1.3.9 Table 5). YOGAM_LIST in utils has the (Sanskrit) names;
# this map provides the plain-English meaning for the UI.
YOGA_MEANINGS = [
    "Door bolt/supporting pillar", "Love/affection", "Long-lived",
    "Long life of spouse (good fortune)", "Splendid, bright", "Great danger",
    "One with good deeds", "Firmness", "Shiva's weapon of destruction (pain)",
    "Danger", "Growth", "Fixed, constant", "Great blow", "Cheerful",
    "Diamond (strong)", "Accomplishment", "Great fall", "Chief/best",
    "Obstacle/hindrance", "Lord Shiva (purity)", "Accomplished/ready",
    "Possible", "Auspicious", "White, bright", "Creator (good knowledge and purity)",
    "Ruler of gods", "A class of gods",
]
# 11 canonical karana names (Ch 1.3.10). Karanas 1..7 repeat 8× through the month;
# karanas 8..11 each come once at month-end / new-moon.
KARANA_NAMES = [
    "Bava", "Balava", "Kaulava", "Taitula", "Garija", "Vanija", "Vishti (Bhadra)",
    "Sakuna", "Chatushpada", "Naga", "Kimstughna",
]
KARANA_NATURES = {
    "Bava": "mobile (chara) — good for movement",
    "Balava": "stable (sthira) — good for stable work",
    "Kaulava": "mixed — moderate",
    "Taitula": "mixed — fair",
    "Garija": "mixed — moderate",
    "Vanija": "mixed — trade/commerce favoured",
    "Vishti (Bhadra)": "fixed — avoid for auspicious starts",
    "Sakuna": "fixed — medicinal/remedial work",
    "Chatushpada": "fixed — cattle/quadruped work",
    "Naga": "fixed — inauspicious for most starts",
    "Kimstughna": "fixed — good only for specific rites",
}


@app.post("/api/yoga_karana")
async def yoga_karana_api(
    date: str = Form(...),
    time: str = Form("12:00"),
    latitude: float = Form(...),
    longitude: float = Form(...),
    timezone: float = Form(...),
):
    place, jd, _, _ = _make_place_and_jd(date, time, latitude, longitude, timezone)

    yog = drik.yogam(jd, place)
    yoga_num = yog[0]
    yoga_name = utils.YOGAM_LIST[yoga_num - 1] if yoga_num and yoga_num <= len(utils.YOGAM_LIST) else str(yoga_num)
    yoga_meaning = YOGA_MEANINGS[yoga_num - 1] if yoga_num and yoga_num <= len(YOGA_MEANINGS) else ""

    kar = drik.karana(jd, place)
    kar_slot = kar[0]  # 1..60 position within the lunar month
    # Map 60-slot index to canonical 11-name index (per the book Ch 1.3.10 rule).
    # Slot 1 = Kimstughna (2nd half of tithi 1).
    # Slots 2..57 = 56 karanas that are the 7 moving karanas (Bava..Vishti) × 8 cycles.
    # Slots 58, 59, 60 = Sakuna, Chatushpada, Naga (the 3 fixed karanas at month end).
    # Actually canonical: slot 1 = Kimstughna, slots 2..57 alternate through Bava..Vishti,
    # slots 58..60 = Sakuna, Chatushpada, Naga.
    if kar_slot == 1:
        kar_canonical = "Kimstughna"
        kar_canon_idx = 11
    elif 2 <= kar_slot <= 57:
        mov_idx = (kar_slot - 2) % 7  # 0..6
        kar_canonical = KARANA_NAMES[mov_idx]
        kar_canon_idx = mov_idx + 1
    elif kar_slot == 58:
        kar_canonical = "Sakuna";       kar_canon_idx = 8
    elif kar_slot == 59:
        kar_canonical = "Chatushpada";  kar_canon_idx = 9
    else:
        kar_canonical = "Naga";         kar_canon_idx = 10

    yoga_table = [
        {"number": i + 1, "name": utils.YOGAM_LIST[i] if i < len(utils.YOGAM_LIST) else str(i + 1),
         "meaning": YOGA_MEANINGS[i] if i < len(YOGA_MEANINGS) else "",
         "is_current": (i + 1) == yoga_num}
        for i in range(27)
    ]
    karana_table = [
        {"number": i + 1, "name": KARANA_NAMES[i], "nature": KARANA_NATURES[KARANA_NAMES[i]],
         "is_current": (i + 1) == kar_canon_idx}
        for i in range(11)
    ]

    return JSONResponse({
        "yoga": {"number": yoga_num, "name": yoga_name, "meaning": yoga_meaning},
        "karana": {"slot": kar_slot, "canonical_number": kar_canon_idx,
                   "name": kar_canonical, "nature": KARANA_NATURES.get(kar_canonical, "")},
        "yoga_table": yoga_table,
        "karana_table": karana_table,
    })


@app.post("/api/chart")
async def chart(
    date: str = Form(...),
    time: str = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    timezone: float = Form(...),
    ayanamsa: Optional[str] = Form(None),
):
    mode = _apply_ayanamsa(ayanamsa)
    place, jd, _, _ = _make_place_and_jd(date, time, latitude, longitude, timezone)
    rasi = charts.rasi_chart(jd, place)
    rasi_names = utils.RAASI_LIST
    ascendant_sign, houses = _houses_from_varga_rows(rasi_names, rasi)
    return JSONResponse({
        "ayanamsa": mode,
        "ascendant_sign": ascendant_sign,
        "ascendant_sign_name": rasi_names[ascendant_sign] if ascendant_sign is not None else None,
        "houses": houses,
    })


@app.get("/api/varga_list")
async def varga_list():
    return {"factors": [{"factor": f, "label": lbl} for f, lbl in VARGA_FACTORS]}


@app.post("/api/varga")
async def varga(
    date: str = Form(...),
    time: str = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    timezone: float = Form(...),
    factor: int = Form(9),
    ayanamsa: Optional[str] = Form(None),
):
    mode = _apply_ayanamsa(ayanamsa)
    place, jd, _, _ = _make_place_and_jd(date, time, latitude, longitude, timezone)
    rasi_names = utils.RAASI_LIST
    if factor == 1:
        rows = charts.rasi_chart(jd, place)
    else:
        rows = charts.divisional_chart(jd, place, divisional_chart_factor=factor)
    ascendant_sign, houses = _houses_from_varga_rows(rasi_names, rows)
    label = next((lbl for f, lbl in VARGA_FACTORS if f == factor), f"D-{factor}")
    return JSONResponse({
        "ayanamsa": mode,
        "factor": factor,
        "label": label,
        "ascendant_sign": ascendant_sign,
        "ascendant_sign_name": rasi_names[ascendant_sign] if ascendant_sign is not None else None,
        "houses": houses,
    })


@app.post("/api/bhava")
async def bhava(
    date: str = Form(...),
    time: str = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    timezone: float = Form(...),
    ayanamsa: Optional[str] = Form(None),
):
    _apply_ayanamsa(ayanamsa)
    place, jd, _, _ = _make_place_and_jd(date, time, latitude, longitude, timezone)
    rasi_names = utils.RAASI_LIST
    bhava_rows = charts.bhava_chart(jd, place)

    def _sign_label(deg: float):
        d = deg % 360.0
        idx = int(d // 30)
        return idx, rasi_names[idx], d - idx * 30

    houses_out = []
    for idx, row in enumerate(bhava_rows):
        _start_sign_idx, (start_deg, mid_deg, end_deg), planet_tokens = row
        s_idx, s_name, s_off = _sign_label(start_deg)
        m_idx, m_name, m_off = _sign_label(mid_deg)
        e_idx, e_name, e_off = _sign_label(end_deg)
        houses_out.append({
            "house": idx + 1,
            "start": {"sign_index": s_idx, "sign": s_name, "deg": _deg_to_dms(s_off), "abs_deg": round(start_deg, 4)},
            "mid":   {"sign_index": m_idx, "sign": m_name, "deg": _deg_to_dms(m_off), "abs_deg": round(mid_deg, 4)},
            "end":   {"sign_index": e_idx, "sign": e_name, "deg": _deg_to_dms(e_off), "abs_deg": round(end_deg, 4)},
            "planets": [_token_to_name(t) for t in planet_tokens],
        })
    return JSONResponse({"houses": houses_out})


def _fmt_dasha_date(date_tuple) -> str:
    y, m, d, hr = date_tuple
    hours = int(hr)
    minutes = int(round((hr - hours) * 60))
    if minutes == 60:
        hours += 1
        minutes = 0
    return f"{y:04d}-{m:02d}-{d:02d} {hours:02d}:{minutes:02d}"


@app.post("/api/dasha")
async def dasha(
    date: str = Form(...),
    time: str = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    timezone: float = Form(...),
    level: int = Form(1),
    ayanamsa: Optional[str] = Form(None),
):
    _apply_ayanamsa(ayanamsa)
    place, jd, _, _ = _make_place_and_jd(date, time, latitude, longitude, timezone)
    level = max(1, min(int(level), 4))
    md_result = vimsottari.get_vimsottari_dhasa_bhukthi(jd, place, dhasa_level_index=1)
    balance = md_result[0]
    balance_years = balance[0] + balance[1] / 12.0 + balance[2] / 365.25

    ad_by_md = {}
    pd_by_md_ad = {}
    sd_by_md_ad_pd = {}
    if level >= 2:
        ad_result = vimsottari.get_vimsottari_dhasa_bhukthi(jd, place, dhasa_level_index=2)
        for entry in ad_result[1]:
            lords = entry[0]
            md_lord = lords[0]
            ad_by_md.setdefault(md_lord, []).append({
                "lord": _token_to_name(lords[1]),
                "lord_id": lords[1],
                "start": _fmt_dasha_date(entry[1]),
                "duration_years": round(entry[2], 4),
            })
    if level >= 3:
        pd_result = vimsottari.get_vimsottari_dhasa_bhukthi(jd, place, dhasa_level_index=3)
        for entry in pd_result[1]:
            lords = entry[0]
            key = (lords[0], lords[1])
            pd_by_md_ad.setdefault(key, []).append({
                "lord": _token_to_name(lords[2]),
                "lord_id": lords[2],
                "start": _fmt_dasha_date(entry[1]),
                "duration_years": round(entry[2], 5),
            })
    if level >= 4:
        sd_result = vimsottari.get_vimsottari_dhasa_bhukthi(jd, place, dhasa_level_index=4)
        for entry in sd_result[1]:
            lords = entry[0]
            key = (lords[0], lords[1], lords[2])
            sd_by_md_ad_pd.setdefault(key, []).append({
                "lord": _token_to_name(lords[3]),
                "lord_id": lords[3],
                "start": _fmt_dasha_date(entry[1]),
                "duration_years": round(entry[2], 6),
            })

    periods = []
    for entry in md_result[1]:
        lords = entry[0]
        md_lord = lords[0]
        lord_names = [_token_to_name(l) for l in lords]
        row = {
            "lord": " / ".join(lord_names),
            "lord_ids": list(lords),
            "start": _fmt_dasha_date(entry[1]),
            "duration_years": round(entry[2], 3),
        }
        if level >= 2:
            ads = ad_by_md.get(md_lord, [])
            if level >= 3:
                for ad in ads:
                    pds = pd_by_md_ad.get((md_lord, ad["lord_id"]), [])
                    if level >= 4:
                        for pd in pds:
                            pd["sookshmadashas"] = sd_by_md_ad_pd.get(
                                (md_lord, ad["lord_id"], pd["lord_id"]), []
                            )
                    ad["pratyantardashas"] = pds
            row["antardashas"] = ads
        periods.append(row)
    return JSONResponse({
        "level": level,
        "balance": {
            "years": balance[0],
            "months": balance[1],
            "days": balance[2],
            "total_years": round(balance_years, 3),
        },
        "periods": periods,
    })


@app.post("/api/life_chart")
async def life_chart_endpoint(
    date: str = Form(...),
    time: str = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    timezone: float = Form(...),
    years: int = Form(100),
    slice_days: int = Form(30),
    ayanamsa: Optional[str] = Form(None),
    name: Optional[str] = Form(None),
):
    _apply_ayanamsa(ayanamsa)
    place, jd, _, _ = _make_place_and_jd(date, time, latitude, longitude, timezone)
    years = max(10, min(int(years), 120))
    slice_days = max(7, min(int(slice_days), 90))
    timeline = life_chart.build_timeline(jd, place, years=years, slice_days=slice_days)
    subject = f"{name or 'Subject'} · {date} {time}"
    svg = life_chart.render_svg(timeline, subject=subject)
    compact = [
        [s["md"], s["ad"], s["marriage"], s["career"], s["finance"], s["key"]]
        for s in timeline["slices"]
    ]
    return JSONResponse({
        "svg": svg,
        "slice_count": len(timeline["slices"]),
        "slice_days": slice_days,
        "slices": compact,
        "planet_labels": ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"],
        "explanations": timeline["explanations"],
        "natal": life_chart.natal_summary(timeline["natal"]),
    })


@app.get("/api/autosave")
async def get_autosave():
    row = db.get_profile(db.AUTOSAVE_KEY)
    return {"profile": row}


@app.post("/api/autosave")
async def set_autosave(
    name: str = Form(""),
    gender: str = Form(""),
    date: str = Form(""),
    time: str = Form(""),
    city: str = Form(""),
    latitude: str = Form(""),
    longitude: str = Form(""),
    timezone: str = Form(""),
):
    row = db.upsert_profile(db.AUTOSAVE_KEY, {
        "name": name, "gender": gender, "date": date, "time": time,
        "city": city, "latitude": latitude, "longitude": longitude, "timezone": timezone,
    })
    return {"ok": True, "profile": row}


@app.get("/api/profiles")
async def profiles_list():
    return {"profiles": db.list_profiles()}


@app.post("/api/profiles")
async def profiles_save(
    label: str = Form(...),
    name: str = Form(""),
    gender: str = Form(""),
    date: str = Form(""),
    time: str = Form(""),
    city: str = Form(""),
    latitude: str = Form(""),
    longitude: str = Form(""),
    timezone: str = Form(""),
):
    label = label.strip()
    if not label or label == db.AUTOSAVE_KEY:
        return JSONResponse({"error": "Invalid profile label"}, status_code=400)
    row = db.upsert_profile(label, {
        "name": name, "gender": gender, "date": date, "time": time,
        "city": city, "latitude": latitude, "longitude": longitude, "timezone": timezone,
    })
    return {"ok": True, "profile": row}


@app.get("/api/profiles/{profile_id}")
async def profiles_get(profile_id: int):
    row = db.get_profile_by_id(profile_id)
    if not row or row["label"] == db.AUTOSAVE_KEY:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return {"profile": row}


@app.delete("/api/profiles/{profile_id}")
async def profiles_delete(profile_id: int):
    ok = db.delete_profile(profile_id)
    if not ok:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web.main:app", host="0.0.0.0", port=8000, reload=False)

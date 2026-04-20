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

utils.get_resource_lists()
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


@app.post("/api/panchangam")
async def panchangam(
    date: str = Form(...),
    time: str = Form("12:00"),
    latitude: float = Form(50.3569),
    longitude: float = Form(7.5890),
    timezone: float = Form(1.0),
):
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


@app.post("/api/chart")
async def chart(
    date: str = Form(...),
    time: str = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    timezone: float = Form(...),
):
    place, jd, _, _ = _make_place_and_jd(date, time, latitude, longitude, timezone)
    rasi = charts.rasi_chart(jd, place)
    rasi_names = utils.RAASI_LIST
    ascendant_sign, houses = _houses_from_varga_rows(rasi_names, rasi)
    return JSONResponse({
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
):
    place, jd, _, _ = _make_place_and_jd(date, time, latitude, longitude, timezone)
    rasi_names = utils.RAASI_LIST
    if factor == 1:
        rows = charts.rasi_chart(jd, place)
    else:
        rows = charts.divisional_chart(jd, place, divisional_chart_factor=factor)
    ascendant_sign, houses = _houses_from_varga_rows(rasi_names, rows)
    label = next((lbl for f, lbl in VARGA_FACTORS if f == factor), f"D-{factor}")
    return JSONResponse({
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
):
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
):
    place, jd, _, _ = _make_place_and_jd(date, time, latitude, longitude, timezone)
    level = max(1, min(int(level), 2))
    vim = vimsottari.get_vimsottari_dhasa_bhukthi(jd, place, dhasa_level_index=level)
    balance = vim[0]
    balance_years = balance[0] + balance[1] / 12.0 + balance[2] / 365.25

    periods = []
    for entry in vim[1]:
        lords = entry[0]
        start_tuple = entry[1]
        dur_years = entry[2]
        lord_names = [_token_to_name(l) for l in lords]
        periods.append({
            "lord": " / ".join(lord_names),
            "lord_ids": list(lords),
            "start": _fmt_dasha_date(start_tuple),
            "duration_years": round(dur_years, 3),
        })
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web.main:app", host="0.0.0.0", port=8000, reload=False)

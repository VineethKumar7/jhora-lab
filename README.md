jhora-lab
=========

An interactive web playground for learning **Vedic astrology fundamentals**,
built on top of the [PyJHora](https://github.com/naturalstupid/PyJHora) library.

Enter birth/event details once and the app gives you a full panchangam, a
D-1…D-60 chart grid, Vimshottari Dasha drilled down to Sookshma-dasha,
a zoomable life-chart timeline, plus ten learning tools derived from
**Chapter 1 of "Vedic Astrology — An Integrated Approach" (P.V.R. Narasimha
Rao)**. Everything runs locally — FastAPI backend, Tailwind + vanilla-JS
frontend.

---

## Features

### Charts & classical tools
- **Panchangam** — tithi, vaara, nakshatra, yoga, karana, sunrise/sunset, rahu-/yama-/gulika-kala for any date/place.
- **Rasi & divisional charts** — the full D-1…D-60 varga stack. Switch between **South / North / East Indian** chart styles with one click.
- **Bhava chart** — house-based (as opposed to sign-based) view with per-house lords and bhava madhya.
- **Dasha** — Vimshottari mahadasha → antardasha → pratyantar → sookshma, expandable inline.
- **Life chart** — zoomable timeline that overlays dasha periods with transit (gochara) events.

### Chapter 1 learning toolkit
| # | Feature | Book ref | What it does |
|---|---------|----------|--------------|
| 1 | **Longitude lookup** | Ex. 1 | Parse any longitude (`94.316°`, `25 Li 31`, `5s 17° 45'`) → rasi, nakshatra, pada, Vimshottari lord, deity. |
| 2 | **Multi-reference houses** | Ex. 2 | Re-index the 12 houses from any chosen reference planet. |
| 3 | **Chart style toggle** | — | Live South / North / East Indian rendering for every varga. |
| 4 | **Hora of the hour** | 1.3.11 | "Who rules this clock-hour?" — sunrise-anchored `Sat→Jup→Mars→Sun→Ven→Mer→Moon` cycle. |
| 5 | **Lunar month namer** | 1.3.8.2 | Sun-Moon conjunction rasi → Chaitra / Vaisakha / …, with the matching full-moon nakshatra. |
| 6 | **Tithi / Paksha visualizer** | 1.3.8 | Moon-phase SVG (waxing/waning), current tithi with lord, full 30-tithi strip with Sukla / Krishna split. |
| 7 | **Yoga + Karana of the day** | 1.3.9–10 | Current yoga with plain-English meaning, current karana (canonical + 60-slot index), full 27-yoga / 11-karana tables. |
| 8 | **Panchaanga muhurta card** | 1.3.12 | Five-limb verdict (good / neutral / avoid) with an overall "is this moment auspicious?" banner. |
| 9 | **Solar calendar counter** | 1.3.7 | Sidereal solar month & day-of-month (1..30), day-of-year (1..360), year-progress bar, precise sankranti timestamps. |
| 10 | **Practice quiz** | — | Auto-generated MCQs drawn from the Ch 1 tables — nakshatra lords, deities, rasi ordinals, longitude→rasi, tithi lord, paksha, pada arc, hora lord, solar-year facts. Score and explanation on every answer. |

---

## Quick start

```bash
git clone https://github.com/VineethKumar7/jhora-lab.git
cd jhora-lab
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
./run.sh web          # starts on http://127.0.0.1:8000
```

First load asks for birth/event details; after that every tab pulls from the
same subject line. Profiles autosave to a local SQLite DB (`web/data/app.db`).

### Configuration

- **Ayanamsa** — default `LAHIRI`, switchable from the nav bar (Lahiri, KP, Raman, Yukteshwar, True-Citra, SuryaSiddhanta, …).
- **Ephemeris** — uses Swiss Ephemeris via the bundled PyJHora data files under `src/jhora/data/ephe`.

---

## Project layout

```
web/
  main.py          FastAPI app — all /api/* endpoints
  basics.py        Ch 1 longitude parsing + nakshatra/rasi tables
  life_chart.py    Gochara overlay + timeline math
  db.py            SQLite profile store
  templates/       Jinja + Tailwind UI (single-page, tab-based)
  static/          JS helpers, icons
src/jhora/         Vendored PyJHora library (unmodified)
docs/book/         Chapter-by-chapter reference notes
```

All additions live in `web/`; the `jhora` package itself is left untouched
so the upstream test suite (`jhora.tests.pvr_tests`, ~6800 tests) continues
to pass unchanged.

---

## Credits

Core astrology math (panchanga, charts, dashas, Swiss-ephemeris bindings) is
provided by the [**PyJHora**](https://github.com/naturalstupid/PyJHora)
library by [naturalstupid](https://github.com/naturalstupid). If you find the
underlying calculations useful, please star that repo.

Everything in `web/` and this README is work specific to **jhora-lab**.

## License

Distributed under the same [GNU AGPL v3.0](./LICENSE) as the PyJHora
library. Any modified version served over a network must provide source to
its users; the web app in this repo satisfies that requirement for its own
modifications.

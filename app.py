import math
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, unquote
from typing import Optional, Dict, Any, List

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from zoneinfo import ZoneInfo  # Europe/Warsaw
from skyfield.api import EarthSatellite, load, wgs84

app = FastAPI()

# -------------------- KONFIG --------------------
HOME_LAT = 52.158026399080114
HOME_LON = 21.55857732726421

# minimalna wysokość nad horyzontem (w stopniach), żeby uznać "przelot"
MIN_ELEV_DEG = 10.0

ISS_ORBIT_MINUTES = 92
ISS_TYPICAL_ALT_KM = 420

WARSAW_TZ = ZoneInfo("Europe/Warsaw")

# Ludzie w kosmosie (bogate API)
PEOPLE_URL = "https://corquaid.github.io/international-space-station-APIs/JSON/people-in-space.json"

# TLE ISS (do obliczania przelotów)
TLE_URL = "https://api.wheretheiss.at/v1/satellites/25544/tles"
TLE_TTL_SECONDS = 6 * 3600  # cache na 6h

# -------------------- STAN (w pamięci procesu) --------------------
_last_fix: Optional[Dict[str, Any]] = None  # {"lat": float, "lon": float, "t": int}
_tle_cache: Dict[str, Any] = {"ts": 0, "name": None, "line1": None, "line2": None}


# -------------------- HELPERY --------------------
def fetch_json(url: str, timeout: int = 12) -> Dict[str, Any]:
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "ISS-demo/1.0 (educational)"})
    r.raise_for_status()
    return r.json()


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def fetch_iss_position_open_notify():
    # serwer->serwer, więc HTTP nie przeszkadza
    data = fetch_json("http://api.open-notify.org/iss-now.json")
    lat = float(data["iss_position"]["latitude"])
    lon = float(data["iss_position"]["longitude"])
    ts = int(data["timestamp"])
    return lat, lon, ts


def get_people_data():
    return fetch_json(PEOPLE_URL)


def get_tle():
    now = int(time.time())
    if _tle_cache["line1"] and (now - _tle_cache["ts"] < TLE_TTL_SECONDS):
        return _tle_cache["name"], _tle_cache["line1"], _tle_cache["line2"]

    data = fetch_json(TLE_URL)
    name = data.get("name") or "ISS (ZARYA)"
    line1 = data.get("line1")
    line2 = data.get("line2")
    if not (line1 and line2):
        raise HTTPException(502, "Nie udało się pobrać TLE dla ISS")

    _tle_cache.update({"ts": now, "name": name, "line1": line1, "line2": line2})
    return name, line1, line2


def wiki_title_from_url(url: str) -> Optional[str]:
    """
    https://en.wikipedia.org/wiki/Wu_Fei_(taikonaut) -> Wu_Fei_(taikonaut)
    """
    try:
        path = urlparse(url).path
        if not path.startswith("/wiki/"):
            return None
        return unquote(path[len("/wiki/"):])
    except Exception:
        return None


def wiki_pl_summary_by_title(title: str) -> Dict[str, Any]:
    encoded = urllib.parse.quote(title, safe="")
    url = f"https://pl.wikipedia.org/api/rest_v1/page/summary/{encoded}"
    try:
        data = fetch_json(url, timeout=10)
        return {
            "ok": True,
            "title": data.get("title"),
            "extract": data.get("extract"),
            "thumbnail": (data.get("thumbnail") or {}).get("source"),
            "content_url": (data.get("content_urls") or {}).get("desktop", {}).get("page"),
        }
    except Exception:
        return {"ok": False}


def wiki_pl_title_from_en_title(en_title: str) -> Optional[str]:
    """
    MediaWiki langlinks: EN title -> PL title (jeśli istnieje)
    """
    api = "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "format": "json",
        "titles": en_title,
        "prop": "langlinks",
        "lllang": "pl",
        "lllimit": "1",
    }
    try:
        r = requests.get(api, params=params, timeout=10, headers={"User-Agent": "ISS-demo/1.0"})
        r.raise_for_status()
        data = r.json()
        pages = (data.get("query") or {}).get("pages") or {}
        for _, page in pages.items():
            ll = page.get("langlinks")
            if ll and isinstance(ll, list) and len(ll) > 0:
                return ll[0].get("*") or ll[0].get("title")
        return None
    except Exception:
        return None


def dumb_down_pl(
    name: str,
    country: Optional[str],
    agency: Optional[str],
    position: Optional[str],
    spacecraft: Optional[str],
    extract: Optional[str],
) -> str:
    bits = [f"{name} przebywa obecnie w kosmosie."]
    if agency:
        bits.append(f"Pracuje w agencji: {agency}.")
    if country:
        bits.append(f"Pochodzi z kraju: {country}.")
    if position:
        bits.append(f"Rola na misji: {position}.")
    if spacecraft:
        bits.append(f"Leci statkiem/modułem: {spacecraft}.")
    if extract:
        short = extract.strip()
        if len(short) > 420:
            short = short[:420].rsplit(" ", 1)[0] + "…"
        bits.append(short)
    return " ".join(bits)


def az_to_cardinal_pl(az_deg: float) -> str:
    """
    8-kierunkowy opis po polsku: północ/wschód/...
    """
    dirs = ["północy", "północnego wschodu", "wschodu", "południowego wschodu",
            "południa", "południowego zachodu", "zachodu", "północnego zachodu"]
    idx = int((az_deg % 360) / 45.0 + 0.5) % 8
    return dirs[idx]


# -------------------- ENDPOINTY --------------------
@app.get("/api/status")
def api_status():
    global _last_fix

    lat, lon, ts = fetch_iss_position_open_notify()
    people_data = get_people_data()
    people_count = int(people_data.get("number", 0))

    speed_kmh = None
    if _last_fix:
        dt = ts - _last_fix["t"]
        if dt > 0:
            dist = haversine_km(_last_fix["lat"], _last_fix["lon"], lat, lon)
            speed_kmh = (dist / dt) * 3600.0

    _last_fix = {"lat": lat, "lon": lon, "t": ts}

    return {
        "iss": {"latitude": lat, "longitude": lon, "timestamp": ts, "speed_kmh": speed_kmh},
        "people_in_space": people_count,
        "facts": {
            "iss_orbit_minutes": ISS_ORBIT_MINUTES,
            "iss_typical_altitude_km": ISS_TYPICAL_ALT_KM,
        },
        "home": {"lat": HOME_LAT, "lon": HOME_LON},
    }


@app.get("/api/people")
def api_people():
    data = get_people_data()
    people = data.get("people", [])
    slim = []
    for p in people:
        slim.append(
            {
                "id": p.get("id"),
                "name": p.get("name"),
                "country": p.get("country"),
                "agency": p.get("agency"),
                "position": p.get("position"),
                "spacecraft": p.get("spacecraft"),
                "image": p.get("image"),
                "url": p.get("url"),
            }
        )
    return {
        "number": data.get("number"),
        "people": slim,
        "iss_expedition": data.get("iss_expedition"),
        "expedition_patch": data.get("expedition_patch"),
    }


@app.get("/api/person/{person_id}")
def api_person(person_id: int):
    data = get_people_data()
    people = data.get("people", [])
    p = next((x for x in people if x.get("id") == person_id), None)
    if not p:
        raise HTTPException(404, "Nie znaleziono takiej osoby")

    name = p.get("name") or "Nieznana osoba"
    country = p.get("country")
    agency = p.get("agency")
    position = p.get("position")
    spacecraft = p.get("spacecraft")

    wiki_url = p.get("url")  # <-- używamy tego, jak człowiek
    image = p.get("image")

    wiki = {"ok": False, "link": wiki_url, "thumbnail": None, "extract": None}

    if wiki_url and "wikipedia.org/wiki/" in wiki_url:
        title = wiki_title_from_url(wiki_url)

        if title:
            # 1) spróbuj PL summary dla tego samego tytułu
            pl = wiki_pl_summary_by_title(title)
            if pl.get("ok"):
                wiki = {
                    "ok": True,
                    "link": pl.get("content_url") or wiki_url,
                    "thumbnail": pl.get("thumbnail"),
                    "extract": pl.get("extract"),
                }
            else:
                # 2) jeśli źródło EN, spróbuj znaleźć PL tytuł
                host = urlparse(wiki_url).netloc.lower()
                if host.startswith("en."):
                    pl_title = wiki_pl_title_from_en_title(title)
                    if pl_title:
                        pl2 = wiki_pl_summary_by_title(pl_title)
                        if pl2.get("ok"):
                            wiki = {
                                "ok": True,
                                "link": pl2.get("content_url") or wiki_url,
                                "thumbnail": pl2.get("thumbnail"),
                                "extract": pl2.get("extract"),
                            }
                        else:
                            wiki["link"] = f"https://pl.wikipedia.org/wiki/{urllib.parse.quote(pl_title, safe='')}"
                # jeśli nie EN: zostaje link z JSON-a jako fallback

    simple = dumb_down_pl(name, country, agency, position, spacecraft, wiki.get("extract"))

    return {
        "id": p.get("id"),
        "name": name,
        "country": country,
        "agency": agency,
        "position": position,
        "spacecraft": spacecraft,
        "image": image,
        "wiki": wiki,
        "simple_pl": simple,
    }


@app.get("/api/passes")
def api_passes():
    sat_name, l1, l2 = get_tle()
    ts = load.timescale()
    satellite = EarthSatellite(l1, l2, sat_name, ts)

    observer = wgs84.latlon(HOME_LAT, HOME_LON)

    start = datetime.now(timezone.utc)
    end = start + timedelta(days=2)  # 48h

    t0 = ts.from_datetime(start)
    t1 = ts.from_datetime(end)

    # events: 0=rise, 1=culminate, 2=set
    times, events = satellite.find_events(observer, t0, t1, altitude_degrees=MIN_ELEV_DEG)

    out: List[Dict[str, Any]] = []
    current: Dict[str, Any] = {}

    for t, e in zip(times, events):
        dt_utc = t.utc_datetime().replace(tzinfo=timezone.utc)

        if e == 0:
            current = {"start_t": t, "start_utc": dt_utc}
        elif e == 1 and current:
            alt, az, _dist = (satellite - observer).at(t).altaz()
            current["max_utc"] = dt_utc
            current["max_elev_deg"] = float(alt.degrees)
        elif e == 2 and current:
            current["end_t"] = t
            current["end_utc"] = dt_utc

            # kierunek: azymut na początku i na końcu
            start_az = (satellite - observer).at(current["start_t"]).altaz()[1].degrees
            end_az = (satellite - observer).at(current["end_t"]).altaz()[1].degrees

            start_dir = az_to_cardinal_pl(float(start_az))
            end_dir = az_to_cardinal_pl(float(end_az))

            # format dla taty
            start_pl = current["start_utc"].astimezone(WARSAW_TZ)
            end_pl = current["end_utc"].astimezone(WARSAW_TZ)
            date_str = start_pl.strftime("%d.%m")
            time_from = start_pl.strftime("%H:%M")
            time_to = end_pl.strftime("%H:%M")

            out.append(
                {
                    "date": date_str,
                    "time_from": time_from,
                    "time_to": time_to,
                    "direction": f"z {start_dir} na {end_dir}",
                    "max_elev_deg": round(current.get("max_elev_deg", 0.0), 1),
                }
            )
            current = {}

    return {
        "home": {"lat": HOME_LAT, "lon": HOME_LON},
        "min_elev_deg": MIN_ELEV_DEG,
        "passes": out[:10],
    }


# -------------------- FRONT --------------------
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index():
    return FileResponse("static/index.html")

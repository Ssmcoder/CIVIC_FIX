"""Location intelligence: landmark extraction, geocoding, ward resolution.

No external geocoder in the demo: we use a small gazetteer of Odisha/Khordha
landmarks plus GPS/manual coordinates. Everything ambiguous returns candidate
points with confidence — never a silent guess.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------- gazetteer
# (name, aliases, lat, lon, ward_hint)
GAZETTEER = [
    ("Engineering College Gate", ["engineering college", "college gate", "engg college", "college"], 20.2969, 85.8242, "Ward 12"),
    ("Main Market", ["main market", "market", "bazaar", "market entrance"], 20.3001, 85.8190, "Ward 12"),
    ("Railway Station", ["railway station", "train station", "station", "rail station"], 20.2560, 85.8440, "Ward 8"),
    ("Biju Patnaik Airport", ["airport", "biju patnaik"], 20.2440, 85.8170, "Ward 5"),
    ("Rajbhavan", ["rajbhavan", "governor house"], 20.3020, 85.8210, "Ward 12"),
    ("Lingaraj Temple", ["lingaraj", "temple", "lingaraj temple"], 20.3150, 85.8310, "Ward 18"),
    ("Master Canteen", ["master canteen", "canteen"], 20.3025, 85.8170, "Ward 12"),
    ("Bus Stand", ["bus stand", "bus station"], 20.2890, 85.8350, "Ward 10"),
    ("Khandagiri", ["khandagiri", "udayagiri", "khandagiri temple"], 20.2620, 85.8130, "Ward 6"),
    ("Marichi Hospital", ["marichi", "hospital", "marichi hospital"], 20.3070, 85.8290, "Ward 18"),
    ("NANDAN", ["nandan", "nandankanan"], 20.2750, 85.8150, "Ward 7"),
    ("Bhatia Park", ["bhatia park", "park"], 20.2920, 85.8060, "Ward 12"),
    ("Sanjivan Hospital", ["sanjivan", "sanjivan hospital"], 20.2990, 85.8310, "Ward 18"),
    ("Gole Bazar", ["gole bazar", "gole market"], 20.2940, 85.8230, "Ward 12"),
    ("Kalpana Square", ["kalpana square", "square"], 20.2960, 85.8160, "Ward 12"),
]

# Ward bounding boxes (approximate Bhubaneswar wards — demo data)
WARDS = {
    "Ward 5":  (20.230, 20.260, 85.800, 85.830),
    "Ward 6":  (20.250, 20.275, 85.800, 85.830),
    "Ward 7":  (20.265, 20.290, 85.800, 85.830),
    "Ward 8":  (20.245, 20.270, 85.830, 85.860),
    "Ward 10": (20.280, 20.305, 85.830, 85.860),
    "Ward 12": (20.290, 20.315, 85.810, 85.835),
    "Ward 18": (20.305, 20.330, 85.825, 85.855),
}


@dataclass
class LocationResult:
    lat: float | None
    lon: float | None
    landmark_text: str | None
    confidence: float
    verified: bool
    candidates: list[dict] = field(default_factory=list)
    ward_name: str | None = None
    method: str = "none"  # gps|manual_pin|landmark|geocode|none


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def extract_landmarks(text: str) -> list[str]:
    t = (text or "").lower()
    found = []
    for name, aliases, *_ in GAZETTEER:
        for alias in aliases:
            if alias in t:
                found.append(name)
                break
    return found


def resolve(text: str, lat: float | None = None, lon: float | None = None,
            manual_confirmed: bool = False) -> LocationResult:
    """Resolve a complaint location. Never guesses silently: ambiguous results
    return candidates with confidence and verified=False."""
    # 1. GPS/manual coordinates
    if lat is not None and lon is not None:
        ward = ward_for(lat, lon)
        if manual_confirmed:
            return LocationResult(lat, lon, None, 0.95, True, ward_name=ward, method="gps" if not manual_confirmed else "manual_pin")
        return LocationResult(lat, lon, None, 0.90, False, ward_name=ward, method="gps")

    # 2. Landmark extraction
    landmarks = extract_landmarks(text)
    if landmarks:
        cands = []
        for name in landmarks:
            for gname, aliases, glat, glon, gward in GAZETTEER:
                if gname == name:
                    cands.append({"name": gname, "lat": glat, "lon": glon, "ward": gward})
        if len(cands) == 1:
            c = cands[0]
            return LocationResult(c["lat"], c["lon"], c["name"], 0.75, False,
                                  candidates=cands, ward_name=c["ward"], method="landmark")
        return LocationResult(None, None, None, 0.30, False, candidates=cands,
                              method="landmark_ambiguous")

    # 3. Vague phrases -> candidate suggestions near default city centre
    vague = _vague_candidates(text)
    if vague:
        return LocationResult(None, None, None, 0.25, False, candidates=vague, method="vague")

    return LocationResult(None, None, None, 0.0, False, method="none")


def _vague_candidates(text: str) -> list[dict]:
    t = (text or "").lower()
    out = []
    if "railway" in t or "station" in t or "train" in t:
        out.append({"name": "Bhubaneswar Railway Station", "lat": 20.2560, "lon": 85.8440, "ward": "Ward 8"})
    if "market" in t:
        out.append({"name": "Main Market", "lat": 20.3001, "lon": 85.8190, "ward": "Ward 12"})
        out.append({"name": "Gole Bazar", "lat": 20.2940, "lon": 85.8230, "ward": "Ward 12"})
    if "college" in t or "school" in t or "university" in t:
        out.append({"name": "Engineering College Gate", "lat": 20.2969, "lon": 85.8242, "ward": "Ward 12"})
        out.append({"name": "Kendriya Vidyalaya Area", "lat": 20.2980, "lon": 85.8200, "ward": "Ward 12"})
    if "temple" in t or "mandir" in t:
        out.append({"name": "Lingaraj Temple", "lat": 20.3150, "lon": 85.8310, "ward": "Ward 18"})
    if "airport" in t:
        out.append({"name": "Biju Patnaik Airport", "lat": 20.2440, "lon": 85.8170, "ward": "Ward 5"})
    if "bus" in t and "stand" in t:
        out.append({"name": "Bus Stand", "lat": 20.2890, "lon": 85.8350, "ward": "Ward 10"})
    if "hospital" in t:
        out.append({"name": "AIIMS Bhubaneswar", "lat": 20.2920, "lon": 85.8260, "ward": "Ward 12"})
        out.append({"name": "Sanjivan Hospital", "lat": 20.2990, "lon": 85.8310, "ward": "Ward 18"})
    return out


def ward_for(lat: float, lon: float) -> str | None:
    for name, (minla, maxla, minlo, maxlo) in WARDS.items():
        if minla <= lat <= maxla and minlo <= lon <= maxlo:
            return name
    return None

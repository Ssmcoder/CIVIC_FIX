"""Shared constants: categories, statuses, priority bands, languages."""

CATEGORIES = {
    "roads": "Roads (potholes, broken roads)",
    "waste": "Waste (garbage overflow, missed collection)",
    "drainage": "Drainage (blocked drains, waterlogging)",
    "water": "Water supply (leakage, no water)",
    "electricity": "Electricity (streetlights, poles, wires)",
    "public_safety": "Public safety (exposed wires, dangerous infrastructure)",
    "other": "Other municipal issue",
}

ISSUE_KEYWORDS = {
    "roads": ["pothole", "road", "street", "asphalt", "crack", "hole", "broken road",
              "speed breaker", "footpath", "koliba", "sadak", "galli"],
    "waste": ["garbage", "waste", "trash", "dustbin", "rubbish", "kacha", "safai",
              "dumpster", "overflowing bin", "swachh"],
    "drainage": ["drain", "drainage", "sewage", "blocked", "choked", "waterlogging",
                 "nala", "gutka", "manhole blocked", "stagnant"],
    "water": ["water", "leak", "leakage", "tap", "pipeline", "no water", "water supply",
              "pani", "jal", "overflow tank"],
    "electricity": ["streetlight", "street light", "pole", "wire", "cable", "electricity",
                    "light", "transformer", "bijli", "bijlee", "lamp post"],
    "public_safety": ["dangerous", "exposed wire", "open manhole", "collapsed", "unsafe",
                      "hazard", "live wire", "electrocution risk", "falling"],
}

SEVERITY_KEYWORDS_HIGH = [
    "huge", "large", "big", "severe", "dangerous", "accident", "falling",
    "exposed", "live wire", "flood", "emergency", "critical", "huge pothole",
    "two-wheelers", "bike", "vehicle damage", "child", "school", "hospital",
]
SEVERITY_KEYWORDS_LOW = ["minor", "small", "tiny", "slight", "cosmetic"]

SAFETY_RISK_TERMS = [
    "exposed wire", "live wire", "open manhole", "manhole", "collapsed",
    "falling", "dangerous", "hazard", "electrocution", "accident", "fire",
    "flood", "deep water", "school", "children", "hospital", "pedestrian",
    "two-wheeler", "bike", "vehicle", "traffic",
]

STATUSES = [
    "received", "under_review", "inspection_scheduled", "in_progress",
    "awaiting_verification", "resolved", "reopened", "closed",
]

INCIDENT_STATUSES = ["open", "in_progress", "awaiting_verification", "resolved", "closed", "reopened"]

PRIORITY_BANDS = ["critical", "high", "medium", "low"]

ROLES = ["super_admin", "state_admin", "district_admin", "municipal_admin", "ward_admin"]

# Default SLA rules (PLACEHOLDER hours — not official municipal figures)
DEFAULT_SLA_RULES = [
    ("*", "critical", 24, 6),
    ("*", "high", 48, 12),
    ("*", "medium", 168, 48),   # 7 days
    ("*", "low", 336, 72),      # 14 days
]

# Default priority weights (PLACEHOLDER, editable by super admin)
DEFAULT_PRIORITY_WEIGHTS = {
    "w_severity": 0.35,
    "w_safety": 0.20,
    "w_corroboration": 0.20,
    "w_waiting": 0.15,
    "w_vulnerability": 0.10,
}

CATEGORIES_ORDERED = ["roads", "waste", "drainage", "water", "electricity", "public_safety", "other"]

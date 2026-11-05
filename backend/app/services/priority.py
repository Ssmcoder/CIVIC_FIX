"""Explainable priority score — fully deterministic and auditable.

P = 0.35*S + 0.20*R + 0.20*C + 0.15*T + 0.10*V   (all factors 0-100)
Weights come from priority_config / DEFAULT_PRIORITY_WEIGHTS.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..taxonomy import DEFAULT_PRIORITY_WEIGHTS


def band_for(score: float) -> str:
    if score >= 80: return "critical"
    if score >= 60: return "high"
    if score >= 35: return "medium"
    return "low"


def compute_priority(*, severity_score: float, safety_risk: float,
                     corroboration: int, waiting_hours: float,
                     vulnerability: float = 50.0,
                     weights: dict | None = None) -> dict:
    """corroboration = number of independent reports (complaints) in incident.
    waiting_hours = hours since first report. vulnerability 0-100.
    Returns score, band and a plain-language factor breakdown."""
    w = {**DEFAULT_PRIORITY_WEIGHTS, **(weights or {})}

    # normalise corroboration: 1 report -> ~15, 5+ -> 100 (log scale)
    import math
    c = min(100.0, 15.0 + 35.0 * math.log2(max(1, corroboration)))
    # waiting: 0h -> 0, 7 days -> ~70, 30 days -> 100
    t = min(100.0, (waiting_hours / 24.0) / 30.0 * 100.0)

    factors = {
        "severity": {"score": round(severity_score, 1), "weight": w["w_severity"],
                     "contribution": round(severity_score * w["w_severity"], 2),
                     "plain": f"Issue severity rated {severity_score:.0f}/100 from description cues"},
        "safety_risk": {"score": round(safety_risk, 1), "weight": w["w_safety"],
                        "contribution": round(safety_risk * w["w_safety"], 2),
                        "plain": f"Public-safety risk {safety_risk:.0f}/100 (proximity to people/traffic/hazards)"},
        "corroboration": {"score": round(c, 1), "weight": w["w_corroboration"],
                          "contribution": round(c * w["w_corroboration"], 2),
                          "plain": f"{corroboration} independent report(s) of the same problem"},
        "waiting": {"score": round(t, 1), "weight": w["w_waiting"],
                    "contribution": round(t * w["w_waiting"], 2),
                    "plain": f"Waiting ~{waiting_hours:.0f} hours since first report"},
        "vulnerability": {"score": round(vulnerability, 1), "weight": w["w_vulnerability"],
                          "contribution": round(vulnerability * w["w_vulnerability"], 2),
                          "plain": f"Affected infrastructure vulnerability {vulnerability:.0f}/100"},
    }
    total = sum(f["contribution"] for f in factors.values())
    band = band_for(total)
    return {
        "score": round(total, 1),
        "band": band,
        "factors": factors,
        "weights": w,
        "formula": "P = 0.35*S + 0.20*R + 0.20*C + 0.15*T + 0.10*V",
    }


def vulnerability_for(category: str, text: str = "") -> float:
    """Heuristic: how critical is the affected infrastructure (0-100)."""
    t = (text or "").lower()
    base = {
        "public_safety": 90, "electricity": 75, "drainage": 65,
        "water": 70, "roads": 60, "waste": 35, "other": 40,
    }.get(category, 40)
    if any(k in t for k in ("school", "hospital", "main road", "highway", "market", "bus stand")):
        base = min(100, base + 20)
    return float(base)

"""Complaint classification: keyword rules + optional sklearn head.

Always returns (category, issue_type, confidence, explanation, nearest_examples).
Confidence is calibrated-ish: keyword hits are strong evidence; the ML head
refines when a trained model exists.
"""
from __future__ import annotations

import json
import logging
import pickle
import re
from pathlib import Path

import numpy as np

from ..config import get_settings
from ..taxonomy import CATEGORIES, ISSUE_KEYWORDS, SEVERITY_KEYWORDS_HIGH, SEVERITY_KEYWORDS_LOW, SAFETY_RISK_TERMS
from .embeddings import embed_one, embed_texts

log = logging.getLogger(__name__)

_MODEL_PATH = Path(get_settings().ml_model_dir) / "category_head.pkl"
_head = None  # {"model": sklearn, "label_encoder": ..., "version": str, "thresholds": {...}}


def _load_head():
    global _head
    if _head is not None:
        return _head
    try:
        if _MODEL_PATH.exists():
            with open(_MODEL_PATH, "rb") as f:
                _head = pickle.load(f)
            log.info("Loaded category head v%s", _head.get("version"))
    except Exception as e:  # noqa: BLE001
        log.warning("category head load failed: %s", e)
        _head = None
    return _head


def classify_text(text: str, lang: str = "en") -> dict:
    """Return classification result dict."""
    t = (text or "").lower()
    scores: dict[str, float] = {}
    hits: dict[str, list[str]] = {}
    for cat, kws in ISSUE_KEYWORDS.items():
        found = [kw for kw in kws if kw in t]
        if found:
            scores[cat] = len(found) * 2.0 + sum(len(kw.split()) for kw in found)
            hits[cat] = found

    # phrase-level boosts for common phrasings
    boosts = {
        "roads": ["pothole", "broken road", "road damage", "sadak", "koliba"],
        "waste": ["garbage", "safai", "waste", "bin overflow"],
        "drainage": ["drain", "nala", "waterlog", "choked"],
        "water": ["leak", "no water", "water supply"],
        "electricity": ["streetlight", "street light", "pole", "bijli"],
        "public_safety": ["exposed wire", "open manhole", "dangerous"],
    }
    for cat, phrases in boosts.items():
        for ph in phrases:
            if ph in t:
                scores[cat] = scores.get(cat, 0) + 3.0

    if not scores:
        # ML head fallback
        head = _load_head()
        if head:
            try:
                emb = embed_one(text)
                proba = head["model"].predict_proba(emb.reshape(1, -1))[0]
                classes = list(head["model"].classes_)
                best = classes[int(np.argmax(proba))]
                conf = float(np.max(proba))
                return _result(best, t, conf, f"ML model v{head['version']} (no keyword match)", hits, scores)
            except Exception as e:  # noqa: BLE001
                log.warning("ML classify failed: %s", e)
        return _result("other", t, 0.30, "No strong keyword match; marked Other for review", hits, scores)

    best = max(scores, key=scores.get)
    total = sum(scores.values()) or 1.0
    raw_conf = scores[best] / total
    conf = min(0.98, 0.45 + 0.5 * raw_conf)  # keyword evidence -> reasonably confident

    # refine with ML head if present
    head = _load_head()
    ml_note = ""
    if head:
        try:
            emb = embed_one(text)
            proba = head["model"].predict_proba(emb.reshape(1, -1))[0]
            classes = list(head["model"].classes_)
            ml_best = classes[int(np.argmax(proba))]
            ml_conf = float(np.max(proba))
            if ml_best == best:
                conf = min(0.99, conf * 0.6 + ml_conf * 0.4)
                ml_note = f"; ML model v{head['version']} agrees (p={ml_conf:.2f})"
            elif ml_conf > 0.75 and raw_conf < 0.5:
                best = ml_best
                conf = ml_conf
                ml_note = f"; ML model v{head['version']} suggests {ml_best} (p={ml_conf:.2f})"
        except Exception as e:  # noqa: BLE001
            log.warning("ML refine failed: %s", e)

    issue = _issue_type(best, t)
    expl = (f"Matched keywords {hits.get(best, [])} for category '{best}' "
            f"({CATEGORIES[best]}){ml_note}")
    return _result(best, t, conf, expl, hits, scores, issue=issue)


def _result(cat, t, conf, expl, hits, scores, issue=""):
    return {
        "category": cat,
        "category_label": CATEGORIES.get(cat, cat),
        "issue_type": issue or _issue_type(cat, t),
        "confidence": round(conf, 3),
        "explanation": expl,
        "matched_keywords": hits.get(cat, []),
        "all_scores": {k: round(v, 2) for k, v in scores.items()},
    }


def _issue_type(cat: str, t: str) -> str:
    if cat == "roads":
        if "pothole" in t or "hole" in t: return "Pothole"
        if "crack" in t: return "Road crack"
        if "speed breaker" in t: return "Broken speed breaker"
        if "footpath" in t or "sidewalk" in t: return "Footpath damage"
        return "Road damage"
    if cat == "waste":
        if "overflow" in t: return "Overflowing waste bin"
        if "missed" in t or "not collected" in t: return "Missed collection"
        return "Garbage accumulation"
    if cat == "drainage":
        if "waterlog" in t or "stagnant" in t: return "Waterlogging"
        return "Blocked drain"
    if cat == "water":
        if "leak" in t: return "Water leakage"
        if "no water" in t: return "Water supply disruption"
        return "Water pipeline issue"
    if cat == "electricity":
        if "streetlight" in t or "street light" in t: return "Streetlight fault"
        if "pole" in t: return "Electric pole issue"
        if "wire" in t or "cable" in t: return "Electrical wiring issue"
        return "Electricity fault"
    if cat == "public_safety":
        if "manhole" in t: return "Open/manhole hazard"
        if "wire" in t: return "Exposed wiring hazard"
        return "Public safety hazard"
    return "General municipal issue"


def severity_and_safety(text: str) -> dict:
    """Deterministic severity + safety-risk estimate with reasons."""
    t = (text or "").lower()
    high_hits = [k for k in SEVERITY_KEYWORDS_HIGH if k in t]
    low_hits = [k for k in SEVERITY_KEYWORDS_LOW if k in t]
    safety_hits = [k for k in SAFETY_RISK_TERMS if k in t]

    if len(high_hits) >= 2:
        sev, sev_score = "high", 85.0
    elif len(high_hits) == 1:
        sev, sev_score = "medium", 60.0
    elif low_hits:
        sev, sev_score = "low", 25.0
    else:
        sev, sev_score = "medium", 45.0

    safety = min(100.0, len(safety_hits) * 20.0 + (30.0 if any(h in t for h in ("school", "children", "hospital")) else 0))
    reasons = []
    if high_hits: reasons.append(f"severity cues: {', '.join(sorted(set(high_hits))[:4])}")
    if safety_hits: reasons.append(f"safety terms: {', '.join(sorted(set(safety_hits))[:4])}")
    if not reasons: reasons.append("no strong severity cues; default medium")
    return {
        "severity": sev,
        "severity_score": sev_score,
        "safety_risk": safety,
        "reasons": reasons,
    }


def strip_pii(text: str) -> str:
    """Remove phone numbers and emails before any ML/training use."""
    t = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[email]", text or "")
    t = re.sub(r"(?<!\d)(\+?\d[\d\s-]{8,}\d)(?!\d)", "[phone]", t)
    return t

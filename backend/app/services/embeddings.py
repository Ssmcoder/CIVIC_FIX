"""Embedding provider with graceful degradation.

Priority order:
  1. sentence-transformers multilingual model (best for Odia/Hindi/Hinglish)
  2. scikit-learn TF-IDF char+word n-grams fitted on seed corpus
Both expose: embed(texts) -> np.ndarray (L2-normalised rows), dim.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import numpy as np

from ..config import get_settings

log = logging.getLogger(__name__)

_WORD = re.compile(r"[a-zA-Z0-9\u0900-\u097F\u0B00-\u0B7F]+")


def _normalise(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


class TfidfEmbedder:
    """Fallback: word + char n-gram TF-IDF. Works for any script, no downloads."""

    name = "tfidf-fallback"

    def __init__(self):
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.word_vec = TfidfVectorizer(
            analyzer="word", ngram_range=(1, 2), min_df=1,
            token_pattern=r"(?u)\b\w[\w\u0900-\u097F\u0B00-\u0B7F]*\b",
            lowercase=True, sublinear_tf=True,
        )
        self.char_vec = TfidfVectorizer(
            analyzer="char_wb", ngram_range=(3, 5), min_df=1,
            lowercase=True, sublinear_tf=True,
        )
        self._fitted = False
        self._dim = 0

    def fit(self, corpus: list[str]) -> "TfidfEmbedder":
        self.word_vec.fit(corpus)
        self.char_vec.fit(corpus)
        self._dim = len(self.word_vec.vocabulary_) + len(self.char_vec.vocabulary_)
        self._fitted = True
        return self

    def embed(self, texts: list[str]) -> np.ndarray:
        if not self._fitted:
            self.fit(texts if texts else ["civic complaint"])
        w = self.word_vec.transform(texts).toarray()
        c = self.char_vec.transform(texts).toarray()
        return _normalise(np.hstack([w, c]).astype(np.float32))

    @property
    def dim(self) -> int:
        return self._dim or 512

    def calibrate(self, cos: float) -> float:
        """TF-IDF cosines compress paraphrases into ~0.2-0.45. Scale so that
        true duplicates land in the same range as sentence-transformer
        cosines (~0.7+). Unrelated pairs stay low."""
        return min(0.99, max(0.0, cos * 1.9))


class SentenceTransformerEmbedder:
    """Multilingual sentence embeddings (downloads model on first use)."""

    name = "paraphrase-multilingual-MiniLM-L12-v2"

    def __init__(self, model_name: str | None = None):
        from sentence_transformers import SentenceTransformer
        self.model_name = model_name or self.name
        self.model = SentenceTransformer(self.model_name)

    def embed(self, texts: list[str]) -> np.ndarray:
        emb = self.model.encode(list(texts), normalize_embeddings=True,
                                convert_to_numpy=True, show_progress_bar=False)
        return np.asarray(emb, dtype=np.float32)

    @property
    def dim(self) -> int:
        return int(self.model.get_sentence_embedding_dimension())

    def calibrate(self, cos: float) -> float:
        return cos  # sentence transformers already produce calibrated cosines


_embedder = None


def get_embedder():
    """Return a process-wide embedder. 'auto' tries sentence-transformers,
    falls back to TF-IDF if torch/models unavailable."""
    global _embedder
    if _embedder is not None:
        return _embedder
    backend = get_settings().embedding_backend
    if backend in ("auto", "sentence"):
        try:
            _embedder = SentenceTransformerEmbedder()
            log.info("Using sentence-transformers embedder %s", _embedder.name)
            return _embedder
        except Exception as e:  # noqa: BLE001
            log.warning("sentence-transformers unavailable (%s); using TF-IDF fallback", e)
            if backend == "sentence":
                raise
    corpus = _seed_corpus()
    _embedder = TfidfEmbedder().fit(corpus)
    log.info("Using TF-IDF fallback embedder (dim=%d)", _embedder.dim)
    return _embedder


def _seed_corpus() -> list[str]:
    """Small built-in corpus so TF-IDF fallback has reasonable coverage."""
    base = [
        "pothole road damaged street broken vehicles college gate market",
        "garbage waste overflowing dustbin missed collection safai",
        "blocked drain choked sewage waterlogging nala stagnant",
        "water leakage pipeline no water supply tap pani",
        "streetlight broken pole wire electricity bijli transformer",
        "exposed wire open manhole dangerous hazard accident risk",
        "pothole near railway station road crack speed breaker",
        "garbage heap near temple market waste dump",
        "drainage blocked near school water logging street",
        "water tank leak pipe burst no supply colony",
        "electric pole fallen wire low height street",
        "manhole cover missing open pit danger",
    ]
    # multilingual smoke corpus
    base += [
        " jama rank roads sadak koliba pothole ",
        " kachah ghaura safai waste bin ",
        " nalika badhila drain block paani ",
        " bijuli light pole tara ",
        " khatara open manhole baba ",
        "There is a big pothole outside the college gate troubling two wheelers",
        "Road is damaged near the market entrance, vehicles falling into hole",
        "Drain near bus stand is choked and water is stagnating",
        "Street light near park has been broken for a week",
        "Exposed wires near school are dangerous for children",
    ]
    return base


def embed_texts(texts: list[str]) -> np.ndarray:
    return get_embedder().embed(texts)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    if a.ndim == 1:
        a = a.reshape(1, -1)
    if b.ndim == 1:
        b = b.reshape(1, -1)
    return float(np.dot(a, b.T)[0, 0])


def calibrated_cosine(a: np.ndarray, b: np.ndarray) -> float:
    return get_embedder().calibrate(cosine(a, b))


def embed_one(text: str) -> np.ndarray:
    return embed_texts([text])[0]

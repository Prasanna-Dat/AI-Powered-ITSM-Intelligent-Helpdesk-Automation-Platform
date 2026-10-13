"""Turns text into vectors (embeddings).

Primary:  sentence-transformers/all-MiniLM-L6-v2  (open source, 384 dims, fast on CPU)
Fallback: a tiny hashed bag-of-words embedder so the project still runs with no internet / no model download.
"""
import logging
import re
import zlib

import numpy as np

from app.config import settings

log = logging.getLogger("embeddings")
STOP = set("a an the is are was were be been to of in on at for and or my me i it this that with from as by do does how what can you your we our not no please".split())


def _tok(text: str):
    out = []
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if w in STOP:
            continue
        for suf in ("ing", "ed", "es", "s"):       # crude stemming: 'locked' -> 'lock', 'syncing' -> 'sync'
            if len(w) > 4 and w.endswith(suf):
                w = w[: -len(suf)]
                break
        out.append(w[:7])
    return out + [f"{a}_{b}" for a, b in zip(out, out[1:])]


class Embedder:
    def __init__(self):
        self.backend = "hashing-fallback"
        self.model_name = "hashing-fallback"
        self.dim = 8192
        self._model = None
        want = settings.EMBEDDING_BACKEND
        if want in ("auto", "st"):
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(settings.EMBEDDING_MODEL)
                self.backend = "sentence-transformers"
                self.model_name = settings.EMBEDDING_MODEL
                self.dim = self._model.get_sentence_embedding_dimension()
            except Exception as exc:               # noqa: BLE001
                log.warning("Embedding model unavailable (%s) -> using hashing fallback", exc)
                if want == "st":
                    raise
        # Score calibration: cosine scores mean different things for different models.
        if self.backend == "sentence-transformers":
            self.min_score, self.full_score = 0.30, 0.60   # below min = "not in the KB"
        else:
            self.min_score, self.full_score = 0.15, 0.40

    def encode(self, texts):
        if self._model is not None:
            v = self._model.encode(list(texts), normalize_embeddings=True, show_progress_bar=False)
            return np.asarray(v, dtype="float32")
        mat = np.zeros((len(texts), self.dim), dtype="float32")
        for i, t in enumerate(texts):
            for tok in _tok(t):
                mat[i, zlib.crc32(tok.encode()) % self.dim] += 1.0
            mat[i] = np.sqrt(mat[i])
            n = np.linalg.norm(mat[i])
            if n:
                mat[i] /= n
        return mat

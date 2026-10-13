"""Builds the heavy objects (embedding model, vector index, LLM) once and shares them."""
from dataclasses import dataclass

from app.embeddings import Embedder
from app.knowledge import KnowledgeBase
from app.llm import LLM

_ctx = None


@dataclass
class Context:
    embedder: Embedder
    kb: KnowledgeBase
    llm: LLM


def get_ctx() -> Context:
    global _ctx
    if _ctx is None:
        emb = Embedder()
        kb = KnowledgeBase(emb)
        kb.build()
        _ctx = Context(emb, kb, LLM())
    return _ctx

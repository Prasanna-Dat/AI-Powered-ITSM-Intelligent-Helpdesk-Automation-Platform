"""RAG retrieval layer:  Document -> Chunking -> Embedding -> Vector DB (Qdrant) -> Semantic search."""
import logging
import re

import numpy as np

from app import db
from app.config import settings

log = logging.getLogger("knowledge")
MAX_WORDS = 90          # max words per chunk
COLLECTION = "it_knowledge"   # name of the Qdrant collection (like a table)


def _parse(path):
    """Read a markdown file with a small '---' front-matter header."""
    raw = path.read_text(encoding="utf-8")
    meta, body = {}, raw
    if raw.startswith("---"):
        _, header, body = raw.split("---", 2)
        for line in header.strip().splitlines():
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    meta["tags"] = [t.strip() for t in meta.get("tags", "").split(",") if t.strip()]
    meta["body"] = body.strip()
    meta["file"] = path.name
    return meta


def chunk_document(doc: dict, max_words: int = MAX_WORDS):
    """Split a document by '## heading', then pack lines into chunks of ~max_words with 1-line overlap."""
    chunks = []
    for section in re.split(r"\n(?=## )", doc["body"]):
        lines = [ln for ln in section.strip().splitlines() if ln.strip()]
        if not lines:
            continue
        if lines[0].startswith("#"):
            heading, lines = lines[0].lstrip("# ").strip(), lines[1:]
        else:
            heading = "Overview"
        if not lines:
            continue
        cur, words, groups = [], 0, []
        for ln in lines:
            w = len(ln.split())
            if cur and words + w > max_words:
                groups.append(cur)
                cur = [cur[-1]]
                words = len(cur[0].split())
            cur.append(ln)
            words += w
        groups.append(cur)
        for g in groups:
            text = "\n".join(g)
            chunks.append({"doc_id": doc["id"], "title": doc["title"], "category": doc["category"],
                           "section": heading, "text": text,
                           "embed_text": f"{doc['title']}. {heading}. {text}"})
    for i, c in enumerate(chunks):
        c["chunk_id"] = f"{doc['id']}-C{i + 1:02d}"
    return chunks


class KnowledgeBase:
    def __init__(self, embedder):
        self.embedder = embedder
        self.docs, self.chunks = [], []
        self.client, self.vecs, self.store = None, None, "numpy (fallback)"


    def _open_client(self):
        """Qdrant has 3 modes, all free: (1) a server/cloud URL, (2) local mode stored in a folder (default),
        (3) in-memory. Local mode needs no installation and no account."""
        from qdrant_client import QdrantClient
        if settings.QDRANT_URL:
            return QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY or None), "Qdrant (server/cloud)"
        if settings.QDRANT_PATH == ":memory:":
            return QdrantClient(":memory:"), "Qdrant (in-memory, cosine)"
        try:
            settings.VECTOR_DIR.mkdir(exist_ok=True)
            return QdrantClient(path=str(settings.VECTOR_DIR / settings.QDRANT_PATH)), "Qdrant (local mode, cosine)"
        except Exception as exc:                                  # folder locked by another running copy
            log.warning("Qdrant local folder busy (%s) -> in-memory Qdrant", exc)
            return QdrantClient(":memory:"), "Qdrant (in-memory, cosine)"

    def _build_vector_db(self):
        try:
            from qdrant_client import models
            if self.client is None:
                self.client, self.store = self._open_client()
            if self.client.collection_exists(COLLECTION):
                self.client.delete_collection(COLLECTION)
            self.client.create_collection(COLLECTION, vectors_config=models.VectorParams(
                size=int(self.vecs.shape[1]), distance=models.Distance.COSINE))
            self.client.upsert(COLLECTION, points=[
                models.PointStruct(id=i, vector=self.vecs[i].tolist(),
                                   payload={k: v for k, v in c.items() if k != "embed_text"})   # metadata stored WITH the vector
                for i, c in enumerate(self.chunks)])
        except Exception as exc:                                  # noqa: BLE001
            log.warning("Qdrant unavailable (%s) -> numpy search", exc)
            self.client, self.store = None, "numpy (fallback)"

    def build(self):
        self.docs = [_parse(p) for p in sorted(settings.KB_DIR.glob("*.md"))]
        self.chunks = [c for d in self.docs for c in chunk_document(d)]
        self.vecs = self.embedder.encode([c["embed_text"] for c in self.chunks])
        self._build_vector_db()
        # keep knowledge metadata in MongoDB
        db.col("knowledge_docs").delete_many({})
        db.col("knowledge_chunks").delete_many({})
        db.col("knowledge_docs").insert_many([{k: v for k, v in d.items()} for d in self.docs])
        db.col("knowledge_chunks").insert_many([{k: v for k, v in c.items() if k != "embed_text"} for c in self.chunks])
        log.info("Knowledge base built: %d docs, %d chunks, store=%s", len(self.docs), len(self.chunks), self.store)

    def search(self, query: str, k: int | None = None, category: str | None = None):
        """Semantic search. Optional 'category' uses Qdrant's metadata filter (e.g. only Network articles)."""
        k = min(k or settings.TOP_K, len(self.chunks))
        q = self.embedder.encode([query])[0]
        out = []
        if self.client is not None:
            from qdrant_client import models
            flt = None
            if category:
                flt = models.Filter(must=[models.FieldCondition(key="category", match=models.MatchValue(value=category))])
            res = self.client.query_points(COLLECTION, query=q.tolist(), limit=k, query_filter=flt, with_payload=True)
            pairs = [(p.payload, p.score) for p in res.points]
        else:
            s = self.vecs @ q
            pairs = [(self.chunks[i], s[i]) for i in np.argsort(-s)[:k]
                     if not category or self.chunks[i]["category"] == category]
        for c, sc in pairs:
            out.append({"chunk_id": c["chunk_id"], "doc_id": c["doc_id"], "title": c["title"],
                        "category": c["category"], "section": c["section"], "text": c["text"],
                        "score": round(float(sc), 3)})
        return out

    @staticmethod
    def sources(hits):
        """Unique documents behind a set of hits (best score first) - shown to the user as 'sources'."""
        seen, out = set(), []
        for h in hits:
            if h["doc_id"] not in seen:
                seen.add(h["doc_id"])
                out.append({"doc_id": h["doc_id"], "title": h["title"], "category": h["category"],
                            "section": h["section"], "score": h["score"]})
        return out

    def articles(self):
        return [{"id": d["id"], "title": d["title"], "category": d["category"], "tags": d["tags"],
                 "chunks": sum(1 for c in self.chunks if c["doc_id"] == d["id"]),
                 "words": len(d["body"].split())} for d in self.docs]

    def article(self, doc_id):
        for d in self.docs:
            if d["id"] == doc_id:
                return {**{k: d[k] for k in ("id", "title", "category", "tags", "body", "file")},
                        "chunks": [{"chunk_id": c["chunk_id"], "section": c["section"], "text": c["text"]}
                                   for c in self.chunks if c["doc_id"] == doc_id]}
        return None

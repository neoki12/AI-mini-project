"""표준서 RAG 인덱스 — 조항 단위 청크를 임베딩해 Chroma에 저장하고 메타데이터로 걸러 검색한다.

- 청크: data/4m/standards/*.md의 `## 조항 N` 하나 = 청크 하나 (41개). 문서 제목·조항 제목·본문을
  함께 임베딩하고, 문서ID·개정판·공장·문서 종류·조항 번호·변경 유형을 메타데이터로 둔다
- 필터: 공장 AND 변경 유형(하나라도 겹침) — 다른 공장의 비슷한 조항(차체 실러 vs 도장 실링)이
  섞이지 않게 한다. 공통 규정(QS-CM-001)은 Agent가 항상 전체를 읽으므로 기본적으로 검색 대상에서
  뺀다 — 공장 조항과 상위 k 자리를 다투지 않게
- 임베딩: ollama(bge-m3, 한국어 지원) 또는 fake(문자 2-gram 해시, 결정론 — 테스트·LLM 없는 실행용)
- 영속화: 내용·임베딩 모델의 해시를 컬렉션 메타데이터에 남겨, 표준서가 바뀌면 다시 인덱싱한다
  (개정 시 재인덱싱 — 계획서의 RAG 트레이드오프)
"""
import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Protocol

import chromadb
from chromadb.config import Settings as ChromaSettings

PROJECT_DIR = Path(__file__).resolve().parent.parent
STANDARDS_DIR = PROJECT_DIR / "data" / "4m" / "standards"
DEFAULT_INDEX_DIR = PROJECT_DIR / ".cache" / "rag"
COLLECTION = "4m-standards"
CHANGE_TYPES = ["Man", "Machine", "Material", "Method"]
COMMON_SHOP = "공통"


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FakeEmbedder:
    """문자 2-gram을 해시해 고정 차원 벡터로 만든다. 결정론적이고 외부 호출이 없다.
    의미를 이해하지는 못하지만 같은 단어(외판, 금형, 전류)를 공유하는 조항은 가깝게 놓인다."""

    name = "fake-char-bigram-512"
    dim = 512

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vec = [0.0] * self.dim
            compact = re.sub(r"\s+", "", text)
            for i in range(len(compact) - 1):
                h = int(hashlib.md5(compact[i:i + 2].encode()).hexdigest()[:8], 16)
                vec[h % self.dim] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vectors.append([v / norm for v in vec])
        return vectors


class OllamaEmbedder:
    def __init__(self, model: str = "bge-m3"):
        from langchain_ollama import OllamaEmbeddings
        self.name = f"ollama:{model}"
        self._model = OllamaEmbeddings(model=model)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._model.embed_documents(texts)


def embedder_from_env() -> Embedder:
    """EMBEDDING_BACKEND(fake|ollama). 없으면 LLM_BACKEND가 fake일 때만 fake, 아니면 ollama."""
    backend = os.environ.get("EMBEDDING_BACKEND") or (
        "fake" if os.environ.get("LLM_BACKEND", "fake") == "fake" else "ollama")
    if backend == "ollama":
        return OllamaEmbedder(os.environ.get("EMBEDDING_MODEL", "bge-m3"))
    return FakeEmbedder()


def _front_matter(text: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}
    return dict(line.split(": ", 1) for line in m.group(1).splitlines() if ": " in line)


def load_chunks(standards_dir: Path = STANDARDS_DIR) -> list[dict]:
    """표준서 → 조항 청크 [{id, text, metadata}]."""
    chunks = []
    for path in sorted(standards_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        front = _front_matter(text)
        change_types = re.findall(r"\w+", front.get("change_types", ""))
        doc_type = "inspection" if front.get("doc_type") == "inspection-criteria" else "standard"
        for m in re.finditer(r"^## 조항 (\S+) ([^\n]*)\n(.*?)(?=^## |\Z)", text, re.S | re.M):
            clause, clause_title, body = m.group(1), m.group(2).strip(), m.group(3).strip()
            metadata = {"doc_id": front["doc_id"], "rev": front.get("rev", ""),
                        "title": front.get("title", ""), "shop": front.get("shop", ""),
                        "doc_type": doc_type, "clause": clause, "clause_title": clause_title}
            metadata.update({f"ct_{ct}": ct in change_types for ct in CHANGE_TYPES})
            chunks.append({"id": f"{front['doc_id']}#{clause}",
                           "text": f"{front.get('title', '')} — {clause_title}\n{body}",
                           "body": body, "metadata": metadata})
    return chunks


def _content_hash(chunks: list[dict], embedder: Embedder) -> str:
    """본문뿐 아니라 메타데이터(개정판 등)까지 해시한다 — 개정판만 바뀌어도 다시 인덱싱해야
    근거 인용에 옛 개정판이 찍히지 않는다."""
    h = hashlib.sha256(embedder.name.encode())
    for c in chunks:
        h.update(c["id"].encode())
        h.update(c["text"].encode())
        h.update(json.dumps(c["metadata"], sort_keys=True, ensure_ascii=False).encode())
    return h.hexdigest()[:16]


def _where(shop: str | None, change_types: list[str], include_common: bool) -> dict | None:
    conditions = []
    if shop:
        conditions.append({"shop": {"$in": [shop, COMMON_SHOP]}} if include_common
                          else {"shop": shop})
    elif not include_common:
        conditions.append({"shop": {"$ne": COMMON_SHOP}})
    flags = [{f"ct_{ct}": True} for ct in change_types if ct in CHANGE_TYPES]
    if len(flags) == 1:
        conditions.append(flags[0])
    elif flags:
        conditions.append({"$or": flags})
    if not conditions:
        return None
    return conditions[0] if len(conditions) == 1 else {"$and": conditions}


class StandardsIndex:
    def __init__(self, embedder: Embedder, index_dir: Path | None = DEFAULT_INDEX_DIR,
                 standards_dir: Path = STANDARDS_DIR):
        self.embedder = embedder
        self.standards_dir = standards_dir
        settings = ChromaSettings(anonymized_telemetry=False)
        if index_dir is None:
            self._client = chromadb.EphemeralClient(settings=settings)
        else:
            index_dir.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(index_dir), settings=settings)
        self._collection = None
        self.chunk_count = 0
        self.rebuilt = False

    def ensure(self):
        """인덱스를 준비한다. 표준서 내용이나 임베딩 모델이 바뀌었으면 다시 만든다."""
        if self._collection is not None:
            return self._collection
        chunks = load_chunks(self.standards_dir)
        digest = _content_hash(chunks, self.embedder)
        try:
            existing = self._client.get_collection(COLLECTION)
            if (existing.metadata or {}).get("content_hash") == digest:
                self._collection, self.chunk_count = existing, existing.count()
                return existing
            self._client.delete_collection(COLLECTION)
        except Exception:   # 컬렉션이 아직 없음
            pass
        collection = self._client.create_collection(
            COLLECTION, embedding_function=None,
            metadata={"hnsw:space": "cosine", "content_hash": digest,
                      "embedding": self.embedder.name})
        collection.add(ids=[c["id"] for c in chunks],
                       embeddings=self.embedder.embed([c["text"] for c in chunks]),
                       documents=[c["body"] for c in chunks],
                       metadatas=[c["metadata"] for c in chunks])
        self._collection, self.chunk_count, self.rebuilt = collection, len(chunks), True
        return collection

    def search(self, query: str, shop: str | None = None,
               change_types: list[str] | None = None, k: int = 6,
               include_common: bool = False) -> list[dict]:
        """질의와 가까운 조항 k개 (필터 적용). score = 1 - 코사인 거리."""
        collection = self.ensure()
        where = _where(shop, change_types or [], include_common)
        result = collection.query(query_embeddings=self.embedder.embed([query]),
                                  n_results=k, where=where)
        hits = []
        for chunk_id, body, meta, dist in zip(result["ids"][0], result["documents"][0],
                                              result["metadatas"][0], result["distances"][0]):
            hits.append({"id": chunk_id, "doc_id": meta["doc_id"], "rev": meta["rev"],
                         "title": meta["title"], "shop": meta["shop"],
                         "doc_type": meta["doc_type"], "clause": meta["clause"],
                         "clause_title": meta["clause_title"], "text": body,
                         "score": round(1 - dist, 4)})
        return hits

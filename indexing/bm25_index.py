import os
import re
import math
import pickle
import logging
from typing import List, Dict, Any, Optional, Tuple
from config import Config
from core.models import DocumentChunk

logger = logging.getLogger(__name__)

class SimpleBM25:
    """Lightweight pure-python BM25 implementation for zero-dependency portability."""
    def __init__(self, corpus: List[List[str]], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus_size = len(corpus)
        self.avgdl = sum(len(doc) for doc in corpus) / (self.corpus_size or 1)
        self.doc_freqs: List[Dict[str, int]] = []
        self.idf: Dict[str, float] = {}
        self.doc_len: List[int] = []

        # Calculate doc frequencies and IDF
        df: Dict[str, int] = {}
        for doc in corpus:
            self.doc_len.append(len(doc))
            frequencies: Dict[str, int] = {}
            for word in doc:
                frequencies[word] = frequencies.get(word, 0) + 1
            self.doc_freqs.append(frequencies)

            for word in frequencies.keys():
                df[word] = df.get(word, 0) + 1

        for word, freq in df.items():
            self.idf[word] = math.log(1 + (self.corpus_size - freq + 0.5) / (freq + 0.5))

    def get_scores(self, query: List[str]) -> List[float]:
        scores = [0.0] * self.corpus_size
        for q in query:
            if q not in self.idf:
                continue
            idf_val = self.idf[q]
            for i, doc_freq in enumerate(self.doc_freqs):
                tf = doc_freq.get(q, 0)
                if tf > 0:
                    numerator = idf_val * tf * (self.k1 + 1)
                    denominator = tf + self.k1 * (1 - self.b + self.b * (self.doc_len[i] / (self.avgdl or 1)))
                    scores[i] += numerator / denominator
        return scores


class BM25IndexStore:
    """Manages the sparse BM25 index across all indexed document chunks."""

    def __init__(self):
        self.index_path = os.path.join(Config.INDEX_FOLDER, "bm25_store.pkl")
        self.chunks: List[DocumentChunk] = []
        self.tokenized_corpus: List[List[str]] = []
        self.bm25 = None
        self._load()

    def _tokenize(self, text: str) -> List[str]:
        """Tokenizes text preserving alphanumerics, metric symbols, and digits."""
        tokens = re.findall(r'\b[a-zA-Z0-9_\-]+\b', text.lower())
        return tokens

    def add_chunks(self, new_chunks: List[DocumentChunk]):
        """Adds new document chunks to the corpus and updates the BM25 model."""
        if not new_chunks:
            return

        for chunk in new_chunks:
            self.chunks.append(chunk)
            self.tokenized_corpus.append(self._tokenize(chunk.text))

        self._build_index()
        self.save()

    def remove_chunks_by_document(self, doc_id: int):
        """Removes all chunks belonging to a document and rebuilds BM25 model."""
        initial_count = len(self.chunks)
        filtered_chunks = []
        filtered_tokens = []
        for chunk, tokens in zip(self.chunks, self.tokenized_corpus):
            if getattr(chunk, 'document_id', None) != doc_id:
                filtered_chunks.append(chunk)
                filtered_tokens.append(tokens)

        if len(filtered_chunks) == initial_count:
            return

        self.chunks = filtered_chunks
        self.tokenized_corpus = filtered_tokens
        self._build_index()
        self.save()
        logger.info(f"Removed BM25 chunks for document {doc_id}. Remaining chunks: {len(self.chunks)}")

    def update_document_name(self, doc_id: int, new_name: str):
        """Updates document name metadata on matching BM25 chunks."""
        updated = False
        for c in self.chunks:
            if getattr(c, 'document_id', None) == doc_id:
                c.document_name = new_name
                updated = True
        if updated:
            self.save()

    def _build_index(self):

        if not self.tokenized_corpus:
            self.bm25 = None
            return

        try:
            from rank_bm25 import BM25Okapi
            self.bm25 = BM25Okapi(self.tokenized_corpus)
        except ImportError:
            logger.info("rank-bm25 package not found, using built-in high-performance SimpleBM25.")
            self.bm25 = SimpleBM25(self.tokenized_corpus)

    def search(
        self,
        query: str,
        top_k: int = 10,
        company_names: Optional[List[str]] = None
    ) -> List[Tuple[DocumentChunk, float]]:
        """
        Executes sparse BM25 search.
        Applies company-level pre-filtering if company_names is provided.
        """
        if not self.bm25 or not self.chunks:
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        raw_scores = self.bm25.get_scores(query_tokens)

        # Normalize company names for case-insensitive filtering
        target_companies = {c.strip().lower() for c in company_names} if company_names else None

        scored_candidates: List[Tuple[DocumentChunk, float]] = []
        for idx, score in enumerate(raw_scores):
            if score <= 0:
                continue
            chunk = self.chunks[idx]
            if target_companies and chunk.company_name.lower() not in target_companies:
                continue
            scored_candidates.append((chunk, float(score)))

        # Sort descending by score
        scored_candidates.sort(key=lambda x: x[1], reverse=True)
        return scored_candidates[:top_k]

    def save(self):
        """Persists the BM25 store to disk."""
        data = {
            "chunks": [c.model_dump() for c in self.chunks],
            "tokenized_corpus": self.tokenized_corpus
        }
        with open(self.index_path, "wb") as f:
            pickle.dump(data, f)
        logger.info(f"Saved BM25 store with {len(self.chunks)} chunks to {self.index_path}")

    def _load(self):
        """Loads BM25 store from disk if exists."""
        if os.path.exists(self.index_path):
            try:
                with open(self.index_path, "rb") as f:
                    data = pickle.load(f)
                self.chunks = [DocumentChunk(**item) for item in data.get("chunks", [])]
                self.tokenized_corpus = data.get("tokenized_corpus", [])
                self._build_index()
                logger.info(f"Loaded BM25 store with {len(self.chunks)} chunks.")
            except Exception as e:
                logger.error(f"Failed to load BM25 store from {self.index_path}: {e}")
                self.chunks = []
                self.tokenized_corpus = []
                self.bm25 = None

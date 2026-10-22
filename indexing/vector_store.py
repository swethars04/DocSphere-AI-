import os
import json
import logging
import numpy as np
import faiss
from typing import List, Dict, Any, Optional, Tuple
from config import Config
from core.models import DocumentChunk
from indexing.embeddings import EmbeddingEngine

logger = logging.getLogger(__name__)

class DenseVectorStore:
    """Manages the dense FAISS vector index with company-level metadata pre-filtering."""

    def __init__(self):
        self.index_path = os.path.join(Config.INDEX_FOLDER, "faiss_dense.index")
        self.meta_path = os.path.join(Config.INDEX_FOLDER, "faiss_metadata.json")
        self.dimension = 384
        self.index = None
        self.chunks: List[DocumentChunk] = []
        self._load()

    def add_chunks(self, chunks: List[DocumentChunk], embeddings: np.ndarray):
        """Adds dense vectors and their corresponding DocumentChunks to the FAISS index."""
        if len(chunks) == 0:
            return

        if self.index is None:
            self.index = faiss.IndexFlatIP(self.dimension)

        # Enforce float32 and add to index
        embeddings_np = embeddings.astype(np.float32)
        self.index.add(embeddings_np)
        self.chunks.extend(chunks)

        self.save()
        logger.info(f"Added {len(chunks)} vectors to FAISS. Total in index: {self.index.ntotal}")

    def search(
        self,
        query_vector: np.ndarray,
        top_k: int = 10,
        company_names: Optional[List[str]] = None
    ) -> List[Tuple[DocumentChunk, float]]:
        """
        Queries FAISS using Cosine Similarity (via Inner Product).
        Filters candidates by company_names if provided.
        """
        if self.index is None or self.index.ntotal == 0 or len(self.chunks) == 0:
            return []

        # Target set of companies for filtering
        target_companies = {c.strip().lower() for c in company_names} if company_names else None

        # Fetch more candidates to ensure sufficient items survive company filtering
        fetch_k = min(self.index.ntotal, max(top_k * 5, 50)) if target_companies else min(self.index.ntotal, top_k)

        query_vec_2d = np.expand_dims(query_vector.astype(np.float32), axis=0)
        distances, indices = self.index.search(query_vec_2d, fetch_k)

        results: List[Tuple[DocumentChunk, float]] = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0 or idx >= len(self.chunks):
                continue
            chunk = self.chunks[idx]
            if target_companies and chunk.company_name.lower() not in target_companies:
                continue

            results.append((chunk, float(dist)))
            if len(results) >= top_k:
                break

        return results

    def remove_chunks_by_document(self, doc_id: int):
        """Removes all chunks belonging to a document and rebuilds FAISS index instantly from memory."""
        initial_count = len(self.chunks)
        keep_indices = [i for i, c in enumerate(self.chunks) if getattr(c, 'document_id', None) != doc_id]
        if len(keep_indices) == initial_count:
            return

        if self.index is not None and self.index.ntotal == initial_count and initial_count > 0:
            if keep_indices:
                all_vectors = self.index.reconstruct_n(0, initial_count)
                kept_vectors = all_vectors[keep_indices]
                self.chunks = [self.chunks[i] for i in keep_indices]
                self.index = faiss.IndexFlatIP(self.dimension)
                self.index.add(kept_vectors.astype(np.float32))
            else:
                self.chunks = []
                self.index = faiss.IndexFlatIP(self.dimension)
        else:
            self.chunks = [self.chunks[i] for i in keep_indices]
            self.index = faiss.IndexFlatIP(self.dimension)
            if self.chunks:
                from indexing.embeddings import EmbeddingEngine
                eng = EmbeddingEngine()
                embeddings = eng.embed_texts([c.text for c in self.chunks])
                self.index.add(embeddings.astype(np.float32))

        self.save()
        logger.info(f"Removed chunks for document {doc_id}. Remaining vectors: {self.index.ntotal if self.index else 0}")

    def update_document_name(self, doc_id: int, new_name: str):
        """Updates document name metadata on matching chunks."""
        updated = False
        for c in self.chunks:
            if getattr(c, 'document_id', None) == doc_id:
                c.document_name = new_name
                updated = True
        if updated:
            self.save()

    def save(self):
        """Persists the FAISS index and chunk metadata."""
        if self.index is not None:
            faiss.write_index(self.index, self.index_path)
            with open(self.meta_path, "w", encoding="utf-8") as f:
                json.dump([c.model_dump() for c in self.chunks], f, ensure_ascii=False, indent=2)
            logger.info(f"Saved FAISS index ({self.index.ntotal} vectors) to {self.index_path}")

    def _load(self):
        """Loads index and metadata if present."""
        if os.path.exists(self.index_path) and os.path.exists(self.meta_path):
            try:
                self.index = faiss.read_index(self.index_path)
                with open(self.meta_path, "r", encoding="utf-8") as f:
                    meta_list = json.load(f)
                self.chunks = [DocumentChunk(**item) for item in meta_list]
                logger.info(f"Loaded FAISS index with {self.index.ntotal} vectors.")
            except Exception as e:
                logger.error(f"Error loading FAISS store: {e}")
                self.index = faiss.IndexFlatIP(self.dimension)
                self.chunks = []
        else:
            self.index = faiss.IndexFlatIP(self.dimension)
            self.chunks = []


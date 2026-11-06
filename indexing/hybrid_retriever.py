import logging
from typing import List, Optional, Dict
from config import Config
from core.models import DocumentChunk, RetrievalResult
from indexing.embeddings import EmbeddingEngine
from indexing.vector_store import DenseVectorStore
from indexing.bm25_index import BM25IndexStore

logger = logging.getLogger(__name__)

class HybridRetriever:
    """
    Enterprise Hybrid Retrieval Engine.
    Executes unified dense vector search and sparse BM25 lexical search with
    company-level pre-filtering and Reciprocal Rank Fusion (RRF).
    """

    def __init__(self):
        self.embedding_engine = EmbeddingEngine()
        self.vector_store = DenseVectorStore()
        self.bm25_store = BM25IndexStore()
        self.alpha = Config.HYBRID_ALPHA  # Weight for dense vector search (0.0 to 1.0)
        self.sync_with_database()

    def sync_with_database(self):
        """
        Validates index files against the active documents table in SQLite.
        Purges any orphan chunks from deleted documents and syncs document names.
        """
        from db.repositories import DocumentRepository
        try:
            active_docs = DocumentRepository.get_all()
            valid_doc_map = {d['id']: d['original_name'] for d in active_docs}
            
            # Check vector store
            orphan_vector_chunks = [c for c in self.vector_store.chunks if getattr(c, 'document_id', None) not in valid_doc_map]
            sync_needed = len(orphan_vector_chunks) > 0
            if not sync_needed:
                for c in self.vector_store.chunks:
                    doc_id = getattr(c, 'document_id', None)
                    if doc_id in valid_doc_map and c.document_name != valid_doc_map[doc_id]:
                        c.document_name = valid_doc_map[doc_id]
                        sync_needed = True

            if sync_needed:
                logger.warning(f"Synchronizing FAISS vector store with active SQLite documents...")
                self.vector_store.chunks = [c for c in self.vector_store.chunks if getattr(c, 'document_id', None) in valid_doc_map]
                for c in self.vector_store.chunks:
                    c.document_name = valid_doc_map[getattr(c, 'document_id', None)]
                import faiss, numpy as np
                self.vector_store.index = faiss.IndexFlatIP(self.vector_store.dimension)
                if self.vector_store.chunks:
                    embeddings = self.embedding_engine.embed_texts([c.text for c in self.vector_store.chunks])
                    self.vector_store.index.add(embeddings.astype(np.float32))
                self.vector_store.save()

            # Check BM25 store
            orphan_bm25_chunks = [c for c in self.bm25_store.chunks if getattr(c, 'document_id', None) not in valid_doc_map]
            bm25_sync_needed = len(orphan_bm25_chunks) > 0
            if not bm25_sync_needed:
                for c in self.bm25_store.chunks:
                    doc_id = getattr(c, 'document_id', None)
                    if doc_id in valid_doc_map and c.document_name != valid_doc_map[doc_id]:
                        c.document_name = valid_doc_map[doc_id]
                        bm25_sync_needed = True

            if bm25_sync_needed:
                logger.warning(f"Synchronizing BM25 store with active SQLite documents...")
                filtered_chunks = []
                filtered_tokens = []
                for chunk, tokens in zip(self.bm25_store.chunks, self.bm25_store.tokenized_corpus):
                    doc_id = getattr(chunk, 'document_id', None)
                    if doc_id in valid_doc_map:
                        chunk.document_name = valid_doc_map[doc_id]
                        filtered_chunks.append(chunk)
                        filtered_tokens.append(tokens)
                self.bm25_store.chunks = filtered_chunks
                self.bm25_store.tokenized_corpus = filtered_tokens
                self.bm25_store._build_index()
                self.bm25_store.save()
        except Exception as e:
            logger.warning(f"Auto-sync indices with database skipped: {e}")

    def index_document_chunks(self, chunks: List[DocumentChunk]):
        """Indexes newly parsed chunks into both Dense FAISS and Sparse BM25 stores."""
        if not chunks:
            return

        logger.info(f"Indexing {len(chunks)} chunks into Hybrid Retrieval Store...")
        
        # 1. Generate dense embeddings and store in FAISS
        chunk_texts = [c.text for c in chunks]
        embeddings = self.embedding_engine.embed_texts(chunk_texts)
        self.vector_store.add_chunks(chunks, embeddings)

        # 2. Add to BM25 sparse index
        self.bm25_store.add_chunks(chunks)
        logger.info("Hybrid indexing complete.")

    def remove_document(self, doc_id: int):
        """Removes all indexed chunks for a document from both FAISS and BM25 stores."""
        self.vector_store.remove_chunks_by_document(doc_id)
        self.bm25_store.remove_chunks_by_document(doc_id)
        logger.info(f"Purged document {doc_id} from hybrid retrieval stores.")

    def rename_document(self, doc_id: int, new_name: str):
        """Updates chunk metadata with the new document name."""
        self.vector_store.update_document_name(doc_id, new_name)
        self.bm25_store.update_document_name(doc_id, new_name)
        logger.info(f"Updated document {doc_id} name to '{new_name}' in hybrid retrieval stores.")

    def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        company_names: Optional[List[str]] = None,
        allowed_doc_ids: Optional[set] = None
    ) -> List[RetrievalResult]:
        """
        Retrieves top_k chunks for query, filtered by company_names and allowed_doc_ids.
        Uses Reciprocal Rank Fusion (RRF) to merge dense and sparse rankings.
        """
        k = top_k or Config.TOP_K_RETRIEVAL
        target_companies = [c.strip() for c in company_names if c.strip()] if company_names else None

        # 1. Dense Vector Search
        query_vector = self.embedding_engine.embed_query(query)
        dense_results = self.vector_store.search(
            query_vector=query_vector,
            top_k=k * 3,
            company_names=target_companies
        )

        # 2. Sparse BM25 Search
        bm25_results = self.bm25_store.search(
            query=query,
            top_k=k * 3,
            company_names=target_companies
        )

        # 3. Reciprocal Rank Fusion (RRF)
        # RRF_score(d) = alpha / (60 + rank_dense) + (1 - alpha) / (60 + rank_bm25)
        rrf_constant = 60.0
        scores: Dict[str, float] = {}
        chunk_map: Dict[str, DocumentChunk] = {}
        source_map: Dict[str, str] = {}

        for rank, (chunk, score) in enumerate(dense_results):
            cid = chunk.chunk_id
            chunk_map[cid] = chunk
            scores[cid] = scores.get(cid, 0.0) + (self.alpha / (rrf_constant + rank + 1))
            source_map[cid] = "vector"

        for rank, (chunk, score) in enumerate(bm25_results):
            cid = chunk.chunk_id
            chunk_map[cid] = chunk
            sparse_score = (1.0 - self.alpha) / (rrf_constant + rank + 1)
            scores[cid] = scores.get(cid, 0.0) + sparse_score
            source_map[cid] = "hybrid" if cid in source_map else "bm25"

        # Sort candidate chunks by combined RRF score descending
        sorted_cids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

        # Cross-reference active documents from SQLite to prevent any orphan chunks
        from db.repositories import DocumentRepository
        try:
            active_docs = DocumentRepository.get_all()
            valid_doc_map = {d['id']: d['original_name'] for d in active_docs}
        except Exception as e:
            logger.warning(f"Could not load active doc map in retrieve: {e}")
            valid_doc_map = None

        final_results: List[RetrievalResult] = []
        for cid in sorted_cids:
            chunk = chunk_map[cid]
            doc_id = getattr(chunk, 'document_id', None)
            if allowed_doc_ids is not None and doc_id not in allowed_doc_ids:
                # Enforce multi-tenant user document privacy isolation
                continue
            if valid_doc_map is not None:
                if doc_id not in valid_doc_map:
                    # Skip orphan chunks belonging to deleted or untracked documents
                    continue
                chunk.document_name = valid_doc_map[doc_id]

            final_results.append(
                RetrievalResult(
                    chunk=chunk,
                    score=float(scores[cid]),
                    retrieval_source=source_map.get(cid, "hybrid")
                )
            )
            if len(final_results) >= k:
                break

        logger.info(
            f"Hybrid retrieval for '{query[:40]}...' (Companies: {target_companies}) "
            f"returned {len(final_results)} chunks (Dense found: {len(dense_results)}, BM25 found: {len(bm25_results)})."
        )
        return final_results

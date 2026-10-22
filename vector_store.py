import os
import json
import logging
import numpy as np
import faiss
from config import Config

logger = logging.getLogger(__name__)

class VectorStore:
    def __init__(self, report_id):
        self.report_id = report_id
        self.index_path = os.path.join(Config.VECTOR_INDEX_FOLDER, f"report_{report_id}.index")
        self.meta_path = os.path.join(Config.VECTOR_INDEX_FOLDER, f"report_{report_id}.meta")
        self.index = None
        self.metadata = []

    def save(self, embeddings, chunks_with_sources):
        """
        Saves vectors into a FAISS index and stores chunk text & sources to a metadata file.
        Normalizes vectors first for cosine similarity.
        """
        if not embeddings:
            logger.warning("Empty embeddings list passed. Saving skipped.")
            return False

        try:
            embeddings_np = np.array(embeddings).astype('float32')
            # Normalize vectors to unit length for Cosine Similarity (via Inner Product)
            faiss.normalize_L2(embeddings_np)
            
            dimension = embeddings_np.shape[1]
            # Use IndexFlatIP for Inner Product (Cosine Similarity on normalized vectors)
            self.index = faiss.IndexFlatIP(dimension)
            self.index.add(embeddings_np)
            
            # Save index to disk
            faiss.write_index(self.index, self.index_path)
            
            # Save metadata to disk
            self.metadata = chunks_with_sources
            with open(self.meta_path, 'w', encoding='utf-8') as f:
                json.dump(self.metadata, f, ensure_ascii=False, indent=2)
                
            logger.info(f"FAISS index and metadata saved successfully for report {self.report_id}.")
            return True
        except Exception as e:
            logger.error(f"Error saving FAISS index for report {self.report_id}: {e}")
            raise RuntimeError(f"FAISS Vector Store Save Error: {str(e)}")

    def _load(self):
        """Loads index and metadata from disk if not already loaded in memory."""
        if self.index is not None and self.metadata:
            return True
            
        if not os.path.exists(self.index_path) or not os.path.exists(self.meta_path):
            logger.warning(f"Index or metadata file missing for report {self.report_id}.")
            return False
            
        try:
            self.index = faiss.read_index(self.index_path)
            with open(self.meta_path, 'r', encoding='utf-8') as f:
                self.metadata = json.load(f)
            return True
        except Exception as e:
            logger.error(f"Error loading FAISS index for report {self.report_id}: {e}")
            return False

    def search(self, query_embedding, k=5):
        """
        Searches the FAISS index for the k most similar chunks to the query.
        Returns a list of dicts containing the chunk text, source reference, and similarity score.
        """
        if not self._load():
            logger.error(f"Could not perform search: Index files not loaded for report {self.report_id}.")
            return []
            
        try:
            query_np = np.array([query_embedding]).astype('float32')
            # Normalize query vector
            faiss.normalize_L2(query_np)
            
            # Search
            distances, indices = self.index.search(query_np, k)
            
            results = []
            for score, idx in zip(distances[0], indices[0]):
                # FAISS returns -1 for empty/out-of-bound indices
                if idx == -1 or idx >= len(self.metadata):
                    continue
                    
                chunk_meta = self.metadata[idx]
                results.append({
                    'text': chunk_meta['text'],
                    'source': chunk_meta['source'],
                    'score': float(score)  # Cosine similarity score
                })
                
            logger.info(f"FAISS search completed for report {self.report_id}. Found {len(results)} matches.")
            return results
        except Exception as e:
            logger.error(f"Error searching FAISS index: {e}")
            return []
            
    @classmethod
    def get_index_status(cls, report_id):
        """Utility to verify if a report's vector index files exist."""
        index_path = os.path.join(Config.VECTOR_INDEX_FOLDER, f"report_{report_id}.index")
        meta_path = os.path.join(Config.VECTOR_INDEX_FOLDER, f"report_{report_id}.meta")
        return os.path.exists(index_path) and os.path.exists(meta_path)

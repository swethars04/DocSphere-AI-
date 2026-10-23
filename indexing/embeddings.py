import logging
from typing import List
import numpy as np
from config import Config

logger = logging.getLogger(__name__)

class EmbeddingEngine:
    """Generates normalized dense vector embeddings using local SentenceTransformers."""
    
    _instance = None
    _model = None

    def __new__(cls):
        # Singleton pattern to prevent multiple copies of the model in memory
        if cls._instance is None:
            cls._instance = super(EmbeddingEngine, cls).__new__(cls)
            cls._instance._model = None
        return cls._instance

    def _get_model(self):
        """Lazy loader for SentenceTransformer to conserve memory on cloud startup."""
        if self._model is None:
            import os
            os.environ["TOKENIZERS_PARALLELISM"] = "false"
            os.environ["OMP_NUM_THREADS"] = "1"
            import torch
            torch.set_num_threads(1)
            torch.set_grad_enabled(False)
            from sentence_transformers import SentenceTransformer
            model_name = Config.EMBEDDING_MODEL_NAME
            logger.info(f"Loading local SentenceTransformer model: {model_name}...")
            try:
                self._model = SentenceTransformer(model_name, local_files_only=True)
            except Exception:
                self._model = SentenceTransformer(model_name)
            logger.info(f"Loaded {model_name} successfully.")
        return self._model

    def embed_texts(self, texts: List[str]) -> np.ndarray:
        """
        Embeds a list of strings into normalized float32 vectors.
        Returns numpy array of shape (N, dimension).
        """
        if not texts:
            return np.empty((0, 384), dtype=np.float32)

        # Sanitize texts
        model = self._get_model()
        clean_texts = [t.replace('\n', ' ').strip() for t in texts]
        embeddings = model.encode(
            clean_texts,
            batch_size=32,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False
        )
        return embeddings.astype(np.float32)

    def embed_query(self, query: str) -> np.ndarray:
        """Embeds a single query string into a normalized 1D vector."""
        vec = self.embed_texts([query])
        return vec[0]

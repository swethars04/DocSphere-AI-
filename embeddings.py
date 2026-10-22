import logging
from sentence_transformers import SentenceTransformer
from config import Config

logger = logging.getLogger(__name__)

class ApiKeyMissingException(Exception):
    """Exception raised when the Groq API key is missing."""
    pass

class EmbeddingGenerator:
    def __init__(self):
        # We verify that a Groq API Key is configured for dashboard error notifications
        if not Config.GROQ_API_KEY or Config.GROQ_API_KEY.strip() == "":
            logger.warning("Groq API key is missing. Embeddings API key validation failed.")
            raise ApiKeyMissingException("Groq API key is missing.")

        self.model_name = "all-MiniLM-L6-v2"
        logger.info(f"Initializing local EmbeddingGenerator with model: {self.model_name}...")
        try:
            self.model = SentenceTransformer(self.model_name)
            logger.info("Local SentenceTransformer model loaded successfully.")
        except Exception as e:
            logger.error(f"Error loading local SentenceTransformer model: {e}")
            raise RuntimeError(f"Model load error: {str(e)}")

    def generate_embeddings(self, texts):
        """
        Generates embeddings for a list of texts locally using SentenceTransformer.
        """
        if not texts:
            return []
            
        try:
            # Replace newlines with spaces
            clean_texts = [text.replace("\n", " ") for text in texts]
            # Generate embeddings locally (returns numpy array of shape (N, 384))
            embeddings = self.model.encode(clean_texts, show_progress_bar=False)
            # Convert to standard Python lists
            embeddings_list = [emb.tolist() for emb in embeddings]
            
            logger.info(f"Successfully generated {len(embeddings_list)} embeddings locally.")
            return embeddings_list
            
        except Exception as e:
            logger.error(f"Error generating local embeddings: {e}")
            raise RuntimeError(f"Local Embedding Error: {str(e)}")
            
    def generate_single_embedding(self, text):
        """Generates embedding for a single text query."""
        res = self.generate_embeddings([text])
        return res[0] if res else []

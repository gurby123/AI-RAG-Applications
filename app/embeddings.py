import os
from typing import List

from sentence_transformers import SentenceTransformer

from .ollama_client import OllamaClient

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
USE_OLLAMA_EMBED = os.getenv("USE_OLLAMA_EMBED", "false").lower() == "true"
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

class EmbeddingService:
	def __init__(self) -> None:
		self._local_model = None if USE_OLLAMA_EMBED else SentenceTransformer(EMBEDDING_MODEL)
		self._ollama = OllamaClient() if USE_OLLAMA_EMBED else None

	def embed_documents(self, texts: List[str]) -> List[List[float]]:
		if self._ollama is not None:
			return self._ollama.embed(texts, model=OLLAMA_EMBED_MODEL)
		# Ensure NumPy arrays returned, then convert to plain lists
		vectors = self._local_model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
		return vectors.tolist()

	def embed_query(self, text: str) -> List[float]:
		return self.embed_documents([text])[0]
import os
from typing import List, Dict, Optional

from .embeddings import EmbeddingService
from .text_processing import extract_text_from_pdf, chunk_text
from .vector_store import FaissStore
from .ollama_client import OllamaClient
from .prompts import SYSTEM_PROMPT, STRATEGY_PROMPT
from .web_search import web_search as ddg_search

INDEX_DIR = os.getenv("INDEX_DIR", ".rag_index")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1200"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))
TOP_K = int(os.getenv("TOP_K", "8"))
WEB_RESULTS = int(os.getenv("WEB_RESULTS", "5"))

class RAGPipeline:
	def __init__(self) -> None:
		self.embedder = EmbeddingService()
		self.chat = OllamaClient()
		self.store: Optional[FaissStore] = None
		self._ensure_store()

	def _ensure_store(self) -> None:
		if self.store is None:
			# Obtain embedding dimension from a sample
			sample_vector = self.embedder.embed_query("dimension probe")
			dim = len(sample_vector)
			self.store = FaissStore(dim=dim, index_dir=INDEX_DIR)
			if os.path.exists(os.path.join(INDEX_DIR, "index.faiss")):
				self.store.load()

	def index_pdf(self, pdf_path: str) -> int:
		self._ensure_store()
		text = extract_text_from_pdf(pdf_path)
		chunks = chunk_text(text, chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
		texts = [c["text"] for c in chunks]
		embs = self.embedder.embed_documents(texts)
		metas = [{"text": t, "source": os.path.basename(pdf_path), "chunk_i": i} for i, t in enumerate(texts)]
		self.store.add(embs, metas)
		self.store.save()
		return len(texts)

	def retrieve(self, query: str, top_k: int = TOP_K) -> List[Dict]:
		self._ensure_store()
		q = self.embedder.embed_query(query)
		results = self.store.search(q, top_k=top_k)
		augmented = []
		for i, (score, md) in enumerate(results):
			augmented.append({"chunk_i": md.get("chunk_i", i), "score": score, "text": md.get("text", ""), "source": md.get("source", "")})
		return augmented

	def answer(self, question: str, use_web: bool = False) -> Dict[str, str]:
		contexts = self.retrieve(question, top_k=TOP_K)
		context_text = "\n\n".join([f"[chunk_{c['chunk_i']}] {c['text']}" for c in contexts])
		web_text = ""
		if use_web:
			web_results = ddg_search(question, max_results=WEB_RESULTS)
			web_text = "\n\n".join([f"[web_{i}] {w['title']} - {w['href']}\n{w['body']}" for i, w in enumerate(web_results)])
		messages = [
			{"role": "system", "content": SYSTEM_PROMPT},
			{"role": "user", "content": STRATEGY_PROMPT.format(context=context_text, web=web_text or "None", question=question)},
		]
		answer_text = self.chat.chat(messages)
		return {"answer": answer_text, "citations": contexts}
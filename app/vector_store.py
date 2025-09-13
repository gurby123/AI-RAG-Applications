import os
import json
from typing import List, Tuple

import numpy as np
import faiss

class FaissStore:
	def __init__(self, dim: int, index_dir: str) -> None:
		self.dim = dim
		self.index_dir = index_dir
		self.index_path = os.path.join(index_dir, "index.faiss")
		self.meta_path = os.path.join(index_dir, "metadatas.jsonl")
		self.index = faiss.IndexFlatIP(dim)
		self.metadatas: List[dict] = []

	def add(self, embeddings: List[List[float]], metadatas: List[dict]) -> None:
		if not embeddings:
			return
		vectors = np.array(embeddings, dtype=np.float32)
		faiss.normalize_L2(vectors)
		self.index.add(vectors)
		self.metadatas.extend(metadatas)

	def search(self, query_embedding: List[float], top_k: int = 8) -> List[Tuple[float, dict]]:
		q = np.array([query_embedding], dtype=np.float32)
		faiss.normalize_L2(q)
		distances, indices = self.index.search(q, top_k)
		results: List[Tuple[float, dict]] = []
		for score, idx in zip(distances[0], indices[0]):
			if idx == -1:
				continue
			results.append((float(score), self.metadatas[int(idx)]))
		return results

	def save(self) -> None:
		os.makedirs(self.index_dir, exist_ok=True)
		faiss.write_index(self.index, self.index_path)
		with open(self.meta_path, "w", encoding="utf-8") as f:
			for md in self.metadatas:
				f.write(json.dumps(md, ensure_ascii=False) + "\n")

	def load(self) -> None:
		if os.path.exists(self.index_path):
			self.index = faiss.read_index(self.index_path)
		if os.path.exists(self.meta_path):
			self.metadatas = []
			with open(self.meta_path, "r", encoding="utf-8") as f:
				for line in f:
					self.metadatas.append(json.loads(line))
import os
import requests
from typing import List, Dict, Optional

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://192.168.2.200:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:latest")

class OllamaClient:
	def __init__(self, base_url: Optional[str] = None, model: Optional[str] = None) -> None:
		self.base_url = base_url or OLLAMA_BASE_URL
		self.model = model or OLLAMA_MODEL

	def chat(self, messages: List[Dict[str, str]], temperature: float = 0.2, stream: bool = False) -> str:
		url = f"{self.base_url}/api/chat"
		payload = {
			"model": self.model,
			"messages": messages,
			"options": {"temperature": temperature},
			"stream": stream,
		}
		resp = requests.post(url, json=payload, timeout=120)
		resp.raise_for_status()
		if stream:
			chunks = []
			for line in resp.iter_lines():
				if not line:
					continue
				chunks.append(line.decode("utf-8"))
			return "".join(chunks)
		return resp.json().get("message", {}).get("content", "")

	def embed(self, input_texts: List[str], model: str = "nomic-embed-text") -> List[List[float]]:
		url = f"{self.base_url}/api/embeddings"
		payload = {"model": model, "input": input_texts}
		resp = requests.post(url, json=payload, timeout=120)
		resp.raise_for_status()
		data = resp.json()
		# Ollama returns {embeddings: [[...], ...]}
		return data.get("embeddings", [])
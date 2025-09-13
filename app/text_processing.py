from typing import List, Dict

from pypdf import PdfReader


def extract_text_from_pdf(file_path: str) -> str:
	reader = PdfReader(file_path)
	texts: List[str] = []
	for page in reader.pages:
		content = page.extract_text() or ""
		if content:
			texts.append(content)
	return "\n".join(texts)


def chunk_text(text: str, chunk_size: int = 1200, chunk_overlap: int = 200) -> List[Dict[str, str]]:
	chunks: List[Dict[str, str]] = []
	start = 0
	length = len(text)
	while start < length:
		end = min(start + chunk_size, length)
		chunk = text[start:end]
		chunks.append({"text": chunk})
		if end == length:
			break
		start = max(end - chunk_overlap, 0)
	return chunks
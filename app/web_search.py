from typing import List, Dict

from duckduckgo_search import DDGS


def web_search(query: str, max_results: int = 5) -> List[Dict[str, str]]:
	with DDGS() as ddgs:
		results = ddgs.text(query, max_results=max_results)
	output: List[Dict[str, str]] = []
	for item in results:
		output.append({
			"title": item.get("title", ""),
			"href": item.get("href", ""),
			"body": item.get("body", ""),
		})
	return output
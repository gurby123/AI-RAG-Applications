import io
import json
import textwrap
from typing import List, Dict, Any

import requests
import streamlit as st
from docx import Document


def read_docx_text(uploaded_file) -> str:
	"""Extracts text from a .docx file-like object."""
	try:
		doc = Document(uploaded_file)
		paragraph_texts = [p.text for p in doc.paragraphs]
		# Include text from tables as well
		for tbl in doc.tables:
			for row in tbl.rows:
				for cell in row.cells:
					paragraph_texts.append(cell.text)
			# Avoid duplicate cell text due to shared cell objects
		paragraph_text = "\n".join([t for t in paragraph_texts if t and t.strip()])
		return paragraph_text.strip()
	except Exception as exc:
		raise ValueError(f"Failed to read .docx: {exc}")


def chunk_text(text: str, max_chars: int = 3000, overlap: int = 300) -> List[str]:
	"""Simple character-based chunking with overlap."""
	if not text:
		return []
	text = text.strip()
	if len(text) <= max_chars:
		return [text]
	chunks: List[str] = []
	start = 0
	end = max_chars
	while start < len(text):
		chunks.append(text[start:end])
		start = end - overlap
		if start < 0:
			start = 0
		end = start + max_chars
	return chunks


def ollama_chat(
	base_url: str,
	model: str,
	messages: List[Dict[str, str]],
	temperature: float = 0.2,
	timeout_seconds: int = 600,
) -> str:
	"""Calls Ollama's /api/chat endpoint and returns the assistant message content."""
	url = f"{base_url.rstrip('/')}/api/chat"
	payload: Dict[str, Any] = {
		"model": model,
		"messages": messages,
		"options": {"temperature": temperature},
		"stream": False,
	}
	try:
		resp = requests.post(url, json=payload, timeout=timeout_seconds)
		resp.raise_for_status()
		data = resp.json()
		# Ollama chat non-stream response typically includes "message": {"role": "assistant", "content": "..."}
		message = data.get("message", {})
		content = message.get("content", "")
		if not content and isinstance(data, dict):
			# Fallback in case of different structure
			content = data.get("content", "")
		return content
	except requests.RequestException as exc:
		raise RuntimeError(f"Failed to reach Ollama at {url}: {exc}")
	except json.JSONDecodeError as exc:
		raise RuntimeError(f"Invalid JSON from Ollama at {url}: {exc}")


def build_summarize_prompt() -> str:
	return (
		"You are an expert management consultant. Summarize the following document chunk "
		"to capture only facts and insights relevant to the McKinsey 7S elements: Strategy, Structure, Systems, Shared Values, Style, Staff, Skills. "
		"Write concise bullet points per S. Avoid repetition and speculation."
	)


def build_consolidation_prompt() -> str:
	return (
		"You will receive multiple chunk-level summaries aligned to the McKinsey 7S model. "
		"Consolidate them into a single, de-duplicated, coherent 7S summary with clear bullets under each S."
	)


def build_7s_analysis_prompt() -> str:
	return textwrap.dedent(
		"""
		You are a senior strategy consultant. Using the consolidated understanding of the organization, produce a rigorous McKinsey 7S analysis.

		For each of the 7S elements, provide:
		- Current State (facts/observations)
		- Strengths
		- Gaps/Issues
		- Root Causes (if inferable from evidence)
		- Implications/Risks
		- Opportunities

		Return the result as well-structured markdown with clear H2 headings for each S and H3 subheadings for the sections above. Be specific, evidence-based, and concise.
		"""
	).strip()


def build_strategic_plan_prompt() -> str:
	return textwrap.dedent(
		"""
		Based on the 7S analysis, generate a complete, pragmatic strategic plan suitable for executive consumption.

		Include the following sections with clear headings and bullet points/tables where helpful:
		1) Executive Summary
		2) Vision and Strategic Objectives (SMART)
		3) Strategic Themes linked to 7S (traceability)
		4) Portfolio of Initiatives (with owner, expected outcomes, effort, value)
		5) 12–24 Month Roadmap (quarterly timeline)
		6) Operating Model Changes (Structure/Systems/Style adjustments)
		7) Capability Uplifts (Staff/Skills)
		8) Change Management & Communications Plan
		9) Governance & Decision Rights
		10) KPIs & Leading Indicators (with baseline and target)
		11) Risks & Mitigations
		12) Budget & Resource Summary (rough order of magnitude)
		13) Dependencies & Assumptions

		Write in crisp, action-oriented business language. Ensure alignment back to each S where relevant. Return markdown.
		"""
	).strip()


def summarize_chunks(
	base_url: str,
	model: str,
	chunks: List[str],
	temperature: float,
) -> List[str]:
	summaries: List[str] = []
	prompt = build_summarize_prompt()
	for idx, chunk in enumerate(chunks, start=1):
		messages = [
			{"role": "system", "content": prompt},
			{"role": "user", "content": f"Chunk {idx}:\n\n{chunk}"},
		]
		summary = ollama_chat(base_url, model, messages, temperature=temperature)
		summaries.append(summary.strip())
	return summaries


def consolidate_summaries(
	base_url: str,
	model: str,
	chunk_summaries: List[str],
	temperature: float,
) -> str:
	consolidation_prompt = build_consolidation_prompt()
	joined = "\n\n".join([f"Summary {i+1}:\n{txt}" for i, txt in enumerate(chunk_summaries)])
	messages = [
		{"role": "system", "content": consolidation_prompt},
		{"role": "user", "content": joined},
	]
	return ollama_chat(base_url, model, messages, temperature=temperature).strip()


def perform_7s_analysis(
	base_url: str,
	model: str,
	consolidated_context: str,
	temperature: float,
) -> str:
	messages = [
		{"role": "system", "content": build_7s_analysis_prompt()},
		{"role": "user", "content": consolidated_context},
	]
	return ollama_chat(base_url, model, messages, temperature=temperature).strip()


def generate_strategic_plan(
	base_url: str,
	model: str,
	seven_s_analysis_markdown: str,
	temperature: float,
) -> str:
	messages = [
		{"role": "system", "content": build_strategic_plan_prompt()},
		{"role": "user", "content": seven_s_analysis_markdown},
	]
	return ollama_chat(base_url, model, messages, temperature=temperature).strip()


def create_plan_docx(
	original_filename: str,
	seven_s_analysis_markdown: str,
	strategic_plan_markdown: str,
) -> bytes:
	"""Create a .docx containing the analysis and plan; return the bytes."""
	doc = Document()
	doc.add_heading("McKinsey 7S Analysis & Strategic Plan", level=1)
	doc.add_paragraph(f"Source document: {original_filename}")

	doc.add_heading("7S Analysis", level=2)
	for line in seven_s_analysis_markdown.splitlines():
		if line.startswith("## "):
			doc.add_heading(line.replace("## ", ""), level=2)
		elif line.startswith("### "):
			doc.add_heading(line.replace("### ", ""), level=3)
		elif line.startswith("- "):
			p = doc.add_paragraph(line[2:])
			p.style = "List Bullet"
		else:
			if line.strip():
				doc.add_paragraph(line)

	doc.add_heading("Strategic Plan", level=2)
	for line in strategic_plan_markdown.splitlines():
		if line.startswith("## "):
			doc.add_heading(line.replace("## ", ""), level=2)
		elif line.startswith("### "):
			doc.add_heading(line.replace("### ", ""), level=3)
		elif line[:2].isdigit() and ") " in line[:5]:
			# support for ordered list like "1) Item"
			p = doc.add_paragraph(line)
			p.style = "List Number"
		elif line.startswith("- "):
			p = doc.add_paragraph(line[2:])
			p.style = "List Bullet"
		else:
			if line.strip():
				doc.add_paragraph(line)

	buffer = io.BytesIO()
	doc.save(buffer)
	buffer.seek(0)
	return buffer.getvalue()


def main() -> None:
	st.set_page_config(page_title="7S Analyzer & Strategy Generator", layout="wide")
	st.title("McKinsey 7S Analysis and Strategic Plan Generator")
	st.caption("Powered by Ollama (Llama 3.1)")

	with st.sidebar:
		st.header("Model Settings")
		default_base = st.text_input("Ollama Base URL", value="http://192.168.2.200:11434")
		model_name = st.text_input("Model", value="llama3.1")
		temperature = st.slider("Temperature", min_value=0.0, max_value=1.0, value=0.2, step=0.05)
		max_chars = st.number_input("Chunk size (chars)", min_value=1000, max_value=12000, value=3000, step=500)
		overlap = st.number_input("Chunk overlap (chars)", min_value=0, max_value=2000, value=300, step=50)

	uploaded = st.file_uploader("Upload a .docx file", type=["docx"])
	run = st.button("Analyze and Generate Plan", type="primary", disabled=(uploaded is None))

	if run and uploaded is not None:
		with st.spinner("Reading document..."):
			try:
				full_text = read_docx_text(uploaded)
				if not full_text:
					st.error("No readable text found in the document.")
					return
				chunks = chunk_text(full_text, max_chars=int(max_chars), overlap=int(overlap))
				st.success(f"Loaded document and created {len(chunks)} chunk(s).")
			except Exception as exc:
				st.error(str(exc))
				return

		st.subheader("Step 1: Chunk Summaries (7S-focused)")
		chunk_placeholders = [st.empty() for _ in chunks]
		chunk_summaries: List[str] = []
		for i, chunk in enumerate(chunks):
			chunk_placeholders[i].info(f"Summarizing chunk {i+1}/{len(chunks)}...")
			try:
				summary = summarize_chunks(default_base, model_name, [chunk], temperature)[0]
				chunk_summaries.append(summary)
				chunk_placeholders[i].success(f"Chunk {i+1} summarized.")
			except Exception as exc:
				chunk_placeholders[i].error(f"Failed to summarize chunk {i+1}: {exc}")
				return

		st.subheader("Step 2: Consolidation")
		try:
			consolidated = consolidate_summaries(default_base, model_name, chunk_summaries, temperature)
			st.success("Consolidated 7S understanding created.")
		except Exception as exc:
			st.error(f"Consolidation failed: {exc}")
			return

		st.subheader("Step 3: 7S Analysis")
		try:
			analysis_md = perform_7s_analysis(default_base, model_name, consolidated, temperature)
			with st.expander("Preview 7S Analysis"):
				st.markdown(analysis_md)
			st.success("7S analysis complete.")
			except Exception as exc:
				st.error(f"7S analysis failed: {exc}")
				return

		st.subheader("Step 4: Strategic Plan Generation")
		try:
			plan_md = generate_strategic_plan(default_base, model_name, analysis_md, temperature)
			with st.expander("Preview Strategic Plan"):
				st.markdown(plan_md)
			st.success("Strategic plan generated.")
			except Exception as exc:
				st.error(f"Plan generation failed: {exc}")
				return

		st.subheader("Step 5: Download Word Document")
		try:
			doc_bytes = create_plan_docx(uploaded.name, analysis_md, plan_md)
			st.download_button(
				label="Download Strategic Plan (.docx)",
				data=doc_bytes,
				file_name="7S_Strategic_Plan.docx",
				mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
			)
			st.success("Your document is ready to download.")
		except Exception as exc:
			st.error(f"Failed to create Word document: {exc}")


if __name__ == "__main__":
	main()


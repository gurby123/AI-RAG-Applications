import os
import tempfile

import streamlit as st

from app.rag_pipeline import RAGPipeline

st.set_page_config(page_title="Strategy RAG - Science and Art", page_icon="📘", layout="wide")

st.title("📘 Strategy RAG: Science and Art of Strategy")
with st.sidebar:
	st.header("Settings")
	ollama_base = st.text_input("Ollama Base URL", os.getenv("OLLAMA_BASE_URL", "http://192.168.2.200:11434"))
	ollama_model = st.text_input("Ollama Model", os.getenv("OLLAMA_MODEL", "llama3.1:latest"))
	index_dir = st.text_input("Index Directory", os.getenv("INDEX_DIR", ".rag_index"))
	chunk_size = st.number_input("Chunk Size", min_value=200, max_value=4000, value=int(os.getenv("CHUNK_SIZE", "1200")), step=100)
	chunk_overlap = st.number_input("Chunk Overlap", min_value=0, max_value=1000, value=int(os.getenv("CHUNK_OVERLAP", "200")), step=50)
	top_k = st.slider("Top K", min_value=3, max_value=20, value=int(os.getenv("TOP_K", "8")))
	use_web = st.checkbox("Use web search (DuckDuckGo)", value=False)

if "pipeline" not in st.session_state:
	# Initialize after user settings (env driven inside modules)
	st.session_state.pipeline = RAGPipeline()

st.subheader("1) Upload the book (PDF) and build index")
uploaded = st.file_uploader("Upload PDF of the book", type=["pdf"], accept_multiple_files=False)
if uploaded is not None:
	with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
		tmp.write(uploaded.getbuffer())
		tmp_path = tmp.name
	st.info("Indexing PDF...")
	count = st.session_state.pipeline.index_pdf(tmp_path)
	st.success(f"Indexed {count} chunks from {uploaded.name}")

st.subheader("2) Ask a strategic question")
col1, col2 = st.columns([3, 1])
with col1:
	question = st.text_area("Your question", height=120, placeholder="E.g., How should a mid-sized manufacturer enter a new market?")
with col2:
	st.caption("Options")
	use_web_opt = st.checkbox("Use web search", value=False, key="use_web_q")

if st.button("Generate Strategy Plan", type="primary"):
	if not question.strip():
		st.warning("Please enter a question.")
	else:
		with st.spinner("Thinking with RAG..."):
			result = st.session_state.pipeline.answer(question.strip(), use_web=use_web_opt)
			st.markdown("### Recommended Strategic Plan")
			st.write(result["answer"]) 
			with st.expander("Show citations"):
				for c in result["citations"]:
					st.markdown(f"- [chunk_{c['chunk_i']}] from {c['source']} (score={c['score']:.3f})")
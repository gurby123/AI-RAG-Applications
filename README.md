# 7S Analyzer & Strategic Plan Generator

A Streamlit app that analyzes an uploaded Word document using the McKinsey 7S model via an Ollama-hosted LLM (Llama 3.1), and produces a complete strategic plan downloadable as a Word document.

## Prerequisites

- Python 3.9+
- Access to an Ollama server with the Llama 3.1 model pulled and running
  - Default URL used by the app: `http://192.168.2.200:11434`
  - To pull and run the model on the Ollama host:
    ```bash
    ollama pull llama3.1
    ollama serve
    ```

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
streamlit run app.py
```

Then open the provided local URL in your browser. In the sidebar you can change the Ollama base URL and model if needed.

## Usage

1. Upload a `.docx` file containing information about the organization.
2. Click “Analyze and Generate Plan”. The app will:
   - Chunk and summarize the document with a 7S focus
   - Consolidate the 7S understanding
   - Produce a structured 7S analysis
   - Generate a comprehensive strategic plan
3. Download the resulting `.docx` document.

## Notes

- For large documents, processing can take several minutes depending on model performance and network latency.
- If your Ollama server requires a different host/port, update it in the sidebar.
- The app sends non-streaming chat requests to the `/api/chat` endpoint.

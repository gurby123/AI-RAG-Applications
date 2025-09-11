# Vision & Strategy Synthesizer (Streamlit + Ollama)

A Streamlit app that helps you synthesize strategy using multiple frameworks. Provide business issues, optionally upload a Word document, select frameworks (Reframing, Delphi, SCAMPER, Blue Ocean, Six Thinking Hats, Balanced Scorecard, McKinsey 7S, Burke-Litwin, TRIZ), and generate:

- 3+ distinct vision statements (via Ollama `llama3.1:latest`)
- A mission statement and 5+ strategic goals for the selected vision
- A downloadable Word document summarizing the analysis

## Prerequisites

- Python 3.9+
- Access to an Ollama server running `llama3.1:latest` (default assumed at `http://192.168.2.200:11434`).

On the Ollama host, ensure the model is available:

```bash
ollama pull llama3.1:latest
```

## Setup

From the project directory:

```bash
pip install -r requirements.txt
```

If the system is externally managed (PEP 668), you may need:

```bash
python3 -m pip install --break-system-packages -r requirements.txt
```

## Run the app

```bash
streamlit run app.py
```

Then open the local URL printed in the terminal.

## Using the app

- Enter business issues in the text area.
- Optionally upload a `.docx` Word document. The app extracts text from paragraphs and tables; expand the preview to verify.
- Toggle "Include uploaded document text" to merge it with the typed issues.
- Select one or more frameworks.
- Click "Generate vision options" to get at least three visions.
- Select a vision and click "Develop mission and goals".
- Use the "Download analysis.docx" button to export the full analysis.

## Configuration

You can set the Ollama host and model via environment variables or in the app sidebar:

- `OLLAMA_HOST` (default `http://192.168.2.200:11434`)
- `OLLAMA_MODEL` (default `llama3.1:latest`)

In the sidebar, you can also adjust `Temperature`.

## Notes

- The app calls Ollama's `POST /api/generate` endpoint for single-turn completions using a system and user prompt wrapper.
- Outputs are parsed from numbered lists; if fewer than three vision options are detected, the top lines are used as a fallback.
- The Word export highlights the selected vision in bold and lists goals numerically.
- Upload parsing reads paragraph and table cell text. Non-textual content is ignored.

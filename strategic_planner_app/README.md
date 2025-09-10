Burke–Litwin Strategic Planning App
===================================

What it does
------------
This Streamlit app ingests a user-uploaded Word document (.docx), analyzes it against the Burke–Litwin causal model using a rules-based approach, and generates a structured strategic plan. The plan is available for download as a Word document.

Key features
------------
- Upload .docx input (organizational context/current state)
- Automatic mapping to Burke–Litwin factors
- Prioritized objectives and initiatives (transformational and transactional)
- Downloadable strategic plan (.docx)

Quick start
----------
1. Create and activate a virtual environment (recommended):
   - Python 3.9+ recommended
```
python -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:
```
pip install -r requirements.txt
```

3. Run the app:
```
streamlit run app.py
```

4. In the browser:
   - Upload your .docx source document
   - Adjust settings in the left sidebar
   - Click "Generate Strategic Plan"
   - Download the plan with the provided button

Using Ollama (LLaMA 3.1)
------------------------
This app can optionally send the extracted text and heuristic factor summary to an Ollama server to produce a refined, board-ready narrative.

- Ensure you have an accessible Ollama server with the model available, for example:
  - Host: `192.168.2.200`
  - Port: `11434`
  - Model: `llama3.1` (or a local tag you use)

- In the app sidebar:
  - Check "Use Ollama LLaMA 3.1 to refine plan"
  - Set the host/port/model as needed
  - Adjust temperature if desired

- The LLM narrative will be displayed and embedded in the downloaded .docx.

Notes
-----
- The model is rule-based and uses keyword heuristics for salience; it does not require external APIs.
- You can adapt keywords for your domain by editing `BURKE_LITWIN_FACTORS` in `app.py`.
- Output is intended as a structured starting point for facilitation and refinement.

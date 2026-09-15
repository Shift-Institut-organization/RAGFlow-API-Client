# RAGFlow API Client & Automated Multi-Persona Pipeline

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Bruno CLI](https://img.shields.io/badge/API%20Client-Bruno-orange.svg)](https://www.usebruno.com/)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

Automates dataset seeding, document parsing, and multi-persona chat provisioning for [RAGFlow](https://ragflow.io/) using declarative [Bruno](https://www.usebruno.com/) API collections.

---

## Key Features

- **Easy transferable Bruno API Collections**
- **Full Automation from requirements to RAG Chat Personas**
- **Transfer Chats, talk with multiple chats simultanously**
- **Create Reports from Chats with Sources**
- **Transparent prompts in Markdown**

---

## Quickstart

### Prerequisites
- Python 3.10+
- Bruno CLI: `npm install -g @usebruno/cli`
- RAGFlow running locally or remotely (default: `http://localhost:9222`)

### 1. Setup
```bash
git clone https://github.com/Shift-Institut-organization/RAGFlow-API-Client.git
cd RAGFlow-API-Client

python -m venv .venv
.\.venv\Scripts\activate   # Windows
# source .venv/bin/activate # Linux/macOS

pip install -r requirements.txt
```

### 2. Configure (`.env`)
```env
BASE_URL=http://localhost:9222
RAGFLOW_API_KEY=<ragflow-your_key_here>
DATA_DIR=data/<project requirements and sources>
DEBUG=false
```

### 3. Run Tests
```bash
pytest
```

### 4. Run Pipeline
```bash
# 1. Extract features and requirements
python start_feature_extraction.py

# 2. Formulate personas, seed datasets, upload docs & parse
python start_persona_creation.py

# 3. Launch interactive multi-persona chat
python start_converse.py
```

---

## Data Directory Requirements (`data/<Project>/`)

The pipeline expects a project folder specified by `DATA_DIR` in `.env`:

```
data/<Project>/
├── requirements.md     # Markdown file explaining the project, its requirements and goals
└── sources/            # Directory containing raw files to upload (.pdf, .csv, .txt, etc.)
```

Both items are required:
- `requirements.md`: Parsed during feature extraction to discover personas and formulate system prompts.
- `sources/`: All files placed here are uploaded to the RAGFlow dataset and sequentially parsed.

> **Unique Project Names Required:** RAGFlow strictly enforces tenant-wide uniqueness for both dataset and chat names.
> - The RAGFlow dataset is named directly after your project folder (`<Project>`).
> - The system prompt generation chat is named `Create System Prompt Chats Auto - <Project>`.
> If a dataset or chat with the same name already exists on your RAGFlow instance, RAGFlow will reject creation requests with a duplicate name error

---

## Scripts & Usage

| Script | What It Does | Usage |
|---|---|---|
| [`start_feature_extraction.py`](start_feature_extraction.py) | Extracts explicit and inferred user features from project requirements into `user_features.json`. | `python start_feature_extraction.py` |
| [`start_persona_creation.py`](start_persona_creation.py) | Runs the 3-stage pipeline: generates persona prompts, provisions dataset & uploads/parses documents, creates chat assistants. | `python start_persona_creation.py` |
| [`start_converse.py`](start_converse.py) | Starts the interactive multi-persona terminal chat with persona switching and `/report` exports. | `python start_converse.py` |
| [`start_bruno.py`](start_bruno.py) | Bruno utility: runs single requests or syncs/clears `.env` tokens in collection files for Bruno Desktop App testing. | `python start_bruno.py --sync-tokens`<br>`python start_bruno.py --clear-tokens` |

---

## License

Apache 2.0 - see [LICENSE](LICENSE).

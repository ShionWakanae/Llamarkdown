# Project Overview
[![Me on CSDN](https://img.shields.io/badge/若苗瞬-CSDN-blue)](https://blog.csdn.net/ddrfan?type=blog)
[![Me on Bilibili](https://img.shields.io/badge/欢迎-bilibili-red?style=flat&logo=youtube)](https://space.bilibili.com/688222797)

[简体中文](README.md) | **English**

## What Is This Project About
> [!Note]
> Like this little cat, I am learning about enterprise knowledge bases and RAG from scratch.  
> The goal of this project is to build a knowledge-base question answering system for telecommunications and mobile support network environments, with high retrieval accuracy, fast response times, and traceability back to the original documents — all while running locally without Internet access for security reasons.
>
> The project was originally built on top of LlamaIndex. However, as development progressed and more specific problems needed to be solved, many LlamaIndex components were gradually replaced with custom implementations.
>
> Docling was also introduced as a dependency to support document conversion within the project.

![](res/cat_typing.gif)

---

# ⭐ Features

## (1) Convert Original Documents

1. Convert original documents into Markdown reference documents
   * Extract images from the original documents as standalone image files and re-reference them inside the Markdown documents
2. Repair and enhance reference documents
   * Fix Markdown formatting issues related to tables, lists, and other structures
   * Use LLMs to analyze referenced images and generate image description blocks
   * Since some source documents may already be written in Markdown and manually edited, all document repair and image recognition are performed during the indexing stage

## (2) Build the Knowledge Base

1. Build the vector database required for RAG. Data is stored in the `project/storage/chroma_db/` directory
   * A custom parser performs chunking based on Markdown heading and content structure
   * Large table chunks are split while preserving table headers
   * Large text chunks are split based on paragraphs and line breaks
   * ⚠️ Oversized content is not yet fully handled. _Please inspect the results carefully — some chunks may still become excessively large (work in progress...)_
   * Merge small chunks from sibling sections when appropriate
   * Inject section headings and add necessary metadata to chunks
   * Enhance metadata according to predefined rules (currently not used during querying, still under consideration...)
2. Support fast retrieval dictionaries. Data is stored in the `project/storage/dict/` directory  
   Please manually copy dictionary text files into this directory; this step is not automated.
   * Supports tab-separated text files with one entry per line
   * The first field is the `keyword`, followed by one or more `definitions`
   * Duplicate keywords are supported, allowing multiple lines to describe the same term
   * This feature was added mainly for industry-oriented use cases such as technical terminology and field structures

## (3) Query and Retrieval

1. Fast dictionary lookup
   * Perform millisecond-level dictionary lookup for single words or terms
   * Supports querying multiple keywords in a simple sentence (for example: `What are CW and hold?`, `IMPI IMPU IMSI MSISDN`)
   * If no dictionary match is found, the system directly falls back to RAG retrieval; otherwise, the WEBUI asks whether to continue with RAG retrieval
2. Vector database retrieval
   * Supports both online and local LLMs, with configurable large/small models for different tasks
   * User intent recognition and keyword enhancement improve retrieval accuracy and answer quality
   * Uses hybrid retrieval combining LLM semantic search and BM25 keyword search, along with reranking, dynamic selection, and strict-match supplementation
   * Uses answer caching to accelerate retrieval. Cache data is stored in the `project/storage/cache/` directory (retrieval caching may also be added in the future...)
3. Query interface
   * Supports both WEBUI and CLI query interfaces
   * Answers display reference documents, allow full document browsing, highlight referenced fragments, and support inline image display
   * Supports navigation from `reference documents` to the `original PDF` for deeper inspection
4. Debugging and feedback
   * This project is mainly intended as a reference implementation for RAG systems. Nobody is actually using it directly... right?
   * The CLI can optionally print detailed retrieval information
   * The WEBUI includes a debug panel with basic retrieval details
   * If necessary, feel free to modify the code to add more debugging information, or report issues to me directly

---

# ⭐ Installation

My development environment uses `Python 3.10`. Newer Python versions have not been tested.

1. Clone the repository:
```shell
git clone https://github.com/ShionWakanae/llamaIndexSample.git
```

2. Create a virtual environment:
```shell
python -m venv venv
```

3. Activate the virtual environment:
```shell
.\venv\scripts\activate
```

4. Install CUDA dependencies (if using GPU acceleration):
```shell
pip install -r requirements_cuda.txt
```

5. Install project dependencies:
```shell
pip install -r requirements.txt
```

💡 It is optional, but recommended, to install [LibreOffice](https://www.libreoffice.org/download/download-libreoffice/) and add it to the system PATH.

---

# ⭐ Usage

## ℹ️ (0) Parameter Configuration

Copy `.env_sample` to `.env`, then modify the API endpoints, API keys, model settings (local or online), and other configuration items as needed. Most parameters can remain unchanged initially.

Example configuration:

```ini
STORAGE_SECRET=xxxxxx                       # Any fixed string

LLM_API_BASE=https://api.openai.com/v1      # Local or online OpenAI-compatible API endpoint
LLM_API_KEY=sk-xxxxx                        # API key
LLM_MODEL=gpt-4.1-mini                      # Model name
LLM_MODEL_SMALL=                            # Smaller model for lightweight tasks (optional)

VISION_API_BASE=https://api.openai.com/v1   # Vision API endpoint
VISION_API_KEY=sk-xxxxx                     # API key
VISION_MODEL=qwen3.6-flash                  # Vision model

EMBEDDING_MODEL=BAAI/bge-m3                 # Automatically downloaded from Hugging Face
EMBEDDING_DEVICE=cuda                       # cuda or cpu
RERANKER_MODEL=BAAI/bge-reranker-v2-m3      # Automatically downloaded from Hugging Face

CHUNK_SIZE=1024                             # Chunk size
CHUNK_OVERLAP=80                            # Chunk overlap

RETRIEVAL_VECTOR_TOP_K = 15                 # Vector retrieval count
RETRIEVAL_BM25_TOP_K = 15                   # BM25 retrieval count
VECTOR_SIMILARITY_TOP_K = 30                # Similarity retrieval count

RETRIEVAL_RERANK_TOP_N = 5                  # Results kept after reranking
RETRIEVAL_RERANK_TOP_N_MAX = 10             # Maximum expanded retrieval count

APP_DOC_PATH = c:\app_doc                   # Required document directory
WEBUI_USERNAME=janedoe                      # WebUI username
WEBUI_PASSWORD=123456                       # WebUI password

HOST=127.0.0.1                              # WebUI host
PORT=7860                                   # WebUI port
```

### GPU Acceleration

If you do not have an NVIDIA GPU, change:

```ini
EMBEDDING_DEVICE=cuda
```

to:

```ini
EMBEDDING_DEVICE=cpu
```

If you do have an NVIDIA GPU, install the CUDA version of PyTorch.  
If the CPU version is already installed, uninstall it first:

```shell
pip uninstall torch torchvision torchaudio
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```

If you are unsure which CUDA version to use, please refer to: [CUDA Version Notes](./doc/cuda.md)

---

## ℹ️ (1) Convert Documents

> If the conversion quality is unsatisfactory, you may also try Microsoft's [markitdown](https://github.com/microsoft/markitdown), or alternatives such as [pymupdf4llm](https://github.com/pymupdf/PyMuPDF4LLM), [marker](https://github.com/datalab-to/marker), and others.

Extract images from documents such as DOCX/PDF files, convert the documents into Markdown while preserving directory structure, and store the results in the `ref_md` directory under `APP_DOC_PATH`.

For PDF documents, the original PDF files are copied into the `ori_pdf` directory under `APP_DOC_PATH`.  
For non-PDF documents, the files are first converted into PDFs and then stored in the `ori_pdf` directory.

You can also manually place already-converted Markdown files into the `ref_md` directory.

```shell
python .\src\convert_cli.py "input_path"
```

Whenever files are added or modified, the knowledge base must be re-indexed, and the query cache will also become invalid (see the next step).

---

## ℹ️ (2) Build the Knowledge Base

Index all `.md` files under the `ref_md` directory inside `APP_DOC_PATH`.

It is recommended to first run the debug mode to inspect document repair results, image recognition, and chunking behavior before performing the actual indexing process:

```shell
python .\src\index_cli.py --debug
# Only preprocesses documents and prints logs without indexing vectors
```

```shell
python .\src\index_cli.py
```

### CPU vs CUDA Performance Comparison

```yml
i9-12900F * Generating embeddings: 100%|█████████████████████| 582/582 [06:45<00:00, 1.43it/s]
4060TI16G * Generating embeddings: 100%|█████████████████████| 582/582 [00:30<00:00, 19.26it/s]
```

---

## ℹ️ (3) Query the Knowledge Base

### CLI Query

```shell
python .\src\rag_cli.py "your question"
```

### Browser Query

1. Start the WebUI service:

```shell
python .\src\reg_webui.py
```

2. Open your browser and visit:

```text
http://127.0.0.1:7860/
```

Enter questions in the input box at the bottom of the page.  
Chat history is displayed above.

Click a `.md` reference file to open a dialog for viewing its contents.

Debug information, execution time, and retrieval statistics are displayed on the right side.  
For more detailed information, use the CLI version.

PS: Mobile phones and tablets are also supported.

![](res/webui.png)

---

# Video Demonstrations

Click the images below to open the videos on Bilibili:

[![WebUI](https://i2.hdslb.com/bfs/archive/4a2a4831b8936c90a563f12f310e6413998f3086.jpg@308w_174h)](https://www.bilibili.com/video/BV1mk5i6nEsQ) [![Mobile Phone](https://i2.hdslb.com/bfs/archive/6cd583150cbc3fbcea9c4724d44c90fd525265a4.jpg@308w_174h)](https://www.bilibili.com/video/BV1s15i6EEQr)

More videos are continuously being uploaded. Please check the channel if needed.

---

# Tech Stack

[![Reddit](https://img.shields.io/reddit/subreddit-subscribers/LlamaIndex?style=plastic&logo=reddit&label=r%2FLlamaIndex&labelColor=white)](https://www.reddit.com/r/LlamaIndex/)
![Python](https://img.shields.io/badge/-Python-silver?logo=Python)
![Pytorch](https://img.shields.io/badge/-Pytorch-silver?logo=Pytorch)
![Node.js](https://img.shields.io/badge/-Node.js-silver?logo=Node.js)
![NiceGUI](https://img.shields.io/badge/NiceGUI-UI-silver?logo=Gradio)
![Docling](https://img.shields.io/badge/-Docling-silver?logo=D)
![Markdown](https://img.shields.io/badge/-Markdown-blue?logo=Markdown)
![Rich](https://img.shields.io/badge/Rich-Print-silver?logo=Rich)
![Yaml](https://img.shields.io/badge/-Yaml-brown?logo=Yaml)
![huggingface](https://img.shields.io/badge/-huggingface-navy?logo=huggingface)
![jieba](https://img.shields.io/badge/Simplified%20Chinese-jieba-red?logo=jieba)

---

# Environment Support

![llama.cpp](https://img.shields.io/badge/-llama.cpp-blueviolet?logo=ollama)
![gemma4](https://img.shields.io/badge/gemma--4--26B--A4B--it--UD--IQ2__M-gguf-blue?logo=Google)
![github](https://img.shields.io/badge/-github-navy?logo=github)
![acer](https://img.shields.io/badge/predator-acer-green?logo=acer)
![nvidia](https://img.shields.io/badge/rtx--4060ti16gb-5a3b92?logo=nvidia)
![Intel](https://img.shields.io/badge/i9--12900f-brown?logo=Intel)
![ChatGPT](https://img.shields.io/badge/OpenAI-ChatGPT-navy?logo=OpenAI)

---

# License

![license](https://img.shields.io/github/license/ShionWakanae/llamaIndexSample.svg "MIT license")

> [!Important]
> This project is licensed under the MIT License. You may use, modify, and distribute this project in accordance with the terms of the license.

Third-party libraries:
- Docling (MIT)
- LlamaIndex (MIT)
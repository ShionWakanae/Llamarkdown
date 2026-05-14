# Project Overview
[![Me on CSDN](https://img.shields.io/badge/若苗瞬-CSDN-blue)](https://blog.csdn.net/ddrfan?type=blog)
[![Me on Bilibili](https://img.shields.io/badge/欢迎-bilibili-red?style=flat&logo=youtube)](https://space.bilibili.com/688222797)

[简体中文](README.md) | **English**

## What Is This Project About
I am trying to learn and understand enterprise knowledge bases and RAG from scratch by developing applications based on LlamaIndex — just like this little cat.  
The goal is to build a knowledge base QA system for telecom and mobile network enterprises, with high recall accuracy, fast response times, and the ability to trace back to the original source.
Especially, it is based on security factors, and does not require internet access.
![]()
![](res/cat_typing.gif)

## About LlamaIndex
> [!Note]
> A data ingestion and Retrieval-Augmented Generation (RAG) framework for Large Language Models (LLMs). It connects external data sources such as local documents, databases, APIs, and knowledge bases to LLMs, enabling question-answering based on private data. It supports multiple data sources, vector databases, and model services including PDF, Markdown, FAISS, Chroma, Qdrant, OpenAI, and local llama.cpp models. It also provides advanced RAG capabilities such as hybrid retrieval, query routing, and multi-index composition. LlamaIndex emphasizes modularity and composability, making it suitable for knowledge-base QA, document search, code retrieval, and offline local RAG scenarios.


## Features

### (1) Convert the Original Document to Markdown Format

1. Convert the original document to Markdown format.
2. Fix the Markdown file format.
3. Save images from the original document to external files and reference them in the Markdown file.
4. Recognize and add image data blocks to the Markdown file.

### (2) Build the Knowledge Base

1. Build the vector database required for RAG. Data is stored in `project/storage/chroma_db` (using embedded Chroma DB).

   * A custom heading structure parser performs chunking based on Markdown heading hierarchy.
   * A custom content-aware parser chunks subsection content based on text, tables, code blocks, and more.
   * Adds metadata to chunks (original file directory, filename, start/end line numbers).
   * Splits large table chunks while preserving table headers, and adds metadata (start/end rows in the original table).
   * Splits large text chunks based on paragraphs and line breaks.
   * ⚠️ _Other types of oversized content are not yet handled!!!_ Some chunks may still become too large (work in progress...).
   * Injects section headings into chunk text.
   * Merges small chunks from sibling sections when appropriate.
   * Enhances metadata based on titles, content, and predefined metadata rules (not yet used during retrieval, still under consideration...).
   * Uses CUDA acceleration for embedding generation.
2. Build a fast retrieval dictionary. Data is stored in `project/storage/dict/` (manually copy text files there; no automatic indexing required).
   * Supports text files using tabs as separators, with one entry per line.
   * The first field is the entry `keyword`, followed by one or more `definitions`.
   * Supports duplicate keywords, allowing multiple lines to explain the same term.
   * This feature was added specifically for industry use cases. Technical terms, field structures, and any keyword-definition mappings can be retrieved quickly.
   
### (3) Query and Retrieval

1. Fast dictionary lookup
   * Performs millisecond-level dictionary lookup for single words or terms.
   * Supports querying multiple keywords in a simple sentence (for example: `What are CW and hold?`, `IMPI IMPU IMSI MSISDN`)
   * If the dictionary does not return a match, RAG retrieval is performed directly.
   * If a dictionary match is found, the system prompts whether to continue searching the knowledge base (WEB only).
2. Vector database retrieval
   * Supports either online or local LLMs, with separate configurable large/small models for different tasks.
   * User intent recognition and keyword enhancement improve recall accuracy and response quality.
   * Uses hybrid retrieval combining LLM semantic search and BM25 keyword search.
   * Re-ranks retrieved content.
   * Dynamically expands selection after reranking.
3. Retrieval query interface
   * Supports both WEBUI and CLI queries.
   * Includes spinners and streaming output for impatient users.
   * WEBUI can display reference documents, allow original document reading, and highlight referenced fragments within documents.
   * Original document viewing supports displaying internally referenced Markdown images stored in specific locations (work in progress...).
4. Debugging and feedback
   * This project is mainly intended as a RAG reference implementation. Nobody is actually using it directly... right?
   * CLI can optionally print detailed retrieval information.
   * WEB includes a debug panel showing basic retrieval information.
   * If necessary, modify the code to add additional debug information for correcting source data or reporting bugs.


## Installation
💡 My own environment uses `python 3.10`. Newer Python versions have not been tested.

1. Clone the repository into a local directory:  
`git clone https://github.com/ShionWakanae/llamaIndexSample.git`
1. Create a virtual environment inside the directory: `python -m venv venv`
2. Activate the virtual environment: `.\venv\scripts\activate`
3. Install CUDA dependencies: `pip install -r requirements_cuda.txt`  (if using CUDA acceleration)
4. Install dependencies: `pip install -r requirements.txt`

## Usage
### (0) Parameter Configurationℹ️

Copy `.env_sample` to `.env`, then modify the API endpoints, API keys, model configurations (local or online), and other settings as needed. Most other parameters can initially remain unchanged.

Configuration example:
``` ini
STORAGE_SECRET=xxxxxx                       # Any fixed string

LLM_API_BASE=https://api.openai.com/v1      # Local or online OpenAI-compatible API endpoint
LLM_API_KEY=sk-xxxxx                        # API key
LLM_MODEL=gpt-4.1-mini                      # Model name
LLM_MODEL_SMALL=                            # Smaller model name; leave empty to disable (used for query rewriting and intent detection)

VISION_API_BASE=https://api.openai.com/v1   # Vision API endpoint
VISION_API_KEY=sk-xxxxx                     # API key
VISION_MODEL=qwen3.6-flash                  # Model name

EMBEDDING_MODEL=BAAI/bge-m3                 # Usually no need to modify; downloaded automatically from Hugging Face
EMBEDDING_DEVICE=cuda                       # Default device is CUDA; can also be set to cpu
RERANKER_MODEL=BAAI/bge-reranker-v2-m3      # Usually no need to modify; downloaded automatically from Hugging Face

CHUNK_SIZE=1024                             # Chunk size
CHUNK_OVERLAP=80                            # Chunk overlap

RETRIEVAL_VECTOR_TOP_K = 15                 # Vector retrieval count
RETRIEVAL_BM25_TOP_K = 15                   # BM25 retrieval count
VECTOR_SIMILARITY_TOP_K = 30                # Similar content retrieval count

RETRIEVAL_RERANK_TOP_N = 5                  # Retrieval count after reranking
RETRIEVAL_RERANK_TOP_N_MAX = 10             # Maximum expanded retrieval count

APP_DOC_PATH = c:\app_doc                   # Application document path (required). Contains ref_md reference docs and ori_pdf original PDF docs
WEBUI_USERNAME=janedoe                      # WebUI username
WEBUI_PASSWORD=123456                       # WebUI password

HOST=127.0.0.1                              # WebUI host
PORT=7860                                   # WebUI port
```

💡 About GPU acceleration:

If you do not have an NVIDIA GPU, change `EMBEDDING_DEVICE=cuda` to `cpu`.  
If you have an NVIDIA GPU, install the CUDA version of PyTorch, and if you have already installed the CPU version, uninstall it first:
``` shell
pip uninstall torch torchvision torchaudio
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```

If you are unsure about CUDA versions, please refer to: [CUDA Version Notes](./doc/cuda.md).

### (1) Convert Documentsℹ️
> If the conversion quality is unsatisfactory, you may also try Microsoft's [markitdown](https://github.com/microsoft/markitdown), or alternatives such as [pymupdf4llm](https://github.com/pymupdf/PyMuPDF4LLM), [marker](https://github.com/datalab-to/marker), and others...

Extract images from documents such as docx/pdf and convert them to markdown with a directory structure, then store the results in the `ref_md` directory under `APP_DOC_PATH`.  
If the document is a PDF, you may choose to copy it to the `ori_pdf` directory under `APP_DOC_PATH`.  
You can also place already converted markdown files directly into the `ref_md` directory under `APP_DOC_PATH`.  
After adding or modifying files, the knowledge base needs to be re-indexed.



``` shell
python .\src\convert_cli.py "input_path"
```

### (2) Build the Knowledge Baseℹ️
Index `.md` files under the `ref_md` directory inside `APP_DOC_PATH`:  
It is recommended to first use the debug parameter to inspect chunking results before performing actual indexing:

``` shell
python .\src\index_cli.py --debug    # Only preprocesses documents and prints logs without indexing vectors
```

``` shell
python .\src\index_cli.py
```


CPU vs CUDA performance comparison:
```yml
i9-12900F * Generating embeddings: 100%|█████████████████████| 582/582 [06:45<00:00, 1.43it/s] 
4060TI16G * Generating embeddings: 100%|█████████████████████| 582/582 [00:30<00:00, 19.26it/s]
```

### (3) Query the Knowledge Baseℹ️
#### CLI Query
``` shell
python .\src\rag_cli.py 'your question'
```

#### Browser Query
1. Start the WebUI service.
``` shell
python .\src\reg_webui.py
```

2. Open your browser and visit `http://127.0.0.1:7860/` to query the knowledge base.  
Enter questions in the input box at the bottom of the page. Chat history is displayed above.  
Click a `.md` reference file to open a dialog for viewing its contents.  
Debug information, timing, and hit statistics are displayed on the right side. Use the CLI for more detailed information.  
PS: Mobile and tablet users can also access the WebUI.

![](res/webui.png)

## Video Demonstrations
Click to open videos on Bilibili:

[![BM25 Video Demo](https://i2.hdslb.com/bfs/archive/5bf16a799cc21268d626462a89255220daf10ef4.jpg@308w_174h)](https://www.bilibili.com/video/BV1rb9zB5EAD/) [![Index and RAG Demo](https://i2.hdslb.com/bfs/archive/728ece5712492028faf11833f9fada09f2bf645a.jpg@308w_174h)](https://www.bilibili.com/video/BV1po9yBhEFH/)  

More videos are continuously being uploaded. Please check the channel if needed.


## Tech Stack
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

## Environment Support
![llama.cpp](https://img.shields.io/badge/-llama.cpp-blueviolet?logo=ollama)
![gemma4](https://img.shields.io/badge/gemma--4--26B--A4B--it--UD--IQ2__M-gguf-blue?logo=Google)
![github](https://img.shields.io/badge/-github-navy?logo=github)
![acer](https://img.shields.io/badge/predator-acer-green?logo=acer)
![nvidia](https://img.shields.io/badge/rtx--4060ti16gb-5a3b92?logo=nvidia)
![Intel](https://img.shields.io/badge/i9--12900f-brown?logo=Intel)
![ChatGPT](https://img.shields.io/badge/OpenAI-ChatGPT-navy?logo=OpenAI)

## License
![license](https://img.shields.io/github/license/ShionWakanae/llamaIndexSample.svg "MIT license")

Third-party libraries:
- Docling (MIT)
- LlamaIndex (MIT)
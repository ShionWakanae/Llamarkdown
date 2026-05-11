# Project Overview
[![Me on CSDN](https://img.shields.io/badge/若苗瞬-CSDN-blue)](https://blog.csdn.net/ddrfan?type=blog)
[![Me on Bilibili](https://img.shields.io/badge/欢迎-bilibili-red?style=flat&logo=youtube)](https://space.bilibili.com/688222797)

[简体中文](README.md) | **English**

## What Is This Project About?
I am experimenting with building applications based on LlamaIndex. Like this little cat, I am learning and exploring enterprise knowledge bases and RAG from scratch.  
![](res/cat_typing.gif)

## About LlamaIndex
> [!Note]
> LlamaIndex is a data ingestion and Retrieval-Augmented Generation (RAG) framework designed for large language models (LLMs). It connects external data sources such as local documents, databases, APIs, and knowledge bases to LLMs, enabling question answering based on private data.
>
> It was originally positioned as a "bridge between LLMs and external data" and later evolved into a complete RAG development framework. Developers can use LlamaIndex for document loading, chunking, embedding generation, index construction, retrieval, and reranking, then pass the retrieved results to an LLM for answer generation.
>
> LlamaIndex supports multiple data sources, vector databases, and model services, including PDF, Markdown, FAISS, Chroma, Qdrant, OpenAI, and local llama.cpp models. It also provides advanced RAG capabilities such as hybrid retrieval, query routing, and multi-index composition.
>
> Compared with traditional approaches that manually combine embeddings, vector databases, and prompts, LlamaIndex emphasizes modularity and composability, making it suitable for knowledge base QA, document search, code retrieval, and offline local RAG scenarios.


## Project Features

### (1) Knowledge Base Construction
1. Build a vector database required for RAG, with data stored in `project/storage/chroma_db` (use chroma embbeded).
   * Supports Markdown files with well-structured sections.
   * A custom header parser splits Markdown files based on their heading hierarchy.
   * A custom content-aware parser further chunks sections based on text, tables, code blocks, etc.
   * Adds metadata to each chunk (original file path, filename, start/end line numbers).
   * Splits large tables while preserving headers, with metadata indicating row ranges in the original table.
   * Splits large text blocks based on paragraphs and line breaks.
   * ⚠️ _Other types of oversized data are not yet handled._ Chunks may exceed limits (work in progress).
   * Injects section headers into chunked text.
   * Merges small chunks from parallel sections.
   * Enriches metadata based on headers, content, and predefined rules (not yet used in querying; under consideration).
   * Uses CUDA acceleration for embedding generation.

2. Build a fast lookup dictionary, stored in `project/storage/dict/` (manual file placement; no indexing required).
   * Supports tab-separated text files, one entry per line.
   * The first field is the keyword; subsequent fields are definitions.
   * Duplicate keywords are supported (multiple lines can define the same term).
   * Designed for domain-specific needs such as terminology and structured fields, enabling fast lookup.

---

### (2) Query and Retrieval

1. Fast dictionary lookup
   * Performs millisecond-level dictionary lookup for single-word queries.
   * Supports querying multiple keywords in a simple sentence (e.g., `What are CW and hold?`, `IMPI IMPU IMSI MSISDN`).
   * Falls back to RAG retrieval if no dictionary match is found.
   * If matched, prompts whether to continue searching the knowledge base (WEB only).

2. Vector database retrieval
   * Supports both local and online LLMs; configurable for different roles.
   * Improves recall accuracy via intent recognition and keyword enhancement.
   * Combines semantic retrieval (LLM) with BM25 keyword search.
   * Applies reranking to retrieved results.
   * Dynamically expands selection after reranking.

3. Query interface
   * Supports both WEB UI and CLI.
   * Includes spinner and streaming output for responsiveness.
   * WEB UI displays reference documents, allows reading originals, and highlights relevant segments.
   * Supports displaying images referenced within Markdown (work in progress).

4. Debugging and feedback
   * This project is intended as a RAG reference rather than a production tool.
   * CLI can optionally print detailed retrieval information.
   * WEB UI includes a debug panel with basic retrieval insights.
   * Modify code as needed to add debug information for data correction or bug reporting.

---

## Installation
💡 I am using Python 3.10 for this project. I have not tested it with more versions.

1. Clone the repository:
   `git clone https://github.com/ShionWakanae/llamaIndexSample.git`

2. Create a virtual environment:
   `python -m venv venv`

3. Activate the environment:
   `.\venv\scripts\activate`

4. Install dependencies:
   `pip install -r requirements.txt`

---

## Usage

### (0) Convert Documents to Markdown

> [!Important]  
> To focus on indexing and retrieval (including debugging), only Markdown format is currently supported.  
> Convert documents to `.md` format before proceeding. Tools include: markitdown, pymupdf4llm, docling, marker, etc.  
>
> Refer to `MarkItDownSample.py` for usage examples.  
> This sample does not run directly in this project; follow the official setup instructions.  
>
> The sample mainly demonstrates handling images in Word (e.g., diagrams, flowcharts, architecture diagrams), converting them into textual descriptions. However, a single prompt does not perform well across diverse image types. A multi-agent pipeline would be more effective—this is a separate topic with its own challenges.  
>
> Manually review converted `.md` files to ensure:
> - Correct formatting  
> - Proper section structure  
> - Tables are aligned  
> - Image descriptions are accurate  
> - No table of contents (TOC)  
>
> Initial manual effort improves downstream automation quality.

Example command:
    python .\MarkItDownSample.py "Input dir" "Output dir"

---

### (1) Configure LLM and Models

Copy `.env_sample` to `.env`, then update the API endpoint, API key, and model configurations (local or remote). The remaining parameters can be left unchanged initially and adjusted later as needed. An example configuration is shown below:
``` ini
STORAGE_SECRET=xxxxxx                       # A random string for storage secret

LLM_API_BASE=https://api.openai.com/v1      # OpenAI or OpenAI-compatible API endpoint (local or remote)
LLM_API_KEY=sk-xxxxx                        # API key
LLM_MODEL=gpt-4.1-mini                      # Model name
LLM_MODEL_SMALL=                            # Small model for query rewrite

EMBEDDING_MODEL=BAAI/bge-m3                 # Automatically downloaded from Hugging Face if needed.
EMBEDDING_DEVICE=cuda                       # Default device is cuda, can be set to cpu
RERANKER_MODEL=BAAI/bge-reranker-v2-m3      # Automatically downloaded from Hugging Face if needed.

CHUNK_SIZE=1024                             # Text chunk size
CHUNK_OVERLAP=80                            # Overlap size between chunks (currently unused)

RETRIEVAL_VECTOR_TOP_K=15                   # Number of vector search results to retrieve
RETRIEVAL_BM25_TOP_K=15                     # Number of BM25 search results to retrieve
VECTOR_SIMILARITY_TOP_K=30                  # Number of similar content chunks to retrieve

RETRIEVAL_RERANK_TOP_N=5                    # Number of results kept after reranking
RETRIEVAL_RERANK_TOP_N_MAX = 10             # Max number of results after dynamic select

REF_FILE_PATH="Path_To"                     # Path to reference documents (used for image rendering and locate source file)
WEBUI_USERNAME=janedoe                      #WebUI username
WEBUI_PASSWORD=123456                       #WebUI password
```

### (2) Build the Knowledge Base
Index `.md` files:
``` shell
python .\src\index_cli.py 'Your Markdown directory'
```
ℹ️ It is recommended to first use the debug parameter to inspect how the documents are chunked, and proceed with formal indexing only after confirming there are no issues.
``` shell
python .\src\index_cli.py '你的MD文件目录' --debug    #print log only
```

If you are using an NVIDIA GPU, CUDA is recommended. Otherwise, comment out the `device="cuda",` line.  
To install CUDA-enabled PyTorch (make sure to choose the correct CUDA version for your GPU):
``` shell
pip uninstall torch torchvision torchaudio
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```

Performance comparison:
```yml
i9-12900F * Generating embeddings: 100%|█████████████████████| 582/582 [06:45<00:00, 1.43it/s] 
4060TI16G * Generating embeddings: 100%|█████████████████████| 582/582 [00:30<00:00, 19.26it/s]
```

### (3) Query the Knowledge Base
#### Command-Line Query
``` shell
python .\src\rag_cli.py 'Your question'
```

#### Browser-Based Query
1. Start the WebUI service.
``` shell
python .\src\reg_webui.py
```

2. Open your browser and visit `http://127.0.0.1:7860/` to query the knowledge base.   
   
Enter your question in the input box at the bottom of the page; the chat history is shown above.  
Click on a .md reference file to open a dialog box and browse its content.  
On the right is the debugging information. For more detailed information, please use the CLI.

![](res/webui.gif)

## Video Demonstrations
Click to watch the videos on Bilibili:

[![BM25 Demo](https://i2.hdslb.com/bfs/archive/5bf16a799cc21268d626462a89255220daf10ef4.jpg@308w_174h)](https://www.bilibili.com/video/BV1rb9zB5EAD/) [![Index and RAG Demo](https://i2.hdslb.com/bfs/archive/728ece5712492028faf11833f9fada09f2bf645a.jpg@308w_174h)](https://www.bilibili.com/video/BV1po9yBhEFH/)  

More videos are available on my channel.


## Tech Stack
[![Reddit](https://img.shields.io/reddit/subreddit-subscribers/LlamaIndex?style=plastic&logo=reddit&label=r%2FLlamaIndex&labelColor=white)](https://www.reddit.com/r/LlamaIndex/)
![Python](https://img.shields.io/badge/-Python-silver?logo=Python)
![Pytorch](https://img.shields.io/badge/-Pytorch-silver?logo=Pytorch)
![Node.js](https://img.shields.io/badge/-Node.js-silver?logo=Node.js)
![Gradio](https://img.shields.io/badge/Gradio-UI-silver?logo=Gradio)  
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
![Intel](https://img.shields.io/badge/i9--12900f-navy?logo=Intel)

## License
![license](https://img.shields.io/github/license/ShionWakanae/llamaIndexSample.svg "MIT license")

According to the LlamaIndex license statement, this project is released under the MIT License.
# Project Overview
[![Me on CSDN](https://img.shields.io/badge/若苗瞬-CSDN-blue)](https://blog.csdn.net/ddrfan?type=blog)
[![Me on Bilibili](https://img.shields.io/badge/欢迎-bilibili-red?style=flat&logo=youtube)](https://space.bilibili.com/688222797)

[简体中文](README.md) | **English**

## What Is This Project About
> [!Note]
Like this little cat, I am learning and understanding enterprise knowledge bases and RAG from scratch.  
The goal is to build a knowledge-base question answering system for telecommunications/mobile support network enterprises, with high retrieval accuracy, fast response speed, and traceability back to the original documents. All of this is intended to work locally without Internet access for security reasons.  
>
> The project is based on LlamaIndex, but as development progressed and specific problems needed to be solved, LlamaIndex components were gradually replaced with custom implementations.  
>
> At the same time, Docling was introduced as a dependency to support document conversion within the project.

![](res/cat_typing.gif)


## ⭐Features

### (1) Convert Original Documents

1. Convert original documents into Markdown-format reference documents
   * Save images from the original documents as external standalone image files and re-reference them in the reference documents
2. Fix and enhance reference documents
   * Repair Markdown formatting issues such as tables, lists, and related structures
   * Use LLMs to recognize images referenced in documents and add image description blocks
   * Considering that original documents may already be in Markdown format and can be manually copied in and edited, all data correction and image recognition are performed during the indexing stage

### (2) Build the Knowledge Base

1. Build the vector database required for RAG. Data is stored in the `project/storage/chroma_db/` directory
   * A custom parser performs chunking on Markdown files based on heading and content structure
   * Large table chunks are split while preserving table headers
   * Large text chunks are split based on paragraphs and line breaks
   * ⚠️ Oversized content is not yet fully handled!!! _Please observe carefully — chunks may still become excessively large (work in progress...)_
   * Merge small chunks from sibling sections when appropriate
   * Add necessary metadata to chunks and inject section headings
   * Enhance metadata according to predefined rules (not yet used during querying, still under consideration...)
1. Support fast retrieval dictionaries. Data is stored in the `project/storage/dict/` directory. Please manually copy text files into this directory; this is not done automatically by the program
   * Supports text files using tabs as separators, with one entry per line
   * The first field is the entry `keyword`, followed by one or more `definitions`
   * Supports duplicate keywords, meaning multiple lines can explain the same term
   * This feature was added specifically for industry-oriented use cases, such as technical terminology and field structures...
   
### (3) Query and Retrieval

1. Fast dictionary retrieval
   * Perform millisecond-level dictionary lookup for single words or terms
   * Supports querying multiple keywords in a simple sentence (for example: `What are CW and hold?`, `IMPI IMPU IMSI MSISDN`)
   * If the dictionary does not return a match, RAG retrieval is performed directly; otherwise, the user is asked whether to continue with RAG retrieval (WEB only)
1. Vector database retrieval
   * Supports either online or local LLMs, with configurable large/small models handling different tasks
   * User intent recognition and keyword enhancement improve retrieval accuracy and response quality
   * Uses hybrid retrieval combining LLM semantic search and BM25 keyword search, along with reranking, dynamic selection, and strict-match supplementation
   * Uses answer caching to accelerate retrieval. Data is stored in the `project/storage/cache/` directory (retrieval caching may also be considered...)
1. Retrieval query interface
   * Supports both WEBUI and CLI query retrieval
   * Answers display reference documents, allow full document reading, highlight referenced fragments, and support referenced image display
   * Supports navigation from `reference documents` to the `original PDF` for deeper browsing
1. Debugging and feedback
   * This project is mainly intended as a RAG reference implementation. Nobody is actually using it directly... right?
   * CLI can optionally print detailed retrieval information
   * WEB includes a debug panel showing basic retrieval information
   * If necessary, please modify the code yourself to add additional debugging information, or report issues to me


## ⭐Installation
💡 My own environment uses `python 3.10`. Newer Python versions have not been tested.

1. Clone the repository into a local directory:  
`git clone https://github.com/ShionWakanae/llamaIndexSample.git`
1. Create a virtual environment inside the directory: `python -m venv venv`
2. Activate the virtual environment: `.\venv\scripts\activate`
3. Install CUDA dependencies: `pip install -r requirements_cuda.txt`  (if using CUDA acceleration)
4. Install dependencies: `pip install -r requirements.txt`

## ⭐Usage
### ℹ️(0) Parameter Configuration

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

### ℹ️(1) Convert Documents
> If the conversion quality is unsatisfactory, you may also try Microsoft's [markitdown](https://github.com/microsoft/markitdown), or alternatives such as [pymupdf4llm](https://github.com/pymupdf/PyMuPDF4LLM), [marker](https://github.com/datalab-to/marker), and others...

Extract images from documents such as docx/pdf and convert them to markdown with a directory structure, then store the results in the `ref_md` directory under `APP_DOC_PATH`.  
If the document is a PDF, you may choose to copy it to the `ori_pdf` directory under `APP_DOC_PATH`.  
You can also place already converted markdown files directly into the `ref_md` directory under `APP_DOC_PATH`.  

``` shell
python .\src\convert_cli.py "input_path"
```
Whenever files are added or modified, the knowledge base must be re-indexed, and the query cache will also become invalid (see the next step).

### ℹ️(2) Build the Knowledge Base
Index `.md` files under the `ref_md` directory inside `APP_DOC_PATH`:  

It is recommended to first use the debug parameter to inspect document correction, image recognition, and chunking results for this batch of documents, and confirm everything is working properly before performing formal indexing:

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

### ℹ️(3) Query the Knowledge Base
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

[![WebUI](https://i2.hdslb.com/bfs/archive/4a2a4831b8936c90a563f12f310e6413998f3086.jpg@308w_174h)](https://www.bilibili.com/video/BV1mk5i6nEsQ) [![Mobile Phone](https://i2.hdslb.com/bfs/archive/6cd583150cbc3fbcea9c4724d44c90fd525265a4.jpg@308w_174h)](https://www.bilibili.com/video/BV1s15i6EEQr)  

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

> [!Important]
> This project is licensed under the MIT License. You can use, modify, and distribute the code of this project as long as you follow the terms of the license.

Third-party libraries:
- Docling (MIT)
- LlamaIndex (MIT)
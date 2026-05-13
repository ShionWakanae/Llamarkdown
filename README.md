# 项目简介
[![Me on CSDN](https://img.shields.io/badge/若苗瞬-CSDN-blue)](https://blog.csdn.net/ddrfan?type=blog)
[![Me on Bilibili](https://img.shields.io/badge/欢迎-bilibili-red?style=flat&logo=youtube)](https://space.bilibili.com/688222797)

**简体中文** | [English](README_en.md)

## 这是在干啥
我正在尝试通过开发基于LlamaIndex的程序。像这只小猫，从0学习和理解企业知识库和RAG的知识。  
![](res/cat_typing.gif)

## 关于llamaIndex
> [!Note]
> 面向大语言模型（LLM）的数据接入与检索增强（RAG）框架，用于将本地文档、数据库、API、知识库等外部数据连接到大模型，实现基于私有数据的问答能力。它支持多种数据源、向量数据库和模型服务，例如 PDF、Markdown、FAISS、Chroma、Qdrant、OpenAI 以及本地 llama.cpp 模型，同时提供混合检索、查询路由、多索引组合等高级 RAG 能力。它更强调模块化与可组合性，适用于知识库问答、文档搜索、代码检索和本地离线 RAG 等场景。


## 项目功能
### （1）建立知识库

1. 建立RAG所需的向量数据库，数据保存在 `项目/storage/chroma_db`（改用内嵌的chroma db）。
   * 支持章节结构正确的Markdown文件。
   * 自定义的标题结构解析器对Markdown文件进行基于标题结构的分块（chunking）
   * 自定义的内容感知解析器对单小节内容进行基于内容文本，表格，代码块等等的分块。
   * 对于分块增加元数据（原始文件的目录位置，文件名，起止行号）。
   * 对大型表格块进行保留表头的拆分，增加元数据（在原表格中的起止行）
   * 对大型文本块进行基于段落和换行的拆分。
   * ⚠️ _其它类型超长数据暂未处理！！！_ 注意chunk可能超长（进行中……）。
   * 对分块文本进行章节标题注入。
   * 对于并列章节内容的小块进行合并。
   * 根据标题和内容以及设定的元数据规则，对元数据进行加强（enrich）（查询尚未使用，考虑中……）。
   * 使用CUDA加速进行向量化（Embedding）。
2. 建立快速检索字典，数据保存到 `项目/storage/dict/`（自己把文本文件拷贝进去，不是自动的，也无需索引）。
   * 支持用tab作为分隔符的文本文件，每行一个词条。
   * 首字段是词条`关键词`，随后的多个字段是该关键词的`释义`。
   * 支持重复的词条关键字，也就是多行文本在解释同一个词。
   * 这部分是考虑到行业特点加进去的。专业术语、字段结构……只要是关键词释义，都可快速检索。
   
### （2）查询检索

1. 字典快速查询检索
   * 对于单个词语（单词）先进行毫秒级别的字典检索。
   * 可用简单的语句同时检索多个关键字（比如：`CW和hold是什么？`,`IMPI IMPU IMSI MSISDN`）
   * 字典未命中则直接进行RAG检索。
   * 字典命中则显示后提示是否在经验库中继续检索（仅WEB）。
2. 向量数据库检索
   * 可选在线或本地LLM，可配置大小LLM分别处理不同工作。
   * 用户意图识别和关键字加强，提高召回精度，更好的回答方式。
   * 使用LLM语义和BM25关键词的混合检索。
   * 对召回内容进行重排序。
   * 对重排序后的数据进行动态扩大选择。
3. 检索查询界面
   * 支持WEBUI网页界面和CLI的查询。
   * 给没有耐心的人准备了spinner和流式输出。
   * WEBUI可显示参考文档，可阅读原文，高亮显示参考资料片段在文档中的位置。 
   * 阅读原文支持特定位置存储的markdown内部引用图片显示（进行中……）。
4. 调试和反馈
   * 这个项目是给大家做RAG的参考，没人真的直接用吧？
   * CLI可选进一步打印召回信息。
   * WEB有调试面板，显示简单的召回信息。
   * 如有必要修改代码增加调试信息，用以修正源数据，或反馈bug。


## 安装
💡我自己用的环境是`python 3.10`，没测试过新的python版本。

1. 将仓库代码克隆到一个本地目录： 
`git clone https://github.com/ShionWakanae/llamaIndexSample.git`
1. 进入这个目录建立虚拟环境：`python -m venv venv`
2. 激活虚拟环境：`.\venv\scripts\activate`
3. 安装依赖：`pip install -r requirements.txt`

## 使用
### （0）配置LLM和模型

将`.env_sample`拷贝成`.env`，并修改其中的API地址密钥，各种模型配置（本地或在线），其它参数可保留原样，后根据实际情况修改，配置样例如下：
``` ini
STORAGE_SECRET=xxxxxx                       #输入任意的固定字符串

LLM_API_BASE=https://api.openai.com/v1      #本地或在线的OpenAI或兼容API地址
LLM_API_KEY=sk-xxxxx                        #密钥
LLM_MODEL=gpt-4.1-mini                      #模型名称
LLM_MODEL_SMALL=                            #小模型名称，留空代表不另外设置（用于查询重写和用户意图）

VISION_API_BASE=https://api.openai.com/v1   #视觉API地址
VISION_API_KEY=sk-xxxxx                     #密钥
VISION_MODEL=qwen3.6-flash                  #模型名称

EMBEDDING_MODEL=BAAI/bge-m3                 #可以不修改，自动从hf上下载。
EMBEDDING_DEVICE=cuda                       #默认设备为cuda，也可以设置为cpu
RERANKER_MODEL=BAAI/bge-reranker-v2-m3      #可以不修改，自动从hf上下载。

CHUNK_SIZE=1024                             #分块大小。
CHUNK_OVERLAP=80                            #分块重叠区间。

RETRIEVAL_VECTOR_TOP_K = 15                 #向量召回数量。
RETRIEVAL_BM25_TOP_K = 15                   #BM25召回数量。
VECTOR_SIMILARITY_TOP_K = 30                #相似内容召回数量。

RETRIEVAL_RERANK_TOP_N = 5                  #重排序后召回数量。
RETRIEVAL_RERANK_TOP_N_MAX = 10             #最大扩展召回数量。

APP_DOC_PATH = c:\app_doc                   #应用文档路径，必须配置（内有ref_md参考文档目录，ori_pdf原始文档目录）。
WEBUI_USERNAME=janedoe                      #WebUI用户名
WEBUI_PASSWORD=123456                       #WebUI密码

HOST=127.0.0.1                              #WebUI主机地址
PORT=7860                                   #WebUI端口
```
💡关于显卡加速：

没有N卡请修改`EMBEDDING_DEVICE=cuda`，改为`cpu`。  
有Nvidia显卡，请安装CUDA版本的Pytorch：
``` shell
pip uninstall torch torchvision torchaudio
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```
如果对CUDA版本有疑问，请参考:[关于CUDA版本的说明](./doc/cuda.md)。

### （1）文档转换为MD格式
> 若转换效果不佳，可自行尝试微软的 [markitdown](https://github.com/microsoft/markitdown)，或者 [pymupdf4llm](https://github.com/pymupdf/PyMuPDF4LLM)，[marker](https://github.com/datalab-to/marker) 等等……
> 

将docx/pdf转换为md并存储到`APP_DOC_PATH`的`ref_md`目录下,把文档中图片提取成为外部图片文件引用。
如果是pdf文档可选择复制到`APP_DOC_PATH`的`ori_pdf`目录下。
``` shell
python .\src\convert_cli.py "input_path"
```

### （2）建立知识库
索引`APP_DOC_PATH`中`ref_md`目录下的`.md`类型的文件：
ℹ️ 建议先通过debug参数，观察这批文档的分块情况，确认没问题再正式索引：
``` shell
python .\src\index_cli.py --debug    #只会预处理文档，打印日志，不会索引向量
```
``` shell
python .\src\index_cli.py
```


CPU和CUDA速度对比：
```yml
i9-12900F * Generating embeddings: 100%|█████████████████████| 582/582 [06:45<00:00, 1.43it/s] 
4060TI16G * Generating embeddings: 100%|█████████████████████| 582/582 [00:30<00:00, 19.26it/s]
```

### （3）查询知识库
#### 命令行查询
``` shell
python .\src\rag_cli.py '你的问题'
```
#### 浏览器查询
1. 启动WebUI服务。
``` shell
python .\src\reg_webui.py
```
2. 打开浏览器，访问`http://127.0.0.1:7860/` 发送问题进行知识库的查询。  
页面下方输入框中输入问题，上方是聊天记录。  
点击一个`.md`参考文件，弹出对话框浏览文件内容。  
右边是调试信息，时长和命中情况。看更详细的信息请用CLI。

![](res/webui.png)

## 视频演示
点击打开B站视频：

[![BM25视频演示](https://i2.hdslb.com/bfs/archive/5bf16a799cc21268d626462a89255220daf10ef4.jpg@308w_174h)](https://www.bilibili.com/video/BV1rb9zB5EAD/) [![Index和RAG演示](https://i2.hdslb.com/bfs/archive/728ece5712492028faf11833f9fada09f2bf645a.jpg@308w_174h)](https://www.bilibili.com/video/BV1po9yBhEFH/)  

还有更多的视频更新，有需要请站内自行查看。


## 技术栈
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
![jieba](https://img.shields.io/badge/简体中文-jieba-red?logo=jieba)

## 环境支撑
![llama.cpp](https://img.shields.io/badge/-llama.cpp-blueviolet?logo=ollama)
![gemma4](https://img.shields.io/badge/gemma--4--26B--A4B--it--UD--IQ2__M-gguf-blue?logo=Google)
![github](https://img.shields.io/badge/-github-navy?logo=github)
![acer](https://img.shields.io/badge/predator-acer-green?logo=acer)
![nvidia](https://img.shields.io/badge/rtx--4060ti16gb-5a3b92?logo=nvidia)
![Intel](https://img.shields.io/badge/i9--12900f-brown?logo=Intel)
![ChatGPT](https://img.shields.io/badge/OpenAI-ChatGPT-navy?logo=OpenAI)

## 授权许可
![license](https://img.shields.io/github/license/ShionWakanae/llamaIndexSample.svg "MIT license")

根据LlamaIndex的声明，本项目采用MIT许可证开源。

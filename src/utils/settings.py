import os
from dotenv import load_dotenv
from utils.myLLM import MyLLM
from llama_index.postprocessor.flag_embedding_reranker import (
    FlagEmbeddingReranker,
)
from pathlib import Path
import re

version_num = "0.2.4"

REF_MD_DIR = "ref_md"
ORI_PDF_DIR = "ori_pdf"

CACHE_DB_PATH = "./storage/cache/cache.db"
CHROMA_DB_PATH = "./storage/chroma_db"
DICT_PATH = "./storage/dict"


def rewrite_image_paths(md_str: str, path: str) -> str:
    ref_md_path = Path(settings.app_doc_path) / REF_MD_DIR
    relative_dir = Path(path).parent.relative_to(ref_md_path).as_posix()

    def repl(m):
        image_path = m.group(2).replace("\\", "/")
        full_path = f"/static/ref_md/{relative_dir}/{image_path}"
        return f"![{m.group(1)}]({full_path})"

    return re.sub(
        r"!\[(.*?)\]\((.*?)\)",
        repl,
        md_str,
    ).replace("//", "/")


class Settings:
    def __init__(self):
        load_dotenv()
        self.webui_username = os.getenv("WEBUI_USERNAME")
        self.webui_password = os.getenv("WEBUI_PASSWORD")
        self.host = os.getenv("HOST", "0.0.0.0")
        self.port = int(os.getenv("PORT", "7860"))
        # LLM
        self.llm_api_base = self._required("LLM_API_BASE")
        self.llm_api_key = self._required("LLM_API_KEY")
        self.llm_model = self._required("LLM_MODEL")
        self.llm_model_small = (
            os.getenv("LLM_MODEL_SMALL", "").strip() or self.llm_model
        )
        self.vision_api_base = os.getenv("VISION_API_BASE", "")
        self.vision_api_key = os.getenv("VISION_API_KEY", "")
        self.vision_model = os.getenv("VISION_MODEL", "")

        # Embedding / Reranker
        self.embedding_model = self._required("EMBEDDING_MODEL")
        self.reranker_model = self._required("RERANKER_MODEL")
        self.embedding_device_index = os.getenv("EMBEDDING_DEVICE", "cuda")
        self.embedding_device_query = (
            "cpu"  # Yes!!! fixed to CPU!!! do not change this!!!
        )

        # Chunk
        self.chunk_size = int(os.getenv("CHUNK_SIZE", "1000"))
        self.chunk_overlap = int(os.getenv("CHUNK_OVERLAP", "80"))

        # Retrieval
        self.retrieval_vector_top_k = int(os.getenv("RETRIEVAL_VECTOR_TOP_K", "15"))
        self.retrieval_bm25_top_k = int(os.getenv("RETRIEVAL_BM25_TOP_K", "15"))
        self.vector_similarity_top_k = int(os.getenv("VECTOR_SIMILARITY_TOP_K", "30"))
        self.retrieval_rerank_top_n = int(os.getenv("RETRIEVAL_RERANK_TOP_N", "5"))
        self.retrieval_rerank_top_n_max = int(
            os.getenv("RETRIEVAL_RERANK_TOP_N_MAX", "10")
        )

        # Other
        self.app_doc_path = os.getenv("APP_DOC_PATH", "")
        self.storage_secret = self._required("STORAGE_SECRET")  # you need this

        # Prompts
        self.rag_system_prompt = """
你是一个企业知识库问答助手

规则：
1. 优先依据提供的上下文回答
2. 如果上下文没有明确答案，直接说`不知道。`
3. 如果无明确答案但仍需提醒用户，需先说`不知道。`后再开始提醒
4. 不要编造事实
5. 不要在回答中提及用户的输出要求
5. 回答尽量准确、简洁
6. 直接回答内容，不要在回答前说类似`根据企业资料`的内容
7. 尽量用有层次结构的列表方式输出并列的内容
8. 如果文档存在歧义，指出歧义
10. 如果发现上下文有语义被截断的可能，提示用户`以参考文档为准！`
""".strip()

        self.rewrite_system_prompt = """
你是一个分析用户输入的助手。
""".strip()

        # Initialize models
        self.rag_llm = MyLLM(
            base_url=self.llm_api_base,
            api_key=self.llm_api_key,
            model=self.llm_model,
            system_prompt=self.rag_system_prompt,
            temperature=0.0,
            extra_body={
                "repeat_penalty": 1.1,
            },
            max_tokens=5120,
        )

        self.rewrite_llm = MyLLM(
            base_url=self.llm_api_base,
            api_key=self.llm_api_key,
            model=self.llm_model_small,
            system_prompt=self.rewrite_system_prompt,
            temperature=0.0,
            max_tokens=200,
        )

        self.reranker = FlagEmbeddingReranker(
            model=self.reranker_model,
            top_n=self.retrieval_rerank_top_n_max,
        )

    def _required(self, key: str):
        value = os.getenv(key)
        if not value:
            raise ValueError(f"Missing required environment variable: {key}")

        return value


settings = Settings()

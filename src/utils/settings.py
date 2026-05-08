import os
from dotenv import load_dotenv


class ShionSettings:
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if ShionSettings._initialized:
            return
        ShionSettings._initialized = True
        self._load()

    def _load(self):
        load_dotenv()

        self.llm_api_base = os.getenv("LLM_API_BASE")
        self.llm_api_key = os.getenv("LLM_API_KEY")
        self.llm_model = os.getenv("LLM_MODEL")
        raw_small = os.getenv("LLM_MODEL_SMALL", "")
        self.llm_model_small = raw_small.strip() or None

        self.embedding_model = os.getenv("EMBEDDING_MODEL")
        self.reranker_model = os.getenv("RERANKER_MODEL")

        self.chunk_size = int(os.getenv("CHUNK_SIZE", "1000"))
        self.chunk_overlap = int(os.getenv("CHUNK_OVERLAP", "80"))

        self.retrieval_vector_top_k = int(os.getenv("RETRIEVAL_VECTOR_TOP_K", "15"))
        self.retrieval_bm25_top_k = int(os.getenv("RETRIEVAL_BM25_TOP_K", "15"))
        self.vector_similarity_top_k = int(os.getenv("VECTOR_SIMILARITY_TOP_K", "30"))
        self.retrieval_rerank_top_n = int(os.getenv("RETRIEVAL_RERANK_TOP_N", "5"))
        self.retrieval_rerank_top_n_max = int(os.getenv("RETRIEVAL_RERANK_TOP_N_MAX", "10"))

        self.ref_file_path = os.getenv("REF_FILE_PATH", "")
        self.storage_secret = os.getenv("STORAGE_SECRET", "")

        self._validate()

    def _validate(self):
        missing = []
        if not self.llm_api_base:
            missing.append("LLM_API_BASE")
        if not self.llm_api_key:
            missing.append("LLM_API_KEY")
        if not self.llm_model:
            missing.append("LLM_MODEL")
        if not self.embedding_model:
            missing.append("EMBEDDING_MODEL")
        if not self.reranker_model:
            missing.append("RERANKER_MODEL")
        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}"
            )

    def apply_to_llama_index(self):
        from llama_index.core import Settings as lli_Settings

        lli_Settings.llm = self.create_llm(
            streaming=True,
            temperature=0.0,
            repeat_penalty=1.1,
            context_window=32000,
            max_tokens=4096,
            system_prompt="""
你是一个企业知识库问答助手。

规则：
1. 优先依据提供的上下文回答。
2. 如果上下文没有明确答案，直接说"不知道"。
3. 不要编造事实。
4. 回答尽量准确、简洁。
5. 直接回答内容，禁止说出"根据企业资料"。
6. 尽量用列表的方式输出并列的内容。
7. 如果文档存在歧义，指出歧义。
8. 如果发现上下文有语义被截断的可能，提示用户`参考并以原始文档为准！`。
""",
        )
        lli_Settings.embed_model = self.create_embed_model(embed_batch_size=8)

    def create_llm(self, **kwargs):
        from llama_index.llms.openai_like import OpenAILike

        defaults = dict(
            api_base=self.llm_api_base,
            api_key=self.llm_api_key,
            model=self.llm_model,
            is_chat_model=True,
        )
        defaults.update(kwargs)
        return OpenAILike(**defaults)

    def create_small_llm(self, **kwargs):
        from llama_index.llms.openai_like import OpenAILike

        model = self.llm_model_small or self.llm_model or "unknown"
        defaults = dict(
            api_base=self.llm_api_base,
            api_key=self.llm_api_key,
            model=model,
            is_chat_model=True,
        )
        defaults.update(kwargs)
        return OpenAILike(**defaults)

    def create_embed_model(self, **kwargs):
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding

        defaults = dict(
            model_name=self.embedding_model,
            device="cuda",
        )
        defaults.update(kwargs)
        return HuggingFaceEmbedding(**defaults)

    def to_dict(self):
        return {
            "llm_api_base": self.llm_api_base,
            "llm_api_key": self.llm_api_key,
            "llm_model": self.llm_model,
            "llm_model_small": self.llm_model_small,
            "embedding_model": self.embedding_model,
            "reranker_model": self.reranker_model,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "retrieval_vector_top_k": self.retrieval_vector_top_k,
            "retrieval_bm25_top_k": self.retrieval_bm25_top_k,
            "vector_similarity_top_k": self.vector_similarity_top_k,
            "retrieval_rerank_top_n": self.retrieval_rerank_top_n,
            "retrieval_rerank_top_n_max": self.retrieval_rerank_top_n_max,
            "ref_file_path": self.ref_file_path,
            "storage_secret": self.storage_secret,
        }


settings = ShionSettings()

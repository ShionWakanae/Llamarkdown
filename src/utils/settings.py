import os
from dotenv import load_dotenv

from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.llms.openai_like import OpenAILike
from llama_index.postprocessor.flag_embedding_reranker import (
    FlagEmbeddingReranker,
)


class Settings:
    def __init__(self):
        load_dotenv()

        #
        # LLM
        #

        self.llm_api_base = self._required("LLM_API_BASE")
        self.llm_api_key = self._required("LLM_API_KEY")

        self.llm_model = self._required("LLM_MODEL")

        self.llm_model_small = (
            os.getenv("LLM_MODEL_SMALL", "").strip() or self.llm_model
        )

        #
        # Embedding / Reranker
        #

        self.embedding_model = self._required("EMBEDDING_MODEL")
        self.reranker_model = self._required("RERANKER_MODEL")

        #
        # Chunk
        #

        self.chunk_size = int(os.getenv("CHUNK_SIZE", "1000"))
        self.chunk_overlap = int(os.getenv("CHUNK_OVERLAP", "80"))

        #
        # Retrieval
        #

        self.retrieval_vector_top_k = int(os.getenv("RETRIEVAL_VECTOR_TOP_K", "15"))

        self.retrieval_bm25_top_k = int(os.getenv("RETRIEVAL_BM25_TOP_K", "15"))

        self.vector_similarity_top_k = int(os.getenv("VECTOR_SIMILARITY_TOP_K", "30"))

        self.retrieval_rerank_top_n = int(os.getenv("RETRIEVAL_RERANK_TOP_N", "5"))

        self.retrieval_rerank_top_n_max = int(
            os.getenv("RETRIEVAL_RERANK_TOP_N_MAX", "10")
        )

        #
        # Other
        #

        self.ref_file_path = os.getenv("REF_FILE_PATH", "")
        self.storage_secret = os.getenv("STORAGE_SECRET", "")

        #
        # Prompts
        #

        self.rag_system_prompt = """
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
""".strip()

        self.rewrite_system_prompt = """
你是一个分析用户输入的助手。
""".strip()

        #
        # Initialize models
        #

        self.rag_llm = OpenAILike(
            api_base=self.llm_api_base,
            api_key=self.llm_api_key,
            model=self.llm_model,
            is_chat_model=True,
            streaming=True,
            temperature=0.0,
            repeat_penalty=1.1,
            context_window=32000,
            max_tokens=4096,
            system_prompt=self.rag_system_prompt,
        )

        self.rewrite_llm = OpenAILike(
            api_base=self.llm_api_base,
            api_key=self.llm_api_key,
            model=self.llm_model_small,
            is_chat_model=True,
            streaming=False,
            temperature=0.0,
            system_prompt=self.rewrite_system_prompt,
            extra_body={
                "enable_thinking": False,
            },
        )

        self.embed_model = HuggingFaceEmbedding(
            model_name=self.embedding_model,
            device="cuda",
            embed_batch_size=8,
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

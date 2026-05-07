import os
import re
import json
import datetime
import traceback
import warnings
from rich import print
from dotenv import load_dotenv
from transformers.utils import logging
from llama_index.core.base.llms.types import (
    CompletionResponse,
)
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.llms.openai_like import OpenAILike
from llama_index.postprocessor.flag_embedding_reranker import FlagEmbeddingReranker
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.retrievers.bm25 import BM25Retriever
from llama_index.core.schema import TextNode
import chromadb
from llama_index.core import Settings as lli_Settings
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.core import VectorStoreIndex

warnings.filterwarnings("ignore", message="pkg_resources is deprecated as an API")
import jieba  # noqa: E402

logging.set_verbosity_error()

load_dotenv()


class UsageCollector:
    def __init__(self):
        self.reset()

    def reset(self):
        self.rewrite = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "source": "none",
            "model": "unknown",
        }
        self.answer = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "source": "none",
            "model": "unknown",
        }

    def set_rewrite(self, usage: dict, source="llm", model="unknown"):
        self.rewrite = {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "source": source,
            "model": model,
        }

    def set_answer(self, usage: dict, source="llm", model="unknown"):
        self.answer = {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "source": source,
            "model": model,
        }

    def get_total(self):
        return {
            "prompt_tokens": self.rewrite["prompt_tokens"]
            + self.answer["prompt_tokens"],
            "completion_tokens": self.rewrite["completion_tokens"]
            + self.answer["completion_tokens"],
            "total_tokens": (
                self.rewrite["prompt_tokens"]
                + self.rewrite["completion_tokens"]
                + self.answer["prompt_tokens"]
                + self.answer["completion_tokens"]
            ),
        }

    def to_dict(self):
        return {
            "rewrite": self.rewrite,
            "answer": self.answer,
            "total": self.get_total(),
        }


def log(msg):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}")


def hybrid_tokenizer(text):
    chinese_tokens = jieba.lcut(text)
    ascii_tokens = re.findall(r"[A-Za-z0-9_]+", text)
    tokens = chinese_tokens + ascii_tokens
    return [t.strip() for t in tokens if t.strip() and len(t.strip()) > 1]


def stream_with_usage(llm, prompt, usage_collector: UsageCollector, engine):
    stream = llm.stream_complete(prompt)

    usage_holder = {}
    full_completion = ""
    try:
        for chunk in stream:
            delta = getattr(chunk, "delta", "")
            if delta:
                full_completion += delta

            yield chunk

            raw = getattr(chunk, "raw", None)
            if raw:
                usage_obj = getattr(raw, "usage", None)
                if usage_obj:
                    for key in ("prompt_tokens", "completion_tokens"):
                        usage_holder[key] = max(
                            usage_holder.get(key, 0),
                            getattr(usage_obj, key, 0),
                        )
    finally:
        model = engine._get_model_name(llm)
        if usage_holder:
            usage_collector.set_answer(
                usage_holder,
                source="llm",
                model=model,
            )
        else:
            usage_collector.set_answer(
                engine.estimate_usage(llm, prompt, full_completion),
                source="estimate",
                model=model,
            )


def extract_usage(response: CompletionResponse):
    # log(type(response.raw))
    raw = getattr(response, "raw", None)
    if raw is None:
        return {}

    # 情况1：dict
    if isinstance(raw, dict):
        usage = raw.get("usage", {})

    # 情况2：Pydantic对象（ChatCompletion）
    else:
        usage_obj = getattr(raw, "usage", None)
        if usage_obj:
            # usage_obj 也是对象，不是dict
            usage = {
                "prompt_tokens": getattr(usage_obj, "prompt_tokens", 0),
                "completion_tokens": getattr(usage_obj, "completion_tokens", 0),
                "total_tokens": getattr(usage_obj, "total_tokens", 0),
            }
        else:
            usage = {}

    return usage


class QuestionNavigator:
    def __init__(self):
        self.llm = OpenAILike(
            api_base=os.getenv("LLM_API_BASE"),
            api_key=os.getenv("LLM_API_KEY"),
            model=(os.getenv("LLM_MODEL_SMALL") or "").strip()
            or os.getenv("LLM_MODEL")
            or "unknown",
            is_chat_model=True,
            streaming=False,
            extra_body={"enable_thinking": False},
            temperature=0.0,
            system_prompt="""
你是一个分析用户输入的助手。
""",
        )

    def analyze_query(self, question: str, engine):
        # fast classify
        fast_type = self._rule_filter(question)
        if fast_type != "RAG":
            return {
                "question_type": fast_type,
                "retrieval_query": "",
                "presentation_intent": "",
                "user_intent": "",
            }

        # llm analyze
        prompt = f"""
请分析用户问题。

目标：
1. 提取真正用于知识检索的内容。
2. 剥离输出格式要求。
3. 剥离语气词。
4. 保留用户真实业务问题。

返回JSON。

你需要判断用户输入属于哪种类型：

- RAG
  用户在询问知识、文档、技术内容，需要检索资料回答。

- CHAT
  普通聊天、问候、感谢、闲聊。

- INVALID
  无意义输入、乱码、极短无上下文内容。

如果是 RAG：
必须生成 retrieval_query。

如果不是 RAG：
retrieval_query 留空。

只返回JSON。

格式：

{{
            "question_type": "RAG | CHAT | INVALID",
    "retrieval_query": "...",
    "presentation_intent": "...",
    "user_intent": "..."
}}

示例：

用户：
Windows平台对比Linux平台，用表格展示

返回：
{{
    "question_type": "RAG",
    "retrieval_query": "Windows平台 Linux平台 对比",
    "presentation_intent": "table",
    "user_intent": "平台差异对比"
}}

用户：
请详细介绍HSS数据解析流程

返回：
{{
    "question_type": "RAG",
    "retrieval_query": "HSS数据解析流程",
    "presentation_intent": "detailed",
    "user_intent": "介绍数据解析流程"
}}

用户:
你好

输出:
{{
            "question_type": "CHAT",
  "retrieval_query": "",
  "presentation_intent": "",
  "user_intent": "打招呼"
}}

用户:
???

输出:
{{
            "question_type": "INVALID",
    ...
}}

只返回JSON对象。
不要使用markdown代码块。
现在分析：

用户：
{question}
        """

        try:
            response = self.llm.complete(prompt)
            usage, source = engine.extract_or_estimate_usage(
                response,
                self.llm,
                prompt,
            )
            model = engine._get_model_name(self.llm)
            engine.usage.set_rewrite(usage, source, model)
            # log(f"[RewriteUsage] {usage}")

            text = response.text.strip()
            # log(f"[QueryAnalyzeRaw] {text}")
            match = re.search(
                r"\{.*\}",
                text,
                re.DOTALL,
            )

            if not match:
                raise ValueError("No JSON found")

            json_text = match.group(0)
            result = json.loads(json_text)
            return result

        except Exception as e:
            log(f"[QueryAnalyzeError] {e}")
            print(traceback.format_exc())

            return {
                "retrieval_query": question,
                "presentation_intent": "",
                "user_intent": "",
            }

    def _rule_filter(self, question: str):
        q = question.strip().lower()

        trivial_words = {
            "hi",
            "hello",
            "hey",
            "你好",
            "你好吗",
            "您好",
            "谢谢",
            "thanks",
            "thank you",
            "bye",
            "再见",
            "?",
            "？",
        }

        if not q:
            return "INVALID"

        if q in trivial_words:
            return "CHAT"

        if len(q) <= 2:
            return "INVALID"

        return "RAG"


class RagEngine:
    def __init__(self):
        log("[RAG] Initializing...")
        self._init_models()
        self._build_pipeline()
        self.navigator = QuestionNavigator()
        self.usage = UsageCollector()
        log("[RAG] Ready")

    def _get_model_name(self, llm):
        return (
            getattr(llm, "model", None) or getattr(llm, "model_name", None) or "unknown"
        )

    def _init_models(self):
        lli_Settings.llm = OpenAILike(
            api_base=os.getenv("LLM_API_BASE"),
            api_key=os.getenv("LLM_API_KEY"),
            model=os.getenv("LLM_MODEL"),
            is_chat_model=True,
            streaming=True,
            temperature=0.0,
            repeat_penalty=1.1,
            context_window=32000,
            max_tokens=4096,
            system_prompt="""
你是一个企业知识库问答助手。

规则：
1. 优先依据提供的上下文回答。
2. 如果上下文没有明确答案，直接说“不知道”。
3. 不要编造事实。
4. 回答尽量准确、简洁。
5. 直接回答内容，禁止说出“根据企业资料”。
6. 尽量用列表的方式输出并列的内容。
7. 如果文档存在歧义，指出歧义。
8. 如果发现上下文有语义被截断的可能，提示用户`参考并以原始文档为准！`。
""",
        )

        lli_Settings.embed_model = HuggingFaceEmbedding(
            model_name=os.getenv("EMBEDDING_MODEL"),
            device="cuda",
            embed_batch_size=8,
        )

    def _build_pipeline(self):

        log("[RAG] Loading storage...")
        # 连接已有 Chroma 数据
        # print("chroma path:", os.path.abspath("./storage/chroma_db"))
        chroma_client = chromadb.PersistentClient(path="./storage/chroma_db")

        # 关键：要用同一个 collection 名
        chroma_collection = chroma_client.get_or_create_collection("docs")

        vector_store = ChromaVectorStore(chroma_collection=chroma_collection)

        # 直接从 vector store 构建 index
        index = VectorStoreIndex.from_vector_store(
            vector_store,
            embed_model=lli_Settings.embed_model,
        )

        collection_data = chroma_collection.get(include=["documents", "metadatas"])

        all_nodes = []
        for text, meta in zip(
            collection_data["documents"],
            collection_data["metadatas"],
        ):
            all_nodes.append(
                TextNode(
                    text=text,
                    metadata=meta or {},
                )
            )
        log(f"[RAG] Loaded nodes: {len(all_nodes)}")

        vector_retriever = index.as_retriever(
            similarity_top_k=int(os.getenv("RETRIEVAL_VECTOR_TOP_K", 15)),
        )

        bm25_retriever = BM25Retriever.from_defaults(
            nodes=all_nodes,
            similarity_top_k=int(os.getenv("RETRIEVAL_BM25_TOP_K", 15)),
            tokenizer=hybrid_tokenizer,
            language="zh",
            skip_stemming=True,
        )

        self.retriever = QueryFusionRetriever(
            [
                vector_retriever,
                bm25_retriever,
            ],
            similarity_top_k=int(os.getenv("VECTOR_SIMILARITY_TOP_K", 30)),
            num_queries=1,
            mode="reciprocal_rerank",
            use_async=False,
        )

        self.reranker = FlagEmbeddingReranker(
            model=os.getenv("RERANKER_MODEL"),
            top_n=int(os.getenv("RETRIEVAL_RERANK_TOP_N_MAX", 5)),
        )

    def dynamic_rerank_select(self, nodes, base_k=5, score_threshold=0.85, max_k=15):
        if not nodes:
            return []

        selected = nodes[:base_k]
        top_score = nodes[0].score if nodes else 0
        for node in nodes[base_k:]:
            if len(selected) >= max_k:
                break

            # 与最高分接近的都保留
            if node.score >= top_score * score_threshold:
                selected.append(node)
            else:
                break

        return selected

    def query(self, question, force_rag):

        analysis = self.navigator.analyze_query(question, self)
        question_type = analysis.get(
            "question_type",
            "RAG",
        )
        # print(question_type)
        if not force_rag and question_type != "RAG":
            return {
                "question_type": question_type,
                "message": (
                    "你好，请直接提出需要查询的问题。"
                    if question_type == "CHAT"
                    else "你好，请输入明确的问题。"
                ),
                "stream": None,
                "source_nodes": [],
            }

        retrieval_query = analysis.get(
            "retrieval_query",
            question,
        )

        user_intent = analysis.get("user_intent", "")
        presentation_intent = analysis.get("presentation_intent", "")
        if not retrieval_query:
            retrieval_query = question

        log(f"[Rewrite] 意图是: {user_intent} ({presentation_intent})")
        log(f"[Rewrite] 关键词: {retrieval_query}")

        # retrieve
        nodes_retriever = self.retriever.retrieve(retrieval_query)
        log(f"[Retrieve] nodes: {len(nodes_retriever)}")

        # rerank
        nodes_rerank = self.reranker.postprocess_nodes(
            nodes_retriever,
            query_str=retrieval_query,
        )
        log(f"[Rerank] nodes: {len(nodes_rerank)}")

        nodes_selected = self.dynamic_rerank_select(
            nodes=nodes_rerank,
            base_k=int(os.getenv("RETRIEVAL_RERANK_TOP_N", 5)),
            score_threshold=0.85,
            max_k=int(os.getenv("RETRIEVAL_RERANK_TOP_N_MAX", 15)),
        )
        log(f"[Dynamic] nodes: {len(nodes_selected)}")

        # build context
        context_parts = []

        for i, node in enumerate(nodes_selected):
            text = node.node.text.strip()
            context_parts.append(text)

        context = "\n\n".join(context_parts)

        #
        # build final prompt
        #

        final_prompt = f"""
请基于提供的企业资料回答用户问题。

规则：

1. 优先依据企业资料回答。
2. 如果企业资料没有明确答案，直接回答“不知道”。
3. 不要编造内容。
4. 保持答案准确。
5. 如果企业资料存在不完整情况，提醒用户参考原始文档。

---

用户真实意图：

{user_intent}

---

输出要求：

{presentation_intent}

---

企业资料：

{context}

---

用户问题：

{question}
"""

        # final generate
        log("Answer starting")
        stream = stream_with_usage(lli_Settings.llm, final_prompt, self.usage, self)
        return {
            "question_type": "RAG",
            "stream": stream,
            "source_nodes": nodes_selected,
        }

    def _rough_token_count(self, text: str) -> int:
        if not text:
            return 0

        # 中文约 1~1.5 char/token
        # 英文约 4 char/token
        return max(1, len(text) // 2)

    def estimate_usage(
        self,
        llm,
        prompt: str,
        completion: str = "",
    ):
        system_prompt = getattr(llm, "system_prompt", "") or ""

        prompt_text = system_prompt + "\n" + prompt
        return {
            "prompt_tokens": self._rough_token_count(prompt_text),
            "completion_tokens": self._rough_token_count(completion),
        }

    def extract_or_estimate_usage(
        self,
        response,
        llm,
        prompt,
    ):
        usage = extract_usage(response)

        if usage:
            return usage, "llm"

        return (
            self.estimate_usage(
                llm,
                prompt,
                response.text,
            ),
            "estimate",
        )


engine = RagEngine()

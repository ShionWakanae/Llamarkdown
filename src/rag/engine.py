import re
import json
import traceback
import warnings
from pathlib import Path
import copy
from rich import print
from transformers.utils import logging
from llama_index.core.base.llms.types import (
    CompletionResponse,
)
from llama_index.postprocessor.flag_embedding_reranker import FlagEmbeddingReranker
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.retrievers.bm25 import BM25Retriever
from llama_index.core.schema import NodeWithScore, TextNode
import chromadb
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.core import VectorStoreIndex
from collections import defaultdict
from utils.logger import logger
from utils.settings import settings

log = logger.log

warnings.filterwarnings("ignore", message="pkg_resources is deprecated as an API")
import jieba  # noqa: E402

logging.set_verbosity_error()


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
        self.llm = settings.rewrite_llm

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
        self._build_pipeline()
        self.navigator = QuestionNavigator()
        self.usage = UsageCollector()
        log("[RAG] Ready")

    def _get_model_name(self, llm):
        return (
            getattr(llm, "model", None) or getattr(llm, "model_name", None) or "unknown"
        )

    def extract_exact_terms(self, text: str):
        """
        提取已经被 QueryRewrite 保留下来的英文术语
        """

        terms = re.findall(
            r"\b[A-Za-z][A-Za-z0-9_]+\b",
            text,
        )

        # lower统一
        return list(dict.fromkeys(t.lower() for t in terms))

    def _index_exact_terms(self, node: TextNode):
        """
        建立 term -> node 的倒排索引
        """
        text = node.text
        terms = self.extract_exact_terms(text)

        for term in terms:
            self.exact_index[term].append(node)

    def extract_matching_sections(
        self,
        text: str,
        terms: list[str],
    ):
        """
        从 node 中，仅提取命中 term 的 [SECTION] 块
        """

        if not text:
            return ""

        # 按 SECTION 切分
        sections = re.split(
            r"(?=\[SECTION\])",
            text,
        )

        matched_sections = []

        for section in sections:
            section_lower = section.lower()

            matched = False

            for term in terms:
                # term 精确匹配
                pattern = re.compile(
                    rf"(?<![A-Za-z0-9_])"
                    rf"{re.escape(term)}"
                    rf"(?![A-Za-z0-9_])",
                    re.IGNORECASE,
                )

                if pattern.search(section_lower):
                    matched = True
                    break

            if matched:
                matched_sections.append(section.strip())

        return "\n\n".join(matched_sections)

    def exact_search(
        self,
        retrieval_query: str,
        existing_nodes,
        max_per_term=10,
        max_total=30,
    ):
        """
        精确英文术语召回
        只作为 supplement recall
        """

        terms = self.extract_exact_terms(retrieval_query)

        if not terms:
            return []

        log(f"[Exact] terms: {terms}", False)

        existing_ids = set()

        for node in existing_nodes:
            try:
                existing_ids.add(node.node.node_id)
            except Exception:
                pass

        result = []

        seen_node_ids = set()
        seen_doc_ids = defaultdict(int)

        for term in terms:
            matched_nodes = self.exact_index.get(term, [])

            added_this_term = 0

            for raw_node in matched_nodes:
                node_id = raw_node.node_id

                if node_id in existing_ids:
                    continue

                if node_id in seen_node_ids:
                    continue

                # 文档级限流
                doc_id = (
                    raw_node.metadata.get("file_path")
                    or raw_node.metadata.get("source")
                    or "unknown"
                )

                if seen_doc_ids[doc_id] >= 2:
                    continue

                # 仅提取命中的 SECTION
                filtered_text = self.extract_matching_sections(
                    raw_node.text,
                    terms,
                )

                if not filtered_text.strip():
                    continue

                seen_doc_ids[doc_id] += 1
                seen_node_ids.add(node_id)

                filtered_node = TextNode(
                    text=filtered_text,
                    metadata=copy.deepcopy(raw_node.metadata),
                )

                result.append(
                    NodeWithScore(
                        node=filtered_node,
                        score=1.0,
                    )
                )

                added_this_term += 1

                if added_this_term >= max_per_term:
                    break

                if len(result) >= max_total:
                    break

            if len(result) >= max_total:
                break

        return result

    def _build_pipeline(self):
        log("[RAG] Loading storage...")
        chroma_client = chromadb.PersistentClient(path="./storage/chroma_db")
        chroma_collection = chroma_client.get_or_create_collection("docs")
        vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
        index = VectorStoreIndex.from_vector_store(
            vector_store,
            embed_model=settings.embed_model,
        )

        collection_data = chroma_collection.get(include=["documents", "metadatas"])
        self.all_nodes = []
        self.exact_index = defaultdict(list)
        all_nodes = []
        for text, meta in zip(
            collection_data["documents"],
            collection_data["metadatas"],
        ):
            node = TextNode(
                text=text,
                metadata=meta or {},
            )

            all_nodes.append(node)
            self.all_nodes.append(node)

            self._index_exact_terms(node)
        log(f"[RAG] Loaded nodes: {len(all_nodes)}")

        # stable exact index order
        for term in self.exact_index:
            self.exact_index[term].sort(
                key=lambda x: (
                    x.metadata.get("file_path", ""),
                    x.node_id,
                )
            )

        vector_retriever = index.as_retriever(
            similarity_top_k=settings.retrieval_vector_top_k,
        )

        bm25_retriever = BM25Retriever.from_defaults(
            nodes=all_nodes,
            similarity_top_k=settings.retrieval_bm25_top_k,
            tokenizer=hybrid_tokenizer,
            language="zh",
            skip_stemming=True,
        )

        self.retriever = QueryFusionRetriever(
            [
                vector_retriever,
                bm25_retriever,
            ],
            llm=settings.rewrite_llm,
            similarity_top_k=settings.vector_similarity_top_k,
            num_queries=1,
            mode="reciprocal_rerank",
            use_async=False,
        )

        self.reranker = FlagEmbeddingReranker(
            model=settings.reranker_model,
            top_n=settings.retrieval_rerank_top_n_max,
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
        log(f"[Rewrite] 关键词: {retrieval_query}", False)

        # retrieve
        nodes_retriever = self.retriever.retrieve(retrieval_query)
        may_dup_count = len(nodes_retriever)
        unique_nodes = {}

        for node in nodes_retriever:
            meta = node.metadata
            key = (
                meta.get("file_path"),
                meta.get("line_start"),
                meta.get("line_end"),
            )
            if key not in unique_nodes:
                unique_nodes[key] = node

        nodes_retriever = list(unique_nodes.values())
        log(f"[Retrieve] nodes: {len(nodes_retriever)}/{may_dup_count}")

        # rerank
        nodes_rerank = self.reranker.postprocess_nodes(
            nodes_retriever,
            query_str=retrieval_query,
        )
        log(f"[Rerank] nodes: {len(nodes_rerank)}")

        top_score = nodes_rerank[0].score if nodes_rerank else -999
        nodes_selected = []
        # log(f"[Rerank] top score: {top_score}", False)
        if top_score > 0:
            nodes_selected = self.dynamic_rerank_select(
                nodes=nodes_rerank,
                base_k=settings.retrieval_rerank_top_n,
                score_threshold=0.85,
                max_k=settings.retrieval_rerank_top_n_max,
            )
            log(f"[Dynamic] nodes: {len(nodes_selected)}")

        # retrieval低质量
        if not nodes_selected or (
            nodes_selected[0].score < 1 and nodes_selected[-1].score < 0
        ):
            nodes_selected = nodes_rerank[: settings.retrieval_rerank_top_n]
            supplement_limit = settings.retrieval_rerank_top_n_max - len(nodes_selected)

            exact_nodes = self.exact_search(
                retrieval_query,
                existing_nodes=nodes_selected,
                max_total=supplement_limit,
            )
            log(f"[Exact] nodes: {len(exact_nodes)}")

            # 找到第一个负分位置
            insert_index = len(nodes_selected)

            for i, node in enumerate(nodes_selected):
                if node.score < 0:
                    insert_index = i
                    break

            # 插入 exact nodes
            nodes_selected = (
                nodes_selected[:insert_index]
                + exact_nodes
                + nodes_selected[insert_index:]
            )

            log(f"[Final] nodes: {len(nodes_selected)}")

        # build context
        context_parts = []

        for _, node in enumerate[NodeWithScore](nodes_selected):
            text = node.node.text.strip()
            context_parts.append(text)

        context = "\n\n".join(context_parts)

        # build final prompt
        final_prompt = f"""
你是一个企业知识库问答助手，请回答用户问题。

规则：
1. 优先依据提供的上下文回答
2. 如果上下文没有明确答案，直接说`不知道。`
3. 如果无明确答案但仍需提醒用户，需先说`不知道。`后再开始提醒
4. 不要编造事实
5. 不要在回答中提及用户的输出要求
5. 回答尽量准确、简洁
6. 直接回答内容，不要在回答前说类似`根据企业资料`的内容
7. 尽量用列表的方式输出并列的内容
8. 如果文档存在歧义，指出歧义
10. 如果发现上下文有语义被截断的可能，提示用户`以参考文档为准！`
---
用户真实意图：

`{user_intent}`

---
输出要求：

`{presentation_intent}`

---
用户问题：

`{question}`

---
企业资料：

{context}

---
严格依据资料回答。
禁止使用外部知识。
禁止寒暄。
直接输出结论。
"""

        # final generate
        log(f"Answer starting, prompt len: {len(final_prompt)}")
        # Path("d:\\debug.txt").write_text(final_prompt, encoding="utf-8")
        stream = stream_with_usage(settings.rag_llm, final_prompt, self.usage, self)
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

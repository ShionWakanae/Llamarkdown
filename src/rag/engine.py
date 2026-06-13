import re
import traceback
import warnings
import copy
import time
from enum import Enum
from rich import print
from transformers.utils import logging
from llama_index.core.base.llms.types import CompletionResponse
from textwrap import dedent
from llama_index.postprocessor.flag_embedding_reranker import FlagEmbeddingReranker
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.retrievers.bm25 import BM25Retriever
from llama_index.core.schema import NodeWithScore, TextNode
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
import chromadb
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.core import VectorStoreIndex
from collections import defaultdict
from typing import Literal
from pydantic import BaseModel, Field
from rag.cache import answer_cache
from utils.logger import logger
from utils.settings import settings, rewrite_image_paths, CHROMA_DB_PATH
from utils.json_extractor import safe_extract_json_fields
from utils.token_analyze import analyze_tokens


log = logger.log

warnings.filterwarnings("ignore", message="pkg_resources is deprecated as an API")
import jieba  # noqa: E402

logging.set_verbosity_error()


pangu_no_think = ""
if "pangu" in settings.llm_model.lower():
    pangu_no_think = "\n/no_think"


class QueryMode(Enum):
    NORMAL = "normal"
    QUOTED = "quoted"
    CONFIRM_RAG = "confirm_rag"


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
    last_model = None
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
                model = getattr(raw, "model", None)
                if model:
                    last_model = model
    finally:
        model = last_model or engine._get_model_name(llm)
        model = model.replace(".gguf", "")
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


class QueryAnalysis(BaseModel):
    question_type: Literal["RAG", "CHAT", "INVALID"]
    retrieval_query: str = Field(default="", max_length=200)
    presentation_intent: str = ""
    user_intent: str = ""


class QuestionNavigator:
    def __init__(self):
        self.llm = settings.rewrite_llm

    def analyze_query(self, question: str, engine):
        # fast classify
        fast_type = self._rule_filter(question)
        if fast_type != "RAG":
            return QueryAnalysis(
                question_type=fast_type,
                retrieval_query=question,
            )

        # llm analyze
        prompt = dedent(f"""\
            请分析用户问题。

            目标：
            1. 提取真正用于知识检索的关键词(retrieval_query),多关键词用空格分割。
            2. 剥离输出格式要求(presentation_intent),形成简短的英文描述。
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
                "retrieval_query": "HSS 数据解析 流程",
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

            {pangu_no_think}
        """)

        text = None
        response = None
        try:
            response = self.llm.complete(
                prompt,
                response_format={"type": "json_object"},
            )
            # if "deepseek" in str(self.llm._client.base_url).lower():
            #     response = self.llm.complete(
            #         prompt,
            #         response_format={"type": "json_object"},
            #     )
            # else:
            #     response = self.llm.complete(
            #         prompt,
            #         response_format={
            #             "type": "json_schema",
            #             "json_schema": {
            #                 "name": "query_analysis",
            #                 "schema": {
            #                     "type": "object",
            #                     "properties": {
            #                         "question_type": {
            #                             "type": "string",
            #                             "enum": ["RAG", "CHAT", "INVALID"],
            #                         },
            #                         "retrieval_query": {"type": "string"},
            #                         "presentation_intent": {"type": "string"},
            #                         "user_intent": {"type": "string"},
            #                     },
            #                     "required": [
            #                         "question_type",
            #                         "retrieval_query",
            #                         "presentation_intent",
            #                         "user_intent",
            #                     ],
            #                     "additionalProperties": False,
            #                 },
            #             },
            #         },
            #     )
            usage, source = engine.extract_or_estimate_usage(
                response,
                self.llm,
                prompt,
            )
            model = engine.extract_model_name(response, self.llm)
            engine.usage.set_rewrite(usage, source, model)
            text = response.text.strip()
            match = re.search(
                r"\{.*\}",
                text,
                re.DOTALL,
            )

            if not match:
                raise ValueError("No JSON found")

            json_text = match.group(0)
            data = safe_extract_json_fields(json_text)
            result = QueryAnalysis.model_validate(data)
            # print(result)
            return result

        except Exception as e:
            log(f"[QueryAnalyzeError] {e}")
            print(traceback.format_exc())
            if response is not None:
                print(response)

            # fallback to RAG, if query rewrite failed
            return QueryAnalysis(
                question_type="RAG",
                retrieval_query=question,
            )

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
        log(f"[Engine] Initializing...<{settings.llm_api_base}>")
        self._build_pipeline()
        self.navigator = QuestionNavigator()
        self.usage = UsageCollector()
        self.need_cache = True
        log("[Engine] Ready")

    def extract_model_name(self, response, llm):
        raw = getattr(response, "raw", None)
        # OpenAI compatible object
        model = getattr(raw, "model", None)
        if model:
            return model.replace(".gguf", "")

        # dict raw
        if isinstance(raw, dict):
            model = raw.get("model")
            if model:
                return model.replace(".gguf", "")

        # fallback
        return self._get_model_name(llm).replace(".gguf", "")

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

    def extract_matching_sections(self, text: str, terms: list[str]):
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
        self, retrieval_query: str, existing_nodes, max_per_term=10, max_total=30
    ):
        """
        精确英文术语召回
        只作为 supplement recall
        """

        terms = self.extract_exact_terms(retrieval_query)
        if not terms:
            return []

        # log(f"[Exact] terms: {terms}", False)
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

    def dedup_nodes(self, nodes, hit_sources):
        unique = {}

        for node in nodes:
            meta = node.metadata
            key = (
                meta.get("file_path"),
                meta.get("line_start"),
                meta.get("line_end"),
            )

            if key not in unique:
                node.metadata.setdefault("hit_sources", [])
                for source in hit_sources:
                    if source not in node.metadata["hit_sources"]:
                        node.metadata["hit_sources"].append(source)

                unique[key] = node

            else:
                existing = unique[key]
                existing.metadata.setdefault("hit_sources", [])
                for source in hit_sources:
                    if source not in existing.metadata["hit_sources"]:
                        existing.metadata["hit_sources"].append(source)

        return list(unique.values())

    def normalize_nodes_metadata(self, nodes):
        remove_keys = {
            "_node_content",
            "_node_type",
            "doc_id",
            "document_id",
            "ref_doc_id",
        }
        for node in nodes:
            metadata = node.metadata
            for key in remove_keys:
                metadata.pop(key, None)

        return nodes

    def _build_pipeline(self):
        log("[Engine] Loading storage...")
        chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        chroma_collection = chroma_client.get_or_create_collection("docs")
        vector_store = ChromaVectorStore(chroma_collection=chroma_collection)

        rag_embed_model = HuggingFaceEmbedding(
            model_name=settings.embedding_model,
            device=settings.embedding_device_query,
            embed_batch_size=8,
        )

        index = VectorStoreIndex.from_vector_store(
            vector_store,
            embed_model=rag_embed_model,
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
        log(f"[Engine] Loaded nodes: {len(all_nodes)}")

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
            use_fp16=True,
        )

    def query(
        self,
        question,
        query_mode=QueryMode.NORMAL,
    ):
        self.need_cache = True
        rewrite_start = time.perf_counter()
        # print(query_mode)
        if query_mode == QueryMode.NORMAL or query_mode == QueryMode.CONFIRM_RAG:
            analysis = self.navigator.analyze_query(question, self)
            if not isinstance(analysis, QueryAnalysis):
                print("BAD ANALYSIS:", type(analysis), analysis)
                print(analysis)
            question_type = analysis.question_type
            if query_mode == QueryMode.NORMAL and question_type != "RAG":
                print(analysis)
                if question_type == "CHAT":
                    ret = "您好，我是专职的企业知识库的智能助理，您可以直接提出问题。"
                elif question_type == "INVALID":
                    ret = (
                        f"非常抱歉，我无法理解您说的 {question} 具体是什么意思，\n"
                        f'请检查拼写，或给关键词加上引号，输入 "{question}" 这样的方式强制查询。'
                    )
                else:
                    ret = "您好，请直接输入明确的需要查询的问题或关键词。"

                yield {
                    "type": "response",
                    "question_type": question_type,
                    "message": ret,
                    "stream": None,
                    "source_nodes": [],
                    "original_question": question,
                }
                return

            retrieval_query = analysis.retrieval_query or question
            user_intent = analysis.user_intent or ""
            presentation_intent = analysis.presentation_intent or ""
            if not retrieval_query:
                retrieval_query = question
                self.need_cache = False
            if not user_intent:
                user_intent = "获取信息"
                self.need_cache = False
            if not presentation_intent:
                presentation_intent = "intro"
                user_intent = "获取信息"

            log(f"[Rewrite] 意图是: {user_intent} ({presentation_intent})")
            log(f"[Rewrite] 关键词: {retrieval_query}", False)

        else:  # query_mode == QueryMode.QUOTED  # 强制查询,目前没有第四种模式
            retrieval_query = question
            user_intent = "获取信息"
            presentation_intent = "intro"
            log(f"[Rewrite] 强制查: {user_intent} ({presentation_intent})")
            log(f"[Rewrite] 关键词: {retrieval_query}", False)
            self.need_cache = False

        if not self.need_cache:
            tokens = analyze_tokens(retrieval_query)
            self.need_cache = (
                tokens["english_count"] == 1 and tokens["chinese_count"] == 0
            )
        timing = round((time.perf_counter() - rewrite_start) * 1000, 2)

        yield {
            "type": "trace",
            "stage": "识别",
            "message": (f"用户希望{user_intent}"),
            "timing": 0,
        }
        yield {
            "type": "trace",
            "stage": "识别",
            "message": (f"我将查询 {retrieval_query}({presentation_intent})的资料"),
            "timing": timing,
        }
        self.last_retrieval_query = retrieval_query
        self.last_presentation_intent = presentation_intent
        self.last_user_intent = user_intent

        cache_hit = answer_cache.search(
            retrieval_query=retrieval_query,
            presentation_intent=presentation_intent,
            user_intent=user_intent,
        )

        if cache_hit:
            best = cache_hit["best"]
            log(f"[Cache] Hit score={best['score']:.4f}")
            yield {
                "type": "trace",
                "stage": "缓存",
                "message": (f"命中语义缓存，相似度: `{best['score']:.4f}`"),
                "timing": 0,
            }
            yield {
                "type": "response",
                "question_type": "RAG",
                "is_cached": True,
                "stream": iter([best["answer"]]),
                "source_nodes": best.get(
                    "source_nodes",
                    [],
                ),
            }
            return

        else:
            log(f"[Cache] {'no cache hit'}")

        # retrieve
        retrieve_start = time.perf_counter()
        nodes_retriever = self.retriever.retrieve(retrieval_query)
        may_dup_count = len(nodes_retriever)

        nodes_retriever = self.dedup_nodes(nodes_retriever, ["bm25", "vector"])
        retrieve_ms = round((time.perf_counter() - retrieve_start) * 1000, 2)
        log(f"[Retrieve] nodes: {may_dup_count} → {len(nodes_retriever)}")
        yield {
            "type": "trace",
            "stage": "召回",
            "message": (
                f"召回并查重的节点数量: `{may_dup_count}` → `{len(nodes_retriever)}`"
            ),
            "timing": retrieve_ms,
        }

        # rerank
        rerank_start = time.perf_counter()
        nodes_rerank = self.reranker.postprocess_nodes(
            nodes_retriever,
            query_str=retrieval_query,
        )
        rerank_ms = round((time.perf_counter() - rerank_start) * 1000, 2)
        top_score = nodes_rerank[0].score if nodes_rerank else -999
        log(f"[Rerank] nodes: {len(nodes_rerank)}, top score: {top_score:.4f}")
        yield {
            "type": "trace",
            "stage": "排序",
            "message": (
                f"重排序后的节点数量: `{len(nodes_rerank)}`, 最高分:`{top_score:.4f}`"
            ),
            "timing": rerank_ms,
        }

        # dynamic select
        nodes_selected = []
        if top_score > 0:
            dynamic_start = time.perf_counter()
            nodes_selected = self.dynamic_rerank_select(
                nodes=nodes_rerank,
                base_k=settings.retrieval_rerank_top_n,
                score_threshold=0.85,
                max_k=settings.retrieval_rerank_top_n_max,
            )
            dynamic_ms = round((time.perf_counter() - dynamic_start) * 1000, 2)
            log(f"[Dynamic] nodes: {len(nodes_selected)}")
            yield {
                "type": "trace",
                "stage": "调整",
                "message": f"动态选择调整后的节点数量: `{len(nodes_selected)}`",
                "timing": dynamic_ms,
            }

        # low quality retrieval
        if not nodes_selected or (
            nodes_selected[0].score < 1 and nodes_selected[-1].score < 0
        ):
            exact_start = time.perf_counter()
            nodes_selected = nodes_rerank[: settings.retrieval_rerank_top_n]
            supplement_limit = (
                settings.retrieval_rerank_top_n_max + settings.retrieval_rerank_top_n
            ) / 2 - len(nodes_selected)
            exact_nodes = self.exact_search(
                retrieval_query,
                existing_nodes=nodes_selected,
                max_total=supplement_limit,
            )
            exact_ms = round((time.perf_counter() - exact_start) * 1000, 2)
            log(f"[Exact] nodes: {len(exact_nodes)}")
            yield {
                "type": "trace",
                "stage": "匹配",
                "message": f"召回质量不足, 补充的节点数量: `{len(exact_nodes)}`",
                "timing": exact_ms,
            }

            insert_index = len(nodes_selected)
            for i, node in enumerate(nodes_selected):
                if node.score < 0:
                    insert_index = i
                    break

            nodes_selected = (
                nodes_selected[:insert_index]
                + exact_nodes
                + nodes_selected[insert_index:]
            )
            may_dup_count1 = len(nodes_selected)
            nodes_selected = self.dedup_nodes(nodes_selected, ["exact"])
            log(f"[Final] nodes: {may_dup_count1} → {len(nodes_selected)}")
            yield {
                "type": "trace",
                "stage": "匹配",
                "message": (
                    f"最终从知识库中提取的节点数量: `{may_dup_count1}` → `{len(nodes_selected)}`"
                ),
                "timing": 0,
            }

        # normalize nodes metadata
        nodes_selected = self.normalize_nodes_metadata(nodes_selected)

        # rewrite image paths
        for node in nodes_selected:
            node.node.text = rewrite_image_paths(
                node.node.text, node.node.metadata["file_path"]
            )

        # build context
        context_parts = []

        for _, node in enumerate[NodeWithScore](nodes_selected):
            text = node.node.text.strip()
            context_parts.append(text)

        context = "\n\n".join(context_parts)
        # build final prompt
        final_prompt = dedent(f"""\
            你是一个企业知识库问答助手，请回答用户问题。

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

            {pangu_no_think}
            """)

        # final generate
        log(f"[Engine] Answer starting, input prompt len: {len(final_prompt)}")
        yield {
            "type": "trace",
            "stage": "回答",
            "message": f"我正在阅读理解相关资料({len(context)}),准备回答用户问题",
            "timing": 0,
        }
        stream = stream_with_usage(settings.rag_llm, final_prompt, self.usage, self)
        yield {
            "type": "response",
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

    def estimate_usage(self, llm, prompt: str, completion: str = ""):
        system_prompt = getattr(llm, "system_prompt", "") or ""

        prompt_text = system_prompt + "\n" + prompt
        return {
            "prompt_tokens": self._rough_token_count(prompt_text),
            "completion_tokens": self._rough_token_count(completion),
        }

    def extract_or_estimate_usage(self, response, llm, prompt):
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

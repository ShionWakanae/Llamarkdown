import time
import re
import traceback
from rag.engine import engine
from rag.dict import dict_engine
from rag.cache import answer_cache
from utils.logger import logger
from rag.engine import QueryMode

log = logger.log

QUOTE_PAIRS = [
    ('"', '"'),
    ("'", "'"),
    ("“", "”"),
    ("”", "“"),
    ("‘", "’"),
    ("`", "`"),
]
QUOTE_CHARS = [
    '"',
    "'",
    "“",
    "”",
    "‘",
    "’",
    "`",
]


def detect_quoted_query(query: str) -> bool:
    """
    Detect whether the whole query is wrapped by quotes.

    Examples:
        '"CFU"'      -> True
        "'MME 定义'" -> True
        "“HSS”"      -> True
        "`APN`"      -> True

        'abc"def'    -> False
        'CFU'        -> False
    """

    q = query.strip()

    if not q:
        return False

    for left, right in QUOTE_PAIRS:
        if q.startswith(left) and q.endswith(right):
            inner = q[len(left) : -len(right)].strip()

            if inner:
                return True

    return False


def sanitize_query(query: str) -> str:
    """
    Remove all quote-like characters from query.

    Examples:
        '"CFU"'      -> CFU
        "'CFU"       -> CFU
        "CFU'"       -> CFU
        "“CFU”"      -> CFU
        "`APN`"      -> APN
    """

    pattern = f"[{re.escape(''.join(QUOTE_CHARS))}]"

    cleaned = re.sub(
        pattern,
        "",
        query,
    )

    return cleaned.strip()


class RagService:
    def get_token_usage(self):
        return engine.usage.to_dict()

    def stream_answer(
        self,
        question,
        query_mode=QueryMode.NORMAL,
    ):
        total_start = time.perf_counter()
        log("[Service] Starting...")
        yield {
            "type": "trace",
            "stage": "开始",
            "message": ("我需要检索信息来回答用户的问题"),
            "timing": 0,
        }
        is_quoted = detect_quoted_query(question)
        if is_quoted:
            question = sanitize_query(question)
            if query_mode == QueryMode.NORMAL:
                query_mode = QueryMode.QUOTED
            # logger.log(f"Sanitized question: {question}")
        if query_mode == QueryMode.NORMAL or query_mode == QueryMode.QUOTED:
            dict_result = dict_engine.query(question)
            if dict_result:
                md = dict_engine.format_markdown(dict_result["entries"])
                total_ms = round(
                    (time.perf_counter() - total_start) * 1000,
                    2,
                )
                yield {
                    "type": "trace",
                    "stage": "字典",
                    "message": ("命中关键字,我将采用字典内容进行回答"),
                    "timing": total_ms,
                }
                yield {
                    "type": "token",
                    "text": md,
                }

                yield {
                    "type": "status",
                    "got_answer": True,
                    "need_rag_confirm": True,
                    "original_question": question,
                    "source": "dict",
                }

                yield {
                    "type": "debug",
                    "query_ms": 0,
                    "llm_ms": 0,
                    "total_ms": total_ms,
                    "retrieval": [],
                }
                return
            else:
                total_ms = round(
                    (time.perf_counter() - total_start) * 1000,
                    2,
                )
                log("[Service] Dict not hit")
                yield {
                    "type": "trace",
                    "stage": "字典",
                    "message": ("未命中关键字,我将继续查询知识库"),
                    "timing": total_ms,
                }

        query_start = time.perf_counter()
        engine.usage.reset()
        response = None
        is_cached = False
        for event in engine.query(question, query_mode):
            if event["type"] == "trace":
                yield event

            elif event["type"] == "response":
                question_type = event.get(
                    "question_type",
                    "RAG",
                )

                if question_type != "RAG":
                    yield {
                        "type": "token",
                        "text": event.get(
                            "message",
                            "无法处理该问题。",
                        ),
                    }
                    if question_type == "INVALID":
                        yield {
                            "type": "status",
                            "got_answer": True,
                            "need_force_rag_confirm": True,
                            "original_question": event.get(
                                "original_question",
                                question,
                            ),
                            "source": "invalid",
                        }
                    total_ms = round(
                        (time.perf_counter() - total_start) * 1000,
                        2,
                    )
                    yield {
                        "type": "debug",
                        "query_ms": 0,
                        "llm_ms": 0,
                        "total_ms": total_ms,
                        "retrieval": [],
                    }
                    return
                is_cached = event.get(
                    "is_cached",
                    False,
                )
                response = event
                break
        query_ms = round(
            (time.perf_counter() - query_start) * 1000,
            2,
        )

        if not response:
            return
        # stream answer
        got_answer = False
        full_answer = []
        llm_start = time.perf_counter()
        for chunk in response["stream"]:
            if isinstance(chunk, str):
                token = chunk
            else:
                token = getattr(
                    chunk,
                    "delta",
                    "",
                )

            if token:
                got_answer = True
                full_answer.append(token)
                yield {
                    "type": "token",
                    "text": token,
                }

        llm_ms = round(
            (time.perf_counter() - llm_start) * 1000,
            2,
        )

        # source nodes
        source_nodes = response.get(
            "source_nodes",
            [],
        )

        yield {
            "type": "sources",
            "nodes": source_nodes,
        }

        # debug info
        retrieval = []

        for idx, node in enumerate(
            source_nodes,
            start=1,
        ):
            if isinstance(node, dict):
                metadata = node
                score = node.get("score", 0)
            else:
                metadata = node.metadata or {}
                score = node.score or 0

            retrieval.append(
                {
                    "rank": idx,
                    "score": round(score or 0, 4),
                    "file_name": metadata.get("file_name", "unknown"),
                    "header_path": metadata.get("header_path", ""),
                    "line_start": metadata.get("line_start"),
                    "line_end": metadata.get("line_end"),
                    "block_types": metadata.get("block_types"),
                    "text_length": metadata.get("text_length"),
                }
            )

        total_ms = round((time.perf_counter() - total_start) * 1000, 2)

        yield {
            "type": "debug",
            "query_ms": query_ms,
            "llm_ms": llm_ms,
            "total_ms": total_ms,
            "retrieval": retrieval,
        }

        # final status
        yield {
            "type": "status",
            "got_answer": got_answer,
            "source": "cache" if is_cached else "llm",
        }

        final_answer = "".join(full_answer).strip()
        # save semantic cache
        if final_answer and (not is_cached) and engine.need_cache:
            try:
                if answer_cache.save(
                    retrieval_query=getattr(engine, "last_retrieval_query", question),
                    presentation_intent=getattr(engine, "last_presentation_intent", ""),
                    user_intent=getattr(engine, "last_user_intent", ""),
                    answer=final_answer,
                    source_nodes=response.get("source_nodes", []),
                ):
                    log("[Cache] Saved")

            except Exception as e:
                log(
                    f"[Cache] Save failed: {e}",
                    False,
                )
                print(traceback.format_exc())


service = RagService()

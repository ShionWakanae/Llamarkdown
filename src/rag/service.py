import time
import re
from rag.engine import engine
from rag.dict import dict_engine
from utils.logger import logger

QUOTE_PAIRS = [
    ('"', '"'),
    ("'", "'"),
    ("“", "”"),
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

    def stream_answer(self, question, force_rag=False):
        total_start = time.perf_counter()
        is_quoted = detect_quoted_query(question)
        if is_quoted:
            question = sanitize_query(question)
            # logger.log(f"Sanitized question: {question}")
        if not force_rag:
            dict_result = dict_engine.query(question)
            if dict_result:
                md = dict_engine.format_markdown(dict_result["entries"])

                yield {
                    "type": "token",
                    "content": md,
                }

                yield {
                    "type": "status",
                    "got_answer": True,
                    "need_rag_confirm": True,
                    "original_question": question,
                    "source": "dict",
                }

                total_ms = round(
                    (time.perf_counter() - total_start) * 1000,
                    2,
                )
                yield {
                    "type": "debug",
                    "content": {
                        "timing": {
                            "query_ms": 0,
                            "llm_ms": 0,
                            "total_ms": total_ms,
                        },
                        "retrieval": [],
                    },
                }

                return

        query_start = time.perf_counter()
        engine.usage.reset()
        response = engine.query(question, force_rag or is_quoted)
        question_type = response.get(
            "question_type",
            "RAG",
        )

        if question_type != "RAG":
            yield {
                "type": "token",
                "content": response.get(
                    "message",
                    "无法处理该问题。",
                ),
            }
            total_ms = round(
                (time.perf_counter() - total_start) * 1000,
                2,
            )
            yield {
                "type": "debug",
                "content": {
                    "timing": {
                        "query_ms": 0,
                        "llm_ms": 0,
                        "total_ms": total_ms,
                    },
                    "retrieval": [],
                },
            }
            return

        query_ms = round(
            (time.perf_counter() - query_start) * 1000,
            2,
        )

        # stream answer
        got_answer = False
        llm_start = time.perf_counter()
        for chunk in response["stream"]:
            token = getattr(
                chunk,
                "delta",
                "",
            )

            if token:
                got_answer = True

                yield {
                    "type": "token",
                    "content": token,
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
            "content": source_nodes,
        }

        # debug info
        retrieval = []

        for idx, node in enumerate(
            source_nodes,
            start=1,
        ):
            metadata = node.metadata or {}

            retrieval.append(
                {
                    "rank": idx,
                    "score": round(
                        node.score or 0,
                        4,
                    ),
                    "file_name": metadata.get(
                        "file_name",
                        "unknown",
                    ),
                    "header_path": metadata.get(
                        "header_path",
                        "",
                    ),
                    "line_start": metadata.get(
                        "line_start",
                    ),
                    "line_end": metadata.get(
                        "line_end",
                    ),
                    "block_type": metadata.get(
                        "block_type",
                    ),
                    "text_length": metadata.get(
                        "text_length",
                    ),
                }
            )

        total_ms = round(
            (time.perf_counter() - total_start) * 1000,
            2,
        )

        yield {
            "type": "debug",
            "content": {
                "timing": {
                    "query_ms": query_ms,
                    "llm_ms": llm_ms,
                    "total_ms": total_ms,
                },
                "retrieval": retrieval,
            },
        }

        #
        # final status
        #

        yield {
            "type": "status",
            "got_answer": got_answer,
            "source": "llm",
        }


service = RagService()

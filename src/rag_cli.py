# import json
import sys
import builtins
from rich import print
from rich.text import Text
from rich.live import Live
from utils.AsyncSpinner import AsyncSpinner
from utils.logger import logger
import argparse
import time


class FilteredStderr:
    def __init__(self, original):
        self.original = original
        self.filters = [
            "resource module not available on Windows",
            "tokenizer parameter is deprecated",
            "Use a stemmer from PyStemmer instead",
        ]

    def write(self, text):
        if not any(f in text for f in self.filters):
            self.original.write(text)

    def flush(self):
        self.original.flush()


sys.stderr = FilteredStderr(sys.stderr)
from rag.engine import QueryMode  # noqa: E402
from rag.service import service  # noqa: E402

log = logger.log

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "question",
        help="Question text",
    )

    parser.add_argument(
        "--ForceRAG",
        action="store_true",
        default=False,
        help="Force full RAG pipeline",
    )

    args = parser.parse_args()
    quest_str = args.question
    force_rag = args.ForceRAG
    if force_rag:
        query_mode = QueryMode.CONFIRM_RAG
    else:
        query_mode = QueryMode.NORMAL

    log(f"Question: [bold bright_yellow]{quest_str}[/]", False)

    debug_data = None
    answer_source = ""
    spinner = AsyncSpinner()
    timing = {}
    streaming_start = time.perf_counter()
    with Live(Text("....", style="yellow"), refresh_per_second=2) as live:
        spinner.live = live
        spinner.start()
        first = True
        source_nodes = []
        accumulated = ""
        for event in service.stream_answer(quest_str, query_mode):
            if event["type"] == "token":
                chunk = event["text"]
                if chunk:
                    if first:
                        log("Streaming...")
                        streaming_start = time.perf_counter()
                        spinner.stop()
                        live.stop()
                        first = False
                    accumulated += chunk
                    # 遇到句号、感叹号、问号或换行时输出
                    if "\n" in accumulated or len(accumulated) > 23:
                        print(
                            f"[bold bright_magenta]{accumulated}[/]", end="", flush=True
                        )
                        accumulated = ""
            elif event["type"] == "sources":
                source_nodes = event["nodes"]
            # debug
            elif event["type"] == "debug":
                debug_data = event
                timing = debug_data
            # status
            elif event["type"] == "status":
                answer_source = event["source"]

            if not first and event["type"] != "token":
                if accumulated:
                    print(f"[bold bright_magenta]{accumulated}[/]", flush=True)
                    print()
                    accumulated = ""

        if accumulated:
            print(f"[bold bright_magenta]{accumulated}[/]", flush=True)
            print()

        if first:
            spinner.stop()
            live.stop()
            print("[bold bright_magenta]对不起，我检索了资料，但还是不知道答案……[/]")
            print()

    print()
    if source_nodes:
        print("Reference:")
        print()
        all_files = []
        j = 0
        for i, node in enumerate(source_nodes):
            # print(node.metadata)
            if isinstance(node, dict):
                metadata = node
            else:
                metadata = node.metadata or {}
            file_name = metadata.get("file_name")
            if file_name and (file_name not in all_files):
                all_files.append(file_name)
                j = j + 1
                print(f"({j}) [bright_blue]{file_name}[/]")
        print()
    streaming_s = round(
        (time.perf_counter() - streaming_start),
        2,
    )
    log("Answer completed")
    log(
        f"Retrieval: {timing.get('query_ms', 0)} ms, Answer: {timing.get('llm_ms', 0)} ms, Total: {timing.get('total_ms', 0)} ms",
        False,
    )
    answer_model = ""
    if answer_source != "dict":
        usage = service.get_token_usage()
        src = usage["rewrite"]["source"]
        model = usage["rewrite"]["model"]
        log(
            f"Rewrite tokens in: {usage['rewrite']['prompt_tokens']:>5}, out:{usage['rewrite']['completion_tokens']:>5}, "
            + f"from: {model if src == 'llm' else f'{model} [bold red]{src}[/]!!!'}",
            False,
        )
        if answer_source == "llm":
            src = usage["answer"]["source"]
            answer_model = usage["answer"]["model"]
            log(
                f"Answers tokens in: {usage['answer']['prompt_tokens']:>5}, "
                + f"out:{usage['answer']['completion_tokens']:>5}, "
                + f"from: {answer_model if src == 'llm' else f'{answer_model} [bold red]{src}[/]!!!'} "
                + f" <{round(int(usage['answer']['completion_tokens']) / streaming_s, 2)} tokens/s>",
                False,
            )
            log(
                f"Total token usage: {usage['total']['total_tokens']:>5}",
                False,
            )

    if debug_data and answer_source != "dict":
        print()
        show_details = input("您要查看具体的命中信息吗？[y/N]: ").strip().lower()
        if show_details.lower() in ("y", "yes"):
            log(
                "命中的内容:",
                False,
            )

            # retrieval = debug_data.get(
            #     "retrieval",
            #     [],
            # )
            # print(JSON(json.dumps(retrieval, ensure_ascii=False, indent=2)))
            preferred_order = [
                "file_path",
                "file_size",
                "file_name",
                "header_path",
                "line_start",
                "line_end",
                "text_length",
                "block_types",
                "table_row_start",
                "table_row_end",
                "merged_chunks",
                "merged_headers",
                "hit_sources",
            ]

            def ordered_metadata(meta):
                ordered = {}

                # 先放重点字段
                for key in preferred_order:
                    if key in meta:
                        ordered[key] = meta[key]

                # 剩余字段按字母排序
                for key in sorted(meta.keys()):
                    if key not in ordered:
                        ordered[key] = meta[key]

                return ordered

            for node in source_nodes:
                if isinstance(node, dict):
                    metadata = node
                    score = node.get("score", 0)
                    answer = "来自缓存"
                else:
                    metadata = node.metadata or {}
                    score = node.score or 0
                    answer = node.text
                print(
                    ">>>-------------------------------------------------------------------------------<<<"
                )
                print(">>> score:(", score, ") metadata：", ordered_metadata(metadata))
                builtins.print(answer.replace("\n\n", "\n"))
                print()

    log(
        "All done ✅",
        False,
    )

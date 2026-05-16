# import json
import sys
import builtins
from rich import print
from rich.text import Text
from rich.live import Live
from utils.AsyncSpinner import AsyncSpinner
from utils.logger import logger
import argparse


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
from rag.service import service  # noqa: E402

log = logger.log
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

log(f"Question: [bold bright_yellow]{quest_str}[/]")

debug_data = None
dct_answer = False
spinner = AsyncSpinner()
timing = {}
with Live(Text("....", style="yellow"), refresh_per_second=2) as live:
    spinner.live = live
    spinner.start()
    first = True
    source_nodes = []
    accumulated = ""
    for event in service.stream_answer(quest_str, force_rag):
        if event["type"] == "token":
            chunk = event["text"]
            if chunk:
                if first:
                    log("Streaming...")
                    spinner.stop()
                    live.stop()
                    first = False
                accumulated += chunk
                # 遇到句号、感叹号、问号或换行时输出
                if "\n" in accumulated:
                    print(f"[bold bright_magenta]{accumulated}[/]", end="", flush=True)
                    accumulated = ""
        elif event["type"] == "sources":
            source_nodes = event["nodes"]
        # debug
        elif event["type"] == "debug":
            debug_data = event
            timing = debug_data
        # status
        elif event["type"] == "status":
            dct_answer = event["source"] == "dict"
    if accumulated:
        print(f"[bold bright_magenta]{accumulated}[/]", end="", flush=True)
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
        file_name = node.metadata.get("file_name")
        if file_name and (file_name not in all_files):
            all_files.append(file_name)
            j = j + 1
            print(f"({j}) [bright_blue]{file_name}[/]")
    print()

log("Answer completed")
log(
    f"Query: {timing.get('query_ms', 0)} ms, LLM: {timing.get('llm_ms', 0)} ms, Total: {timing.get('total_ms', 0)} ms",
    False,
)
if not dct_answer:
    usage = service.get_token_usage()
    src = usage["rewrite"]["source"]
    model = usage["rewrite"]["model"]
    log(
        f"Rewrite token in: {usage['rewrite']['prompt_tokens']}, out:{usage['rewrite']['completion_tokens']}, from: {model if src == 'llm' else f'{model} [bold red]{src}[/]!!!'}",
        False,
    )
    src = usage["answer"]["source"]
    model = usage["answer"]["model"]
    log(
        f"Answers token in: {usage['answer']['prompt_tokens']}, out:{usage['answer']['completion_tokens']}, from: {model if src == 'llm' else f'{model} [bold red]{src}[/]!!!'}",
        False,
    )
    log(f"Total token usage: {usage['total']['total_tokens']}", False)
print()

if debug_data:
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
            "block_type",
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
            print(
                ">>>-------------------------------------------------------------------------------<<<"
            )
            print(
                ">>> score:(",
                node.score,
                ") metadata：",
                ordered_metadata(node.metadata),
            )
            builtins.print(node.text.replace("\n\n", "\n"))
            print()

log(
    "All done ✅",
    False,
)

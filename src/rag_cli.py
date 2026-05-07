# import json
import sys
import datetime

import builtins
from rich import print
from rich.text import Text
from rich.live import Live

# from rich.json import JSON
from utils.AsyncSpinner import AsyncSpinner
from rag.service import service


def log(msg):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    print(f"[{timestamp}] {msg}")


if len(sys.argv) != 2:
    print("Usage: python Sample_RAG_from_storage.py 'Your_Question...'")
    sys.exit(1)

quest_str = sys.argv[1]
log(f"Question: [bold bright_yellow]{quest_str}[/]")

# log("Vector retrieval test")
# vector_results = vector_retriever.retrieve(quest_str)
# for i, node in enumerate(vector_results[:5], 1):
#     print(f"\n[VECTOR {i}] score={node.score}")
#     print(node.text[:300])

# log("hybrid_tokenizer")
# print(hybrid_tokenizer(quest_str))

# log("all_nodes")
# print(all_nodes[0].text[:200])

# log("hybrid_tokenizer all_nodes")
# print(hybrid_tokenizer(all_nodes[0].text[:200]))

# log("BM25 retrieval test")
# bm25_results = bm25_retriever.retrieve(quest_str)
# for i, node in enumerate(bm25_results[:5], 1):
#     print(f"\n[BM25 {i}] score={node.score}")
#     print(node.text[:300])

debug_data = None
spinner = AsyncSpinner()
timing = {}
with Live(Text("....", style="yellow"), refresh_per_second=2) as live:
    spinner.live = live
    spinner.start()
    first = True
    source_nodes = []
    accumulated = ""
    for event in service.stream_answer(quest_str):
        if event["type"] == "token":
            chunk = event["content"]
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
            source_nodes = event["content"]
        # debug
        elif event["type"] == "debug":
            debug_data = event["content"]
            timing = debug_data.get("timing", {})
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
    f"Query: {timing.get('query_ms', 0)} ms, LLM: {timing.get('llm_ms', 0)} ms, Total: {timing.get('total_ms', 0)} ms"
)
usage = service.get_token_usage()
src = usage["rewrite"]["source"]
model = usage["rewrite"]["model"]
log(
    f"Rewrite token in: {usage['rewrite']['prompt_tokens']}, out:{usage['rewrite']['completion_tokens']}, from: {model if src == 'llm' else f'{model} [bold red]{src}[/]!!!'}"
)
src = usage["answer"]["source"]
model = usage["answer"]["model"]
log(
    f"Answers token in: {usage['answer']['prompt_tokens']}, out:{usage['answer']['completion_tokens']}, from: {model if src == 'llm' else f'{model} [bold red]{src}[/]!!!'}"
)
log(f"Total token usage: {usage['total']['total_tokens']}")
print()

if debug_data:
    show_details = input("你要查看具体的命中信息吗？[y/N]: ").strip().lower()
    if show_details.lower() in ("y", "yes"):
        log("命中的内容:")

        retrieval = debug_data.get(
            "retrieval",
            [],
        )
        # print(JSON(json.dumps(retrieval, ensure_ascii=False, indent=2)))

        for node in source_nodes:
            print(
                ">>>-------------------------------------------------------------------------------<<<"
            )
            print(">>> score:(", node.score, ") metadata：", node.metadata)
            builtins.print(node.text)
            print()

log("All done ✅")

from rich import print
from llama_index.core import VectorStoreIndex
import argparse
from collections import Counter, defaultdict
from indexing.builder import IndexBuilder
import chromadb
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.core import StorageContext
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from utils.logger import logger
from utils.settings import settings
from utils.cuda import check_cuda
from indexing.VisionClient import VisionClient
from indexing.ImageOCREnhancer import ImageOCREnhancer

check_cuda(settings)

log = logger.log


def print_metadata_stats(final_nodes):
    stats = defaultdict(Counter)
    total_nodes = len(final_nodes)
    for node in final_nodes:
        meta = node.metadata

        # topic
        if "topic" in meta:
            stats["topic"][meta["topic"]] += 1

        # block_type : text | image | table | code | other
        if "block_type" in meta:
            stats["block_type"][meta["block_type"]] += 1

        # boolean metadata
        for key in [
            "has_error_code",
            "has_sql",
            "has_api",
            "has_number",
        ]:
            if meta.get(key) is True:
                stats[key]["true"] += 1

    print()
    print("=" * 60)
    print(f"TOTAL NODES: {total_nodes}")
    print("=" * 60)

    for category, counter in stats.items():
        print()
        print(f"***{category}***")
        total_matched = sum(counter.values())
        print(f"matched nodes: {total_matched}")
        for k, v in counter.most_common():
            percent = (v / total_nodes) * 100
            print(f"  {k}: {v} ({percent:.1f}%)")


def Show_debug_info_and_exit(final_nodes: list):
    node_max = -1
    node_min = -1
    node_max_index = -1
    node_min_index = -1

    print_metadata_stats(final_nodes)

    if len(final_nodes) >= 10:
        log("Print first max and min markdown node metadata")
        for i, node in enumerate(final_nodes):
            # print(f"({i})","=" * 80)
            # print("[header_path]",node.metadata.get("header_path"))
            # print("[node_text]",node.text[:200])

            if (node_min == -1) or len(node.text) < node_min:
                node_min = len(node.text)
                node_min_index = i

            if (node_max == -1) or len(node.text) > node_max:
                node_max = len(node.text)
                node_max_index = i

        print(f"Node max length:{node_max}, and min length:{node_min}")
        print(f"min({node_min})No.{node_min_index}", "=" * 80)
        print("[min node]", final_nodes[node_min_index])
        print(f"max({node_max})No.{node_max_index}", "=" * 80)
        print("[max node]", final_nodes[node_max_index])

    exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="若苗瞬的 LlamaIndex 文档索引工具")
    parser.add_argument("doc_path", help="文档路径")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="启用调试模式, 只打印分块信息, 不索引和保存",
    )
    args = parser.parse_args()

    # 使用参数
    doc_path = args.doc_path
    debug_mode = args.debug

    log(f"Starting {'debug mode...' if debug_mode else '...'}")

    if settings.vision_api_base:
        log(f"Image enhancement: {doc_path}")
        vision_client = VisionClient(
            api_base=settings.vision_api_base,
            api_key=settings.vision_api_key,
            model=settings.vision_model,
        )
        enhancer = ImageOCREnhancer(
            vision_client=vision_client,
            vision_model=settings.vision_model,
            debug=debug_mode,
        )
        enhancer.process_directory(doc_path)
        # 初始化 Chroma（持久化目录）
        chroma_client = chromadb.PersistentClient(path="./storage/chroma_db")
        # collection（类似表）
        chroma_collection = chroma_client.get_or_create_collection(
            "docs", metadata={"hnsw:space": "cosine"}
        )
    else:
        log("Skip image enhancement")

    # 包装成 LlamaIndex 的 vector store
    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    # 替换 storage_context
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    log(f"Building nodes from: {doc_path}")
    builder = IndexBuilder()
    final_nodes = builder.build_nodes(doc_path, debug_mode)
    for node in final_nodes:
        meta = node.metadata
        if "merged_headers" in meta and isinstance(meta["merged_headers"], list):
            meta["merged_headers"] = " > ".join(meta["merged_headers"])

    # debug part
    if debug_mode:
        Show_debug_info_and_exit(final_nodes)

    # 建索引
    log("Indexing...")

    index_embed_model = HuggingFaceEmbedding(
        model_name=settings.embedding_model,
        device=settings.embedding_device_index,
        embed_batch_size=8,
    )

    index = VectorStoreIndex(
        nodes=final_nodes,
        storage_context=storage_context,
        show_progress=True,
        embed_model=index_embed_model,
    )

    log("All done ✅")

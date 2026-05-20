from llama_index.core import SimpleDirectoryReader
from llama_index.core.schema import TextNode
from parser.MarkdownHeadingAwareParser import MarkdownHeadingAwareParser
from parser.MarkdownContentAwareParser import MarkdownContentAwareParser
from indexing.metadata import enrich_metadata
from utils.settings import settings
import copy

global_chunk_size = settings.chunk_size
global_chunk_overlap = settings.chunk_overlap


class IndexBuilder:
    def __init__(self):
        self.markdown_heading_parser = MarkdownHeadingAwareParser(
            include_metadata=True,
            include_prev_next_rel=True,
        )
        self.markdown_content_parser = MarkdownContentAwareParser(
            chunk_size=global_chunk_size,
            include_prev_next_rel=True,
        )
        self.debug_mode = False

        self.block_handlers = {
            "table": self._handle_table,
            "text": self._handle_text,
            "code": self._handle_code,
            "math": self._handle_math,
            "ocr": self._handle_ocr,
        }

    def _split_large_text_node(self, node):
        text = node.text
        metadata = copy.deepcopy(node.metadata)

        max_size = global_chunk_size
        tolerance = global_chunk_overlap

        lines = text.splitlines()
        base_line_start = metadata.get("line_start", 0)

        result = []
        current_lines = []
        current_start = 0

        def flush(end_idx):
            if not current_lines:
                return
            chunk_text = "\n".join(current_lines)
            new_meta = copy.deepcopy(metadata)
            new_meta["line_start"] = base_line_start + current_start
            new_meta["line_end"] = base_line_start + end_idx

            result.append(
                TextNode(
                    text=chunk_text,
                    metadata=new_meta,
                )
            )

        i = 0
        while i < len(lines):
            line = lines[i]
            tentative = current_lines + [line]
            tentative_text = "\n".join(tentative)

            if current_lines and len(tentative_text) > max_size + tolerance:
                # 优先在“段落边界”切
                flush(i)
                current_lines = [line]
                current_start = i
            else:
                if not current_lines:
                    current_start = i
                current_lines.append(line)

            i += 1

        flush(len(lines))
        return result

    def _split_table_node(
        self,
        node,
        max_chunk_size: int = 1000,
        tolerance: int = 300,
    ):
        """
        Split markdown table node by chunk size.

        Features:
        - preserve header
        - preserve prefix content
        - dynamic row grouping
        - preserve metadata
        - update line_start / line_end
        """

        text = node.text or ""
        lines = text.splitlines()

        if len(lines) < 3:
            return [node]

        # locate separator line
        separator_idx = None

        for i, line in enumerate(lines):
            stripped = line.strip()
            if "|" in stripped and "-" in stripped:
                separator_idx = i
                break

        if (
            separator_idx is None
            or separator_idx == 0
            or separator_idx >= len(lines) - 1
        ):
            return [node]

        header_idx = separator_idx - 1
        prefix_lines = lines[:header_idx]
        header_line = lines[header_idx]
        separator_line = lines[separator_idx]
        data_lines = lines[separator_idx + 1 :]
        if not data_lines:
            return [node]

        metadata = copy.deepcopy(node.metadata)
        base_line_start = metadata.get(
            "line_start",
            0,
        )
        result_nodes = []

        # fixed part size
        fixed_lines = [
            *prefix_lines,
            header_line,
            separator_line,
        ]

        fixed_text = "\n".join(fixed_lines)
        current_rows = []
        current_start_idx = 0

        def flush_rows(end_idx):

            nonlocal current_rows
            nonlocal current_start_idx

            if not current_rows:
                return

            chunk_lines = [
                *fixed_lines,
                *current_rows,
            ]

            chunk_text = "\n".join(chunk_lines)
            first_data_line = separator_idx + 1 + current_start_idx
            last_data_line = separator_idx + end_idx
            new_metadata = copy.deepcopy(metadata)
            new_metadata["line_start"] = base_line_start + first_data_line
            new_metadata["line_end"] = base_line_start + last_data_line + 1
            new_metadata["table_row_start"] = current_start_idx
            new_metadata["table_row_end"] = end_idx - 1

            result_nodes.append(
                TextNode(
                    text=chunk_text,
                    metadata=new_metadata,
                )
            )
            current_rows = []

        # dynamic split
        for idx, row in enumerate(data_lines):
            tentative_rows = current_rows + [row]
            tentative_text = "\n".join(
                [
                    fixed_text,
                    *tentative_rows,
                ]
            )

            # soft limit
            if current_rows and len(tentative_text) > max_chunk_size + tolerance:
                flush_rows(idx)
                current_start_idx = idx
                current_rows = [row]
            else:
                current_rows.append(row)

        # final flush
        flush_rows(len(data_lines))
        return result_nodes

    def _handle_table(self, node):
        if len(node.text) > global_chunk_size:
            sub_nodes = self._split_table_node(node, global_chunk_size)
            return sub_nodes, len(sub_nodes) > 1
        return [node], False

    def _handle_text(self, node):
        if len(node.text) > global_chunk_size:
            sub_nodes = self._split_large_text_node(node)
            return sub_nodes, len(sub_nodes) > 1
        return [node], False

    def _create_code_chunk_node(
        self,
        current_lines: list,
        chunk_index: int,
        total_code_lines: int,
        base_line_start: int,
        original_metadata: dict,
        code_block_start_idx: int,  # 该chunk在当前代码块内的起始行索引（0-based）
        is_split: bool = True,
    ):
        """创建单个拆分后的代码 chunk"""
        chunk_text = "".join(current_lines)
        fence_char = original_metadata.get("fence_char", "`")
        fence_len = original_metadata.get("fence_len", 3)
        fence = fence_char * fence_len
        language = original_metadata.get("code_language", "")
        language_suffix = language if language else ""

        # 计算相对于代码块的行号（从 1 开始计数）
        rel_start = code_block_start_idx + 1
        rel_end = code_block_start_idx + len(current_lines)

        # 注入行号提示到正文最前面
        line_info = (
            f"【代码块 第 {rel_start}-{rel_end} 行，共 {total_code_lines} 行】\n"
        )
        final_text = (
            line_info
            + f"{fence}{language_suffix}\n"
            + chunk_text.rstrip("\n")
            + f"\n{fence}"
        )

        new_metadata = copy.deepcopy(original_metadata)
        new_metadata.update(
            {
                # 文档绝对行号（保持你 [start, end) 半开区间设计）
                "line_start": base_line_start + code_block_start_idx,
                "line_end": base_line_start + code_block_start_idx + len(current_lines),
                "block_types": ["code"],
                "code_chunk_index": chunk_index,
                "code_total_chunks": chunk_index + 1,  # 临时，后续可优化为真实总数
                "is_code_split": is_split,
                "relative_line_start": rel_start,
                "relative_line_end": rel_end,
            }
        )

        if "code_language" in original_metadata:
            new_metadata["code_language"] = original_metadata["code_language"]

        return TextNode(
            text=final_text,
            metadata=new_metadata,
        )

    def _handle_code(self, node):
        """
        处理超长代码块：
        - 超过 chunk_size * 1.5 时才拆分
        - 按行累加，超过 chunk_size 时切分（无 overlap）
        - 在 chunk 正文开头注入相对行号信息
        - 更新文档绝对行号 line_start / line_end
        """
        original_text = (
            node.get_content() if hasattr(node, "get_content") else node.text
        )
        if not original_text or not original_text.strip():
            return [node], False

        original_metadata = copy.deepcopy(node.metadata)
        base_line_start = original_metadata.get("line_start", 0)  # 文档绝对起始行
        code_lines = original_text.splitlines(keepends=True)  # 保留换行

        result_nodes = []
        current_lines = []
        current_char_count = 0
        chunk_index = 0

        # 如果不算太长，包装原node内容并返回
        if len(original_text) <= global_chunk_size * 1.5:
            new_node = self._create_code_chunk_node(
                current_lines=code_lines,
                chunk_index=0,
                total_code_lines=len(code_lines),
                base_line_start=base_line_start,
                original_metadata=original_metadata,
                code_block_start_idx=0,
                is_split=False,
            )
            result_nodes.append(new_node)
            return result_nodes, False

        for i, line in enumerate(code_lines):
            tentative_count = current_char_count + len(line)

            # 加入这一行会超长 → 先保存当前 chunk
            if current_lines and tentative_count > global_chunk_size:
                new_node = self._create_code_chunk_node(
                    current_lines=current_lines,
                    chunk_index=chunk_index,
                    total_code_lines=len(code_lines),
                    base_line_start=base_line_start,
                    original_metadata=original_metadata,
                    code_block_start_idx=i
                    - len(current_lines),  # 该chunk在代码块内的起始索引（0-based）
                )
                result_nodes.append(new_node)

                current_lines = []
                current_char_count = 0
                chunk_index += 1

            current_lines.append(line)
            current_char_count += len(line)

        # 处理最后一个 chunk
        if current_lines:
            new_node = self._create_code_chunk_node(
                current_lines=current_lines,
                chunk_index=chunk_index,
                total_code_lines=len(code_lines),
                base_line_start=base_line_start,
                original_metadata=original_metadata,
                code_block_start_idx=len(code_lines) - len(current_lines),
            )
            result_nodes.append(new_node)

        return result_nodes, True

    def _handle_math(self, node):
        return [node], False

    def _handle_ocr(self, node):
        return [node], False

    def _dispatch_by_block_type(self, node, block_type):
        handler = self.block_handlers.get(block_type)
        if handler:
            return handler(node)
        return [node], False

    def build_nodes(self, doc_path, debug_mode: bool):
        self.debug_mode = debug_mode
        documents = self._load_documents(doc_path)

        # step 1 markdown header
        markdown_heading_nodes, max_node_len, min_node_len = (
            self._build_markdown_heading_nodes(documents)
        )
        if debug_mode:
            print(
                f"markdown heading nodes:{len(markdown_heading_nodes)}, len:{min_node_len} to {max_node_len}"
            )

        # step 2 markdown content
        markdown_content_nodes, max_node_len, min_node_len = (
            self._build_markdown_content_nodes(markdown_heading_nodes)
        )
        if debug_mode:
            print(
                f"markdown content nodes:{len(markdown_content_nodes)}, len:{min_node_len} to {max_node_len}"
            )

        # step 2 table content split
        candidate_nodes = self._build_candidate_nodes(markdown_content_nodes)
        if debug_mode:
            max_node_len = 0
            min_node_len = None

            for node in candidate_nodes:
                node_len = len(node.text)
                if node_len > max_node_len:
                    max_node_len = node_len
                if min_node_len is None or node_len < min_node_len:
                    min_node_len = node_len
            print(
                f"candidate nodes:{len(candidate_nodes)}, len:{min_node_len} to {max_node_len}"
            )

        final_nodes = self._merge_small_chunks(candidate_nodes)
        if debug_mode:
            max_node_len = 0
            min_node_len = None

            for node in final_nodes:
                node_len = len(node.text)
                if node_len > max_node_len:
                    max_node_len = node_len
                if min_node_len is None or node_len < min_node_len:
                    min_node_len = node_len
            print(
                f"final nodes:{len(final_nodes)}, len:{min_node_len} to {max_node_len}"
            )

        return final_nodes

    def _load_documents(self, doc_path):
        documents = SimpleDirectoryReader(
            input_dir=doc_path,
            recursive=True,
            required_exts=[".md"],
            filename_as_id=True,
        ).load_data()

        for doc in documents:
            doc.text_resource.text = doc.get_content()
        return documents

    def _build_markdown_heading_nodes(
        self,
        documents,
    ):
        return self.markdown_heading_parser.get_nodes_from_documents(
            documents=documents,
        )

    def _build_markdown_content_nodes(
        self,
        documents,
    ):
        return self.markdown_content_parser.get_nodes_from_documents(
            nodes=documents,
        )

    # do not split now, just filter empty and enriched
    def _build_candidate_nodes(
        self,
        markdown_nodes,
    ):
        candidate_nodes = []

        def append_candidate(text, metadata, header):
            enriched_text = f"[SECTION]\n{header}\n\n[CONTENT]\n{text}"
            candidate_nodes.append(
                TextNode(text=enriched_text, metadata=copy.deepcopy(metadata))
            )

        split_count = 0
        for node in markdown_nodes:
            if self._is_title_only(node):
                continue

            header = (
                node.metadata.get(
                    "header_path",
                    "",
                )
                .strip("/")
                .replace(
                    "/",
                    " > ",
                )
            )

            # 所有块分类处理，是否拆分开，取决于内部逻辑
            block_types = node.metadata.get(
                "block_types",
                ["text"],
            )
            if len(block_types) != 1:
                raise ValueError(
                    f"Unexpected block_types before dispatch: {block_types}"
                )
            sub_nodes, did_split = self._dispatch_by_block_type(node, block_types[0])
            if did_split:
                split_count += 1
            for sub_node in sub_nodes:
                append_candidate(sub_node.text, sub_node.metadata, header)

        if self.debug_mode:
            print(f"== Large nodes split:{split_count}")
        return candidate_nodes

    def relative_to_parent(self, parent_header: str, target_header: str) -> str:
        if target_header.startswith(parent_header):
            remain = target_header[len(parent_header) :]
            if not remain:
                return ""
            if not remain.startswith("/"):
                remain = "/" + remain
            return remain
        return target_header

    def _merge_small_chunks(
        self,
        candidate_nodes,
    ):
        final_nodes = []
        i = 0
        merge_count = 0

        def parent_header(header: str) -> str:
            """
            /A/B/C/ -> /A/B/
            /A/B/   -> /A/
            /A/     -> /
            """
            parts = [p for p in header.strip("/").split("/") if p]

            if len(parts) <= 1:
                return "/"

            return "/" + "/".join(parts[:-1]) + "/"

        while i < len(candidate_nodes):
            current = candidate_nodes[i]

            if len(current.text.strip()) < 1:
                i += 1
                continue

            current_header = current.metadata.get("header_path", "")
            current_parent_header = parent_header(current_header)

            merged_text = current.text
            merged_nodes = [current]

            #
            # keep merging forward while:
            # - current chunk still too small
            # - same parent section
            # - merged size not exceeding limit
            #
            j = i + 1

            if len(merged_text) < global_chunk_size * 0.75:
                merged_block_types = set(current.metadata.get("block_types", ["text"]))
                while len(merged_text) < (global_chunk_size * 1.5) and j < len(
                    candidate_nodes
                ):
                    nxt = candidate_nodes[j]
                    if current.metadata.get("file_path") != nxt.metadata.get(
                        "file_path"
                    ):
                        break
                    if len(nxt.text.strip()) < 1:
                        j += 1
                        continue

                    next_header = nxt.metadata.get("header_path", "")
                    next_parent_header = parent_header(next_header)

                    # only merge under same parent section
                    # or next is current's child
                    if (
                        current_parent_header != next_parent_header
                        and not next_header.startswith(current_header)
                    ):
                        break

                    candidate_text = merged_text + "\n\n" + nxt.text
                    merged_block_types.update(nxt.metadata.get("block_types", ["text"]))

                    # stop if exceeding max chunk size
                    if len(candidate_text) > (global_chunk_size * 1.5):
                        break

                    merged_text = candidate_text
                    merged_nodes.append(nxt)

                    j += 1

            # metadata based on merged range
            base_meta = copy.deepcopy(current.metadata)
            base_meta["block_types"] = sorted(merged_block_types)
            # update line range
            if len(merged_nodes) > 1:
                last_node = merged_nodes[-1]
                if "line_end" in last_node.metadata:
                    base_meta["line_end"] = last_node.metadata["line_end"]

                # optional:
                # merged chunk count
                base_meta["merged_chunks"] = len(merged_nodes)
                base_meta["merged_headers"] = [
                    self.relative_to_parent(
                        current_parent_header,
                        n.metadata.get("header_path", ""),
                    )
                    for n in merged_nodes
                ]

            temp_node = TextNode(
                text=merged_text,
                metadata=base_meta,
            )

            enriched_meta = enrich_metadata(temp_node)
            final_nodes.append(
                TextNode(
                    text=merged_text.strip(),
                    metadata=enriched_meta,
                )
            )

            if len(merged_nodes) > 1:
                merge_count += len(merged_nodes) - 1

            i = j if len(merged_nodes) > 1 else i + 1

        if self.debug_mode:
            print(f"== small nodes merged:{merge_count}")

        return final_nodes

    def _is_title_only(
        self,
        node,
    ):

        text = node.text.strip()
        return text.startswith("#") and "\n" not in text

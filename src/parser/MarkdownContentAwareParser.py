import re
import copy
from llama_index.core.schema import TextNode


class MarkdownContentAwareParser:
    """
    Content-aware markdown splitter.

    Expected input:
    - Nodes already processed by MarkdownHeadingAwareParser
    - Heading lines already removed
    - header_path already stored in metadata

    Features:
    - Preserve code blocks
    - Preserve markdown tables
    - Preserve OCR blocks
    - Preserve math blocks
    - Merge normal text intelligently
    - Avoid over-fragmentation
    - Keep line_start / line_end updated
    """

    CODE_FENCE_RE = re.compile(r"^(```|~~~)")
    TABLE_RE = re.compile(r"^\s*\|.*\|\s*$")
    MATH_BLOCK_RE = re.compile(r"^\s*\$\$\s*$")
    OCR_START_RE = re.compile(r"^\*\[Image OCR\]\*\s*$")
    OCR_END_RE = re.compile(r"^\*\[End OCR\]\*\s*$")

    def __init__(
        self,
        chunk_size: int = 1000,
        include_prev_next_rel: bool = True,
    ):
        self.chunk_size = chunk_size
        self.include_prev_next_rel = include_prev_next_rel

    def get_nodes_from_documents(self, nodes):

        all_nodes = []

        max_node_len = 0
        min_node_len = None

        for node in nodes:
            split_nodes = self._split_node(node)

            for sub_node in split_nodes:
                node_len = len(sub_node.text)

                if node_len > max_node_len:
                    max_node_len = node_len

                if min_node_len is None or node_len < min_node_len:
                    min_node_len = node_len

            all_nodes.extend(split_nodes)

        if min_node_len is None:
            min_node_len = 0

        #
        # prev / next relation
        #
        if self.include_prev_next_rel:
            for i, node in enumerate(all_nodes):
                if i > 0:
                    node.relationships["previous"] = all_nodes[i - 1].node_id

                if i < len(all_nodes) - 1:
                    node.relationships["next"] = all_nodes[i + 1].node_id

        return (
            all_nodes,
            max_node_len,
            min_node_len,
        )

    def _split_node(self, node):

        text = node.text or ""

        lines = text.splitlines()

        metadata = copy.deepcopy(node.metadata)

        base_line_start = metadata.get(
            "line_start",
            0,
        )

        blocks = self._extract_blocks(lines)

        result_nodes = []

        current_lines = []
        current_start = None
        current_end = None

        def flush_chunk():

            nonlocal current_lines
            nonlocal current_start
            nonlocal current_end

            content = "\n".join(current_lines)

            if not content.strip():
                current_lines = []
                current_start = None
                current_end = None
                return

            new_metadata = copy.deepcopy(metadata)
            new_metadata["line_start"] = current_start
            new_metadata["line_end"] = current_end
            new_metadata["block_type"] = "text"
            result_nodes.append(
                TextNode(
                    text=content,
                    metadata=new_metadata,
                )
            )

            current_lines = []
            current_start = None
            current_end = None

        for block in blocks:
            block_text = block["text"]
            block_type = block["type"]
            abs_start = base_line_start + block["start_line"]
            abs_end = base_line_start + block["end_line"] + 1

            #
            # structured block
            #
            if block_type in {
                "code",
                "table",
                "math",
                "ocr",
            }:
                #
                # flush current text chunk
                #
                if current_lines:
                    flush_chunk()

                structured_metadata = copy.deepcopy(metadata)
                structured_metadata["line_start"] = abs_start
                structured_metadata["line_end"] = abs_end
                structured_metadata["block_type"] = block_type

                result_nodes.append(
                    TextNode(
                        text=block_text,
                        metadata=structured_metadata,
                    )
                )

                continue

            #
            # normal text block
            #
            block_lines = block_text.splitlines()

            for idx, line in enumerate(block_lines):
                tentative_lines = current_lines + [line]

                tentative_text = "\n".join(tentative_lines)

                #
                # split only when truly needed
                #
                if current_lines and len(tentative_text) > self.chunk_size:
                    flush_chunk()

                if current_start is None:
                    current_start = abs_start + idx

                current_end = abs_start + idx + 1

                current_lines.append(line)

        if current_lines:
            flush_chunk()

        return result_nodes

    def _extract_blocks(
        self,
        lines,
    ):

        blocks = []

        i = 0

        while i < len(lines):
            line = lines[i]

            #
            # skip leading empty lines
            #
            if not line.strip():
                i += 1
                continue

            #
            # OCR block
            #
            if self.OCR_START_RE.match(line):
                start = i

                i += 1

                while i < len(lines):
                    if self.OCR_END_RE.match(lines[i]):
                        i += 1
                        break

                    i += 1

                blocks.append(
                    {
                        "type": "ocr",
                        "text": "\n".join(lines[start:i]),
                        "start_line": start,
                        "end_line": i - 1,
                    }
                )

                continue

            #
            # code block
            #
            if self.CODE_FENCE_RE.match(line):
                start = i

                fence = line[:3]

                i += 1

                while i < len(lines):
                    if lines[i].startswith(fence):
                        i += 1
                        break

                    i += 1

                blocks.append(
                    {
                        "type": "code",
                        "text": "\n".join(lines[start:i]),
                        "start_line": start,
                        "end_line": i - 1,
                    }
                )

                continue

            #
            # math block
            #
            if self.MATH_BLOCK_RE.match(line):
                start = i

                i += 1

                while i < len(lines):
                    if self.MATH_BLOCK_RE.match(lines[i]):
                        i += 1
                        break

                    i += 1

                blocks.append(
                    {
                        "type": "math",
                        "text": "\n".join(lines[start:i]),
                        "start_line": start,
                        "end_line": i - 1,
                    }
                )

                continue

            #
            # table
            #
            if self.TABLE_RE.match(line):
                start = i

                i += 1

                while i < len(lines) and self.TABLE_RE.match(lines[i]):
                    i += 1

                blocks.append(
                    {
                        "type": "table",
                        "text": "\n".join(lines[start:i]),
                        "start_line": start,
                        "end_line": i - 1,
                    }
                )

                continue

            #
            # normal text
            #
            start = i

            collected = []

            while i < len(lines):
                current = lines[i]

                #
                # stop on structured block
                #
                if (
                    self.OCR_START_RE.match(current)
                    or self.CODE_FENCE_RE.match(current)
                    or self.TABLE_RE.match(current)
                    or self.MATH_BLOCK_RE.match(current)
                ):
                    break

                collected.append(current)

                i += 1

            text = "\n".join(collected)

            if text.strip():
                blocks.append(
                    {
                        "type": "text",
                        "text": text,
                        "start_line": start,
                        "end_line": i - 1,
                    }
                )

        return blocks

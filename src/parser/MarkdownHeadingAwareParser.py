import re
import copy
from llama_index.core.schema import TextNode


class MarkdownHeadingAwareParser:
    """
    Strict hierarchical markdown parser.

    Behavior:
    - Each heading becomes an independent section.
    - Parent sections DO NOT include child section content.
    - Child sections inherit full header path.
    - Heading lines are NOT included in content.
    - Root-level content uses header_path="/"

    Example:

        # A

        aaa

        ## B

        bbb

    Produces:

        header_path = "/A/"
        content = "aaa"

        header_path = "/A/B/"
        content = "bbb"
    """

    HEADER_RE = re.compile(r"^(#{1,6})\s+(.*)$")

    def __init__(
        self,
        include_metadata: bool = True,
        include_prev_next_rel: bool = True,
    ):
        self.include_metadata = include_metadata
        self.include_prev_next_rel = include_prev_next_rel

    def get_nodes_from_documents(self, documents):

        all_nodes = []

        # node length statistics
        max_node_len = 0
        min_node_len = None

        for doc in documents:
            text = doc.text or ""
            nodes = self._parse_document(
                text=text,
                metadata=copy.deepcopy(doc.metadata),
            )

            # update node length statistics
            for node in nodes:
                node_len = len(node.text)

                if node_len > max_node_len:
                    max_node_len = node_len

                if min_node_len is None or node_len < min_node_len:
                    min_node_len = node_len

            all_nodes.extend(nodes)

        # fallback when no nodes exist
        if min_node_len is None:
            min_node_len = 0

        # prev / next relation
        if self.include_prev_next_rel:
            for i, node in enumerate(all_nodes):
                if i > 0:
                    node.relationships["previous"] = all_nodes[i - 1].node_id

                if i < len(all_nodes) - 1:
                    node.relationships["next"] = all_nodes[i + 1].node_id

        return all_nodes, max_node_len, min_node_len

    def _parse_document(self, text: str, metadata: dict):
        lines = text.splitlines()
        nodes = []

        #
        # header stack:
        # [
        #   (level, title),
        # ]
        #
        header_stack = []
        current_content = []
        current_start_line = 0
        current_end_line = 0
        current_header_path = "/"

        def flush_section():

            nonlocal current_content
            nonlocal current_header_path
            nonlocal current_start_line
            nonlocal current_end_line
            content = "\n".join(current_content)

            #
            # skip empty content
            #
            if not content.strip():
                return

            node_metadata = copy.deepcopy(metadata)
            node_metadata["line_start"] = current_start_line
            node_metadata["line_end"] = current_end_line
            if self.include_metadata:
                node_metadata["header_path"] = current_header_path

            node = TextNode(
                text=content,
                metadata=node_metadata,
            )

            nodes.append(node)

        for line_no, line in enumerate(lines):
            match = self.HEADER_RE.match(line)

            #
            # heading found
            #
            if match:
                #
                # flush previous section
                #
                flush_section()
                current_start_line = line_no + 1
                current_end_line = line_no + 1
                current_content = []
                hashes = match.group(1)
                title = match.group(2).strip()
                level = len(hashes)

                #
                # pop same-or-deeper levels
                #
                while header_stack and header_stack[-1][0] >= level:
                    header_stack.pop()

                #
                # push current header
                #
                header_stack.append((level, title))

                #
                # rebuild header path
                #
                path_parts = [h[1] for h in header_stack]
                current_header_path = "/" + "/".join(path_parts) + "/"
            else:
                current_content.append(line)
                current_end_line = line_no + 1

        #
        # flush last section
        #
        flush_section()

        return nodes

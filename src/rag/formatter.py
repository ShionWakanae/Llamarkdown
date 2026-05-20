def build_reference_files(source_nodes):

    refs = []
    files = {}
    # seen = set()
    for node in source_nodes:
        # cache hit:
        # dict
        if isinstance(node, dict):
            metadata = node
        # normal rag:
        # NodeWithScore
        else:
            metadata = node.metadata or {}

        file_name = metadata.get(
            "file_name",
            "unknown",
        )

        file_path = metadata.get(
            "file_path",
            "",
        )

        line_start = metadata.get(
            "line_start",
            -1,
        )

        line_end = metadata.get(
            "line_end",
            -1,
        )

        # if file_path in seen:
        #     continue
        # seen.add(file_path)

        ref_line = f"- `{file_name}`"
        if line_start >= 0 and line_end > line_start:
            ref_line = f"{ref_line} `{line_start}->{line_end}行`"
        refs.append(ref_line)

        if file_name not in files:
            files[file_name] = {
                "path": file_path,
                "hits": [],
            }

        files[file_name]["hits"].append(
            (
                line_start,
                line_end,
            )
        )

    return (
        "\n".join(refs),
        files,
    )


def build_debug_html(debug_data):

    if not debug_data:
        return """
        <div class="debug-panel">
            ...
        </div>
        """

    retrieval = debug_data.get(
        "retrieval",
        [],
    )

    html = """
    <div class="debug-panel">
        <h5 style="background-color:#1f3f65;">Timing</h5>
    """

    html += f"""
        <div>
            query:
            {debug_data.get("query_ms", 0)}
            ms
        </div>

        <div>
            llm:
            {debug_data.get("llm_ms", 0)}
            ms
        </div>

        <div>
            total:
            {debug_data.get("total_ms", 0)}
            ms
        </div>

        <h5 style="background-color:#1f3f65;">
            Retrieval
            ({len(retrieval)})
        </h5>
    """

    for item in retrieval:
        html += f"""

        <div class="debug-item">

            <div>
                <b>
                    #{item.get("rank")}
                </b>

                {item.get("file_name")}
            </div>

            <div>
                score:
                {item.get("score")}
            </div>

            <div>
                lines:
                {item.get("line_start")}
                -
                {item.get("line_end")}
            </div>

            <div>
                block:
                {item.get("block_types")}
            </div>

            <div style="margin-top:4px; color:#94a3b8;">
                caption:
                {item.get("header_path")}
            </div>

            <hr>

        </div>
        """

    html += "</div>"

    return html

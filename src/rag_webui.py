import sys
import asyncio
import datetime
from pathlib import Path
import threading
from queue import Queue
import traceback
import markdown
from nicegui import ui
from nicegui import app
from nicegui import context
from fastapi.responses import HTMLResponse
import secrets
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from rich import print
import re
from rag.formatter import build_reference_files
from rag.formatter import build_debug_html
from utils.logger import logger
from utils.settings import settings


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

security = HTTPBasic()


def verify_password(credentials: HTTPBasicCredentials = Depends(security)):

    correct_username = secrets.compare_digest(
        credentials.username,
        settings.webui_username,
    )

    correct_password = secrets.compare_digest(
        credentials.password,
        settings.webui_password,
    )

    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username


app.add_static_files("/static/js", "./src/ui/js")
app.add_static_files("/static/css", "./src/ui/css")
ref_path = settings.ref_file_path
if ref_path:
    app.add_static_files("/static/ref_md", f"{ref_path}")


def rewrite_image_paths(md_str: str) -> str:
    return re.sub(
        r"!\[(.*?)\]\(images/(.*?)\)",
        r"![\1](/static/ref_md/images/\2)",
        md_str,
    )


def render_markdown_html(md_str: str) -> str:
    md_str = rewrite_image_paths(md_str)
    rendered_html = markdown.markdown(
        md_str,
        extensions=[
            "fenced_code",
            "tables",
            "nl2br",
            "extra",
            "sane_lists",
            "pymdownx.mark",
        ],
    )
    return f"""
<div class="final-markdown">
    {rendered_html}
</div>"""


def read_file_by_path(path):
    if not path:
        return "文件不存在！"

    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    except Exception as e:
        return f"读取失败:\n\n{e}"


def build_highlighted_markdown(content, hits):

    lines = content.splitlines()
    output = []
    first_hit_done = False
    # merge intervals
    normalized_hits = []
    for start, end in sorted(hits):
        if end <= start:
            continue

        if not normalized_hits:
            normalized_hits.append([start, end])
            continue

        _, last_end = normalized_hits[-1]

        if start <= last_end:
            normalized_hits[-1][1] = max(
                last_end,
                end,
            )
        else:
            normalized_hits.append([start, end])

    # highlighted line set
    highlighted = set()

    for start, end in normalized_hits:
        for i in range(start, end):
            highlighted.add(i)

    # rebuild markdown
    output = []

    for idx, line in enumerate(lines):
        # highlight line
        if idx in highlighted:
            # avoid empty line highlight issue
            if line.strip():
                if line.lstrip().startswith("|"):
                    parts = line.split("|")
                    # 保留原始结构，包括首尾的空字符串
                    is_separator = False

                    # 检查是否为分隔行（如 | --- | --- |）
                    if len(parts) > 2:  # 至少有 3 个部分（首空 + 内容 + 尾空）
                        # 检查非空单元格是否都是分隔符格式
                        non_empty_cells = [p for p in parts if p.strip()]
                        is_separator = all(
                            all(ch in "- " for ch in cell.strip())
                            and "-" in cell.strip()
                            for cell in non_empty_cells
                            if cell.strip()
                        )

                    if is_separator:
                        # 分隔行，保持原样
                        output.append(line)
                    else:
                        # 数据行，高亮每个单元格内容
                        result_parts = ["|"]  # 开头
                        for i, cell in enumerate(parts[1:-1], 1):  # 跳过首尾空字符串
                            stripped = cell.strip()
                            if stripped:
                                if not first_hit_done:
                                    result_parts.append(
                                        f' <mark id="first-hit">{stripped}</mark> |'
                                    )
                                    first_hit_done = True
                                else:
                                    result_parts.append(f" <mark>{stripped}</mark> |")
                            else:
                                result_parts.append(" |")
                        # 不需要额外加尾部的 |
                        marked_line = "".join(result_parts)
                        output.append(marked_line)
                else:
                    if not first_hit_done:
                        output.append(f'<mark id="first-hit">{line}</mark>')
                        first_hit_done = True
                    else:
                        output.append(f"<mark>{line}</mark>")
            else:
                output.append(line)

        # normal line
        else:
            output.append(line)

    return "\n".join(output)


def auto_scroll_chat(client):
    client.run_javascript("scrollToBottom()")


@ui.page("/")
def main(username: str = Depends(verify_password)):
    chat_history = app.storage.user.setdefault("chat_history", [])
    debug_panel_shown = False

    def clear_chat():
        chat_history.clear()
        chat_scroll.clear()
        clear_button.disable()
        clear_button.style("""
            filter: grayscale(1);
        """)
        nonlocal debug_panel_shown
        debug_panel_shown = True
        show_hide_debug_panel()

    def confirm_clear():
        with ui.dialog().props("persistent") as dialog:
            with ui.card().style(
                """
                width: 500px;
                max-width: 90vw;
                background: #313131;
                """
            ):
                ui.markdown("### 清空聊天记录")
                ui.label("确定清空聊天记录吗，目前清空后聊天记录就无法恢复了哦？")

                with ui.row().classes("w-full justify-end gap-2 mt-4"):
                    ui.button("取消", on_click=dialog.close).props("flat icon='close'")
                    ui.button(
                        "确定",
                        on_click=lambda: (
                            clear_chat(),
                            dialog.close(),
                        ),
                    ).props("color=primary icon='check'")
        dialog.open()

    def show_inline_rag_confirm(question, container, client):
        container.clear()
        with container:
            ui.label("❓需要继续从资料库检索吗？").classes("text-sm text-gray-400")

            def on_yes():
                container.clear()
                container.delete()
                asyncio.create_task(
                    send_message(
                        question,
                        force_rag=True,
                        from_confirm=True,
                        client=client,
                    )
                )

            def on_no():
                container.clear()
                container.delete()

            ui.button("否", on_click=on_no).props("flat dense size=sm icon='close'")
            ui.button("是", on_click=on_yes).props("dense size=sm icon='check'")

    def show_file_preview(name, path, hits):

        content = read_file_by_path(path)

        highlighted_md = build_highlighted_markdown(
            content,
            hits,
        )

        highlighted_html = render_markdown_html(
            highlighted_md,
        )

        with ui.dialog().props("maximized persistent") as dialog:
            with ui.card().style(
                """
        width: 1200px;
        max-width: 90vw;

        height: 900px;
        max-height: 90vh;

        position: relative;

        background: #313131;

        padding: 16px;
        """
            ):
                ui.button(
                    icon="close",
                    on_click=dialog.close,
                ).props("flat round dense").style(
                    """
                    position: absolute;
                    top: 16px;
                    right: 8px;
                    z-index: 10;
                    """
                )

                ui.html(f"""
                <div>
                    <div style="font-size:20px;font-weight:600;">
                        《{name}》
                    </div>

                    <div style="
                        color:#888;
                        font-size:12px;
                        margin-top:6px;
                        margin-left:12px;
                    ">
                        智能助手回答时参考了本文档的 {len(hits)} 段内容，参考文本见高亮区域。
                    </div>
                </div>
                """)

                original_path = f"{ref_path}\\pdf\\{name}.pdf"
                web_path = f"/static/ref_md/pdf/{name}.pdf"
                # print(original_path)
                # print(Path(original_path).exists())
                # print(web_path)
                if original_path and Path(original_path).exists():
                    # ui.link(
                    #     "🔗查看原始文档",
                    #     web_path,
                    #     new_tab=True,
                    # )
                    ui.button(
                        icon="picture_as_pdf",
                        text="请查看完整的原始文档获取更详细的信息",
                        on_click=lambda: ui.navigate.to(web_path, new_tab=True),
                    ).props("flat dense size=md")

                ui.html(highlighted_html).classes("w-full").style(
                    """
                    flex: 1;
                    overflow-y: auto;
                    background: #1b1b1b;
                    border: 1px solid #3a3a3a;
                    border-radius: 8px;
                    padding: 8px;
                    """
                )

                with ui.row().classes("w-full justify-center"):
                    ui.button(
                        "关闭",
                        on_click=dialog.close,
                    ).style(
                        """
                        width: 160px;
                        """
                    )
                ui.run_javascript("""
                setTimeout(() => {
                    document.getElementById("first-hit")
                        ?.scrollIntoView({
                            behavior: "smooth",
                            block: "center"
                        });
                }, 500);
                """)

        dialog.open()

    message_id = 0
    # page
    ui.add_head_html("""
        <script>
        window.MathJax = {
        tex: {
            inlineMath: [['$', '$'], ['\\\\(', '\\\\)']]
        }
        };
        </script>
        <style>
        </style>
        """)
    ui.add_head_html("""
        <link rel="stylesheet" href="/static/css/app.css">
    """)
    ui.add_body_html("""
        <script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
    """)
    ui.add_body_html("""
        <script src="/static/js/chat_scroll.js"></script>
    """)

    ui.dark_mode(True)
    ui.colors(
        primary="#4f8cff",
        secondary="#2d2d2d",
        accent="#1f1f1f",
        dark="#111111",
    )

    def show_hide_debug_panel():
        nonlocal debug_panel_shown
        debug_panel_shown = not debug_panel_shown
        if debug_panel_shown:
            right_column.style(
                """
                display: block;
                """
            )
            outer_container.style(remove="max-width: 960px;")
            outer_container.style("max-width: 1280px;")
        else:
            outer_container.style(remove="max-width: 1280px;")
            outer_container.style("max-width: 960px;")
            right_column.style(
                """
                display: none;
                """
            )

    with ui.column().classes(
        "w-full h-screen max-w-7xl mx-auto px-2 py-1 gap-0 overflow-hidden"
    ):
        with ui.row().classes("w-full items-center justify-between mt-0 mb-0"):
            with ui.row().classes("items-center gap-4 mt-0 mb-0"):
                with ui.row().classes("items-center gap-0 mt-0 mb-0 ml-4"):
                    ui.icon("database").props("size=medium")
                    ui.label("企业知识库").style("font-size: 16px; font-weight: 600;")
                quick_questions = [
                    "什么是数据质量保障?",
                    "IMSI和MSISDN和IMPI和IMPU的关系?",
                    "华为HSS数据有哪些类型和格式?",
                    "STNSR",
                    "SRVCC",
                ]
                for q in quick_questions:
                    ui.button(q, on_click=lambda msg=q: send_message(msg)).props(
                        "flat dense size=sm"
                    )
            ui.label("ver 0.1.1").style(
                "font-size: 12px; color: #888; margin-right: 12px;"
            )
            ui.button().props('icon="logout" round').on(
                "click", lambda: ui.navigate.to("/logout")
            )

        initial_container_height = "100%" if chat_history else "60%"
        outer_container = (
            ui.row()
            .classes("w-full no-wrap outer-container")
            .style(
                f"""
                height: {initial_container_height};
                max-width: 960px;
                margin: 0 auto;
                padding: 4px;
                gap: 4px;
                overflow: hidden;
                transition: height 0.3s ease;
                """
            )
        )
        with outer_container:
            # left
            left_column = ui.column().style(
                """
                position: relative;
                flex: 1;
                height: 100%;
                overflow: hidden;
                """
            )
            with left_column:
                (
                    ui.button(
                        icon="keyboard_arrow_down",
                        on_click=lambda: context.client.run_javascript(
                            "scrollToBottom()"
                        ),
                    )
                    .classes("scroll-to-bottom-btn")
                    .props("round")
                    .style("""
                        position: absolute;
                        bottom: 30px;
                        left: 50%;
                        transform: translateX(-50%);
                        z-index: 100;
                        opacity: 0.0;
                        transition: opacity 0.5s;
                    """)
                )

                # 空状态区域
                empty_state = (
                    ui.column()
                    .classes("empty-state items-center justify-center")
                    .style("""
                        position: absolute;
                        inset: 0;

                        z-index: 5;
                        pointer-events: none;

                        gap: 10px;

                        opacity: 1;
                        transition: opacity 0.25s ease;
                        transform: translateY(80px);
                    """)
                )

                with empty_state:
                    ui.image("images/logo.png").style("""
                        width: 128px;
                        height: 128px;
                        opacity: 0.9;
                    """)

                    ui.label("企业知识库").style("""
                        font-size: 28px;
                        font-weight: 700;
                        color: #f0f0f0;
                        letter-spacing: 1px;
                        margin-top: 4px;
                    """)

                    ui.label(
                        "查询公司内部资料、项目方案、软件系统、版本历史\n移动通信领域术语、用户数据定义、表结构信息"
                    ).style("""
                        white-space: pre-line;

                        text-align: center;
                        line-height: 1.7;

                        font-size: 15px;
                        color: #9aa4b2;

                        max-width: 520px;
                    """)

                # chat area
                chat_scroll = (
                    ui.column()
                    .classes("w-full chat-area")
                    .style(
                        """
                    flex: 1;
                    overflow-y: auto;
                    background: #313131;

                    border: none;
                    border-radius: 8px;

                    padding: 12px;
                    margin: 0px;
                    """
                    )
                )
                with chat_scroll:
                    for item in chat_history:
                        if not item["confirm"]:
                            with ui.row().classes("w-full justify-end"):
                                with ui.chat_message(
                                    sent=True,
                                    name="用户🧑",
                                    stamp=item["qtime"],
                                ).style("max-width: 85%;"):
                                    ui.markdown(item["question"])

                        with ui.column().classes("w-full items-start mt-0 mb-0"):
                            with ui.chat_message(
                                sent=False,
                                name="🧠历史回复",
                            ).style("max-width: 95%;"):
                                html = render_markdown_html(item["answer"])
                                message_id += 1
                                ui.html(html).props(
                                    f"id=assistant-msg{message_id}"
                                ).style(
                                    """
                                    width: 100%;
                                    """
                                )
                                context.client.run_javascript(f"""
                                if (window.MathJax) {{
                                    MathJax.typesetPromise();
                                    const el = document.getElementById("assistant-msg{message_id}");
                                    MathJax.typesetPromise([el]);
                                }}
                                """)
                            if item["sources"]:
                                with (
                                    ui.row()
                                    .classes("gap-0 mt-0 mb-0")
                                    .style("max-width: 95%;")
                                ):
                                    for source in item["sources"]:
                                        ui.button(
                                            Path(source["file_name"]).stem,
                                            icon="description",
                                            on_click=lambda n=Path(source["file_name"]).stem, p=source["path"], h=source["hits"]: (
                                                show_file_preview(n, p, h)
                                            ),
                                        ).props("flat dense").style("""
                                            white-space: nowrap;
                                            flex-shrink: 0;
                                            min-width: 140px;
                                        """)

            # right
            right_column = ui.column().style(
                """
                width: 24%;
                height: 100%;
                overflow: hidden;
                display: none;
            """
            )

            with right_column:
                # debug
                debug_panel = ui.html(
                    """
                    <div class="debug-panel">
                        暂无调试信息
                    </div>
                    """
                ).classes("w-full")

                debug_panel.style(
                    """
                    width: 100%;
                    border: 1px solid #3a3a3a;
                    border-radius: 8px;
                    padding: 12px;
                    height: 100%;
                    overflow-y: auto;
                    font-size: 12px;
                    background: #1b1b1b;
                    """
                )
        # input row
        with (
            ui.row()
            .classes("w-full items-center justify-center no-wrap")
            .style(
                """
                padding-top: 4px;
                padding-bottom: 28px;
                """
            )
        ):
            clear_button = ui.button(
                icon="cleaning_services", on_click=confirm_clear
            ).props("round")
            if len(chat_scroll.default_slot.children) > 0:
                clear_button.enable()
                clear_button.style("""
                    filter: none;
                """)
            else:
                clear_button.disable()
                clear_button.style("""
                    filter: grayscale(1);
                """)
            with (
                ui.input(
                    placeholder="请输入简短词汇进行字典查询，或输入完整问题进行知识库检索..."
                )
                .classes("chat-input")
                .props("clearable")
                .style("""
                flex: 1;
                min-width: 0;
                max-width: 900px;
            """) as input_box
            ):
                with input_box.add_slot("append"):
                    send_button = ui.button(
                        icon="send",
                    ).props("flat round dense")

            async def send_message(
                message=None,
                force_rag=False,
                from_confirm=False,
                client=None,
            ):

                try:
                    if client is None:
                        client = context.client

                    if message is None:
                        message = (input_box.value or "").strip()

                    if not message:
                        return

                    input_box.value = ""
                    send_button.disable()
                    send_button.props("loading")
                    clear_button.disable()
                    clear_button.style("""
                        filter: grayscale(1);
                    """)

                    input_box.disable()
                    nonlocal debug_panel_shown
                    log(f"Question: {message}", False)

                    # messages
                    qtime = f"\U0001f550{datetime.datetime.now().strftime('%H:%M:%S')}"
                    with chat_scroll:
                        if not from_confirm:
                            # 用户消息：右边
                            with ui.row().classes("w-full justify-end"):
                                with ui.chat_message(
                                    sent=True,
                                    name="用户🧑",
                                    stamp=qtime,
                                ).style("max-width: 85%;"):
                                    ui.markdown(message)

                        # 助理消息
                        with ui.column().classes("w-full items-start mt-0 mb-0"):
                            llm_msg = ui.chat_message(
                                sent=False,
                                name="\U00002728智能助理",
                            ).style("max-width: 95%;")

                            with llm_msg:
                                wait_html = markdown.markdown(
                                    "&nbsp;&nbsp;\U000023f3我正在检索资料库，可能需要时间，请耐心等候……&nbsp;&nbsp;",
                                )
                                nonlocal message_id
                                message_id += 1
                                assistant_message = (
                                    ui.html(
                                        f"""
                                    <div class="streaming-text loading-text">
                                        {wait_html}
                                    </div>
                                    """
                                    )
                                    .props(f"id=assistant-msg{message_id}")
                                    .style(
                                        """
                                    width: 100%;
                                    """
                                    )
                                )

                            sources_container = (
                                ui.row().classes("gap-0 mt-0 mb-0").style("width: 95%;")
                            )
                            action_container = ui.row().classes("gap-2 mt-0 mb-0")
                            auto_scroll_chat(client)

                    # reset status
                    debug_panel.content = """
                    <div class="debug-panel">
                        waiting for data...
                    </div>
                    """
                    debug_panel.update()

                    # state
                    partial_text = ""
                    source_nodes = []
                    got_answer = False
                    dct_answer = False
                    first_token = False
                    timing = {}
                    # background stream
                    queue = Queue()

                    def worker():
                        try:
                            for event in service.stream_answer(message, force_rag):
                                queue.put(event)
                        finally:
                            queue.put(None)

                    threading.Thread(
                        target=worker,
                        daemon=True,
                    ).start()

                    # consume
                    accumulated = ""
                    while True:
                        event = await asyncio.to_thread(queue.get)
                        if event is None:
                            break

                        # token
                        if event["type"] == "token":
                            got_answer = True
                            if not first_token:
                                log("Streaming...")
                            first_token = True
                            accumulated += event["content"]
                            if "\n" in accumulated:
                                partial_text += accumulated
                                accumulated = ""
                                rendered_html = render_markdown_html(partial_text)
                                assistant_message.content = rendered_html
                                assistant_message.update()
                                # auto scroll
                                auto_scroll_chat(client)

                        # sources
                        elif event["type"] == "sources":
                            source_nodes = event["content"]

                        # debug
                        elif event["type"] == "debug":
                            timing = event["content"].get("timing", {})
                            debug_html = build_debug_html(event["content"])
                            debug_panel.content = debug_html
                            debug_panel.update()

                        # status
                        elif event["type"] == "status":
                            dct_answer = event["source"] == "dict"
                            got_answer = event["got_answer"]
                            if event.get("need_rag_confirm"):
                                show_inline_rag_confirm(
                                    event.get("original_question"),
                                    action_container,
                                    client,
                                )

                    if accumulated:
                        partial_text += accumulated

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
                        log(
                            f"Total token usage: {usage['total']['total_tokens']}",
                            False,
                        )
                    print()

                    # fallback
                    if not got_answer:
                        partial_text = "对不起，我检索了资料，但还是不知道答案……"

                    # references
                    (
                        ref_text,
                        file_map,
                    ) = build_reference_files(source_nodes)

                    # if ref_text:
                    #     partial_text += f"\n  \n---  \n##### 参考文件\n{ref_text}"

                    # source buttons
                    should_show_sources = (
                        ref_text
                        and got_answer
                        and partial_text.strip()
                        not in [
                            "不知道",
                            "不知道.",
                            "不知道。",
                            "我不知道",
                            "我不知道.",
                            "我不知道。",
                            "无法回答",
                        ]
                    )
                    # final update

                    atime = f"🕐{datetime.datetime.now().strftime('%H:%M:%S')}"
                    partial_text += f"""
                        <div style="text-align:right; font-size:12px; color:#888888 !important;">
                        ⚡{timing.get("total_ms", 0)}ms &nbsp;&nbsp;&nbsp;&nbsp; {atime}
                        </div>
                    """
                    rendered_html = render_markdown_html(partial_text)
                    assistant_message.content = rendered_html
                    assistant_message.update()
                    client.run_javascript(f"""
                    if (window.MathJax) {{
                        MathJax.typesetPromise();
                        const el = document.getElementById("assistant-msg{message_id}");
                        MathJax.typesetPromise([el]);
                    }}
                    """)

                    history_item = {
                        "question": message,
                        "qtime": qtime,
                        "answer": partial_text,
                        "atime": atime,
                        "confirm": from_confirm,
                        "sources": [],
                    }
                    if should_show_sources:
                        shown_files = set()
                        with sources_container:
                            with ui.row().classes("gap-2 mt-0").style("width: 95%;"):
                                for file_name, file_info in file_map.items():
                                    file_path = file_info["path"]
                                    hits = file_info["hits"]
                                    if file_name in shown_files:
                                        continue

                                    shown_files.add(file_name)

                                    ui.button(
                                        Path(file_name).stem,
                                        icon="description",
                                        on_click=lambda n=Path(file_name).stem, p=file_path, h=hits: (
                                            show_file_preview(n, p, h)
                                        ),
                                    ).props("flat dense")
                                    history_item["sources"].append(
                                        {
                                            "file_name": file_name,
                                            "path": file_info["path"],
                                            "hits": file_info["hits"],
                                        }
                                    )
                    else:
                        sources_container.delete()
                    chat_history.append(history_item)

                except Exception as e:
                    partial_text += f"  \n  \n  `📛出现了错误：{str(e)}`！"
                    atime = f"🕐{datetime.datetime.now().strftime('%H:%M:%S')}"
                    partial_text += f"""
                        <div style="text-align:right; font-size:12px; color:#888888 !important;">
                        {atime}
                        </div>
                    """
                    rendered_html = render_markdown_html(partial_text)
                    log(e)
                    print(traceback.format_exc())
                    assistant_message.content = rendered_html
                    assistant_message.update()
                finally:
                    auto_scroll_chat(client)
                    send_button.enable()
                    send_button.props(remove="loading")
                    clear_button.enable()
                    clear_button.style("""
                        filter: none;
                    """)
                    input_box.enable()

            # enter submit
            input_box.on(
                "keydown.enter",
                lambda e: send_message(),
            )
            send_button.on("click", send_message)
            debug_button = ui.button()
            debug_button.props('icon="developer_mode" round')
            debug_button.on("click", show_hide_debug_panel)


@app.get("/logout")
def logout():
    return HTMLResponse(
        """
    <html>
    <body style="
        background:#111;
        color:white;
        font-family:sans-serif;
        display:flex;
        justify-content:center;
        align-items:center;
        height:100vh;
        flex-direction:column;
    ">
        <h2>已退出登录</h2>
        <p>关闭浏览器后认证通常会失效。</p>

        <a href="/" style="
            color:#4f8cff;
            margin-top:20px;
        ">
            返回首页
        </a>
    </body>
    </html>
    """,
        status_code=401,
        headers={"WWW-Authenticate": "Basic"},
    )


# run app
ui.run(
    host="0.0.0.0",
    port=7860,
    title="企业知识库",
    language="zh-CN",
    storage_secret=settings.storage_secret,
    reload=False,
    dark=True,
)

import sys
import asyncio
import datetime
from pathlib import Path
import threading
from queue import Queue
import traceback
import time
import markdown
from nicegui import ui
from nicegui import app
from nicegui import context
from rich import print
import re
from rag.formatter import build_reference_files
from rag.formatter import build_debug_html
from utils.logger import logger
from utils.settings import (
    settings,
    rewrite_image_paths,
    REF_MD_DIR,
    ORI_PDF_DIR,
    version_num,
)


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


def get_speed_str(total_ms: float) -> str:
    if total_ms < 500:
        speed_str = "⚡"
    elif total_ms < 2000:
        speed_str = "🚀"
    elif total_ms < 5000:
        speed_str = "✈️"
    elif total_ms < 10000:
        speed_str = "🚅"
    elif total_ms < 20000:
        speed_str = "🚗"
    elif total_ms < 40000:
        speed_str = "🏃"
    elif total_ms < 60000:
        speed_str = "🚶"
    else:
        speed_str = "🐢"
    return speed_str


def auth_guard():
    if not app.storage.user.get("authenticated", False):
        ui.navigate.to("/login")


def logout():
    app.storage.user.clear()
    ui.navigate.to("/login")


app.add_static_files("/static/js", "./src/ui/js")
app.add_static_files("/static/css", "./src/ui/css")
app.add_static_files("/static/images", "./images")
if settings.app_doc_path:
    app.add_static_files("/static/ref_md", f"{settings.app_doc_path}/{REF_MD_DIR}")
    app.add_static_files("/static/ori_pdf", f"{settings.app_doc_path}/{ORI_PDF_DIR}")


def render_markdown_html(md_str: str, class_name: str = "final-markdown") -> str:
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
            <div class="{class_name}">
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
    CODE_FENCE_RE = re.compile(r"^\s*(```+|~~~+)")
    lines = content.splitlines()
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

    # code fence state
    in_code_block = False
    current_fence = None

    for idx, line in enumerate(lines):
        # detect fence
        fence_match = CODE_FENCE_RE.match(line)
        if fence_match:
            fence = fence_match.group(1)
            # entering code block
            if not in_code_block:
                in_code_block = True
                current_fence = fence

            # leaving code block
            elif fence.startswith(current_fence[0]):
                in_code_block = False
                current_fence = None

            output.append(line)
            continue

        # do not highlight inside code block
        if in_code_block:
            output.append(line)
            continue

        # normal highlight logic
        if idx in highlighted:
            # avoid empty line highlight issue
            if line.strip() and not line.lstrip().startswith("#"):
                # markdown table
                if line.lstrip().startswith("|"):
                    parts = line.split("|")
                    # preserve original structure
                    is_separator = False
                    if len(parts) > 2:
                        non_empty_cells = [p for p in parts if p.strip()]
                        is_separator = all(
                            all(ch in "- :" for ch in cell.strip())
                            and "-" in cell.strip()
                            for cell in non_empty_cells
                            if cell.strip()
                        )

                    # separator row
                    if is_separator:
                        # 分隔行，保持原样
                        output.append(line)
                    # data row
                    else:
                        # 数据行，高亮每个单元格内容
                        result_parts = ["|"]  # 开头
                        for cell in parts[1:-1]:
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
                # markdown list
                else:
                    # 检查当前行是否为列表项
                    m = re.match(r"^(\s*(?:\*|-|\+|\d+[.)])\s+)(.*)", line)
                    if m:
                        # 检查上一行是否为列表项
                        prev_line = output[-1] if output else ""
                        prev_is_list = re.match(
                            r"^\s*(?:\*|-|\+|\d+[.)])\s+",
                            prev_line,
                        )
                        if prev_line.strip() and not prev_is_list:
                            output.append("")

                        # 判断是否为第一个高亮项
                        if not first_hit_done:
                            output.append(
                                f"{m.group(1)}=={m.group(2)}==<mark id='first-hit'/>"
                            )
                            first_hit_done = True
                        else:
                            output.append(f"{m.group(1)}=={m.group(2)}==")
                    else:
                        if not first_hit_done:
                            output.append(f'=={line}== <mark id="first-hit"/>')
                            first_hit_done = True
                        else:
                            output.append(f"=={line}==")
            else:
                output.append(line)

        # normal line
        else:
            output.append(line)

    return "\n".join(output)


def auto_scroll_chat(client):
    client.run_javascript("scrollToBottom()")


@ui.page("/")
def main():
    auth_guard()
    chat_history = app.storage.user.setdefault("chat_history", [])

    def clear_chat():
        chat_history.clear()
        chat_scroll.clear()
        clear_menu_item.disable()
        clear_menu_item.style("filter: grayscale(1);")
        clear_badge.set_text("0")
        clear_badge.set_background_color("gray")
        switch_debug.set_value(False)
        switch_debug.set_enabled(False)
        debug_panel.content = """
        <div class="debug-panel">
            waiting for data...
        </div>
        """
        debug_panel.update()

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
                        query_mode=QueryMode.CONFIRM_RAG,
                        client=client,
                    )
                )

            def on_no():
                container.clear()
                container.delete()

            ui.button("否", on_click=on_no).props("flat dense size=sm icon='close'")
            ui.button("是", on_click=on_yes).props("dense size=sm icon='check'")

    def show_inline_force_rag_confirm(question, container, client):
        container.clear()
        with container:
            ui.label(f"❓需要重新强制检索'{question}'吗？？").classes(
                "text-sm text-gray-400"
            )

            def on_yes():
                container.clear()
                container.delete()
                asyncio.create_task(
                    send_message(
                        f"'{question}'",
                        query_mode=QueryMode.QUOTED,
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
        highlighted_md = rewrite_image_paths(
            highlighted_md,
            path,
        )
        highlighted_html = render_markdown_html(
            highlighted_md,
            class_name="markdown-preview-light",
        )

        with ui.dialog().props("maximized persistent") as dialog:
            with ui.card().style(
                """
        width: 1280px;
        max-width: 92vw;

        height: 960px;
        max-height: 92vh;

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

                original_path = f"{settings.app_doc_path}\\{ORI_PDF_DIR}\\{name}.pdf"
                web_path = f"/static/ori_pdf/{name}.pdf"
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
                    background: #eed;
                    border: 1px solid #d0d0d0;
                    border-radius: 8px;
                    padding: 8px;
                    color-scheme: light;
                    scrollbar-color: #999 #eed;
                    scrollbar-width: auto;
                    """
                )

                with ui.row().classes("w-full justify-center"):
                    ui.button(
                        "关闭",
                        icon="close",
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

    def show_hide_debug_panel(show: bool):
        if show:
            right_column.style("display: block;")
            outer_container.style(remove="max-width: 960px;")
            outer_container.style("max-width: 1280px;")
        else:
            outer_container.style(remove="max-width: 1280px;")
            outer_container.style("max-width: 960px;")
            right_column.style("display: none;")

    with ui.column().classes(
        "w-full h-screen max-w-7xl mx-auto px-0 sm:px-2 py-1 gap-0 overflow-hidden"
    ):
        with ui.row().classes("w-full items-center justify-between mt-0 mb-0"):
            # =========================
            # 左侧整体区域，logo，标题，快捷提问
            # =========================
            with ui.row().classes("""
                items-center
                flex-1
                min-w-0
                no-wrap
                overflow-hidden
            """):
                # logo区域（固定宽度）
                with (
                    ui.row()
                    .classes("""
                        items-center
                        gap-0
                        mt-0
                        mb-0
                        ml-4
                        flex-shrink-0
                    """)
                    .style("width: 100px;")
                ):
                    ui.icon("database").props("size=medium")
                    ui.label("企业知识库").style("font-size: 16px; font-weight: 600;")

                # 快捷问题区域（桌面显示）
                with ui.row().classes("""
                    gt-sm
                    items-center
                    gap-4
                    ml-4
                    mr-4
                    no-wrap
                    overflow-x-auto
                    flex-1
                    min-w-0
                """):
                    quick_questions = [
                        "请介绍数据质量保障平台",
                        "IMSI和MSISDN和IMPI和IMPU的关系?",
                        "华为HSS数据有哪些类型和格式?",
                        "中兴HSS数据有哪些类型和格式?",
                        "SRVCC",
                        "STNSR",
                        "EPSSER",
                    ]

                    for q in quick_questions:
                        ui.button(q, on_click=lambda msg=q: send_message(msg)).props(
                            "flat dense size=sm"
                        )
                    switch_debug = ui.switch(
                        "debug", on_change=lambda e: show_hide_debug_panel(e.value)
                    )
                    switch_debug.set_enabled(False)

            # =========================
            # 右侧固定区域，版本号，菜单。
            # =========================
            with ui.row().classes("""
                items-center
                gap-2
                flex-shrink-0

                mr-2
            """):
                ui.label(f"ver {version_num}").style("""
                    font-size: 12px;
                    color: #888;
                """)

                with ui.button(icon="more_vert").props("flat round"):
                    clear_badge = ui.badge("0", color="gray").props("floating")
                    with ui.menu():
                        clear_menu_item = ui.menu_item(
                            "🧹 清空会话",
                            on_click=confirm_clear,
                        )
                        ui.separator()
                        ui.menu_item(
                            "🚪 退出登录",
                            on_click=logout,
                        )

        outer_container = (
            ui.row()
            .classes("w-full no-wrap outer-container")
            .style(
                """
                height: calc(100vh - 70px);
                max-width: 960px;
                margin: 0 auto;
                padding: 0px;
                gap: 0px;
                overflow: hidden;
                transition: height 0.3s ease;
                background: #313131;
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
                    ui.image("/static/images/logo.png").style(
                        "width: 128px; height: 128px; opacity: 0.9;"
                    )

                    ui.label("企业知识库").style(
                        "font-size: 28px; font-weight: 700; color: #f0f0f0; letter-spacing: 1px; margin-top: 4px;"
                    )

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
                        background: #303030;
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
                                message_id += 1
                                ui.html(item["answer"]).props(
                                    f"id=assistant-msg{message_id}"
                                ).style("width: 100%;")
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
                                    .classes("gap-2 mt-0 mb-0")
                                    .style("max-width: 95%;")
                                ):
                                    for source in item["sources"]:
                                        with ui.row().classes("items-start gap-0"):
                                            ui.link(
                                                f"""
                                                📄{Path(source["file_name"]).stem}
                                                """,
                                                target=None,
                                            ).style(
                                                "cursor: pointer; text-decoration: none;"
                                            ).props("no-caps").on(
                                                "click",
                                                lambda n=Path(source["file_name"]).stem, p=source["path"], h=source["hits"]: (
                                                    show_file_preview(n, p, h)
                                                ),
                                            )

                alen = len(chat_scroll.default_slot.children)
                clear_badge.set_text(f"{alen}")
                if alen == 0:
                    clear_badge.set_background_color("gray")
                    clear_menu_item.disable()
                    clear_menu_item.style("filter: grayscale(100%);")

                else:
                    clear_badge.set_background_color("red")
                    clear_menu_item.enable()
                    clear_menu_item.style("filter: none;")

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
                    padding: 8px;
                    height: 100%;
                    overflow-y: auto;
                    font-size: 12px;
                    background: #1b1b1b;
                    """
                )
        # input row
        with (
            ui.row()
            .classes("w-full justify-center no-wrap")
            .style("padding-top: 4px; padding-bottom: 28px;")
        ):
            with (
                ui.input(placeholder="请输入简短关键字或完整问题...")
                .classes("chat-input")
                .props("clearable type=text inputmode=text enterkeyhint=send")
                .style("""
                    width: 100%;
                    max-width: 860px;
                    margin-left: 20px;
                    margin-right: 20px;
                """) as input_box
            ):
                with input_box.add_slot("append"):
                    send_button = ui.button(
                        icon="send",
                    ).props("flat round dense")

            async def send_message(
                message=None,
                query_mode: QueryMode = QueryMode.NORMAL,
                client=None,
            ):
                partial_text = ""
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
                    clear_menu_item.disable()
                    clear_menu_item.style("filter: grayscale(1);")
                    clear_badge.set_text(f"{len(chat_scroll.default_slot.children)}")
                    clear_badge.set_background_color("gray")

                    input_box.disable()
                    switch_debug.set_value(False)
                    switch_debug.set_enabled(False)
                    print("=" * 60)
                    log(f"Question: {message}", False)
                    # reset status
                    debug_panel.content = """
                    <div class="debug-panel">
                        waiting for data...
                    </div>
                    """
                    debug_panel.update()
                    # messages
                    qtime = f"🕐{datetime.datetime.now().strftime('%H:%M:%S')}"
                    with chat_scroll:
                        if not query_mode == QueryMode.CONFIRM_RAG:
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
                                name="✨智能助理",
                            ).style("max-width: 95%;")

                            with llm_msg:
                                with ui.column().classes(
                                    "w-full items-start mt-0 mb-0"
                                ):
                                    assistant_stage_spinner = ui.spinner(
                                        "dots", size="md"
                                    ).classes("mt-0 mb-0")
                                    assistant_answer_spinner = ui.spinner(
                                        "facebook", size="md"
                                    ).classes("mt-0 mb-0")
                                    assistant_answer_spinner.set_visibility(False)

                                    rendered_html = render_markdown_html("### 思考中")
                                    nonlocal message_id
                                    message_id += 1
                                    assistant_message = (
                                        ui.html(rendered_html)
                                        .props(f"id=assistant-msg{message_id}")
                                        .style(
                                            """
                                            width: 100%;
                                            """
                                        )
                                    )
                                    auto_scroll_chat(client)

                            sources_container = (
                                ui.row().classes("gap-0 mt-0 mb-0").style("width: 95%;")
                            )
                            action_container = ui.row().classes("gap-2 mt-0 mb-0")
                            auto_scroll_chat(client)

                    # state
                    source_nodes = []
                    event_source = "none"
                    got_answer = False
                    answer_source = ""
                    first_token = False
                    first_trace = False
                    timing = {}
                    # background stream
                    queue = Queue()

                    def worker():
                        try:
                            for event in service.stream_answer(message, query_mode):
                                queue.put(event)
                        finally:
                            queue.put(None)

                    threading.Thread(
                        target=worker,
                        daemon=True,
                    ).start()

                    # consume
                    accumulated = ""
                    streaming_start = time.perf_counter()
                    while True:
                        event = await asyncio.to_thread(queue.get)
                        if event is None:
                            break

                        # token
                        if event["type"] == "token":
                            got_answer = True
                            if not first_token:
                                log("Streaming...")
                                streaming_start = time.perf_counter()
                                partial_text = ""
                                first_token = True
                                if assistant_stage_spinner:
                                    assistant_stage_spinner.set_visibility(False)
                                if assistant_answer_spinner:
                                    assistant_answer_spinner.set_visibility(True)
                            accumulated += event["text"]
                            if "\n" in accumulated or len(accumulated) > 23:
                                partial_text += accumulated
                                accumulated = ""
                                rendered_html = render_markdown_html(partial_text)
                                assistant_message.content = rendered_html
                                assistant_message.update()
                                auto_scroll_chat(client)

                        elif event["type"] == "trace":
                            if not first_trace:
                                partial_text = "### 思考中\n\n"
                                first_trace = True
                            trace_stage = event["stage"]
                            trace_message = event["message"]
                            trace_timing = event["timing"]
                            msg_str = f"- **[{trace_stage}]** {trace_message}"
                            timing_str = (
                                "" if not trace_timing else f"(_{trace_timing}ms_)"
                            )
                            partial_text += f"{msg_str} {timing_str}\n\n"
                            rendered_html = render_markdown_html(partial_text)
                            assistant_message.content = rendered_html
                            assistant_message.update()
                            auto_scroll_chat(client)

                        # sources
                        elif event["type"] == "sources":
                            source_nodes = event["nodes"]

                        # debug
                        elif event["type"] == "debug":
                            timing = event
                            debug_html = build_debug_html(event)
                            debug_panel.content = debug_html
                            debug_panel.update()
                            switch_debug.set_enabled(True)

                        # status
                        elif event["type"] == "status":
                            event_source = event["source"]
                            answer_source = event_source
                            got_answer = event["got_answer"]
                            if event.get("need_rag_confirm"):
                                show_inline_rag_confirm(
                                    event.get("original_question"),
                                    action_container,
                                    client,
                                )
                            if event.get("need_force_rag_confirm"):
                                show_inline_force_rag_confirm(
                                    event.get("original_question"),
                                    action_container,
                                    client,
                                )

                    if accumulated:
                        partial_text += accumulated
                    streaming_s = round(
                        (time.perf_counter() - streaming_start),
                        2,
                    )
                    log("Answer completed")
                    log("----------------")
                    log(
                        f"Retrieval: {timing.get('query_ms', 0)} ms, Answers: {timing.get('llm_ms', 0)} ms, Total: {timing.get('total_ms', 0)} ms",
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
                    print()

                    # fallback
                    if not got_answer:
                        partial_text = "对不起，我检索了资料，但还是不知道答案……"

                    # references
                    (
                        ref_text,
                        file_map,
                    ) = build_reference_files(source_nodes)

                    # source buttons
                    should_show_sources = (
                        ref_text
                        and got_answer
                        and not partial_text.strip().startswith(
                            (
                                "不知道",
                                "我不知道",
                                "无法回答",
                            )
                        )
                    )
                    # final update
                    source_hint = ""
                    if event_source == "dict":
                        source_hint = "🔍"
                    elif event_source == "llm":
                        source_hint = f"📖{answer_model}"
                    elif event_source == "cache":
                        source_hint = "📦"

                    atime = f"🕐{datetime.datetime.now().strftime('%H:%M:%S')}"
                    total_ms = timing.get("total_ms", 0)
                    speed_str = get_speed_str(float(total_ms))
                    footer = f"""
                        <br>
                        <div style="text-align:right; font-size:12px; color:#888888 !important;">
                        {source_hint}&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; {speed_str}{logger.format_duration(total_ms)} &nbsp;&nbsp;&nbsp;&nbsp; {atime}
                        </div>
                    """
                    rendered_html = render_markdown_html(partial_text)
                    assistant_message.content = rendered_html + footer
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
                        "answer": rendered_html + footer,
                        "atime": atime,
                        "confirm": query_mode == QueryMode.CONFIRM_RAG,
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
                                    with ui.row().classes("items-start gap-0"):
                                        ui.link(
                                            f"""
                                            📄{Path(file_name).stem}
                                            """,
                                            target=None,
                                        ).style(
                                            "cursor: pointer; text-decoration: none;"
                                        ).props("no-caps").on(
                                            "click",
                                            lambda n=Path(file_name).stem, p=file_path, h=hits: (
                                                show_file_preview(n, p, h)
                                            ),
                                        )
                                    history_item["sources"].append(
                                        {
                                            "file_name": file_name,
                                            "path": file_info["path"],
                                            "hits": file_info["hits"],
                                        }
                                    )
                    else:
                        if sources_container:
                            sources_container.delete()
                    chat_history.append(history_item)

                except Exception as e:
                    partial_text += f"  \n  \n  `📛出现了错误：{str(e)}`！"
                    atime = f"🕐{datetime.datetime.now().strftime('%H:%M:%S')}"
                    rendered_html = render_markdown_html(partial_text)
                    log(e)
                    print(traceback.format_exc())
                    if assistant_message:
                        assistant_message.content = rendered_html
                        assistant_message.update()
                finally:
                    if assistant_stage_spinner:
                        assistant_stage_spinner.delete()
                    if assistant_answer_spinner:
                        assistant_answer_spinner.delete()
                    auto_scroll_chat(client)
                    send_button.enable()
                    send_button.props(remove="loading")
                    clear_menu_item.enable()
                    clear_menu_item.style("filter: none;")
                    clear_badge.set_text(f"{len(chat_scroll.default_slot.children)}")
                    clear_badge.set_background_color("red")
                    input_box.enable()

            # enter submit
            input_box.on(
                "keydown.enter",
                lambda e: send_message(),
            )
            send_button.on("click", send_message)


@ui.page("/login")
def login():
    ui.add_head_html("""
        <link rel="stylesheet" href="/static/css/app.css">
    """)
    if app.storage.user.get("authenticated", False):
        ui.navigate.to("/")
        return

    def try_login():
        if (
            username.value == settings.webui_username
            and password.value == settings.webui_password
        ):
            app.storage.user["authenticated"] = True
            ui.navigate.to("/")
        else:
            ui.notify("用户名或密码错误", color="negative", position="center")

    with (
        ui.column()
        .classes("absolute-center items-center w-80 gap-4")
        .style("""
        transform: translate(-50%, -30%);
    """)
    ):
        ui.image("/static/images/logo.png").style(
            "width: 128px; height: 128px; opacity: 0.9;"
        )
        ui.label("企业知识库").style("font-size:28px; font-weight:700;")

        username = (
            ui.input(placeholder="请输入用户名")
            .classes("chat-input w-full")
            .props("clearable")
        )
        password = (
            ui.input(
                placeholder="请输入密码",
                password=True,
                password_toggle_button=True,
            )
            .classes("chat-input w-full")
            .props("clearable")
        )
        password.on(
            "keydown.enter",
            lambda e: try_login(),
        )

        with password.add_slot("append"):
            ui.button(
                icon="login",
                on_click=try_login,
            ).props("flat round dense")


# run app
ui.run(
    host=settings.host,
    port=settings.port,
    title="企业知识库",
    language="zh-CN",
    storage_secret=settings.storage_secret,
    reload=False,
    dark=True,
)

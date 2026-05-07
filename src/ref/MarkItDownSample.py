import sys

from markitdown import MarkItDown
from openai import OpenAI
import datetime
from pathlib import Path


def log(msg):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    print(f"[{timestamp}] {msg}")


if len(sys.argv) != 3:
    print("Usage: python script.py <input_dir> <output_dir>")
    sys.exit(1)


log("Start")

input_dir = Path(sys.argv[1])
output_dir = Path(sys.argv[2])

if not input_dir.is_dir():
    print(f"Input directory does not exist: {input_dir}")
    sys.exit(1)

output_dir.mkdir(parents=True, exist_ok=True)

client = OpenAI(base_url="http://localhost:8999/v1", api_key="dummy")

md = MarkItDown(
    enable_plugins=True,
    llm_client=client,
    llm_model="gemma-4-26B-A4B-it-UD-IQ2_M",
    llm_prompt="""
请分析这张图片，用于技术文档 RAG 知识库中的图片摘要生成。

目标：
为中文技术文档中的图片生成简洁、准确、适合检索的摘要。

关键要求：
- 不要进行全面 OCR。
- 不要大量转录图片中的文字。
- 不要推测隐藏的业务含义。
- 不要臆造流程、阶段、标签或关系。
- 只描述图片中可以直接看到的信息。
- 宁可少提取，也不要幻觉生成。
- 所有输出必须使用简体中文。
- 保留必要的英文产品名、系统名或界面标签。
- 输出必须简洁、事实化、适合检索。

输出格式：

[图片摘要]

类型：<界面截图 | 架构图 | 流程图 | 表格 | 代码截图 | 装饰性图片 | 其他>

可见特征：
- 简洁特征
- 简洁特征

关系：
- A -> B
- X 连接到 Y

重要标签：
- 可见标签
- 可见标签

不同图片类型的规则：

1. 界面截图
- 仅总结界面的可见用途。
- 忽略日志、时间戳、重复记录、菜单、按钮、状态栏以及大量界面文字。
- 不要描述详细运行数据。
- 最多保留 2~3 个关键点。

好的示例：
- 任务历史界面
- 工作流可视化区域
- 执行日志面板

错误示例：
- 单条日志内容
- 时间戳
- 用户名
- 运行时具体数值

2. 架构图 / 系统图
- 保留主要可见组件。
- 仅保留图中明确显示的连接关系。
- 不要臆造流程阶段。
- 忽略 Task1、ServerA、ExampleDB 等示例性占位名称，除非它们是核心内容。
- 如果图是概念性的，关系描述保持通用。

好的示例：
- 任务平台连接业务数据库
- 数据库连接 Web 查询系统

错误示例：
- 臆造图中未明确显示的处理流程

3. 流程图
- 仅保留清晰可读且重要的步骤名称与方向关系。
- 忽略装饰性箭头或仅用于排版的连接线。

4. 表格
- 仅提取有意义的结构化知识。
- 忽略运行日志类或重复性记录。

5. 代码截图
- 仅总结代码用途。
- 仅在必要时提取关键标识符。

6. 装饰性图片或低信息量图片

输出格式必须严格为：

[图片摘要]
类型：装饰性图片

最终规则：
- 所有自然语言描述必须使用简体中文。
- 仅描述视觉上可以验证的信息。
- 优先保证准确性，而不是完整性。
- 建议控制在 80 字以内。
""",
)


# 支持的文件类型
extensions = {".docx", ".pdf", ".xlsx"}


for input_file in input_dir.rglob("*"):
    if not input_file.is_file():
        continue

    if input_file.suffix.lower() not in extensions:
        continue

    # 保持文件名，仅改后缀为 .md
    output_file = output_dir / f"{input_file.stem}.md"

    try:
        log(f"Processing: {input_file}")

        result = md.convert(str(input_file))

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(result.text_content)

        log(f"Done: {output_file}")

    except Exception as e:
        log(f"Failed: {input_file}")
        log(str(e))

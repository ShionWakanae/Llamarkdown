import re
from pathlib import Path
from typing import List, Optional


LIST_RE = re.compile(r"^(\s*(?:\*|-|\+|\d+[.)])\s+)(.*)")
CODE_FENCE_RE = re.compile(r"^[ \t]{0,3}(```+|~~~+)")


class MarkdownTextCleaner:
    """
    Unified markdown text cleaner.

    Processing model:
    1. Full-text transforms
    2. Line-based transforms with shared state/context
    3. Optional business logic (e.g. heading generation)
    """

    @classmethod
    def clean(
        cls,
        text: str,
        filename: Optional[str] = None,
        ensure_heading: bool = True,
    ) -> str:
        if not text:
            text = ""

        # Full-text processing
        text = cls._process_full_text(text)
        # Shared line context
        context = cls._create_line_context(text)
        # 自动识别并包裹疑似代码（同时更新 in_code_block）
        cls._wrap_auto_code_blocks(context)
        # Line-based processing pipeline
        cls._process_line_trailing_spaces(context)
        cls._process_list_spacing(context)
        # Rebuild text
        text = "\n".join(context["lines"])

        # Optional heading generation
        if ensure_heading and filename:
            has_level_one_heading = cls._has_level_one_heading(context)
            if not has_level_one_heading:
                text = cls._prepend_level_one_heading(text, filename)

        # Final full-text normalization
        text = cls._finalize_full_text(text)
        return text

    @staticmethod
    def _is_markdown_syntax(line: str) -> bool:
        """
        判断是否为明显的 Markdown 语法（不是代码）
        """
        if not line:
            return False

        # 图片
        if re.match(r"^!\[.*\]\(.*\)", line):
            return True

        # 链接
        if re.match(r"^\[[^\]]+\]\([^\)]+\)", line):
            return True

        # 多个 # 的标题
        if re.match(r"^#{2,6}\s+", line):
            return True

        # 无序列表
        if re.match(r"^[-*+]\s+", line):
            return True

        # 有序列表
        if re.match(r"^\d+[.)]\s+", line):
            return True

        # 表格
        if line.startswith("|") and line.endswith("|"):
            return True

        # 引用
        if line.startswith(">"):
            return True

        return False  # 重要：默认返回 False

    @classmethod
    def _wrap_auto_code_blocks(cls, context: dict) -> None:
        """
        在非代码块的普通文本中识别疑似代码（配置/XML/YAML/JSON/bash等），
        并用 ``` 包裹起来。同步更新 in_code_block 标记。
        """
        lines = context["lines"]
        in_code_flags = context["in_code_block"]

        # 标记 OCR 块区域（保持不变）
        ocr_flags = [False] * len(lines)
        i = 0
        n = len(lines)
        while i < n:
            stripped = lines[i].lstrip()
            if stripped == "*[Image OCR]*":
                ocr_flags[i] = True
                i += 1
                while i < n:
                    ocr_flags[i] = True
                    if lines[i].lstrip() == "*[End OCR]*":
                        i += 1
                        break
                    i += 1
            else:
                i += 1

        # 自动代码块标记
        auto_code_flags = [False] * len(lines)

        # 状态机
        inside_auto = False
        i = 0

        while i < n:
            if in_code_flags[i]:
                inside_auto = False
                i += 1
                continue

            if ocr_flags[i]:
                inside_auto = False
                i += 1
                continue

            raw_line = lines[i]
            stripped = raw_line.lstrip()

            if not inside_auto:
                # ========== 优先排除：以中文开头 ==========
                # 以中文开头（连续2个以上中文字符），直接不进入代码块
                if re.match(r"^[\u4e00-\u9fff]{2,}", stripped):
                    i += 1
                    continue

                is_code_like = MarkdownTextCleaner._is_line_code_like(stripped)
                is_md_syntax = MarkdownTextCleaner._is_markdown_syntax(stripped)

                # 新增：检查中文占比，如果太高则不进入代码块
                total_len = len(stripped)
                chinese_count = len(re.findall(r"[\u4e00-\u9fff]", stripped))
                chinese_ratio = chinese_count / total_len if total_len > 0 else 0

                # 中文占比超过 40% 且无代码特征，不进入代码块
                if chinese_ratio > 0.4:
                    # 注意：单个 # 在这里不是代码特征（因为是一级标题）
                    code_markers = r"[\(\)\{\}\"';=<>\[\]|&]"
                    if not re.search(code_markers, stripped):
                        is_code_like = False

                if is_code_like and not is_md_syntax:
                    inside_auto = True
                    auto_code_flags[i] = True
                i += 1
            else:
                if cls._is_code_continuation(lines, i, auto_code_flags):
                    auto_code_flags[i] = True
                    i += 1
                else:
                    inside_auto = False
                    continue

        # 重建文本和标记数组
        new_lines = []
        new_code_flags = []
        i = 0
        while i < n:
            if in_code_flags[i]:
                # 原有代码块：恢复转义字符
                restored_line = cls._unescape_html_entities(lines[i])
                new_lines.append(restored_line)
                new_code_flags.append(True)
                i += 1
                continue

            if ocr_flags[i]:
                new_lines.append(lines[i])
                new_code_flags.append(False)
                i += 1
                continue

            if auto_code_flags[i]:
                new_lines.append("```")
                new_code_flags.append(False)

                while i < n and auto_code_flags[i]:
                    # 自动识别的代码块：恢复转义字符
                    restored_line = cls._unescape_html_entities(lines[i])
                    new_lines.append(restored_line)
                    new_code_flags.append(True)
                    i += 1

                new_lines.append("```")
                new_code_flags.append(False)
            else:
                # 普通文本：不恢复转义字符（保持原样）
                new_lines.append(lines[i])
                new_code_flags.append(False)
                i += 1

        context["lines"] = new_lines
        context["in_code_block"] = new_code_flags

    @staticmethod
    def _has_bare_chinese(text: str) -> bool:
        """
        检测文本中是否有不在引号或注释内的中文。
        返回 True 表示有裸中文（应该排除/退出）。
        返回 False 表示所有中文都在引号或注释内（可能是代码）。
        """
        if not text:
            return False

        i = 0
        n = len(text)

        in_string = False
        string_char = None
        in_comment = False
        in_block_comment = False

        while i < n:
            ch = text[i]

            # 处理转义字符（字符串内）
            if in_string and ch == "\\" and i + 1 < n:
                i += 2
                continue

            # 字符串开始/结束
            if not in_comment and not in_block_comment and ch in ('"', "'"):
                if not in_string:
                    in_string = True
                    string_char = ch
                elif ch == string_char:
                    in_string = False
                    string_char = None
                i += 1
                continue

            # 块注释开始 /*
            if not in_string and not in_comment and not in_block_comment:
                if ch == "/" and i + 1 < n and text[i + 1] == "*":
                    in_block_comment = True
                    i += 2
                    continue

            # 块注释结束 */
            if in_block_comment:
                if ch == "*" and i + 1 < n and text[i + 1] == "/":
                    in_block_comment = False
                    i += 2
                    continue
                i += 1
                continue

            # 行注释 // 或 #
            if not in_string and not in_comment and not in_block_comment:
                if ch == "#" or (ch == "/" and i + 1 < n and text[i + 1] == "/"):
                    in_comment = True
                    i += 2 if ch == "/" else 1
                    continue

            # 在注释内，跳过整行剩余部分
            if in_comment:
                i += 1
                continue

            # 检查中文（不在字符串、不在注释内）
            if not in_string and not in_comment and not in_block_comment:
                if "\u4e00" <= ch <= "\u9fff":
                    return True

            i += 1

        return False

    @staticmethod
    def _has_paired_markdown_marker(text: str) -> bool:
        """
        检测文本中是否包含成对出现的 Markdown 标记（** 或 ==）。
        要求标记紧挨内容（标记后紧跟非空格，结束标记前也是非空格）。
        返回 True 表示找到成对标记（应该排除/退出）。
        """
        if not text:
            return False

        for marker in ["**", "=="]:
            first = text.find(marker)
            if first == -1:
                continue

            after_first = first + len(marker)
            if after_first >= len(text) or text[after_first] == " ":
                continue

            second = text.find(marker, after_first)
            if second == -1:
                continue

            if second - 1 < 0 or text[second - 1] == " ":
                continue

            return True

        return False

    @staticmethod
    def _unescape_html_entities(text: str) -> str:
        """
        将常见的 HTML/XML 转义字符恢复为原始字符。
        用于代码块内部内容的还原。
        """
        if not text:
            return text

        replacements = {
            "&lt;": "<",
            "&gt;": ">",
            "&amp;": "&",
            "&quot;": '"',
            "&#39;": "'",
            "&apos;": "'",
        }

        for entity, char in replacements.items():
            text = text.replace(entity, char)

        return text

    @staticmethod
    def _is_line_code_like(line: str) -> bool:
        if not line:
            return False

        stripped = line.lstrip()

        if not stripped:
            return False

        # ========== 最高优先级：成对 Markdown 标记检测 ==========
        # 检测成对出现的 ** 或 ==，且要求紧挨内容（无空格）
        if MarkdownTextCleaner._has_paired_markdown_marker(stripped):
            return False

        # ========== 优先排除：以中文开头 ==========
        # 以中文开头（连续2个以上中文字符），直接不是代码
        if re.match(r"^[\u4e00-\u9fff]{2,}", stripped):
            return False

        # ========== 裸中文检测 ==========
        if MarkdownTextCleaner._has_bare_chinese(stripped):
            return False

        # ========== 排除 Markdown 原生语法 ==========

        # 1. 标题：以 # 开头（后面有空格）
        if re.match(r"^#{1,6}\s+", stripped):
            return False

        # 2. 无序列表：-, *, + 开头
        if re.match(r"^[-*+]\s+", stripped):
            return False

        # 3. 有序列表：数字 + . 或 ) 开头
        if re.match(r"^\d+[.)]\s+", stripped):
            return False

        # 4. 表格行：包含 | 且数量合理
        if stripped.count("|") >= 2:
            # 排除表格分隔行（|---|）
            if re.match(r"^\s*\|?[\s\-:]+\|", stripped):
                return False
            # 普通表格行
            return False

        # 5. 数学公式块：$$ 开头或结尾
        if stripped.startswith("$$") or stripped.endswith("$$"):
            return False

        # 6. 行内数学公式：$...$ 模式（简单判断）
        if stripped.count("$") >= 2 and not stripped.startswith("```"):
            return False

        # 7. 引用：> 开头
        if stripped.startswith(">"):
            return False

        # 8. 水平分割线：---, ***, ___ 等
        if re.match(r"^[-*_]{3,}\s*$", stripped):
            return False

        # 9. HTML 注释：<!-- -->
        if stripped.startswith("<!--") and stripped.endswith("-->"):
            return False

        # 10. 任务列表：- [ ] 或 - [x]
        if re.match(r"^[-*+]\s+\[[ x]\]\s+", stripped):
            return False

        # 11. Markdown 图片：![alt](url)
        if re.match(r"^!\[.*\]\(.*\)", stripped):
            return False

        # 12. Markdown 链接：[text](url)
        # 但要排除命令提示符如 [root@localhost ~]#
        if re.match(r"^\[[^\]]+\]\([^\)]+\)", stripped):
            return False

        # ========== 代码特征判断 ==========
        # 代码关键字
        code_keywords = [
            r"\bdef\s+\w+\s*\(",
            r"\bclass\s+\w+",
            r"\bfunction\s+\w+\s*\(",
            r"\bif\s*\(",
            r"\bfor\s*\(",
            r"\bwhile\s*\(",
            r"\bimport\s+",
            r"\bfrom\s+\w+\s+import",
            r"\breturn\s+",
            r"\bexport\s+",
            r"\bsudo\s+",
            r"\bdocker\s+",
            r"\bgit\s+",
            r"\bapt\s+",
            r"\byum\s+",
            r"\bnpm\s+",
            r"\byarn\s+",
            r"\bpip\s+",
            r"\bconda\s+",
            r"\bcurl\s+",
            r"\bwget\s+",
            r"\bssh\s+",
            r"\bscp\s+",
            r"\brsync\s+",
        ]
        for kw in code_keywords:
            if re.search(kw, stripped):
                return True

        # SQL 关键字
        sql_keywords = [
            r"\bSELECT\s+",
            r"\bINSERT\s+",
            r"\bUPDATE\s+",
            r"\bDELETE\s+",
            r"\bFROM\s+",
            r"\bWHERE\s+",
            r"\bJOIN\s+",
            r"\bORDER\s+BY",
            r"\bGROUP\s+BY",
            r"\bHAVING\s+",
            r"\bLIMIT\s+",
            r"\bUNION\s+",
            r"\bINTO\s+",
            r"\bVALUES\s*\(",
            r"\bSET\s+\w+\s*=",
        ]
        for kw in sql_keywords:
            if re.search(kw, stripped, re.IGNORECASE):
                return True

        # SQL 占位符 ?
        if re.search(r"\=\s*\?\s*$", stripped):
            return True

        # 包含 => 或 -> 的代码（如 OraQuery->Params）
        if re.search(r"[-=]>", stripped):
            return True

        # XML/HTML 转义字符
        if re.search(r"&(lt|gt|amp|quot|#39|#x?\w+);", stripped):
            return True

        # 配置文件特征
        if re.search(r"^\w+\s*=\s*.+", stripped):
            if not re.search(r"[\u4e00-\u9fff]", stripped):
                return True

        # key: value 形式
        if re.search(r"^\w+\s*:\s*\S+", stripped):
            words = stripped.split()
            if len(words) <= 5:
                if not re.search(r"[\u4e00-\u9fff]", stripped):
                    return True

        # YAML 列表项
        if re.match(r"^-\s+\w+:", stripped):
            return True
        if re.match(r"^\d+\.\s*\w+:", stripped):
            return True

        # JSON/JS 对象
        if re.search(r"^\s*[{\[]", stripped) and re.search(r"[}\]]\s*$", stripped):
            return True
        if stripped.count("{") + stripped.count("}") >= 2:
            chinese_count = len(re.findall(r"[\u4e00-\u9fff]", stripped))
            if chinese_count < len(stripped) * 0.3:
                return True

        # XML/HTML 标签
        if re.search(r"<[/]?\w+[^>]*>", stripped):
            return True

        # 函数调用（允许参数中包含中文）
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*\(.*\)\s*;?\s*$", stripped):
            return True

        # 函数定义
        if re.search(
            r"^\s*(void|int|char|float|double|long|static|const|virtual|class|struct)\s+\w+\s*\([^)]*\)\s*\{?\s*$",
            stripped,
            re.IGNORECASE,
        ):
            return True

        # Shell 提示符
        # 情况1: 直接以 $, #, > 开头
        if re.search(r"^[\$\#>]\s+", stripped):
            return True

        # 情况2: [user@host path]# 或 [root@host bin]# 格式
        if re.search(r"^\[.*\]\s*[#$>]\s+", stripped):
            return True

        # 情况3: user@host:~$ 格式
        if re.search(r"^[\w\-\.]+@[\w\-\.]+:.*[$#>]\s+", stripped):
            return True

        # 情况4: 管道符
        if re.search(r"^\$?\s*\w+\s*\|", stripped):
            return True

        # 分号结尾
        # 修改后的分号规则
        if re.search(r";\s*$", stripped) and not stripped.endswith(";;"):
            # 必须有强代码特征（赋值/括号/关键字）才认为是代码
            if re.search(r"[=\(\)]|\b(if|for|while|return|def|class)\b", stripped):
                if not re.search(r"[\u4e00-\u9fff]", stripped):
                    return True

        # URL 带参数
        if re.search(r"https?://[^\s]+\?[^\s]+=[^\s]+", stripped):
            return True

        # 缩进代码
        if stripped.startswith(("    ", "\t", "  ")):
            chinese_count = len(re.findall(r"[\u4e00-\u9fff]", stripped))
            if chinese_count < len(stripped) * 0.3:
                if re.search(r"[{}[\]();=<>|&]", stripped):
                    return True

        # 文件路径特征
        if re.search(r"^[/\\]?(?:[\w\-]+[/\\])+[\w\-]+\.\w+", stripped):
            return True

        # IP 地址
        if re.search(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", stripped):
            return True

        # 环境变量
        if re.search(r"^[A-Z_][A-Z0-9_]*=", stripped):
            return True

        # 协议前缀（sip:, tel: 等）
        if re.match(r"^(sip|tel|mailto|ftp)://?", stripped, re.IGNORECASE):
            return True
        if re.match(r"^[\w\-\.]+@[\w\-\.]+", stripped):  # email
            return True

        return False

    @staticmethod
    def _is_code_continuation(
        lines: List[str], idx: int, auto_flags: List[bool]
    ) -> bool:
        """
        判断当前行是否应延续 auto_code 模式。
        返回 True：延续（留在代码块内）
        返回 False：退出代码块
        """
        if idx >= len(lines):
            return False

        line = lines[idx]
        stripped = line.lstrip()

        # 空行：在 auto_code 内部延续（保留空行）
        if not stripped:
            return True

        # ========== 强制退出条件（明确的非代码内容）==========
        # 遇到成对 ** 或 == 时，退出代码块
        if MarkdownTextCleaner._has_paired_markdown_marker(stripped):
            return False

        # 1. 多个 # 开头（##、### 等）→ 一定是标题，退出
        if re.match(r"^#{2,6}\s+", stripped):
            return False

        # 2. 无序列表：-, *, + 开头
        if re.match(r"^[-*+]\s+", stripped):
            return False

        # 3. 有序列表：数字 + . 或 ) 开头
        if re.match(r"^\d+[.)]\s+", stripped):
            return False

        # 4. 表格行：以 | 开头和结尾
        if stripped.startswith("|") and stripped.endswith("|"):
            return False

        # 5. 代码块标记（```
        if stripped.startswith("```"):
            return False

        # 6. Markdown 图片
        if re.match(r"^!\[.*\]\(.*\)", stripped):
            return False

        # 7. Markdown 链接
        if re.match(r"^\[[^\]]+\]\([^\)]+\)", stripped):
            return False

        # ========== 中文开头检查（优先于代码特征）==========
        # 以中文开头（连续2个以上中文字符），直接退出
        if re.match(r"^[\u4e00-\u9fff]{2,}", stripped):
            return False

        # ========== 裸中文检测 ==========
        if MarkdownTextCleaner._has_bare_chinese(stripped):
            return False

        # ========== 代码特征检查（有特征就延续）==========
        code_patterns = [
            r"[\(\)]",  # 括号 ()
            r"[\{\}]",  # 花括号 {}
            r"[\"]",  # 双引号 "
            r"[']",  # 单引号 '
            r";",  # 分号
            r"=",  # 等号
            r"<",  # 小于号
            r">",  # 大于号
            r"\[",  # 方括号 [
            r"\]",  # 方括号 ]
            r"^\s*#\s+",  # 单 # 注释（代码特征）
            r"^\s*//",  # C++ 注释
            r"^\s*/\*",  # C 注释开始
        ]

        has_code_feature = any(
            re.search(pattern, stripped) for pattern in code_patterns
        )

        if has_code_feature:
            return True

        # 如果上一行是 SQL（包含 SELECT/INSERT/UPDATE 等），当前行延续
        if idx > 0 and auto_flags[idx - 1]:
            prev_upper = lines[idx - 1].upper()
            if re.search(r"\b(SELECT|INSERT|UPDATE|DELETE|FROM|WHERE)\b", prev_upper):
                return True

        # ========== 默认 ==========
        return False

    @staticmethod
    def _process_full_text(text: str) -> str:
        # Normalize line endings
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        # Fix escaped underscores
        text = text.replace(r"\_", "_")
        # Collapse excessive spaces
        text = re.sub(r" {3,}", "  ", text)
        # Collapse excessive horizontal rules
        text = re.sub(r"-{3,}", "--", text)
        return text

    @staticmethod
    def _finalize_full_text(text: str) -> str:
        # Collapse excessive blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip() + "\n"

    @classmethod
    def _create_line_context(cls, text: str) -> dict:
        """
        Create reusable line-processing context.

        This avoids repeated:
            lines = text.split("\n")
        """
        lines = text.split("\n")
        code_block_flags = cls._build_code_block_flags(lines)
        return {
            "lines": lines,
            "in_code_block": code_block_flags,
        }

    @staticmethod
    def _build_code_block_flags(lines: List[str]) -> List[bool]:
        """
        Precompute whether each line is inside a fenced code block.

        Markdown rules:
        - opening fence:
            - up to 3 leading spaces
            - fence is ``` or ~~~ with length >= 3

        - closing fence:
            - same fence character
            - length >= opening fence length
        """
        flags = [False] * len(lines)
        in_code_block = False
        fence_char = ""
        fence_len = 0
        for idx, line in enumerate(lines):
            match = CODE_FENCE_RE.match(line)

            # Opening fence
            if not in_code_block:
                if match:
                    in_code_block = True

                    opening_fence = match.group(1)

                    fence_char = opening_fence[0]
                    fence_len = len(opening_fence)

                    flags[idx] = False
                    continue

                flags[idx] = False
                continue

            # Inside code block
            flags[idx] = True

            if not match:
                continue

            closing_fence = match.group(1)

            # Fence type must match
            if closing_fence[0] != fence_char:
                continue

            # Closing fence length must be >= opening
            if len(closing_fence) < fence_len:
                continue

            in_code_block = False

        return flags

    @classmethod
    def _process_line_trailing_spaces(cls, context: dict) -> None:
        """
        Remove trailing spaces from all lines.
        """
        context["lines"] = [line.rstrip() for line in context["lines"]]

    @classmethod
    def _process_list_spacing(cls, context: dict) -> None:
        """
        Ensure blank line before markdown lists.
        """
        lines = context["lines"]
        code_flags = context["in_code_block"]
        new_lines: List[str] = []
        new_code_flags: List[bool] = []
        for idx, line in enumerate(lines):
            if code_flags[idx]:
                new_lines.append(line)
                new_code_flags.append(code_flags[idx])
                continue

            if not LIST_RE.match(line):
                new_lines.append(line)
                new_code_flags.append(code_flags[idx])
                continue

            cls._append_list_line(new_lines, new_code_flags, line)

        context["lines"] = new_lines
        context["in_code_block"] = new_code_flags

    # -------------------------------------------------------------------------
    # List helpers
    # -------------------------------------------------------------------------
    @staticmethod
    def _append_list_line(
        new_lines: List[str],
        new_code_flags: List[bool],
        current_line: str,
    ) -> None:
        """
        Add blank line before list item if needed.
        """
        if not new_lines:
            new_lines.append(current_line)
            new_code_flags.append(False)
            return

        prev_line = new_lines[-1]

        # Already separated
        if not prev_line.strip():
            new_lines.append(current_line)
            new_code_flags.append(False)
            return

        # Previous line is not a list item
        if not LIST_RE.match(prev_line):
            new_lines.append("")
            new_code_flags.append(False)

        new_lines.append(current_line)
        new_code_flags.append(False)

    @classmethod
    def _has_level_one_heading(
        cls,
        context: dict,
    ) -> bool:
        """
        Check whether markdown contains a level-1 heading.
        """
        lines = context["lines"]
        code_flags = context["in_code_block"]
        for idx, line in enumerate(lines):
            if code_flags[idx]:
                continue

            if re.match(r"^# [^#]", line):
                return True

        return False

    @staticmethod
    def _prepend_level_one_heading(text: str, filename: str) -> str:
        heading_text = Path(filename).stem
        return f"# {heading_text}\n\n{text.lstrip()}"

    # -------------------------------------------------------------------------
    # Batch processing
    # -------------------------------------------------------------------------
    @staticmethod
    def clean_markdown_files(
        root_dir: str, log_func=print, debug: bool = False
    ) -> None:
        root = Path(root_dir)
        md_files = list(root.rglob("*.md"))
        changed_count = 0

        for md_file in md_files:
            try:
                original = md_file.read_text(encoding="utf-8")
                cleaned = MarkdownTextCleaner.clean(original, filename=md_file.name)

                if cleaned == original:
                    continue

                md_file.write_text(cleaned, encoding="utf-8")
                changed_count += 1

                if debug:
                    log_func(f"[FIX+] cleaned: {md_file}")

            except Exception as e:
                log_func(f"[FIX+] clean failed: {md_file} : {e}")

        log_func(
            f"[FIX+] clean finished: {changed_count}/{len(md_files)} files changed"
        )

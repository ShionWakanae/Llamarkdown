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

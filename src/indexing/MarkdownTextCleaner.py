import re
from pathlib import Path

LIST_RE = re.compile(r"^(\s*(?:\*|-|\+|\d+[.)])\s+)(.*)")


class MarkdownTextCleaner:
    """
    Unified markdown text cleaner.

    Responsibilities:
    - normalize line endings
    - fix escaped underscore
    - collapse excessive spaces
    - collapse excessive horizontal rules
    """

    @classmethod
    def clean(cls, text: str) -> str:
        text = cls.normalize_md(text)
        text = cls.normalize_list_spacing(text)
        return text

    @classmethod
    def normalize_list_spacing(cls, text: str) -> str:
        lines = text.splitlines()

        new_lines = []

        in_code_block = False

        for line in lines:
            stripped = line.strip()

            #
            # fenced code block toggle
            #
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_code_block = not in_code_block
                new_lines.append(line)
                continue

            #
            # markdown list item
            #
            m = LIST_RE.match(line)

            if not in_code_block and m:
                #
                # previous line exists and is not blank
                #
                if new_lines and new_lines[-1].strip():
                    #
                    # previous line is not list item
                    #
                    prev_is_list = LIST_RE.match(new_lines[-1])

                    if not prev_is_list:
                        new_lines.append("")

            new_lines.append(line)

        return "\n".join(new_lines)

    @staticmethod
    def normalize_md(text: str) -> str:
        if not text:
            return ""

        #
        # normalize line endings
        #
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        #
        # fix escaped underscore
        #
        text = text.replace(
            r"\_",
            "_",
        )

        # collapse spaces and ---
        text = re.sub(r" {3,}", "  ", text)
        text = re.sub(r"-{3,}", "--", text)

        #
        # remove trailing spaces
        #
        text = "\n".join(line.rstrip() for line in text.split("\n"))

        #
        # collapse excessive blank lines
        #
        text = re.sub(
            r"\n{3,}",
            "\n\n",
            text,
        )

        return text

    @staticmethod
    def clean_markdown_files(
        root_dir,
        log_func=print,
        debug: bool = False,
    ):
        root = Path(root_dir)
        md_files = list(root.rglob("*.md"))
        changed_count = 0

        for md_file in md_files:
            try:
                original = md_file.read_text(
                    encoding="utf-8",
                )

                cleaned = MarkdownTextCleaner.clean(original)

                #
                # only write if changed
                #
                if cleaned != original:
                    md_file.write_text(
                        cleaned,
                        encoding="utf-8",
                    )

                    changed_count += 1
                    if debug:
                        log_func(f"[FIX+] cleaned: {md_file}")

            except Exception as e:
                log_func(f"[FIX+] clean failed: {md_file} : {e}")

        log_func(
            f"[FIX+] clean finished: {changed_count}/{len(md_files)} files changed"
        )

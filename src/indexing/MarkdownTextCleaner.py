import re
from pathlib import Path


class MarkdownTextCleaner:
    """
    Unified markdown text cleaner.

    Responsibilities:
    - normalize line endings
    - fix escaped underscore
    - collapse excessive spaces
    - collapse excessive horizontal rules
    """

    @staticmethod
    def clean(text: str) -> str:
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
                        log_func(f"Markdown cleaned: {md_file}")

            except Exception as e:
                log_func(f"Markdown clean failed: {md_file} : {e}")

        log_func(
            f"Markdown clean finished: {changed_count}/{len(md_files)} files changed"
        )

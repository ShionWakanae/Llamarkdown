import re

from pathlib import Path


class ImageOCREnhancer:
    IMAGE_RE = re.compile(r"!\[(.*?)\]\((.*?)\)")

    OCR_START_RE = re.compile(r"^\*\[Image OCR\]\*\s*$")

    OCR_END_RE = re.compile(r"^\*\[End OCR\]\*\s*$")

    PROMPT = """
请分析这张图片，用于企业知识库RAG系统中的图片摘要。

要求：
- 使用简体中文
- 简洁准确
- 不要幻觉
- 不要大量OCR
- 不要逐字转录
- 仅保留关键结构、组件、关系、标签
- 适合语义检索
- 控制在80字以内

直接输出摘要正文。
""".strip()

    def __init__(
        self,
        vision_client,
        debug: bool = False,
    ):
        self.vision_client = vision_client
        self.debug = debug

    #
    # public
    #

    def process_directory(
        self,
        root_dir: str,
    ):
        root = Path(root_dir)

        md_files = list(root.rglob("*.md"))

        for md_file in md_files:
            try:
                self.process_markdown_file(md_file)

            except Exception as e:
                print(f"[ImageOCREnhancer] ERROR: {md_file} -> {e}")

    def process_markdown_file(
        self,
        md_path: Path,
    ):

        text = md_path.read_text(encoding="utf-8")

        lines = text.splitlines()

        new_lines = []

        i = 0

        modified = False

        while i < len(lines):
            line = lines[i]

            image_match = self.IMAGE_RE.match(line.strip())

            #
            # normal line
            #
            if not image_match:
                new_lines.append(line)
                i += 1
                continue

            #
            # image line
            #
            new_lines.append(line)

            image_rel_path = image_match.group(2)

            #
            # check OCR block
            #
            has_ocr = False

            j = i + 1

            while j < len(lines):
                candidate = lines[j].strip()

                #
                # skip blank
                #
                if not candidate:
                    j += 1
                    continue

                #
                # OCR block exists
                #
                if self.OCR_START_RE.match(candidate):
                    has_ocr = True

                break

            #
            # already processed
            #
            if has_ocr:
                i += 1
                continue

            #
            # resolve image path
            #
            image_path = (md_path.parent / image_rel_path).resolve()

            if not image_path.exists():
                print(f"[ImageOCREnhancer] missing image: {image_path}")

                i += 1
                continue

            #
            # analyze
            #
            if self.debug:
                print(f"[ImageOCREnhancer] analyzing: {image_path}")

            caption = self.vision_client.analyze_image(
                image_path=image_path,
                prompt=self.PROMPT,
            )

            if not caption:
                caption = "该图包含技术相关内容。"

            #
            # inject OCR block
            #
            new_lines.append("*[Image OCR]*")

            new_lines.append(caption.strip())

            new_lines.append("*[End OCR]*")

            modified = True

            i += 1

        #
        # write back
        #
        if modified:
            new_text = "\n".join(new_lines)

            md_path.write_text(
                new_text,
                encoding="utf-8",
            )

            print(f"[ImageOCREnhancer] updated: {md_path}")

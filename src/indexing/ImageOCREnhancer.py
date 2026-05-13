import hashlib
import re

from pathlib import Path
from PIL import Image
from PIL import UnidentifiedImageError
from tqdm import tqdm


class ImageOCREnhancer:
    IMAGE_RE = re.compile(r"!\[(.*?)\]\((.*?)\)")
    OCR_START_LINE_RE = re.compile(r"^\*\[Image OCR\]\*\s*$")
    OCR_END_LINE_RE = re.compile(r"^\*\[End OCR\]\*\s*$")
    OCR_ID_RE = re.compile(r"^id:\s*(.+?)\s*$")
    PROMPT = """
请分析这张图片，用于企业知识库RAG系统中的图片摘要。

要求：
- 使用简体中文
- 简洁准确
- 不要幻觉
- 不要大量OCR
- 不要逐字转录
- 不要推测结论
- 仅保留关键结构、组件、关系、标签
- 适合语义检索
- 控制在80字以内

直接输出摘要正文。
""".strip()

    def __init__(
        self,
        vision_client,
        vision_model: str,
        debug: bool = False,
    ):
        self.vision_client = vision_client
        self.vision_model = vision_model
        self.debug = debug

        # runtime memory cache
        self.caption_cache = {}

    def _normalize_image_filename(
        self,
        md_path: Path,
        image_rel_path: str,
        rename_counter: int,
        rename_map: dict,
    ):
        """
        Rename ugly/long image filenames into:

            img_000001.png

        Returns:
            (
                new_image_rel_path,
                new_image_abs_path,
                new_rename_counter,
            )
        """

        #
        # resolve original path
        #
        original_path = (md_path.parent / image_rel_path).resolve()

        #
        # already renamed in current markdown
        #
        if str(original_path) in rename_map:
            cached_rel_path = rename_map[str(original_path)]

            return (
                cached_rel_path,
                (md_path.parent / cached_rel_path).resolve(),
                rename_counter,
            )

        #
        # filename only
        #
        filename = original_path.stem

        #
        # keep normal filenames
        #
        # examples:
        #   chart
        #   image_01
        #   kafka_arch
        #
        if len(filename) <= 20 and re.match(
            r"^[a-zA-Z0-9_\-]+$",
            filename,
        ):
            return (
                image_rel_path,
                original_path,
                rename_counter,
            )

        #
        # generate new filename
        #
        new_filename = f"img_{rename_counter:06d}"

        #
        # preserve suffix
        #
        new_name = new_filename + original_path.suffix.lower()

        #
        # new relative path
        #
        new_rel_path = str(Path(image_rel_path).with_name(new_name)).replace("\\", "/")

        #
        # new absolute path
        #
        new_path = (md_path.parent / new_rel_path).resolve()

        #
        # avoid accidental overwrite
        #
        while new_path.exists():
            rename_counter += 1

            new_filename = f"img_{rename_counter:06d}"

            new_name = new_filename + original_path.suffix.lower()

            new_rel_path = str(Path(image_rel_path).with_name(new_name)).replace(
                "\\", "/"
            )

            new_path = (md_path.parent / new_rel_path).resolve()

        #
        # rename physical file
        #
        original_path.rename(new_path)

        #
        # cache mapping
        #
        rename_map[str(original_path)] = new_rel_path

        #
        # logging
        #
        if self.debug:
            print(
                "[ImageOCREnhancer] "
                f"renamed image:\n"
                f"  from: {original_path.name}\n"
                f"  to:   {new_name}"
            )

        rename_counter += 1

        return (
            new_rel_path,
            new_path,
            rename_counter,
        )

    def process_directory(
        self,
        root_dir: str,
    ):
        root = Path(root_dir)
        md_files = list(root.rglob("*.md"))
        for md_file in md_files:
            if self.debug:
                print(f"[ImageOCREnhancer] processing: {md_file}")
            try:
                self.process_markdown_file(md_file)

            except Exception as e:
                print(f"\n[ImageOCREnhancer] ERROR: {md_file} -> {e}")
        print()

    def process_markdown_file(
        self,
        md_path: Path,
    ):
        rename_counter = 1
        rename_map = {}
        text = md_path.read_text(encoding="utf-8")
        lines = text.splitlines()
        new_lines = []
        modified = False

        i = 0
        while i < len(lines):
            line = lines[i]
            image_match = self.IMAGE_RE.match(line.strip())
            # normal line
            if not image_match:
                new_lines.append(line)
                i += 1
                continue

            # image line
            image_rel_path = image_match.group(2)
            image_path = (md_path.parent / image_rel_path).resolve()

            if not self.debug:
                print(".", end="", flush=True)
            # image file is missing
            if not image_path.exists():
                print(f"[ImageOCREnhancer] missing image: {image_path}")
                i += 1
                continue

            # normalize image filename
            (
                image_rel_path,
                image_path,
                rename_counter,
            ) = self._normalize_image_filename(
                md_path=md_path,
                image_rel_path=image_rel_path,
                rename_counter=rename_counter,
                rename_map=rename_map,
            )

            new_image_line = f"![{image_match.group(1)}]({image_rel_path})"
            new_lines.append(new_image_line)
            if new_image_line != line:
                modified = True

            #
            # image meaningful?
            #
            if not self._is_meaningful_image(image_path):
                if self.debug:
                    print(f"[ImageOCREnhancer] skip meaningless image: {image_path}")

                i += 1
                continue

            #
            # current image id
            #
            image_id = self._compute_image_id(image_path)

            #
            # parse existing OCR block
            #
            parsed = self._parse_existing_ocr_block(
                lines,
                i + 1,
            )
            if self.debug:
                print(f"[ImageOCREnhancer] parsed: {parsed}")

            # existing OCR exists
            if parsed:
                (
                    block_start,
                    block_end,
                    metadata,
                    body_lines,
                ) = parsed

                existing_id = metadata.get("id")
                if self.debug:
                    print(f"[ImageOCREnhancer] existing id: {existing_id}")
                #
                # case 1:
                # old OCR format
                #
                if not existing_id:
                    if self.debug:
                        print("[ImageOCREnhancer] upgrade old OCR block")

                    #
                    # preserve old caption
                    #
                    old_caption = "\n".join(body_lines).strip()

                    #
                    # inject upgraded block
                    #
                    new_lines.extend(
                        self._build_ocr_block(
                            image_id=image_id,
                            caption=old_caption,
                        )
                    )

                    modified = True

                    i = block_end + 1

                    continue

                #
                # case 2:
                # same image
                #
                if existing_id == image_id:
                    #
                    # keep original block
                    #
                    for k in range(
                        i + 1,
                        block_end + 1,
                    ):
                        new_lines.append(lines[k])

                    i = block_end + 1

                    continue

                #
                # case 3:
                # image changed
                #
                if self.debug:
                    print("[ImageOCREnhancer] image changed")

                #
                # skip old block
                #
                i = block_end + 1

            else:
                i += 1

            #
            # get caption
            #
            caption = self._get_or_create_caption(
                image_id=image_id,
                image_path=image_path,
            )

            #
            # inject OCR block
            #
            new_lines.extend(
                self._build_ocr_block(
                    image_id=image_id,
                    caption=caption,
                )
            )

            modified = True

        #
        # write back
        #
        if modified:
            new_text = "\n".join(new_lines)

            md_path.write_text(
                new_text,
                encoding="utf-8",
            )
            if self.debug:
                print(f"[ImageOCREnhancer] updated: {md_path}")

    #
    # OCR block
    #

    def _build_ocr_block(
        self,
        image_id: str,
        caption: str,
    ):

        return [
            "*[Image OCR]*",
            f"id: {image_id}",
            f"model: {self.vision_model}",
            "status: ok",
            "*",
            "",
            caption.strip(),
            "",
            "*[End OCR]*",
        ]

    def _parse_existing_ocr_block(
        self,
        lines,
        start_index,
    ):

        i = start_index

        #
        # skip blank
        #
        while i < len(lines):
            if lines[i].strip():
                break

            i += 1

        if i >= len(lines):
            return None

        #
        # not OCR
        #
        if not self.OCR_START_LINE_RE.match(lines[i].strip()):
            return None

        block_start = i

        metadata = {}

        body_lines = []

        i += 1

        #
        # parse metadata
        #
        while i < len(lines):
            current = lines[i].rstrip()

            #
            # metadata end
            #
            if current.strip() == "*":
                i += 1
                break
            #
            # old format:
            # body starts directly
            #
            if ":" not in current:
                break

            id_match = self.OCR_ID_RE.match(current.strip())

            if id_match:
                metadata["id"] = id_match.group(1)

            i += 1

        #
        # parse body
        #
        while i < len(lines):
            current = lines[i]

            if self.OCR_END_LINE_RE.match(current.strip()):
                block_end = i

                return (
                    block_start,
                    block_end,
                    metadata,
                    body_lines,
                )

            body_lines.append(current)

            i += 1

        return None

    #
    # caption
    #

    def _get_or_create_caption(
        self,
        image_id: str,
        image_path: Path,
    ):

        #
        # memory cache
        #
        if image_id in self.caption_cache:
            if self.debug:
                print("[ImageOCREnhancer] caption cache hit")

            return self.caption_cache[image_id]

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

        self.caption_cache[image_id] = caption

        return caption

    #
    # image
    #

    def _compute_image_id(
        self,
        image_path: Path,
    ) -> str:

        hasher = hashlib.sha256()

        with open(image_path, "rb") as f:
            hasher.update(f.read())

        #
        # short stable id
        #
        return hasher.hexdigest()[:16]

    def _is_meaningful_image(
        self,
        image_path: Path,
    ):

        try:
            with Image.open(image_path) as img:
                w, h = img.size

        except (
            UnidentifiedImageError,
            OSError,
        ):
            return False

        #
        # too small
        #
        if w < 300 or h < 180:
            return False

        #
        # extreme ratio
        #
        ratio = w / h

        if ratio > 8 or ratio < 0.12:
            return False

        return True

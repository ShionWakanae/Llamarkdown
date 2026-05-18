import shutil
import traceback
import zipfile
from pathlib import Path
from PIL import Image
from rich import print
from docling.document_converter import DocumentConverter
from docling.backend.msword_backend import MsWordDocumentBackend
from pydantic import AnyUrl
from docling_core.types.doc import ImageRefMode
from docling_core.types.doc import PictureItem
from utils.settings import settings, REF_MD_DIR, ORI_PDF_DIR
from utils.logger import logger
import subprocess

log = logger.log
ref_md_path = (Path(settings.app_doc_path) / REF_MD_DIR).resolve()
ori_pdf_path = (Path(settings.app_doc_path) / ORI_PDF_DIR).resolve()

SUPPORTED_EXTS = {".pdf", ".docx", ".xlsx", ".pptx"}

# =========================================================
# docling compatibility patches
# =========================================================
_original_get_hyperlink_target = MsWordDocumentBackend._get_hyperlink_target


def safe_get_hyperlink_target(self, hyperlink):
    """
    Handle invalid enterprise hyperlinks safely.

    Examples:
        http://ipaddr:port
        http://host:<port>
        javascript:void(0)

    Keep raw text instead of crashing.
    """

    address = getattr(
        hyperlink,
        "address",
        None,
    )
    if not address:
        return None
    try:
        return str(AnyUrl(address))

    except Exception:
        return address


MsWordDocumentBackend._get_hyperlink_target = safe_get_hyperlink_target


# =========================================================
# helpers
# =========================================================
def sanitize_text(text: str) -> str:
    """
    Remove invalid unicode/surrogate chars safely.
    """

    if not text:
        return ""

    return text.encode(
        "utf-8",
        errors="replace",
    ).decode("utf-8")


def is_valid_office_file(path: Path) -> bool:
    """
    Validate Office zip container integrity.
    docx/xlsx/pptx are zip files internally.
    """

    try:
        with zipfile.ZipFile(path, "r") as zf:
            bad = zf.testzip()

            if bad:
                return False

        return True

    except Exception:
        return False


# =========================================================
# converter
# =========================================================
class DoclingDirectoryConverter:
    def __init__(
        self,
        input_dir: str,
        save_original_pdf: bool = True,
    ):
        self.input_dir = Path(input_dir).resolve()
        self.output_dir = ref_md_path
        self.save_original_pdf = save_original_pdf
        self.converter = DocumentConverter()

    def run(self):
        files = []
        for path in self.input_dir.rglob("*"):
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTS:
                files.append(path)

        if not files:
            log("No supported files found.")
            return

        log(f"Found {len(files)} files.")
        success = 0
        failed = 0

        for file_path in files:
            try:
                self.convert_one(file_path)
                if self.save_original_pdf:
                    self.export_pdf_copy(file_path)
                success += 1

            except Exception as e:
                failed += 1
                log(f"[red]FAILED[/red]: {file_path}")
                print(e)
                print(traceback.format_exc())

        print()
        print("=" * 60)
        print(f"Success: {success}")
        print(f"Failed : {failed}")
        print("=" * 60)

    def convert_one(self, input_file: Path):
        relative_parent = input_file.parent.relative_to(self.input_dir)
        output_dir = self.output_dir / relative_parent
        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        log(f"Converting: {input_file}")

        # -------------------------------------------------
        # office zip integrity check
        # -------------------------------------------------
        if input_file.suffix.lower() in {
            ".docx",
            ".xlsx",
            ".pptx",
        }:
            if not is_valid_office_file(input_file):
                log(f"[red]Broken Office file[/red]: {input_file}")
                return

        # -------------------------------------------------
        # docling convert
        # -------------------------------------------------
        try:
            result = self.converter.convert(str(input_file))
        except Exception as e:
            log(f"[red]Convert failed[/red]: {e}")
            print(traceback.format_exc())
            return

        # -------------------------------------------------
        # export images
        # -------------------------------------------------
        self.export_images(
            result=result,
            output_dir=output_dir,
            stem=input_file.stem,
        )
        # -------------------------------------------------
        # export markdown
        # -------------------------------------------------
        output_md = output_dir / f"{input_file.stem}.md"
        try:
            markdown = result.document.export_to_markdown(
                image_mode=ImageRefMode.REFERENCED
            )

        except Exception as e:
            log(f"[yellow]Markdown export failed[/yellow]: {e}")
            print(traceback.format_exc())
            markdown = ""

        markdown = sanitize_text(markdown)
        output_md.write_text(
            markdown,
            encoding="utf-8",
        )
        log(f"[green]OK[/green]: {output_md}")

    def export_images(
        self,
        result,
        output_dir: Path,
        stem: str,
    ):
        # same style as docling cli:
        # xxx_artifacts/
        artifact_dir = output_dir / f"{stem}_artifacts"
        artifact_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        image_index = 1
        # walk doc items
        for element, _level in result.document.iterate_items():
            if isinstance(element, PictureItem) and element.image:
                try:
                    image = element.image.pil_image
                    image_name = f"img_{image_index:06d}.png"
                    image_path = artifact_dir / image_name
                    MAX_SIZE = (1536, 1536)
                    image.thumbnail(
                        MAX_SIZE,
                        Image.Resampling.LANCZOS,
                    )

                    try:
                        image = image.convert("RGB")
                        image = image.convert(
                            "P",
                            palette=Image.ADAPTIVE,
                        )
                    except Exception:
                        image = image.convert("RGB")

                    image.save(
                        image_path,
                        compress_level=9,
                        optimize=True,
                    )
                    image_index += 1
                    element.image.uri = image_path.relative_to(output_dir).as_posix()

                except Exception as e:
                    log(f"[yellow]Image export failed[/yellow]: {e}")
                    print(traceback.format_exc())

    def export_pdf_copy(
        self,
        input_file: Path,
    ):
        # relative_path = input_file.relative_to(self.input_dir)
        target_dir = ori_pdf_path
        target_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        suffix = input_file.suffix.lower()
        target = target_dir / input_file.name
        # already pdf
        if suffix == ".pdf":
            try:
                shutil.copy2(
                    input_file,
                    target,
                )
                log(f"[green]PDF copied[/green]: {target}")
            except Exception as e:
                log(f"[yellow]PDF copy failed[/yellow]: {e}")
                print(traceback.format_exc())
            return

        # office -> pdf
        if suffix in {
            ".docx",
            ".pptx",
            ".xlsx",
        }:
            try:
                subprocess.run(
                    [
                        "soffice",
                        "--headless",
                        "--convert-to",
                        "pdf",
                        "--outdir",
                        str(target_dir),
                        str(input_file),
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                log(f"[green]PDF exported[/green]: {target}")
            except Exception as e:
                log(f"[yellow]PDF export failed[/yellow]: {e}")
                print(traceback.format_exc())


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Recursive Docling API Converter")
    parser.add_argument(
        "input_dir",
        help="Input directory",
    )

    parser.add_argument(
        "--no-save-pdf",
        action="store_true",
        help="Do not preserve original pdf files",
    )

    args = parser.parse_args()
    converter = DoclingDirectoryConverter(
        input_dir=args.input_dir,
        save_original_pdf=not args.no_save_pdf,
    )

    converter.run()

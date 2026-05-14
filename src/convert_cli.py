import shutil
from PIL import Image
from pathlib import Path
import traceback
from rich import print
from docling.document_converter import DocumentConverter
from docling_core.types.doc import ImageRefMode
from docling_core.types.doc import PictureItem
from utils.settings import settings, REF_MD_DIR

ref_md_path = (Path(settings.app_doc_path) / REF_MD_DIR).resolve()

SUPPORTED_EXTS = {
    ".pdf",
    ".docx",
}


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

    def log(self, msg: str):
        print(f"[cyan][Docling][/cyan] {msg}")

    def run(self):
        files = []
        for path in self.input_dir.rglob("*"):
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTS:
                files.append(path)

        if not files:
            self.log("No supported files found.")
            return

        self.log(f"Found {len(files)} files.")
        success = 0
        failed = 0

        for file_path in files:
            try:
                self.convert_one(file_path)
                if self.save_original_pdf and file_path.suffix.lower() == ".pdf":
                    self.copy_original_pdf(file_path)
                success += 1

            except Exception as e:
                failed += 1
                self.log(f"[red]FAILED[/red]: {file_path}")
                print(e)

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

        self.log(f"Converting: {input_file}")

        # docling convert
        result = self.converter.convert(str(input_file))

        # export pictures
        self.export_images(
            result=result,
            output_dir=output_dir,
            stem=input_file.stem,
        )
        # output markdown path
        output_md = output_dir / f"{input_file.stem}.md"
        # export markdown
        markdown = result.document.export_to_markdown(
            image_mode=ImageRefMode.REFERENCED
        )

        output_md.write_text(
            markdown,
            encoding="utf-8",
        )
        self.log(f"[green]OK[/green]: {output_md}")

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
            # picture
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
                    image = image.convert(
                        "P",
                        palette=Image.ADAPTIVE,
                    )
                    image.save(
                        image_path,
                        compress_level=9,
                        optimize=True,
                    )
                    image_index += 1
                    element.image.uri = image_path.relative_to(
                        output_dir
                    ).as_posix()  # set uri manually

                except Exception as e:
                    self.log(f"[yellow]Image export failed[/yellow]: {e}")
                    print(traceback.format_exc())

    def copy_original_pdf(
        self,
        input_file: Path,
    ):
        relative_path = input_file.relative_to(self.input_dir)
        target = self.output_dir / "ori_pdf" / relative_path
        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        shutil.copy2(
            input_file,
            target,
        )


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

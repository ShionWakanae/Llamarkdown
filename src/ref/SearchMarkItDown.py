import argparse
import time
from datetime import datetime
from pathlib import Path


def format_elapsed(seconds: float) -> str:
    return f"{seconds:.3f}s"


def log(start_time: float, message: str):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    elapsed = format_elapsed(time.perf_counter() - start_time)

    print(f"[{now_str}] [{elapsed}] {message}")


def search_in_md_files(keyword: str, root_dir: str):
    start_time = time.perf_counter()

    printed_count = 0
    total_matches = 0
    total_files = 0
    total_lines = 0
    permission_error_count = 0

    root = Path(root_dir)

    if not root.exists():
        log(start_time, f"目录不存在: {root}")
        return

    log(start_time, f"开始搜索目录: {root}")

    for path in root.rglob("*.md"):
        # 防止目录名叫 xxx.md
        if not path.is_file():
            continue

        total_files += 1

        try:
            with path.open("r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, start=1):
                    total_lines += 1

                    if keyword in line:
                        total_matches += 1

                        # 只打印前5条
                        if printed_count < 5:
                            log(start_time, f"命中: {path} - 第{line_no}行")
                            printed_count += 1

        except PermissionError:
            permission_error_count += 1

        except Exception as e:
            log(start_time, f"读取失败: {path} - {e}")

    total_elapsed = time.perf_counter() - start_time

    log(start_time, "搜索完成")
    log(start_time, f"总文件数: {total_files}")
    log(start_time, f"总行数: {total_lines}")
    log(start_time, f"总匹配次数: {total_matches}")
    log(start_time, f"权限失败文件数: {permission_error_count}")
    log(start_time, f"总耗时: {format_elapsed(total_elapsed)}")


def main():
    parser = argparse.ArgumentParser(description="递归搜索目录下 .md 文件中的字符串")

    parser.add_argument("keyword", help="要搜索的字符串")

    parser.add_argument("directory", help="要搜索的目录")

    args = parser.parse_args()

    search_in_md_files(args.keyword, args.directory)


if __name__ == "__main__":
    main()

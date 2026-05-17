import os
import re
from utils.logger import logger
from utils.settings import DICT_PATH

log = logger.log


class DictEngine:
    def __init__(self, dict_dir=DICT_PATH):
        self.dict_map = {}
        self._load_dicts(dict_dir)
        log("[DICT] Ready")

    def _load_dicts(self, dict_dir):
        if not os.path.exists(dict_dir):
            return

        for fname in os.listdir(dict_dir):
            if not fname.endswith(".txt"):
                continue

            path = os.path.join(dict_dir, fname)
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    parts = line.split("\t")
                    term = parts[0].strip()
                    if not term:
                        continue

                    defs = [p.strip() for p in parts[1:] if p.strip()]
                    key = term.lower()
                    entry = {
                        "term": term,
                        "definitions": defs,
                    }

                    # 多项同名词 → list
                    self.dict_map.setdefault(key, []).append(entry)

    # def extract_terms(self, text: str) -> str:
    #     t = text.strip()

    #     lowered = t.lower()

    #     # 去掉标点（前后）
    #     t = t.strip("？?。.!，, ")

    #     # 去前缀
    #     prefix_patterns = [
    #         r"^什么是\s*",
    #         r"^啥是\s*",
    #         r"^请解释\s*",
    #         r"^请介绍\s*",
    #         r"^请说说\s*",
    #         r"^解释一下\s*",
    #         r"^解释\s*",
    #         r"^介绍一下\s*",
    #         r"^介绍\s*",
    #         r"^说说\s*",
    #         r"^what is\s+",
    #         r"^what's\s+",
    #         r"^define\s+",
    #     ]

    #     for p in prefix_patterns:
    #         if re.match(p, lowered):
    #             t = re.sub(p, "", t, flags=re.IGNORECASE)
    #             break

    #     # 去后缀
    #     suffix_patterns = [
    #         r"\s*是什么意思$",
    #         r"\s*什么意思$",
    #         r"\s*的意思$",
    #         r"\s*是什么$",
    #         r"\s*是啥意思$",
    #         r"\s*啥意思$",
    #         r"\s*是啥$",
    #         r"\s*的含义$",
    #         r"\s*含义$",
    #         r"\s*definition$",
    #         r"\s*\?$",
    #     ]

    #     for p in suffix_patterns:
    #         t = re.sub(p, "", t, flags=re.IGNORECASE)

    #     # ✅ 核心：多分隔符切词
    #     # 支持：空格 / 和 / 与 / 以及 / , / ，
    #     split_pattern = r"\s+|和|与|以及|and|or|,|，"
    #     parts = re.split(split_pattern, t)

    #     # 清洗
    #     terms = []
    #     for p in parts:
    #         p = p.strip()
    #         if not p:
    #             continue

    #         # 去掉残留标点
    #         p = p.strip("？?。.!，, ")

    #         if p:
    #             terms.append(p)

    #     return terms

    # def query(self, text: str):
    #     terms = self.extract_terms(text)

    #     results = []

    #     for term in terms:
    #         key = term.lower()
    #         entries = self.dict_map.get(key)
    #         if entries:
    #             results.extend(entries)

    #     if not results:
    #         return None

    #     return {
    #         "question_type": "DICT",
    #         "entries": results,
    #         "terms": terms,
    #     }

    def query(self, text: str):
        lowered = text.lower()
        matches = []

        # 找所有命中（substring）
        for key, entries in self.dict_map.items():
            # 英文术语：严格 token 匹配
            if re.fullmatch(r"[a-zA-Z0-9_-]+", key):
                # 允许短横线可有可无
                escaped = re.escape(key)
                # 把 \- 替换成 -?
                escaped = escaped.replace(r"\-", "-?")
                pattern = rf"(?<![a-zA-Z0-9]){escaped}(?![a-zA-Z0-9])"
                for m in re.finditer(pattern, lowered):
                    matches.append((key, m.start(), m.end(), entries))

            # 中文术语：substring
            else:
                start = lowered.find(key)
                if start != -1:
                    matches.append((key, start, start + len(key), entries))

        if not matches:
            return None

        # 按长度排序（长词优先）
        matches.sort(key=lambda x: len(x[0]), reverse=True)

        selected = []
        occupied = [False] * len(lowered)

        # 覆盖过滤（避免短词干扰）
        for key, start, end, entries in matches:
            if any(occupied[start:end]):
                continue

            selected.append((key, start, end, entries))

            for i in range(start, end):
                occupied[i] = True

        # 覆盖率判断（核心）
        covered_len = sum(end - start for _, start, end, _ in selected)
        coverage = covered_len / len(lowered)

        # 阈值可调（建议 0.25 ~ 0.4）
        if coverage < 0.5:
            return None

        # flatten
        hits = []
        for _, _, _, entries in selected:
            hits.extend(entries)

        return {
            "question_type": "DICT",
            "entries": hits,
        }

    def clean_definition(self, text: str) -> str:
        if not text:
            return ""
        text = text.replace('""', '"')
        # 去掉外层双引号（只去一层）
        if text.startswith('"') and text.endswith('"'):
            text = text[1:-1]

        # 去掉 mdx 的 entry:// 链接，只保留显示文本
        # <a href="entry://CFD">CFD</a> → CFD
        text = re.sub(r'<a\s+href="entry://[^"]+">([^<]+)</a>', r"\1", text)

        # ■ 转换为换行 + 列表
        # 避免第一行前面多一个空行
        text = text.replace("■", "\n- ")
        text = text.replace("<br>", "\n")
        text = re.sub(r"\n+", "\n", text).strip()

        return text

    def format_markdown(self, entries):
        if not entries:
            return ""

        # 按 term 分组（保持顺序）
        term_groups = {}
        term_order = []

        for entry in entries:
            term = entry["term"]
            if term not in term_groups:
                term_groups[term] = []
                term_order.append(term)

            term_groups[term].append(entry)

        parts = []

        # 遍历每个 term
        for term in term_order:
            group = term_groups[term]
            parts.append(f"## **{term}**")

            # 多释义（多个 entry）
            for idx, entry in enumerate(group, start=1):
                defs = entry.get("definitions", [])
                if len(group) > 1:
                    # 第一列作为主释义
                    main_def = defs[0] if defs else ""
                    main_def = self.clean_definition(main_def)
                    parts.append(f"#### {idx}. {main_def}")
                    rest_defs = defs[1:]
                else:
                    rest_defs = defs

                # 输出 definitions
                for d in rest_defs:
                    cleaned = self.clean_definition(d)
                    lines = cleaned.split("\n")
                    for i, line in enumerate(lines):
                        if i == 0:
                            parts.append(f"- {line}")
                        else:
                            parts.append(f"  {line}")

            parts.append("")  # term 之间空行

        return "\n".join(parts).strip()


# 单例（类似 rag engine）
dict_engine = DictEngine()

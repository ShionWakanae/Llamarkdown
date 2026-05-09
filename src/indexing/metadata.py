import yaml
import re
import copy

with open(
    "metadata_rules.yaml",
    "r",
    encoding="utf-8",
) as f:
    RULES = yaml.safe_load(f)


def match_patterns(
    text,
    patterns,
):
    return any(p.lower() in text for p in patterns)


def enrich_metadata(node):
    text = node.text.lower()
    header = node.metadata.get(
        "header_path",
        "",
    ).lower()

    meta = copy.deepcopy(node.metadata)

    #
    # defaults
    #
    # meta.setdefault(
    #     "chunk_type",
    #     "text",
    # )

    meta.setdefault(
        "has_error_code",
        False,
    )

    meta.setdefault(
        "has_sql",
        False,
    )

    meta.setdefault(
        "has_api",
        False,
    )

    meta.setdefault(
        "has_number",
        False,
    )

    #
    # derived features
    #

    meta["text_length"] = len(text)

    meta["is_too_short"] = len(text) < 100

    meta["is_large_table"] = text.count("|") > 20

    meta["has_number"] = any(c.isdigit() for c in text)

    #
    # header_rules
    #

    for rule in RULES.get(
        "header_rules",
        [],
    ):
        if match_patterns(
            header,
            rule["match"],
        ):
            meta[rule["name"]] = rule["value"]

    #
    # text_rules
    #

    for rule in RULES.get(
        "text_rules",
        [],
    ):
        matched = False

        if rule["type"] == "contains_any":
            matched = match_patterns(
                text,
                rule["patterns"],
            )

        elif rule["type"] == "regex":
            matched = any(
                re.search(
                    p,
                    text,
                )
                for p in rule["patterns"]
            )

        if matched:
            meta[rule["name"]] = rule["value"]

    #
    # chunk_type_rules
    #

    # for rule in RULES.get(
    #     "chunk_type_rules",
    #     [],
    # ):
    #     target = rule.get(
    #         "target",
    #         "text",
    #     )

    #     source = text

    #     if target == "header":
    #         source = header

    #     if match_patterns(
    #         source,
    #         rule["match"],
    #     ):
    #         meta["chunk_type"] = rule["value"]

    #         break

    return meta

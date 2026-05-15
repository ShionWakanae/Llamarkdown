import json
import re


def safe_extract_json_fields(text: str):
    # first try strict json
    try:
        return json.loads(text)
    except Exception:
        pass

    # fallback regex extract
    result = {}
    fields = [
        "question_type",
        "retrieval_query",
        "presentation_intent",
        "user_intent",
    ]

    for field in fields:
        # normal:
        # "field": "value"
        m = re.search(
            rf'"{field}"\s*:\s*"([^"]*)"',
            text,
            re.DOTALL,
        )

        if m:
            value = m.group(1).strip()

            # fix:
            # "type": "RAG"
            m2 = re.search(r'^[a-zA-Z_]+\s*":\s*"(.+)$', value)

            if m2:
                value = m2.group(1).strip()

            value = value.rstrip('"')
            result[field] = value

    return result

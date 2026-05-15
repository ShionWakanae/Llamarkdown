import re

ENGLISH_WORD_RE = re.compile(r"[A-Za-z]+")


def analyze_tokens(text: str):
    text = (text or "").strip()

    #
    # english words
    #

    english_words = ENGLISH_WORD_RE.findall(text)

    #
    # chinese chars
    #

    chinese_chars = re.findall(
        r"[\u4e00-\u9fff]",
        text,
    )

    #
    # normalize english
    #

    english_words = [w.lower() for w in english_words]

    unique_english = list(dict.fromkeys(english_words))

    return {
        "english_words": unique_english,
        "english_count": len(unique_english),
        "chinese_count": len(chinese_chars),
    }

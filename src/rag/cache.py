import sqlite3
import json
import hashlib
import time
from pathlib import Path

import numpy as np

from llama_index.embeddings.huggingface import HuggingFaceEmbedding

from utils.settings import settings


CACHE_DB_PATH = "./storage/cache/cache.db"


class AnswerCache:
    def __init__(self):
        Path("./storage/cache").mkdir(
            parents=True,
            exist_ok=True,
        )

        self.conn = sqlite3.connect(
            CACHE_DB_PATH,
            check_same_thread=False,
        )

        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS answer_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                cache_key TEXT,
                retrieval_query TEXT,
                presentation_intent TEXT,
                user_intent TEXT,

                answer TEXT,

                embedding TEXT,

                knowledge_hash TEXT,

                created_at INTEGER
            )
            """
        )

        self.conn.commit()

        self.embed_model = HuggingFaceEmbedding(
            model_name=settings.embedding_model,
            device="cpu",
            embed_batch_size=8,
        )

    #
    # build cache query
    #

    def build_cache_query(
        self,
        retrieval_query: str,
        presentation_intent: str,
        user_intent: str,
    ):
        return f"""
检索问题:
{retrieval_query}

用户意图:
{user_intent}

输出要求:
{presentation_intent}
        """.strip()

    #
    # embedding
    #

    def embed_text(self, text: str):
        emb = self.embed_model.get_text_embedding(text)
        return np.array(
            emb,
            dtype=np.float32,
        )

    #
    # cosine similarity
    #

    def cosine_similarity(
        self,
        a: np.ndarray,
        b: np.ndarray,
    ):
        denom = np.linalg.norm(a) * np.linalg.norm(b)

        if denom == 0:
            return 0.0

        return float(np.dot(a, b) / denom)

    #
    # knowledge hash
    #

    def build_knowledge_hash(self):
        base = []

        root = Path(settings.app_doc_path)

        if not root.exists():
            return "empty"

        for path in sorted(root.rglob("*")):
            if path.is_file():
                stat = path.stat()

                base.append(f"{path}:{stat.st_size}:{int(stat.st_mtime)}")

        joined = "\n".join(base)

        return hashlib.md5(joined.encode("utf-8")).hexdigest()

    #
    # search cache
    #

    def search(
        self,
        retrieval_query: str,
        presentation_intent: str,
        user_intent: str,
        threshold=0.93,
        top_k=5,
    ):
        knowledge_hash = self.build_knowledge_hash()

        cache_query = self.build_cache_query(
            retrieval_query=retrieval_query,
            presentation_intent=presentation_intent,
            user_intent=user_intent,
        )

        query_emb = self.embed_text(cache_query)

        rows = self.conn.execute(
            """
            SELECT
                id,
                answer,
                embedding,
                retrieval_query,
                presentation_intent,
                user_intent
            FROM answer_cache
            WHERE knowledge_hash = ?
            ORDER BY id DESC
            LIMIT 1000
            """,
            (knowledge_hash,),
        ).fetchall()

        scored = []

        for row in rows:
            (
                cache_id,
                answer,
                embedding_json,
                cached_query,
                cached_presentation,
                cached_user_intent,
            ) = row

            try:
                emb = np.array(
                    json.loads(embedding_json),
                    dtype=np.float32,
                )

                score = self.cosine_similarity(
                    query_emb,
                    emb,
                )

                scored.append(
                    {
                        "id": cache_id,
                        "score": score,
                        "answer": answer,
                        "retrieval_query": cached_query,
                        "presentation_intent": cached_presentation,
                        "user_intent": cached_user_intent,
                    }
                )

            except Exception:
                continue

        scored.sort(
            key=lambda x: x["score"],
            reverse=True,
        )

        if not scored:
            return None

        top_results = scored[:top_k]
        best = top_results[0]
        if best["score"] < threshold:
            return None

        return {
            "best": best,
            "top_results": top_results,
        }

    #
    # save cache
    #

    def save(
        self,
        retrieval_query: str,
        presentation_intent: str,
        user_intent: str,
        answer: str,
    ):
        answer = (answer or "").strip()

        #
        # skip low quality
        #

        if not answer:
            return

        if len(answer) < 20:
            return

        if answer in {
            "不知道",
            "不知道.",
            "不知道。",
            "我不知道",
            "我不知道.",
            "我不知道。",
            "无法回答",
        }:
            return

        knowledge_hash = self.build_knowledge_hash()

        cache_query = self.build_cache_query(
            retrieval_query=retrieval_query,
            presentation_intent=presentation_intent,
            user_intent=user_intent,
        )

        embedding = self.embed_text(cache_query)

        embedding_json = json.dumps(
            embedding.tolist(),
            ensure_ascii=False,
        )

        cache_key = hashlib.md5(cache_query.encode("utf-8")).hexdigest()

        self.conn.execute(
            """
            INSERT INTO answer_cache (
                cache_key,
                retrieval_query,
                presentation_intent,
                user_intent,
                answer,
                embedding,
                knowledge_hash,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cache_key,
                retrieval_query,
                presentation_intent,
                user_intent,
                answer,
                embedding_json,
                knowledge_hash,
                int(time.time()),
            ),
        )

        self.conn.commit()


answer_cache = AnswerCache()

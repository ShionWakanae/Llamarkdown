import sqlite3
import json
import hashlib
import time
from pathlib import Path
import numpy as np
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from utils.settings import settings, CACHE_DB_PATH, REF_MD_DIR
from utils.logger import logger

log = logger.log


def serialize_source_nodes(nodes):
    result = []

    for node in nodes:
        metadata = node.metadata or {}

        result.append(
            {
                "score": round(
                    node.score or 0,
                    4,
                ),
                "file_name": metadata.get(
                    "file_name",
                    "",
                ),
                "file_path": metadata.get(
                    "file_path",
                    "",
                ),
                "header_path": metadata.get(
                    "header_path",
                    "",
                ),
                "line_start": metadata.get(
                    "line_start",
                ),
                "line_end": metadata.get(
                    "line_end",
                ),
            }
        )

    return result


class AnswerCache:
    def __init__(self):
        Path(CACHE_DB_PATH).parent.mkdir(
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

                source_nodes TEXT,

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

        self.knowledge_hash = self.build_knowledge_hash()
        deleted = self.invalidate_old_cache()
        cache_delete_msg = "" if deleted == 0 else f", {deleted} old entries removed"
        log(f"[RAG] Cache ready{cache_delete_msg}")

    # build cache query
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

    # embedding
    def embed_text(self, text: str):
        emb = self.embed_model.get_text_embedding(text)
        return np.array(
            emb,
            dtype=np.float32,
        )

    # cosine similarity
    def cosine_similarity(
        self,
        a: np.ndarray,
        b: np.ndarray,
    ):
        denom = np.linalg.norm(a) * np.linalg.norm(b)

        if denom == 0:
            return 0.0

        return float(np.dot(a, b) / denom)

    # knowledge hash
    def build_knowledge_hash(self):
        base = []
        root = (Path(settings.app_doc_path) / REF_MD_DIR).resolve()
        if not root.exists():
            return "empty"

        for path in sorted(root.rglob("*")):
            if path.is_file():
                stat = path.stat()

                base.append(f"{path}:{stat.st_size}:{int(stat.st_mtime)}")

        joined = "\n".join(base)
        return hashlib.md5(joined.encode("utf-8")).hexdigest()

    # search cache
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
                source_nodes,
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
                serialized_nodes,
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
                source_nodes = []

                if serialized_nodes:
                    try:
                        source_nodes = json.loads(serialized_nodes)
                    except Exception:
                        pass
                score = self.cosine_similarity(
                    query_emb,
                    emb,
                )

                # filter by presentation intent
                if cached_presentation != presentation_intent:
                    continue

                scored.append(
                    {
                        "id": cache_id,
                        "score": score,
                        "answer": answer,
                        "source_nodes": source_nodes,
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

    # delete old cache
    def invalidate_old_cache(self):
        cursor = self.conn.execute(
            """
            DELETE FROM answer_cache
            WHERE knowledge_hash <> ?
            """,
            (self.knowledge_hash,),
        )
        deleted = cursor.rowcount
        self.conn.commit()
        if deleted > 0:
            self.conn.execute("VACUUM")
        return deleted

    # save cache
    def save(
        self,
        retrieval_query: str,
        presentation_intent: str,
        user_intent: str,
        answer: str,
        source_nodes: list = None,
    ):
        answer = (answer or "").strip()
        serialized_nodes = json.dumps(
            serialize_source_nodes(source_nodes),
            ensure_ascii=False,
        )
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
                source_nodes,
                embedding,
                knowledge_hash,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cache_key,
                retrieval_query,
                presentation_intent,
                user_intent,
                answer,
                serialized_nodes,
                embedding_json,
                knowledge_hash,
                int(time.time()),
            ),
        )
        self.conn.commit()


answer_cache = AnswerCache()

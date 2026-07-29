"""
Embedding writer — behavioural notes (and summaries) -> pgvector.

Each note is embedded with Bedrock Titan (``amazon.titan-embed-text-v2:0``) and
stored in ``app_embeddings`` so the coding agent can do "find the thing that does X"
similarity retrieval. Degrades gracefully: if Bedrock is unreachable, the load logs
a warning and continues (the graph/Postgres facts are unaffected).

Idempotent per app: re-ingesting clears the app's prior note embeddings first.
"""
import json
import logging
from typing import List

import psycopg2

logger = logging.getLogger(__name__)

_EMBED_DIM = 1024   # must match schema.sql app_embeddings.embedding vector(1024)


class EmbeddingWriter:
    def __init__(self, pg_config: dict, bedrock_config: dict):
        self.conn = psycopg2.connect(
            host=pg_config["host"], port=pg_config["port"],
            database=pg_config["database"], user=pg_config["user"],
            password=pg_config["password"],
        )
        self.region = bedrock_config.get("region", "us-east-1")
        model = bedrock_config.get("embedding_model") or "amazon.titan-embed-text-v2:0"
        # accept either a bare model id or a full foundation-model ARN
        self.model_id = model.split("/")[-1] if model.startswith("arn:") else model
        self._client = None

    def _bedrock(self):
        if self._client is None:
            import boto3
            self._client = boto3.client("bedrock-runtime", region_name=self.region)
        return self._client

    def _embed(self, text: str) -> List[float]:
        resp = self._bedrock().invoke_model(
            modelId=self.model_id,
            body=json.dumps({"inputText": text[:8000],
                             "dimensions": _EMBED_DIM, "normalize": True}),
        )
        return json.loads(resp["body"].read())["embedding"]

    def write_notes(self, app_id: str, notes: list) -> int:
        """Embed and store each note. Returns the count actually written."""
        if not notes:
            return 0
        written = 0
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM app_embeddings WHERE app_id=%s AND kind='note'", (app_id,))
            for n in notes:
                try:
                    emb = self._embed(n.text)
                except Exception as exc:               # one bad note never fails the load
                    logger.warning(f"  embedding skipped (Bedrock error): {exc}")
                    continue
                vec = "[" + ",".join(f"{x:.6f}" for x in emb) + "]"
                cur.execute(
                    "INSERT INTO app_embeddings "
                    "(app_id, kind, subject, text, embedding, file_path, line, provenance) "
                    "VALUES (%s,'note',%s,%s,%s::vector,%s,%s,%s)",
                    (app_id, n.subject, n.text, vec, n.file_path, n.line, n.provenance),
                )
                written += 1
        self.conn.commit()
        return written

    def close(self):
        self.conn.close()

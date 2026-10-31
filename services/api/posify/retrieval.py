"""Optional offline E5 retrieval. No training, downloads or remote model code."""
import hashlib
import json
import importlib.util
from importlib.metadata import version, PackageNotFoundError
import math
import os
from pathlib import Path
from threading import Lock

from fastapi import HTTPException

from posify.assistant import retrieve, source_excerpt


class HybridRetriever:
    def __init__(self, database=None):
        self.database = database
        self._namespace = None
        self.model_path = os.getenv('POSIFY_EMBEDDING_DIR', '')
        self.min_score = float(os.getenv('POSIFY_EMBEDDING_MIN_SCORE', '0.80'))
        if not math.isfinite(self.min_score) or not -1 <= self.min_score <= 1:
            raise RuntimeError('POSIFY_EMBEDDING_MIN_SCORE must be finite and between -1 and 1')
        self._model = None
        self._lock = Lock()

    def readiness(self):
        return {'mode': 'hybrid_e5' if self.model_path else 'lexical',
                'artifact_present': bool(self.model_path and Path(self.model_path).is_dir()),
                'dependency_present': importlib.util.find_spec('sentence_transformers') is not None,
                'loaded': self._model is not None,
                'persistent_cache': self.database is not None,
                'note': 'Semantic score threshold is a configurable heuristic, not a confidence probability.'}

    def search(self, procedures, question):
        lexical = retrieve(procedures, question)
        if not self.model_path:
            return lexical
        if not procedures:
            return []
        if not self.readiness()['artifact_present'] or not self.readiness()['dependency_present']:
            raise HTTPException(503, 'Configured local embedding model or sentence-transformers is missing')
        sources = []
        for p in procedures:
            for offset in range(0, len(p['source_text']), 1000):
                sources.append(source_excerpt(p, offset))
        if len(sources) > 256:
            raise HTTPException(422, 'Local semantic search supports at most 256 chunks; narrow the procedure collection')
        with self._lock:
            try:
                if self._model is None:
                    from sentence_transformers import SentenceTransformer
                    self._model = SentenceTransformer(self.model_path, local_files_only=True,
                                                       trust_remote_code=False, device='cpu')
                    self._model.max_seq_length = 512
                vectors = self._vectors(sources, question)
                scores = [sum(a * b for a, b in zip(vectors[0], v, strict=True)) for v in vectors[1:]]
            except Exception:
                raise HTTPException(503, 'Local embedding inference failed')
        if len(scores) != len(sources) or not all(math.isfinite(s) for s in scores):
            raise HTTPException(502, 'Embedding runtime returned invalid scores')
        semantic = [s for _, s in sorted(zip(scores, sources), key=lambda x: (-x[0], x[1]['id']))
                    if _ >= self.min_score][:8]
        ranks = {}
        for result in (lexical, semantic):
            for rank, source in enumerate(result, start=1):
                ranks[source['id']] = ranks.get(source['id'], 0) + 1 / (60 + rank)
        indexed = {s['id']: s for s in sources}
        return [indexed[key] for key in sorted(ranks, key=lambda key: (-ranks[key], key))[:4]]

    @staticmethod
    def _valid(vector, dimensions=None):
        if not isinstance(vector, (list, tuple)) or not 1 <= len(vector) <= 4096:
            return False
        if dimensions is not None and len(vector) != dimensions:
            return False
        return all(isinstance(n, (int, float)) and math.isfinite(n) for n in vector) and abs(sum(n*n for n in vector) - 1) < 0.01

    def _cache_namespace(self):
        if self._namespace is None:
            # Model artifacts must be immutable for the lifetime of the process.
            digest = hashlib.sha256(b'posify-e5-v1:query-passage:normalized:512:1000')
            try:
                digest.update(version('sentence-transformers').encode())
            except PackageNotFoundError:
                digest.update(b'controlled-encoder')
            root = Path(self.model_path).resolve()
            for path in sorted(root.rglob('*')):
                if path.is_file():
                    digest.update(str(path.relative_to(root)).encode())
                    with path.open('rb') as handle:
                        digest.update(hashlib.file_digest(handle, 'sha256').digest())
            self._namespace = digest.hexdigest()
        return self._namespace

    def _vectors(self, sources, question):
        hashes = [hashlib.sha256(source['excerpt'].encode()).hexdigest() for source in sources]
        cached = {}
        namespace = self._cache_namespace() if self.database else None
        if self.database:
            with self.database.connect() as db:
                # Only content hashes from the already scoped candidate set are read.
                for key in set(hashes):
                    row = db.execute('SELECT vector FROM embedding_cache WHERE namespace=? AND passage_hash=?', (namespace, key)).fetchone()
                    if row:
                        try:
                            candidate = json.loads(row['vector'])
                            if self._valid(candidate):
                                cached[key] = candidate
                        except (ValueError, TypeError):
                            pass
        missing = list(dict.fromkeys(key for key in hashes if key not in cached))
        text_by_hash = {key: source['excerpt'] for key, source in zip(hashes, sources, strict=True)}
        encoded = self._model.encode(['query: ' + question] + ['passage: ' + text_by_hash[key] for key in missing],
                                     normalize_embeddings=True, show_progress_bar=False)
        vectors = [[float(n) for n in vector] for vector in encoded]
        if len(vectors) != 1 + len(missing) or not vectors or not all(self._valid(v, len(vectors[0])) for v in vectors):
            raise ValueError('Invalid normalized embedding vectors')
        dimensions = len(vectors[0])
        wrong = [key for key in hashes if key in cached and len(cached[key]) != dimensions]
        if wrong:
            # A corrupt cache must not change ranking; recompute incompatible entries.
            unique = list(dict.fromkeys(wrong))
            corrected = [[float(n) for n in v] for v in self._model.encode(
                ['passage: ' + text_by_hash[key] for key in unique], normalize_embeddings=True, show_progress_bar=False)]
            if len(corrected) != len(unique) or not all(self._valid(v, dimensions) for v in corrected):
                raise ValueError('Invalid replacement embeddings')
            cached.update(zip(unique, corrected, strict=True))
            missing.extend(unique)
        fresh = dict(zip(list(dict.fromkeys(key for key in hashes if key not in cached)), vectors[1:], strict=True))
        cached.update(fresh)
        if self.database:
            with self.database.connect() as db:
                for key in set(missing):
                    db.execute('INSERT INTO embedding_cache(namespace,passage_hash,vector) VALUES(?,?,?) '
                               'ON CONFLICT(namespace,passage_hash) DO UPDATE SET vector=excluded.vector',
                               (namespace, key, json.dumps(cached[key])))
        return [vectors[0], *[cached[key] for key in hashes]]

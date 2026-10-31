"""Optional offline E5 retrieval. No training, downloads or remote model code."""
import importlib.util
import math
import os
from pathlib import Path
from threading import Lock

from fastapi import HTTPException

from posify.assistant import retrieve, source_excerpt


class HybridRetriever:
    def __init__(self):
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
                vectors = self._model.encode(['query: ' + question] +
                                             ['passage: ' + s['excerpt'] for s in sources],
                                             normalize_embeddings=True, show_progress_bar=False)
                scores = [sum(float(a) * float(b) for a, b in zip(vectors[0], v, strict=True))
                          for v in vectors[1:]]
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

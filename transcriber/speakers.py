from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np


@dataclass(frozen=True)
class DiarizationResult:
    labels: list[str]


@lru_cache(maxsize=1)
def _load_speaker_encoder():
    try:
        from speechbrain.inference.speaker import EncoderClassifier
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Speaker labeling requires extra deps. Install them with: pip install -r requirements-speakers.txt "
            "(Windows: run Setup-Speakers.cmd)."
        ) from e

    # Downloads the model automatically on first use.
    return EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb")


def _cluster_embeddings(embeddings: np.ndarray, num_speakers: int) -> list[int]:
    if num_speakers <= 1 or embeddings.shape[0] == 0:
        return [0] * int(embeddings.shape[0])

    # Normalize for cosine-ish clustering with KMeans.
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-12
    X = embeddings / norms

    try:
        from sklearn.cluster import KMeans
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Speaker labeling requires extra deps. Install them with: pip install -r requirements-speakers.txt "
            "(Windows: run Setup-Speakers.cmd)."
        ) from e

    km = KMeans(n_clusters=int(num_speakers), n_init="auto", random_state=0)
    labels = km.fit_predict(X)
    return [int(x) for x in labels.tolist()]


def label_speakers_from_windows(*, windows: list[np.ndarray], num_speakers: int) -> DiarizationResult:
    """
    windows: list of float32 mono 16k audio arrays, each same length.
    Returns 'S1', 'S2', ... per window.
    """
    if not windows:
        return DiarizationResult(labels=[])
    if num_speakers <= 1:
        return DiarizationResult(labels=["Speaker 1"] * len(windows))

    encoder = _load_speaker_encoder()

    import torch

    batch = 16
    embs: list[np.ndarray] = []
    for i in range(0, len(windows), batch):
        chunk = windows[i : i + batch]
        wavs = torch.from_numpy(np.stack(chunk, axis=0))
        with torch.no_grad():
            e = encoder.encode_batch(wavs)
        e = e.squeeze(1).cpu().numpy()
        embs.append(e)

    embeddings = np.concatenate(embs, axis=0)
    cluster_ids = _cluster_embeddings(embeddings, num_speakers=int(num_speakers))
    labels = [f"Speaker {cid + 1}" for cid in cluster_ids]
    return DiarizationResult(labels=labels)

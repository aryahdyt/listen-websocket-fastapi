from typing import List, Dict, Tuple

import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression


def build_training_pairs(
    candidates: List[Dict[str, float]],
    truth_map: Dict[str, str],
    negative_ratio: float = 1.0,
) -> Tuple[pd.DataFrame, np.ndarray]:
    """
    Build a training dataset from candidate pairs and truth mapping.
    Positive: candidate where truth_map[arpa_id] == ais_id
    Negative: randomly sample other candidates for each ARPA (up to negative_ratio × positives)
    Returns: (X_df features, y labels)
    """
    # Index candidates by arpa_id for negative sampling
    by_arpa: Dict[str, List[Dict[str, float]]] = {}
    for c in candidates:
        by_arpa.setdefault(c["arpa_id"], []).append(c)

    rows = []
    y = []

    # Build positives
    for arpa_id, ais_id_true in truth_map.items():
        cand_list = by_arpa.get(arpa_id, [])
        for c in cand_list:
            if c["ais_id"] == ais_id_true:
                rows.append({k: c[k] for k in ["d_m", "dv_ms", "dtheta_deg", "dt_s", "s_total"]})
                y.append(1)
                break

    positives = len(y)
    if positives == 0:
        # No truth or no candidates found; return empty
        return pd.DataFrame(columns=["d_m", "dv_ms", "dtheta_deg", "dt_s", "s_total"]), np.array([])

    # Build negatives: sample from other candidates per ARPA
    neg_needed = int(negative_ratio * positives)
    rng = np.random.default_rng(123)
    neg_rows = []
    for arpa_id, cand_list in by_arpa.items():
        # Filter out true match if exists
        true_ais = truth_map.get(arpa_id, None)
        pool = [c for c in cand_list if c["ais_id"] != true_ais]
        if len(pool) == 0:
            continue
        take = rng.integers(1, min(3, len(pool)) + 1)
        samples = rng.choice(pool, size=take, replace=False)
        for c in samples:
            neg_rows.append({k: c[k] for k in ["d_m", "dv_ms", "dtheta_deg", "dt_s", "s_total"]})
    # Downsample negatives to requested amount
    if len(neg_rows) > 0:
        idx = rng.choice(len(neg_rows), size=min(len(neg_rows), neg_needed), replace=False)
        for i in idx:
            rows.append(neg_rows[i])
            y.append(0)

    X = pd.DataFrame(rows)
    y_arr = np.array(y)
    return X, y_arr


def train_logistic_model(X: pd.DataFrame, y: np.ndarray) -> Pipeline:
    """
    Train a logistic regression classifier on features.
    Features used: d_m, dv_ms, dtheta_deg, dt_s, s_total
    Returns a scikit-learn pipeline with StandardScaler + LogisticRegression.
    """
    if X.empty or y.size == 0:
        # Create a dummy pipeline to avoid crashing; not fitted
        pipe = Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=500))
        ])
        return pipe

    pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(max_iter=500, class_weight="balanced"))
    ])
    pipe.fit(X, y)
    return pipe


def predict_probabilities(model: Pipeline, X: pd.DataFrame) -> np.ndarray:
    if X.empty:
        return np.array([])
    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(X)
        # Probability of class 1 (match)
        return proba[:, 1]
    else:
        # Fallback to decision function scaled to [0,1]
        scores = model.decision_function(X)
        # Min-max scale
        mn, mx = float(scores.min()), float(scores.max())
        if mx - mn < 1e-6:
            return np.full_like(scores, 0.5, dtype=float)
        return (scores - mn) / (mx - mn)
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment


def angle_diff_deg(a: float, b: float) -> float:
    """Minimal absolute angle difference between a and b in degrees."""
    d = abs((a - b) % 360.0)
    if d > 180.0:
        d = 360.0 - d
    return d


@dataclass
class ScoringParams:
    pos_sigma_m: float = 150.0
    spd_sigma_ms: float = 1.5
    hdg_sigma_deg: float = 20.0
    time_sigma_s: float = 30.0
    w_pos: float = 0.5
    w_spd: float = 0.15
    w_brg: float = 0.15
    w_time: float = 0.2
    # Optional ARPA geometry (range/bearing) scoring params
    range_sigma_m: float = 0.0
    brg_geo_sigma_deg: float = 0.0
    w_range: float = 0.0
    w_brg_geo: float = 0.0


def extract_features(ais_row: pd.Series, arpa_row: pd.Series) -> Dict[str, float]:
    dx = float(arpa_row["x"]) - float(ais_row["x"])
    dy = float(arpa_row["y"]) - float(ais_row["y"])
    d_m = float(np.hypot(dx, dy))
    dv_ms = abs(float(arpa_row["speed_ms"]) - float(ais_row["sog_ms"]))
    dtheta_deg = angle_diff_deg(float(arpa_row["heading_deg"]), float(ais_row["cog_deg"]))
    dt_s = abs(float(arpa_row["timestamp_s"]) - float(ais_row["timestamp_s"]))
    feats: Dict[str, float] = {
        "d_m": d_m,
        "dv_ms": dv_ms,
        "dtheta_deg": dtheta_deg,
        "dt_s": dt_s,
    }
    # Optional ARPA geometry comparison: compare ARPA measured (range/bearing) to AIS radial from site
    arpa_r_meas = arpa_row.get("r_meas_m", None)
    arpa_brg_meas = arpa_row.get("brg_meas_deg", None)
    ais_r_site = ais_row.get("r_site_m", None)
    ais_brg_site = ais_row.get("brg_site_deg", None)
    try:
        if arpa_r_meas is not None and ais_r_site is not None:
            feats["range_error_m"] = abs(float(arpa_r_meas) - float(ais_r_site))
    except Exception:
        pass
    try:
        if arpa_brg_meas is not None and ais_brg_site is not None:
            feats["bearing_error_deg"] = angle_diff_deg(float(arpa_brg_meas), float(ais_brg_site))
    except Exception:
        pass
    return feats


def feature_score(features: Dict[str, float], p: ScoringParams) -> Dict[str, float]:
    s_pos = float(np.exp(-((features["d_m"] / p.pos_sigma_m) ** 2)))
    s_spd = float(np.exp(-((features["dv_ms"] / p.spd_sigma_ms) ** 2)))
    s_brg = float(np.exp(-((features["dtheta_deg"] / p.hdg_sigma_deg) ** 2)))
    s_time = float(np.exp(-((features["dt_s"] / p.time_sigma_s) ** 2)))
    # Optional ARPA geometry metrics
    s_range = 0.0
    s_brg_geo = 0.0
    if "range_error_m" in features and p.range_sigma_m and p.range_sigma_m > 0.0:
        s_range = float(np.exp(-((features["range_error_m"] / p.range_sigma_m) ** 2)))
    if "bearing_error_deg" in features and p.brg_geo_sigma_deg and p.brg_geo_sigma_deg > 0.0:
        s_brg_geo = float(np.exp(-((features["bearing_error_deg"] / p.brg_geo_sigma_deg) ** 2)))
    s_total = (
        p.w_pos * s_pos
        + p.w_spd * s_spd
        + p.w_brg * s_brg
        + p.w_time * s_time
        + p.w_range * s_range
        + p.w_brg_geo * s_brg_geo
    )
    return {
        "s_pos": s_pos,
        "s_spd": s_spd,
        "s_brg": s_brg,
        "s_time": s_time,
        "s_range": s_range,
        "s_brg_geo": s_brg_geo,
        "s_total": s_total,
    }


def build_candidates(
    ais_df: pd.DataFrame,
    arpa_df: pd.DataFrame,
    gating_distance_m: float = 800.0,
    time_gate_s: float = 120.0,
    scoring_params: Optional[ScoringParams] = None,
) -> List[Dict[str, float]]:
    """
    Build candidate ARPA↔AIS pairs within gates and compute feature-based scores.
    Returns a list of dicts with keys: arpa_id, ais_id, s_total, d_m, dv_ms, dtheta_deg, dt_s
    """
    scoring_params = scoring_params or ScoringParams()
    candidates: List[Dict[str, float]] = []
    # Pre-index rows by id for later lookup
    ais_index = {row["ais_id"]: i for i, row in ais_df.iterrows()}
    arpa_index = {row["arpa_id"]: i for i, row in arpa_df.iterrows()}

    for _, a_row in arpa_df.iterrows():
        for _, i_row in ais_df.iterrows():
            feats = extract_features(i_row, a_row)
            if feats["d_m"] <= gating_distance_m and feats["dt_s"] <= time_gate_s:
                scores = feature_score(feats, scoring_params)
                candidates.append(
                    {
                        "arpa_id": a_row["arpa_id"],
                        "ais_id": i_row["ais_id"],
                        "s_total": scores["s_total"],
                        **feats,
                    }
                )
    return candidates


def assign_one_to_one(
    candidates: List[Dict[str, float]],
    arpa_df: pd.DataFrame,
    ais_df: pd.DataFrame,
    accept_threshold: float = 0.7,
) -> Tuple[List[Dict[str, float]], List[str]]:
    """
    Perform Hungarian assignment on cost=1 - s_total, then accept matches above threshold.
    Returns: (accepted_matches, unmatched_arpa_ids)
    """
    if len(candidates) == 0:
        return [], list(arpa_df["arpa_id"].tolist())

    # Build a cost matrix
    arpa_ids = arpa_df["arpa_id"].tolist()
    ais_ids = ais_df["ais_id"].tolist()
    arpa_idx_map = {aid: i for i, aid in enumerate(arpa_ids)}
    ais_idx_map = {iid: j for j, iid in enumerate(ais_ids)}

    cost = np.ones((len(arpa_ids), len(ais_ids))) * 1.5  # large default cost
    score_map: Dict[Tuple[int, int], float] = {}

    for c in candidates:
        i = arpa_idx_map[c["arpa_id"]]
        j = ais_idx_map[c["ais_id"]]
        score_map[(i, j)] = c["s_total"]
        cost[i, j] = 1.0 - c["s_total"]

    row_ind, col_ind = linear_sum_assignment(cost)

    accepted = []
    assigned_arpa = set()
    for i, j in zip(row_ind, col_ind):
        s = score_map.get((i, j), None)
        if s is not None and s >= accept_threshold:
            accepted.append(
                {
                    "arpa_id": arpa_ids[i],
                    "ais_id": ais_ids[j],
                    "score": float(s),
                }
            )
            assigned_arpa.add(arpa_ids[i])

    unmatched_arpa = [aid for aid in arpa_ids if aid not in assigned_arpa]
    return accepted, unmatched_arpa
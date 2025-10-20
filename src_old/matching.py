"""
Matching module for AIS-ARPA data fusion.
Full implementation with probabilistic scoring and Hungarian assignment.
"""
from typing import List, Dict, Any, Tuple
import pandas as pd
import numpy as np

try:
    from scipy.optimize import linear_sum_assignment
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False
    linear_sum_assignment = None


class ScoringParams:
    """Parameters for scoring matches between AIS and ARPA."""
    
    def __init__(
        self,
        pos_sigma_m: float = 500.0,
        spd_sigma_ms: float = 3.0,
        hdg_sigma_deg: float = 40.0,
        time_sigma_s: float = 60.0,
        range_sigma_m: float = 1500.0,
        brg_geo_sigma_deg: float = 15.0,
        w_range: float = 0.15,
        w_brg_geo: float = 0.15
    ):
        """
        Initialize scoring parameters.
        
        Args:
            pos_sigma_m: Position uncertainty (meters)
            spd_sigma_ms: Speed uncertainty (m/s)
            hdg_sigma_deg: Heading uncertainty (degrees)
            time_sigma_s: Time uncertainty (seconds)
            range_sigma_m: Range measurement uncertainty (meters)
            brg_geo_sigma_deg: Bearing geometry uncertainty (degrees)
            w_range: Weight for range score
            w_brg_geo: Weight for bearing score
        """
        self.pos_sigma_m = pos_sigma_m
        self.spd_sigma_ms = spd_sigma_ms
        self.hdg_sigma_deg = hdg_sigma_deg
        self.time_sigma_s = time_sigma_s
        self.range_sigma_m = range_sigma_m
        self.brg_geo_sigma_deg = brg_geo_sigma_deg
        self.w_range = w_range
        self.w_brg_geo = w_brg_geo


def normalize_angle_diff(angle_diff: float) -> float:
    """
    Normalize angle difference to [-180, 180] range.
    
    Args:
        angle_diff: Angle difference in degrees
        
    Returns:
        Normalized angle in [-180, 180]
    """
    while angle_diff > 180.0:
        angle_diff -= 360.0
    while angle_diff < -180.0:
        angle_diff += 360.0
    return angle_diff


def gaussian_score(delta: float, sigma: float) -> float:
    """
    Calculate Gaussian probability score.
    
    Args:
        delta: Difference value
        sigma: Standard deviation
        
    Returns:
        Score in [0, 1] range
    """
    if sigma <= 0:
        return 0.0
    
    # Gaussian: exp(-0.5 * (delta/sigma)^2)
    score = np.exp(-0.5 * (delta / sigma) ** 2)
    return float(score)


def build_candidates(
    ais_df: pd.DataFrame,
    arpa_df: pd.DataFrame,
    gating_distance_m: float = 8000.0,
    time_gate_s: float = 1800.0,
    scoring_params: ScoringParams = None
) -> List[Dict[str, Any]]:
    """
    Build candidate matches between AIS and ARPA targets.
    
    Uses probabilistic scoring based on:
    - Position difference (Euclidean distance)
    - Speed difference
    - Heading difference
    - Time difference
    - Range/bearing geometry (if available)
    
    Args:
        ais_df: DataFrame with AIS data (requires: x, y, spd, hdg, t columns)
        arpa_df: DataFrame with ARPA data (requires: x, y, spd, hdg, t columns)
        gating_distance_m: Maximum distance for gating (meters)
        time_gate_s: Maximum time difference for gating (seconds)
        scoring_params: Scoring parameters
        
    Returns:
        List of candidate matches with scores
    """
    if scoring_params is None:
        scoring_params = ScoringParams()
    
    candidates = []
    
    # Iterate through all ARPA targets
    for arpa_idx, arpa_row in arpa_df.iterrows():
        arpa_x = arpa_row.get('x', 0.0)
        arpa_y = arpa_row.get('y', 0.0)
        arpa_spd = arpa_row.get('spd', arpa_row.get('speed_ms', 0.0))
        arpa_hdg = arpa_row.get('hdg', arpa_row.get('heading_deg', 0.0))
        arpa_t = arpa_row.get('t', arpa_row.get('timestamp_s', 0.0))
        arpa_id = arpa_row.get('arpa_id', arpa_row.get('target', str(arpa_idx)))
        
        # Optional: ARPA range/bearing measurements
        arpa_r_meas = arpa_row.get('r_meas_m', np.nan)
        arpa_brg_meas = arpa_row.get('brg_meas_deg', np.nan)
        arpa_r_site = arpa_row.get('r_site_m', np.nan)
        arpa_brg_site = arpa_row.get('brg_site_deg', np.nan)
        
        # Iterate through all AIS targets
        for ais_idx, ais_row in ais_df.iterrows():
            ais_x = ais_row.get('x', 0.0)
            ais_y = ais_row.get('y', 0.0)
            ais_spd = ais_row.get('spd', ais_row.get('sog_ms', 0.0))
            ais_hdg = ais_row.get('hdg', ais_row.get('cog_deg', 0.0))
            ais_t = ais_row.get('t', ais_row.get('timestamp_s', 0.0))
            ais_id = ais_row.get('ais_id', ais_row.get('mmsi', str(ais_idx)))
            
            # Optional: AIS range/bearing from site
            ais_r_site = ais_row.get('r_site_m', np.nan)
            ais_brg_site = ais_row.get('brg_site_deg', np.nan)
            
            # Calculate differences
            dx = ais_x - arpa_x
            dy = ais_y - arpa_y
            d_m = np.sqrt(dx**2 + dy**2)  # Euclidean distance
            
            dv_ms = abs(ais_spd - arpa_spd)  # Speed difference
            
            dtheta_deg = normalize_angle_diff(ais_hdg - arpa_hdg)  # Heading difference
            dtheta_deg = abs(dtheta_deg)
            
            dt_s = abs(ais_t - arpa_t)  # Time difference
            
            # Gating: Skip if outside distance or time gates
            if d_m > gating_distance_m:
                continue
            if dt_s > time_gate_s:
                continue
            
            # Calculate individual scores
            s_pos = gaussian_score(d_m, scoring_params.pos_sigma_m)
            s_spd = gaussian_score(dv_ms, scoring_params.spd_sigma_ms)
            s_hdg = gaussian_score(dtheta_deg, scoring_params.hdg_sigma_deg)
            s_time = gaussian_score(dt_s, scoring_params.time_sigma_s)
            
            # Optional: Range/bearing geometry scores
            s_range = 1.0  # Default
            s_brg = 1.0    # Default
            range_error_m = np.nan
            bearing_error_deg = np.nan
            
            # If ARPA has measured range and we have AIS site range
            if np.isfinite(arpa_r_meas) and np.isfinite(ais_r_site):
                range_error_m = abs(ais_r_site - arpa_r_meas)
                s_range = gaussian_score(range_error_m, scoring_params.range_sigma_m)
            
            # If ARPA has measured bearing and we have AIS site bearing
            if np.isfinite(arpa_brg_meas) and np.isfinite(ais_brg_site):
                bearing_error_deg = normalize_angle_diff(ais_brg_site - arpa_brg_meas)
                bearing_error_deg = abs(bearing_error_deg)
                s_brg = gaussian_score(bearing_error_deg, scoring_params.brg_geo_sigma_deg)
            
            # Combined score (weighted product)
            # Base weights: equal for pos, spd, hdg, time
            w_base = (1.0 - scoring_params.w_range - scoring_params.w_brg_geo) / 4.0
            
            # Calculate total score
            s_total = (
                s_pos ** w_base *
                s_spd ** w_base *
                s_hdg ** w_base *
                s_time ** w_base *
                s_range ** scoring_params.w_range *
                s_brg ** scoring_params.w_brg_geo
            )
            
            # Store candidate
            candidate = {
                'arpa_id': arpa_id,
                'ais_id': ais_id,
                'arpa_idx': int(arpa_idx),
                'ais_idx': int(ais_idx),
                'd_m': float(d_m),
                'dv_ms': float(dv_ms),
                'dtheta_deg': float(dtheta_deg),
                'dt_s': float(dt_s),
                'range_error_m': float(range_error_m),
                'bearing_error_deg': float(bearing_error_deg),
                's_pos': float(s_pos),
                's_spd': float(s_spd),
                's_hdg': float(s_hdg),
                's_time': float(s_time),
                's_range': float(s_range),
                's_brg': float(s_brg),
                's_total': float(s_total)
            }
            
            candidates.append(candidate)
    
    return candidates


def assign_one_to_one(
    candidates: List[Dict[str, Any]],
    arpa_df: pd.DataFrame = None,
    ais_df: pd.DataFrame = None,
    accept_threshold: float = 0.6
) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
    """
    Assign one-to-one matches using Hungarian algorithm (optimal assignment).
    
    Uses scipy.optimize.linear_sum_assignment for maximum weight matching.
    
    Args:
        candidates: List of candidate matches with scores
        arpa_df: DataFrame with ARPA data (optional, for getting IDs)
        ais_df: DataFrame with AIS data (optional, for getting IDs)
        accept_threshold: Minimum score threshold (below this = reject)
        
    Returns:
        Tuple of:
        - matches: List of matched pairs with scores
        - unmatched_arpa: List of unmatched ARPA IDs
        - unmatched_ais: List of unmatched AIS IDs
    """
    if not candidates:
        # No candidates - all unmatched
        unmatched_arpa = []
        unmatched_ais = []
        
        if arpa_df is not None and not arpa_df.empty:
            unmatched_arpa = arpa_df.get('arpa_id', arpa_df.get('target', arpa_df.index)).tolist()
            unmatched_arpa = [str(x) for x in unmatched_arpa]
        
        if ais_df is not None and not ais_df.empty:
            unmatched_ais = ais_df.get('ais_id', ais_df.get('mmsi', ais_df.index)).tolist()
            unmatched_ais = [str(x) for x in unmatched_ais]
        
        return [], unmatched_arpa, unmatched_ais
    
    if not HAS_SCIPY:
        print("⚠️ scipy not available, using greedy assignment (non-optimal)")
        return _greedy_assignment(candidates, arpa_df, ais_df, accept_threshold)
    
    # Build cost matrix for Hungarian algorithm
    # Collect unique ARPA and AIS IDs from candidates
    arpa_ids = sorted(set(c['arpa_id'] for c in candidates))
    ais_ids = sorted(set(c['ais_id'] for c in candidates))
    
    arpa_id_to_idx = {aid: i for i, aid in enumerate(arpa_ids)}
    ais_id_to_idx = {iid: i for i, iid in enumerate(ais_ids)}
    
    n_arpa = len(arpa_ids)
    n_ais = len(ais_ids)
    
    # Initialize cost matrix (negative score for maximization)
    # scipy linear_sum_assignment minimizes, so use negative scores
    cost_matrix = np.full((n_arpa, n_ais), 1e9)  # High cost = no match
    
    # Fill cost matrix
    for c in candidates:
        arpa_idx = arpa_id_to_idx[c['arpa_id']]
        ais_idx = ais_id_to_idx[c['ais_id']]
        score = c['s_total']
        
        # Negative score for maximization (minimize negative = maximize positive)
        cost_matrix[arpa_idx, ais_idx] = -score
    
    # Run Hungarian algorithm
    arpa_indices, ais_indices = linear_sum_assignment(cost_matrix)
    
    # Extract matches above threshold
    matches = []
    matched_arpa_ids = set()
    matched_ais_ids = set()
    
    for arpa_idx, ais_idx in zip(arpa_indices, ais_indices):
        arpa_id = arpa_ids[arpa_idx]
        ais_id = ais_ids[ais_idx]
        score = -cost_matrix[arpa_idx, ais_idx]  # Convert back to positive
        
        # Only accept if score above threshold
        if score >= accept_threshold:
            # Find original candidate to get all details
            candidate = next(
                (c for c in candidates if c['arpa_id'] == arpa_id and c['ais_id'] == ais_id),
                None
            )
            
            if candidate:
                matches.append(candidate)
                matched_arpa_ids.add(arpa_id)
                matched_ais_ids.add(ais_id)
    
    # Determine unmatched
    all_arpa_ids = set()
    all_ais_ids = set()
    
    if arpa_df is not None and not arpa_df.empty:
        all_arpa_ids = set(arpa_df.get('arpa_id', arpa_df.get('target', arpa_df.index)).astype(str).tolist())
    else:
        all_arpa_ids = set(arpa_ids)
    
    if ais_df is not None and not ais_df.empty:
        all_ais_ids = set(ais_df.get('ais_id', ais_df.get('mmsi', ais_df.index)).astype(str).tolist())
    else:
        all_ais_ids = set(ais_ids)
    
    unmatched_arpa = sorted(list(all_arpa_ids - matched_arpa_ids))
    unmatched_ais = sorted(list(all_ais_ids - matched_ais_ids))
    
    return matches, unmatched_arpa, unmatched_ais


def _greedy_assignment(
    candidates: List[Dict[str, Any]],
    arpa_df: pd.DataFrame,
    ais_df: pd.DataFrame,
    accept_threshold: float
) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
    """
    Fallback greedy assignment (non-optimal) when scipy is not available.
    
    Sorts candidates by score and greedily assigns highest scores first.
    """
    # Sort by score descending
    sorted_candidates = sorted(candidates, key=lambda c: c['s_total'], reverse=True)
    
    matches = []
    matched_arpa_ids = set()
    matched_ais_ids = set()
    
    for candidate in sorted_candidates:
        arpa_id = candidate['arpa_id']
        ais_id = candidate['ais_id']
        score = candidate['s_total']
        
        # Skip if already matched or below threshold
        if score < accept_threshold:
            continue
        if arpa_id in matched_arpa_ids or ais_id in matched_ais_ids:
            continue
        
        matches.append(candidate)
        matched_arpa_ids.add(arpa_id)
        matched_ais_ids.add(ais_id)
    
    # Determine unmatched
    all_arpa_ids = set()
    all_ais_ids = set()
    
    if arpa_df is not None and not arpa_df.empty:
        all_arpa_ids = set(arpa_df.get('arpa_id', arpa_df.get('target', arpa_df.index)).astype(str).tolist())
    else:
        all_arpa_ids = set(c['arpa_id'] for c in candidates)
    
    if ais_df is not None and not ais_df.empty:
        all_ais_ids = set(ais_df.get('ais_id', ais_df.get('mmsi', ais_df.index)).astype(str).tolist())
    else:
        all_ais_ids = set(c['ais_id'] for c in candidates)
    
    unmatched_arpa = sorted(list(all_arpa_ids - matched_arpa_ids))
    unmatched_ais = sorted(list(all_ais_ids - matched_ais_ids))
    
    return matches, unmatched_arpa, unmatched_ais

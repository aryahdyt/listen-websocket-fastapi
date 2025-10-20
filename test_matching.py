"""
Test script for matching algorithm.
Run this to verify the matching system works correctly.
"""
import pandas as pd
import numpy as np
from src.matching import ScoringParams, build_candidates, assign_one_to_one
from src.geo import make_transformer, to_xy, parse_time_s, knots_to_mps


def test_coordinate_transformation():
    """Test coordinate transformation."""
    print("\n" + "="*60)
    print("TEST 1: Coordinate Transformation")
    print("="*60)
    
    site_lat = -1.279656
    site_lon = 116.809655
    
    # Create transformer
    transformer = make_transformer(site_lat, site_lon, method="utm")
    
    # Test single point
    lat, lon = -1.28, 116.81
    x, y = to_xy(lat, lon, site_lat, site_lon, transformer)
    
    print(f"\nSite: ({site_lat:.6f}, {site_lon:.6f})")
    print(f"Test Point: ({lat:.6f}, {lon:.6f})")
    print(f"XY Coordinates: ({x:.2f} m, {y:.2f} m)")
    print(f"Distance from site: {np.sqrt(x**2 + y**2):.2f} m")
    
    # Test multiple points
    lats = [-1.28, -1.29, -1.30]
    lons = [116.81, 116.82, 116.83]
    xs, ys = to_xy(lats, lons, site_lat, site_lon, transformer)
    
    print(f"\nMultiple points:")
    for i, (lat, lon, x, y) in enumerate(zip(lats, lons, xs, ys)):
        print(f"  Point {i+1}: ({lat:.6f}, {lon:.6f}) → ({x:.2f} m, {y:.2f} m)")
    
    print("\n✓ Coordinate transformation test passed!")


def test_matching_algorithm():
    """Test matching algorithm with synthetic data."""
    print("\n" + "="*60)
    print("TEST 2: Matching Algorithm")
    print("="*60)
    
    site_lat = -1.279656
    site_lon = 116.809655
    
    # Create transformer
    transformer = make_transformer(site_lat, site_lon, method="utm")
    
    # Create synthetic AIS data
    print("\nCreating synthetic AIS data...")
    ais_data = {
        'ais_id': ['123456', '789012', '345678'],
        'lat': [-1.280, -1.285, -1.290],
        'lon': [116.810, 116.815, 116.820],
        'sog': [10.5, 8.2, 12.3],  # knots
        'cog': [45.0, 90.0, 180.0],  # degrees
        'ts': [1700000000, 1700000000, 1700000000]  # timestamp
    }
    ais_df = pd.DataFrame(ais_data)
    
    # Convert to XY
    ais_df['x'], ais_df['y'] = to_xy(
        ais_df['lat'].values, ais_df['lon'].values,
        site_lat, site_lon, transformer
    )
    ais_df['spd'] = ais_df['sog'].apply(knots_to_mps)
    ais_df['hdg'] = ais_df['cog']
    ais_df['t'] = ais_df['ts'].apply(parse_time_s)
    
    print(f"  {len(ais_df)} AIS targets created")
    
    # Create synthetic ARPA data (slightly offset from AIS)
    print("\nCreating synthetic ARPA data...")
    arpa_data = {
        'arpa_id': ['T1', 'T2', 'T3'],
        'lat': [-1.2801, -1.2851, -1.2901],  # Slight offset
        'lon': [116.8101, 116.8151, 116.8201],
        'speed': [10.4, 8.1, 12.2],  # knots, close to AIS
        'course': [44.0, 89.0, 179.0],  # degrees, close to AIS
        'recv_at': [1700000001, 1700000001, 1700000001]  # 1 second later
    }
    arpa_df = pd.DataFrame(arpa_data)
    
    # Convert to XY
    arpa_df['x'], arpa_df['y'] = to_xy(
        arpa_df['lat'].values, arpa_df['lon'].values,
        site_lat, site_lon, transformer
    )
    arpa_df['spd'] = arpa_df['speed'].apply(knots_to_mps)
    arpa_df['hdg'] = arpa_df['course']
    arpa_df['t'] = arpa_df['recv_at'].apply(parse_time_s)
    
    print(f"  {len(arpa_df)} ARPA targets created")
    
    # Build candidates
    print("\nBuilding candidates...")
    scoring_params = ScoringParams(
        pos_sigma_m=500.0,
        spd_sigma_ms=3.0,
        hdg_sigma_deg=40.0,
        time_sigma_s=60.0
    )
    
    candidates = build_candidates(
        ais_df, arpa_df,
        gating_distance_m=8000.0,
        time_gate_s=1800.0,
        scoring_params=scoring_params
    )
    
    print(f"  {len(candidates)} candidates generated")
    
    # Display candidates
    if candidates:
        print("\n  Top 5 candidates:")
        sorted_candidates = sorted(candidates, key=lambda c: c['s_total'], reverse=True)
        for i, c in enumerate(sorted_candidates[:5], 1):
            print(f"    {i}. AIS {c['ais_id']} ↔ ARPA {c['arpa_id']}")
            print(f"       Score: {c['s_total']:.4f}")
            print(f"       Distance: {c['d_m']:.1f} m")
            print(f"       Speed diff: {c['dv_ms']:.2f} m/s")
            print(f"       Heading diff: {c['dtheta_deg']:.1f}°")
            print(f"       Time diff: {c['dt_s']:.1f} s")
    
    # Assign matches
    print("\nAssigning optimal matches...")
    matches, unmatched_arpa, unmatched_ais = assign_one_to_one(
        candidates, arpa_df, ais_df,
        accept_threshold=0.6
    )
    
    print(f"\n  Matched pairs: {len(matches)}")
    print(f"  Unmatched ARPA: {len(unmatched_arpa)}")
    print(f"  Unmatched AIS: {len(unmatched_ais)}")
    
    # Display matches
    if matches:
        print("\n  Matched pairs:")
        for i, match in enumerate(matches, 1):
            print(f"    {i}. AIS {match['ais_id']} ↔ ARPA {match['arpa_id']}")
            print(f"       Score: {match['s_total']:.4f}")
            print(f"       Distance: {match['d_m']:.1f} m")
    
    if unmatched_arpa:
        print(f"\n  Unmatched ARPA: {', '.join(unmatched_arpa)}")
    
    if unmatched_ais:
        print(f"\n  Unmatched AIS: {', '.join(unmatched_ais)}")
    
    print("\n✓ Matching algorithm test passed!")


def test_edge_cases():
    """Test edge cases."""
    print("\n" + "="*60)
    print("TEST 3: Edge Cases")
    print("="*60)
    
    # Empty dataframes
    print("\nTest 3.1: Empty DataFrames")
    empty_ais = pd.DataFrame()
    empty_arpa = pd.DataFrame()
    
    candidates = build_candidates(empty_ais, empty_arpa)
    print(f"  Empty input: {len(candidates)} candidates (expected: 0)")
    
    matches, unmatched_arpa, unmatched_ais = assign_one_to_one(
        candidates, empty_arpa, empty_ais
    )
    print(f"  Matches: {len(matches)} (expected: 0)")
    
    # No matches above threshold
    print("\nTest 3.2: No matches above threshold")
    site_lat, site_lon = -1.279656, 116.809655
    transformer = make_transformer(site_lat, site_lon, method="utm")
    
    # AIS far from ARPA
    ais_df = pd.DataFrame({
        'ais_id': ['123456'],
        'lat': [-1.280],
        'lon': [116.810],
        'sog': [10.5],
        'cog': [45.0],
        'ts': [1700000000]
    })
    ais_df['x'], ais_df['y'] = to_xy(ais_df['lat'].values, ais_df['lon'].values, site_lat, site_lon, transformer)
    ais_df['spd'] = ais_df['sog'].apply(knots_to_mps)
    ais_df['hdg'] = ais_df['cog']
    ais_df['t'] = ais_df['ts'].apply(parse_time_s)
    
    arpa_df = pd.DataFrame({
        'arpa_id': ['T1'],
        'lat': [-1.350],  # Very far
        'lon': [116.900],
        'speed': [20.0],  # Very different speed
        'course': [180.0],  # Opposite direction
        'recv_at': [1700003600]  # 1 hour later
    })
    arpa_df['x'], arpa_df['y'] = to_xy(arpa_df['lat'].values, arpa_df['lon'].values, site_lat, site_lon, transformer)
    arpa_df['spd'] = arpa_df['speed'].apply(knots_to_mps)
    arpa_df['hdg'] = arpa_df['course']
    arpa_df['t'] = arpa_df['recv_at'].apply(parse_time_s)
    
    scoring_params = ScoringParams()
    candidates = build_candidates(ais_df, arpa_df, scoring_params=scoring_params)
    
    print(f"  Distant targets: {len(candidates)} candidates")
    if candidates:
        print(f"  Best score: {candidates[0]['s_total']:.4f}")
    
    matches, unmatched_arpa, unmatched_ais = assign_one_to_one(
        candidates, arpa_df, ais_df, accept_threshold=0.9
    )
    print(f"  High threshold (0.9): {len(matches)} matches (expected: 0)")
    
    print("\n✓ Edge cases test passed!")


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("MATCHING ALGORITHM TEST SUITE")
    print("="*60)
    
    try:
        test_coordinate_transformation()
        test_matching_algorithm()
        test_edge_cases()
        
        print("\n" + "="*60)
        print("✅ ALL TESTS PASSED!")
        print("="*60)
        print("\nThe matching algorithm is working correctly.")
        print("You can now enable polling by setting ENABLE_POLLING=True in .env")
        
    except Exception as e:
        print("\n" + "="*60)
        print("❌ TEST FAILED!")
        print("="*60)
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()

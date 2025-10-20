"""
Matching Controller - Handle AIS-ARPA matching via API.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

from app.services.clickhouse import clickhouse_service
from app.core.config import settings
from src.matching import ScoringParams, build_candidates, assign_one_to_one
from src.geo import make_transformer, to_xy, parse_time_s, knots_to_mps


class MatchingController:
    """Controller for AIS-ARPA matching operations."""
    
    def __init__(self):
        """Initialize matching controller."""
        self.site_lat = getattr(settings, 'SITE_LAT', -1.279656)
        self.site_lon = getattr(settings, 'SITE_LON', 116.809655)
        self.filter_radius_km = getattr(settings, 'FILTER_RADIUS_KM', 60.0)
        self.projection = getattr(settings, 'PROJECTION', 'EPSG:32650')
        self.gating_distance_m = getattr(settings, 'GATING_DISTANCE_M', 8000.0)
        self.time_gate_s = getattr(settings, 'TIME_GATE_S', 1800.0)
        self.match_threshold = getattr(settings, 'MATCH_THRESHOLD', 0.8)
        
        # Initialize projection
        self.transformer = make_transformer(self.site_lat, self.site_lon, method=self.projection)
        
        # Scoring parameters
        self.scoring_params = ScoringParams(
            pos_sigma_m=getattr(settings, 'POS_SIGMA_M', 500.0),
            spd_sigma_ms=getattr(settings, 'SPD_SIGMA_MS', 3.0),
            hdg_sigma_deg=getattr(settings, 'HDG_SIGMA_DEG', 40.0),
            time_sigma_s=getattr(settings, 'TIME_SIGMA_S', 60.0),
            range_sigma_m=getattr(settings, 'RANGE_SIGMA_M', 1500.0),
            brg_geo_sigma_deg=getattr(settings, 'BEARING_GEO_SIGMA_DEG', 15.0),
            w_range=getattr(settings, 'W_RANGE', 0.15),
            w_brg_geo=getattr(settings, 'W_BRG_GEO', 0.15)
        )
        
        print(f"✓ MatchingController initialized")
        print(f"  Site: ({self.site_lat:.6f}, {self.site_lon:.6f})")
        print(f"  Radius: {self.filter_radius_km} km")
        print(f"  Projection: {self.projection}")
    
    def _calculate_bbox(self, polygon: Optional[List[List[List[float]]]] = None) -> Dict[str, float]:
        """
        Calculate bounding box from polygon or site radius.
        
        Args:
            polygon: GeoJSON polygon coordinates [[[lon, lat], ...]]
            
        Returns:
            Bounding box dict with min/max lat/lon
        """
        import math
        
        if polygon and len(polygon) > 0 and len(polygon[0]) > 0:
            # Extract coordinates from polygon
            coords = polygon[0]  # First ring (outer boundary)
            
            lons = [coord[0] for coord in coords]
            lats = [coord[1] for coord in coords]
            
            return {
                'min_lat': min(lats),
                'max_lat': max(lats),
                'min_lon': min(lons),
                'max_lon': max(lons)
            }
        else:
            # Fallback: use site and radius
            # Approximate: 1 degree ≈ 111 km
            lat_delta = self.filter_radius_km / 111.0
            lon_delta = self.filter_radius_km / (111.0 * math.cos(math.radians(self.site_lat)))
            
            return {
                'min_lat': self.site_lat - lat_delta,
                'max_lat': self.site_lat + lat_delta,
                'min_lon': self.site_lon - lon_delta,
                'max_lon': self.site_lon + lon_delta
            }
    
    def _point_in_polygon(self, lon: float, lat: float, polygon: List[List[List[float]]]) -> bool:
        """
        Check if point is inside polygon using ray casting algorithm.
        
        Args:
            lon: Longitude
            lat: Latitude
            polygon: GeoJSON polygon coordinates [[[lon, lat], ...]]
            
        Returns:
            True if point is inside polygon
        """
        if not polygon or len(polygon) == 0 or len(polygon[0]) == 0:
            return True  # No polygon filter, accept all
        
        coords = polygon[0]  # First ring (outer boundary)
        n = len(coords)
        inside = False
        
        j = n - 1
        for i in range(n):
            xi, yi = coords[i][0], coords[i][1]
            xj, yj = coords[j][0], coords[j][1]
            
            if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
                inside = not inside
            
            j = i
        
        return inside
    
    async def fetch_ais_data(
        self,
        since_minutes: int = 60,
        limit: int = 1000,
        polygon: Optional[List[List[List[float]]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch AIS data from ClickHouse.
        
        Args:
            since_minutes: Fetch data from last N minutes
            limit: Maximum number of records
            polygon: Optional GeoJSON polygon for spatial filter
            
        Returns:
            List of AIS records
        """
        try:
            bbox = self._calculate_bbox(polygon)
            since = datetime.utcnow() - timedelta(minutes=since_minutes)
            
            query = f"""
                SELECT 
                    mmsi,
                    name as ship_name,
                    toFloat64(lat) as lat,
                    toFloat64(lng) as lon,
                    toFloat64(sog) as sog,
                    toFloat64(cog) as cog,
                    toFloat64(heading) as heading,
                    ts,
                    received_at
                FROM css.ais_current FINAL
                WHERE ts > parseDateTimeBestEffort('{since.isoformat()}')
                  AND lat BETWEEN {bbox['min_lat']} AND {bbox['max_lat']}
                  AND lng BETWEEN {bbox['min_lon']} AND {bbox['max_lon']}
                ORDER BY ts DESC
                LIMIT {limit}
            """
            
            result = clickhouse_service.execute_query(query)
            
            if not result:
                return []
            
            # Convert to list of dicts
            ais_data = []
            for row in result:
                try:
                    lat = float(row.get('lat') or 0.0)
                    lon = float(row.get('lon') or 0.0)
                    
                    # Skip if no valid coordinates
                    if lat == 0.0 and lon == 0.0:
                        continue
                    
                    # Apply polygon filter if provided
                    if polygon and not self._point_in_polygon(lon, lat, polygon):
                        continue
                    
                    ais_data.append({
                        'mmsi': str(row.get('mmsi', '')),
                        'ship_name': row.get('ship_name', ''),
                        'lat': lat,
                        'lon': lon,
                        'sog': float(row.get('sog') or 0.0),
                        'cog': float(row.get('cog') or 0.0),
                        'heading': float(row.get('heading') or 0.0),
                        'ts': row.get('ts'),
                        'received_at': row.get('received_at')
                    })
                except (ValueError, TypeError) as e:
                    # Skip invalid records
                    print(f"  ⚠️ Skipping AIS record with invalid data: {e}")
                    continue
            
            return ais_data
            
        except Exception as e:
            print(f"❌ Error fetching AIS data: {e}")
            return []
    
    async def fetch_arpa_data(
        self,
        since_minutes: int = 60,
        limit: int = 1000,
        polygon: Optional[List[List[List[float]]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch ARPA data from ClickHouse.
        
        Args:
            since_minutes: Fetch data from last N minutes
            limit: Maximum number of records
            polygon: Optional GeoJSON polygon for spatial filter
            
        Returns:
            List of ARPA records
        """
        try:
            bbox = self._calculate_bbox(polygon)
            since = datetime.utcnow() - timedelta(minutes=since_minutes)
            
            query = f"""
                SELECT 
                    target,
                    toFloat64(lat) as lat,
                    toFloat64(lng) as lon,
                    toFloat64(speed) as speed,
                    toFloat64(course) as course,
                    toFloat64(distanceNM) as distance_nm,
                    toFloat64(bearing) as bearing,
                    recv_at,
                    received_at
                FROM css.arpa_current FINAL
                WHERE recv_at > parseDateTimeBestEffort('{since.isoformat()}')
                  AND lat BETWEEN {bbox['min_lat']} AND {bbox['max_lat']}
                  AND lng BETWEEN {bbox['min_lon']} AND {bbox['max_lon']}
                ORDER BY recv_at DESC
                LIMIT {limit}
            """
            
            result = clickhouse_service.execute_query(query)
            
            if not result:
                return []
            
            # Convert to list of dicts
            arpa_data = []
            for row in result:
                try:
                    lat = float(row.get('lat') or 0.0)
                    lon = float(row.get('lon') or 0.0)
                    
                    # Skip if no valid coordinates
                    if lat == 0.0 and lon == 0.0:
                        continue
                    
                    # Apply polygon filter if provided
                    if polygon and not self._point_in_polygon(lon, lat, polygon):
                        continue
                    
                    # Handle optional distance_nm
                    distance_nm = row.get('distance_nm')
                    distance_nm_value = float(distance_nm) if distance_nm is not None else None
                    
                    # Handle optional bearing
                    bearing = row.get('bearing')
                    bearing_value = float(bearing) if bearing is not None else None
                    
                    arpa_data.append({
                        'target': str(row.get('target', '')),
                        'lat': lat,
                        'lon': lon,
                        'speed': float(row.get('speed') or 0.0),
                        'course': float(row.get('course') or 0.0),
                        'distance_nm': distance_nm_value,
                        'bearing': bearing_value,
                        'recv_at': row.get('recv_at'),
                        'received_at': row.get('received_at')
                    })
                except (ValueError, TypeError) as e:
                    # Skip invalid records
                    print(f"  ⚠️ Skipping ARPA record with invalid data: {e}")
                    continue
            
            return arpa_data
            
        except Exception as e:
            print(f"❌ Error fetching ARPA data: {e}")
            return []
    
    def _prepare_dataframes(
        self,
        ais_data: List[Dict],
        arpa_data: List[Dict]
    ) -> tuple:
        """
        Prepare DataFrames for matching.
        
        Args:
            ais_data: List of AIS records
            arpa_data: List of ARPA records
            
        Returns:
            Tuple of (ais_df, arpa_df)
        """
        # Build AIS DataFrame
        ais_df = pd.DataFrame(ais_data)
        
        if not ais_df.empty:
            # Add IDs
            ais_df['ais_id'] = ais_df['mmsi']
            
            # Convert to XY (row by row)
            xy_results = []
            for _, row in ais_df.iterrows():
                x, y = to_xy(
                    row['lat'],
                    row['lon'],
                    self.site_lat,
                    self.site_lon,
                    self.transformer
                )
                xy_results.append((x, y))
            
            ais_df['x'] = [r[0] for r in xy_results]
            ais_df['y'] = [r[1] for r in xy_results]
            
            # Convert speeds (matching.py expects 'sog_ms')
            ais_df['sog_ms'] = ais_df['sog'].apply(knots_to_mps)
            
            # Use heading if available, otherwise cog (matching.py expects 'cog_deg')
            ais_df['cog_deg'] = ais_df.apply(
                lambda row: row['heading'] if pd.notna(row['heading']) and row['heading'] != 0 else row['cog'],
                axis=1
            )
            
            # Convert timestamps (matching.py expects 'timestamp_s')
            ais_df['timestamp_s'] = ais_df['ts'].apply(parse_time_s)
        
        # Build ARPA DataFrame
        arpa_df = pd.DataFrame(arpa_data)
        
        if not arpa_df.empty:
            # Add IDs
            arpa_df['arpa_id'] = arpa_df['target']
            
            # Convert to XY (row by row)
            xy_results = []
            for _, row in arpa_df.iterrows():
                x, y = to_xy(
                    row['lat'],
                    row['lon'],
                    self.site_lat,
                    self.site_lon,
                    self.transformer
                )
                xy_results.append((x, y))
            
            arpa_df['x'] = [r[0] for r in xy_results]
            arpa_df['y'] = [r[1] for r in xy_results]
            
            # Convert speeds (matching.py expects 'speed_ms')
            arpa_df['speed_ms'] = arpa_df['speed'].apply(knots_to_mps)
            
            # Use course as heading (matching.py expects 'heading_deg')
            arpa_df['heading_deg'] = arpa_df['course']
            
            # Convert timestamps (matching.py expects 'timestamp_s')
            arpa_df['timestamp_s'] = arpa_df['recv_at'].apply(parse_time_s)
            
            # Add range/bearing measurements if available
            if 'distance_nm' in arpa_df.columns:
                arpa_df['r_meas_m'] = arpa_df['distance_nm'].apply(
                    lambda x: x * 1852.0 if pd.notna(x) else np.nan
                )
            
            if 'bearing' in arpa_df.columns:
                arpa_df['brg_meas_deg'] = arpa_df['bearing']
        
        return ais_df, arpa_df
    
    async def process_matching(
        self,
        polygon: Optional[List[List[List[float]]]] = None,
        since_minutes: int = 60,
        ais_limit: int = 1000,
        arpa_limit: int = 1000
    ) -> Dict[str, Any]:
        """
        Process AIS-ARPA matching.
        
        Args:
            polygon: Optional GeoJSON polygon for spatial filter
            since_minutes: Fetch data from last N minutes
            ais_limit: Maximum AIS records to fetch
            arpa_limit: Maximum ARPA records to fetch
            
        Returns:
            Dict with matching results
        """
        try:
            start_time = datetime.utcnow()
            
            # Fetch data
            if polygon:
                print(f"📊 Fetching data within polygon (last {since_minutes} minutes)...")
            else:
                print(f"📊 Fetching data (last {since_minutes} minutes)...")
            
            ais_data = await self.fetch_ais_data(since_minutes, ais_limit, polygon)
            arpa_data = await self.fetch_arpa_data(since_minutes, arpa_limit, polygon)
            
            print(f"  AIS: {len(ais_data)} records")
            print(f"  ARPA: {len(arpa_data)} records")
            
            if not ais_data or not arpa_data:
                return {
                    "success": True,
                    "message": "Insufficient data for matching",
                    "data": {
                        "matched_pairs": [],
                        "unmatched_ais": [],
                        "unmatched_arpa": [],
                        "statistics": {
                            "total_ais": len(ais_data),
                            "total_arpa": len(arpa_data),
                            "matched": 0,
                            "unmatched_ais": len(ais_data),
                            "unmatched_arpa": len(arpa_data)
                        }
                    },
                    "timestamp": datetime.utcnow().isoformat()
                }
            
            # Prepare DataFrames
            print("🔄 Preparing data for matching...")
            ais_df, arpa_df = self._prepare_dataframes(ais_data, arpa_data)
            
            # Build candidates
            print("🔍 Building candidates...")
            candidates = build_candidates(
                ais_df,
                arpa_df,
                gating_distance_m=self.gating_distance_m,
                time_gate_s=self.time_gate_s,
                scoring_params=self.scoring_params
            )
            
            print(f"  {len(candidates)} candidates generated")
            
            # Handle case when no candidates
            if len(candidates) == 0:
                print("  ⚠️ No candidates passed gating criteria")
                print(f"     Gating distance: {self.gating_distance_m}m")
                print(f"     Time gate: {self.time_gate_s}s")
                
                return {
                    "success": True,
                    "message": "No matching candidates found within gating parameters",
                    "data": {
                        "matched_pairs": [],
                        "unmatched_ais": ais_data,
                        "unmatched_arpa": arpa_data,
                        "statistics": {
                            "total_ais": len(ais_data),
                            "total_arpa": len(arpa_data),
                            "matched": 0,
                            "unmatched_ais": len(ais_data),
                            "unmatched_arpa": len(arpa_data),
                            "candidates_generated": 0
                        },
                        "parameters": {
                          "since_minutes": since_minutes,
                          "gating_distance_m": self.gating_distance_m,
                          "time_gate_s": self.time_gate_s,
                          "match_threshold": self.match_threshold,
                          "filter_radius_km": self.filter_radius_km,
                          "polygon_provided": polygon is not None,
                          "bbox": self._calculate_bbox(polygon)
                      }
                    },
                    "timestamp": datetime.utcnow().isoformat()
                }
            
            # Assign matches
            print("🎯 Assigning optimal matches...")
            matches, unmatched_arpa_ids = assign_one_to_one(
                candidates,
                arpa_df,
                ais_df,
                accept_threshold=self.match_threshold
            )
            
            # Calculate unmatched AIS IDs
            matched_ais_ids = {m['ais_id'] for m in matches}
            all_ais_ids = set(ais_df['ais_id'].tolist())
            unmatched_ais_ids = list(all_ais_ids - matched_ais_ids)
            
            print(f"  ✓ {len(matches)} matched pairs")
            print(f"  ✓ {len(unmatched_arpa_ids)} unmatched ARPA")
            print(f"  ✓ {len(unmatched_ais_ids)} unmatched AIS")
            
            # Build candidate lookup for detailed features
            candidate_lookup = {}
            for c in candidates:
                key = (c['arpa_id'], c['ais_id'])
                candidate_lookup[key] = c
            
            # Build response
            matched_pairs = []
            for match in matches:
                arpa_id = match['arpa_id']
                ais_id = match['ais_id']
                
                # Get original records
                ais_record = next((r for r in ais_data if str(r['mmsi']) == str(ais_id)), None)
                arpa_record = next((r for r in arpa_data if str(r['target']) == str(arpa_id)), None)
                
                # Look up detailed candidate features
                candidate = candidate_lookup.get((arpa_id, ais_id), {})
                
                matched_pairs.append({
                    "arpa_id": arpa_id,
                    "ais_id": ais_id,
                    "score": float(match['score']),
                    "distance_m": float(candidate.get('d_m', 0)),
                    "speed_diff_ms": float(candidate.get('dv_ms', 0)),
                    "heading_diff_deg": float(candidate.get('dtheta_deg', 0)),
                    "time_diff_s": float(candidate.get('dt_s', 0)),
                    "ais": ais_record,
                    "arpa": arpa_record,
                    "features": {
                        "d_m": float(candidate.get('d_m', 0)),
                        "dv_ms": float(candidate.get('dv_ms', 0)),
                        "dtheta_deg": float(candidate.get('dtheta_deg', 0)),
                        "dt_s": float(candidate.get('dt_s', 0)),
                        "s_pos": float(candidate.get('s_pos', 0)),
                        "s_spd": float(candidate.get('s_spd', 0)),
                        "s_hdg": float(candidate.get('s_hdg', 0)),
                        "s_time": float(candidate.get('s_time', 0)),
                        "s_range": float(candidate.get('s_range', 1.0)),
                        "s_brg": float(candidate.get('s_brg', 1.0))
                    }
                })
            
            # Get unmatched records
            unmatched_ais = [
                r for r in ais_data if str(r['mmsi']) in unmatched_ais_ids
            ]
            
            unmatched_arpa = [
                r for r in arpa_data if str(r['target']) in unmatched_arpa_ids
            ]
            
            elapsed_time = (datetime.utcnow() - start_time).total_seconds()
            
            geojson = self.build_geojson(matched_pairs)
            
            
            return {
                "success": True,
                "message": f"Matching completed successfully in {elapsed_time:.2f}s",
                "data": {
                    "matched_pairs": matched_pairs,
                    "unmatched_ais": unmatched_ais,
                    "unmatched_arpa": unmatched_arpa,
                    "statistics": {
                        "total_ais": len(ais_data),
                        "total_arpa": len(arpa_data),
                        "matched": len(matches),
                        "unmatched_ais": len(unmatched_ais_ids),
                        "unmatched_arpa": len(unmatched_arpa_ids),
                        "candidates_generated": len(candidates),
                        "processing_time_s": elapsed_time
                    },
                    "parameters": {
                        "since_minutes": since_minutes,
                        "gating_distance_m": self.gating_distance_m,
                        "time_gate_s": self.time_gate_s,
                        "match_threshold": self.match_threshold,
                        "filter_radius_km": self.filter_radius_km,
                        "polygon_provided": polygon is not None,
                        "bbox": self._calculate_bbox(polygon)
                    },
                    "geojson": geojson
                },
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            print(f"❌ Error in matching process: {e}")
            import traceback
            traceback.print_exc()
            
            return {
                "success": False,
                "message": f"Matching failed: {str(e)}",
                "data": None,
                "timestamp": datetime.utcnow().isoformat()
            }
    
    def build_geojson(self, matched_pairs):
        features = []
        for match in matched_pairs:
            ais = match.get("ais", {})
            arpa = match.get("arpa", {})
            score = match.get("score", 0)
            distance_m = match.get("distance_m", 0)

            # AIS Point
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [ais.get("lon"), ais.get("lat")]
                },
                "properties": {
                    "type": "ais",
                    "mmsi": ais.get("mmsi"),
                    "ship_name": ais.get("ship_name"),
                    "score": score
                }
            })

            # ARPA Point
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [arpa.get("lon"), arpa.get("lat")]
                },
                "properties": {
                    "type": "arpa",
                    "target": arpa.get("target"),
                    "score": score
                }
            })

            # LineString connecting AIS and ARPA
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [ais.get("lon"), ais.get("lat")],
                        [arpa.get("lon"), arpa.get("lat")]
                    ]
                },
                "properties": {
                    "type": "match",
                    "ais_id": ais.get("mmsi"),
                    "arpa_id": arpa.get("target"),
                    "score": score,
                    "distance_m": distance_m,
                    "ship_name": ais.get("ship_name"),
                    "target": arpa.get("target")
                }
            })

        return {
            "type": "FeatureCollection",
            "features": features
        }

# Create singleton instance
matching_controller = MatchingController()

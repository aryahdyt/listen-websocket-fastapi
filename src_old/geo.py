"""
Geo module for coordinate transformations and utilities.
Full implementation with pyproj for accurate projections.
"""
from typing import Any, Union, Tuple
from datetime import datetime
import math
import numpy as np

try:
    from pyproj import Transformer, CRS
    HAS_PYPROJ = True
except ImportError:
    HAS_PYPROJ = False
    Transformer = None
    CRS = None


def make_transformer(site_lat: float, site_lon: float, method: str = "utm") -> Any:
    """
    Create coordinate transformer for projection.
    
    Args:
        site_lat: Site latitude
        site_lon: Site longitude
        method: Projection method (utm, EPSG:32650, etc.)
        
    Returns:
        Transformer object from pyproj
    """
    if not HAS_PYPROJ:
        print("⚠️ pyproj not available, using simple approximation")
        return None
    
    try:
        # WGS84 (lat/lon)
        wgs84 = CRS.from_epsg(4326)
        
        # Determine target projection
        if method.upper() == "UTM":
            # Auto-detect UTM zone from longitude
            zone = int((site_lon + 180) / 6) + 1
            # Determine hemisphere
            hemisphere = 'north' if site_lat >= 0 else 'south'
            # UTM zone CRS
            if hemisphere == 'north':
                epsg_code = 32600 + zone  # Northern hemisphere
            else:
                epsg_code = 32700 + zone  # Southern hemisphere
            target_crs = CRS.from_epsg(epsg_code)
            print(f"✓ Using UTM Zone {zone}{hemisphere[0].upper()}: EPSG:{epsg_code}")
        elif method.upper().startswith("EPSG:"):
            # Use specified EPSG code
            epsg_code = int(method.split(":")[1])
            target_crs = CRS.from_epsg(epsg_code)
            print(f"✓ Using projection: {method}")
        else:
            # Default to UTM auto-detect
            zone = int((site_lon + 180) / 6) + 1
            hemisphere = 'north' if site_lat >= 0 else 'south'
            if hemisphere == 'north':
                epsg_code = 32600 + zone
            else:
                epsg_code = 32700 + zone
            target_crs = CRS.from_epsg(epsg_code)
            print(f"✓ Auto-detected UTM Zone {zone}{hemisphere[0].upper()}: EPSG:{epsg_code}")
        
        # Create transformer from WGS84 to target CRS
        transformer = Transformer.from_crs(wgs84, target_crs, always_xy=True)
        return transformer
        
    except Exception as e:
        print(f"❌ Error creating transformer: {e}")
        return None


def to_xy(
    lat: Union[float, list, np.ndarray],
    lon: Union[float, list, np.ndarray],
    site_lat: float,
    site_lon: float,
    transformer: Any,
    method: str = "utm"
) -> Tuple[Union[float, np.ndarray], Union[float, np.ndarray]]:
    """
    Convert lat/lon to XY coordinates using proper projection.
    
    Args:
        lat: Latitude(s)
        lon: Longitude(s)
        site_lat: Site latitude (reference point, not used if transformer provided)
        site_lon: Site longitude (reference point, not used if transformer provided)
        transformer: Transformer object from make_transformer()
        method: Projection method (fallback if no transformer)
        
    Returns:
        Tuple of (x, y) coordinates in meters
    """
    single_value = False
    # Convert to numpy arrays for consistent handling
    if isinstance(lat, (list, tuple)):
        lat = np.array(lat, dtype=float)
        lon = np.array(lon, dtype=float)
    elif not isinstance(lat, np.ndarray):
        lat = np.array([lat], dtype=float)
        lon = np.array([lon], dtype=float)
        single_value = True
    
    # Use transformer if available
    if transformer is not None and HAS_PYPROJ:
        try:
            # pyproj transformer.transform expects (lon, lat) for always_xy=True
            x, y = transformer.transform(lon, lat)
            
            # Return single values or arrays based on input
            if single_value:
                return float(x[0]), float(y[0])
            else:
                return x, y
        except Exception as e:
            print(f"⚠️ Transformer error: {e}, falling back to approximation")
    
    # Fallback: Simple approximation (less accurate)
    # 1 degree latitude ≈ 111.32 km
    # 1 degree longitude ≈ 111.32 km * cos(latitude)
    x = (lon - site_lon) * 111320.0 * np.cos(np.radians(site_lat))
    y = (lat - site_lat) * 111320.0
    
    if single_value:
        return float(x[0]), float(y[0])
    else:
        return x, y


def parse_time_s(timestamp: Any) -> float:
    """
    Parse timestamp to seconds since epoch.
    
    Args:
        timestamp: Timestamp (string, datetime, or float)
        
    Returns:
        Seconds since epoch
    """
    if isinstance(timestamp, str):
        try:
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            return dt.timestamp()
        except Exception:
            return 0.0
    elif isinstance(timestamp, datetime):
        return timestamp.timestamp()
    elif isinstance(timestamp, (int, float)):
        return float(timestamp)
    else:
        return 0.0


def knots_to_mps(knots: Union[float, int]) -> float:
    """
    Convert knots to meters per second.
    
    Args:
        knots: Speed in knots
        
    Returns:
        Speed in meters per second
    """
    try:
        return float(knots) * 0.514444
    except (TypeError, ValueError):
        return 0.0

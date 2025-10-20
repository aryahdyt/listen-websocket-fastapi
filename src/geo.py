from __future__ import annotations

from typing import Tuple, Optional
import math
import pandas as pd

try:
    from pyproj import Transformer
except Exception:
    Transformer = None  # type: ignore


def knots_to_mps(knots: float) -> float:
    return float(knots) * 0.514444 if pd.notna(knots) else 0.0


def parse_time_s(ts: Optional[str]) -> float:
    """Parse time string to epoch seconds (naive). Returns 0.0 if invalid."""
    if ts is None:
        return 0.0
    try:
        t = pd.to_datetime(ts)
        # pandas Timestamp has .value in ns
        return float(t.value) / 1e9
    except Exception:
        return 0.0


def compute_origin(lat_series: pd.Series, lon_series: pd.Series) -> Tuple[float, float]:
    """Compute a sensible origin for local projection (mean lat/lon)."""
    lat0 = float(lat_series.mean())
    lon0 = float(lon_series.mean())
    return lat0, lon0


def latlon_to_xy_m(lat: float, lon: float, lat0: float, lon0: float) -> Tuple[float, float]:
    """
    Convert lat/lon (deg) to local x,y meters using an equirectangular approximation
    around (lat0, lon0). Suitable for regional scales (< ~100 km).
    """
    # meters per degree latitude ~ constant
    m_per_deg_lat = 111_320.0
    # meters per degree longitude depends on latitude
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(lat0))
    x = (lon - lon0) * m_per_deg_lon
    y = (lat - lat0) * m_per_deg_lat
    return float(x), float(y)


def utm_epsg_for_latlon(lat: float, lon: float) -> int:
    """Return EPSG code for WGS84 UTM zone based on lat/lon."""
    zone = int((lon + 180.0) // 6.0) + 1
    if lat >= 0:
        return 32600 + zone  # Northern hemisphere
    else:
        return 32700 + zone  # Southern hemisphere


def make_transformer(lat0: float, lon0: float, method: str = "utm"):
    """Create a coordinate transformer for given method."""
    if method == "utm" and Transformer is not None:
        epsg = utm_epsg_for_latlon(lat0, lon0)
        try:
            return Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
        except Exception:
            return None
    # ENU/equirectangular fallback uses manual function
    return None


def to_xy(lat: float, lon: float, lat0: float, lon0: float, transformer=None, method: str = "utm") -> Tuple[float, float]:
    """Convert lat/lon to meters using provided method. If transformer is None or method is not utm, use equirectangular."""
    if method == "utm" and transformer is not None:
        # pyproj uses (lon, lat) order when always_xy=True
        x, y = transformer.transform(lon, lat)
        return float(x), float(y)
    else:
        return latlon_to_xy_m(lat, lon, lat0, lon0)
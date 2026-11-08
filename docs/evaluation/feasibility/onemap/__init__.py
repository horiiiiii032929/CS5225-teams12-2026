"""FlatSplit 的 OneMap 整合工具包。

為 CS5224 Team 12 的 issue #3（可行性驗證）而建，同時供 #14 / #15 / #19 / #27 重用。
所有設計決策都標註了 2026-10-11 的實測依據。
"""

from .client import OneMapClient, OFFICIAL_LIMIT_PER_MIN, DEFAULT_LIMIT_PER_MIN
from .errors import (AuthError, Blocked, InvalidRequest, NoRouteFound,
                     OneMapError, RateLimited, TokenExpiring, UpstreamError)
from .stations import canonical_key, dedupe_stations, is_station_entry, parse_codes
from .towns import (ROUTABLE_TOWNS, TOWNS, TOWN_COORDS,
                    TOWN_REFERENCE_POINTS, coords)

__all__ = [
    "OneMapClient", "OFFICIAL_LIMIT_PER_MIN", "DEFAULT_LIMIT_PER_MIN",
    "OneMapError", "AuthError", "Blocked", "InvalidRequest", "NoRouteFound",
    "RateLimited", "TokenExpiring", "UpstreamError",
    "canonical_key", "dedupe_stations", "is_station_entry", "parse_codes",
    "ROUTABLE_TOWNS", "TOWNS", "TOWN_COORDS", "TOWN_REFERENCE_POINTS", "coords",
]

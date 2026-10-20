"""Bounded Amap Web Service POI search, geocoding and reverse geocoding.

Amap returns GCJ-02 coordinates.  Every place crossing this boundary is
converted to WGS-84, the coordinate system the itinerary and map projection
use.  The key is read through :mod:`travel_agent.services.amap_client`; it is
never returned, logged or embedded in an error message.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import httpx

from ..config import get_settings
from ..utils.coordinates import gcj02_to_wgs84, wgs84_to_gcj02
from ..utils.log_redaction import install_query_secret_redaction
from ..utils.rate_gate import rate_gate_for
from .amap_client import (
    AMAP_RATE_GATE_KEY,
    AmapResponseError,
    AmapServiceError,
    AmapTimeout,
    amap_api_key,
    amap_min_interval_seconds,
)

# amap takes the key as a query parameter; httpx logs request URLs at INFO.
install_query_secret_redaction()

_POI_PATH = "/v3/place/text"
_GEOCODE_PATH = "/v3/geocode/geo"
_REGEOCODE_PATH = "/v3/geocode/regeo"
_SOURCE_URL = "https://lbs.amap.com/api/webservice/guide/api/search"
_GEO_SOURCE_URL = "https://lbs.amap.com/api/webservice/guide/api/georegeo"

_INFO_MESSAGES = {
    "INVALID_USER_KEY": "高德拒绝了当前 Key；请确认它是 Web 服务 Key，且已启用该服务。",
    "USER_KEY_PLAT_NOMATCH": "高德 Key 的平台类型不匹配；Web 服务请求需要使用 Web 服务 Key。",
    "INVALID_USER_SCODE": "高德 Key 安全码校验失败，请检查控制台白名单与 Key 绑定。",
    "SERVICE_NOT_AVAILABLE": "高德账号或服务未开通该接口权限。",
    "INSUFFICIENT_PRIVILEGES": "高德 Key 缺少该接口权限。",
    "DAILY_QUERY_OVER_LIMIT": "高德当日配额已用完，请稍后重试或检查账户配额。",
    "ACCESS_TOO_FREQUENT": "高德请求过于频繁，请降低调用频率。",
    "CUQPS_HAS_EXCEEDED_THE_LIMIT": "高德并发配额已超限，请稍后重试。",
    "INVALID_PARAMS": "高德拒绝了请求参数，请检查地址、城市或坐标。",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any) -> str:
    if isinstance(value, list):
        return ""
    return str(value or "").strip()


def _location(value: Any) -> Tuple[Optional[float], Optional[float]]:
    """Parse amap's ``lon,lat`` string without inventing a point."""

    if not isinstance(value, str) or "," not in value:
        return None, None
    try:
        longitude, latitude = (float(part) for part in value.split(",", 1))
    except ValueError:
        return None, None
    if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
        return None, None
    converted_longitude, converted_latitude = gcj02_to_wgs84(longitude, latitude)
    return converted_longitude, converted_latitude


def _status(payload: Dict[str, Any]) -> None:
    if str(payload.get("status") or "") == "1":
        return
    info = str(payload.get("info") or "UNKNOWN")
    infocode = str(payload.get("infocode") or "")
    message = _INFO_MESSAGES.get(info, "高德拒绝了本次查询")
    raise AmapResponseError(message, info=info, infocode=infocode)


async def _get(
    path: str,
    params: Dict[str, Any],
    client: Optional[httpx.AsyncClient],
) -> Dict[str, Any]:
    settings = get_settings().routing
    owns_client = client is None
    resolved = client or httpx.AsyncClient(
        timeout=settings.timeout_seconds,
        headers={"User-Agent": settings.user_agent},
    )
    try:
        await rate_gate_for(AMAP_RATE_GATE_KEY).acquire(amap_min_interval_seconds())
        response = await resolved.get(
            f"{settings.amap_base_url.rstrip('/')}{path}",
            params=params,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.TimeoutException as exc:
        raise AmapTimeout("高德服务请求超时") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise AmapServiceError("高德服务暂时不可用") from exc
    finally:
        if owns_client:
            await resolved.aclose()
    if not isinstance(payload, dict):
        raise AmapServiceError("高德返回了无效响应")
    _status(payload)
    return payload


def _poi(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    name = _text(row.get("name"))
    poi_id = _text(row.get("id"))
    if not name:
        return None
    longitude, latitude = _location(row.get("location"))
    if not poi_id:
        poi_id = hashlib.sha1(
            f"{name}|{row.get('adcode')}|{row.get('location')}".encode("utf-8")
        ).hexdigest()[:16]
    typecode = _text(row.get("typecode"))
    return {
        "place_id": f"amap:{poi_id}",
        "amap_poi_id": poi_id,
        "name": name,
        "address": _text(row.get("address")),
        "latitude": latitude,
        "longitude": longitude,
        "city": _text(row.get("cityname")),
        "district": _text(row.get("adname")),
        "province": _text(row.get("pname")),
        "adcode": _text(row.get("adcode")),
        "typecode": typecode,
        "type": _text(row.get("type")),
        "business_area": _text(row.get("business_area")),
        "provider": "amap",
        "provider_place_type": _amap_place_type_label(
            typecode, _text(row.get("type"))
        ),
        "provider_country_code": "CN",
        "coordinate_system": "WGS84",
        "raw_coordinate_system": "GCJ-02",
        "raw_location": _text(row.get("location")),
        "confidence_status": (
            "provider_returned" if latitude is not None else "provider_returned_without_coordinates"
        ),
        "source_url": _SOURCE_URL,
        "retrieved_at": _now(),
    }


def _amap_place_type_label(typecode: str, raw_type: str) -> str:
    """Project an amap typecode to the admission marker the worker expects.

    Candidate admission decides dining/lodging domains from this string, not
    from the numeric code; a bare ``050101`` would look like a visit.
    """

    code = (typecode or "").split("|")[0]
    if code.startswith("050"):
        label = "餐饮服务·餐厅"
    elif code.startswith("100"):
        label = "住宿服务·酒店"
    elif code.startswith("110"):
        label = "风景名胜·景点"
    elif code.startswith("060"):
        label = "购物服务·商场"
    else:
        label = raw_type or "amap POI"
    return f"{label}（amap typecode {code or 'unknown'}）"


def _geocode(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    formatted = _text(row.get("formatted_address"))
    if not formatted:
        return None
    longitude, latitude = _location(row.get("location"))
    adcode = _text(row.get("adcode"))
    place_id = f"amap:geocode:{adcode or 'unknown'}:{row.get('location') or ''}"
    return {
        "place_id": place_id,
        "amap_geocode_id": hashlib.sha1(place_id.encode("utf-8")).hexdigest()[:16],
        "name": formatted,
        "address": formatted,
        "latitude": latitude,
        "longitude": longitude,
        "city": _text(row.get("city")),
        "district": _text(row.get("district")),
        "province": _text(row.get("province")),
        "adcode": adcode,
        "level": _text(row.get("level")),
        "provider": "amap",
        "provider_place_type": "geocode",
        "provider_country_code": "CN",
        "coordinate_system": "WGS84",
        "raw_coordinate_system": "GCJ-02",
        "raw_location": _text(row.get("location")),
        "confidence_status": (
            "provider_returned" if latitude is not None else "provider_returned_without_coordinates"
        ),
        "source_url": _GEO_SOURCE_URL,
        "retrieved_at": _now(),
    }


async def amap_poi_search(
    *,
    keywords: str,
    city: Optional[str] = None,
    types: Optional[str] = None,
    limit: int = 8,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    radius: Optional[int] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Search real Amap POIs; an empty result is a success with ``places: []``."""

    query = (keywords or "").strip()
    if not query:
        raise ValueError("keywords is required")
    # amap's text search treats ASCII spaces as a strict multi-term filter; a
    # Chinese phrase such as "杭州 西湖 酒店" then returns zero.  Collapse
    # spaces for CJK queries while leaving Latin queries untouched.
    if re.search(r"[\u4e00-\u9fff]", query):
        query = re.sub(r"\s+", "", query)
    if (latitude is None) != (longitude is None):
        raise ValueError("latitude and longitude must be provided together")
    params: Dict[str, Any] = {
        "key": amap_api_key(),
        "keywords": query,
        "offset": str(max(1, min(int(limit), 10))),
        "page": "1",
        "extensions": "base",
    }
    if city:
        params["city"] = city.strip()
        params["citylimit"] = "true"
    if types:
        params["types"] = types.strip()
    if latitude is not None and longitude is not None:
        gcj_longitude, gcj_latitude = wgs84_to_gcj02(longitude, latitude)
        params["location"] = f"{gcj_longitude:.6f},{gcj_latitude:.6f}"
        if radius is not None:
            params["radius"] = str(max(1, min(int(radius), 50000)))
    payload = await _get(_POI_PATH, params, client)
    places = [
        normalized
        for row in (payload.get("pois") or [])
        if isinstance(row, dict)
        for normalized in [_poi(row)]
        if normalized is not None
    ]
    return {
        "success": True,
        "provider": "amap",
        "provider_api_version": "amap-v3",
        "query": query,
        "count": len(places),
        "places": places,
        "message": "ok" if places else "no_result",
        "source_url": _SOURCE_URL,
        "retrieved_at": _now(),
    }


async def amap_geocode(
    *,
    address: str,
    city: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    query = (address or "").strip()
    if not query:
        raise ValueError("address is required")
    params: Dict[str, Any] = {"key": amap_api_key(), "address": query}
    if city:
        params["city"] = city.strip()
    payload = await _get(_GEOCODE_PATH, params, client)
    places = [
        normalized
        for row in (payload.get("geocodes") or [])
        if isinstance(row, dict)
        for normalized in [_geocode(row)]
        if normalized is not None
    ]
    return {
        "success": True,
        "provider": "amap",
        "provider_api_version": "amap-v3",
        "query": query,
        "count": len(places),
        "places": places,
        "message": "ok" if places else "no_result",
        "source_url": _GEO_SOURCE_URL,
        "retrieved_at": _now(),
    }


async def amap_regeocode(
    *,
    latitude: float,
    longitude: float,
    radius: int = 1000,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    gcj_longitude, gcj_latitude = wgs84_to_gcj02(longitude, latitude)
    payload = await _get(
        _REGEOCODE_PATH,
        {
            "key": amap_api_key(),
            "location": f"{gcj_longitude:.6f},{gcj_latitude:.6f}",
            "extensions": "base",
            "radius": str(max(1, min(int(radius), 3000))),
        },
        client,
    )
    regeocode = payload.get("regeocode") or {}
    component = regeocode.get("addressComponent") or {}
    address = _text(regeocode.get("formatted_address"))
    pois = [
        normalized
        for row in (regeocode.get("pois") or [])
        if isinstance(row, dict)
        for normalized in [_poi(row)]
        if normalized is not None
    ]
    return {
        "success": True,
        "provider": "amap",
        "provider_api_version": "amap-v3",
        "query": {"latitude": latitude, "longitude": longitude},
        "result": {
            "address": address or None,
            "province": _text(component.get("province")),
            "city": _text(component.get("city")),
            "district": _text(component.get("district")),
            "township": _text(component.get("township")),
            "adcode": _text(component.get("adcode")),
            "latitude": latitude,
            "longitude": longitude,
            "pois": pois,
        },
        "message": "ok" if address else "no_result",
        "source_url": _GEO_SOURCE_URL,
        "retrieved_at": _now(),
    }


__all__ = ["amap_geocode", "amap_poi_search", "amap_regeocode"]

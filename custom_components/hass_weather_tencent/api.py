"""API client for the Tencent Maps Weather service."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import re
from typing import Any
from urllib.parse import urlparse

import aiohttp

from .const import (
    ABNORMAL_INT,
    ABNORMAL_STR,
    GET_MD_6,
    TENCENT_WEATHER_API,
    TYPE_FUTURE,
    TYPE_NOW,
    WIND_POWER_TEXT_MAP,
    WIND_SPEED_MAP,
)

_LOGGER = logging.getLogger(__name__)


class TencentWeatherApiError(Exception):
    """Base exception for Tencent Weather API errors."""


class TencentWeatherAuthError(TencentWeatherApiError):
    """Authentication / key / permission error (status 190/199/110/111/112/113)."""


class TencentWeatherConnectionError(TencentWeatherApiError):
    """Network / connection error."""


class TencentWeatherQuotaError(TencentWeatherApiError):
    """Quota / rate-limit error (status 120/121)."""


# Tencent Maps WebService API status codes that indicate a *key* problem
# (invalid key, key not enabled, referer/IP/sig/feature not authorized).
# Reference: https://lbs.qq.com/service/webService/webServiceGuide/status
_AUTH_STATUS_CODES = {
    110,  # 请求来源未被授权
    111,  # 签名验证失败
    112,  # IP未被授权
    113,  # 此功能未被授权
    190,  # 无效的KEY
    199,  # 此key未开启webservice功能
}

# Quota / rate-limit codes — these are NOT auth failures; retrying later
# usually fixes them. Distinct class so the coordinator can surface a
# friendlier message instead of "invalid_key".
_QUOTA_STATUS_CODES = {
    120,  # 此key每秒请求量已达上限
    121,  # 此key每日调用量已达上限
}


class TencentWeatherApiClient:
    """Client for the Tencent Maps Weather API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        key: str,
        secret_key: str | None = None,
    ) -> None:
        """Initialize the API client.

        ``secret_key`` is the WebService SN / 签名校验 Secret Key (SK).
        When set, every request gets a ``sig`` query param per
        https://lbs.qq.com/faq/serverFaq/webServiceKey
        """
        self._session = session
        self._key = key
        self._secret_key = (secret_key or "").strip() or None

    async def async_get_weather_by_adcode(
        self,
        adcode: str,
        *,
        type: str = TYPE_NOW,
        get_md: int = 0,
        added_fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Get weather data by administrative adcode.

        Args:
            adcode: 行政区划代码（市级或区/县级）.
            type: now / future / hours.
            get_md: 0=当天+3天, 1=当天+6天 (only for type=future).
            added_fields: alarm (now), index/air (future).
        """
        params = self._build_params(
            adcode=adcode,
            type=type,
            get_md=get_md,
            added_fields=added_fields,
        )
        return await self._async_request(params)

    async def async_get_weather_by_location(
        self,
        latitude: float,
        longitude: float,
        *,
        type: str = TYPE_NOW,
        get_md: int = 0,
        added_fields: list[str] | None = None,
        convert_coord: bool = True,
    ) -> dict[str, Any]:
        """Get weather data by latitude/longitude.

        Tencent expects location as "latitude,longitude" (纬度在前) and
        interprets it as **GCJ-02 (火星坐标)**. Home Assistant zones and
        the global config store WGS-84 (GPS) coordinates, so by default
        we convert WGS-84 → GCJ-02 before sending. Pass
        ``convert_coord=False`` to send the raw values (e.g. if the
        caller already has GCJ-02).
        """
        if convert_coord:
            latitude, longitude = wgs84_to_gcj02(latitude, longitude)
        params = self._build_params(
            location=f"{latitude},{longitude}",
            type=type,
            get_md=get_md,
            added_fields=added_fields,
        )
        return await self._async_request(params)

    async def async_validate_key(self) -> bool:
        """Validate the API key by making a minimal test request."""
        try:
            await self.async_get_weather_by_adcode(
                "110000",  # 北京市
                type=TYPE_NOW,
            )
            return True
        except TencentWeatherAuthError:
            return False
        except TencentWeatherApiError:
            raise

    def _build_params(
        self,
        *,
        adcode: str | None = None,
        location: str | None = None,
        type: str,
        get_md: int,
        added_fields: list[str] | None,
    ) -> dict[str, Any]:
        """Build the GET query parameter dict for Tencent API.

        Tencent rejects requests that contain both `adcode` and `location`
        (status 351 — mutually exclusive). We therefore only ever set one.
        """
        params: dict[str, Any] = {
            "key": self._key,
            "type": type,
            "output": "json",
        }
        if adcode is not None:
            params["adcode"] = adcode
        elif location is not None:
            params["location"] = location
        else:
            # Should never happen — caller must supply one.
            raise TencentWeatherApiError("adcode 或 location 至少需要一项")
        if type == TYPE_FUTURE:
            params["get_md"] = GET_MD_6 if get_md == GET_MD_6 else 0
        if added_fields:
            params["added_fields"] = ",".join(added_fields)
        return params


    @staticmethod
    def _api_path() -> str:
        """Path used both for the request URL and for SN signing (must match)."""
        return urlparse(TENCENT_WEATHER_API).path or "/ws/weather/v1/"

    def _sign_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Return a copy of params with ``sig`` when Secret Key is configured.

        Per Tencent docs: md5(path + "?" + sorted_raw_query + SK), lowercase.
        Sign with raw (unencoded) values; aiohttp still URL-encodes on send.
        ``sig`` itself is not included in the signed string.
        """
        out = dict(params)
        if not self._secret_key:
            return out
        # Values must be strings of the raw values for stable signing.
        items = sorted((k, "" if v is None else str(v)) for k, v in out.items())
        query = "&".join(f"{k}={v}" for k, v in items)
        raw = f"{self._api_path()}?{query}{self._secret_key}"
        out["sig"] = hashlib.md5(raw.encode("utf-8")).hexdigest()
        return out

    async def _async_request(self, params: dict[str, Any]) -> dict[str, Any]:
        """Make the GET request and return the cleaned `result` payload."""
        params = self._sign_params(params)
        try:
            async with asyncio.timeout(30):
                response = await self._session.get(
                    TENCENT_WEATHER_API, params=params
                )
                response.raise_for_status()
                data = await response.json(content_type=None)
        except asyncio.TimeoutError as err:
            raise TencentWeatherConnectionError(
                "请求腾讯天气API超时"
            ) from err
        except aiohttp.ClientError as err:
            raise TencentWeatherConnectionError(
                f"连接腾讯天气API失败: {err}"
            ) from err

        status = data.get("status")
        if status != 0:
            message = data.get("message", "未知错误")
            if status in _AUTH_STATUS_CODES:
                raise TencentWeatherAuthError(
                    f"腾讯天气API认证失败 (状态码: {status}): {message}"
                )
            if status in _QUOTA_STATUS_CODES:
                raise TencentWeatherQuotaError(
                    f"腾讯天气API配额超限 (状态码: {status}): {message}"
                )
            raise TencentWeatherApiError(
                f"腾讯天气API请求失败 (状态码: {status}): {message}"
            )

        result = data.get("result", {})
        # result may be a dict with realtime/forecast/forecast_hours keys,
        # each of which is a list of objects. Clean abnormal values.
        return self._clean_data(result)

    def _clean_data(self, data: Any) -> Any:
        """Recursively strip Tencent's abnormal sentinel values."""
        if isinstance(data, dict):
            return {k: self._clean_data(v) for k, v in data.items()}
        if isinstance(data, list):
            return [self._clean_data(item) for item in data]
        if data == ABNORMAL_INT:
            return None
        if data == ABNORMAL_STR:
            return None
        return data


def parse_wind_power(wind_power: str | None) -> int | None:
    """Extract the Beaufort level from a wind_power string.

    Tencent returns:
      * Forecast:  "微风" (text), "4-5级", "4级"
      * Realtime:  "4级" (wind_power_v2), "无风"

    For digit-based descriptions we pick the upper bound so the value
    better reflects the worst-case wind in the period. For text-based
    descriptions ("微风" etc.) we look up WIND_POWER_TEXT_MAP.
    """
    if not wind_power:
        return None
    # Try text-based lookup first (covers "微风", "无风", "和风", "清风").
    if wind_power in WIND_POWER_TEXT_MAP:
        return WIND_POWER_TEXT_MAP[wind_power]
    # Match all leading digits (covers "4-5级" -> 5, "4级" -> 4)
    matches = re.findall(r"(\d+)", wind_power)
    if not matches:
        return None
    return max(int(m) for m in matches)


def wind_power_to_speed(wind_power: str | None) -> float | None:
    """Convert a Tencent wind_power string to a km/h value."""
    level = parse_wind_power(wind_power)
    if level is None:
        return None
    return WIND_SPEED_MAP.get(level)


# ----------------------------------------------------------------------
# WGS-84 → GCJ-02 coordinate conversion
# ----------------------------------------------------------------------
# Tencent Maps WebService APIs (including the weather endpoint) interpret
# the `location` parameter as GCJ-02 (火星坐标), the Chinese government's
# mandatory coordinate offset for domestic map data. Home Assistant's
# zones and the global latitude/longitude configuration are sourced from
# GPS / WGS-84. Feeding WGS-84 directly to Tencent causes the point to
# drift by ~50–500 m in mainland China; at border districts or coastal
# areas this drift can push the coordinate out of coverage, returning
# status 393 ("没有符合条件的数据") — which the integration previously
# misreported as an invalid key.
#
# The standard algorithm below is the well-known "eviltransform" /
# GCJ-02 encryption formula. It is deterministic and depends only on the
# input WGS-84 lat/lon. Reference implementation widely published in
# open-source projects.
_PI = math.pi
_A = 6378245.0  # semi-major axis (Krasovsky 1940)
_EE = 0.00669342162296594323  # first eccentricity squared


def _out_of_china(lng: float, lat: float) -> bool:
    """Return True if the point is outside mainland China's bounding box.

    Points outside this box are returned unchanged — Tencent Maps does
    not apply the GCJ-02 offset there, so WGS-84 == GCJ-02 offshore.
    """
    return not (73.66 <= lng <= 135.05 and 3.86 <= lat <= 53.55)


def _transform_lat(x: float, y: float) -> float:
    ret = (
        -100.0
        + 2.0 * x
        + 3.0 * y
        + 0.2 * y * y
        + 0.1 * x * y
        + 0.2 * math.sqrt(abs(x))
    )
    ret += (
        (20.0 * math.sin(6.0 * x * _PI) + 20.0 * math.sin(2.0 * x * _PI)) * 2.0 / 3.0
    )
    ret += (
        (20.0 * math.sin(y * _PI) + 40.0 * math.sin(y / 3.0 * _PI)) * 2.0 / 3.0
    )
    ret += (
        (160.0 * math.sin(y / 12.0 * _PI) + 320 * math.sin(y * _PI / 30.0))
        * 2.0
        / 3.0
    )
    return ret


def _transform_lng(x: float, y: float) -> float:
    ret = (
        300.0
        + x
        + 2.0 * y
        + 0.1 * x * x
        + 0.1 * x * y
        + 0.1 * math.sqrt(abs(x))
    )
    ret += (
        (20.0 * math.sin(6.0 * x * _PI) + 20.0 * math.sin(2.0 * x * _PI)) * 2.0 / 3.0
    )
    ret += (
        (20.0 * math.sin(x * _PI) + 40.0 * math.sin(x / 3.0 * _PI)) * 2.0 / 3.0
    )
    ret += (
        (150.0 * math.sin(x / 12.0 * _PI) + 300.0 * math.sin(x / 30.0 * _PI))
        * 2.0
        / 3.0
    )
    return ret


def wgs84_to_gcj02(lat: float, lng: float) -> tuple[float, float]:
    """Convert WGS-84 (lat, lng) to GCJ-02 (lat, lng).

    Returns the input unchanged for points outside mainland China,
    where GCJ-02 is not applied.
    """
    if _out_of_china(lng, lat):
        return lat, lng
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * _PI
    magic = math.sin(radlat)
    magic = 1 - _EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrtmagic) * _PI)
    dlng = (dlng * 180.0) / (_A / sqrtmagic * math.cos(radlat) * _PI)
    return lat + dlat, lng + dlng

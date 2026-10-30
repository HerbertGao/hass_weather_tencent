"""DataUpdateCoordinator for the Tencent Weather integration.

A single coordinator fetches the three Tencent query types (now / future /
hours) plus the requested added_fields (alarm / index / air), and stores
them under stable keys consumed by the weather entity and sensors.
"""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import (
    TencentWeatherApiClient,
    TencentWeatherApiError,
    TencentWeatherAuthError,
    TencentWeatherConnectionError,
    TencentWeatherQuotaError,
)
from .const import (
    ADDED_AIR,
    ADDED_ALARM,
    ADDED_INDEX,
    CONF_ADCODE,
    CONF_ENABLE_ALERTS,
    CONF_ENABLE_AIR,
    CONF_ENABLE_INDEXES,
    CONF_FORECAST_DAYS,
    CONF_KEY,
    CONF_SECRET_KEY,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_MODE,
    CONF_UPDATE_INTERVAL,
    DEFAULT_FORECAST_DAYS,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    GET_MD_6,
    KEY_AIR_FORECAST,
    KEY_AIR_NOW,
    KEY_ALERTS,
    KEY_FORECAST_HOURS,
    KEY_FORECASTS,
    KEY_INDEXES,
    KEY_LOCATION,
    KEY_NOW,
    MODE_ADCODE,
    TYPE_FUTURE,
    TYPE_HOURS,
    TYPE_NOW,
)

_LOGGER = logging.getLogger(__name__)

type TencentWeatherConfigEntry = ConfigEntry[TencentWeatherCoordinator]


class TencentWeatherCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for fetching Tencent Weather data."""

    config_entry: TencentWeatherConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: TencentWeatherConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        self.api = TencentWeatherApiClient(
            session=async_get_clientsession(hass),
            key=config_entry.data[CONF_KEY],
            secret_key=config_entry.data.get(CONF_SECRET_KEY),
        )
        self._mode = config_entry.data[CONF_MODE]
        self._adcode: str | None = config_entry.data.get(CONF_ADCODE)
        self._latitude: float | None = config_entry.data.get(CONF_LATITUDE)
        self._longitude: float | None = config_entry.data.get(CONF_LONGITUDE)

        update_interval = config_entry.options.get(
            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL.total_seconds()
        )
        if isinstance(update_interval, (int, float)):
            update_interval = timedelta(seconds=update_interval)

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{config_entry.entry_id}",
            update_interval=update_interval,
            config_entry=config_entry,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _added_fields_for_now(self) -> list[str]:
        """Compute the added_fields list for the `now` request."""
        opts = self.config_entry.options
        fields: list[str] = []
        if opts.get(CONF_ENABLE_ALERTS, True):
            fields.append(ADDED_ALARM)
        if opts.get(CONF_ENABLE_AIR, True):
            fields.append(ADDED_AIR)
        return fields

    def _added_fields_for_future(self) -> list[str]:
        """Compute the added_fields list for the `future` request."""
        opts = self.config_entry.options
        fields: list[str] = []
        if opts.get(CONF_ENABLE_INDEXES, True):
            fields.append(ADDED_INDEX)
        if opts.get(CONF_ENABLE_AIR, True):
            fields.append(ADDED_AIR)
        return fields

    def _forecast_get_md(self) -> int:
        """Return get_md for the future request (0 or 1)."""
        days = self.config_entry.options.get(
            CONF_FORECAST_DAYS,
            self.config_entry.data.get(CONF_FORECAST_DAYS, DEFAULT_FORECAST_DAYS),
        )
        return GET_MD_6 if days == GET_MD_6 else 0

    async def _fetch(self, type_: str, added: list[str]) -> dict[str, Any]:
        """Dispatch a single API call depending on the configured mode."""
        get_md = self._forecast_get_md() if type_ == TYPE_FUTURE else 0
        if self._mode == MODE_ADCODE and self._adcode:
            return await self.api.async_get_weather_by_adcode(
                self._adcode,
                type=type_,
                get_md=get_md,
                added_fields=added or None,
            )
        if self._latitude is not None and self._longitude is not None:
            return await self.api.async_get_weather_by_location(
                latitude=self._latitude,
                longitude=self._longitude,
                type=type_,
                get_md=get_md,
                added_fields=added or None,
            )
        raise UpdateFailed("未配置有效的位置信息")

    # ------------------------------------------------------------------
    # Main update
    # ------------------------------------------------------------------
    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Tencent Weather API."""
        try:
            now_raw = await self._fetch(TYPE_NOW, self._added_fields_for_now())
            future_raw = await self._fetch(
                TYPE_FUTURE, self._added_fields_for_future()
            )
            hours_raw = await self._fetch(TYPE_HOURS, [])
        except TencentWeatherAuthError as err:
            # 认证失败（Key 无效/未授权）触发 HA 的 reauth 流程，
            # 而不是无限重试。
            raise ConfigEntryAuthFailed(f"API 认证失败: {err}") from err
        except TencentWeatherQuotaError as err:
            raise UpdateFailed(f"API 配额超限: {err}") from err
        except TencentWeatherConnectionError as err:
            raise UpdateFailed(f"连接失败: {err}") from err
        except TencentWeatherApiError as err:
            raise UpdateFailed(f"API 错误: {err}") from err

        # --- Realtime ---
        realtime_list = now_raw.get("realtime") or []
        now_data: dict[str, Any] = {}
        alerts: list[dict[str, Any]] = []
        air_now: dict[str, Any] = {}
        location: dict[str, Any] = {}
        if realtime_list:
            rt = realtime_list[0]
            location = {
                "province": rt.get("province"),
                "city": rt.get("city"),
                "district": rt.get("district"),
                "adcode": rt.get("adcode"),
                "update_time": rt.get("update_time"),
            }
            now_data = rt.get("infos", {}) or {}
            # alarms only present when added_fields=alarm
            alerts = rt.get("alarms") or []
            # air quality only present when added_fields=air
            if isinstance(rt.get("air"), dict):
                air_now = rt["air"]
        elif future_raw.get("forecast"):
            # Fall back to forecast's location info if realtime failed
            fc = future_raw["forecast"][0]
            location = {
                "province": fc.get("province"),
                "city": fc.get("city"),
                "district": fc.get("district"),
                "adcode": fc.get("adcode"),
                "update_time": fc.get("update_time"),
            }

        # --- Forecast daily ---
        forecast_list = future_raw.get("forecast") or []
        forecasts: list[dict[str, Any]] = []
        air_forecast: list[dict[str, Any]] = []
        indexes: list[dict[str, Any]] = []
        if forecast_list:
            fc = forecast_list[0]
            forecasts = fc.get("infos") or []
            # air is a list of {air_date, aqi, ...}
            air_forecast = fc.get("air") or []
            # indexes is a list of {index_date, ids: [...]}
            indexes = fc.get("indexes") or []

        # --- Forecast hourly ---
        forecast_hours_list = hours_raw.get("forecast_hours") or []
        forecast_hours: list[dict[str, Any]] = []
        if forecast_hours_list:
            forecast_hours = forecast_hours_list[0].get("infos") or []

        return {
            KEY_LOCATION: location,
            KEY_NOW: now_data,
            KEY_FORECASTS: forecasts,
            KEY_FORECAST_HOURS: forecast_hours,
            KEY_ALERTS: alerts,
            KEY_INDEXES: indexes,
            KEY_AIR_NOW: air_now,
            KEY_AIR_FORECAST: air_forecast,
        }

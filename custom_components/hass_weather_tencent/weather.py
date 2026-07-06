"""Weather entity for the Tencent Weather integration."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import logging
from typing import Any

from homeassistant.components.weather import (
    Forecast,
    WeatherEntity,
    WeatherEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfLength,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import wind_power_to_speed
from .const import (
    ATTRIBUTION,
    CONF_LOCATION_NAME,
    DOMAIN,
    KEY_ALERTS,
    KEY_AIR_NOW,
    KEY_FORECAST_HOURS,
    KEY_FORECASTS,
    KEY_INDEXES,
    KEY_LOCATION,
    KEY_NOW,
    WIND_BEARING_MAP,
    map_condition,
)
from .coordinator import TencentWeatherCoordinator

_LOGGER = logging.getLogger(__name__)

# Tencent's Beijing timezone offset
_CN_TZ = timezone(timedelta(hours=8))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tencent Weather entity from a config entry."""
    coordinator: TencentWeatherCoordinator = entry.runtime_data
    async_add_entities([TencentWeatherEntity(coordinator, entry)])


class TencentWeatherEntity(
    CoordinatorEntity[TencentWeatherCoordinator], WeatherEntity
):
    """Representation of a Tencent Weather entity."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_attribution = ATTRIBUTION

    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_wind_speed_unit = UnitOfSpeed.KILOMETERS_PER_HOUR
    _attr_native_visibility_unit = UnitOfLength.KILOMETERS
    _attr_native_precipitation_unit = UnitOfPrecipitationDepth.MILLIMETERS

    _attr_supported_features = (
        WeatherEntityFeature.FORECAST_DAILY
        | WeatherEntityFeature.FORECAST_HOURLY
    )

    def __init__(
        self,
        coordinator: TencentWeatherCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the weather entity."""
        super().__init__(coordinator)
        self._entry = entry
        location_name = entry.data.get(CONF_LOCATION_NAME, "腾讯天气")

        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}"
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer="腾讯地图",
            name=f"腾讯天气 - {location_name}",
            configuration_url="https://lbs.qq.com/dev/console/key/manage",
        )

    # ------------------------------------------------------------------
    # Data accessors
    # ------------------------------------------------------------------
    @property
    def _now_data(self) -> dict[str, Any]:
        """Return current weather (infos) data."""
        if self.coordinator.data is None:
            return {}
        return self.coordinator.data.get(KEY_NOW, {}) or {}

    @property
    def _air_now(self) -> dict[str, Any]:
        """Return current air quality data."""
        if self.coordinator.data is None:
            return {}
        return self.coordinator.data.get(KEY_AIR_NOW, {}) or {}

    # ------------------------------------------------------------------
    # WeatherEntity properties
    # ------------------------------------------------------------------
    @property
    def condition(self) -> str | None:
        """Return the current condition."""
        text = self._now_data.get("weather")
        if text is None:
            return None
        result = map_condition(text)
        if result is None:
            _LOGGER.warning(
                "无法映射腾讯天气描述 [%s] 到 HA condition，"
                "请在日志中反馈此文本以便补充映射表",
                text,
            )
        return result

    @property
    def native_temperature(self) -> float | None:
        """Return the temperature."""
        return self._now_data.get("temperature")

    @property
    def humidity(self) -> float | None:
        """Return the humidity."""
        return self._now_data.get("humidity")

    @property
    def native_pressure(self) -> float | None:
        """Return the pressure."""
        return self._now_data.get("air_pressure")

    @property
    def native_wind_speed(self) -> float | None:
        """Return the wind speed.

        Prefer wind_power_v2 (single-level, e.g. "4级") when available;
        fall back to wind_power ("4-5级").
        """
        wind_power = self._now_data.get("wind_power_v2") or self._now_data.get(
            "wind_power"
        )
        return wind_power_to_speed(wind_power, WIND_BEARING_MAP)

    @property
    def wind_bearing(self) -> float | str | None:
        """Return the wind bearing."""
        wind_dir = self._now_data.get("wind_direction")
        if wind_dir is None:
            return None
        return WIND_BEARING_MAP.get(wind_dir, wind_dir)

    @property
    def ozone(self) -> float | None:
        """Return the ozone level.

        Tencent's realtime air payload exposes an `o3` field (μg/m³);
        while not strictly the Dobson Unit HA expects, exposing it here
        is still useful as an approximation for voice assistants.
        """
        return self._air_now.get("o3")

    # ------------------------------------------------------------------
    # Extra state attributes — designed for LLM / voice assistant readability
    # ------------------------------------------------------------------
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes for voice assistants.

        Includes current conditions, AQI breakdown, daily forecast,
        hourly forecast, alerts, and life indexes in a single flat-ish
        JSON-friendly structure that LLM integrations (e.g. Extended
        OpenAI Conversation) can read directly from entity state without
        needing to call the weather.get_forecasts service.
        """
        attrs: dict[str, Any] = {}
        now = self._now_data
        air = self._air_now
        data = self.coordinator.data or {}

        # --- Current conditions (Chinese-text originals, for TTS) ---
        if now.get("weather") is not None:
            attrs["condition_cn"] = now["weather"]
        if now.get("wind_direction") is not None:
            attrs["wind_direction_cn"] = now["wind_direction"]
        if now.get("wind_power") is not None:
            attrs["wind_power"] = now["wind_power"]
        if now.get("wind_power_v2") is not None:
            attrs["wind_power_v2"] = now["wind_power_v2"]
        if now.get("air_pressure") is not None:
            attrs["air_pressure"] = now["air_pressure"]

        # --- Air quality (realtime) ---
        if air:
            if air.get("aqi") is not None:
                attrs["aqi"] = air["aqi"]
                attrs["aqi_level"] = _aqi_level(air["aqi"])
            for k in ("pm25", "pm10", "no2", "o3", "so2", "co"):
                if air.get(k) is not None:
                    attrs[k] = air[k]

        # --- Location & update time ---
        loc = data.get(KEY_LOCATION, {}) or {}
        if loc.get("province"):
            attrs["province"] = loc["province"]
        if loc.get("city"):
            attrs["city"] = loc["city"]
        if loc.get("district"):
            attrs["district"] = loc["district"]
        if loc.get("update_time"):
            attrs["update_time"] = loc["update_time"]

        # --- Daily forecast (compact summary list) ---
        daily_raw = data.get(KEY_FORECASTS, []) or []
        if daily_raw:
            attrs["forecast_daily"] = [
                _summarize_daily(fc, idx) for idx, fc in enumerate(daily_raw)
            ]

        # --- Hourly forecast ---
        hours_raw = data.get(KEY_FORECAST_HOURS, []) or []
        if hours_raw:
            attrs["forecast_hourly"] = [_summarize_hourly(h) for h in hours_raw]

        # --- Weather alerts ---
        alerts = data.get(KEY_ALERTS, []) or []
        if alerts:
            attrs["alerts"] = [
                {
                    "type": a.get("type_name", ""),
                    "level": a.get("level_name", ""),
                    "title": a.get("title", ""),
                    "description": a.get("pub_content", ""),
                }
                for a in alerts
            ]
            top = alerts[0]
            attrs["alert_type"] = top.get("type_name", "")
            attrs["alert_level"] = top.get("level_name", "")
            attrs["alert_title"] = top.get("title", "")

        # --- Life indexes (today only, flattened) ---
        indexes = data.get(KEY_INDEXES, []) or []
        if indexes:
            today_indexes = indexes[0].get("ids") or [] if isinstance(indexes[0], dict) else []
            attrs["life_indexes"] = [
                {
                    "name": i.get("name", ""),
                    "level": i.get("level", ""),
                    "desc": i.get("desc", ""),
                }
                for i in today_indexes
            ]

        return attrs

    # ------------------------------------------------------------------
    # Forecasts
    # ------------------------------------------------------------------
    async def async_forecast_daily(self) -> list[Forecast] | None:
        """Return the daily forecast."""
        if self.coordinator.data is None:
            return None
        forecasts_raw = self.coordinator.data.get(KEY_FORECASTS, []) or []
        if not forecasts_raw:
            return None

        out: list[Forecast] = []
        for fc in forecasts_raw:
            date_str = fc.get("date")
            dt_str = _to_rfc3339_date(date_str)
            if dt_str is None:
                continue

            day = fc.get("day") or {}
            night = fc.get("night") or {}

            cond_text = day.get("weather") or night.get("weather")
            condition = map_condition(cond_text) if cond_text else None

            wind_speed = wind_power_to_speed(day.get("wind_power"), WIND_BEARING_MAP)
            wind_bearing = WIND_BEARING_MAP.get(day.get("wind_direction", ""))

            high = day.get("temperature")
            low = night.get("temperature")

            entry: Forecast = Forecast(
                datetime=dt_str,
                condition=condition,
                native_temperature=high,
                native_templow=low,
                native_wind_speed=wind_speed,
                wind_bearing=wind_bearing,
                humidity=day.get("humidity"),
            )
            out.append(entry)
        return out

    async def async_forecast_hourly(self) -> list[Forecast] | None:
        """Return the hourly forecast."""
        if self.coordinator.data is None:
            return None
        hours_raw = self.coordinator.data.get(KEY_FORECAST_HOURS, []) or []
        if not hours_raw:
            return None

        out: list[Forecast] = []
        for hour in hours_raw:
            hour_str = hour.get("hour")
            dt_str = _to_rfc3339_hour(hour_str)
            if dt_str is None:
                continue

            info = hour.get("info") or {}
            cond_text = info.get("weather")
            condition = map_condition(cond_text) if cond_text else None

            wind_speed = wind_power_to_speed(
                info.get("wind_power"), WIND_BEARING_MAP
            )
            wind_bearing = WIND_BEARING_MAP.get(info.get("wind_direction", ""))

            entry: Forecast = Forecast(
                datetime=dt_str,
                condition=condition,
                native_temperature=info.get("temperature"),
                native_wind_speed=wind_speed,
                wind_bearing=wind_bearing,
            )
            out.append(entry)
        return out


# ----------------------------------------------------------------------
# Module-level helpers
# ----------------------------------------------------------------------
_DAY_LABELS_CN = ["今天", "明天", "后天", "大后天", "第五天", "第六天", "第七天"]


def _aqi_level(aqi: float) -> str:
    """Map an AQI value to a Chinese level description (CN AQI standard)."""
    if aqi <= 50:
        return "优"
    if aqi <= 100:
        return "良"
    if aqi <= 150:
        return "轻度污染"
    if aqi <= 200:
        return "中度污染"
    if aqi <= 300:
        return "重度污染"
    return "严重污染"


def _to_rfc3339_date(date_str: str | None) -> str | None:
    """Convert "YYYY-MM-DD" to an RFC3339 string at 00:00 Beijing time."""
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.replace(tzinfo=_CN_TZ).isoformat()
    except (ValueError, TypeError):
        return None


def _to_rfc3339_hour(hour_str: str | None) -> str | None:
    """Convert "YYYY-MM-DD HH:MM" to an RFC3339 string in Beijing time."""
    if not hour_str:
        return None
    try:
        dt = datetime.strptime(hour_str, "%Y-%m-%d %H:%M")
        return dt.replace(tzinfo=_CN_TZ).isoformat()
    except (ValueError, TypeError):
        # Some payloads may include seconds; try once more
        try:
            dt = datetime.strptime(hour_str, "%Y-%m-%d %H:%M:%S")
            return dt.replace(tzinfo=_CN_TZ).isoformat()
        except (ValueError, TypeError):
            return None


def _summarize_daily(fc: dict[str, Any], idx: int) -> dict[str, Any]:
    """Build a compact, TTS-friendly summary dict for one forecast day."""
    day = fc.get("day") or {}
    night = fc.get("night") or {}
    high = day.get("temperature")
    low = night.get("temperature")
    entry: dict[str, Any] = {
        "date": fc.get("date", ""),
        "day_label": _DAY_LABELS_CN[idx] if idx < len(_DAY_LABELS_CN) else f"第{idx+1}天",
    }
    if day.get("weather"):
        entry["condition_day"] = day["weather"]
    if night.get("weather"):
        entry["condition_night"] = night["weather"]
    if high is not None:
        entry["temperature_high"] = high
    if low is not None:
        entry["temperature_low"] = low
    if day.get("wind_direction"):
        entry["wind_direction_day"] = day["wind_direction"]
    if day.get("wind_power"):
        entry["wind_power_day"] = day["wind_power"]
    if night.get("wind_direction"):
        entry["wind_direction_night"] = night["wind_direction"]
    if night.get("wind_power"):
        entry["wind_power_night"] = night["wind_power"]
    return entry


def _summarize_hourly(h: dict[str, Any]) -> dict[str, Any]:
    """Build a compact summary dict for one forecast hour."""
    info = h.get("info") or {}
    entry: dict[str, Any] = {}
    if h.get("hour"):
        entry["datetime"] = h["hour"]
    if info.get("weather"):
        entry["condition"] = info["weather"]
    if info.get("temperature") is not None:
        entry["temperature"] = info["temperature"]
    if info.get("wind_direction"):
        entry["wind_direction"] = info["wind_direction"]
    if info.get("wind_power"):
        entry["wind_power"] = info["wind_power"]
    return entry

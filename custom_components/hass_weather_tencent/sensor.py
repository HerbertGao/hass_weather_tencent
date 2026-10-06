"""Sensor entities for the Tencent Weather integration.

Provides three families of sensors designed for voice-assistant / LLM
readability:
  * Weather alert sensor     — count + structured alert payload
  * AQI sensor               — realtime air-quality index + breakdown
  * Daily forecast sensors   — one per day, native value is a
                               human-readable summary like "多云 12~20°C"
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTRIBUTION,
    CONF_LOCATION_NAME,
    DOMAIN,
    KEY_AIR_NOW,
    KEY_ALERTS,
    KEY_FORECASTS,
)
from .coordinator import TencentWeatherCoordinator

_LOGGER = logging.getLogger(__name__)

# Day labels (index 0 = today). Tencent supports up to 7-day forecasts (get_md=1).
_DAY_LABELS_CN = [
    "今天", "明天", "后天", "大后天",
    "第五天", "第六天", "第七天",
]
_DAY_KEYS = [
    "forecast_today", "forecast_tomorrow", "forecast_day2",
    "forecast_day3", "forecast_day4", "forecast_day5", "forecast_day6",
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tencent Weather sensor entities from a config entry."""
    coordinator: TencentWeatherCoordinator = entry.runtime_data
    location_name = entry.data.get(CONF_LOCATION_NAME, "腾讯天气")

    entities: list[SensorEntity] = [
        TencentWeatherAlertSensor(coordinator, entry, location_name),
        TencentWeatherAqiSensor(coordinator, entry, location_name),
    ]

    # Daily forecast sensors: 4 for get_md=0, 7 for get_md=1.
    # We always create 7; the ones without data simply return None.
    for day_index in range(7):
        entities.append(
            TencentWeatherDailyForecastSensor(
                coordinator, entry, location_name, day_index
            )
        )

    async_add_entities(entities)


class _TencentBaseSensor(
    CoordinatorEntity[TencentWeatherCoordinator], SensorEntity
):
    """Common base for Tencent sensors."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: TencentWeatherCoordinator,
        entry: ConfigEntry,
        location_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer="腾讯地图",
            name=f"腾讯天气 - {location_name}",
            configuration_url="https://lbs.qq.com/dev/console/key/manage",
        )


class TencentWeatherAlertSensor(_TencentBaseSensor):
    """Sensor entity for weather alerts."""

    _attr_translation_key = "weather_alert"
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(
        self,
        coordinator: TencentWeatherCoordinator,
        entry: ConfigEntry,
        location_name: str,
    ) -> None:
        super().__init__(coordinator, entry, location_name)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_alert"

    @property
    def native_value(self) -> str | None:
        """Return the number of active alerts or 'None'."""
        if self.coordinator.data is None:
            return None
        alerts = self.coordinator.data.get(KEY_ALERTS, []) or []
        if not alerts:
            return "无预警"
        return f"{len(alerts)}条预警"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return detailed alert information."""
        attrs: dict[str, Any] = {}
        if self.coordinator.data is None:
            return attrs
        alerts = self.coordinator.data.get(KEY_ALERTS, []) or []
        attrs["alert_count"] = len(alerts)
        attrs["alerts"] = []
        for i, alert in enumerate(alerts):
            alert_info = {
                "type": alert.get("type_name", "未知"),
                "level": alert.get("level_name", "未知"),
                "title": alert.get("title", ""),
                "description": alert.get("pub_content", ""),
            }
            attrs["alerts"].append(alert_info)
            # Top-level convenience for voice assistants
            if i == 0:
                attrs["alert_type"] = alert.get("type_name", "未知")
                attrs["alert_level"] = alert.get("level_name", "未知")
                attrs["alert_title"] = alert.get("title", "")
        return attrs


class TencentWeatherAqiSensor(_TencentBaseSensor):
    """Sensor entity for Air Quality Index (realtime)."""

    _attr_translation_key = "aqi"
    _attr_device_class = SensorDeviceClass.AQI
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: TencentWeatherCoordinator,
        entry: ConfigEntry,
        location_name: str,
    ) -> None:
        super().__init__(coordinator, entry, location_name)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_aqi"

    @property
    def native_value(self) -> int | None:
        """Return the AQI value."""
        if self.coordinator.data is None:
            return None
        air = self.coordinator.data.get(KEY_AIR_NOW, {}) or {}
        return air.get("aqi")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return detailed air quality data."""
        attrs: dict[str, Any] = {}
        if self.coordinator.data is None:
            return attrs
        air = self.coordinator.data.get(KEY_AIR_NOW, {}) or {}
        for k in ("pm25", "pm10", "no2", "so2", "o3", "co"):
            if air.get(k) is not None:
                attrs[k] = air[k]
        aqi = air.get("aqi")
        if aqi is not None:
            attrs["aqi_level"] = _aqi_level(aqi)
        return attrs


class TencentWeatherDailyForecastSensor(_TencentBaseSensor):
    """Sensor entity for a single day's weather forecast.

    Each instance represents one day (today, tomorrow, ...). The sensor
    state is a human-readable summary like "多云 12~20°C" so voice
    assistants can read it aloud directly.
    """

    _attr_icon = "mdi:weather-partly-cloudy"

    def __init__(
        self,
        coordinator: TencentWeatherCoordinator,
        entry: ConfigEntry,
        location_name: str,
        day_index: int,
    ) -> None:
        super().__init__(coordinator, entry, location_name)
        self._day_index = day_index
        self._attr_translation_key = _DAY_KEYS[day_index]
        self._attr_unique_id = (
            f"{DOMAIN}_{entry.entry_id}_{_DAY_KEYS[day_index]}"
        )

    def _get_forecast_data(self) -> dict[str, Any] | None:
        """Get the forecast data for this day by index."""
        if self.coordinator.data is None:
            return None
        forecasts = self.coordinator.data.get(KEY_FORECASTS, []) or []
        if self._day_index < len(forecasts):
            return forecasts[self._day_index]
        return None

    @property
    def native_value(self) -> str | None:
        """Return a human-readable weather summary for this day.

        Format: "多云 12~20°C" or "晴转多云 8~18°C".
        """
        fc = self._get_forecast_data()
        if fc is None:
            return None
        day = fc.get("day") or {}
        night = fc.get("night") or {}
        text_day = day.get("weather", "")
        text_night = night.get("weather", "")
        high = day.get("temperature")
        low = night.get("temperature")

        if text_day and text_night and text_day != text_night:
            condition_text = f"{text_day}转{text_night}"
        elif text_day:
            condition_text = text_day
        elif text_night:
            condition_text = text_night
        else:
            condition_text = "未知"

        if low is not None and high is not None:
            temp_text = f"{low}~{high}°C"
        elif high is not None:
            temp_text = f"最高{high}°C"
        elif low is not None:
            temp_text = f"最低{low}°C"
        else:
            temp_text = ""

        return f"{condition_text} {temp_text}" if temp_text else condition_text

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return detailed forecast attributes for this day."""
        attrs: dict[str, Any] = {}
        fc = self._get_forecast_data()
        if fc is None:
            return attrs

        if fc.get("date"):
            attrs["date"] = fc["date"]
        attrs["day_label"] = (
            _DAY_LABELS_CN[self._day_index]
            if self._day_index < len(_DAY_LABELS_CN)
            else f"第{self._day_index + 1}天"
        )

        day = fc.get("day") or {}
        night = fc.get("night") or {}

        if day.get("weather"):
            attrs["condition_day"] = day["weather"]
        if night.get("weather"):
            attrs["condition_night"] = night["weather"]
        if day.get("temperature") is not None:
            attrs["temperature_high"] = day["temperature"]
        if night.get("temperature") is not None:
            attrs["temperature_low"] = night["temperature"]
        if day.get("wind_direction"):
            attrs["wind_direction_day"] = day["wind_direction"]
        if day.get("wind_power"):
            attrs["wind_power_day"] = day["wind_power"]
        if night.get("wind_direction"):
            attrs["wind_direction_night"] = night["wind_direction"]
        if night.get("wind_power"):
            attrs["wind_power_night"] = night["wind_power"]
        if day.get("humidity") is not None:
            attrs["humidity_day"] = day["humidity"]
        if night.get("humidity") is not None:
            attrs["humidity_night"] = night["humidity"]
        if fc.get("week"):
            attrs["week"] = fc["week"]

        return attrs


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

"""Config flow for the Tencent Weather integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    TencentWeatherApiClient,
    TencentWeatherApiError,
    TencentWeatherAuthError,
    TencentWeatherConnectionError,
    TencentWeatherQuotaError,
)
from .const import (
    CONF_ADCODE,
    CONF_CITY,
    CONF_DISTRICT,
    CONF_ENABLE_ALERTS,
    CONF_ENABLE_AIR,
    CONF_ENABLE_INDEXES,
    CONF_FORECAST_DAYS,
    CONF_KEY,
    CONF_LATITUDE,
    CONF_LOCATION_NAME,
    CONF_LONGITUDE,
    CONF_MODE,
    CONF_PROVINCE,
    CONF_UPDATE_INTERVAL,
    DEFAULT_FORECAST_DAYS,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    GET_MD_3,
    GET_MD_6,
    MODE_ADCODE,
    MODE_LOCATION,
)

_LOGGER = logging.getLogger(__name__)


class TencentWeatherConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tencent Weather."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._key: str = ""
        self._mode: str = ""
        self._province: str = ""
        self._city: str = ""
        self._district: str = ""
        self._adcode: str = ""
        self._location_name: str = ""
        self._latitude: float = 0.0
        self._longitude: float = 0.0

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step — enter Key and select mode."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._key = user_input[CONF_KEY]
            self._mode = user_input[CONF_MODE]

            session = async_get_clientsession(self.hass)
            client = TencentWeatherApiClient(session=session, key=self._key)
            try:
                valid = await client.async_validate_key()
                if not valid:
                    errors["base"] = "invalid_key"
            except TencentWeatherConnectionError:
                errors["base"] = "cannot_connect"
            except TencentWeatherQuotaError:
                errors["base"] = "quota_exceeded"
            except TencentWeatherApiError:
                errors["base"] = "unknown"

            if not errors:
                if self._mode == MODE_ADCODE:
                    return await self.async_step_adcode()
                return await self.async_step_location()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_KEY): str,
                    vol.Required(CONF_MODE, default=MODE_ADCODE): vol.In(
                        {
                            MODE_ADCODE: "按行政区划代码选择",
                            MODE_LOCATION: "按地点经纬度选择",
                        }
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_adcode(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle adcode (行政区划代码) input step.

        Tencent uses the China National Bureau of Statistics adcode,
        a 6-digit number identifying a province/city/district. The user
        is asked to enter it directly along with a friendly location
        name; the API will validate it.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            self._adcode = str(user_input[CONF_ADCODE]).strip()
            self._province = user_input.get(CONF_PROVINCE, "")
            self._city = user_input.get(CONF_CITY, "")
            self._district = user_input.get(CONF_DISTRICT, "")
            self._location_name = (
                user_input.get(CONF_LOCATION_NAME)
                or self._build_location_name()
                or "腾讯天气"
            )

            if not self._adcode.isdigit() or len(self._adcode) != 6:
                errors["base"] = "invalid_adcode"
            else:
                # Validate by making a `now` request
                session = async_get_clientsession(self.hass)
                client = TencentWeatherApiClient(
                    session=session, key=self._key
                )
                try:
                    raw = await client.async_get_weather_by_adcode(
                        self._adcode, type="now"
                    )
                except TencentWeatherAuthError:
                    errors["base"] = "invalid_key"
                except TencentWeatherConnectionError:
                    errors["base"] = "cannot_connect"
                except TencentWeatherQuotaError:
                    errors["base"] = "quota_exceeded"
                except TencentWeatherApiError as err:
                    # Surface the real Tencent status/message so the
                    # user can tell e.g. "adcode 不存在" from a key issue.
                    _LOGGER.warning(
                        "腾讯天气 adcode 校验失败: %s", err
                    )
                    errors["base"] = "api_error"
                else:
                    # Backfill province/city/district from API response
                    realtime = raw.get("realtime") or []
                    if realtime:
                        rt = realtime[0]
                        self._province = self._province or rt.get("province", "")
                        self._city = self._city or rt.get("city", "")
                        self._district = self._district or rt.get("district", "")

            if not errors:
                await self.async_set_unique_id(
                    f"{DOMAIN}_{self._adcode}"
                )
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"{self._build_location_name()}",
                    data={
                        CONF_KEY: self._key,
                        CONF_MODE: MODE_ADCODE,
                        CONF_ADCODE: self._adcode,
                        CONF_PROVINCE: self._province,
                        CONF_CITY: self._city,
                        CONF_DISTRICT: self._district,
                        CONF_LOCATION_NAME: self._location_name,
                    },
                    options={
                        CONF_FORECAST_DAYS: DEFAULT_FORECAST_DAYS,
                        CONF_ENABLE_ALERTS: True,
                        CONF_ENABLE_INDEXES: True,
                        CONF_ENABLE_AIR: True,
                    },
                )

        return self.async_show_form(
            step_id="adcode",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADCODE): str,
                    vol.Optional(CONF_PROVINCE): str,
                    vol.Optional(CONF_CITY): str,
                    vol.Optional(CONF_DISTRICT): str,
                    vol.Optional(CONF_LOCATION_NAME): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "adcode_hint": "6位行政区划代码，例如 110105 (北京市朝阳区)"
            },
        )

    async def async_step_location(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle location (经纬度) selection step using HA zones."""
        errors: dict[str, str] = {}

        if user_input is not None:
            selected = user_input.get("zone")
            if selected == "__home__":
                self._location_name = "Home"
                self._latitude = self.hass.config.latitude
                self._longitude = self.hass.config.longitude
            elif selected == "__manual__":
                lat = user_input.get(CONF_LATITUDE)
                lon = user_input.get(CONF_LONGITUDE)
                name = user_input.get(CONF_LOCATION_NAME, "自定义位置")
                if lat is not None and lon is not None:
                    self._location_name = name
                    self._latitude = float(lat)
                    self._longitude = float(lon)
                else:
                    errors["base"] = "invalid_location"
            else:
                zone = self.hass.states.get(selected)
                if zone:
                    self._location_name = zone.name
                    self._latitude = zone.attributes.get("latitude", 0.0)
                    self._longitude = zone.attributes.get("longitude", 0.0)
                else:
                    errors["base"] = "invalid_location"

            if not errors:
                if self._latitude == 0.0 and self._longitude == 0.0:
                    errors["base"] = "invalid_location"

            if not errors:
                session = async_get_clientsession(self.hass)
                client = TencentWeatherApiClient(
                    session=session, key=self._key
                )
                try:
                    await client.async_get_weather_by_location(
                        latitude=self._latitude,
                        longitude=self._longitude,
                        type="now",
                    )
                except TencentWeatherAuthError:
                    errors["base"] = "invalid_key"
                except TencentWeatherConnectionError:
                    errors["base"] = "cannot_connect"
                except TencentWeatherQuotaError:
                    errors["base"] = "quota_exceeded"
                except TencentWeatherApiError as err:
                    # Common cases here: status 393 (坐标所在区县无天气
                    # 数据，例如境外/海域) or 348/395 (参数不合法)。
                    # Coordinate-system drift is already handled by the
                    # WGS-84→GCJ-02 conversion inside the client, so any
                    # remaining error is worth surfacing verbatim.
                    _LOGGER.warning(
                        "腾讯天气 location 校验失败 (lat=%s, lon=%s): %s",
                        self._latitude, self._longitude, err
                    )
                    errors["base"] = "no_weather_data"

            if not errors:
                unique = f"{DOMAIN}_{self._latitude}_{self._longitude}"
                await self.async_set_unique_id(unique)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"腾讯天气 - {self._location_name}",
                    data={
                        CONF_KEY: self._key,
                        CONF_MODE: MODE_LOCATION,
                        CONF_LATITUDE: self._latitude,
                        CONF_LONGITUDE: self._longitude,
                        CONF_LOCATION_NAME: self._location_name,
                    },
                    options={
                        CONF_FORECAST_DAYS: DEFAULT_FORECAST_DAYS,
                        CONF_ENABLE_ALERTS: True,
                        CONF_ENABLE_INDEXES: True,
                        CONF_ENABLE_AIR: True,
                    },
                )

        zone_options: dict[str, str] = {
            "__home__": (
                f"Home ({self.hass.config.latitude}, {self.hass.config.longitude})"
            )
        }
        for state in self.hass.states.async_all("zone"):
            lat = state.attributes.get("latitude", "")
            lon = state.attributes.get("longitude", "")
            zone_options[state.entity_id] = f"{state.name} ({lat}, {lon})"
        zone_options["__manual__"] = "手动输入经纬度"

        schema_fields: dict[Any, Any] = {
            vol.Required("zone", default="__home__"): vol.In(zone_options),
            vol.Optional(CONF_LOCATION_NAME): str,
            vol.Optional(CONF_LATITUDE): vol.Coerce(float),
            vol.Optional(CONF_LONGITUDE): vol.Coerce(float),
        }

        return self.async_show_form(
            step_id="location",
            data_schema=vol.Schema(schema_fields),
            errors=errors,
        )

    def _build_location_name(self) -> str:
        """Build a human-friendly location name from province/city/district."""
        parts = [p for p in (self._province, self._city, self._district) if p]
        return "".join(parts)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> TencentWeatherOptionsFlowHandler:
        """Get the options flow for this handler."""
        return TencentWeatherOptionsFlowHandler()


class TencentWeatherOptionsFlowHandler(OptionsFlow):
    """Handle options flow for Tencent Weather."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    CONF_UPDATE_INTERVAL: user_input[CONF_UPDATE_INTERVAL],
                    CONF_FORECAST_DAYS: user_input[CONF_FORECAST_DAYS],
                    CONF_ENABLE_ALERTS: user_input[CONF_ENABLE_ALERTS],
                    CONF_ENABLE_INDEXES: user_input[CONF_ENABLE_INDEXES],
                    CONF_ENABLE_AIR: user_input[CONF_ENABLE_AIR],
                },
            )

        current_interval = self.config_entry.options.get(
            CONF_UPDATE_INTERVAL,
            int(DEFAULT_UPDATE_INTERVAL.total_seconds()),
        )
        current_days = self.config_entry.options.get(
            CONF_FORECAST_DAYS,
            self.config_entry.data.get(CONF_FORECAST_DAYS, DEFAULT_FORECAST_DAYS),
        )
        current_alerts = self.config_entry.options.get(CONF_ENABLE_ALERTS, True)
        current_indexes = self.config_entry.options.get(
            CONF_ENABLE_INDEXES, True
        )
        current_air = self.config_entry.options.get(CONF_ENABLE_AIR, True)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_UPDATE_INTERVAL,
                        default=current_interval,
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=300, max=7200),
                    ),
                    vol.Required(
                        CONF_FORECAST_DAYS,
                        default=int(current_days) if current_days is not None else DEFAULT_FORECAST_DAYS,
                    ): vol.In(
                        {
                            GET_MD_3: "当天+3天",
                            GET_MD_6: "当天+6天",
                        }
                    ),
                    vol.Required(
                        CONF_ENABLE_ALERTS,
                        default=current_alerts,
                    ): bool,
                    vol.Required(
                        CONF_ENABLE_INDEXES,
                        default=current_indexes,
                    ): bool,
                    vol.Required(
                        CONF_ENABLE_AIR,
                        default=current_air,
                    ): bool,
                }
            ),
        )

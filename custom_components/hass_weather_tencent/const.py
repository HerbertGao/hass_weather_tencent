"""Constants for the Tencent Weather integration."""

from datetime import timedelta

DOMAIN = "hass_weather_tencent"

# Configuration keys
CONF_KEY = "key"
CONF_MODE = "mode"
CONF_ADCODE = "adcode"
CONF_LOCATION_NAME = "location_name"
CONF_LATITUDE = "latitude"
CONF_LONGITUDE = "longitude"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_PROVINCE = "province"
CONF_CITY = "city"
CONF_DISTRICT = "district"
CONF_FORECAST_DAYS = "forecast_days"
CONF_ENABLE_ALERTS = "enable_alerts"
CONF_ENABLE_INDEXES = "enable_indexes"
CONF_ENABLE_AIR = "enable_air"

# Mode values
MODE_ADCODE = "adcode"
MODE_LOCATION = "location"

# API
TENCENT_WEATHER_API = "https://apis.map.qq.com/ws/weather/v1/"

# Query type
TYPE_NOW = "now"
TYPE_FUTURE = "future"
TYPE_HOURS = "hours"

# added_fields
ADDED_ALARM = "alarm"
ADDED_INDEX = "index"
ADDED_AIR = "air"

# get_md (forecast days)
GET_MD_3 = 0  # 当天加未来3天
GET_MD_6 = 1  # 当天加未来6天

# Default values
DEFAULT_UPDATE_INTERVAL = timedelta(minutes=15)
DEFAULT_NAME = "腾讯天气"
DEFAULT_FORECAST_DAYS = GET_MD_6

# Coordinator data keys
KEY_LOCATION = "location"
KEY_NOW = "now"
KEY_FORECASTS = "forecasts"
KEY_FORECAST_HOURS = "forecast_hours"
KEY_ALERTS = "alerts"
KEY_INDEXES = "indexes"
KEY_AIR_NOW = "air_now"
KEY_AIR_FORECAST = "air_forecast"

# Platforms
PLATFORMS = ["weather", "sensor"]

# Tencent weather description -> HA condition mapping
# NOTE: The Tencent API doc lists descriptions like "晴", but the actual
# API response uses "晴天" / "阴天" etc. Both forms are mapped here.
# Composite phrases like "晴转多云" are handled by map_condition().
CONDITION_MAP: dict[str, str] = {
    # 晴
    "晴": "sunny",
    "晴天": "sunny",
    # 多云 / 阴
    "多云": "partlycloudy",
    "阴": "cloudy",
    "阴天": "cloudy",
    # 雨
    "阵雨": "rainy",
    "雷阵雨": "lightning-rainy",
    "雷阵雨伴有冰雹": "hail",
    "雨夹雪": "snowy-rainy",
    "小雨": "rainy",
    "中雨": "rainy",
    "大雨": "pouring",
    "暴雨": "pouring",
    "大暴雨": "pouring",
    "特大暴雨": "pouring",
    # 雪
    "阵雪": "snowy",
    "小雪": "snowy",
    "中雪": "snowy",
    "大雪": "snowy",
    "暴雪": "snowy",
    # 雾 / 霾
    "雾": "fog",
    "冻雨": "snowy-rainy",
    "浓雾": "fog",
    "强浓雾": "fog",
    "大雾": "fog",
    "特强浓雾": "fog",
    "霾": "fog",
    "中度霾": "fog",
    "重度霾": "fog",
    "严重霾": "fog",
    # 沙尘
    "沙尘暴": "exceptional",
    "强沙尘暴": "exceptional",
    "浮尘": "exceptional",
    "扬沙": "exceptional",
    # 范围描述
    "小到中雨": "rainy",
    "中到大雨": "rainy",
    "大到暴雨": "pouring",
    "暴雨到大暴雨": "pouring",
    "大暴雨到特大暴雨": "pouring",
    "小到中雪": "snowy",
    "中到大雪": "snowy",
    "大到暴雪": "snowy",
    # 兜底
    "无": "sunny",
    "雨": "rainy",
    "雪": "snowy",
}

# Wind power text -> Beaufort level.
# Tencent forecast returns text like "微风" (no digit), "4-5级", "4级".
# Realtime wind_power_v2 returns single-level like "4级" or "无风".
WIND_POWER_TEXT_MAP: dict[str, int] = {
    "无风": 0,
    "微风": 1,  # forecast 天气用 "微风" 表示 0-1 级
    "和风": 2,
    "清风": 3,
}

# Wind power -> Beaufort level. Tencent returns strings like "4-5级" or "4级".
# We extract the leading number and treat it as the Beaufort scale.
# Wind speed (km/h) approximated from Beaufort scale midpoint.
WIND_SPEED_MAP: dict[int, float] = {
    0: 1.0,    # 无风
    1: 2.0,    # 1级  1-5 km/h
    2: 7.0,    # 2级  6-11
    3: 14.0,   # 3级  12-19
    4: 22.0,   # 4级  20-28
    5: 32.0,   # 5级  29-38
    6: 42.0,   # 6级  39-49
    7: 54.0,   # 7级  50-61
    8: 67.0,   # 8级  62-74
    9: 81.0,   # 9级  75-88
    10: 96.0,  # 10级 89-102
    11: 112.0, # 11级 103-117
    12: 130.0, # 12级 118+
}

# Wind direction (Chinese) -> bearing degrees.
# Tencent returns 8 cardinal directions plus "无持续风向" / "旋转风"
# for variable winds. Those map to None (HA shows no bearing).
WIND_BEARING_MAP: dict[str, float | None] = {
    "北风": 0.0,
    "东北风": 45.0,
    "东风": 90.0,
    "东南风": 135.0,
    "南风": 180.0,
    "西南风": 225.0,
    "西风": 270.0,
    "西北风": 315.0,
    "无持续风向": None,
    "旋转风": None,
}

# Attribution
ATTRIBUTION = "数据来源：腾讯地图天气服务"

# Tencent API abnormal values
ABNORMAL_INT = 999999
ABNORMAL_STR = "暂无"


def map_condition(text: str | None) -> str | None:
    """Map a Tencent weather description to a HA condition.

    Tencent's documented weather-description table is not exhaustive —
    the API can also return composite phrases like ``"晴转多云"`` /
    ``"晴间多云"``. We first look up the exact phrase in
    ``CONDITION_MAP``; on miss we fall back to keyword-based matching
    so that unmapped descriptions resolve to a sensible HA condition
    instead of the misleading ``"exceptional"``.

    Returns ``None`` if the input is empty or no keyword matches.
    """
    if not text:
        return None
    # Exact match first.
    if text in CONDITION_MAP:
        return CONDITION_MAP[text]
    # Keyword-based fallback (order matters — most specific first).
    if "冰雹" in text:
        return "hail"
    if "雷" in text:
        return "lightning-rainy"
    if "沙" in text or "尘" in text:
        return "exceptional"
    if "雪" in text:
        if "雨" in text:
            return "snowy-rainy"
        return "snowy"
    if "暴雨" in text or "大雨" in text or "大暴雨" in text or "特大暴雨" in text:
        return "pouring"
    if "雨" in text:
        return "rainy"
    if "雾" in text or "霾" in text:
        return "fog"
    if "阴" in text:
        return "cloudy"
    if "晴" in text or "云" in text:
        # 晴间多云 / 多云 / 晴转多云 ...
        if "云" in text and "晴" in text:
            return "partlycloudy"
        if "云" in text:
            return "partlycloudy"
        return "sunny"
    return None

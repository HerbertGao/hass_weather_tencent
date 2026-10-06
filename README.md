# 腾讯天气 - Home Assistant 集成 (hass_weather_tencent)

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](#)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

基于 [腾讯地图天气接口](https://lbs.qq.com/service/weatherService/weather) 的 Home Assistant 自定义集成，提供完整的天气实体、空气质量、天气预警、生活指数、多日预报以及为语音助手 / LLM 优化的状态属性。

> 设计参考 [`hass_weather_baidu`](https://github.com/xyzmos/hass_weather_baidu)，结构与命名保持一致以便于迁移和对照。

---

## ✨ 功能特性

- **完整适配 Home Assistant 天气实体接口**
  - 当前天气：温度、湿度、气压、风速、风向、臭氧
  - 原生单位：摄氏度 / hPa / km/h / km / mm
  - 支持 `WeatherEntityFeature.FORECAST_DAILY` / `FORECAST_HOURLY` / `FORECAST_TWICE_DAILY`
  - 实现 `async_forecast_daily` / `async_forecast_hourly` / `async_forecast_twice_daily` 返回 `Forecast` 列表（腾讯预报含独立白天/夜晚数据，`twice_daily` 直接映射）
- **多源数据**：单次更新并行拉取 `now` / `future` / `hours` 三种查询类型
- **附加字段可配置**：通过选项流启用 / 禁用
  - `alarm` 实时天气预警（仅 `type=now`）
  - `index` 生活指数（仅 `type=future`）
  - `air` 实时与预报空气质量
- **预报天数可选**：`当天+3天` 或 `当天+6天`（对应 `get_md=0/1`）
- **双模式定位**
  - 按行政区划代码 `adcode`
  - 按经纬度 `location`（自动选取 Home Assistant `zone` 或 `Home` 坐标）
- **语音助手 / LLM 友好**
  - 天气实体暴露 `extra_state_attributes`：包含当前中文天气描述、AQI 分项、每日 / 每小时预报、预警、生活指数
  - 每日预报传感器 `native_value` 为 `"多云 12~20°C"` 格式，便于 TTS 直接朗读
  - 自动注册 `weather.get_forecast`（单数）服务别名，兼容 Extended OpenAI Conversation 等 LLM 集成
- **诊断支持**：通过 `diagnostics` 平台安全导出（Key 与经纬度自动脱敏）
- **认证失败自动触发 reauth**：Key 失效时 HA 会弹出重新认证流程，无需删除重建配置项
- **兼容 HA 新旧版本**：自动适配 voluptuous（≤2026.5）与 probatio（2026.6+）表单 / 服务 schema，要求 HA ≥ 2024.11

---

## 📦 安装

### 通过 HACS 安装（推荐）

1. 在 HACS 中点击 **Integrations** → 右上角 ⋮ → **Custom repositories**
2. 添加本仓库地址：`https://github.com/xyzmos/hass_weather_tencent`
3. 类别选择 **Integration**，点击 **Add**
4. 在列表中搜索 **腾讯天气 (Tencent Weather)**，点击 **Download**
5. 重启 Home Assistant

### 手动安装

1. 下载本仓库
2. 将 `custom_components/hass_weather_tencent` 目录复制到你的 HA 配置目录下的 `custom_components/` 中
3. 重启 Home Assistant

---

## 🔑 获取腾讯地图 Key

1. 访问 [腾讯位置服务控制台](https://lbs.qq.com/dev/console/key/manage)
2. 创建应用 → 添加 Key → 产品选择 **WebService API**
3. 复制生成的 Key，用于集成配置

> ⚠️ 请确保你的 Key 已开通 **天气服务** 权限（默认开通），并留意每日调用配额。

---

## ⚙️ 配置

1. 进入 **设置 → 设备与服务 → 添加集成**
2. 搜索 **腾讯天气** 或 **Tencent Weather**
3. 选择配置模式：
   - **按行政区划代码**：输入 6 位 `adcode`（如 `110105` 表示北京市朝阳区）
   - **按地点经纬度**：选择 Home Assistant 中已配置的 `zone`（含 `Home`），或手动输入经纬度
4. 完成后可在集成卡片中点击 **配置** 调整以下选项：

| 选项 | 默认 | 说明 |
| --- | --- | --- |
| 更新间隔（秒） | 900 | 300–7200 秒 |
| 预报天数 | 当天+3天 | `get_md=0` 或 `get_md=1` |
| 启用天气预警 | 开启 | 拉取 `alarm` 字段 |
| 启用生活指数 | 开启 | 拉取 `index` 字段 |
| 启用空气质量 | 开启 | 拉取实时与预报 `air` 字段 |

---

## 📡 暴露的实体

### 天气实体（`weather.*`）

- `condition` / `native_temperature` / `humidity` / `native_pressure` / `native_wind_speed` / `wind_bearing` / `ozone`
- `async_forecast_daily`：返回每日预报列表（含 `condition` / `native_temperature` / `native_templow` / `native_wind_speed` / `wind_bearing` / `humidity`）
- `async_forecast_hourly`：返回未来 24 小时预报列表
- `async_forecast_twice_daily`：白天（`is_daytime=true`，12:00）+ 夜晚（`is_daytime=false`，00:00）预报列表
- `extra_state_attributes`（LLM 友好）：
  - `condition_cn` / `wind_direction_cn` / `wind_power` / `air_pressure`
  - `aqi` / `aqi_level` / `pm25` / `pm10` / `no2` / `o3` / `so2` / `co`
  - `province` / `city` / `district` / `update_time`
  - `forecast_daily`（每日摘要列表）
  - `forecast_hourly`（每小时摘要列表）
  - `alerts` / `alert_type` / `alert_level` / `alert_title`
  - `life_indexes`

### 传感器实体（`sensor.*`）

| 实体 | 状态 | 说明 |
| --- | --- | --- |
| 天气预警 | `"3条预警"` / `"无预警"` | 携带 `alerts` 详情 |
| 空气质量指数 | AQI 数值 | 携带 PM2.5 / PM10 / NO₂ / O₃ / SO₂ / CO 与等级 |
| 今天天气预报 | `"多云 12~20°C"` | 携带日 / 夜详细字段 |
| 明天天气预报 / 后天 / 大后天 / ... 第七天 | 同上 | 最多 7 个每日预报传感器 |

---

## 🗣 语音助手 / LLM 集成

本集成针对 [Extended OpenAI Conversation](https://github.com/jukben/ha-extended-openai-conversation) 等 LLM 集成做了如下优化：

1. **每日预报传感器的 `native_value` 为中文摘要**，例如 `sensor.xxx_forecast_tomorrow` 的状态为 `"小雨 15~22°C"`，LLM 可直接朗读
2. **天气实体的 `extra_state_attributes` 包含完整结构化数据**：当前天气、AQI、预警、未来预报与生活指数均以 JSON 友好的扁平结构暴露
3. **自动注册 `weather.get_forecast`（单数）服务**：HA 核心仅注册 `weather.get_forecasts`（复数），部分 LLM 集成调用单数形式会报 `ServiceNotFound`，本集成兼容两者

在 Extended OpenAI Conversation 的 functions 中可直接读取上述实体状态，无需额外的服务调用即可让 LLM 回答 "明天天气怎么样"、"现在有预警吗" 等问题。

---

## 📁 目录结构

```
hass_weather_tencent/
├── .github/workflows/
│   ├── validate.yaml                        # HACS + Hassfest 验证 CI
│   └── release.yaml                         # GitHub Release 自动发布（可选）
├── hacs.json                                # HACS 元数据
├── README.md                                # 本文档
├── INFO.md                                  # HACS 商店简介
├── LICENSE
└── custom_components/
    └── hass_weather_tencent/
        ├── __init__.py                      # 集成入口 + get_forecast 服务注册
        ├── api.py                           # 腾讯地图 API 客户端 + WGS84→GCJ02 转换
        ├── config_flow.py                   # 配置与选项流
        ├── const.py                         # 常量与映射表
        ├── coordinator.py                   # 数据更新协调器
        ├── diagnostics.py                   # 诊断导出
        ├── manifest.json                    # HA 集成清单
        ├── sensor.py                        # 传感器实体（预警 / AQI / 每日预报）
        ├── services.yaml                    # 服务描述（get_forecast）
        ├── strings.json                     # 翻译键
        ├── weather.py                       # 天气实体
        └── translations/
            ├── en.json
            └── zh-Hans.json
```

---

## 🔧 技术细节

### 风力等级换算

腾讯 API 返回的风力字段形如 `"4-5级"`（预报）或 `"4级"`（实时 `wind_power_v2`）。本集成解析其中的数字并取上限作为蒲福风级，再映射为公里 / 小时（参考蒲福风级中位值），用于填充 `native_wind_speed`。

### 天气描述映射

完整覆盖腾讯文档列出的全部天气描述表，映射到 Home Assistant 的 15 种合法 condition 值（`sunny` / `cloudy` / `partlycloudy` / `rainy` / `pouring` / `lightning-rainy` / `hail` / `snowy` / `snowy-rainy` / `fog` / `exceptional` 等）。

### 时间格式

`async_forecast_daily` / `async_forecast_hourly` / `async_forecast_twice_daily` 返回的 `datetime` 字段为 RFC 3339 格式，时区为北京时间（`+08:00`）。`twice_daily` 白天条目取 12:00、夜晚条目取 00:00。

### 坐标系转换

腾讯地图 WebService API（含天气接口）的 `location` 参数期望 **GCJ-02（火星坐标）**，而 Home Assistant 的 `zone` 与全局 `latitude/longitude` 配置来自 GPS / **WGS-84**。直接传 WGS-84 会导致坐标漂移 50–500 米，在边界区县或沿海地区甚至可能落到境外/海域从而返回 `status=393（没有符合条件的数据）`。

本集成在 `api.py` 内置了标准的 WGS-84 → GCJ-02 转换算法（eviltransform / 国测局加密公式），境内坐标自动纠偏，境外坐标（如东京）保持不变。调用方无需感知坐标系差异。

### 状态码识别

腾讯 WebService API 状态码分为三类，本集成对应不同异常：

| 状态码 | 含义 | 抛出异常 |
| --- | --- | --- |
| 0 | 正常 | — |
| 110 / 111 / 112 / 113 / 190 / 199 | Key 无效 / 未授权 / 未开启 WebService | `TencentWeatherAuthError` → 配置流提示 "无效的 Key"，运行期触发 `ConfigEntryAuthFailed` → reauth |
| 120 / 121 | QPS / 每日配额超限 | `TencentWeatherQuotaError` → 提示 "配额超限" |
| 300+ / 500+ | 参数错误 / 服务异常 | `TencentWeatherApiError` → 提示具体错误并写入日志 |

---

## 🐛 常见问题

**Q: 提示 "无效的 Key"**
A: 请检查 Key 是否正确、是否开通了 WebService API 与天气服务权限，以及 IP 白名单是否包含 Home Assistant 服务器的出口 IP。本集成仅当腾讯返回状态码 110/111/112/113/190/199 时才判定为 Key 无效，其余错误会显示更具体的提示。

**Q: `adcode` 模式正常，但 `location` 模式提示错误**
A: 本集成已内置 WGS-84 → GCJ-02 坐标转换，正常情况下不应出现坐标漂移问题。若仍报错，请查看 Home Assistant 日志中的腾讯状态码：393 表示该坐标所在区县暂无天气数据（可能位于边界或海域），建议改用 `adcode` 模式精确指定区县。

**Q: 经纬度模式返回的天气与预期不符**
A: 腾讯 API 经纬度查询返回坐标所在**区县**的天气，若你位于边界地区，建议改用 `adcode` 模式精确定位。

**Q: 每日预报只有 4 天**
A: 在集成选项中将 "预报天数" 切换为 "当天+6天"（即 `get_md=1`）。默认已为当天+6天。

---

## 📄 许可证

MIT License — 详见 [LICENSE](LICENSE)

## 🙏 致谢

- [腾讯位置服务](https://lbs.qq.com/) 提供天气数据
- [`hass_weather_baidu`](https://github.com/xyzmos/hass_weather_baidu) 提供设计参考

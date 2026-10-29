# 设置 → 配置接口的映射

`config.mapping_report()` 生成下表，设置界面“引擎能力与生效位置”区域原样展示，避免出现用户以为
生效、实际没人读取的选项。

| 设置项 | 目标接口 | 状态 | 说明 |
|---|---|---|---|
| `input.schema` | `engine.configure(schema)` | 即时生效 | 真实引擎 `server_ime_engine.Engine`，检查中回读 `state.config` |
| `input.page_size` | `engine.configure(page_size)` | 即时生效 | 1–9；`apply-engine` 与界面保存都验证过 |
| `input.incomplete` | `engine.configure(incomplete)` | 即时生效 | 布尔 |
| `input.learning` | `engine.configure(learning)` | 能力为真时生效 | 当前引擎 `false`，界面不显示开关 |
| `input.double_pinyin_scheme` | `engine.configure(double_pinyin_scheme)` | 能力为真时生效 | 当前未支持 |
| `input.fuzzy` / `input.correction` | `engine.configure(fuzzy/correction)` | 能力为真时生效 | 当前未支持 |
| `panel.layout` | `panel_options()` → `CandidatePanel.set_options()` | 即时生效 | 候选排列方向，缺省 `horizontal`（从左到右同一行）；旧配置缺键也按横向生效 |
| `panel.font_scale` / `max_visible` / `show_page_info` / `show_hints` | `panel_options()` → `CandidatePanel.set_options()` | 即时生效 | 面板字号、条数、页码与提示开关 |
| `punctuation.chinese` / `use_full_width_pairs` | `punctuation.Punctuation` 映射表 | 配置已写入，框架接入后生效 | 平台文档说明“中文标点配置归界面/集成”，提交路径尚未调用 |
| `shortcuts.*` | `keymap-v1`（平台按键层） | 配置已写入，框架接入后生效 | 见 `shortcuts.md` |

## 交给集成任务（platform `fa505f8c`）的两处接线

1. **候选数**：`platform/server_ime/ibus_adapter.py` 构造 `Controller(...)` 时传入
   `config.platform_patch(settings)["page_size"]`。当前 `Controller` 默认 5；引擎侧已经按设置
   生效，因此框架与引擎的页大小可能不一致（面板按快照里的 `page_size` 显示，不会错位）。
   检查用 `tests/test_engine_mapping.py::PlatformMappingTest` 证明传入 3 时快照与分页都按 3 工作。
2. **标点与快捷键**：在按键路径调用 `punctuation.Punctuation.map_char()` 处理中文标点，
   并用 `keymap.resolve(keyval, state)` 决定动作（当前 `Controller.key()` 内的固定分支可保留为默认值）。
   两处都只需读同一个 `settings.json`；未读取时行为与现在完全一致。

## 反向依赖

界面不写平台或引擎的私有文件，只通过：引擎 `Engine().create_session(config=patch)` 与
`session.configure(patch)`；平台 `StateClient`（`GetState`/`SelectCandidate`/`Page`/`SetMode`/信号）。
任何一项失败都转成带中文说明的 `ConfigError`，不会静默降级。

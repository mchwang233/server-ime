# 设置格式 v1

归属 `employee_id: interface`。机器可读定义：`../config/settings-v1.schema.json`；默认值：
`../config/defaults.json`；实现与校验：`../src/ime_interface/config.py`；界面与保存路径：
`../src/ime_interface/settings_ui.py`。

文件位置：`SERVER_IME_CONFIG` > `$XDG_CONFIG_HOME/server-ime/settings.json` > `~/.config/server-ime/settings.json`。
写入为同目录临时文件 + `os.replace`，权限 `0600`；校验失败不写盘，也不会留下半成品。
个人数据（学习）目录：`SERVER_IME_DATA` > `$XDG_DATA_HOME/server-ime` > `~/.local/share/server-ime`，
学习数据在其子目录 `learning/`。

## 字段

| 键 | 类型/范围 | 含义 | 生效位置 |
|---|---|---|---|
| `version` | 必须为 `1` | 格式主版本；其它值拒绝加载并提示“请恢复默认” | — |
| `input.schema` | `full_pinyin`（`double_pinyin` 需 `capabilities.schemas` 声明） | 转换方案 | `engine.configure(schema)` |
| `input.page_size` | 1–9 | 每页候选数 | `engine.configure(page_size)`；平台 `Controller(page_size=…)` |
| `input.incomplete` | bool | 允许不完整拼音取候选 | `engine.configure(incomplete)` |
| `input.learning` | bool | 个人学习；`features.learning=false` 时置 true 被拒 | `engine.configure(learning)`，需明确 `user_data_dir` |
| `input.double_pinyin_scheme` | `null` 或 `capabilities.double_pinyin_schemes` 内的名字（当前真实引擎只有 `ziranma`） | 双拼方案；`null` 表示引擎默认（引擎默认值为 `ziranma`） | `engine.configure(double_pinyin_scheme)` |
| `input.fuzzy.{enabled,rules}` | bool / 数组，规则必须来自 `capabilities.fuzzy_rules` | 模糊音 | `engine.configure(fuzzy)` |
| `input.correction.{enabled,rules}` | bool / 数组，规则必须来自 `capabilities.correction_rules` | 拼音纠错 | `engine.configure(correction)` |
| `punctuation.chinese` | bool | ASCII 标点映射为中文标点 | 界面映射表 + 集成层（待接入） |
| `punctuation.use_full_width_pairs` | bool | 引号/括号使用成对中文标点 | 同上 |
| `shortcuts.*` | `MOD+Key`，`select_digit` 为 `1-9` | 快捷键绑定 | 平台按键层（待接入，见 `shortcuts.md`） |
| `panel.layout` | `horizontal`（缺省）/ `vertical` | 候选排列方向：同一页候选从左到右排一行；`vertical` 只为旧式单列偏好保留 | 候选面板，即时生效 |
| `panel.font_scale` | 0.8–3.0 | 候选面板字号缩放 | 候选面板，即时生效 |
| `panel.max_visible` | 1–9 | 视口宽度预算：一次大约能看几个候选。**不截断候选**，逻辑页大小仍由平台的 `page_size` 决定（缺省 5），一页里多出来的候选靠横向滚动查看 | 候选面板，即时生效 |
| `panel.show_page_info` / `show_hints` | bool | 显示页码 / 快捷键提示 | 候选面板，即时生效 |
| `panel.edge_margin` | 0–64 | 面板距屏幕边缘像素 | 候选面板，即时生效 |
| `ui.language` | `zh_CN` | 界面语言（当前只有中文） | 设置界面 |

## 候选排列与宽度约束（v1，向后兼容）

* 默认 `panel.layout="horizontal"`：同一页候选**从左到右排在同一行**，编号在左、`ime-cell` 之间用细分隔线。
  **旧配置文件没有 `panel.layout` 键**：`validate()` 以默认值为底，因此升级后立即横排，不需要用户改配置；
  文件里已有的未知键仍然原样保留（前向兼容）。
* 显式写 `"vertical"` 可回到旧版单列布局；其它值被拒绝（`bad-enum`，提示可用 `horizontal, vertical`）。
* 宽度不会超出屏幕：面板可用宽度 = `屏幕宽 - 2*panel.edge_margin`。超宽时依次
  1. 压缩候选文字（`max-width-chars` + 末尾省略号，至少保留 2 个字）；
  2. 仍超宽则整行候选放进固定宽度的**单行横向滚动视口**（可见横向滚动条），
     高亮候选自动滚进可见区域；**不减少同屏候选数、不丢弃任何候选**，逻辑页大小、
     候选编号与候选 ID 都不变（`metrics().dropped_for_width` 恒为 `[]`）。
* 视口宽度 = `min(本页候选自然宽度, 屏幕可用宽度 - 滚动条占位, max_visible 宽度预算)`：
  `panel.max_visible=3` 时一页 9 个候选仍然全部渲染（`metrics().ids` 9 项、序号 0–8、
  数字键映射不变），只是视口只显示约 3 个宽、其余横向滚动；`metrics()` 里
  `max_visible` / `viewport_cap` / `page_size` / `page_start` 分开报告，供装配层核对。
  文字省略只影响显示：候选 `id` 与实际提交文本永远是引擎给的完整值（`tests/ui_scenario.py`
  `ellipsized-candidate-keeps-full-id-and-text`、`narrow-360px-last-candidate-clickable-with-full-text`
  用点击回放核对）。
* 辅助信息（状态、页码、序号、注释、快捷键提示）字号随 `font_scale` 放大但有上限，
  避免提示行自己把面板撑出屏幕。

## 能力门控（不展示无法生效的控制项）

`config.Capabilities` 读取真实引擎 `capabilities()`，分两层：

* **能力位** `features.*`：`double_pinyin` / `fuzzy_pinyin` / `correction` / `learning` 为 `false` 时，
  界面**不渲染**对应控件，只在“引擎未支持”区列出说明；把这些键改成非默认值会被校验拒绝（`unsupported-option`）。
* **声明清单** `double_pinyin_schemes` / `fuzzy_rules` / `correction_rules`：方案名与规则名**只能取清单内的值**。
  清单里没有的名字（例如 `mspy`、`not-a-rule`、`mg_mg`）在保存前被拒绝（`bad-enum` / `unknown-rule`），
  重复规则被拒绝（`duplicate-rule`）；能力位为 true 但清单为空时才出现的具名值被拒绝（`undeclared-catalog`）。
  `engine_patch()` 只输出能力为真、且在清单内的键和值，绝不把无效选项传给引擎。
* 夹具 `capabilities-fixture.json` 只打开能力位、**不声明任何清单**，因此它不能证明双拼/模糊音/纠错已实现；
  检查记录中单列为夹具覆盖。

当前真实引擎（`server_ime_engine`，`capabilities.component_version=0.4.0`）声明：
`double_pinyin_schemes=["ziranma"]`；`fuzzy_rules=[c_ch, s_sh, z_zh, f_h, g_k, l_n, l_r, an_ang, en_eng, in_ing]`；
`correction_rules=[gn_ng, mg_ng, iou_iu, uei_ui, uen_un, ue_ve, v_u, on_ong, transpose, delete, insert, substitute]`。
界面据此显示“双拼方案（自然码）”、10 个模糊音规则、12 个纠错规则和个人学习开关。

## 保存路径与失败语义（`settings_ui`）

```python
SettingsWindow(settings, caps, path, on_saved=None, save_handler=None, user_data_dir=None)
```

| 成员 | 签名 | 说明 |
|---|---|---|
| `save_handler` | `save_handler(settings: dict) -> dict`，失败抛 `ConfigError` | 产品装配层提供的回调。**提供时**：由回调完成验证、运行中配置传播与持久化；窗口不写盘、不创建引擎。返回值作为新的规范化 settings。返回值不是 dict → `ConfigError(code="handler-result")`；回调抛出 `ConfigError` 原样上抛，抛出其它异常 → `ConfigError(code="handler-error", message="保存回调失败：…")`。两种情况都不写盘、不提示成功、不触发 `on_saved`。 |
| `on_saved` | `on_saved(settings)` | 保存/恢复默认**成功后**调用；失败不调用。 |
| `user_data_dir` | `str | Path | None` | 无回调时传给 `Engine(user_data_dir=…)`；`None` 时用 `learning_data_dir()`（仅当本次配置开启学习）。 |
| `collect()` | `-> dict` | 控件 → 未校验 settings。 |
| `save()` | `-> bool` | 走 `apply_settings()`；成功 `True`（刷新控件、显示成功、触发 `on_saved`），失败 `False`（红条显示全部错误、控件和文件都不变）。 |
| `reset(close=False)` | `-> dict | False` | 恢复默认，走**同一条** `apply_settings()` 路径（含回调）；成功刷新控件、显示“已恢复默认设置”、触发 `on_saved`；失败返回 `False`。 |
| `refresh_controls(settings)` | `-> None` | 用规范化 settings 回填控件（`_refresh_controls` 为兼容别名）。 |
| `show_errors(errors)` | `-> None` | 显示 `[{code,path,message}]`。 |

模块级统一路径（无 GTK 依赖，可无显示调用）：

```python
ime_interface.settings_ui.apply_settings(settings, path, caps,
                                         save_handler=None, user_data_dir=None, env=None)
    -> (settings, info)          # 失败抛 ConfigError
```

* 有 `save_handler`：先本地 `config.validate`，再把规范化 settings 交给回调；
  `info = {"persisted_by": "save_handler", "engine_patch": …}`，**不写盘、不建引擎**。
* 无 `save_handler`：`info = {"persisted_by": "config.save", "engine_patch": …, "engine_state_config": …, "user_data_dir": …}`；
  顺序固定为 **先应用引擎、后写盘**，因此引擎失败时原配置文件保持不变、界面不报告成功。

引擎应用接口（无回调路径与产品回调都会用）：

```python
ime_interface.config.apply_engine(settings, engine=None, caps=None, user_data_dir=None, env=None)
    -> (patch, state)            # 失败抛 ConfigError(code="engine-<engine code>")
ime_interface.config.learning_data_dir(env=None) -> Path     # …/server-ime/learning
```

`user_data_dir` 显式透传给 `Engine(user_data_dir=…)`；未给出且本次配置开启学习、能力视图来自真实引擎时
使用 `learning_data_dir()`。能力视图来自夹具（`Capabilities.from_file`，`fixture=True`）时**不会**替夹具创建
真实个人目录，兼容旧行为——引擎如实报 `engine-learning_unavailable`。没有个人目录就不会声称学习已生效。

## 前向兼容约定

1. 未知键原样保留（保存时写回），后续引擎/界面增强可直接加键，旧版本不会丢数据。
2. 未知 `version` 一律拒绝，不做猜测式迁移；迁移工具必须显式实现。
3. 新选项必须先进入引擎 `capabilities`（能力位 + 声明清单），再由本格式加键；界面按能力与清单渲染。
4. 删除或改变既有键含义需要升主版本。
5. 旧调用方式继续有效：`SettingsWindow(settings, caps, path, on_saved)`、`save()`/`reset()`/`_refresh_controls`
   名称不变，`config.apply_engine(settings, engine, caps)` 位置参数不变，`config.validate/save/load/reset` 签名不变。

## 错误码

`not-object`、`bad-version`、`unknown-version`、`bad-enum`、`not-integer`、`not-number`、
`not-boolean`、`not-string`、`not-array`、`out-of-range`、`unknown-rule`、`duplicate-rule`、
`undeclared-catalog`、`unsupported-option`、`invalid-json`、`handler-result`、`handler-error`、
`learning-data-dir`、`empty-binding`、`invalid-key`、`invalid-modifier`、`bad-range`、`unsupported-binding`、
`unknown-action`、`conflict`、`engine-<code>`。每条错误都带中文 `message` 与 `path`，
设置界面把全部错误显示在红色提示区并拒绝保存。

## 复现检查

```bash
python3 interface/tools/run_checks.py                       # 单测 + 隔离 X/D-Bus/IBus 界面检查
python3 -m unittest discover -s interface/tests -p 'test_*.py' -v
# 委派复现：真实引擎 + 本包校验（mspy / not-a-rule 在保存前被拒，学习走显式目录）
T=$(mktemp -d); SERVER_IME_CONFIG=$T/settings.json XDG_DATA_HOME=$T/data \
  python3 integration/checks/reproduce_interface.py
```

最近证据：`evidence/run-20261029-123248/`（`summary.json` 五项 PASS；`settings-checks.json` 12/12 PASS；
`unit` 51 项通过）。缺陷复现 `python3 integration/checks/reproduce_interface.py` 现输出：
`mspy` → `bad-enum`（只列出 ziranma）、`not-a-rule` → `unknown-rule`（列出 10 条真实模糊音）、
`learning=true` 无回调时由 `learning_data_dir()` 显式传入 `Engine(user_data_dir=…)` 后被引擎接受（`engine_accepted=true`）。

缺陷回归（`integration/checks/interface-defects.json` 的三类场景、学习目录、回调失败、恢复默认刷新）
分别在 `tests/test_config.py`（`CapabilityCatalogTest`、`LearningDirectoryTest`、`ApplySettingsTest`）
与 `tests/settings_scenario.py`（`save-handler-*`、`reset-uses-handler-*`、`learning-applied-*`）里。

# 快捷键说明与配置

格式：`MOD+Key`，修饰键 `Control`/`Shift`/`Alt`/`Super`（顺序固定，`Control+space`）；数字选词使用区间
`1-9`。解析与校验实现：`../src/ime_interface/keymap.py`。

## 默认绑定（与平台实际实现一致）

| 动作 | 默认 | 平台行为 | 状态 |
|---|---|---|---|
| 中英切换 | `Control+space` | 取消未提交组合后切换中/英 | 平台已实现 |
| 数字选词 | `1-9` | 选择当前页第 N 项，受候选数限制，超出范围按普通字符 | 平台已实现 |
| 上一页 / 下一页 | `Page_Up` / `Page_Down` | 整页移动，边界不循环 | 平台已实现 |
| 上一项 / 下一项 | `Up` / `Down` | 逐项移动选中候选 | 平台已实现 |
| 提交原始拼音 | `Return`（也接受 `KP_Enter`） | 不选词，直接上屏拼音原文 | 平台已实现 |
| 取消输入 | `Escape` | 清空预编辑，不提交 | 平台已实现 |
| 切换焦点 | `Tab` | 先取消组合，再把按键交还应用 | 平台已实现 |

面板内的鼠标操作：左键单击候选=选词；滚轮上/下=上一页/下一页；单击「‹ ›」=翻页；单击中/英徽标=
切换中英。面板底部显示当前绑定的提示文字（`panel.show_hints=false` 可关闭；屏幕过窄时自动隐藏）。

候选默认**横排**（同一页从左到右）：数字 `1`–`9` 对应从左到右的编号；`Up`/`Down` 仍在当前页内
按编号逐项移动高亮（不因横排变成左右）；高亮候选在面板上有浅蓝背景。旧式单列（`panel.layout="vertical"`）
下这些语义完全一致，只是排列方向不同。

## 校验与反馈

保存时 `keymap.validate_shortcuts()` 检查整张表，错误全部带中文说明并阻止写盘：

| 情况 | 错误码 | 中文提示（示例） |
|---|---|---|
| 两个动作绑同一个键 | `conflict` | 快捷键冲突：上一页 与 下一页 都绑定为 Page Up，请只保留一个 |
| 平台不会执行的绑定 | `unsupported-binding` | 下一页 不能绑定为 Ctrl+Page Down；平台按键层当前只执行 Page Down |
| 未知修饰键 | `invalid-modifier` | 未知修饰键 Hyper；可用 Control/Shift/Alt/Super |
| 未知按键 | `invalid-key` | 未知按键“F13”；可用按键：空格/回车/Esc/Tab/方向键/Page Up/Page Down/a–z/1–9 |
| 空绑定 | `empty-binding` | 快捷键不能为空 |
| 数字区间反了 | `bad-range` | 数字区间 9-1 起点大于终点 |
| 未知动作 | `unknown-action` | 未知快捷键动作“teleport” |

## 生效范围（如实）

当前平台按键层只实现上表中的固定绑定，因此**设置界面把这些行显示为“已写入配置，框架接入后生效”**，
并把非默认值当作非法配置拒绝保存，而不是假装生效。`keymap.resolve(keyval, state)` 与平台
`Controller.key()` 的判定顺序一致，`tests/test_engine_mapping.py` 用真实 `Controller` 验证数字选词、
翻页与中英切换的行为，确保默认绑定表和平台实现不会漂移。平台集成任务接上 `keymap-v1` 之后，
这些绑定即可由配置文件驱动；届时只需把 `ACTION_SPECS[...]["accepted"]` 扩展到新按键。

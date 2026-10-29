# 装配接口与归属

employee_id: platform；`verifies: []`。只在同一显式选定的私有 IBus 连接使用接口，不提供网络服务。

| 接口 | 归属 | 产品调用 |
|---|---|---|
| `PlatformSession(config=None, **engine_options)` | engine | 显式传 `user_data_dir=data_dir/learning`；固定 0.4.0/API 1.0，`deterministic=false` |
| `UserStore.record_commit` | lexicon | 仅由 engine 的候选提交事件调用；没有装配层二次学习/重复记账 |
| `Capabilities` / `validate` / `engine_patch` / `save` | interface | 真实能力清单校验；配置事务与 0600 原子落盘 |
| `SettingsWindow(..., save_handler=callback)` | interface | 回调返回 `Client.call('apply', settings=...)['settings']`；失败抛 ConfigError |
| `ProductController` | platform | Binding 精确修饰位匹配、标点、输入/焦点/候选生命周期 |
| `ServerIME.controller_factory` | platform | 可选工厂，原 Controller 为缺省；产品提供受配置管理的 Controller |
| `CandidatePanel` / `ProductPanel` | interface / platform 装配 | 原界面行组件、鼠标/滚轮；装配层提供 live options、光标位置和屏幕边界处理 |
| supervisor / CLI | platform | 启停、进程恢复、受管 IBus、显式应用环境、避免输入内容持久日志 |

`org.superpartner.ServerIME1` 与已有状态服务兼容。快照新增 `cursor_rect` 和 `configuration_revision`。
`cursor_rect=null` 表示未知；否则为 `{x,y,width,height,coordinate_space:"screen"}`。
相同 cursor_rect 不重复发状态，失焦清空。旧 revision 的候选选择会被拒绝。

新服务总线名 `org.freedesktop.IBus.ServerIME`，对象 `/org/freedesktop/IBus/ServerIME/Product`，
接口 `org.superpartner.ServerIME.Product1`：

- `Call(request_json: s) -> response_json: s`，最多 65536 字符。
- 请求 `{"op":"get"}`、`{"op":"apply","settings":{...}}`、`{"op":"reset"}`、
  `{"op":"learning-status"}`、`{"op":"reload-lexicon"}`。
- 成功 `{"ok":true,"result":...}`；失败 `{"ok":false,"errors":[{"code","path","message"}]}`。
- `get/apply/reset.result` 为 `{settings,revision,engine_config,capabilities,config_path,data_dir,backend,deterministic}`。
- `SettingsChanged(view_json:s)`：成功保存后通知面板；所有已存在 Controller 同步更新；新上下文继承新配置。

面板总线名 `org.freedesktop.IBus.ServerIME.Panel`，对象 `/org/freedesktop/IBus/ServerIME/Panel`，
接口 `org.superpartner.ServerIME.Panel1.Geometry() -> s` 返回
`{panel,rows,settings_revision,cursor_rect,context_id,anchored,candidate_presentation,metrics,revision,page_start,page_size}`。
`rows` 保留本页全部候选 ID、逻辑 index 和像素矩形，另含 `selected/in_view/text_w/text_needed/ellipsized`。
视口外候选的坐标可能在面板外；只有 `in_view=true` 才表示该候选完整可见，不能丢掉视口外的 ID。
`metrics.ids/in_view` 分别为本页完整/可见 ID；`metrics.scroll` 为 `value/page_size/upper/scrollable/scrollbar_visible`。
`metrics.viewport/scrollbar` 为真实 GTK 分配的屏幕矩形 `{x,y,w,h}`，控件未映射时返回 null。
`revision/page_start/page_size` 对应当前渲染快照，支持将逻辑页和几何信息逐一核对。
该接口只读、不写文件、不含候选原文；坐标单位为本次 X11 屏幕像素。
横向滚动仅改变当前页视口；数字选词与 Page Up/Down 仍使用平台的逻辑页及完整候选 ID。

配置事务在服务的单个 GLib 线程执行。所有 engine.configure 成功后才保存；保存失败回滚；成功后清空
各上下文旧预编辑并广播配置。崩溃重启以最后落盘配置为准，个人数据由 UserStore 自己持久化。
候选面板进程使用 GTK simple 输入模块（自身无编辑框），防止面板鼠标 grab 抢占应用 IBus 焦点。
使用外部 IBus 时记录原全局引擎并在停止时尝试恢复；外部真实桌面模式未验证，不声称部署完成。

当前 shim 为读取实际状态和 `learning_status/reload_lexicon` 使用 PlatformSession 的 `_session/_engine`。
该封装随 engine 0.4.0 固定版本装配；升级该适配器内部结构时必须同步此 glue，不承诺跨版本私有字段稳定。

## 组合输入增量

产品 0.2.1 消费 `Conversion.literal_digits`；平台按原始光标位置保留 ASCII 大小写及原文符号。
纯拼音末尾的 `, . ? !` 经 `ProductController.commit_sentence` 提交高亮候选及未消费后缀，再调用界面标点映射。
地址/版本的符号、音节单引号、组合中间的编辑和 `KP_Decimal` 原文插入保持独立语义。
状态接口追加同名布尔字段；原有字段、D-Bus 名称、版本检查和配置事务保持兼容。
`ProductController.insert_text(text)` 为内部插入路径，数字小键盘不会触发候选编号选择。
坐标回报只发布状态、移动候选窗，不重复向应用发送预编辑或候选表。
按键语义及歧义处理见 `mixed-input.md`；不接入测试后端或能力夹具。

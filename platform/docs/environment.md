# 环境能力矩阵与本轮边界

employee_id: **platform**。采集日期：2026-10-28，Asia/Shanghai。命令、退出码和完整 stdout/stderr 在 [environment.json](../evidence/environment.json)。本轮事实优先于较早提供的工具说明。

| 能力 | 命令 / 实际结果 | 本轮选择与限制 |
|---|---|---|
| 系统 / 架构 | `cat /etc/os-release`：Rocky Linux 9.8；`uname -srmo`：5.14.0-687.17.1.el9_8.x86_64 | 使用系统 Python/GI，不修改系统包 |
| 运行权限 | `id`：uid 1001 普通用户 | 仅 platform 内输出；不使用 root/user service |
| 现有远程会话 | `loginctl show-session 3`：Type=x11、Display=:2、Remote=yes、Service=tigervnc、State=active、Seat 为空 | 只读 logind 信息；不激活/切换/终止会话 |
| 当前任务环境 | DISPLAY=:2.0、DBUS_SESSION_BUS_ADDRESS 指向 /run/user/1001/bus；WAYLAND_DISPLAY 为空 | 与早期“环境变量为空”说明不同；不使用继承的显示/bus 地址 |
| 宿主桌面可访问性 | 认证文件与 /tmp/.X11-unix 明确受限 | 未连接既有桌面；不通过其他途径读取受限认证数据 |
| 独立显示 | `/usr/bin/Xvnc -displayfd …` + `xdpyinfo -display 127.0.0.1:N` 退出 0 | 已实际运行 X11，独立 MIT cookie；关闭 Unix X 监听，VNC 只提供私有本地 socket |
| Wayland / Fcitx5 | `which wayland-info/fcitx5` 无结果；rpm 表示 fcitx5 未安装 | 未选用；无 Wayland 会话或协议验证证据 |
| 输入框架 | `ibus version`：1.5.25；rpm ibus/ibus-gtk3 已安装 | 主路线为 IBus + GTK3 模块 |
| Python GI | IBus GI 1.5.25；Gtk GI 3.24.31；python3-gobject 3.40.1 | 无需 C 开发头文件即可构造 Engine、Factory、InputContext |
| 原生开发模块 | `pkg-config --exists` ibus-1.0、glib-2.0、gio-2.0、gtk+-3.0、fcitx5、libpinyin 均退出 1 | 不尝试系统编译/安装该依赖；运行库与开发模块是不同能力 |
| 真实应用检查依赖 | rpm libX11 1.8.12、libXtst 1.2.3；GTK3；XTest 输入成功 | 实际 Gtk.Entry 收到按键、预编辑与中文结果，截图中中文可显示 |
| D-Bus | 私有 dbus-daemon + IBus register_component + 客户端选择引擎成功 | 自定义 session 配置不含服务激活目录；不使用宿主 bus |
| 日志工具 | `journalctl --version`：systemd 252 | 检查证据写 platform/evidence，不采集系统/其他用户日志，不向 journal 写输入内容 |

独立显示启动使用 `-displayfd` 自动选择可用 X TCP 显示号，`-nolisten unix -nolisten local` 避免触碰受限的现有 Unix X 套接字。显示号由私有服务器返回；即使编号为 0，也不是连接用户已有的 `:2`。X 连接使用新生成的认证 cookie，证据不包含 cookie，结束时销毁。所有启动命令保存在每轮 `summary.json`。

实际通过的能力包括：组件注册和选用；客户端预编辑、候选、中文提交；输入状态清空；页内数字选择；两个 IBus 客户端的焦点转移；真实 GTK 双输入框 Tab 切换；Ctrl+A 应用快捷键；按键释放和 Ctrl 组合透传；密码用途旁路；恢复普通输入；状态 revision 拒绝过期选择；UI 客户端的状态订阅、翻页、选择和中英模式命令。

以下未执行，不应读成已有支持：用户现有 VNC 桌面安装/启用；Wayland 原生协议；Qt/GTK4/Electron/浏览器/EDA 应用；传统 XIM；IBus 原生候选面板的视觉/DPI/鼠标检查；用户级自动启动、退出重连和安装回滚；真实转换质量和引擎性能。主链路使用 GTK IBus 模块，不把设置了 XMODIFIERS 当作已经验证 XIM。真实引擎、界面视觉和部署分别由后续相应任务负责。

检查中的 `portal is not running … ServiceUnknown` 来自关闭外部服务激活的私有 D-Bus。GTK3 走已验证的直接 IBus 连接，本轮不依赖 portal。Xvnc 的 `Could not find any render nodes` / `Failed to initialize DRI3 extension` 表明没有硬件加速路径；软件显示和 GTK 输入检查仍真实成功。

性能数据只计确定性后端下 `IBus.InputContext.process_key_event` 的同步往返时间，包含 IPC 和适配器，排除测试客户端等待分发信号的 sleep。它不是中文转换算法性能，也不是端到端视觉延迟；原始每次采样和统计在 `ibus-client.json`。

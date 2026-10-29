# 服务器输入法：平台接入交付

employee_id: **platform** · 接口版本 **1** · Python 模块许可证 **MIT**。

本交付实现 **X11 → GTK3 IBus 模块 → IBus 1.5.25 → 平台适配器 → 可替换转换端口**。
服务器是 Rocky Linux 9.8；现有桌面为 TigerVNC/X11 `:2`。本轮使用独立的 Xvnc、D-Bus 和 IBus 实例完成输入检查，未连接或切换用户现有桌面，也未修改用户输入法配置。

当前后端是明确标记的 `deterministic-fixture-v1`，只有 `ni`、`hao`、`nihao`、`zhongwen` 四组固定数据。它用于检查按键、候选、预编辑、提交和焦点链路，**不代表真实拼音转换质量、整句解码、双拼、纠错、学习或 Windows 11 体验已完成**。真实引擎由后续集成任务接入。

在项目根目录运行：

```bash
/usr/bin/python3 platform/tools/probe_environment.py --output platform/evidence/environment.json
/usr/bin/python3 platform/tools/run_checks.py
```

无需安装包或编译。使用已安装的 Python GI、IBus、GTK3、libX11、libXtst、Xvnc、dbus-daemon。脚本返回非零表示检查失败，详细结果写入它打印的 `platform/evidence/run-时间/`。

检查包含纯 Python 状态机、实际注册组件后的 IBus InputContext 客户端、通过 XTest 发送真实按键的 GTK3 双输入框。GTK 测试观察应用自己的预编辑信号与最终文本，并保存截图。测试客户端是自建的真实 GTK 应用；这不构成 Firefox、Qt、Electron 或 EDA 软件的兼容承诺。

所有测试配置、认证文件、套接字和缓存位于权限为 0700 的 `platform/.runtime/r-*/`，完成或失败后清理。日志与固定测试数据单独保存在 `platform/evidence/`。脚本使用私有 XDG 路径、内存 GSettings 后端和没有外部服务激活目录的 D-Bus 配置；不重设 `HOME`，不读取受限目录，不使用 `sudo`、`ibus --replace`、`pkill` 或宿主用户服务。测试结束会按记录的 PID 回收自己启动的进程。

适配器入口：

```bash
# 仅在调用者已准备并明确指定 IBUS_ADDRESS 的会话中注册；不会自动发现宿主 IBus。
/usr/bin/python3 platform/launch.py --register --test-backend

# 后续集成时替换为一个可导入模块的无参工厂：
/usr/bin/python3 platform/launch.py --register --backend your_engine_adapter:create_session

# 只生成 XML，不复制到任何输入法配置目录，也不启用输入法：
/usr/bin/python3 platform/launch.py --test-backend --manifest platform/evidence/server-ime-test.xml
```

`--register` 已经实际运行并检查。`--ibus` 是为 manifest 启动保留的入口；本轮生成了 manifest，但未检查 daemon 按 manifest 自动拉起进程，安装任务应验证该部署方式。默认引擎名为 `server-ime-test`，生产装配应明确传入 `--engine-name` 并使用真实后端。

接口说明见 [docs/interfaces.md](docs/interfaces.md)，环境能力和限制见 [docs/environment.md](docs/environment.md)，证据与后续任务消费约定见 [handoff.json](handoff.json)。所有实现和证据都归 `employee_id=platform`；`verifies` 为空，本任务自检。

## 产品装配入口（employee_id: platform）

真实产品现在由 `../integration/bin/server-ime` 启动，固定使用 engine 0.3.0 的
PlatformSession、lexicon.UserStore 和 interface 候选/设置组件；见
[产品说明](../integration/README.md) 和 [应用兼容结果](../integration/docs/application-compatibility.md)。
本目录 launch.py 的显式测试模式继续仅用于平台单测，不在产品运行包中。
新增 ProductController、可注入的 controller_factory、光标位置去重和总线断开时的退出清理。

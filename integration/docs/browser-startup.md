# 浏览器启动最小复现

employee_id: platform；`verifies: []`。本记录只涉及新建隔离 Xvnc/X11 会话。
用户既有 TigerVNC `:2` 保持 `NOT_DEPLOYED`，没有访问其授权、配置或桌面。

## 系统 Firefox

复现命令：`python3 integration/checks/run_checks.py --browser-startup-only`。
脚本创建 cookie 授权的 Xvnc、私有 D-Bus，启动完整产品，再经统一
`server-ime ... exec --` 依次运行以下三个入口。每个入口使用不同的空白工作区 profile，
参数均为 `--no-remote --profile /工作区/profile --new-instance http://127.0.0.1:端口`。

| 入口 | 参数转交 | 实际结果 |
|---|---|---|
| `/bin/bash -x /usr/bin/firefox` | `exec /usr/lib64/firefox/firefox "$@"`；strace 确认参数未丢失 | Profile Missing；没有页面请求 |
| `/usr/lib64/firefox/firefox` | 直接传递相同参数 | 相同错误 |
| `/usr/lib64/firefox/firefox-bin` | 直接传递相同参数 | 相同错误 |

实测版本为 `Mozilla Firefox 140.12.0esr`。三个程序哈希、启动参数、退出清理结果、
窗口树、截图、strace 和 profile 文件清单位于
`integration/evidence/run-20261028-203124/`；汇总为 `browser-startup.json`。
三个专用 profile 均没有初始化出任何文件。它们共同失败的调用为：

```text
mkdir("/home/vncer/.mozilla/firefox", 0700) = -1 EACCES (Permission denied)
```

这不是 `--profile` 参数被包装器吞掉。Mozilla ESR140 的
[Toolkit profile service 初始化代码](https://raw.githubusercontent.com/mozilla-firefox/firefox/esr140/toolkit/profile/nsToolkitProfileService.cpp)
先请求应用级配置目录，之后才进入 profile 选择；
[目录提供器](https://raw.githubusercontent.com/mozilla-firefox/firefox/esr140/toolkit/xre/nsXREDirProvider.cpp)
从 HOME 派生该目录并要求创建成功。源码快照及哈希随复现证据保存。
该控制流与本次失败调用相符；这是基于源码与实测的故障定位，未修改系统 Firefox。

复现沿用 `MOZ_DISABLE_LANGPACKS=1`，只为排除包装器语言包写入这一已知干扰；
并未把再次关闭语言包或再次创建目录当作修复。HOME、权限和浏览器沙箱均未修改，
未读取既有用户 profile。strace 只记录新建进程的路径操作与返回码，未记录文件读取内容。

## 官方独立浏览器检查工具

根据 [Chromium 官方下载说明](https://www.chromium.org/getting-involved/download-chromium/)，
使用官方 Chrome for Testing 发布索引及其 `storage.googleapis.com/chrome-for-testing-public/`
发行文件。`integration/browser-runtime/source.json` 固定版本、下载地址、SHA256、
发布端 MD5 校验和二进制哈希；`release-index.json` 保存取用的索引原文。
`python3 integration/tools/fetch_check_browser.py` 校验并解压已固定的发行文件。
浏览器只作为本步骤检查工具，不进入输入法产品包，不需要系统安装。

复跑浏览器链路：

```sh
SERVER_IME_PRODUCT_ROOT=/绝对路径/integration/build/product python3 integration/checks/run_checks.py --browser-only
```

该选项跳过此前已通过的终端、编辑器和产品生命周期检查；默认选择已下载的 Chrome。
`SERVER_IME_CHECK_BROWSER=firefox` 可显式复现系统 Firefox 行为。
独立 `--user-data-dir`、XDG 目录和临时文件均在本步骤新建的工作区目录内。
未提供 `--no-sandbox`、`--disable-web-security` 或降低沙箱级别的环境变量。
网页只监听真实按键、组合、焦点、输入事件并回报值；不使用 WebDriver、DOM 赋值或合成 DOM 事件。
具体成功/失败结果与兼容范围见 `application-compatibility.md`，本复现记录本身不声明浏览器输入通过。

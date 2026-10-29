# 当前发布：0.1.6（employee_id: delivery）

包含装配 0.2.9 的单一候选窗、完整候选页及布局后高亮滚动、短页宽度收缩修复。旧包保留；[升级/启动/取消组合/回滚/反馈](docs/实机验收.md)。当前检查见 [证据索引](docs/evidence-index.md)，历史说明如下。

# delivery：统一构建、发布包与用户级安装生命周期

本目录交付服务器输入法的**真实发布包**与**用户级**安装工具链：显式前缀、显式运行数据目录、
无 root、不写系统目录、不产生系统服务。发布包已包含运行所需全部组件
（libpinyin 运行时与词库表、引擎、平台适配、词库学习、候选/设置界面、产品入口），
并用同一套工具在隔离前缀完成安装、重复安装、启动/停止、升级、回滚、诊断与卸载。

- 发布包：`dist/server-ime-0.1.6.tar.gz`（112 文件，sha256 见 `dist/SHA256SUMS`）+ 源码合规包 `dist/server-ime-0.1.6-sources.tar.gz`
- 许可材料：安装包与源码包均含 `engine/LICENSE`、`platform/LICENSE`、`integration/LICENSE`、`interface/LICENSE`、
  `interface/SOURCES.md`、`lexicon/SOURCES.md` 及 libpinyin/glib/libdb/pcre 许可原文；缺失时 `bin/ime-build` 以退出码 5 拒绝出包
- 中文说明：包内 `share/ime/docs/README.zh_CN.md`（快速上手），完整版在 `docs/使用指南.md`
- 中文使用与运维：`docs/使用指南.md`
- 功能/证据/许可及未验证范围：`docs/feature-matrix.md`、`docs/evidence-index.md`、`docs/licenses.md`
- 交接清单：`handoff.json`
- 实际桌面状态：**NOT_DEPLOYED**（按约定不改动用户桌面与共享套接字；启用步骤见使用指南第 3 节）

## 1. 目录内容

```
delivery/
  bin/ime-build            统一构建入口：装配组件 → ime-bundle 安装包 + 源码包 + 版本锁定 + 构建记录
  bin/ime-release-check    真实发布包隔离生命周期检查（安装/重复安装/启动停止/升级/回滚/诊断/卸载）
  bin/ime-install          安装/升级/回滚/卸载/恢复/列版本/校验（Python 3 标准库）
  bin/ime-diagnose         诊断报告（不含输入内容）
  bin/ime-manifest         组件清单 / 安装包 / 产品清单校验
  bin/ime-selfcheck        构建样例包并跑完整生命周期自检
  lib/ime_delivery/        实现：policy / manifest / installer / diagnose / product / cli
  manifest/
    component-manifest.schema.json   组件交付清单 JSON Schema
    README.md                        清单字段、包格式、安装布局约定
    product-manifest.json            产品级汇总清单（server-ime 0.1.6，packaging_ready=true）
    lock.json                        版本锁定：组件输入摘要、锁定运行时、包/源码哈希
  dist/                    发布包、源码包、组件清单副本、SHA256SUMS
  build/<版本>/            构建记录 build.json（输入摘要、输出哈希、排除项）
  samples/                 隔离样例包与负例（fixture，不是真实输入法）
  tests/make_samples.py    可重复构建样例包（确定性 tar）
  tests/run_lifecycle_check.py     安装工具自检（11 个场景）
  tests/verify_release_content.py  发布包内容校验：许可材料/中文说明/源码包/工具/校验和/运行代码哈希
  docs/install-lifecycle.md        事务阶段、崩溃恢复、退出码
  docs/diagnostics-privacy.md      诊断的隐私边界
  evidence/                自检日志、JUnit XML、汇总 JSON
  .check/                  自检使用的隔离前缀/数据目录（可删除重跑）
```

安装工具只用 Python 标准库；产品运行需要 Python 3.9+、系统 GI/GTK3/IBus 和可访问的 X11 会话。无需 root。

## 2. 安装工具样例（真实产品安装见 docs/使用指南.md）

```sh
cd delivery
P="$PWD/.user/prefix"     # 显式安装前缀（不能是 /usr 等系统目录、不能是 $HOME 本身）
D="$PWD/.user/data"       # 显式运行数据目录（必须在前缀之外）

# 安装（重复安装同一版本是幂等的）
bin/ime-install install --prefix "$P" --data-dir "$D" samples/packages/ime-demo-1.0.0.tar.gz

# 升级；升级后旧版本保留，可回滚
bin/ime-install upgrade --prefix "$P" --data-dir "$D" samples/packages/ime-demo-1.1.0.tar.gz

# 查看版本 / 校验已安装文件 / 回滚
bin/ime-install list   --prefix "$P"
bin/ime-install verify --prefix "$P"
bin/ime-install rollback --prefix "$P"            # 回到 previous
bin/ime-install rollback --prefix "$P" --to 1.1.0 # 或指定版本

# 诊断（只含路径/大小/校验值，不含任何输入内容）
bin/ime-diagnose --prefix "$P" --json

# 中断后恢复（下次 install/upgrade 前也会自动执行）
bin/ime-install recover --prefix "$P"

# 卸载：默认保留运行数据与无关文件
bin/ime-install uninstall --prefix "$P"
# 彻底删除运行数据需要显式确认
bin/ime-install uninstall --prefix "$P" --purge-data --yes
```

常用可选参数：

| 参数 | 用途 |
| --- | --- |
| `--allowed-root DIR` | 额外白名单：前缀与数据目录都必须在此根之下（可重复） |
| `--lock-timeout SEC` | 等待前缀锁的秒数（默认 0，立即失败，退出码 6） |
| `--force-conflicts` | 入口路径被无关文件占用时，把该文件移入 `ime/backup/` 后继续（不删除） |
| `--repair` | 同版本内容不一致/已安装文件被修改时重装（旧目录移入 `ime/backup/`） |
| `--retain N` | 保留版本数（含当前与上一版本，默认取清单 `retain_versions`，通常 2） |
| `--sha256 HEX` | 覆盖整包校验值；缺省读取 `<包>.sha256` |
| `--fault POINT` | 仅测试：在指定阶段强制退出以验证崩溃恢复 |

注意：策略同时拒绝把前缀/数据目录直接放在 `/tmp`、`/home`、`/workspace` 这些目录本身
（其子目录可用），也拒绝 `/usr`、`/etc`、`/var`、`/opt` 等系统目录；完整列表见
[`docs/install-lifecycle.md`](docs/install-lifecycle.md) 第 1 节。

所有子命令支持 `--json`；`-v` 把审计日志同时打印到 stderr。

## 3. 复跑自检

```sh
cd delivery
bin/ime-selfcheck
# 等价于：
python3 tests/make_samples.py && python3 tests/run_lifecycle_check.py
```

预期输出（本机实测，2026-10-28）：

```
PASS manifest_and_bundle      7 个清单负例、4 个坏包、3 个产品清单样例均按预期拒绝
PASS install_repeat_repair    首次安装、幂等重复安装、--repair、空前缀升级拒绝均通过
PASS policy                   系统目录、相对路径、空前缀、主目录、数据目录互相包含、白名单越界均被拒绝；白名单内安装成功
PASS upgrade_rollback_data    安装/升级/两次回滚/漂移拒绝/--allow-drift/修复后个人数据与无关文件哈希不变
PASS retain                   --retain 2 只保留当前与上一版本，回滚仍可用
PASS verification_failure     4 种校验失败（篡改载荷/错误 sidecar/额外文件/缺失文件）均未破坏已安装版本
PASS conflicts                入口占位冲突中止且不动原文件；--force-conflicts 备份后继续；ime/current 占用被识别
PASS interrupt                7 个升级中断点与 1 个首次安装中断点均恢复到一致状态并可重试
PASS uninstall                卸载移除全部受管文件、保留个人数据/无关文件/冲突备份，幂等；purge 需 --yes
PASS diagnose_privacy         诊断报告包含依赖/入口/数据清单，不含任何词条文本；漂移可被发现并修复
PASS lock                     前缀锁阻止并发事务（退出码 6），释放后可正常升级

自检结果: 11 通过, 0 失败, 7.6 秒
```

证据文件：

- `evidence/lifecycle-<时间戳>.log`：每条命令、返回码、耗时、stdout/stderr；
- `evidence/lifecycle-junit.xml`：JUnit 格式（`tests="11" failures="0"`）；
- `evidence/lifecycle-summary.json`：场景结果与证据路径索引。

自检使用的全部前缀与数据目录位于 `delivery/.check/`，可整体删除后重跑；
不会写入 `$HOME`、`/tmp` 系统目录或任何系统路径（子进程 `HOME`/`TMPDIR` 也被
重定向到 `delivery/.check/`）。`samples/` 与 `.check/` 都不属于最终安装。

## 4. 组件交付清单（最终打包输入）

字段、包格式与校验规则见 [`manifest/README.md`](manifest/README.md)，schema 见
[`manifest/component-manifest.schema.json`](manifest/component-manifest.schema.json)。
要点：

- 每个组件打成一个 `ime-bundle/1`（`component-manifest.json` + `payload/`），
  清单声明**版本、逐文件 sha256/大小/权限、运行依赖、启动入口、运行数据目录、保留策略**；
- `bin/ime-manifest inspect <包>` 可在不安装的情况下校验整包（含 `<包>.sha256`）；
- `manifest/product-manifest.json` 汇总真实产品包；`bin/ime-manifest product` 校验并报告
  `packaging_ready=true`（当前 `server-ime` 0.1.0 已就绪，sha256 与 `dist/SHA256SUMS` 一致）；
- 构建入口 `bin/ime-build` 在暂存阶段显式纳入许可/来源材料与包内中文说明，
  **必需许可材料缺失时构建失败**（退出码 5，见 `evidence/license-fix-20261028T131941Z/`）。

## 5. 与真实输入法集成的边界（诚实说明）

- 本目录验证的是**包装与安装生命周期**。`samples/` 内的样例组件 `ime-demo` 只打印版本并统计数据目录
  文件数，不包含拼音转换、IBus 适配或候选界面；它不声称是输入法，只是工具自检的 fixture。
- 真实产品打包：`bin/ime-build` 调用 `integration/tools/build_product.py` 装配产品根后打成 `ime-bundle/1`，
  再用同一套 `ime-install` 在用户前缀中安装；安装完成后通过 `ime-diagnose` 复核入口与依赖。
- 未在本环境验证的内容：Wayland 会话、root/系统级安装、DEB/RPM 包安装（无 dpkg/root）、systemd 用户服务、
  系统 Firefox、真实用户桌面启用（按约定不改动用户桌面；`NOT_DEPLOYED`）。无 Windows 11 运行环境与
  同机对照测评，因此不声称达到 Windows 11 水平。
- 本工具不写 `/usr`、`/etc`、`/var`、`/opt`、`$HOME` 等位置，也不依赖 root；
  若站点要求把前缀放在受管目录，需由管理员预先创建并把所有权交给运行用户，再用
  `--allowed-root` 收窄写入范围。

源码包含安装工具及项目构建材料。独立获取与重建步骤见 [SOURCE-BUILD.md](docs/SOURCE-BUILD.md)；完整哈希以 `delivery/dist/SHA256SUMS` 为准。

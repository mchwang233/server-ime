# 安装事务与故障恢复

本文说明 `bin/ime-install` 的安装/升级/回滚/卸载事务边界、原子切换点、崩溃恢复规则与
退出码。所有写入都发生在显式前缀 `<prefix>` 和显式运行数据目录 `<data-dir>` 内，
不使用 root、系统服务或系统目录。

## 1. 安全边界

| 检查 | 行为 |
| --- | --- |
| 前缀/数据目录必须显式给出 | 缺省或空值直接拒绝（退出码 2），工具不假设默认位置 |
| 必须是绝对路径 | 相对路径拒绝（2） |
| 拒绝系统目录 | `/`、`/usr`、`/usr/local`、`/etc`、`/var`、`/opt`、`/bin`、`/sbin`、`/lib*`、`/boot`、`/proc`、`/sys`、`/dev`、`/run`、`/root`、`/srv` 及其子目录（3） |
| 拒绝主目录本身 | `--prefix $HOME` 拒绝；允许 home 下的专用子目录 |
| 所有权/可写性 | 已存在目录必须是当前 uid 拥有且可写；不存在时最近父目录必须可写（其他用户的非 sticky 目录拒绝） |
| 拒绝符号链接目标 | 前缀/数据目录本身是 symlink 时拒绝，路径按 `realpath` 规范化后使用 |
| 数据与前缀分离 | 二者相同或互相包含都拒绝（3），保证卸载/回滚不会碰到个人数据 |
| 可选白名单 | `--allowed-root DIR`（可重复）要求前缀与数据目录都在白名单内 |
| 并发互斥 | 前缀根下 `.ime-install.lock` 上的 `flock`；拿不到锁立即失败（6），`--lock-timeout` 可等待 |

## 2. 目录与版本模型

- 每个版本一个独立目录 `<prefix>/ime/versions/<version>/`，安装时由 staging 目录整体
  `rename` 进来（同文件系统内原子）；
- `<prefix>/ime/current` 是指向 `versions/<version>` 的符号链接，**唯一切换点**；
- `<prefix>/bin/<入口>` 指向 `../ime/current/<文件>`，因此切换 current 即完成入口切换；
- 状态文件 `<prefix>/ime/state/installed.json` 记录版本、逐文件校验值、启动入口、
  数据目录、创建过的目录与操作历史；
- 进行中的事务写入 `<prefix>/ime/state/journal.json`，是崩溃恢复的唯一依据。

## 3. 安装/升级事务阶段

```
校验参数与策略
  → 取前缀锁
  → 若存在 journal：先自动 recover
  → 解包 staging/<txid>，逐文件校验清单（大小 + sha256）
  → 只读检查：同版本是否已安装、版本目录归属、入口/current 冲突
  → 写 journal（phase=staged）
  → --force-conflicts 时把占位文件移入 ime/backup/conflicts-<txid>/（记录在 journal）
  → --repair 时把旧版本目录移入 ime/backup/（记录为 journal.version_backup）
  → 创建运行数据空目录（0700，不写内容）
  → rename payload → versions/<version>            [after_version_placed]
  → 原子替换 current 链接                           [after_switch]
  → 同步 bin/ 入口链接                              [after_links]
  → 计算保留策略、写状态（journal phase=committing → committed）[before/after_state_commit]
  → 删除超出保留数的旧版本目录
  → 清理 staging 与 journal
```

任何一步失败或进程被杀，`current` 要么仍指向旧版本，要么指向完整的新版本目录；
`versions/<version>` 只有在清单校验全部通过后才会出现。

## 4. 崩溃恢复（`ime-install recover`，也会在下次安装前自动执行）

判定是否已提交：journal `phase=committed`，或状态里 `current == new_version` 且
该版本目录的文件与状态记录完全一致。

| 情况 | 恢复动作 |
| --- | --- |
| 未提交，存在 `version_backup`（修复/覆盖场景） | 删除半成品目录，把备份版本目录移回原位 |
| 未提交，新建的版本目录（含首次安装） | 删除该目录 |
| 未提交，有上一版本 | `current` 链接指回上一版本，补齐其入口链接 |
| 未提交，首次安装 | 移除 current 链接与新建入口，不写状态 |
| 冲突备份 | 把 `conflicts-*` 中移走的用户文件移回原路径（仅当原路径仍空） |
| 已提交 | 只清理 staging/journal，保留新版本 |
| 只有 staging 残留 | 直接清理 |

测试通过 `--fault <阶段>` 在 7 个阶段强制退出（退出码 90）验证上述规则；
每个阶段随后都要求：旧版本入口仍可执行、`recover` 后无残留 journal/staging、
运行数据哈希不变、可以重新升级。

## 5. 重复安装、修复与保留策略

- 同包同版本再次安装：逐文件校验一致且为当前版本 → 输出"已安装且内容一致"，退出 0，
  不改动任何文件或状态（幂等）；
- 同版本但内容不同、或已安装文件被修改：拒绝（3），提示使用 `--repair`；
  `--repair` 会把旧目录移入 `ime/backup/` 后重装，成功提交后才删除备份之外的旧内容；
- 已安装但非当前版本：拒绝（3），提示用 `rollback --to`；
- `retain_versions`（默认 2，可用 `--retain N` 覆盖）按安装顺序保留当前与上一版本；
  超出保留数的版本目录在状态提交后才删除，因此中途崩溃最多留下未被引用的目录，
  不会破坏状态引用。

## 6. 回滚

`ime-install rollback --prefix P [--to VERSION]`：

1. 目标版本默认取状态中的 `previous`；
2. 校验目标版本目录存在且逐文件校验值一致；不一致时拒绝（5），
   除非显式 `--allow-drift`；
3. 原子切换 current、同步入口链接（补齐目标版本入口、移除旧版本独有入口）；
4. 更新状态（current/previous 互换），清理 journal。

回滚事务同样有 journal；中途崩溃会恢复到回滚**之前**的版本，且不会删除原本已存在的
版本目录（journal 记录 `new_version_preexisting`）。

## 7. 卸载

`ime-install uninstall --prefix P [--data-dir D] [--purge-data --yes]`：

- 只删除状态中记录的本工具文件：入口链接、版本目录、状态、staging、日志、锁文件；
- 按记录回收本次安装创建的**空**目录（有无关文件时保留目录）；
- `ime/backup/`（用户被占用文件的副本、修复前的旧版本）**始终保留**并在结果中报告；
- 运行数据目录默认保留；`--purge-data` 必须同时给 `--yes`，否则退出 2 且不删除；
- 前缀中与本工具无关的文件/目录原样保留，结果 JSON 的 `preserved` 列出全部保留项；
- 未安装时重复卸载返回 `not-installed`、退出 0（幂等）。

## 8. 退出码

| 码 | 含义 |
| --- | --- |
| 0 | 成功（含幂等重复安装、未安装时重复卸载） |
| 2 | 参数用法错误（缺前缀/空前缀/相对路径/`--purge-data` 未确认） |
| 3 | 策略拒绝或冲突（系统目录、数据目录包含关系、无关文件冲突、版本内容不一致） |
| 4 | 未安装（对空前缀执行 upgrade/rollback，或回滚目标不存在） |
| 5 | 校验失败（清单、载荷、sidecar、已安装文件漂移、诊断发现异常） |
| 6 | 前缀锁被占用 / 内部中止 |
| 90 | 仅测试：`--fault` 注入的强制退出（模拟进程被杀死） |

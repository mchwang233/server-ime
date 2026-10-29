# 组件交付清单约定（ime.component-manifest/1）

本目录定义"最终打包"所需的全部信息：版本、文件、校验值、运行依赖、启动入口、
运行数据目录与保留策略。安装工具 `bin/ime-install` 只接受符合本约定的
`ime-bundle/1` 安装包；`bin/ime-manifest` 可在不安装的情况下校验清单与整包。

- 机器可读 schema：[`component-manifest.schema.json`](./component-manifest.schema.json)
- 产品级汇总清单：[`product-manifest.json`](./product-manifest.json)（`server-ime` 0.1.0 为 `ready`）
- 校验实现：[`../lib/ime_delivery/manifest.py`](../lib/ime_delivery/manifest.py)
  （不依赖第三方 `jsonschema`，在无网络的服务器上也能运行）

## 1. 安装包格式（ime-bundle/1）

固定为 `tar.gz`，根目录只能有两个条目：

```
component-manifest.json      # 本清单
payload/                     # 载荷根（payload_root 默认为 payload）
  bin/ime-demo
  lib/...
  share/ime/...
```

约束（`ime-manifest inspect` 会逐条检查）：

| 约束 | 说明 |
| --- | --- |
| 仅普通文件/目录 | 包内不允许符号链接、硬链接、设备文件 |
| 路径安全 | 不允许绝对路径、`..`、反斜杠、空段；成员不得重复 |
| 清单先行 | 根目录必须有 `component-manifest.json` |
| 逐文件一致 | `files[]` 中的 `path/size/sha256` 必须与 payload 完全一致 |
| 无额外文件 | payload 中不允许出现清单未声明的文件 |
| 总大小限制 | ≤ 20000 个文件、≤ 4 GiB 载荷 |
| 可选整包校验 | 同名 `<包>.sha256`，首列为 64 位小写十六进制摘要；存在时安装前校验 |

## 2. 字段说明

### component（组件身份）

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `id` | 是 | `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`，与产品清单中的组件 id 一致 |
| `name` | 是 | 中文/英文显示名 |
| `version` | 是 | 语义化版本 `1.0.0` / `1.1.0-rc1`，安装目录名即此版本 |
| `kind` | 是 | `product`/`engine`/`frontend`/`data`/`tool` |
| `license` | 是 | 许可证标识（打包时必须可汇总） |
| `description` | 是 | 一句话说明 |

### package（包元信息）

`format` 固定 `ime-bundle/1`；`payload_root` 默认 `payload`；`created_at`、`builder` 供
溯源使用。

### compatibility（运行环境）

`platform` 必须包含 `linux`；`python` 给出解释器要求（如 `>=3.8`）；
`arch` 列出已验证架构。

### files（文件清单与校验值）

每个条目：

```json
{"path": "bin/ime-demo", "sha256": "<64 hex>", "size": 1234,
 "mode": "0755", "kind": "executable", "description": "样例入口"}
```

- `path` 相对 payload 根，也就是安装后在 `<prefix>/ime/versions/<version>/` 下的相对路径；
- `mode` 只允许 `0xxx`，且不得带 setuid/setgid/sticky；
- `kind=executable` 时 mode 必须含可执行位，同名可执行文件不得重复（启动入口名唯一）；
- 安装时按 `mode` 重设权限，校验时按 `sha256`+`size` 比较。

### runtime（运行依赖与数据位置）

```json
"runtime": {
  "requires": [
    {"id": "python3", "kind": "executable", "probe": ["python3", "--version"],
     "minimum": "3.6", "required": true, "description": "解释器"},
    {"id": "json", "kind": "python-module", "module": "json", "required": true}
  ],
  "env": {"IME_DATA_DIR": "{data_dir}"},
  "data_dirs": [
    {"path": "personal", "description": "个人词库与短语（不得删除）", "preserve": true},
    {"path": "learning", "description": "学习与统计状态", "preserve": true}
  ]
}
```

- `requires[].kind`：`executable`（用 `probe` 参数数组探测，禁止 shell 字符串）、
  `python-module`（`module`）、`file`（`path`，支持 `{prefix}`/`{data_dir}` 占位）；
- `env` 不得包含凭据类变量名（password/secret/token/api_key 等）；
- `data_dirs` 是相对**运行数据目录**的子目录，安装时只创建空目录（0700），
  安装/升级/回滚/卸载都不会写入或删除其中内容（`preserve: true` 为默认语义）。

### entrypoints（启动入口）

```json
"entrypoints": [
  {"id": "demo-cli", "kind": "cli",
   "argv": ["{prefix}/bin/ime-demo", "--version"],
   "description": "版本查询入口"}
]
```

- `argv[0]` 必须是 `{prefix}/bin/<名字>`（名字与某个 `executable` 文件同名），
  或 `{prefix}/ime/current/<files 中的路径>`；
- `kind`：`cli`/`engine`/`panel`/`service`/`setup`，供平台集成与界面接入时区分；
- 安装器在 `<prefix>/bin/<名字>` 建立相对符号链接
  `../ime/current/<路径>`，**指向 current 而不是具体版本**，因此升级/回滚后入口自动切换；
- 入口集合随版本变化：升级或回滚时会补齐新入口、移除旧版本独有入口。

### install / preserve

- `install.link_dir` 目前固定为 `bin`；
- `install.retain_versions`（1..10，默认 2）：保留的版本数，含当前与上一版本；
- `preserve.data_globs`：数据目录中必须保留的相对 glob（如 `personal/**`），
  卸载与升级逻辑据此复核，不做删除。

## 3. 产品级清单（ime.product-manifest/1）

`product-manifest.json` 把各组件汇总为最终打包输入：

```json
{
  "schema": "ime.product-manifest/1",
  "product": {"id": "server-ime", "name": "...", "version": "0.1.0-draft", "license": "...", "description": "..."},
  "components": [
    {"id": "engine", "employee_id": "engine", "role": "拼音引擎", "status": "pending",
     "version": null, "bundle": null, "entrypoints": [], "data_dirs": [], "notes": "..."}
  ]
}
```

- `status`：`pending`（未交付）/`ready`（包已就绪）/`blocked`；
- `ready` 组件必须给出 `version`、`bundle`（相对产品清单的 `ime-bundle` 路径）与
  至少一个 `entrypoints` 名称；`ime-manifest product` 会打开包核对组件 id/版本一致性，
  并报告 `packaging_ready`（全部 ready 时才为 true）；
- 当前真实清单中 `server-ime` 0.1.0 为 `ready`（sha256 与 `dist/SHA256SUMS` 一致），
  因此 `ime-manifest product` 报告 `packaging_ready=true`；清单只描述可安装产物。

校验命令：

```sh
bin/ime-manifest validate <manifest.json> [--payload <payload目录>] [--json]
bin/ime-manifest inspect  <package.tar.gz> [--json]
bin/ime-manifest product  manifest/product-manifest.json [--json|--no-bundles]
```

## 4. 安装布局（安装器消费清单的方式）

```
<prefix>/bin/<入口>                 -> ../ime/current/<可执行文件>
<prefix>/ime/current                -> versions/<版本>        # 原子切换点
<prefix>/ime/versions/<版本>/...    # 每个版本独立目录
<prefix>/ime/state/installed.json   # 版本、文件校验值、入口、数据目录、历史
<prefix>/ime/state/journal.json     # 进行中的事务（崩溃恢复依据）
<prefix>/ime/staging/<txid>/        # 解包校验临时目录
<prefix>/ime/backup/                # 冲突/修复时保留的原始文件副本（卸载不删除）
<prefix>/ime/log/install.log        # 审计日志（仅路径/版本/校验值）
<data-dir>/personal, learning ...   # 运行数据，独立于前缀
```

详细事务与恢复语义见 [`../docs/install-lifecycle.md`](../docs/install-lifecycle.md)。

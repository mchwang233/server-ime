# 许可与第三方组件清单（server-ime 0.1.0）

发布包 `delivery/dist/server-ime-0.1.0.tar.gz` 内含全部运行所需组件及其许可证副本；
`delivery/dist/server-ime-0.1.0-sources.tar.gz` 含对应源码、必要构建材料与同一批许可原文。
本文件由构建交付汇总，**不替代各组件目录内的原始许可证文本**。

许可材料由构建入口 `delivery/bin/ime-build` 在暂存阶段显式纳入安装载荷（`REQUIRED_LICENSE_MEMBERS`），
任一缺失即以退出码 5 拒绝出包（实测见 `delivery/evidence/punctuation-closeout-20261029/missing-LICENSE.log`、`missing-SOURCES.md.log`）。
包内路径清单同时写在 `share/ime/release.json` 的 `license_material` 字段。

| 组件 / 范围 | 版本 | 许可 | 包内许可文件 | 说明 |
| --- | --- | --- | --- | --- |
| engine（转换组件代码） | 0.4.0 | GPL-3.0-or-later | `engine/LICENSE` | 基于 libpinyin 2.6.0 的 ctypes 绑定与候选逻辑 |
| libpinyin 运行时 | 2.6.0-4.el9 (`libpinyin.so.13.0.0`) | GPL-3.0-or-later | `engine/vendor/runtime/licenses/libpinyin/COPYING`、`AUTHORS`、`README`、`opengram.license` | 随包分发二进制；源码在 `-sources.tar.gz`（上游 tar 与 src.rpm） |
| libpinyin 数据表 | 2.6.0-4.el9 | GPL-3.0-or-later（上游数据包） | 同上 | `engine/vendor/runtime/data/*.bin`、`bigram.db`、`table.conf` |
| glib2 运行时 | 2.68.4-19.el9_8.1 | LGPL-2.1-or-later | `engine/vendor/runtime/licenses/glib2/COPYING` | libpinyin 依赖；源码 `glib2-*.src.rpm` 在 `-sources` 包 |
| libdb 运行时 | 5.3.28-57.el9_6 | Sleepycat / LGPL-2.1（双许可，随包取 LGPL 文本） | `engine/vendor/runtime/licenses/libdb/LICENSE`、`lgpl-2.1.txt` | bigram.db 访问；源码 `libdb-*.src.rpm` 在 `-sources` 包 |
| pcre 运行时 | 8.44-4.el9 | BSD-3-Clause | `engine/vendor/runtime/licenses/pcre/COPYING`、`LICENCE` | libpinyin 依赖；源码 `pcre-*.src.rpm` 在 `-sources` 包 |
| lexicon（代码） | base-v1 | GPL-3.0-or-later | `lexicon/licenses/GPL-3.0.txt` | 见 `lexicon/SOURCES.md` |
| lexicon 增强词库数据 | 369 条 | CC-BY-4.0 | `lexicon/SOURCES.md`（含来源与哈希） | pypinyin 生成拼音，MIT 许可文本 `lexicon/licenses/pypinyin-MIT.txt` |
| platform（IBus 适配层） | 0.1.0 | MIT | `platform/LICENSE` | |
| integration（产品装配与入口） | 0.2.1 | GPL-3.0-or-later | `integration/LICENSE` | 含 `bin/server-ime` 入口 |
| interface（候选面板与设置界面） | 设置格式 v1 | GPL-3.0-or-later | `interface/LICENSE`（SPDX 头 + 完整 GPL-3.0 文本，36,160 字节） | 由 interface 组件补交；原创文件范围、GTK3/PyGObject/IBus/libpinyin 等运行期依赖的上游许可见 `interface/SOURCES.md`。interface 组件本身不复制第三方源码/二进制/字体；统一发布包另含上表引擎运行依赖 |
| 字体 | 系统 `google-noto-cjk` 等 | 各自许可 | 不分发 | 由系统提供，安装包不含字体 |
| 包内中文快速说明 | 0.1.0 | GPL-3.0-or-later | — | `share/ime/docs/README.zh_CN.md`（由构建入口生成，随产品同许可发布） |

## 源码合规

- `delivery/dist/server-ime-0.1.0-sources.tar.gz`（sha256 `ebacb78b86de1a9fc1b36f595cbdd01bdc61393eeadb38c83adeb7774e7db50a`，
  86,016,025 字节）包含：
  `engine/vendor/libpinyin-2.6.0.tar.gz`、`engine/vendor/libpinyin-2.6.0-4.el9.src.rpm`、
  `engine/vendor/sources/{glib2,libdb,pcre}-*.src.rpm`、`engine/vendor.lock.json`、
  `engine/LICENSE`、`platform/LICENSE`、`integration/LICENSE`、`interface/LICENSE`、
  `interface/SOURCES.md`、`lexicon/licenses`、`lexicon/SOURCES.md`；另含全部项目运行源码、engine/CMakeLists.txt、各 tools/bin、delivery/bin 与 delivery/lib、中文构建安装说明 delivery/docs/SOURCE-BUILD.md。
- 0.1.1 升级测试包与 0.1.0 使用同一份源码包（内容相同，sha256 相同）。
- 安装载荷**不包含**上述源码包（`delivery/build/0.1.0/build.json` 的 `excluded_from_payload` 有记录），
  安装体积因此从 112 MiB 降到约 54 MiB 载荷。
- GPL 组件的完整对应源码可用上述来源包重建；`engine/vendor.lock.json` 固定了 40 个运行时/源码文件哈希。
- 校验命令：`(cd delivery/dist && sha256sum -c SHA256SUMS)`；逐项内容核对：
  `python3 delivery/tests/verify_release_content.py`（含许可材料、源码包、中文说明与运行代码哈希）。

## 已知许可事项

1. 所有组件均已随包提供许可文件，**无未解决占位**；`interface/` 的许可材料已由该组件补交并纳入安装包与源码包。
2. `lexicon` 代码为 GPL-3.0-or-later、数据为 CC-BY-4.0，数据与代码许可不同，再分发时需同时保留两者声明。
3. 随包分发 libpinyin/glib/libdb/pcre 二进制：必须同时提供对应源码（已提供）并在文档中标注修改情况（未修改，仅按原包复制）。

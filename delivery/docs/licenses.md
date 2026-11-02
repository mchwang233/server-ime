# 许可与第三方组件清单（server-ime 0.1.13 起）

server-ime 整体以 **GPL-3.0-or-later** 发布（根目录 `LICENSE`）：它链接 libpinyin（GPL-3.0-or-later），
所以只能用 GPL-3 或兼容的许可。各组件目录另有自己的许可文件，`platform/`（IBus 适配层）是 MIT，可单独按 MIT 使用。

每个 GitHub Release 都附有对应源码包 `*-sources.tar.gz`：其中 `project/` 是该版本标签处的完整项目源码，
`third-party/` 是下表“随包二进制”各项的上游源码原件（未修改，附 SHA256SUMS）。源码包由
`delivery/bin/ime-sources` 生成。

## 项目自身

| 组件 | 许可 | 许可文件 |
| --- | --- | --- |
| engine（拼音转换引擎、`engine/native/sime_libime.cpp`） | GPL-3.0-or-later | `engine/LICENSE` |
| lexicon（词库代码） | GPL-3.0-or-later | `lexicon/LICENSE`、`lexicon/licenses/GPL-3.0.txt` |
| lexicon 增强词库数据（369 条） | CC-BY-4.0 | `lexicon/SOURCES.md`（拼音由 pypinyin 生成，MIT：`lexicon/licenses/pypinyin-MIT.txt`） |
| interface（候选面板、设置界面） | GPL-3.0-or-later | `interface/LICENSE`、`interface/SOURCES.md` |
| integration（产品装配与入口） | GPL-3.0-or-later | `integration/LICENSE` |
| platform（IBus 适配层） | MIT | `platform/LICENSE` |
| delivery（构建、安装工具） | GPL-3.0-or-later | 根目录 `LICENSE` |

## 随包数据

| 数据 | 来源 | 许可 | 说明 |
| --- | --- | --- | --- |
| libpinyin 词库表与模型（`engine/vendor/runtime/data`） | libpinyin 2.6.0 | GPL-3.0-or-later | 上游数据包原样复制 |
| libime 词典与语言模型（`engine/vendor/libime/data`：sc.dict、extb.dict、zh_CN.lm、zh_CN.lm.predict） | libime 1.1.17 发布的 `dict-20260907`、`lm_sc.arpa-20260629` | LGPL-2.1-or-later（随 libime 发布，上游未另行声明） | 用 libime 自带工具从上游数据构建；上游数据在源码包 `libime-1.1.17_dict.tar.zst` |
| 英文词表（`engine/data/english-v1.txt`） | FrequencyWords 2018 `en_50k`（基于 OpenSubtitles，github.com/hermitdave/FrequencyWords），以 hunspell `en_US` 词典过滤，另加少量技术词 | **CC-BY-SA-4.0** | 该文件是 FrequencyWords 数据的派生作品，按 CC-BY-SA-4.0 再分发（署名同上，相同方式共享）；制作方法见 `engine/docs/MIXED-INPUT.md` |

## 随包二进制

三个版本共有：

| 组件 | 版本 | 许可 | 上游源码（源码包 `third-party/`） |
| --- | --- | --- | --- |
| libpinyin | 2.6.0 | GPL-3.0-or-later | `libpinyin-2.6.0.tar.gz`（主版本另附 `libpinyin-2.6.0-4.el9.src.rpm`） |
| libime（libIMECore、libIMEPinyin，内含 kenlm） | 1.1.11 | LGPL-2.1-or-later | `libime-1.1.11.tar.zst` |
| fcitx5 工具库（libFcitx5Utils） | 5.1.12 | LGPL-2.1-or-later | `fcitx5-5.1.12.tar.zst` |
| fmt（编译进 libFcitx5Utils） | 10.2.1 | MIT | `fmt-10.2.1.tar.gz` |

libime、fcitx5 未修改源码，只按 `engine/vendor/libime/README.md`、`delivery/el*/build-native.sh` 的选项构建
（不构建 fcitx4 迁移工具、桌面数据和翻译）；它们以共享库形式随包，用户可以替换成自己构建的版本。
许可原文在安装包 `engine/vendor/libime/licenses/`、`engine/vendor/runtime/licenses/`。

各版本另带的系统库：

| 版本 | glib2（LGPL-2.1-or-later） | libdb（LGPL-2.1 / Sleepycat） | pcre（BSD-3-Clause） | 其他 |
| --- | --- | --- | --- | --- |
| 主版本（EL9） | 2.68.4-19.el9_8.1 | 5.3.28-57.el9_6 | 8.44-4.el9 | Boost iostreams、zstd 用系统的，不随包 |
| Rocky/Alma/RHEL 8 | 2.56.4-164.el8 | 5.3.28-42.el8_4 | 8.42-6.el8 | 见下 |
| CentOS/RHEL 7 | 2.56.1-9.el7_9 | 5.3.21-25.el7 | 8.32-17.el7 | zstd 1.5.5-1.el7（EPEL，BSD-3-Clause / GPL-2.0 双许可，取 BSD） |

上游源码为对应的 `.src.rpm`，分别来自 Rocky Linux 9、Rocky Linux 8、CentOS 7.9 归档（及 EPEL 7 归档）。

EL7/EL8 版另外自带 Python 运行环境：

| 组件 | 版本 | 许可 | 上游源码 |
| --- | --- | --- | --- |
| Python（python-build-standalone 构建） | 3.11.10 | PSF-2.0；内含的 OpenSSL、libffi、SQLite、zlib、xz、bzip2、ncurses 等均为宽松许可 | python-build-standalone（github.com/astral-sh/python-build-standalone）发布的 3.11.10 x86_64-unknown-linux-gnu install_only 包（sha256 `8b50a442b04724a24c1eebb65a36a0c0e833d35374dbdf9c9470d8a97b164cd9`），未修改，只删去 IDLE、tkinter、测试等不用的部分；许可原文在包内 `python/lib/python3.11/LICENSE.txt` |
| PyGObject | 3.42.2 | LGPL-2.1-or-later | `PyGObject-3.42.2.tar.gz` |
| pycairo | 1.26.1 | LGPL-2.1-only 或 MPL-1.1 | `pycairo-1.26.1.tar.gz` |
| Boost iostreams（静态链接进 libime） | 1.83.0 | BSL-1.0 | 不要求附源码；boost.org 发布的 `boost_1_83_0.tar.bz2` |
| GCC 运行库（devtoolset-11 / gcc-toolset-12 静态链接部分） | — | GPL-3.0 附 GCC Runtime Library Exception | 不要求附源码 |

## 不随包分发

GTK 3、IBus、gobject-introspection、cairo、字体等由用户系统提供，安装包不含。

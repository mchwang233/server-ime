# 引擎选型与来源

负责人 `employee_id: engine`，调查日期 2026-10-28。完整版本、URL、SHA-256、RPM 签名结果分别在 `dependencies.json`、`vendor.lock.json`、`checks/abi-and-packages.txt`。未运行参考仓库的安装脚本、构建脚本或测试。选择使用已安装的发行版运行库并复制到工作目录，再编写自己的封装；CMake 装配无需 root 或开发头文件。

| 候选 | 固定版本/提交 | 许可 | 调查结果与本次判断 |
|---|---|---|---|
| libpinyin | 2.6.0，19d8e9a1e577fb0d93dc9fb51ea982d677331755；运行包 2.6.0-4.el9 | GPL-3.0-or-later；open-gram 中 Android 派生条目附 Apache-2.0 | 提供拼音解析、整句 N-best、候选、约束、原生学习与导入接口。主机已有匹配的库与词库，C ABI 可由 Python 调用，选择作为当前后端。 |
| librime | Git 快照 56737cd29a4d393a104a2098ece3697aa2810465 | BSD-3-Clause | 可扩展的成熟方案系统；固定 README 列出 Boost、LevelDB、Marisa、OpenCC、yaml-cpp 等依赖。本机未安装 librime；本阶段无需新增这套运行/构建链。作为后续可替换后端的对照，不复制其代码。 |

GitHub 评分脚本按任务提供算法运行：libpinyin 75，librime 81；结果在 checks/github-ranking.jsonl。这只是维护/社区线索，不是转换质量测评。最初两次请求因环境内 GitHub 凭据被服务端拒绝（HTTP 401），之后一次不带凭据的公开查询成功；没有读写凭据文件，也没有在日志保存 token。只读 API 调查固定 commit 后才读源码与许可。

证据来源：

- [libpinyin 固定源码](https://github.com/libpinyin/libpinyin/tree/19d8e9a1e577fb0d93dc9fb51ea982d677331755)，本地 `vendor/libpinyin-2.6.0/`，包括 README、COPYING、pinyin.h/cpp、pinyin_custom2.h 和 opengram.license。
- [libpinyin 发行版对应源码 RPM](https://download.rockylinux.org/pub/rocky/9/AppStream/source/tree/Packages/l/libpinyin-2.6.0-4.el9.src.rpm)，本地完整副本及 `vendor/libpinyin-srpm/` 中 spec/发布源包。spec 表明本版本没有启用 snapshot patch；源包包含完整基础词表与语言模型。
- [librime 固定 README](https://github.com/rime/librime/blob/56737cd29a4d393a104a2098ece3697aa2810465/README.md) 和 [固定 LICENSE](https://github.com/rime/librime/blob/56737cd29a4d393a104a2098ece3697aa2810465/LICENSE)，本地 `vendor/research/`。
- GLib、BerkeleyDB、PCRE 的实际库复制自主机 RPM；对应发行版源码 RPM 下载自 Rocky 官方 BaseOS。全部四个源码 RPM 均通过本机 `rpm -K` 的 digests/signatures 检查。

## 依赖及分发说明

| 依赖 | 版本 | 许可/保留位置 |
|---|---|---|
| libpinyin 及基础数据 | 2.6.0-4.el9 | GPL-3.0-or-later，open-gram 部分 Apache-2.0；vendor/runtime/licenses/libpinyin/ |
| GLib | 2.68.4-19.el9_8.1 | LGPL-2.0-or-later；vendor/runtime/licenses/glib2/ |
| BerkeleyDB | 5.3.28-57.el9_6 | RPM 声明 BSD and LGPLv2 and Sleepycat and MIT；完整 LICENSE 与 LGPL 文本在 vendor/runtime/licenses/libdb/ |
| PCRE | 8.44-4.el9 | BSD-3-Clause；vendor/runtime/licenses/pcre/ |
| 系统运行时（不随包复制） | Python 3.9.25、glibc 2.34、libstdc++/libgcc 11.5.0 | 使用主机系统库，具体 RPM 与符号版本见 abi-and-packages.txt |
| 构建工具（不随包复制） | CMake 3.31.8、make 4.3 | 本任务只用其装配、安装和 CTest 功能 |

新封装采用 GPL-3.0-or-later，与已选 GPL 后端兼容。完整第三方许可和对应源码包随组件包保留；不能在产品分发时只取 `.so` 和词库而丢弃这些文件。此次使用的是发行版锁定版本，不宣称为最新 libpinyin，也没有从网上采集未授权词库。双拼等后续功能不改变这些许可证义务。

主机 `pkg-config --modversion glib-2.0 ibus-1.0 sqlite3 libpinyin` 实际失败，`rpm -q libpinyin-devel glib2-devel` 显示未安装，见 environment.txt。该限制影响从源码重编第三方依赖，但不影响已交付的真实运行路径。未使用假字典替代缺失引擎。

REFERENCE: libpinyin/libpinyin@19d8e9a1e577fb0d93dc9fb51ea982d677331755 license=GPL-3.0-or-later score=75 use=reuse what=C-ABI/runtime/stock-model/corresponding-source

REFERENCE: rime/librime@56737cd29a4d393a104a2098ece3697aa2810465 license=BSD-3-Clause score=81 use=reference what=pinned-README/LICENSE/dependency-comparison

## Lessons

1. 缺开发头文件不等于缺成熟引擎：先检查 RPM 运行库及匹配模型，ctypes 可直接调用经过类型约束的 C ABI。
2. libpinyin 2.6 的候选 offset 是原始拼音位置；部分选词后的 N-best 文本仍为完整句子，显示时需去前缀，提交时不能重复拼接。
3. 候选指针在重算后失效；公开 API 使用会话 nonce 和 revision，避免调用方持有原生对象。
4. 默认 NULL 用户目录避免个人数据加载和学习存盘，但上游会在 stderr 留下一次空用户配置诊断。应如实记录、保持 stdout 协议独立。

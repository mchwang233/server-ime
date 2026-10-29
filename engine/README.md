# 服务器拼音引擎 0.4.0

employee_id: engine。API 1.0 兼容增强：真实 libpinyin 2.6.0 整句/候选、369 条公共词库接入、自然码双拼、10 组可配置模糊音、8 组全拼别名纠错和 4 类单编辑纠错、个人词频/短语及敏感用途隔离。新增保留原文的拼音/英文/数字/符号片段组合，限制扩展搜索的枚举开销；保留原生前三候选及个人学习优先级。全部转换与学习本地处理，无云服务。

```sh
engine/bin/server-ime-engine --capabilities
python3 engine/examples/python_client.py
engine/bin/server-ime-engine < engine/examples/requests.jsonl
# 只在明确提供用户目录时启用个人数据能力；自动学习仍默认关闭
engine/bin/server-ime-engine --user-data-dir "$PWD/engine/build/demo-user"
```

Python：`PYTHONPATH=engine/src`，`from server_ime_engine import Engine`。新建 `Engine(user_data_dir=...)` 后通过 `create_session({"learning": True})`启用自动学习，通过 `add_phrase(text,pinyin,count=50)` 管理用户短语。普通新会话 learning=false。配置、词条管理、用途切换均可通过 JSONL 调用。

接口与接入：[API-v1.md](docs/API-v1.md)、[api-v1.schema.json](api-v1.schema.json)、[EXTENSIONS.md](docs/EXTENSIONS.md)。方案键位、规则及功能矩阵：[FEATURES.md](docs/FEATURES.md)。量化结果、测量边界和未解决项：[QUALITY-PERFORMANCE.md](docs/QUALITY-PERFORMANCE.md)。

## 构建与检查

```sh
cmake -S engine -B engine/build
cmake --build engine/build -j 8
ctest --test-dir engine/build --output-on-failure --output-junit revision-junit.xml
cmake --install engine/build --prefix "$PWD/engine/build/prefix-0.4"
python3 engine/tools/evaluate_mixed_revision.py
```

无 root、无开发头文件、无 pip 依赖。CMake 校验并装配已固定的原生运行库/模型、Python 封装和 lexicon 的未修改源码/数据，不执行第三方构建脚本，不从零编译 libpinyin。产物 `engine/build/server-ime-engine-0.4.0.tar.gz`；Linux x86_64/Rocky 9/glibc 2.34 为实测目标。相同输入支持可重现构建、前缀整体搬迁；安装、升级、回滚及实际桌面装配继续由 delivery/platform 完成。

保留的 0.1/0.2/0.3 包及 `checks/enhancement/`、`checks/quality-revision/` 为不可变对照；新证据在 `checks/mixed-revision/`。新增 405 项音节表由固定后端语法表机械提取，不包含中文词条或评测答案。

基础模型及四份原生依赖对应源码、许可留在 vendor/；新增 lexicon 代码 GPL-3.0-or-later、公共增强数据 CC-BY-4.0，独立包携带 source manifest、GPL 文本和来源署名。详见 [dependencies.json](dependencies.json)、[SELECTION.md](docs/SELECTION.md) 和 `vendor/LEXICON-SOURCES.md`（包内）。不修改用户已有 native 表，兼容入口在临时副本加载。libpinyin 的 NULL 用户目录会向 stderr 输出 `open  failed.`；这是已确认的上游空配置诊断，协议 stdout 独立。

## 后续集成约定

- platform：既有工厂 `server_ime_engine.platform_adapter:create_session` 无参兼容；可用 `create_session(config=...,user_data_dir=...)` 注入产品个人目录，或用 PlatformSession 同签名。set_context 接收原来的 private/purpose/hints；核心再次隔离敏感数据。端口最多 200 候选，核心分页提供完整列表。
- interface：capabilities 开启新增能力；本版双拼仅 ziranma，其他方案明确拒绝。settings 的 fuzzy/correction `{enabled,rules}` 结构已兼容；界面现有 defaults 将 correction 显式关掉，产品应根据设置决定是否覆盖引擎默认。设置试用或应用 learning=true 时须把已带 user_data_dir 的 Engine 传给 apply_engine，不能期待无目录的临时 Engine 存盘。
- lexicon：公开 user_dir 已替代构造期 monkey patch；UserStore 仍是唯一持久写入者。外部词条管理自动刷新；不要求每次学习重建 native/。已有 native/ 派生表的更新仍由 lexicon 管理。
- delivery：用户 store 是产品管理的外部持久目录，升级/卸载默认保留；不可把运行时个人数据装入只读引擎 payload。独立引擎包包含所需 lexicon 源码和公共数据快照；统一装配时避免引入不匹配的另一份 lexicon 版本。

不宣称达到 Windows 11 输入法质量。质量评估继续保留 200 条原始语料的所有失败与不支持输入；词库和答案均未修改。所有检查由 engine 执行，verifies=[]。

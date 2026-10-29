# 词库与学习接入（0.4.0，employee_id: engine）

词库格式、验证、个人数据写入仍归 `lexicon`。引擎消费其 `service.load_base`、`records.validate_entry/check_reading`、`UserStore`，不另造个人数据格式，不调用 `pinyin_train` 或 `pinyin_save`。API 仍为 1.0。

## 模型和排序

默认加载锁定的 libpinyin 2.6.0 原配模型及 `lexicon/data/base/lexicon-v1.jsonl` 的 369 条公共增强记录；独立包内对应 `data/lexicon/`。公共记录经验证后导入内存中的 USER_DICTIONARY。数据文件和词频没有为本次评估修改。

原生 N-best、词频和二元语言模型负责整句及词语排序。显式个人目录中的词条同时导入独立个人上下文，让词条参与整句解码。全串读音精确匹配的用户短语/已学词条排在前面，按累计次数降序，平次数按时间戳、文字排序；单编辑纠错至多两项可排在原生前三前面，首音节约束整句至多两项排在原生前三之后，其余原生候选保持相对顺序；个人精确候选始终最优先，所有候选按文字去重。公开候选 ID/分页/原始输入坐标规则不变。

`Engine.import_dictionary(entries)` 消费 lexicon base record 列表（text、pinyin、count、kind=base、source），不接收文件路径或任意二进制。批次验证并在新上下文导入成功后切换；错误保留旧模型与候选 ID。按 `(text,pinyin)` 合并，最多 20000 条，每条最多 15 字。成功让全部会话 revision 更新、清除部分选词约束，保留原始拼音重算。此方法仅内存有效；产品领域词库应作为版本化 base_lexicon 参数提供。

## 个人目录与持久化

```python
from server_ime_engine import Engine
with Engine(user_data_dir="/explicit/writable/server-ime/learning") as e:
    s = e.create_session({"learning": True})
    r = s.set_input("shishi")
    s.select(r["candidates"]["items"][1]["id"])
    print(s.set_input("shishi")["candidates"]["items"][0])
    e.add_phrase("星河试验站", "xing'he'shi'yan'zhan", count=50)
    s.configure({"learning": False})
```

`user_data_dir` 是 lexicon **store 根目录**，含 meta.json/words.jsonl/lock；若不存在由 UserStore 创建（目录 0700，文件 0600），学习初始关闭。缺省不探测 HOME/XDG，不读写个人目录。`Engine.add_phrase(text,pinyin,count=50)` / `remove_phrase(text,pinyin=None)` 是 UserStore 的管理适配，管理操作不受自动学习开关限制。原生不接受的读音在存储前拒绝，避免留下无法使用的个人库。

每个 Session 的 learning 开关和持久 store 总开关都必须允许，且用途可学习，才记录候选提交。显式创建/配置会话的 learning=true/false 同时更新 store 总开关；缺省创建会话不改总开关，且该会话 learning=false。关闭学习停止**新增记录**，已有个人词条仍可用于普通输入；清除已有条目使用 lexicon 管理/删除接口。其他进程关闭总开关后，本进程 record_commit 的锁内重读也会拒绝写入。

最终候选上屏才记录一次，event_id 交给 UserStore 去重。预编辑、查询、取消、literal 提交、核心部分选词不会记录。平台端口实际接受部分应用提交时，适配器只记录被提交前缀；之后 remaining 转换独立进行。双拼/纠错记录解析得到的规范全拼，不能确认完整音节或字数不匹配时不学习，并返回原因。由于 lexicon 最大词长 16，超过 16 字的整句仍正常提交，但不会作为整条个人词条保存。

成功提交事件新增 `learning: {recorded,reason,...}`；存储锁冲突/读音验证失败等返回非记录原因，**不丢失应提交文字**。存盘由 lexicon 原有锁与原子文件替换实现，数据恢复/导入/导出仍用 lexicon 的接口与约定。未改变其两个文件的事务及崩溃恢复能力。

每次引擎操作检查 meta 的 inode/mtime/size；变化后通过 UserStore 快照重读、重建内存个人上下文，后续候选立即可见。可显式 `reload_lexicon()` 强制刷新。学习后首次按键包含该重建时间，已单列测量。其他会话的候选凭据会随共享数据刷新失效，调用方应重新取候选。重启保留排序数据和 store 总开关，但新会话仍默认 learning=false，产品设置应显式重放。

16 字个人短语受上游 native import 的 `<16` 限制，以精确全串候选提供；不会进入原生子句组合。1–15 字短语进入原生上下文。此边界在功能检查中有真实用例。

## 隐私与用途

`Session.set_context(private=False,purpose="text",hints=0)` 消费框架的用途信号。private、密码/PIN、credential/secret 等非普通用途、未知用途或 hints 的 bit 11 均禁用个人候选与学习；普通可学习用途是 text/free_form/alpha/terminal/normal，或 IBus 数值 0/1/10。数字、电话、邮箱、URL 等保守使用公共模型。

敏感会话始终绑定**独立公共模型**，既不使用个人词条，也不写学习记录。切换用途清空原预编辑并使旧候选 ID 失效。公共转换仍可供调用方使用；密码框按键直通由平台控制。适配器把现有 InputContext 的 private/purpose/hints 原样交给此方法。IBus PRIVATE 提示含义参见 [官方接口文档](https://ibus.github.io/docs/ibus-1.5/ibus-ibustypes.html#IBusInputHints)。本机较旧 GI 不暴露符号时仍保守识别 bit 11。

## 已构建的 native 用户表

为兼容 lexicon.engine.open_engine，新增 `Engine(user_dir=...)`：它指 **native 表目录**，与 user_data_dir 不同。先检查 format 6/model 14，然后把允许的表文件复制到独立临时目录再初始化，避免上游 check_format 对原文件做清理。仅接收本项目锁定版本产生的可信表；不接收陌生 ABI/二进制。此表只读快照、没有自动重建或自动学习；建议正常产品使用 UserStore，而非混用两种目录。原始表哈希不变有检查证据。

## 输入方案与规则

自然码（ziranma）由 libpinyin 原生 DOUBLE_PINYIN_ZRM 实现，默认全拼不变。模糊音的 10 组和全拼纠错的 8 组名单、用例见 [FEATURES.md](FEATURES.md)。每会话重设上下文选项，避免多个会话相互污染。纠错不用于双拼键码；双拼音节仍可用模糊音。0.3.0 起支持单编辑纠错：相邻换位、插入、删除、QWERTY 邻键替换，只在 5–64 个无分隔字母且不能完整切分为有效音节时生成，生成至多 8 个完整读音，0.4.0 最多解码前 4 个；有效拼音、多处错误、跨音节换位和词义推断不保证修复。405 项音节表来自固定上游语法。辅助解码实例与当前会话使用同一个公共/个人上下文；每次切换用途、词库或关闭会话都会释放，查询结果不写入全局缓存或磁盘。纠错选择使用候选的规范全拼学习，存储前继续通过 lexicon 字数/读音检验。

## 组合输入学习

`set_composition` 的候选包含拼音转换和原文片段；只把已确认读音的中文片段交给同一 UserStore，英文、数字、邮箱、网址原文不进入学习文件。整段提交事件的 learning.segments 列出每段真实记录结果；每个片段的 event_id 是本次提交 ID 加序号。部分预编辑选择累计片段，到实际提交才写盘；literal 提交不学习。敏感用途先清空组合缓存并重绑公共模型，读写双重门控同旧接口。细节见 MIXED-INPUT.md。

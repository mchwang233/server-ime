# 能力与功能检查矩阵

employee_id: engine；API 1.0；组件 0.4.0；真实后端 libpinyin 2.6.0。

| 能力 | 入口/范围 | 真实检查 |
|---|---|---|
| 全拼整句、候选排序 | N-best + 词频/二元模型；最多 128 个原始字符 | nihaoshijie → 你好世界；非首选及部分选词、编辑、分页、候选凭据生命周期 |
| 自然码双拼 | schema=double_pinyin，double_pinyin_scheme=ziranma | nihk → 你好；vswf → 中文；uurufa → 输入法；nihkuijx → 你好世界；xian → 西安；aa/ee 零声母 |
| 公共词库 | 369 条 lexicon 数据，原生内存表 | 逐条通过原生导出迭代器核对文字及读音集合；源文件哈希不变 |
| 内存领域导入 | Engine.import_dictionary(entries)，lexicon base record | 全批验证、失败状态不变、成功候选失效并重算 |
| 候选学习 | 显式 user_data_dir + learning=true | shishi 选择非首选，下次首选改变；关闭并重启后排序仍在 |
| 用户短语 | add_phrase/remove_phrase；外部 UserStore 管理 | 新增后立即候选生效、外部新增/删除自动刷新、16 字短语可精确提交 |
| 关闭学习 | Session.configure({learning:false}) | 对候选提交/查询/取消/重放比较整个 store 文件哈希，无新增记录；其他会话也受总开关约束 |
| 敏感用途 | set_context，平台 InputContext | private/password/PIN/数值 8、9/credential/未知用途/hint bit 11；无个人候选、无写入、旧候选失效 |
| 异常存储 | UserStore 锁冲突、原生不支持读音 | 提交文字保留；写入失败原因可见；不支持的手工短语拒绝且不污染 store |
| 向后兼容 | API 1.0 字段/方法、JSONL、平台工厂 | 原 16 项检查继续通过（仅把“尚不支持双拼”反例改成未知 schema）；既有增强 20 项、质量扩展 6 项 |

模糊音配置 `{"fuzzy":{"enabled":true,"rules":["l_n"]}}`；rules=[] 且 enabled=true 表示开启下表全部规则，默认关闭。规则匹配有效拼音音节，不把无效拼写自动当成方言。例如 fe 不是合法音节，f_h 不保证把 fe 改成 he。

| 规则名（双向） | 开启后新增/提升的前五候选示例 |
|---|---|
| c_ch | cifan → 吃饭 |
| s_sh | sijie → 世界 |
| z_zh | zongwen → 中文 |
| f_h | fanguo → 韩国 |
| g_k | geji → 科技 |
| l_n | lihao → 你好 |
| l_r | lemen → 热门 |
| an_ang | banmang → 帮忙 |
| en_eng | shenri → 生日 |
| in_ing | beijin → 北京 |

纠错配置 `{"correction":{"enabled":true,"rules":["gn_ng"]}}`；默认 enabled=true、rules=[]，即下表全部。只作用于全拼，所有规则都有开/关和实际选词提交用例。

| 规则名（定向别名） | 输入 → 候选 |
|---|---|
| gn_ng | zhognwen → 中文 |
| mg_ng | zhomgwen → 中文 |
| iou_iu | liou → 六 |
| uei_ui | shuei → 水 |
| uen_un | luen → 论 |
| ue_ve | nue → 虐 |
| v_u | jv → 据（j/q/x/y 的 ü/u 拼写） |
| on_ong | zhonwen → 中文 |

自然码声母 ch/sh/zh 对应 i/u/v；主要韵母键：b=ou、c=iao、d=uang/iang、f=en、g=eng、h=ang、j=an、k=ao、l=ai、m=ian、n=in、o=uo/o、p=un、q=iu、r=uan/er、s=ong/iong、t=ue、v=ui/v、w=ia/ua、x=ie、y=uai/ing、z=ei；a/e/i/u 保持字面。零声母遵循原生自然码回退表：aa/a、ai、an、ah/ang、ao、ee/e、ei、en、er、oo/o、ou。

检查命令：`python3 engine/tests/test_engine.py`、`python3 engine/tests/test_enhanced.py`、`python3 engine/tests/test_quality_revision.py`；CTest 统一运行。输出见 `checks/mixed-revision/compatibility.log`、`functional.log`、`feature-matrix.json`。质量与性能差距见 [QUALITY-PERFORMANCE.md](QUALITY-PERFORMANCE.md)。这些正反例只存在于检查代码，不加入发布词库。

REFERENCE: libpinyin/libpinyin@19d8e9a1e577fb0d93dc9fb51ea982d677331755 license=GPL-3.0-or-later score=75 use=reuse what=pinned native parsing/options/dictionary ABI; original upstream notices and sources retained in vendor/.

## 0.3.0 起的通用质量改进

| 规则/能力 | 范围与检查 |
|---|---|
| transpose | 同一音节内相邻字母换位；huanyingguanglni → 欢迎光临 |
| delete | 删除多余字母，优先重复字母；shanghaiijiaotong → 上海交通 |
| insert | 补一个字母使音节完整；shanghijiaotong → 上海交通 |
| substitute | 同/相邻 QWERTY 行列的邻键替换；huanyingguanglim → 欢迎光临 |
| 整句候选扩展 | 四音节起的完整全拼，用两个不同首音节汉字约束重算全句；原生前三保持顺序，新增候选可实际整句提交 |
| 纠正读音学习 | 选择 shanghaiijiaotong 的上海交通存为 shang'hai'jiao'tong，重启后对正确拼写生效；关闭学习整目录哈希不变 |
| 辅助解码敏感隔离 | 个人短语可由纠错解码召回；password/pin/未知用途切换后不能召回，提交无存盘 |

单编辑规则仅用于无法由 405 项完整音节切分的 5–64 个字母，不作用于有效完整拼写、显式分隔符、双拼键码或多处错误。使用前后完整音节路径复用，生成至多 8 个拼写假设，按拼写先验最多解码前 4 个读音。拼写代价优先，相同代价用后端词频的每字对数分数排序：它是词汇先验启发式，不是可访问的完整语言模型得分。不会改变原始输入、光标、部分选择坐标；仅选中纠错候选才按规范读音提交/学习。

来源 `data/syllables-v1.json`：从固定 libpinyin pinyin_parser_table.h 的 IS_PINYIN 项中剔除 INCOMPLETE/CORRECT，再排序去重。无中文词条、频次或评估引用。来源散列、GPL-3.0-or-later 许可记录在文件自身和 dependencies.json。

## 0.4.0 组合输入和搜索界限

新增 `set_composition` / `input_text`，原入口保持兼容。独立的 12 条逐键用例验证英文大小写、版本号、数字、邮箱、URL、路径、中文片段、自然码混输和大小写/连续小写歧义候选。9 项测试另覆盖编辑、数字选择、分段提交、原文往返、旧候选拒绝、原文不学习和敏感用途缓存隔离。见 [MIXED-INPUT.md](MIXED-INPUT.md) 与 `checks/mixed-revision/composition-features.json`。

原生解析和全串整句 N-best 使用所有配置规则。局部词语枚举限制在 24 个原始码点窗口；长于窗口的词语可能不作为部分候选出现，但整句及个人全串精确候选仍可选。纠错从全部启用规则生成候选，最多解码四个读音；两条首音节整句扩展保留。纠错通过末尾位置读取 N-best，免去整串词语枚举；首音节约束的词语枚举只使用前两个音节。未关闭模糊音、纠错、学习、双拼或整句功能，没有以测试词句设置例外。原生调用不可中途取消，50 ms 为测量目标而非硬时限，实测超时见性能报告。

# 拼音与原文片段（API 1.0 兼容扩展）

employee_id: engine；组件 0.4.0。旧客户端的 `set_input` 校验、大小写归一化和候选凭据规则不变。新客户端先检查 `capabilities.features.mixed_input`，再使用以下入口：

```python
with Engine() as engine:
    session = engine.create_session()
    state = session.set_composition("nihaoLinux6.1")
    assert state["input"]["text"] == "nihaoLinux6.1"
    event = session.commit()["commits"][0]
    assert event["text"] == "你好Linux6.1"
```

`set_composition(text, cursor=None)` 设置完整原文并进入组合模式；`input_text(text)` 在光标处插入并进入组合模式。二者也通过 JSONL 同名 op 开放，参数、错误形式和 session_id 规则与旧方法相同。最多 128 个 Unicode 码点，允许可打印字符，拒绝控制字符、换行和孤立代理码点。大小写、空格、数字、Unicode 及实际输入的符号逐字保留。`set_input` 显式回到旧拼音模式。组合模式下 `input/edit`、光标和删除键使用原文坐标；重置保留输入模式，清空内容及选词；编辑撤销部分选词并失效旧候选。

新增 `state.composition={mode,spans,literal_digits}`：mode 是 pinyin/mixed，spans 是完整原始输入的 `{start,end,kind,text}` 列表（kind=pinyin/literal）；literal_digits 提示当前光标处数字是原文还是选词。这里的 spans 属于原始输入坐标，原有 preedit.segments 继续属于显示文本坐标。组合模式 parsed_length 表示被片段处理覆盖的原文长度（包含原文片段），unparsed 为空；旧模式字段的原生解析含义不变。

组合候选仍使用 sentence/phrase 两种 kind；可增加 input_end（原始消费终点，需实际选择才能确定时为 null）和 literal 布尔提示。ID 仍绑定会话、revision 和候选索引，焦点用途变化、输入编辑、词库刷新、配置变化都使旧 ID 无效。

## 边界与歧义

分段依赖大小写、数字、符号以及网址/邮箱/路径的通用结构，不包含英文词表、产品名或评估答案。小写拼音片段使用完整的当前配置：词库、个人排序、自然码/全拼、模糊音和纠错全部生效。原文片段没有大小写转换、拼写替换或标点补全。例如 `nihao User+Tag@Example.org` 可选 `你好 User+Tag@Example.org`；空格及地址中的大小写和符号原样存在。`nihaoAPI2shijie` 可选 `你好API2世界`。

连续小写有真实歧义：`xian` 既能作为拼音，也能作为原文；`nihaohello` 同时保留原文、中文猜测及 `你好hello` 等候选。对无法完整切分的小写串，最多尝试两个完整拼音前缀和两个后缀；只改变一个片段生成整段候选，避免片段组合数相乘。不能保证无分隔的小写中英边界自动判断正确；超过此搜索范围时用户可先选择中文前缀，再提交剩余原文。每次始终有整段原文候选，Return/literal 提交也是确定的原文路径。不恢复未输入的 @、点号、大小写或丢失的英文拼写。

整体首选按每段默认候选组合；多片段的整段原文靠前保留；单个拼音片段保留旧引擎前五的顺序，然后提供原文和组合选项；另提供首个未选片段的部分候选。最多 200 项。已选中文前缀保留在预编辑，例如 `nihaoLinux6.1shijie` 依次选“你好”、“Linux6.1”、“世界”，核心只在最终提交一次“你好Linux6.1世界”。纯原文和混合结果都可以显式选择，不能把“看上去像拼音”当作不可撤销的自动替换。

## 按键及平台端口

核心 `key` 在组合模式下接受可打印字符。space 是选择键、Return 是原文提交；要插入空格调用 input_text。数字 1–9 在纯拼音位置保持原有选词语义，在原文片段内/边界插入；输入为空时数字也是原文。`input_text("2")` 始终插入数字，即使前面是纯拼音。完全相同的数字按键不能同时表达“选第二项”和“插入 2”，客户端应使用 literal_digits、显式选词动作（鼠标或 select）和文本插入入口区分；用户也可先选中文，再继续数字。不要把所有数字都当选词键。

`PlatformSession.convert(composition,cursor)` 签名不变，内部改用 set_composition；返回的 Conversion 追加 `literal_digits: bool=False`。Candidate/Selection 既有字段和 factory 保留。平台仍拥有按键分类、焦点及最终应用提交：需把大小写/数字/标点原样传入 convert，并根据 literal_digits 分流数字；原有 set_context 必须在输入前传用途。引擎的适配器检查只证明该端口返回内容，不等同于 IBus/GTK/浏览器实际链路已接通。

平台端口选择部分候选时，`Selection(commit,remaining,cursor)` 继续立即提交选中前缀，并返回未消费的**原始文本**；例如选“你好”得到 commit=你好、remaining=Linux6.1shijie、cursor=0。之后平台重新 convert remaining。核心 Session 的部分选词仍只保留预编辑。这两种已发布语义分别保留。

## 学习及敏感用途

组合候选只学习有确定读音的中文片段，不保存原文 token。learning=false 不新增记录；已学排序仍可用于普通用途。敏感用途/private/hint bit 11 清空缓存、废弃候选并绑定公共模型；所有片段的学习也会被拒绝。最终事件仍只有一次 text 提交，learning.segments 是各中文片段的实际写入结果。管理 API、外部词库刷新和重启持久化约定不变，user_data_dir 指向产品的 `<产品数据目录>/learning`。

检查：`python3 engine/tests/test_composition.py`。独立 12 条实际逐键行为数据在 `data/mixed-keystrokes-v1.json`，逐键状态及最终选词在 `checks/mixed-revision/composition-features.json`；未把这些测试文本加入任何词库。原冻结混合语料及原评分完整保留，不能用这 12 条行为检查替代原 200 条质量分母。

## English words (0.1.11)

`engine/data/english-v1.txt` holds about 30,000 common English words, most frequent first:
FrequencyWords 2018 `en_50k` (OpenSubtitles, CC-BY-SA-4.0, github.com/hermitdave/FrequencyWords)
kept where hunspell `en_US` accepts them, plus a short list of product and tech terms with
their usual spelling (GitHub, iPhone, JSON). `english.py` looks words up and finds one-typo
corrections; `Composer.english` places them for a single lowercase fragment:

| input | example | English candidate |
|---|---|---|
| not pinyin, a word | hello, github | first (second for three letters) |
| pinyin being typed, a word | went | second |
| complete pinyin, a word of 2+ syllables | women, china | last on the first page |
| complete pinyin of one syllable | wang, gong | none |
| not pinyin, one typo from a common word | pyhton, recieve | second and third |
| pinyin and words in turn | woyongdockerbushu | 我用Docker部署 first |

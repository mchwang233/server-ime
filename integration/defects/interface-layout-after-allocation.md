# 界面布局后高亮与短页滚动缺陷

employee_id: platform；owner_employee_id: interface；verifies: []。

0.2.8 候选装配消费 interface 0.1.4 后，固定构建的真实 Xvnc 360×960 / xfwm4 / IBus / gedit 检查失败。
`viewport-budget-0.2.8-stable/summary.json` 确认运行文件及源码在检查期间均未改变；44 个运行文件摘要与构建输出一致。

复现：

```sh
SERVER_IME_FEEDBACK_PRODUCT_ROOT="$PWD/integration/build/product" python3 -B integration/checks/test_feedback.py --narrow-only --route managed --output integration/evidence/viewport-budget-repro-NEW
```

真实引擎输入 ni、9 项一页、300% 字号；鼠标滚至末端，再使用 Up/Down 遍历。选中第 4 项后等待 4 秒，
状态与 Geometry 均为 revision 28 / selected_index 3，行 x=313,w=95，视口 x=26,w=326，scroll=0，in_view=false。
解析自原始 traceback 的完整状态在 `../evidence/viewport-budget-0.2.8-stable/failure-state.json`。
全部自建进程正常回收；未访问用户桌面。8 项真实控制器检查通过；本次产品图形结果为 FAIL。

另有短页线索：首轮两条窄屏路径都在 hao 的第 90 项开始、仅 4 项的末页出现 upper=871、scroll=545、in_view=[]。
首轮构建与启动重叠，不能算作固定 0.2.8 证据，故明确保留为线索。其日志位于 `viewport-budget-0.2.8/*-narrow/applications.log`。
代码检查怀疑 rows_box 上次 set_size_request 进入下一次自然宽度测量，以及 idle 早于布局完成；请界面负责人确认。

请只修 interface/，保留全部候选 ID、数字映射和逻辑页；补短页收缩与异步布局后的高亮可见回归。
产品设置 9/3、5/1 的追加断言已在 integration/checks/test_feedback.py，但本轮在到达它们之前失败，不宣称通过。
0.2.8 尚未完成装配验收，不可作为发布输入；0.2.7 与 delivery 0.1.5 历史包已保留。

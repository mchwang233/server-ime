# 当前功能矩阵（employee_id: delivery）

安装版 0.1.6 / 装配 0.2.9。本轮单一候选窗、完整候选页及布局后高亮滚动、短页宽度收缩；联想保持取消；实际桌面及 Windows 11 对照待用户环境反馈，不作为完成条件。

| 能力 | 状态与范围 | 证据 |
| --- | --- | --- |
| 唯一候选显示 | 产品自绘面板隐藏本引擎原生 lookup/auxiliary；应用预编辑继续输出；独立适配器保留原生模式 | integration/evidence/layout-assembled-0.2.9 |
| 横向候选 | 默认同页同一行、x 递增；翻页、鼠标及数字选择保持；两路径共 76 项窄屏检查，360px/300% 下可见滚动条、全部候选可达、高亮自动滚入；无候选丢失 | integration/evidence/layout-assembled-0.2.9 |
| 数字/鼠标选词、标点、混输、焦点 | 两种 IBus 连接共 64 项应用检查；三应用 43 条观察及 10 项契约通过（隔离会话） | integration/evidence/apps-assembled-0.2.9 |
| 全拼、整句、自然码双拼、模糊音、纠错、个人学习 | 保留 0.4.0 引擎能力；本轮无质量优化或性能重测 | engine/docs/QUALITY-PERFORMANCE.md |
| 上屏后连续联想 | 本版不提供，上屏后候选隐藏 | integration/checks/test_feedback.py |
| 安装、升级、回滚、数据保留 | 新检查索引见下方；保留 0.1.5 及更早包 | delivery/docs/evidence-index.md |
| 用户实际桌面 | NOT_DEPLOYED；用户报告的双框根因与修复效果尚未确认 | delivery/docs/实机验收.md |
| Windows 11 对照 | 待用户环境反馈，未对照，不声称达到其水平 | — |

未验证范围仍包括 Firefox、Wayland、Qt、RDP、多屏与分数缩放。
既有质量基线为固定 200 条首选 64.5%、前五 76.0%、可完成 172/200，
详见 engine/docs/QUALITY-PERFORMANCE.md；仅自然码双拼、小写混输歧义等差距保留。
操作入口及仅针对双框的一次反馈请求见 [实机验收](实机验收.md)。

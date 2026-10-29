# 当前发布证据（employee_id: delivery）

0.1.6 / 装配 0.2.9，单一候选窗、完整候选页及布局后高亮滚动、短页宽度收缩；历史包与历史证据保留。
版本锁 manifest/lock.json；摘要 dist/SHA256SUMS。

| 检查 | 证据 |
| --- | --- |
| 构建安装包及对应源码 | delivery/evidence/layout-release-0.1.6/build.json |
| 45 运行文件、源码、旧包不变 | delivery/evidence/layout-release-0.1.6/content.json |
| 0.1.5 → 0.1.6 → 0.1.5；外部配置和词库逐字节保留 | delivery/evidence/release-20261029T055730Z/summary.json |
| 真实个人词库添加、导出、移除、导入、重载 | delivery/evidence/layout-release-0.1.6/learning-roundtrip.json |
| 对应源码独立重建摘要一致 | delivery/evidence/layout-release-0.1.6/source-rebuild-match.json |
| 当前产品清单 | delivery/evidence/layout-release-0.1.6/product-manifest.json |
| 两组应用检查运行文件绑定 | integration/evidence/layout-assembled-0.2.9/tested-runtime-hashes.json |
| 搬迁、装配 115 文件 | integration/checks/feedback-inventory.json |

应用证据归平台所有：integration/evidence/layout-assembled-0.2.9（两种 IBus 连接、64 项应用检查、76 项窄屏检查）；
integration/evidence/apps-assembled-0.2.9（三应用 43 条观察、10 项契约）。
用户桌面 NOT_DEPLOYED，实际双框效果待反馈。联想保持取消；Windows 11 对照待用户环境反馈；
不据隔离检查宣称用户问题已解决。操作入口见 [实机验收](实机验收.md)。

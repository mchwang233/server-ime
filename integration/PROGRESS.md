# 集成完成记录 / employee_id: platform

本步骤的可执行交付已完成，真实应用覆盖为 PARTIAL。统一入口 integration/bin/server-ime。
生产链路为 engine 0.3.0 / libpinyin、lexicon.UserStore、interface 面板/设置、platform IBus。
配置事务、学习恢复、候选位置、精确快捷键、标点和进程恢复已接入。运行包排除测试后端。

源码整轮：integration/evidence/run-20261028-201440。
装配目录整轮：integration/evidence/run-20261028-201830。
21 项平台/装配单测通过；10 项真实产品契约场景通过；终端和 gedit 实际输入通过。
Firefox 独立配置加载失败，未开始网页输入检查；用户实际 TigerVNC 会话受权限限制未连接。
上述两类限制均保留为未验证，不宣布用户部署完成。

最终交接、全部缺口、追加读取文件和证据入口：integration/handoff.json。
产品清单与 SHA256：integration/build/component-delivery.json、server-ime-product-0.1.0.tar.gz.sha256。
原 interface-defects.json 保留委派前复现；真实能力校验及保存回调修复已消费并在产品链路通过。
新观察到的 interface resolve 辅助函数问题另交接在 checks/interface-resolver-observation.json；
产品按键层消费 Binding 做精确修饰位匹配，不调用该辅助函数。

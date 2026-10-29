"""employee_id=delivery: publish display-only 0.1.6 references; preserve historical artifacts."""
import json
from pathlib import Path
D=Path(__file__).resolve().parent
E=D/'evidence/layout-release-0.1.6'
def read(p):return json.loads(p.read_text())
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
r=read(D/'build/0.1.6/build.json')
assert read(D/'manifest/lock.json')['assembly_version']=='0.2.9'
ev=Path(next(x[10:] for x in (E/'lifecycle.log').read_text().splitlines() if x.startswith('evidence: ')))
lifecycle=read(ev/'summary.json')
assert lifecycle['result']=='PASS' and all(x['ok'] for x in lifecycle['steps'])
assert lifecycle['upgrade_package']['sha256']==r['package']['sha256']
relative=str(ev.relative_to(D.parent))
p=D/'manifest/product-manifest.json';m=read(E/'previous-product-manifest.json');m['product']['version']='0.1.6';c=m['components'][0]
c.update(version='0.1.6',bundle='../dist/server-ime-0.1.6.tar.gz',sha256=r['package']['sha256'],notes='装配 0.2.9：单一候选窗、完整候选页及布局后高亮滚动、短页宽度收缩；用户桌面未部署')
c['included_components'][-1]['version']='0.2.9'
for component in c['included_components']:
    if component.get('id')=='interface': component['version']='0.1.5'
c['artifacts'].update(manifest='../dist/server-ime-0.1.6.component-manifest.json',manifest_file_sha256=r['package']['manifest_sha256'],sources='../dist/server-ime-0.1.6-sources.tar.gz',sources_sha256=r['sources']['sha256'],sources_bytes=r['sources']['bytes'],build_record='../build/0.1.6/build.json',content_check='../evidence/layout-release-0.1.6/content.json')
c.pop('upgrade_test_package',None);write(p,m)
h=read(E/'previous-handoff.json')
h['task']='发布 0.1.6 / 装配 0.2.9：单一候选窗、完整候选页及布局后高亮滚动、短页宽度收缩'
h['provides']['packages']=[r['package'],r['sources']]
h['historical_packages']=list(read(E/'historical-hashes.json'))
h['checks']={'content':'delivery/evidence/layout-release-0.1.6/content.json','lifecycle':relative+'/summary.json','learning':'delivery/evidence/layout-release-0.1.6/learning-roundtrip.json','source_rebuild':'delivery/evidence/layout-release-0.1.6/source-rebuild-match.json'}
h['deployment'].update(user_session='NOT_DEPLOYED',evidence=relative+'/session-enablement.json',enable_steps='delivery/docs/实机验收.md',reason='本步骤不访问用户桌面授权文件或共享套接字，仅做隔离安装检查')
h['acceptance']={'real_desktop':'PENDING_USER_FEEDBACK','windows11':'PENDING_USER_ENVIRONMENT','prediction':'CANCELLED_OUT_OF_SCOPE','feedback_request':'安装版本、双框应用及版本、启动方式、两框内容或去隐私截图、升级后是否复现、期望的联想示例、可用 Windows 11 环境'}
h['reuse_policy']='反馈检查 44 个、全应用检查 45 个运行文件逐字节绑定 integration/evidence/layout-assembled-0.2.9 及 integration/evidence/apps-assembled-0.2.9；隔离通过不代表用户问题已解决。'
h['additional_reads_this_revision']=['delivery/bin/ime-build','delivery/bin/ime-release-check','delivery/tests/check_feedback_release.py','delivery/tests/check_learning_roundtrip.py','integration/handoff.json','integration/evidence/layout-assembled-0.2.9/tested-runtime-hashes.json','integration/checks/feedback-inventory.json','integration/evidence/layout-assembled-0.2.9/tested-runtime-hashes.json','integration/evidence/apps-assembled-0.2.9/tested-runtime-hashes.json']
h['additional_reads_reason']='任务未附实现正文；补读现有打包/检查实现和新装配证据，以复用工具和绑定运行文件。'
h['additional_reads_this_revision'] += ['integration/tools/build_product.py','interface/config/defaults.json']
h['verifies']=[];write(D/'handoff.json',h)
(D/'docs/evidence-index.md').write_text('''# 当前发布证据（employee_id: delivery）

0.1.6 / 装配 0.2.9，单一候选窗、完整候选页及布局后高亮滚动、短页宽度收缩；历史包与历史证据保留。
版本锁 manifest/lock.json；摘要 dist/SHA256SUMS。

| 检查 | 证据 |
| --- | --- |
| 构建安装包及对应源码 | delivery/evidence/layout-release-0.1.6/build.json |
| 45 运行文件、源码、旧包不变 | delivery/evidence/layout-release-0.1.6/content.json |
| 0.1.5 → 0.1.6 → 0.1.5；外部配置和词库逐字节保留 | '''+relative+'''/summary.json |
| 真实个人词库添加、导出、移除、导入、重载 | delivery/evidence/layout-release-0.1.6/learning-roundtrip.json |
| 对应源码独立重建摘要一致 | delivery/evidence/layout-release-0.1.6/source-rebuild-match.json |
| 当前产品清单 | delivery/evidence/layout-release-0.1.6/product-manifest.json |
| 两组应用检查运行文件绑定 | integration/evidence/layout-assembled-0.2.9/tested-runtime-hashes.json |
| 搬迁、装配 115 文件 | integration/checks/feedback-inventory.json |

应用证据归平台所有：integration/evidence/layout-assembled-0.2.9（两种 IBus 连接、64 项应用检查、76 项窄屏检查）；
integration/evidence/apps-assembled-0.2.9（三应用 43 条观察、10 项契约）。
用户桌面 NOT_DEPLOYED，实际双框效果待反馈。联想保持取消；Windows 11 对照待用户环境反馈；
不据隔离检查宣称用户问题已解决。操作入口见 [实机验收](实机验收.md)。
''')
print('0.1.6 references synchronized')

# 源码包使用与重建（employee_id: delivery）

将安装包、源码包及 SHA256SUMS 保存到本地。源码包含项目 Python 源码、构建脚本、
安装工具、词库输入、锁定运行依赖以及第三方对应源码 tar/src.rpm；不含浏览器测试发行包、
历史证据、个人数据或测试运行目录。依赖的系统 Python 3.9+、GI/GTK3/IBus 仍由运行系统提供。

```sh
mkdir -p source
tar -xzf server-ime-0.1.6-sources.tar.gz -C source
cd source
python3 delivery/bin/ime-build --version 0.1.6 --note "装配 0.2.9：单一候选窗、完整候选页及布局后高亮滚动、短页宽度收缩"
(cd delivery/dist && sha256sum -c SHA256SUMS)
python3 delivery/bin/ime-install install delivery/dist/server-ime-0.1.6.tar.gz \
    --prefix "$HOME/.local/opt/server-ime" --data-dir "$HOME/.local/share/server-ime"
```

构建入口只写 delivery；独立 --out/--work 不更新正式锁。正式锁中的 path_base=delivery，
package/sources/build_record 均相对此目录解析；产品清单 path_base=manifest-directory。
重建使用包中锁定的运行依赖，不要求现场编译 GTK/IBus。上游重新编译材料及版本锁位于
engine/vendor、engine/vendor.lock.json，项目引擎构建入口为 engine/CMakeLists.txt。

安装后的中文说明：<prefix>/ime/current/share/ime/docs/README.zh_CN.md。
安装、诊断、回滚与卸载工具可直接用源码包 delivery/bin 中的命令；生命周期说明及隐私说明
位于 delivery/docs。完整交付证据与版本清单保存在原发布目录，不嵌入源码包以避免自引用。

所有 start/exec/settings/config/status/stop 命令必须使用相同 --state-dir。
真实桌面保持 NOT_DEPLOYED；实际双框效果待用户反馈；联想及 Windows 11 对照待用户环境反馈；Wayland 和系统安装仍未验证。

源码包内 integration/handoff.json 将历史包摘要保留在 distribution_history_not_required，
historical_packages 为空：独立重建不依赖历史二进制包；原发布目录仍保留并校验全部历史包。

"""用户级输入法安装/升级/回滚/卸载工具（delivery 模块）。

不依赖 root、系统服务或受限用户目录；所有写入都限定在显式指定的前缀与
运行数据目录内。组件交付清单（component manifest）定义见 manifest/README.md。
"""

TOOL_VERSION = "0.1.0"
TOOL_NAME = "ime-install"

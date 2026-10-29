"""服务器输入法界面包（employee_id=interface）。

模块：
* config      设置格式 v1、校验、原子读写、引擎/平台映射
* keymap      快捷键格式、冲突与非法绑定校验、按键解析
* punctuation 中文标点映射表
* panel       候选面板 + 中/英/后端状态提示（消费平台 D-Bus 接口）
* settings_ui 中文设置界面（按引擎能力显示控件）
* bridge      平台 StateClient 的薄封装
"""
__version__ = "0.1.0"

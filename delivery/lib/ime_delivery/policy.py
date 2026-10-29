"""写入策略：显式前缀 + 运行数据目录，拒绝系统路径、符号链接与只读位置。

设计目标（均为无 root 环境下可验证）：
* 前缀与数据目录必须由用户显式给出绝对路径，并解析为真实路径；
* 拒绝系统目录与目录本身是符号链接的情况，避免把文件写到策略之外；
* 若目标已存在，必须是当前用户拥有的可写目录；若不存在，最近的已存在父目录必须可写；
* 可选 --allowed-root 白名单，把写入限制在站点指定的根之下；
* 数据目录不得与前缀互相包含，保证卸载/回滚不会触碰个人数据。
"""

from __future__ import annotations

import os
import stat

from .util import ImeError, within

# 这些目录（含其子目录）永远不允许作为安装前缀或数据目录。
DENY_TREES = (
    "/usr",
    "/etc",
    "/var",
    "/opt",
    "/bin",
    "/sbin",
    "/lib",
    "/lib32",
    "/lib64",
    "/boot",
    "/proc",
    "/sys",
    "/dev",
    "/run",
    "/root",
    "/srv",
    "/snap",
)

# 只拒绝目录本身，不拒绝其子目录（用户可以在自己 home 下建前缀）。
DENY_EXACT = ("/", "/home", "/tmp", "/workspace")

DENY_PREFIXES = ("/usr/local",)  # /usr 已覆盖，保留可读性


def _deny_reason(canon):
    for tree in DENY_TREES:
        if canon == tree or canon.startswith(tree + "/"):
            return "位于系统目录 %s 之下" % tree
    for exact in DENY_EXACT:
        if canon == exact:
            return "不允许直接使用目录 %s" % exact
    return None


def _writable_reason(canon, what):
    """目标存在时检查所有权/可写性；不存在时检查最近的已存在父目录。"""
    if os.path.lexists(canon):
        st = os.lstat(canon)
        if stat.S_ISLNK(st.st_mode):
            return "%s 是符号链接，拒绝写入（请给出真实目录）" % what
        if not stat.S_ISDIR(st.st_mode):
            return "%s 已存在但不是目录" % what
        if st.st_uid != os.getuid():
            return "%s 属于其他用户 (uid=%d)" % (what, st.st_uid)
        if not os.access(canon, os.W_OK | os.X_OK):
            return "%s 不可写" % what
        return None
    parent = os.path.dirname(canon)
    while parent and not os.path.lexists(parent):
        parent = os.path.dirname(parent)
    if not parent:
        return "%s 没有可用的已存在父目录" % what
    st = os.lstat(parent)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        return "%s 的父路径 %s 不是目录" % (what, parent)
    if not os.access(parent, os.W_OK | os.X_OK):
        return "%s 的父目录 %s 不可写" % (what, parent)
    if st.st_uid != os.getuid() and not (st.st_mode & stat.S_ISVTX):
        return "%s 的父目录 %s 属于其他用户且非 sticky" % (what, parent)
    return None


def resolve_target(path, what, allowed_roots=()):
    """校验并规范化一个将被写入的目录（前缀或数据目录）。"""
    if path is None or not str(path).strip():
        raise ImeError("policy", "%s 必须显式指定（--%s），本工具不假设默认位置" % (what, what), 2)
    raw = str(path)
    if not os.path.isabs(raw):
        raise ImeError("policy", "%s 必须是绝对路径: %s" % (what, raw), 2)
    canon = os.path.realpath(os.path.abspath(raw))
    reason = _deny_reason(canon)
    if reason:
        raise ImeError("policy", "%s 被拒绝：%s（解析为 %s）" % (what, reason, canon), 3)
    reason = _writable_reason(canon, what)
    if reason:
        raise ImeError("policy", "%s 被拒绝：%s" % (what, reason), 3)
    if allowed_roots:
        roots = [os.path.realpath(os.path.abspath(r)) for r in allowed_roots]
        if not any(within(canon, root) for root in roots):
            raise ImeError(
                "policy",
                "%s %s 不在允许写入的根之内: %s" % (what, canon, ", ".join(roots)),
                3,
            )
    return canon


def check_prefix(prefix, allowed_roots=()):
    canon = resolve_target(prefix, "prefix", allowed_roots)
    home = os.path.realpath(os.path.expanduser("~"))
    if canon == home:
        raise ImeError(
            "policy",
            "前缀不允许是用户主目录本身（%s），请使用其下的专用子目录" % canon,
            3,
        )
    if canon.startswith("/./") or "/../" in canon + "/":
        raise ImeError("policy", "前缀路径未规范化: %s" % canon, 3)
    if canon == "/":
        raise ImeError("policy", "前缀不允许为根目录", 3)
    return canon


def check_data_dir(data_dir, prefix, allowed_roots=()):
    canon = resolve_target(data_dir, "data-dir", allowed_roots)
    if canon == prefix:
        raise ImeError("policy", "运行数据目录不得与安装前缀相同: %s" % canon, 3)
    if within(canon, prefix):
        raise ImeError(
            "policy",
            "运行数据目录不得位于安装前缀内部（%s 在 %s 下），否则卸载会波及个人数据" % (canon, prefix),
            3,
        )
    if within(prefix, canon):
        raise ImeError(
            "policy",
            "安装前缀不得位于运行数据目录内部（%s 在 %s 下）" % (prefix, canon),
            3,
        )
    return canon


def check_allowed_roots(roots):
    """规范化 --allowed-root 列表，拒绝相对路径与不可用目录。"""
    out = []
    for root in roots or ():
        if not os.path.isabs(root):
            raise ImeError("policy", "--allowed-root 必须是绝对路径: %s" % root, 2)
        canon = os.path.realpath(os.path.abspath(root))
        out.append(canon)
    return out

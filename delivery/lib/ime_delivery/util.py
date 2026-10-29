"""ime-delivery 通用工具：哈希、原子写、路径安全、JSON、锁。

只依赖 Python 3.8+ 标准库，不写入任何用户受限目录。
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import time

CHUNK_SIZE = 1 << 20
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_RELPATH_RE = re.compile(r"^[A-Za-z0-9._@+/-]+$")
MODE_RE = re.compile(r"^0[0-7]{3}$")


class ImeError(Exception):
    """带稳定错误类别与退出码的安装工具异常。"""

    def __init__(self, kind, message, exit_code=6, details=None):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.exit_code = exit_code
        self.details = list(details or [])

    def as_dict(self):
        return {
            "error": self.kind,
            "message": self.message,
            "exit_code": self.exit_code,
            "details": self.details,
        }


def utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_txid():
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + secrets.token_hex(4)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(CHUNK_SIZE)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def is_sha256(value):
    return isinstance(value, str) and bool(SHA256_RE.match(value))


def fsync_dir(path):
    """尽力 fsync 目录项，让重命名在崩溃后可见。"""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError as exc:  # 某些文件系统不支持目录 fsync
        if exc.errno not in (errno.EINVAL, errno.EBADF):
            raise
    finally:
        os.close(fd)


def atomic_write_bytes(path, data, mode=0o644):
    """同目录临时文件 + fsync + rename，保证读者看到完整内容。"""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    tmp = os.path.join(directory, ".%s.tmp-%s" % (os.path.basename(path), secrets.token_hex(4)))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    fsync_dir(directory)


def write_json_atomic(path, obj, mode=0o644):
    payload = json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    atomic_write_bytes(path, payload.encode("utf-8"), mode)


def atomic_symlink(target, link_path):
    directory = os.path.dirname(link_path)
    tmp = os.path.join(directory, ".%s.link-%s" % (os.path.basename(link_path), secrets.token_hex(4)))
    os.symlink(target, tmp)
    try:
        os.replace(tmp, link_path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    fsync_dir(directory)


def load_json(path, default=None):
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except FileNotFoundError:
        return default
    if not raw.strip():
        return default
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ImeError("state", "无法解析 JSON 文件 %s: %s" % (path, exc), 5)


def safe_relpath(path, what="path"):
    """只接受干净相对路径：无绝对路径、无 ./、无 ..、无反斜杠。"""
    if not isinstance(path, str) or not path:
        raise ImeError("manifest", "%s 必须为非空字符串" % what, 5)
    if "\x00" in path or "\\" in path:
        raise ImeError("manifest", "%s 含有非法字符: %r" % (what, path), 5)
    if path.startswith("/") or path.startswith("./") or path.endswith("/"):
        raise ImeError("manifest", "%s 必须是不带前后缀的相对路径: %r" % (what, path), 5)
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ImeError("manifest", "%s 含有空段/./..: %r" % (what, path), 5)
    if not SAFE_RELPATH_RE.match(path):
        raise ImeError("manifest", "%s 含有不允许的字符: %r" % (what, path), 5)
    if len(path) > 512:
        raise ImeError("manifest", "%s 过长: %r" % (what, path), 5)
    return path


def within(path, parent):
    """path 是否等于 parent 或位于 parent 之下（按路径分量判断）。"""
    try:
        return os.path.commonpath([os.path.realpath(path), os.path.realpath(parent)]) == os.path.realpath(parent)
    except ValueError:
        return False


def human_bytes(size):
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return ("%d %s" % (int(value), unit)) if unit == "B" else ("%.1f %s" % (value, unit))
        value /= 1024.0


def read_sha256_sidecar(package_path):
    """读取 <pkg>.sha256（首列为 64 位十六进制摘要）。不存在时返回 None。"""
    sidecar = package_path + ".sha256"
    if not os.path.isfile(sidecar):
        return None
    with open(sidecar, "r", encoding="utf-8") as fh:
        token = fh.read().strip().split()
    if not token:
        raise ImeError("package", "校验文件为空: %s" % sidecar, 5)
    digest = token[0].lower()
    if not is_sha256(digest):
        raise ImeError("package", "校验文件格式不合法: %s" % sidecar, 5)
    return digest


class PrefixLock:
    """前缀级排它锁，防止两个安装/卸载/回滚事务交叠。"""

    def __init__(self, path, timeout=0.0):
        self.path = path
        self.timeout = float(timeout)
        self.fh = None

    def __enter__(self):
        self.fh = open(self.path, "a+", encoding="utf-8")
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    self.fh.close()
                    raise
                if time.monotonic() >= deadline:
                    self.fh.close()
                    self.fh = None
                    raise ImeError(
                        "locked",
                        "前缀正被另一个安装/卸载进程锁定: %s" % self.path,
                        6,
                        ["如确认没有其它进程，请检查是否有残留进程持有该锁"],
                    )
                time.sleep(0.05)

    def __exit__(self, exc_type, exc, tb):
        if self.fh is not None:
            try:
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
            finally:
                self.fh.close()
                self.fh = None
        return False


def makedirs_recorded(path, created):
    """逐级创建目录，并把本次新建的目录追加到 created（供卸载时按空目录回收）。"""
    missing = []
    cur = os.path.abspath(path)
    while not os.path.isdir(cur):
        if os.path.lexists(cur):
            raise ImeError("conflict", "路径已存在但不是目录: %s" % cur, 3)
        missing.append(cur)
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    for directory in reversed(missing):
        os.mkdir(directory, 0o755)
        created.append(directory)
    return created


def remove_empty_dirs(dirs):
    """只删除空目录，返回仍被保留（非空）的目录。"""
    kept = []
    for directory in sorted(set(dirs), key=lambda p: p.count(os.sep), reverse=True):
        try:
            os.rmdir(directory)
        except OSError:
            kept.append(directory)
    return kept


def list_tree(root, limit=5000):
    """列出目录树中的相对路径（不含文件内容），仅用于诊断与保留项报告。"""
    entries = []
    if not os.path.isdir(root):
        return entries
    for base, dirs, names in os.walk(root):
        dirs.sort()
        for name in sorted(names):
            full = os.path.join(base, name)
            entries.append(os.path.relpath(full, root))
            if len(entries) >= limit:
                return entries
    return entries

#!/usr/bin/env python3
"""安装工具自检：在 delivery/.check/ 下的隔离前缀中跑完整生命周期。

覆盖：策略拒绝、首次安装、重复安装、修复、升级、回滚、保留策略、包/文件校验失败、
无关文件冲突、各阶段崩溃与恢复、卸载（保留数据 / 清除数据）、诊断隐私、并发锁。

所有操作都通过 delivery/bin/ 下的命令行工具完成（与最终用户路径一致），
不使用 root、系统服务或系统目录。输出证据写入 delivery/evidence/。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "bin")
PACKAGES = os.path.join(ROOT, "samples", "packages")
MANIFESTS = os.path.join(ROOT, "samples", "manifests")
PRODUCT_MANIFEST = os.path.join(ROOT, "manifest", "product-manifest.json")
CHECK = os.path.join(ROOT, ".check")
EVIDENCE = os.path.join(ROOT, "evidence")
PY = sys.executable

INSTALL = [PY, os.path.join(BIN, "ime-install")]
DIAGNOSE = [PY, os.path.join(BIN, "ime-diagnose")]
MANIFEST = [PY, os.path.join(BIN, "ime-manifest")]

CANARY = "CANARY-INPUT-LEAK-9f3a7d"
CANARY_LEARNING = "CANARY-LEARNING-STATE-4b1c"


def pkg(name):
    return os.path.join(PACKAGES, name)


def need(condition, message):
    if not condition:
        raise AssertionError(message)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_hashes(root):
    out = {}
    if not os.path.isdir(root):
        return out
    for base, dirs, names in os.walk(root):
        dirs.sort()
        for name in sorted(names):
            full = os.path.join(base, name)
            out[os.path.relpath(full, root)] = sha256_file(full)
    return out


def read_state(prefix):
    path = os.path.join(prefix, "ime", "state", "installed.json")
    with open(path, "rb") as fh:
        return json.loads(fh.read().decode("utf-8"))


def state_path(prefix):
    return os.path.join(prefix, "ime", "state", "installed.json")


def current_link(prefix):
    return os.path.join(prefix, "ime", "current")


def version_dir(prefix, version):
    return os.path.join(prefix, "ime", "versions", version)


def list_versions(r, prefix, expect=0):
    proc = r.run(INSTALL + ["list", "--prefix", prefix, "--json"], expect=expect)
    return json.loads(proc.stdout) if proc.stdout.strip() else {}


def fresh(case):
    base = os.path.join(CHECK, case)
    if os.path.isdir(base):
        shutil.rmtree(base)
    prefix = os.path.join(base, "prefix")
    data = os.path.join(base, "data")
    os.makedirs(base)
    return base, prefix, data


def seed_data(data):
    os.makedirs(os.path.join(data, "personal"), exist_ok=True)
    os.makedirs(os.path.join(data, "learning"), exist_ok=True)
    with open(os.path.join(data, "personal", "dict.json"), "w", encoding="utf-8") as fh:
        json.dump({"schema": "ime.sample-user-dict/1", "entries": [CANARY]}, fh, ensure_ascii=False)
    with open(os.path.join(data, "learning", "stats.json"), "w", encoding="utf-8") as fh:
        json.dump({"schema": "ime.sample-learning/1", "note": CANARY_LEARNING}, fh, ensure_ascii=False)
    with open(os.path.join(data, "settings.json"), "w", encoding="utf-8") as fh:
        json.dump({"schema": "ime.sample-settings/1", "candidate_page_size": 9}, fh, ensure_ascii=False)


def write_file(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class Runner(object):
    def __init__(self):
        self.transcript = []
        self.env = dict(os.environ)
        for key, value in (
            ("HOME", os.path.join(CHECK, "home")),
            ("TMPDIR", os.path.join(CHECK, "tmp")),
            ("XDG_DATA_HOME", os.path.join(CHECK, "xdg", "data")),
            ("XDG_CONFIG_HOME", os.path.join(CHECK, "xdg", "config")),
        ):
            os.makedirs(value, exist_ok=True)
            self.env[key] = value
        os.makedirs(os.path.join(CHECK, "tmp"), exist_ok=True)

    def run(self, argv, expect=None, timeout=240, env_extra=None):
        env = dict(self.env)
        if env_extra:
            env.update(env_extra)
        started = time.time()
        proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout, env=env)
        duration = time.time() - started
        self.transcript.append(
            {
                "command": argv,
                "returncode": proc.returncode,
                "seconds": round(duration, 3),
                "stdout": proc.stdout[-4000:],
                "stderr": proc.stderr[-4000:],
            }
        )
        if expect is not None and proc.returncode != expect:
            raise AssertionError(
                "命令返回码 %d，期望 %d: %s\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (proc.returncode, expect, " ".join(argv), proc.stdout[-2000:], proc.stderr[-2000:])
            )
        return proc

    def install(self, command, package, prefix, data, *extra, expect=0, timeout=240):
        argv = INSTALL + [command, "--prefix", prefix, "--data-dir", data, package] + list(extra)
        return self.run(argv, expect=expect, timeout=timeout)

    def diagnose(self, prefix, *extra, expect=0):
        return self.run(DIAGNOSE + ["--prefix", prefix] + list(extra), expect=expect)


# --------------------------------------------------------------------------- scenarios


def scenario_manifest_and_bundle(r):
    proc = r.run(MANIFEST + ["inspect", pkg("ime-demo-1.0.0.tar.gz"), "--json"], expect=0)
    data = json.loads(proc.stdout)
    need(data["version"] == "1.0.0", "清单版本解析错误: %s" % data.get("version"))
    need(data["sidecar_verified"] is True, "inspect 未校验 .sha256 sidecar")
    need(data["files"] == 5, "文件数错误: %s" % data["files"])
    need(data["entrypoints"] == ["bin/ime-demo"], "启动入口错误: %s" % data["entrypoints"])
    need(data["data_dirs"] == ["personal", "learning"], "数据目录声明错误")

    r.run(MANIFEST + ["validate", os.path.join(MANIFESTS, "good-component.json")], expect=0)
    for name in (
        "bad-absolute-path.json",
        "bad-sha256.json",
        "bad-traversal.json",
        "bad-entrypoint.json",
        "bad-missing-runtime.json",
        "bad-schema.json",
        "bad-duplicate-file.json",
    ):
        proc = r.run(MANIFEST + ["validate", os.path.join(MANIFESTS, name)], expect=5)
        need("错误:" in proc.stderr, "负例 %s 未输出中文错误信息" % name)
    for name in (
        "ime-demo-1.1.0-tampered.tar.gz",
        "ime-demo-1.2.0-extra-payload.tar.gz",
        "ime-demo-1.2.0-missing-file.tar.gz",
        "ime-demo-1.1.0-badsidecar.tar.gz",
    ):
        r.run(MANIFEST + ["inspect", pkg(name)], expect=5)

    proc = r.run(MANIFEST + ["product", os.path.join(ROOT, "samples", "product-demo-ready.json"), "--json"], expect=0)
    product = json.loads(proc.stdout)
    need(product["packaging_ready"] is True, "样例产品清单应可打包")
    need(product["components"][0]["bundle_version"] == "1.0.0", "产品清单未读取包内版本")
    r.run(MANIFEST + ["product", os.path.join(ROOT, "samples", "product-demo-missing.json")], expect=5)
    r.run(MANIFEST + ["product", os.path.join(ROOT, "samples", "product-demo-mismatch.json")], expect=5)
    proc = r.run(MANIFEST + ["product", PRODUCT_MANIFEST, "--json"], expect=0)
    real = json.loads(proc.stdout)
    # 真实产品清单随发布进度变化：未打包时必须明确报告不可打包；已生成发布包时必须可打包且含入口。
    dist_bundle = os.path.join(ROOT, "dist", "server-ime-0.1.0.tar.gz")
    if os.path.isfile(dist_bundle):
        need(real["packaging_ready"] is True, "已生成发布包时真实产品清单必须报告可打包")
        need(real["ready"] >= 1, "真实产品清单应至少含一个就绪组件")
        need(bool(real["components"][0]["entrypoints"]), "就绪组件必须声明启动入口")
    else:
        need(real["packaging_ready"] is False, "真实产品清单在组件未就绪时必须报告不可打包")
        need(real["not_ready"] >= 1, "真实产品清单应包含未就绪组件")
    return "7 个清单负例、4 个坏包、3 个产品清单样例均按预期拒绝；真实产品清单一如当前发布状态"


def scenario_install_repeat_repair_and_upgrade_guard(r):
    base, prefix, data = fresh("s02")
    r.install("install", pkg("ime-demo-1.0.0.tar.gz"), prefix, data)
    out = r.run([os.path.join(prefix, "bin", "ime-demo"), "--version"], expect=0).stdout.strip()
    need(out == "ime-demo 1.0.0", "入口版本错误: %r" % out)
    state = read_state(prefix)
    need(state["current"] == "1.0.0", "状态 current 错误")
    need(state["previous"] is None, "首次安装 previous 应为空")
    need(state["data_dir"] == os.path.realpath(data), "状态未记录数据目录")
    need(os.path.islink(os.path.join(prefix, "bin", "ime-demo")), "bin/ime-demo 应为符号链接")
    need(state["created_dirs"], "状态应记录创建的目录以便卸载回收")

    versions_before = tree_hashes(version_dir(prefix, "1.0.0"))
    state_before = sha256_file(state_path(prefix))
    proc = r.install("install", pkg("ime-demo-1.0.0.tar.gz"), prefix, data)
    need("已安装且内容一致" in proc.stdout, "重复安装未报告幂等: %s" % proc.stdout)
    need(tree_hashes(version_dir(prefix, "1.0.0")) == versions_before, "重复安装改动了版本文件")
    need(sha256_file(state_path(prefix)) == state_before, "重复安装改动了状态文件")

    r.install("install", pkg("ime-demo-1.0.0.tar.gz"), prefix, data, "--repair")
    r.run(INSTALL + ["verify", "--prefix", prefix], expect=0)

    base2, prefix2, data2 = fresh("s02b")
    proc = r.install("upgrade", pkg("ime-demo-1.1.0.tar.gz"), prefix2, data2, expect=4)
    need("尚未安装" in proc.stderr, "空前缀升级应提示未安装: %s" % proc.stderr)
    need(not os.path.exists(state_path(prefix2)), "失败的升级不应留下状态")
    return "首次安装、幂等重复安装、--repair、空前缀升级拒绝均通过"


def scenario_policy(r):
    base, prefix, data = fresh("s03")
    denied = "/usr/local/ime-selfcheck-denied"
    proc = r.install("install", pkg("ime-demo-1.0.0.tar.gz"), denied, data, expect=3)
    need("系统目录" in proc.stderr, "系统前缀应被拒绝: %s" % proc.stderr)
    need(not os.path.exists(denied), "被拒绝的前缀不应被创建")
    r.install("install", pkg("ime-demo-1.0.0.tar.gz"), prefix, os.path.join(prefix, "var"), expect=3)
    r.install("install", pkg("ime-demo-1.0.0.tar.gz"), prefix, prefix, expect=3)
    r.install("install", pkg("ime-demo-1.0.0.tar.gz"), "relative/prefix", data, expect=2)
    r.install("install", pkg("ime-demo-1.0.0.tar.gz"), "", data, expect=2)
    r.install("install", pkg("ime-demo-1.0.0.tar.gz"), r.env["HOME"], data, expect=3)
    allowed = os.path.join(base, "allowed")
    os.makedirs(allowed)
    r.install("install", pkg("ime-demo-1.0.0.tar.gz"), prefix, data, "--allowed-root", allowed, expect=3)
    ok_prefix = os.path.join(allowed, "prefix")
    ok_data = os.path.join(allowed, "data-allowed")
    r.install("install", pkg("ime-demo-1.0.0.tar.gz"), ok_prefix, ok_data, "--allowed-root", allowed)
    need(os.path.isdir(os.path.join(ok_prefix, "ime", "versions", "1.0.0")), "白名单内安装未完成")
    r.run(INSTALL + ["uninstall", "--prefix", ok_prefix], expect=0)
    need(not os.path.exists(prefix), "策略拒绝的安装不应创建前缀")
    return "系统目录、相对路径、空前缀、主目录、数据目录互相包含、白名单越界均被拒绝；白名单内安装成功"


def scenario_upgrade_rollback_and_data(r):
    base, prefix, data = fresh("s04")
    seed_data(data)
    personal = tree_hashes(data)
    write_file(os.path.join(prefix, "notes.txt"), "unrelated notes\n")
    write_file(os.path.join(prefix, "tools", "other.sh"), "#!/bin/sh\necho other\n")
    unrelated = {
        "notes.txt": sha256_file(os.path.join(prefix, "notes.txt")),
        os.path.join("tools", "other.sh"): sha256_file(os.path.join(prefix, "tools", "other.sh")),
    }

    r.install("install", pkg("ime-demo-1.0.0.tar.gz"), prefix, data)
    selftest = r.run(
        [os.path.join(prefix, "bin", "ime-demo"), "--selftest"],
        expect=0,
        env_extra={"IME_DATA_DIR": data},
    ).stdout.strip()
    info = json.loads(selftest)
    need(info["version"] == "1.0.0", "样例自检版本错误")
    need(info["personal_files"] == 1, "样例组件看不到个人词库文件: %s" % info)
    need(tree_hashes(data) == personal, "安装改动了运行数据")

    proc = r.install("upgrade", pkg("ime-demo-1.1.0.tar.gz"), prefix, data)
    need("1.1.0" in proc.stdout, "升级输出缺少版本: %s" % proc.stdout)
    need(r.run([os.path.join(prefix, "bin", "ime-demo"), "--version"], expect=0).stdout.strip() == "ime-demo 1.1.0", "升级后入口版本错误")
    need(r.run([os.path.join(prefix, "bin", "ime-demo-settings")], expect=0).stdout.strip() == "ime-demo-settings 1.1.0", "新增入口不可用")
    state = read_state(prefix)
    need(state["current"] == "1.1.0" and state["previous"] == "1.0.0", "升级状态错误: %s/%s" % (state["current"], state["previous"]))
    need(os.path.isdir(version_dir(prefix, "1.0.0")) and os.path.isdir(version_dir(prefix, "1.1.0")), "升级应保留上一版本目录")
    need(tree_hashes(data) == personal, "升级改动了运行数据")

    r.run(INSTALL + ["rollback", "--prefix", prefix], expect=0)
    need(r.run([os.path.join(prefix, "bin", "ime-demo"), "--version"], expect=0).stdout.strip() == "ime-demo 1.0.0", "回滚后版本错误")
    need(not os.path.lexists(os.path.join(prefix, "bin", "ime-demo-settings")), "回滚后应移除 1.1.0 独有的入口")
    state = read_state(prefix)
    need(state["current"] == "1.0.0" and state["previous"] == "1.1.0", "回滚状态错误")
    need(tree_hashes(data) == personal, "回滚改动了运行数据")

    r.run(INSTALL + ["rollback", "--prefix", prefix, "--to", "1.1.0"], expect=0)
    need(r.run([os.path.join(prefix, "bin", "ime-demo"), "--version"], expect=0).stdout.strip() == "ime-demo 1.1.0", "--to 回滚失败")
    need(tree_hashes(data) == personal, "再次回滚改动了运行数据")

    readme = os.path.join(version_dir(prefix, "1.0.0"), "share", "ime", "README.txt")
    with open(readme, "a", encoding="utf-8") as fh:
        fh.write("local modification\n")
    proc = r.run(INSTALL + ["rollback", "--prefix", prefix, "--to", "1.0.0"], expect=5)
    need("不一致" in proc.stderr, "漂移回滚未说明原因: %s" % proc.stderr)
    need(read_state(prefix)["current"] == "1.1.0", "漂移回滚失败却改动了当前版本")
    r.run(INSTALL + ["verify", "--prefix", prefix, "--version", "1.0.0"], expect=5)
    r.run(INSTALL + ["rollback", "--prefix", prefix, "--to", "1.0.0", "--allow-drift"], expect=0)
    need(r.run([os.path.join(prefix, "bin", "ime-demo"), "--version"], expect=0).stdout.strip() == "ime-demo 1.0.0", "--allow-drift 回滚失败")
    r.install("install", pkg("ime-demo-1.0.0.tar.gz"), prefix, data, "--repair")
    r.run(INSTALL + ["verify", "--prefix", prefix], expect=0)
    need(tree_hashes(data) == personal, "全流程改动了运行数据")
    need(sha256_file(os.path.join(prefix, "notes.txt")) == unrelated["notes.txt"], "无关文件被改动")
    need(sha256_file(os.path.join(prefix, "tools", "other.sh")) == unrelated[os.path.join("tools", "other.sh")], "无关脚本被改动")
    return "安装/升级/两次回滚/漂移拒绝/--allow-drift/修复后个人数据与无关文件哈希不变"


def scenario_retain(r):
    base, prefix, data = fresh("s05")
    r.install("install", pkg("ime-demo-1.0.0.tar.gz"), prefix, data)
    r.install("upgrade", pkg("ime-demo-1.1.0.tar.gz"), prefix, data)
    r.install("upgrade", pkg("ime-demo-1.2.0.tar.gz"), prefix, data, "--retain", "2")
    state = read_state(prefix)
    need(state["current"] == "1.2.0" and state["previous"] == "1.1.0", "保留策略下状态错误")
    need(sorted(state["versions"]) == ["1.1.0", "1.2.0"], "状态应只保留两个版本: %s" % sorted(state["versions"]))
    need(not os.path.isdir(version_dir(prefix, "1.0.0")), "超出保留数的版本目录未清理")
    need(os.path.isdir(version_dir(prefix, "1.1.0")), "上一版本目录不应被清理")
    r.run(INSTALL + ["rollback", "--prefix", prefix], expect=0)
    need(r.run([os.path.join(prefix, "bin", "ime-demo"), "--version"], expect=0).stdout.strip() == "ime-demo 1.1.0", "保留版本回滚失败")
    return "--retain 2 只保留当前与上一版本，回滚仍可用"


def scenario_verification_failure(r):
    base, prefix, data = fresh("s06")
    seed_data(data)
    r.install("install", pkg("ime-demo-1.0.0.tar.gz"), prefix, data)
    personal = tree_hashes(data)
    state_before = sha256_file(state_path(prefix))
    for name, version in (
        ("ime-demo-1.1.0-tampered.tar.gz", "1.1.0"),
        ("ime-demo-1.1.0-badsidecar.tar.gz", "1.1.0"),
        ("ime-demo-1.2.0-extra-payload.tar.gz", "1.2.0"),
        ("ime-demo-1.2.0-missing-file.tar.gz", "1.2.0"),
    ):
        proc = r.install("install", pkg(name), prefix, data, expect=5)
        need(("校验" in proc.stderr) or ("payload" in proc.stderr) or ("清单" in proc.stderr), "失败包未说明校验原因: %s" % proc.stderr)
        need(read_state(prefix)["current"] == "1.0.0", "%s 失败后当前版本被改动" % name)
        need(sha256_file(state_path(prefix)) == state_before, "%s 失败后状态文件被改动" % name)
        need(not os.path.isdir(version_dir(prefix, version)), "%s 失败后留下了版本目录" % name)
        need(r.run([os.path.join(prefix, "bin", "ime-demo"), "--version"], expect=0).stdout.strip() == "ime-demo 1.0.0", "失败后旧版本不可用")
        staging = os.path.join(prefix, "ime", "staging")
        need(not os.listdir(staging), "%s 失败后 staging 未清理: %s" % (name, os.listdir(staging)))
        need(not os.path.exists(os.path.join(prefix, "ime", "state", "journal.json")), "%s 失败后残留事务日志" % name)
        need(tree_hashes(data) == personal, "%s 失败后运行数据被改动" % name)
    return "4 种校验失败（篡改载荷/错误 sidecar/额外文件/缺失文件）均未破坏已安装版本"


def scenario_conflicts(r):
    base, prefix, data = fresh("s07")
    write_file(os.path.join(prefix, "bin", "ime-demo"), "#!/bin/sh\necho unrelated-tool\n")
    write_file(os.path.join(prefix, "bin", "keep"), "keep\n")
    original = sha256_file(os.path.join(prefix, "bin", "ime-demo"))
    proc = r.install("install", pkg("ime-demo-1.0.0.tar.gz"), prefix, data, expect=3)
    need("bin/ime-demo" in proc.stderr, "冲突输出未指出路径: %s" % proc.stderr)
    need(sha256_file(os.path.join(prefix, "bin", "ime-demo")) == original, "冲突中止后占位文件被改动")
    need(not os.path.exists(state_path(prefix)), "冲突中止不应写入安装状态")
    need(list_versions(r, prefix)["installed"] is False, "冲突中止后不应显示已安装")

    r.install("install", pkg("ime-demo-1.0.0.tar.gz"), prefix, data, "--force-conflicts")
    need(os.path.islink(os.path.join(prefix, "bin", "ime-demo")), "--force-conflicts 后入口不是受管链接")
    need(r.run([os.path.join(prefix, "bin", "ime-demo"), "--version"], expect=0).stdout.strip() == "ime-demo 1.0.0", "冲突处理后入口不可用")
    backups = []
    for base_dir, dirs, names in os.walk(os.path.join(prefix, "ime", "backup")):
        for name in names:
            backups.append(os.path.join(base_dir, name))
    matches = [path for path in backups if sha256_file(path) == original]
    need(matches, "--force-conflicts 未保留被占用的原始文件副本")
    r.run(INSTALL + ["uninstall", "--prefix", prefix], expect=0)
    need(os.path.exists(os.path.join(prefix, "bin", "keep")), "卸载删除了无关文件 bin/keep")
    need(os.path.exists(matches[0]), "卸载删除了冲突文件备份（用户数据）")

    base2, prefix2, data2 = fresh("s07b")
    write_file(os.path.join(prefix2, "ime", "current", "blocker.txt"), "occupied\n")
    proc = r.install("install", pkg("ime-demo-1.0.0.tar.gz"), prefix2, data2, expect=3)
    need("ime/current" in proc.stderr, "ime/current 占用未报告: %s" % proc.stderr)
    shutil.rmtree(os.path.join(prefix2, "ime", "current"))
    r.install("install", pkg("ime-demo-1.0.0.tar.gz"), prefix2, data2)
    return "入口占位冲突中止且不动原文件；--force-conflicts 备份后继续；ime/current 占用被识别"


def scenario_interrupt(r):
    detail = []
    for point in (
        "after_verify",
        "after_stage",
        "after_version_placed",
        "after_switch",
        "after_links",
        "before_state_commit",
        "after_state_commit",
    ):
        base, prefix, data = fresh("s08-" + point)
        seed_data(data)
        personal = tree_hashes(data)
        r.install("install", pkg("ime-demo-1.0.0.tar.gz"), prefix, data)
        need(tree_hashes(data) == personal, "初始安装改动了运行数据")
        proc = r.install("upgrade", pkg("ime-demo-1.1.0.tar.gz"), prefix, data, "--fault", point, expect=90)
        need("fault-injected" in proc.stderr, "故障注入未生效: %s" % proc.stderr)
        running = r.run([os.path.join(prefix, "bin", "ime-demo"), "--version"], expect=0).stdout.strip()
        need(running in ("ime-demo 1.0.0", "ime-demo 1.1.0"), "中断后入口不可用: %r" % running)
        listing = list_versions(r, prefix)
        expected_current = "1.1.0" if point == "after_state_commit" else "1.0.0"
        need(listing["current"] == expected_current, "中断点 %s 后当前版本为 %s，期望 %s" % (point, listing["current"], expected_current))
        recovered = r.run(INSTALL + ["recover", "--prefix", prefix, "--json"], expect=0)
        recovery = json.loads(recovered.stdout)
        listing = list_versions(r, prefix)
        need(listing["pending_journal"] is None, "恢复后仍有未完成事务")
        need(not os.listdir(os.path.join(prefix, "ime", "staging")), "恢复后 staging 未清理")
        need(tree_hashes(data) == personal, "恢复过程改动了运行数据")
        need(not os.path.exists(os.path.join(prefix, "ime", "state", "journal.json")), "恢复后事务日志未清除")
        if listing["current"] != "1.0.0":
            r.run(INSTALL + ["rollback", "--prefix", prefix, "--to", "1.0.0"], expect=0)
        need(r.run([os.path.join(prefix, "bin", "ime-demo"), "--version"], expect=0).stdout.strip() == "ime-demo 1.0.0", "恢复后 1.0.0 不可用")
        r.run(INSTALL + ["verify", "--prefix", prefix], expect=0)
        if point != "after_state_commit":
            proc = r.install("upgrade", pkg("ime-demo-1.1.0.tar.gz"), prefix, data)
            need(r.run([os.path.join(prefix, "bin", "ime-demo"), "--version"], expect=0).stdout.strip() == "ime-demo 1.1.0", "恢复后重新升级失败")
        detail.append("%s->%s" % (point, recovery.get("status")))

    base, prefix, data = fresh("s08-first")
    proc = r.install("install", pkg("ime-demo-1.0.0.tar.gz"), prefix, data, "--fault", "after_switch", expect=90)
    r.run(INSTALL + ["recover", "--prefix", prefix], expect=0)
    need(not os.path.lexists(current_link(prefix)), "首次安装中断恢复后不应保留 current 链接")
    need(not os.path.exists(state_path(prefix)), "首次安装中断恢复后不应写入状态")
    need(not os.listdir(os.path.join(prefix, "ime", "versions")), "首次安装中断恢复后不应保留版本目录")
    r.install("install", pkg("ime-demo-1.0.0.tar.gz"), prefix, data)
    need(r.run([os.path.join(prefix, "bin", "ime-demo"), "--version"], expect=0).stdout.strip() == "ime-demo 1.0.0", "中断后重装失败")
    return "7 个升级中断点与 1 个首次安装中断点均恢复到一致状态并可重试 (%s)" % ", ".join(detail)


def scenario_uninstall(r):
    base, prefix, data = fresh("s09")
    seed_data(data)
    r.install("install", pkg("ime-demo-1.0.0.tar.gz"), prefix, data)
    r.install("upgrade", pkg("ime-demo-1.1.0.tar.gz"), prefix, data)
    write_file(os.path.join(prefix, "keepme.txt"), "keep me\n")
    write_file(os.path.join(prefix, "tools", "other.sh"), "#!/bin/sh\necho other\n")
    personal = tree_hashes(data)
    keep_hash = sha256_file(os.path.join(prefix, "keepme.txt"))
    proc = r.run(INSTALL + ["uninstall", "--prefix", prefix, "--json"], expect=0)
    result = json.loads(proc.stdout)
    need(result["status"] == "uninstalled", "卸载状态错误: %s" % result)
    need(not os.path.lexists(os.path.join(prefix, "bin", "ime-demo")), "卸载后入口仍存在")
    need(not os.path.isdir(os.path.join(prefix, "ime", "versions")), "卸载后版本目录仍存在")
    need(not os.path.exists(state_path(prefix)), "卸载后状态文件仍存在")
    need(not os.path.exists(os.path.join(prefix, ".ime-install.lock")), "卸载后锁文件仍存在")
    need(tree_hashes(data) == personal, "卸载改动了运行数据")
    need(sha256_file(os.path.join(prefix, "keepme.txt")) == keep_hash, "卸载改动了无关文件")
    need("keepme.txt" in result["preserved"] and os.path.join("tools", "other.sh") in result["preserved"], "保留项报告不完整: %s" % result["preserved"])
    need(".ime-install.lock" not in result["preserved"], "保留项不应包含本工具锁文件")
    need(not any(item.startswith("ime/log") or item.startswith("ime/versions") for item in result["preserved"]), "保留项不应包含本工具日志/版本: %s" % result["preserved"])
    second = json.loads(r.run(INSTALL + ["uninstall", "--prefix", prefix, "--json"], expect=0).stdout)
    need(second["status"] == "not-installed", "重复卸载应幂等: %s" % second["status"])

    r.install("install", pkg("ime-demo-1.0.0.tar.gz"), prefix, data)
    proc = r.run(INSTALL + ["uninstall", "--prefix", prefix, "--purge-data", "--json"], expect=2)
    need(os.path.isdir(data), "--purge-data 缺少 --yes 时不应删除数据")
    r.run(INSTALL + ["uninstall", "--prefix", prefix, "--purge-data", "--yes"], expect=0)
    need(not os.path.exists(data), "--purge-data --yes 未删除数据目录")

    base2, prefix2, data2 = fresh("s09b")
    r.install("install", pkg("ime-demo-1.0.0.tar.gz"), prefix2, data2)
    r.run(INSTALL + ["uninstall", "--prefix", prefix2], expect=0)
    need(not os.path.exists(prefix2), "无无关文件时卸载应回收本工具创建的前缀目录")
    return "卸载移除全部受管文件、保留个人数据/无关文件/冲突备份，幂等；purge 需 --yes"


def scenario_diagnose_privacy(r):
    base, prefix, data = fresh("s10")
    seed_data(data)
    r.install("install", pkg("ime-demo-1.0.0.tar.gz"), prefix, data)
    proc = r.diagnose(prefix, "--json", expect=0)
    report = json.loads(proc.stdout)
    need(report["ok"] is True, "健康安装的诊断应为 ok: %s" % report["errors"])
    need("不含任何输入文本" in report["privacy"], "诊断缺少隐私声明")
    need(report["data"]["count"] >= 3, "诊断未列出运行数据文件: %s" % report["data"].get("count"))
    need(all(item["status"] == "ok" for item in report["runtime"]), "运行依赖探测失败: %s" % report["runtime"])
    need(all(item["executable"] and item["link_managed"] for item in report["entrypoints"]), "启动入口诊断失败")
    need(report["install"]["current"] == "1.0.0", "诊断当前版本错误")
    for item in report["data"]["files"]:
        need("sha256" in item and "size" in item, "数据清单缺少校验信息")

    text = r.diagnose(prefix, expect=0).stdout
    need(CANARY not in text and CANARY_LEARNING not in text, "文本诊断泄露了词库内容")
    need("隐私" in text and "运行数据" in text, "文本诊断缺少关键段落")
    for proc in (r.diagnose(prefix, "--json", expect=0), r.diagnose(prefix, expect=0)):
        need(CANARY not in proc.stdout and CANARY not in proc.stderr, "诊断输出泄露输入内容")
        need(CANARY_LEARNING not in proc.stdout + proc.stderr, "诊断输出泄露学习数据")
    leaked = []
    for base_dir, dirs, names in os.walk(prefix):
        for name in names:
            full = os.path.join(base_dir, name)
            if os.path.islink(full):
                continue
            with open(full, "rb") as fh:
                blob = fh.read()
            if CANARY.encode() in blob or CANARY_LEARNING.encode() in blob:
                leaked.append(os.path.relpath(full, prefix))
    need(not leaked, "安装前缀中出现个人数据内容副本: %s" % leaked)

    installed = os.path.join(version_dir(prefix, "1.0.0"), "share", "ime", "defaults.json")
    with open(installed, "a", encoding="utf-8") as fh:
        fh.write("\n")
    proc = r.diagnose(prefix, "--json", expect=5)
    drift = json.loads(proc.stdout)
    need(drift["files"]["ok"] is False and drift["files"]["drift"], "诊断未发现文件漂移")
    need(CANARY not in proc.stdout, "漂移诊断泄露输入内容")
    r.run(INSTALL + ["verify", "--prefix", prefix], expect=5)
    r.install("install", pkg("ime-demo-1.0.0.tar.gz"), prefix, data, "--repair")
    r.run(INSTALL + ["verify", "--prefix", prefix], expect=0)
    r.diagnose(prefix, "--json", expect=0)
    return "诊断报告包含依赖/入口/数据清单，不含任何词条文本；漂移可被发现并修复"


def scenario_lock(r):
    base, prefix, data = fresh("s11")
    r.install("install", pkg("ime-demo-1.0.0.tar.gz"), prefix, data)
    lock_path = os.path.join(prefix, ".ime-install.lock")
    holder = subprocess.Popen(
        [
            PY,
            "-c",
            (
                "import fcntl, sys, time\n"
                "fh = open(sys.argv[1], 'a+')\n"
                "fcntl.flock(fh.fileno(), fcntl.LOCK_EX)\n"
                "print('locked', flush=True)\n"
                "time.sleep(20)\n"
            ),
            lock_path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        line = holder.stdout.readline().strip()
        need(line == "locked", "无法持有前缀锁: %r" % line)
        proc = r.install("upgrade", pkg("ime-demo-1.1.0.tar.gz"), prefix, data, expect=6)
        need("锁定" in proc.stderr, "并发安装未报告锁冲突: %s" % proc.stderr)
        need(read_state(prefix)["current"] == "1.0.0", "并发失败后状态被改动")
    finally:
        holder.terminate()
        holder.wait(timeout=10)
    r.install("upgrade", pkg("ime-demo-1.1.0.tar.gz"), prefix, data)
    need(r.run([os.path.join(prefix, "bin", "ime-demo"), "--version"], expect=0).stdout.strip() == "ime-demo 1.1.0", "锁释放后升级失败")
    return "前缀锁阻止并发事务（退出码 6），释放后可正常升级"


SCENARIOS = [
    ("manifest_and_bundle", scenario_manifest_and_bundle),
    ("install_repeat_repair", scenario_install_repeat_repair_and_upgrade_guard),
    ("policy", scenario_policy),
    ("upgrade_rollback_data", scenario_upgrade_rollback_and_data),
    ("retain", scenario_retain),
    ("verification_failure", scenario_verification_failure),
    ("conflicts", scenario_conflicts),
    ("interrupt", scenario_interrupt),
    ("uninstall", scenario_uninstall),
    ("diagnose_privacy", scenario_diagnose_privacy),
    ("lock", scenario_lock),
]


def main(argv):
    started = time.time()
    os.makedirs(CHECK, exist_ok=True)
    os.makedirs(EVIDENCE, exist_ok=True)
    r = Runner()
    results = []
    for name, func in SCENARIOS:
        r.transcript.append({"scenario": name, "phase": "start"})
        try:
            detail = func(r)
            results.append({"scenario": name, "status": "PASS", "detail": detail})
            print("PASS %-24s %s" % (name, detail))
        except Exception as exc:  # noqa: BLE001 - 自检需要记录任何失败
            tb = traceback.format_exc()
            results.append({"scenario": name, "status": "FAIL", "detail": str(exc), "traceback": tb})
            print("FAIL %-24s %s" % (name, exc))
            r.transcript.append({"scenario": name, "failure": tb})
        r.transcript.append({"scenario": name, "phase": "end"})
    duration = time.time() - started
    passed = sum(1 for item in results if item["status"] == "PASS")
    failed = len(results) - passed

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    log_path = os.path.join(EVIDENCE, "lifecycle-%s.log" % stamp)
    with open(log_path, "w", encoding="utf-8") as fh:
        fh.write("ime-delivery lifecycle self-check %s\n" % stamp)
        fh.write("root=%s\npython=%s\n" % (ROOT, sys.version.split()[0]))
        for entry in r.transcript:
            if "command" in entry:
                fh.write("\n$ %s\nrc=%s seconds=%s\n" % (" ".join(entry["command"]), entry["returncode"], entry["seconds"]))
                if entry["stdout"].strip():
                    fh.write("--- stdout ---\n%s\n" % entry["stdout"].rstrip())
                if entry["stderr"].strip():
                    fh.write("--- stderr ---\n%s\n" % entry["stderr"].rstrip())
            elif "scenario" in entry:
                fh.write("\n== %s %s ==\n" % (entry["scenario"], entry.get("phase", entry.get("failure", ""))))
            else:
                fh.write("\n%s\n" % entry)
    junit_path = os.path.join(EVIDENCE, "lifecycle-junit.xml")
    with open(junit_path, "w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        fh.write(
            '<testsuite name="ime-delivery-lifecycle" tests="%d" failures="%d" time="%.3f">\n'
            % (len(results), failed, duration)
        )
        for item in results:
            fh.write('  <testcase classname="ime_delivery.lifecycle" name="%s" time="0">\n' % escape(item["scenario"]))
            if item["status"] == "PASS":
                fh.write("    <system-out>%s</system-out>\n" % escape(item["detail"]))
            else:
                fh.write('    <failure message="%s">%s</failure>\n' % (escape(item["detail"]), escape(item.get("traceback", ""))))
            fh.write("  </testcase>\n")
        fh.write("</testsuite>\n")
    summary_path = os.path.join(EVIDENCE, "lifecycle-summary.json")
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "schema": "ime.delivery-selfcheck/1",
                "status": "pass" if failed == 0 else "fail",
                "passed": passed,
                "failed": failed,
                "seconds": round(duration, 3),
                "scenarios": results,
                "artifacts": {
                    "log": os.path.relpath(log_path, ROOT),
                    "junit": os.path.relpath(junit_path, ROOT),
                },
            },
            fh,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        fh.write("\n")
    print("")
    print("自检结果: %d 通过, %d 失败, %.1f 秒" % (passed, failed, duration))
    print("证据: %s" % os.path.relpath(log_path, ROOT))
    print("JUnit: %s" % os.path.relpath(junit_path, ROOT))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

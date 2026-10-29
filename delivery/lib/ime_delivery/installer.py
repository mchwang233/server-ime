"""用户级安装事务：安装、重复安装、升级、回滚、崩溃恢复与卸载。

布局（全部位于显式前缀内）::

    <prefix>/bin/<入口>              -> ../ime/current/<可执行文件>（仅启动入口）
    <prefix>/ime/current             -> versions/<版本>（原子切换点）
    <prefix>/ime/versions/<版本>/...  每个版本独占目录
    <prefix>/ime/state/installed.json 状态（版本、文件校验值、启动入口、历史）
    <prefix>/ime/state/journal.json   进行中的事务（崩溃恢复依据）
    <prefix>/ime/staging/<txid>/      解包与校验的临时目录
    <prefix>/ime/backup/              冲突文件的保留副本（卸载不删除）
    <prefix>/ime/log/install.log      审计日志（只含路径/校验值/版本，不含内容）

运行数据（个人词库、学习数据）位于独立的数据目录，安装/升级/回滚/卸载均不修改
其内容；卸载默认保留，只有 --purge-data --yes 才会删除。
"""

from __future__ import annotations

import os
import shutil
import stat
import sys

from . import policy
from .manifest import load_bundle, verify_package_sha256
from .state import (
    STATE_SCHEMA,
    clear_journal,
    has_journal,
    load_journal,
    load_state,
    save_state,
    write_journal,
)
from .util import (
    ImeError,
    PrefixLock,
    atomic_symlink,
    fsync_dir,
    human_bytes,
    load_json,
    makedirs_recorded,
    new_txid,
    read_sha256_sidecar,
    remove_empty_dirs,
    sha256_file,
    utc_now,
    within,
)

from . import TOOL_VERSION

FAULT_EXIT_CODE = 90


class Layout(object):
    def __init__(self, prefix):
        self.prefix = prefix
        self.root = os.path.join(prefix, "ime")
        self.versions = os.path.join(self.root, "versions")
        self.statedir = os.path.join(self.root, "state")
        self.staging = os.path.join(self.root, "staging")
        self.logs = os.path.join(self.root, "log")
        self.backup = os.path.join(self.root, "backup")
        self.current = os.path.join(self.root, "current")
        self.statefile = os.path.join(self.statedir, "installed.json")
        self.journal = os.path.join(self.statedir, "journal.json")
        self.logfile = os.path.join(self.logs, "install.log")
        self.lock = os.path.join(prefix, ".ime-install.lock")


class Logger(object):
    """审计日志：只记录操作、版本、相对路径与校验值，绝不记录文件内容。"""

    def __init__(self, path=None, echo=False, stream=None):
        self.path = path
        self.echo = echo
        self.stream = stream or sys.stderr

    def log(self, message, **fields):
        parts = [utc_now(), "msg=" + _quote(message)]
        for key in sorted(fields):
            parts.append("%s=%s" % (key, _quote(fields[key])))
        line = " ".join(parts)
        if self.path:
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
            except OSError:
                pass
        if self.echo:
            self.stream.write(line + "\n")
            self.stream.flush()

    def set_path(self, path):
        self.path = path


def _quote(value):
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _fault(point, enabled):
    """测试用的故障注入：在指定阶段直接退出，模拟进程被杀死。"""
    if enabled and point == enabled:
        sys.stderr.write("fault-injected point=%s pid=%d\n" % (point, os.getpid()))
        sys.stderr.flush()
        os._exit(FAULT_EXIT_CODE)


def _ensure_dirs(lay, created):
    for directory in (lay.prefix, lay.root, lay.versions, lay.statedir, lay.staging, lay.logs, lay.backup):
        makedirs_recorded(directory, created)
    makedirs_recorded(os.path.join(lay.prefix, "bin"), created)


def _rel(prefix, path):
    return os.path.relpath(path, prefix)


def _is_managed_link(path, lay):
    if not os.path.islink(path):
        return False
    target = os.readlink(path)
    resolved = os.path.normpath(os.path.join(os.path.dirname(path), target))
    return within(resolved, lay.root)


def _apply_modes(root, files):
    for item in files:
        full = os.path.join(root, item["path"])
        os.chmod(full, int(item["mode"], 8))


def verify_version_files(version_dir, files):
    drift = []
    for item in files:
        full = os.path.join(version_dir, item["path"])
        if not os.path.isfile(full) or os.path.islink(full):
            drift.append({"path": item["path"], "reason": "缺失或被替换"})
            continue
        if os.path.getsize(full) != item["size"]:
            drift.append({"path": item["path"], "reason": "大小不符"})
            continue
        if sha256_file(full) != item["sha256"]:
            drift.append({"path": item["path"], "reason": "校验值不符"})
    return drift


def _tree_matches(version_dir, files):
    return not verify_version_files(version_dir, files)


def _staging_leftovers(lay):
    if not os.path.isdir(lay.staging):
        return []
    return sorted(os.path.join(lay.staging, name) for name in os.listdir(lay.staging))


def _cleanup_tx(lay, txid):
    if not txid:
        return
    work = os.path.join(lay.staging, txid)
    if os.path.isdir(work):
        shutil.rmtree(work, ignore_errors=True)


def _version_dirs(lay):
    if not os.path.isdir(lay.versions):
        return []
    return sorted(name for name in os.listdir(lay.versions) if os.path.isdir(os.path.join(lay.versions, name)))


def _check_conflicts(lay, manifest, state):
    """返回与无关文件冲突的列表；只报告，不修改任何东西。"""
    conflicts = []
    if os.path.lexists(lay.current) and not _is_managed_link(lay.current, lay):
        kind = "符号链接指向前缀之外" if os.path.islink(lay.current) else "普通文件或目录"
        conflicts.append({"path": _rel(lay.prefix, lay.current), "reason": "ime/current 已存在且非本工具创建（%s）" % kind})
    for entry in manifest.entrypoints:
        link = os.path.join(lay.prefix, entry["link_rel"])
        if os.path.lexists(link) and not _is_managed_link(link, lay):
            kind = "符号链接指向前缀之外" if os.path.islink(link) else "普通文件或目录"
            conflicts.append({"path": entry["link_rel"], "reason": "启动入口路径已被占用且非本工具创建（%s）" % kind})
    bin_dir = os.path.join(lay.prefix, "bin")
    if os.path.lexists(bin_dir) and not os.path.isdir(bin_dir):
        conflicts.append({"path": "bin", "reason": "bin 已存在但不是目录"})
    return conflicts


def _backup_conflicts(lay, conflicts, txid, log):
    backup_root = os.path.join(lay.backup, "conflicts-" + txid)
    backups = []
    for item in conflicts:
        source = os.path.join(lay.prefix, item["path"])
        if not os.path.lexists(source):
            continue
        destination = os.path.join(backup_root, item["path"])
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        os.rename(source, destination)
        backups.append({"from": item["path"], "to": os.path.relpath(destination, lay.prefix)})
        log.log("conflict preserved", path=item["path"], backup=backups[-1]["to"], reason=item["reason"])
    return backups


def _restore_conflict_backups(lay, backups, log):
    for item in backups:
        source = os.path.join(lay.prefix, item["to"])
        destination = os.path.join(lay.prefix, item["from"])
        if os.path.lexists(source) and not os.path.lexists(destination):
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            os.rename(source, destination)
            log.log("conflict backup restored", path=item["from"])


def _sync_links(lay, manifest, state, journal, log):
    """按当前版本的启动入口同步 <prefix>/bin；返回链接记录。"""
    desired = {}
    for entry in manifest.entrypoints:
        desired[entry["link_rel"]] = {
            "path": entry["link_rel"],
            "target": "ime/current/" + entry["file_rel"],
            "entry_id": entry["id"],
        }
    links = []
    for link_rel in sorted(desired):
        record = desired[link_rel]
        link_path = os.path.join(lay.prefix, link_rel)
        os.makedirs(os.path.dirname(link_path), exist_ok=True)
        atomic_symlink("../" + record["target"], link_path)
        links.append(record)
        log.log("entrypoint linked", link=link_rel, target=record["target"])
    old_links = set()
    if state:
        old_links = {item["path"] for item in state.get("links", [])}
    for stale in sorted(old_links - set(desired)):
        stale_path = os.path.join(lay.prefix, stale)
        if _is_managed_link(stale_path, lay):
            os.unlink(stale_path)
            log.log("stale entrypoint link removed", link=stale)
    if journal is not None:
        journal["links"] = links
    return links


def _make_journal(op, txid, prev, new, data_dir, package, package_sha, new_preexisting=False):
    return {
        "txid": txid,
        "op": op,
        "prev_version": prev,
        "new_version": new,
        "data_dir": data_dir,
        "package": os.path.basename(package),
        "package_sha256": package_sha,
        "phase": "staged",
        "started_at": utc_now(),
        "links": [],
        "conflict_backups": [],
        "new_version_preexisting": bool(new_preexisting),
        "version_backup": None,
    }


def _prune_plan(state_versions, current, previous, retain):
    """返回需要从状态与磁盘移除的旧版本集合，保留 current/previous 与最近 retain 个。

    版本按写入状态的先后顺序（即安装顺序）判定新旧，避免同一秒内安装造成的
    时间戳并列把最新版本误判为最旧。
    """
    order = list(reversed(list(state_versions.keys())))
    keep = set(order[: max(1, retain)])
    if current:
        keep.add(current)
    if previous:
        keep.add(previous)
    return [v for v in order if v not in keep]


def recover(lay, log, fault=None):
    """把被中断的事务恢复到一致状态：优先回到事务开始前的版本。"""
    journal = load_journal(lay)
    state = load_state(lay)
    if journal is None:
        leftovers = _staging_leftovers(lay)
        for path in leftovers:
            shutil.rmtree(path, ignore_errors=True)
        if leftovers:
            log.log("staging leftovers removed", count=len(leftovers))
        return {"status": "clean", "removed_staging": len(leftovers)}

    txid = journal.get("txid")
    new_version = journal.get("new_version")
    prev_version = journal.get("prev_version")
    committed = journal.get("phase") == "committed"
    if not committed and state and new_version and state.get("current") == new_version and new_version in (state.get("versions") or {}):
        entry = state["versions"][new_version]
        committed = _tree_matches(os.path.join(lay.versions, new_version), entry.get("files", []))
    committed = bool(committed)
    result = {"txid": txid, "op": journal.get("op"), "phase": journal.get("phase"), "new_version": new_version}
    if committed:
        _cleanup_tx(lay, txid)
        clear_journal(lay)
        log.log("recover: transaction had committed, cleaned up", txid=txid, version=new_version)
        result["status"] = "cleaned-committed"
        return result

    version_dir = os.path.join(lay.versions, new_version) if new_version else None

    # 1) 先恢复被本事务移走的版本目录（--repair 或覆盖外来版本目录的情况）。
    version_backup = journal.get("version_backup")
    if version_backup:
        backup_path = os.path.join(lay.prefix, version_backup)
        if version_dir and os.path.isdir(version_dir):
            shutil.rmtree(version_dir, ignore_errors=True)
        if os.path.isdir(backup_path):
            os.rename(backup_path, version_dir)
            result["restored_version_backup"] = new_version
            log.log("recover: displaced version dir restored", txid=txid, version=new_version)
    elif version_dir and os.path.isdir(version_dir) and not journal.get("new_version_preexisting"):
        # 2) 本事务新建的版本目录还没有被状态记录，删除它。
        shutil.rmtree(version_dir, ignore_errors=True)
        result["removed_version_dir"] = new_version
        log.log("recover: incomplete version dir removed", txid=txid, version=new_version)

    # 3) 当前版本指回事务开始前的版本；首次安装失败则移除 current 链接。
    if prev_version and os.path.isdir(os.path.join(lay.versions, prev_version)):
        atomic_symlink("versions/" + prev_version, lay.current)
        result["restored_current"] = prev_version
        log.log("recover: current restored", txid=txid, version=prev_version)
    elif os.path.islink(lay.current):
        target = os.readlink(lay.current)
        if new_version and ("versions/" + new_version) in target:
            os.unlink(lay.current)
            result["removed_current"] = new_version
            log.log("recover: incomplete first install, current link removed", txid=txid)

    # 4) 恢复事务开始前版本的启动入口链接，并移除本事务新增的链接。
    state_links = {item.get("path") for item in (state or {}).get("links", [])}
    if prev_version and state and state.get("current") == prev_version:
        for item in state.get("links", []):
            link_path = os.path.join(lay.prefix, item["path"])
            if _is_managed_link(link_path, lay):
                continue
            os.makedirs(os.path.dirname(link_path), exist_ok=True)
            atomic_symlink("../" + item["target"], link_path)
            result.setdefault("restored_links", []).append(item["path"])
    for item in journal.get("links") or []:
        if item.get("path") in state_links:
            continue
        link_path = os.path.join(lay.prefix, item.get("path", ""))
        if _is_managed_link(link_path, lay):
            os.unlink(link_path)
            result.setdefault("removed_links", []).append(item.get("path"))

    # 5) 恢复被移动到备份区的用户文件，避免冲突处理中途崩溃导致文件消失。
    _restore_conflict_backups(lay, journal.get("conflict_backups") or [], log)

    _cleanup_tx(lay, txid)
    clear_journal(lay)
    result["status"] = "rolled-back"
    log.log("recover: transaction rolled back", txid=txid)
    return result


def run_install(
    package,
    prefix,
    data_dir,
    *,
    upgrade_only=False,
    force_conflicts=False,
    repair=False,
    retain_override=None,
    allow_data_dir_change=False,
    fault=None,
    allowed_roots=(),
    lock_timeout=0.0,
    log=None,
):
    log = log or Logger()
    prefix = policy.check_prefix(prefix, allowed_roots)
    data_dir = policy.check_data_dir(data_dir, prefix, allowed_roots)
    package = os.path.abspath(package)
    if not os.path.isfile(package):
        raise ImeError("package", "安装包不存在: %s" % package, 2)
    expected = read_sha256_sidecar(package)
    package_sha = sha256_file(package)
    if expected:
        verify_package_sha256(package, expected)
        log.log("package sha256 verified", package=os.path.basename(package), sha256=package_sha)

    created = []
    log.log("install start", package=os.path.basename(package), prefix=prefix, data_dir=data_dir, upgrade_only=upgrade_only)
    makedirs_recorded(prefix, created)
    lay = Layout(prefix)
    with PrefixLock(lay.lock, lock_timeout):
        if has_journal(lay):
            log.log("pending transaction found, recovering before install")
            recover(lay, log)
        state = load_state(lay)
        if state and state.get("data_dir") and state["data_dir"] != data_dir and not allow_data_dir_change:
            raise ImeError(
                "conflict",
                "已安装记录的数据目录为 %s，与本次 --data-dir %s 不一致；如确需更换请加 --allow-data-dir-change"
                % (state["data_dir"], data_dir),
                3,
            )
        if upgrade_only and not state:
            raise ImeError("not-installed", "前缀 %s 尚未安装任何版本，无法执行升级" % prefix, 4)

        _ensure_dirs(lay, created)
        log.set_path(lay.logfile)
        txid = new_txid()
        work = os.path.join(lay.staging, txid)
        os.makedirs(work)

        log.log("bundle extracting", txid=txid, package=os.path.basename(package))
        try:
            manifest, payload_dir, bundle_root = load_bundle(package, work)
        except BaseException:
            # 校验失败时只清理本事务的 staging，绝不改动已安装版本或运行数据。
            _cleanup_tx(lay, txid)
            raise
        log.log(
            "bundle verified",
            txid=txid,
            component=manifest.component_id,
            version=manifest.version,
            files=len(manifest.files),
            manifest_sha256=manifest.sha256,
        )
        _fault("after_verify", fault)

        version = manifest.version
        target = os.path.join(lay.versions, version)
        prev_version = state.get("current") if state else None
        recorded = (state or {}).get("versions", {}).get(version)

        need_version_backup = False
        backup_reason = None
        if recorded and os.path.isdir(target):
            same_package = recorded.get("manifest_sha256") == manifest.sha256
            actual_clean = _tree_matches(target, recorded.get("files", []))
            if same_package and actual_clean and not repair:
                if prev_version == version:
                    _cleanup_tx(lay, txid)
                    log.log("already installed", version=version)
                    return {
                        "status": "already-installed",
                        "version": version,
                        "current": version,
                        "prefix": prefix,
                        "data_dir": data_dir,
                        "message": "版本 %s 已安装且内容一致，未做任何改动" % version,
                    }
                _cleanup_tx(lay, txid)
                raise ImeError(
                    "conflict",
                    "版本 %s 已安装但当前生效的是 %s；如需切换请使用 rollback --to %s" % (version, prev_version, version),
                    3,
                )
            if not repair:
                _cleanup_tx(lay, txid)
                detail = "包内容与该已安装版本不同" if not same_package else "已安装文件被修改"
                raise ImeError("conflict", "版本 %s 已存在且%s；如确需覆盖请使用 --repair" % (version, detail), 3)
            need_version_backup = True
            backup_reason = "repair"
        elif os.path.isdir(target) and not recorded:
            if not repair:
                _cleanup_tx(lay, txid)
                raise ImeError(
                    "conflict",
                    "版本目录 %s 已存在但不属于本工具（无安装记录）；如确认可覆盖请使用 --repair" % _rel(prefix, target),
                    3,
                )
            need_version_backup = True
            backup_reason = "foreign"

        conflicts = _check_conflicts(lay, manifest, state)
        if conflicts and not force_conflicts:
            _cleanup_tx(lay, txid)
            raise ImeError(
                "conflict",
                "发现与无关文件/目录冲突，安装已中止，现有版本未被改动",
                3,
                ["%s: %s" % (item["path"], item["reason"]) for item in conflicts],
            )
        journal = _make_journal(
            "upgrade" if prev_version else "install",
            txid,
            prev_version,
            version,
            data_dir,
            package,
            package_sha,
        )
        write_journal(lay, journal)
        if conflicts:
            journal["conflict_backups"] = _backup_conflicts(lay, conflicts, txid, log)
            write_journal(lay, journal)
            log.log("conflicts preserved with --force-conflicts", count=len(conflicts))
        if need_version_backup:
            backup_dir = os.path.join(lay.backup, "%s-%s-%s" % (backup_reason, version, txid))
            os.makedirs(backup_dir, exist_ok=True)
            os.rename(target, os.path.join(backup_dir, version))
            journal["version_backup"] = _rel(prefix, os.path.join(backup_dir, version))
            write_journal(lay, journal)
            log.log("existing version dir moved to backup", version=version, backup=_rel(prefix, backup_dir), reason=backup_reason)

        # 创建并锁定运行数据子目录（个人词库等），只建空目录，不写任何内容。
        if not os.path.isdir(data_dir):
            os.makedirs(data_dir, 0o700)
            os.chmod(data_dir, 0o700)
            log.log("data root created", path=data_dir)
        for item in manifest.data_dirs:
            data_path = os.path.join(data_dir, item["path"])
            if not os.path.isdir(data_path):
                os.makedirs(data_path, 0o700)
                os.chmod(data_path, 0o700)
                log.log("data dir created", path=item["path"])

        _fault("after_stage", fault)

        os.rename(payload_dir, target)
        _apply_modes(target, manifest.files)
        fsync_dir(lay.versions)
        journal["phase"] = "version_placed"
        write_journal(lay, journal)
        log.log("payload placed", version=version, target=_rel(prefix, target))
        _fault("after_version_placed", fault)

        atomic_symlink("versions/" + version, lay.current)
        journal["phase"] = "switched"
        write_journal(lay, journal)
        log.log("current switched", version=version, previous=prev_version)
        _fault("after_switch", fault)

        links = _sync_links(lay, manifest, state, journal, log)
        journal["phase"] = "links_synced"
        write_journal(lay, journal)
        _fault("after_links", fault)

        versions = dict((state or {}).get("versions", {}))
        versions[version] = manifest.to_state_entry(
            installed_at=utc_now(),
            package_sha256=package_sha,
            source_package=os.path.basename(package),
        )
        retain = retain_override or manifest.retain_versions
        history = list((state or {}).get("history", []))
        history.append(
            {
                "at": utc_now(),
                "op": journal["op"],
                "version": version,
                "previous": prev_version,
                "package": os.path.basename(package),
                "package_sha256": package_sha,
            }
        )
        pruned = _prune_plan(versions, version, prev_version, retain)
        for old in pruned:
            versions.pop(old, None)
        created_all = sorted(set(((state or {}).get("created_dirs") or []) + created))
        new_state = {
            "schema": STATE_SCHEMA,
            "tool_version": TOOL_VERSION,
            "prefix": prefix,
            "data_dir": data_dir,
            "link_dir": "bin",
            "current": version,
            "previous": prev_version if prev_version != version else None,
            "versions": versions,
            "links": links,
            "created_dirs": created_all,
            "history": history[-50:],
        }
        journal["phase"] = "committing"
        write_journal(lay, journal)
        _fault("before_state_commit", fault)
        save_state(lay, new_state)
        journal["phase"] = "committed"
        write_journal(lay, journal)
        log.log("state committed", version=version, previous=new_state["previous"])
        _fault("after_state_commit", fault)

        for old in pruned:
            old_dir = os.path.join(lay.versions, old)
            if os.path.isdir(old_dir):
                shutil.rmtree(old_dir, ignore_errors=True)
                log.log("pruned old version", version=old, retain=retain)
        _cleanup_tx(lay, txid)
        clear_journal(lay)
        log.log("install complete", version=version, previous=new_state["previous"])
        return {
            "status": "installed" if journal["op"] == "install" else "upgraded",
            "version": version,
            "previous": new_state["previous"],
            "prefix": prefix,
            "data_dir": data_dir,
            "entrypoints": [item["path"] for item in links],
            "message": "已安装 %s %s，当前版本 %s" % (manifest.component_id, version, version),
        }


def run_rollback(
    prefix,
    *,
    to_version=None,
    allow_drift=False,
    fault=None,
    allowed_roots=(),
    lock_timeout=0.0,
    log=None,
):
    log = log or Logger()
    prefix = policy.check_prefix(prefix, allowed_roots)
    lay = Layout(prefix)
    if not os.path.isdir(lay.root):
        raise ImeError("not-installed", "前缀 %s 没有安装记录，无法回滚" % prefix, 4)
    with PrefixLock(lay.lock, lock_timeout):
        if has_journal(lay):
            recover(lay, log)
        state = load_state(lay)
        if state is None:
            raise ImeError("not-installed", "前缀 %s 没有安装记录，无法回滚" % prefix, 4)
        log.set_path(lay.logfile)
        target = to_version or state.get("previous")
        if not target:
            raise ImeError("rollback", "没有可回滚的历史版本（状态中无 previous）", 4)
        if target not in state.get("versions", {}):
            raise ImeError("rollback", "版本 %s 不在安装记录中" % target, 4)
        current = state.get("current")
        if target == current:
            raise ImeError("rollback", "版本 %s 已是当前版本，无需回滚" % target, 3)
        target_dir = os.path.join(lay.versions, target)
        if not os.path.isdir(target_dir):
            raise ImeError("rollback", "版本目录缺失: %s" % _rel(prefix, target_dir), 4)
        drift = verify_version_files(target_dir, state["versions"][target].get("files", []))
        if drift and not allow_drift:
            raise ImeError(
                "verify",
                "目标版本 %s 的文件与安装记录不一致，回滚已中止" % target,
                5,
                ["%s: %s" % (item["path"], item["reason"]) for item in drift],
            )
        txid = new_txid()
        journal = _make_journal("rollback", txid, current, target, state.get("data_dir"), "rollback", None, new_preexisting=True)
        write_journal(lay, journal)
        atomic_symlink("versions/" + target, lay.current)
        journal["phase"] = "switched"
        write_journal(lay, journal)
        _fault("after_switch", fault)

        links = []
        for entry in state["versions"][target].get("entrypoints", []):
            link_rel = entry["link_rel"]
            record = {"path": link_rel, "target": "ime/current/" + entry["file_rel"], "entry_id": entry["id"]}
            link_path = os.path.join(prefix, link_rel)
            os.makedirs(os.path.dirname(link_path), exist_ok=True)
            atomic_symlink("../" + record["target"], link_path)
            links.append(record)
        stale = {item["path"] for item in state.get("links", [])} - {item["path"] for item in links}
        for link_rel in sorted(stale):
            link_path = os.path.join(prefix, link_rel)
            if _is_managed_link(link_path, lay):
                os.unlink(link_path)
                log.log("stale entrypoint link removed", link=link_rel)
        journal["links"] = links
        journal["phase"] = "links_synced"
        write_journal(lay, journal)
        _fault("after_links", fault)

        new_state = dict(state)
        new_state["current"] = target
        new_state["previous"] = current
        new_state["links"] = links
        new_state["history"] = list(state.get("history", [])) + [
            {"at": utc_now(), "op": "rollback", "version": target, "previous": current}
        ]
        journal["phase"] = "committing"
        write_journal(lay, journal)
        save_state(lay, new_state)
        journal["phase"] = "committed"
        write_journal(lay, journal)
        clear_journal(lay)
        _cleanup_tx(lay, txid)
        log.log("rollback complete", version=target, previous=current)
        return {
            "status": "rolled-back",
            "version": target,
            "previous": current,
            "prefix": prefix,
            "message": "已回滚到版本 %s（原版本 %s）" % (target, current),
        }


def run_uninstall(
    prefix,
    *,
    purge_data=False,
    yes=False,
    data_dir=None,
    fault=None,
    allowed_roots=(),
    lock_timeout=0.0,
    log=None,
):
    log = log or Logger()
    prefix = policy.check_prefix(prefix, allowed_roots)
    if data_dir is not None:
        data_dir = policy.check_data_dir(data_dir, prefix, allowed_roots)
    if purge_data and not yes:
        raise ImeError("usage", "--purge-data 会删除个人数据目录，必须同时给出 --yes 确认", 2)
    lay = Layout(prefix)
    if not os.path.isdir(lay.root):
        return {
            "status": "not-installed",
            "prefix": prefix,
            "message": "前缀 %s 下没有安装目录，无需卸载" % prefix,
            "preserved": [],
        }
    with PrefixLock(lay.lock, lock_timeout):
        if has_journal(lay):
            recover(lay, log)
        state = load_state(lay)
        log.set_path(lay.logfile)
        if state is None:
            try:
                os.unlink(lay.lock)  # Linux 允许在持有 flock 时解除目录项
            except OSError:
                pass
            return {
                "status": "not-installed",
                "prefix": prefix,
                "message": "前缀 %s 没有安装记录，未删除任何文件" % prefix,
                "preserved": sorted(os.listdir(prefix)),
            }
        removed_links = []
        for item in state.get("links", []):
            link_path = os.path.join(prefix, item["path"])
            if _is_managed_link(link_path, lay):
                os.unlink(link_path)
                removed_links.append(item["path"])
                log.log("entrypoint link removed", link=item["path"])
        if os.path.islink(lay.current) and _is_managed_link(lay.current, lay):
            os.unlink(lay.current)
        removed_versions = []
        for version in sorted(state.get("versions", {})):
            version_dir = os.path.join(lay.versions, version)
            if os.path.isdir(version_dir):
                shutil.rmtree(version_dir)
                removed_versions.append(version)
                log.log("version removed", version=version)
        # 不属于任何安装记录的版本目录保持原样（不删除非本工具创建的内容）。
        orphans = _version_dirs(lay)
        if orphans:
            log.log("unreferenced version dirs kept", dirs=orphans)
        for path in _staging_leftovers(lay):
            shutil.rmtree(path, ignore_errors=True)
        if os.path.isdir(lay.statedir):
            shutil.rmtree(lay.statedir, ignore_errors=True)
        data_purged = None
        effective_data = data_dir or state.get("data_dir")
        if purge_data:
            if not effective_data or not os.path.isdir(effective_data):
                data_purged = "absent"
            else:
                shutil.rmtree(effective_data)
                data_purged = effective_data
                log.log("data dir purged", data_dir=effective_data)
        _fault("before_cleanup_dirs", fault)
        created_dirs = list(state.get("created_dirs") or [])
        log.log("uninstall cleanup", removed_versions=len(removed_versions), kept_version_dirs=len(orphans))
        log.set_path(None)  # 审计日志随安装目录一起移除，避免卸载后再生成 log 目录
        for path in (lay.logs, lay.staging):
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
        remove_empty_dirs(created_dirs)
    try:
        os.unlink(lay.lock)
    except OSError:
        pass
    if prefix in created_dirs:
        try:
            os.rmdir(prefix)
        except OSError:
            pass
    preserved = sorted(_remaining_entries(prefix))
    result = {
        "status": "uninstalled",
        "prefix": prefix,
        "removed_links": removed_links,
        "removed_versions": removed_versions,
        "kept_version_dirs": orphans,
        "preserved": preserved,
        "data_dir": effective_data,
        "data_purged": data_purged,
        "message": "已卸载前缀 %s" % prefix,
    }
    if preserved:
        result["message"] += "；保留 %d 个与本工具无关的路径" % len(preserved)
    if effective_data and not purge_data:
        result["message"] += "；个人数据保留在 %s" % effective_data
    return result


def _remaining_entries(prefix):
    """列出卸载后前缀中仍存在的路径（相对），用于报告保留项。"""
    entries = []
    if not os.path.isdir(prefix):
        return entries
    for base, dirs, names in os.walk(prefix):
        dirs.sort()
        for name in sorted(dirs):
            full = os.path.join(base, name)
            if os.path.islink(full):
                entries.append(os.path.relpath(full, prefix) + "/")
        for name in sorted(names):
            entries.append(os.path.relpath(os.path.join(base, name), prefix))
    return entries


def verify_installed(prefix, version=None, *, allowed_roots=()):
    prefix = policy.check_prefix(prefix, allowed_roots)
    lay = Layout(prefix)
    state = load_state(lay)
    if state is None:
        raise ImeError("not-installed", "前缀 %s 没有安装记录" % prefix, 4)
    target_version = version or state.get("current")
    if target_version not in state.get("versions", {}):
        raise ImeError("verify", "版本 %s 不在安装记录中" % target_version, 4)
    version_dir = os.path.join(lay.versions, target_version)
    entry = state["versions"][target_version]
    drift = verify_version_files(version_dir, entry.get("files", []))
    links = []
    for item in state.get("links", []):
        link_path = os.path.join(prefix, item["path"])
        links.append(
            {
                "path": item["path"],
                "exists": os.path.lexists(link_path),
                "managed": _is_managed_link(link_path, lay),
            }
        )
    return {
        "prefix": prefix,
        "current": state.get("current"),
        "previous": state.get("previous"),
        "version": target_version,
        "files": len(entry.get("files", [])),
        "drift": drift,
        "links": links,
        "ok": not drift and all(item["managed"] for item in links),
    }


def list_versions(prefix, *, allowed_roots=()):
    prefix = policy.check_prefix(prefix, allowed_roots)
    lay = Layout(prefix)
    state = load_state(lay)
    journal = load_journal(lay)
    rows = []
    if state:
        for version, entry in sorted(state.get("versions", {}).items()):
            version_dir = os.path.join(lay.versions, version)
            rows.append(
                {
                    "version": version,
                    "component": entry.get("component_id"),
                    "installed_at": entry.get("installed_at"),
                    "current": version == state.get("current"),
                    "previous": version == state.get("previous"),
                    "present": os.path.isdir(version_dir),
                    "files": len(entry.get("files", [])),
                    "size": sum(int(item.get("size", 0)) for item in entry.get("files", [])),
                }
            )
    return {
        "prefix": prefix,
        "installed": state is not None,
        "current": state.get("current") if state else None,
        "previous": state.get("previous") if state else None,
        "data_dir": state.get("data_dir") if state else None,
        "versions": rows,
        "pending_journal": journal,
    }

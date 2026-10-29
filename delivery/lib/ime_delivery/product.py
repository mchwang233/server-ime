"""产品级交付清单：把各组件（引擎/前端/词库/界面）的包清单汇总为最终打包输入。"""

from __future__ import annotations

import os
import tempfile

from .manifest import ID_RE, VERSION_RE, load_bundle
from .util import ImeError, is_sha256, safe_relpath

PRODUCT_SCHEMA = "ime.product-manifest/1"
COMPONENT_STATUS = {"pending", "ready", "blocked"}


def _need(cond, message, details=None):
    if not cond:
        raise ImeError("manifest", message, 5, details)


def _str(value, what, allow_empty=False):
    _need(isinstance(value, str), "%s 必须是字符串" % what)
    if not allow_empty:
        _need(value.strip() != "", "%s 不能为空" % what)
    return value


def validate_product_data(data, base_dir, *, check_bundles=True):
    _need(isinstance(data, dict), "产品清单必须是 JSON 对象")
    _need(data.get("schema") == PRODUCT_SCHEMA, "产品清单 schema 必须为 %s" % PRODUCT_SCHEMA)
    product = data.get("product")
    _need(isinstance(product, dict), "product 必须是对象")
    _str(product.get("id"), "product.id")
    _need(bool(ID_RE.match(product["id"])), "product.id 非法: %r" % product["id"])
    _str(product.get("name"), "product.name")
    _str(product.get("version"), "product.version")
    _need(bool(VERSION_RE.match(product["version"])), "product.version 非法: %r" % product["version"])
    _str(product.get("license"), "product.license")
    _str(product.get("description"), "product.description")

    components = data.get("components")
    _need(isinstance(components, list) and components, "components 必须是非空数组")
    seen = set()
    summary = []
    for index, item in enumerate(components):
        what = "components[%d]" % index
        _need(isinstance(item, dict), "%s 必须是对象" % what)
        cid = _str(item.get("id"), what + ".id")
        _need(bool(ID_RE.match(cid)), "%s.id 非法: %r" % (what, cid))
        _need(cid not in seen, "components id 重复: %s" % cid)
        seen.add(cid)
        _str(item.get("employee_id"), what + ".employee_id")
        _str(item.get("role"), what + ".role")
        status = _str(item.get("status"), what + ".status")
        _need(status in COMPONENT_STATUS, "%s.status 必须是 %s 之一" % (what, "/".join(sorted(COMPONENT_STATUS))))
        entrypoints = item.get("entrypoints", [])
        _need(isinstance(entrypoints, list), "%s.entrypoints 必须是数组" % what)
        data_dirs = item.get("data_dirs", [])
        _need(isinstance(data_dirs, list), "%s.data_dirs 必须是数组" % what)
        for path in data_dirs:
            safe_relpath(path, what + ".data_dirs")
        record = {
            "id": cid,
            "employee_id": item.get("employee_id"),
            "role": item.get("role"),
            "status": status,
            "version": item.get("version"),
            "bundle": item.get("bundle"),
            "entrypoints": entrypoints,
            "data_dirs": data_dirs,
            "notes": item.get("notes", ""),
        }
        if status == "ready":
            _str(item.get("version"), what + ".version")
            _need(bool(VERSION_RE.match(item["version"])), "%s.version 非法: %r" % (what, item["version"]))
            bundle = _str(item.get("bundle"), what + ".bundle")
            _need(bool(entrypoints), "%s 标记 ready 但未声明启动入口" % what)
            if "sha256" in item:
                _need(is_sha256(item["sha256"]), "%s.sha256 必须是 64 位小写十六进制" % what)
            bundle_path = bundle if os.path.isabs(bundle) else os.path.join(base_dir, bundle)
            _need(os.path.isfile(bundle_path), "%s 的安装包不存在: %s" % (what, bundle_path))
            record["bundle_path"] = os.path.realpath(bundle_path)
            if check_bundles:
                work = tempfile.mkdtemp(prefix="ime-product-")
                try:
                    manifest, _payload, _root = load_bundle(bundle_path, work)
                finally:
                    import shutil

                    shutil.rmtree(work, ignore_errors=True)
                _need(
                    manifest.version == item["version"],
                    "%s 声明的版本 %s 与包内清单版本 %s 不一致" % (what, item["version"], manifest.version),
                )
                _need(
                    manifest.component_id == cid,
                    "%s 的 id 与包内清单组件 id %s 不一致" % (what, manifest.component_id),
                )
                record["bundle_version"] = manifest.version
                record["bundle_manifest_sha256"] = manifest.sha256
                record["bundle_files"] = len(manifest.files)
        else:
            record["bundle_version"] = None
        summary.append(record)
    _need(any(item["status"] == "ready" for item in summary) or True, "")
    ready = [item for item in summary if item["status"] == "ready"]
    pending = [item for item in summary if item["status"] != "ready"]
    return {
        "schema": PRODUCT_SCHEMA,
        "product": {
            "id": product["id"],
            "name": product["name"],
            "version": product["version"],
            "license": product["license"],
        },
        "components": summary,
        "ready": len(ready),
        "not_ready": len(pending),
        "packaging_ready": not pending,
        "notes": data.get("notes", ""),
    }

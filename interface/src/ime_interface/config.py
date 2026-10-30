"""服务器输入法 用户设置：格式 v1、校验、读写与映射（employee_id=interface）。

设计约束
* 本模块是设置格式的唯一所有者；引擎/平台只提供各自的配置接口。
* 双拼方案、模糊音规则、纠错规则**只接受真实 capabilities 声明的值**
  （`double_pinyin_schemes` / `fuzzy_rules` / `correction_rules`）。
  能力位为 true 但没有声明清单时也不放行具名方案/规则，避免“界面能存、引擎不认”。
* 学习（learning）需要明确的个人数据目录：`apply_engine(..., user_data_dir=…)`
  会把该目录显式传给 `Engine(user_data_dir=…)`；绝不使用没有个人目录的临时引擎冒充成功。
* 未知键原样保留（前向兼容），未知主版本拒绝加载而不是猜测迁移。
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path

VERSION = 1
APP_DIR = "server-ime"
DEFAULTS_PATH = Path(__file__).resolve().parents[2] / "config" / "defaults.json"

#: 引擎 capabilities.features 中与本设置界面相关的位。缺省视为不支持。
FEATURE_KEYS = ("sentence", "candidates", "pagination", "double_pinyin", "fuzzy_pinyin",
                "correction", "learning", "dictionary_import")

#: 规则/方案的中文短标签；引擎未给出名称时的显示兜底。
RULE_LABELS = {
    "c_ch": "c/ch", "s_sh": "s/sh", "z_zh": "z/zh", "f_h": "f/h", "g_k": "g/k",
    "l_n": "l/n", "l_r": "l/r", "an_ang": "an/ang", "en_eng": "en/eng", "in_ing": "in/ing",
    "gn_ng": "gn/ng", "mg_ng": "mg/ng", "iou_iu": "iou/iu", "uei_ui": "uei/ui",
    "uen_un": "uen/un", "ue_ve": "ue/ve", "v_u": "v/u", "on_ong": "on/ong",
    "transpose": "相邻字母颠倒", "delete": "多输入字母", "insert": "漏输入字母",
    "substitute": "错输入字母",
}
SCHEME_LABELS = {"ziranma": "自然码"}

#: 中文提示文案，键为错误码。
MESSAGES = {
    "not-object": "配置文件根节点必须是 JSON 对象",
    "bad-version": "配置版本 {value} 不受支持（本版本只接受 1）；请使用“恢复默认”重建配置",
    "unknown-version": "配置缺少 version 字段，无法确认格式版本",
    "not-integer": "{path} 必须是整数",
    "not-boolean": "{path} 必须是 true 或 false",
    "not-number": "{path} 必须是数字",
    "not-string": "{path} 必须是字符串",
    "out-of-range": "{path} 超出允许范围 {minimum}–{maximum}",
    "bad-enum": "{path} 只能是 {allowed} 之一",
    "not-array": "{path} 必须是数组",
    "duplicate-rule": "{path} 重复声明了规则 {rule}，已拒绝保存",
    "unknown-rule": "{path} 的规则 {rule} 不在本引擎支持的清单内；可用：{allowed}",
    "undeclared-catalog": "引擎未声明可用的{what}（capabilities 清单为空），已拒绝保存 {path}",
    "unsupported-option": "{path} 当前引擎不支持（capabilities.features.{feature}=false），不会生效，已拒绝保存",
    "bad-punctuation": "标点选项不合法：{path}",
    "missing-section": "缺少必需的配置段 {path}",
    "learning-data-dir": "开启个人学习需要明确的用户数据目录（user_data_dir）；"
                         "不会把学习数据写入临时目录",
    "handler-result": "保存回调必须返回规范化 settings（dict），实际得到 {value}",
    "handler-error": "保存回调失败：{message}；原配置未改动，也未提示保存成功",
}


class ConfigError(Exception):
    """保存/应用被拒绝；errors 为 [{code,path,message}] 列表。"""

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("; ".join(e["message"] for e in self.errors))

    def codes(self):
        return [e["code"] for e in self.errors]


def defaults():
    return json.loads(DEFAULTS_PATH.read_text(encoding="utf-8"))


def config_path(env=None):
    """优先级：SERVER_IME_CONFIG > $XDG_CONFIG_HOME/server-ime/settings.json > ~/.config/..."""
    env = os.environ if env is None else env
    explicit = env.get("SERVER_IME_CONFIG")
    if explicit:
        return Path(explicit)
    root = env.get("XDG_CONFIG_HOME") or str(Path(env.get("HOME", ".")) / ".config")
    return Path(root) / APP_DIR / "settings.json"


def data_dir(env=None):
    """个人数据根目录：SERVER_IME_DATA > $XDG_DATA_HOME/server-ime > ~/.local/share/server-ime"""
    env = os.environ if env is None else env
    explicit = env.get("SERVER_IME_DATA")
    if explicit:
        return Path(explicit)
    root = env.get("XDG_DATA_HOME") or str(Path(env.get("HOME", ".")) / ".local" / "share")
    return Path(root) / APP_DIR


def learning_data_dir(env=None):
    """学习（个人词频/短语）数据目录；`apply_engine` 开启学习时显式传给引擎。"""
    return data_dir(env) / "learning"


def _error(code, path, message):
    return {"code": code, "path": path, "message": message}


def rule_label(name):
    return RULE_LABELS.get(name, str(name).replace("_", "/"))


def _scheme_names(value):
    """capabilities.double_pinyin_schemes 可执行文件实测为 {name: {name,native_id}}。"""
    names = []
    if isinstance(value, dict):
        names = [str(key) for key in value]
    elif isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict) and "name" in item:
                names.append(str(item["name"]))
    return [name for name in names if name]


def _rule_names(value):
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if isinstance(item, str)]


class Capabilities:
    """引擎能力视图。真实来源为 `server_ime_engine.Engine.capabilities()`。

    能力位（features）决定“能不能开”；声明清单（double_pinyin_schemes / fuzzy_rules /
    correction_rules）决定“能选什么”。清单缺失时不放行任何具名方案/规则。
    """

    def __init__(self, source=None, fixture=False):
        data = copy.deepcopy(source or {})
        self.raw = data
        self.fixture = bool(fixture)
        self.api_version = str(data.get("api_version", "unknown"))
        self.component_version = str(data.get("component_version", ""))
        self.backend = str(data.get("backend", "unknown"))
        self.backend_version = str(data.get("backend_version", ""))
        self.schemas = list(data.get("schemas") or ["full_pinyin"])
        features = dict(data.get("features") or {})
        self.features = {key: bool(features.get(key, False)) for key in FEATURE_KEYS}

        self.double_pinyin_schemes = _scheme_names(data.get("double_pinyin_schemes"))
        self.scheme_labels = {}
        schemes = data.get("double_pinyin_schemes")
        if isinstance(schemes, dict):
            for key, value in schemes.items():
                if isinstance(value, dict) and value.get("name"):
                    self.scheme_labels[str(key)] = str(value["name"])
        self.fuzzy_rules = _rule_names(data.get("fuzzy_rules"))
        self.correction_rules = _rule_names(data.get("correction_rules"))
        config_defaults = data.get("config_defaults")
        default_scheme = config_defaults.get("double_pinyin_scheme") if isinstance(config_defaults, dict) else None
        if default_scheme not in self.double_pinyin_schemes:
            default_scheme = self.double_pinyin_schemes[0] if self.double_pinyin_schemes else None
        self.default_scheme = default_scheme

    def supports(self, feature):
        return bool(self.features.get(feature, False))

    def scheme_label(self, name):
        return self.scheme_labels.get(name) or SCHEME_LABELS.get(name, str(name))

    def rule_label(self, name):
        return rule_label(name)

    @classmethod
    def from_engine(cls, engine):
        return cls(engine.capabilities())

    @classmethod
    def from_file(cls, path):
        return cls(json.loads(Path(path).read_text(encoding="utf-8")), fixture=True)

    def summary(self):
        return {"backend": self.backend, "backend_version": self.backend_version,
                "api_version": self.api_version, "component_version": self.component_version,
                "schemas": self.schemas, "features": self.features,
                "double_pinyin_schemes": self.double_pinyin_schemes,
                "default_scheme": self.default_scheme,
                "fuzzy_rules": self.fuzzy_rules, "correction_rules": self.correction_rules,
                "fixture": self.fixture}


def _check_bool(value, path, errors):
    if not isinstance(value, bool):
        errors.append(_error("not-boolean", path, MESSAGES["not-boolean"].format(path=path)))
        return False
    return value


def _check_int(value, path, minimum, maximum, errors):
    if type(value) is not int:
        errors.append(_error("not-integer", path, MESSAGES["not-integer"].format(path=path)))
        return minimum
    if not minimum <= value <= maximum:
        errors.append(_error("out-of-range", path, MESSAGES["out-of-range"].format(
            path=path, minimum=minimum, maximum=maximum)))
        return min(max(value, minimum), maximum)
    return value


def _check_number(value, path, minimum, maximum, errors):
    if type(value) not in (int, float) or isinstance(value, bool):
        errors.append(_error("not-number", path, MESSAGES["not-number"].format(path=path)))
        return minimum
    if not minimum <= float(value) <= maximum:
        errors.append(_error("out-of-range", path, MESSAGES["out-of-range"].format(
            path=path, minimum=minimum, maximum=maximum)))
        return min(max(float(value), minimum), maximum)
    return float(value)


def _check_rules(value, path, catalog, what, errors):
    """按引擎声明清单校验规则名，返回保留下来的规则列表（未知/重复项被剔除且记错）。"""
    if not isinstance(value, list):
        errors.append(_error("not-array", path, MESSAGES["not-array"].format(path=path)))
        return []
    kept = []
    allowed = ", ".join(catalog) if catalog else "（引擎未声明任何规则）"
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        if not isinstance(item, str):
            errors.append(_error("not-string", item_path, MESSAGES["not-string"].format(path=item_path)))
            continue
        if item not in catalog:
            errors.append(_error("unknown-rule", item_path,
                                 MESSAGES["unknown-rule"].format(path=item_path, rule=item, allowed=allowed)))
        elif item in kept:
            errors.append(_error("duplicate-rule", item_path,
                                 MESSAGES["duplicate-rule"].format(path=item_path, rule=item)))
        else:
            kept.append(item)
    return kept


def validate(raw, caps, base=None):
    """校验并规范化配置，返回 (settings, errors)。errors 非空时调用方必须拒绝保存。"""
    errors, root = [], copy.deepcopy(base if base is not None else defaults())
    if not isinstance(raw, dict):
        return root, [_error("not-object", "", MESSAGES["not-object"])]
    if "version" not in raw:
        errors.append(_error("unknown-version", "version", MESSAGES["unknown-version"]))
    version = raw.get("version", VERSION)
    if type(version) is not int or version != VERSION:
        errors.append(_error("bad-version", "version", MESSAGES["bad-version"].format(value=version)))
        return root, errors

    for section in ("input", "punctuation", "shortcuts", "panel", "ui"):
        if section not in raw:
            continue
        data = raw[section]
        if not isinstance(data, dict):
            errors.append(_error("not-object", section, MESSAGES["missing-section"].format(path=section)))
            continue
        _merge_section(root[section], data, section, errors, caps)

    # 未知键原样保留，供后续增强读取（前向兼容）。
    for key, value in raw.items():
        if key not in root:
            root[key] = copy.deepcopy(value)

    from . import keymap  # 局部导入：keymap 反向使用本模块的默认值

    normalized, shortcut_errors, _ = keymap.validate_shortcuts(root["shortcuts"])
    errors.extend(shortcut_errors)
    if not shortcut_errors:
        root["shortcuts"].update(normalized)
    return root, errors


def _merge_section(target, data, section, errors, caps):
    unknown = {}
    for key, value in data.items():
        if key not in target:
            unknown[key] = copy.deepcopy(value)
            continue
        path = f"{section}.{key}"
        if section == "input":
            _merge_input(target, key, value, path, errors, caps)
        elif section == "punctuation":
            target[key] = _check_bool(value, path, errors)
        elif section == "shortcuts":
            if not isinstance(value, str):
                errors.append(_error("not-string", path, MESSAGES["not-string"].format(path=path)))
            else:
                target[key] = value
        elif section == "panel":
            if key == "layout":
                if value not in ("horizontal", "vertical"):
                    errors.append(_error("bad-enum", path, MESSAGES["bad-enum"].format(
                        path=path, allowed="horizontal, vertical")))
                else:
                    target[key] = value
            elif key == "font_scale":
                target[key] = _check_number(value, path, 0.8, 3.0, errors)
            elif key == "max_visible":
                target[key] = _check_int(value, path, 1, 9, errors)
            elif key == "edge_margin":
                target[key] = _check_int(value, path, 0, 64, errors)
            else:
                target[key] = _check_bool(value, path, errors)
        elif section == "ui":
            if value != "zh_CN":
                errors.append(_error("bad-enum", path, MESSAGES["bad-enum"].format(path=path, allowed="zh_CN")))
            else:
                target[key] = value
    target.update(unknown)


def _merge_input(target, key, value, path, errors, caps):
    if key == "schema":
        allowed = [s for s in ("full_pinyin", "double_pinyin") if s in caps.schemas or s == "full_pinyin"]
        if value not in allowed:
            errors.append(_error("bad-enum", path, MESSAGES["bad-enum"].format(path=path, allowed=", ".join(allowed))))
        else:
            target[key] = value
    elif key == "page_size":
        target[key] = _check_int(value, path, 1, 9, errors)
    elif key in ("incomplete", "prediction", "shift_toggle"):
        target[key] = _check_bool(value, path, errors)
    elif key == "learning":
        enabled = _check_bool(value, path, errors)
        if enabled and not caps.supports("learning"):
            errors.append(_error("unsupported-option", path,
                                 MESSAGES["unsupported-option"].format(path=path, feature="learning")))
        else:
            target[key] = enabled
    elif key == "double_pinyin_scheme":
        _merge_scheme(target, value, path, errors, caps)
    elif key in ("fuzzy", "correction"):
        _merge_rules(target, key, value, path, errors, caps)


def _merge_scheme(target, value, path, errors, caps):
    """双拼方案只接受引擎 capabilities.double_pinyin_schemes 声明的名字；null 表示用引擎默认。"""
    if value is None:
        target["double_pinyin_scheme"] = None
        return
    if not isinstance(value, str):
        errors.append(_error("not-string", path, MESSAGES["not-string"].format(path=path)))
        return
    if not caps.supports("double_pinyin"):
        errors.append(_error("unsupported-option", path,
                             MESSAGES["unsupported-option"].format(path=path, feature="double_pinyin")))
        return
    if not caps.double_pinyin_schemes:
        errors.append(_error("undeclared-catalog", path,
                             MESSAGES["undeclared-catalog"].format(what="双拼方案", path=path)))
        return
    if value not in caps.double_pinyin_schemes:
        allowed = ", ".join(f"{name}（{caps.scheme_label(name)}）" for name in caps.double_pinyin_schemes)
        errors.append(_error("bad-enum", path, MESSAGES["bad-enum"].format(path=path, allowed=allowed)))
        return
    target["double_pinyin_scheme"] = value


def _merge_rules(target, key, value, path, errors, caps):
    feature = "fuzzy_pinyin" if key == "fuzzy" else "correction"
    what = "模糊音规则" if key == "fuzzy" else "纠错规则"
    catalog = caps.fuzzy_rules if key == "fuzzy" else caps.correction_rules
    if value is not None and not isinstance(value, dict):
        errors.append(_error("not-object", path, MESSAGES["not-object"]))
        return
    data = value or {}
    enabled = _check_bool(data.get("enabled", False), path + ".enabled", errors)
    rules = _check_rules(data.get("rules", []), path + ".rules", catalog, what, errors)
    if enabled and not caps.supports(feature):
        errors.append(_error("unsupported-option", path,
                             MESSAGES["unsupported-option"].format(path=path, feature=feature)))
    else:
        target[key] = {"enabled": enabled, "rules": list(rules)}
    for extra_key, extra_value in data.items():
        if extra_key not in ("enabled", "rules"):
            target[key][extra_key] = copy.deepcopy(extra_value)


def load(path=None, caps=None, env=None):
    """读取配置；文件不存在时返回默认值（不写盘）。"""
    path = Path(path) if path else config_path(env)
    caps = caps or Capabilities()
    if not path.exists():
        return defaults(), [], path
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return defaults(), [_error("invalid-json", str(path), f"配置文件无法解析：{exc}")], path
    settings, errors = validate(raw, caps)
    return settings, errors, path


def save(settings, path=None, caps=None, env=None):
    """原子写入（0600）。校验失败时抛 ConfigError 且不触碰磁盘。"""
    path = Path(path) if path else config_path(env)
    caps = caps or Capabilities()
    normalized, errors = validate(settings, caps)
    if errors:
        raise ConfigError(errors)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".settings-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(normalized, handle, ensure_ascii=False, indent=2, sort_keys=False)
            handle.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return normalized


def reset(path=None, caps=None, env=None):
    """恢复默认：写回默认值并返回。"""
    caps = caps or Capabilities()
    return save(defaults(), path=path, caps=caps, env=env)


def engine_patch(settings, caps=None):
    """映射到引擎配置接口 Engine.configure(patch) / Engine.create_session(config=patch)。

    只输出能力为真且有声明清单的键；未声明的方案/规则绝不进入 patch。
    """
    caps = caps or Capabilities()
    in_value = settings.get("input", {})
    patch = {"schema": in_value.get("schema", "full_pinyin"),
             "page_size": int(in_value.get("page_size", 5)),
             "incomplete": bool(in_value.get("incomplete", True))}
    if caps.supports("learning"):
        patch["learning"] = bool(in_value.get("learning", False))
    if caps.supports("double_pinyin") and caps.double_pinyin_schemes:
        scheme = in_value.get("double_pinyin_scheme") or caps.default_scheme
        if scheme in caps.double_pinyin_schemes:
            patch["double_pinyin_scheme"] = scheme
    for key, feature in (("fuzzy", "fuzzy_pinyin"), ("correction", "correction")):
        if caps.supports(feature):
            patch[key] = _rules_patch(in_value.get(key), caps,
                                      caps.fuzzy_rules if key == "fuzzy" else caps.correction_rules)
    return patch


def _rules_patch(value, caps, catalog):
    data = value if isinstance(value, dict) else {}
    rules = [rule for rule in (data.get("rules") or []) if rule in catalog]
    return {"enabled": bool(data.get("enabled", False)), "rules": rules}


def platform_patch(settings):
    """映射到平台配置：Controller(page_size=...)。框架侧尚未读取的键单列在 handoff 中。"""
    return {"page_size": int(settings.get("input", {}).get("page_size", 5))}


def panel_options(settings):
    panel = settings.get("panel", {})
    layout = str(panel.get("layout", "horizontal")).strip().lower()
    return {"layout": layout if layout in ("horizontal", "vertical") else "horizontal",
            "font_scale": float(panel.get("font_scale", 1.0)),
            "max_visible": int(panel.get("max_visible", 9)),
            "show_page_info": bool(panel.get("show_page_info", True)),
            "show_hints": bool(panel.get("show_hints", True)),
            "edge_margin": int(panel.get("edge_margin", 8)),
            "chinese_punctuation": bool(settings.get("punctuation", {}).get("chinese", True))}


def apply_engine(settings, engine=None, caps=None, user_data_dir=None, env=None):
    """在真实引擎上应用配置，返回 (patch, state)。失败抛 ConfigError。

    学习目录：`user_data_dir` 显式透传给 `Engine(user_data_dir=…)`。
    * 显式给出 → 始终使用该目录；
    * 未给出、开启学习、且能力视图来自真实引擎（非夹具）→ 用 `learning_data_dir()`；
    * 未给出且能力视图是夹具 → 不替夹具创建真实个人目录，交给引擎报 learning_unavailable。
    兼容：`apply_engine(settings)` / `apply_engine(settings, engine)` / `caps=` 原样可用。
    """
    caps = caps or Capabilities()
    patch = engine_patch(settings, caps)
    directory = user_data_dir
    if directory is None and patch.get("learning") and not caps.fixture:
        directory = learning_data_dir(env)
    try:
        if engine is None:
            from server_ime_engine import Engine

            kwargs = {"user_data_dir": str(directory)} if directory is not None else {}
            with Engine(**kwargs) as local:
                session = local.create_session(config=patch)
                return patch, session.state()
        session = engine.create_session(config=patch)
        return patch, session.state()
    except ConfigError:
        raise
    except Exception as exc:  # 引擎错误码映射为中文提示
        code = getattr(exc, "code", "engine-error")
        raise ConfigError([_error("engine-" + str(code), "input", f"引擎拒绝了配置：{exc}")]) from exc


def learning_patch(settings, caps=None):
    """只取学习相关配置，供产品保存回调把它应用到已运行的引擎会话。"""
    caps = caps or Capabilities()
    if not caps.supports("learning"):
        return {}
    return {"learning": bool(settings.get("input", {}).get("learning", False))}


def mapping_report(settings, caps):
    """设置项 → 生效位置的对应表，供设置界面和交接文档显示。"""
    def state(feature, catalog=None):
        if not caps.supports(feature):
            return "unsupported"
        if catalog is not None and not catalog:
            return "undeclared"
        return "live"

    return [
        {"key": "input.schema", "label": "输入方案", "target": "engine.configure(schema)",
         "state": "live" if caps.supports("sentence") else "unavailable"},
        {"key": "input.double_pinyin_scheme", "label": "双拼方案",
         "target": "engine.configure(double_pinyin_scheme)",
         "state": state("double_pinyin", caps.double_pinyin_schemes),
         "options": [f"{name}（{caps.scheme_label(name)}）" for name in caps.double_pinyin_schemes]},
        {"key": "input.page_size", "label": "候选数", "target": "engine.configure(page_size)",
         "state": "live"},
        {"key": "input.incomplete", "label": "不完整拼音", "target": "engine.configure(incomplete)",
         "state": "live"},
        {"key": "input.learning", "label": "输入学习", "target": "engine.configure(learning)",
         "state": state("learning")},
        {"key": "input.fuzzy", "label": "模糊音", "target": "engine.configure(fuzzy)",
         "state": state("fuzzy_pinyin", caps.fuzzy_rules),
         "options": [caps.rule_label(name) for name in caps.fuzzy_rules]},
        {"key": "input.correction", "label": "拼音纠错", "target": "engine.configure(correction)",
         "state": state("correction", caps.correction_rules),
         "options": [caps.rule_label(name) for name in caps.correction_rules]},
        {"key": "punctuation.chinese", "label": "中文标点", "target": "界面标点映射表（框架接入待集成）",
         "state": "config-only"},
        {"key": "shortcuts.*", "label": "快捷键", "target": "keymap-v1（平台按键层，待集成）",
         "state": "config-only"},
        {"key": "panel.font_scale", "label": "面板字号缩放", "target": "候选面板（本界面即时生效）",
         "state": "live"},
        {"key": "panel.max_visible", "label": "面板最多显示", "target": "候选面板（本界面即时生效）",
         "state": "live"},
    ]

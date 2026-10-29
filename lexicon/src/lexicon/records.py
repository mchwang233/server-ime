"""Record formats, validation and canonical hashing.

SPDX-License-Identifier: GPL-3.0-or-later
"""
import hashlib
import json
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from .errors import LexiconError

SCHEMA_BASE = "ime-lexicon-base/1"
SCHEMA_READINGS = "ime-lexicon-readings/1"
SCHEMA_USER = "ime-lexicon-user/1"
SCHEMA_BUNDLE = "ime-lexicon-user-bundle/1"
SCHEMA_CORPUS = "ime-eval-corpus/1"
SCHEMA_NATIVE = "ime-lexicon-native/1"

MAX_TEXT = 16
MAX_PINYIN = 200
MAX_COUNT = 1_000_000
MAX_ENTRIES = 20_000
KINDS = ("base", "learned", "custom")
DOMAIN_RE = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
SYLLABLE_RE = re.compile(r"[a-zv]+\Z")
PINYIN_RE = re.compile(r"[a-z']+\Z")
# Standard Hanyu Pinyin syllables in keyboard spelling (ü -> v).  A small
# number of interjections are included.  Both lve/nve (standard) and lue/nue
# (common IME spelling) are accepted.
VALID_SYLLABLES = frozenset("""
a ai an ang ao ba bai ban bang bao bei ben beng bi bian biao bie bin bing bo bu
ca cai can cang cao ce cen ceng cha chai chan chang chao che chen cheng chi
chong chou chu chua chuai chuan chuang chui chun chuo ci cong cou cu cuan cui
cun cuo da dai dan dang dao de dei den deng di dia dian diao die ding diu dong
dou du duan dui dun duo e ei en eng er fa fan fang fei fen feng fo fou fu ga
gai gan gang gao ge gei gen geng gong gou gu gua guai guan guang gui gun guo
ha hai han hang hao he hei hen heng hm hng hong hou hu hua huai huan huang hui
hun huo ji jia jian jiang jiao jie jin jing jiong jiu ju juan jue jun ka kai
kan kang kao ke ken keng kong kou ku kua kuai kuan kuang kui kun kuo la lai
lan lang lao le lei leng li lia lian liang liao lie lin ling liu long lou lu
luan lue lun luo lv lve m ma mai man mang mao me mei men meng mi mian miao mie
min ming miu mo mou mu n na nai nan nang nao ne nei nen neng ng ni nian niang
niao nie nin ning niu nong nou nu nuan nue nuo nv nve o ou pa pai pan pang pao
pei pen peng pi pian piao pie pin ping po pou pu qi qia qian qiang qiao qie
qin qing qiong qiu qu quan que qun ran rang rao re ren reng ri rong rou ru rua
ruan rui run ruo sa sai san sang sao se sen seng sha shai shan shang shao she
shei shen sheng shi shou shu shua shuai shuan shuang shui shun shuo si song
sou su suan sui sun suo ta tai tan tang tao te teng ti tian tiao tie ting tong
tou tu tuan tui tun tuo wa wai wan wang wei wen weng wo wu xi xia xian xiang
xiao xie xin xing xiong xiu xu xuan xue xun ya yan yang yao ye yi yin ying yo
yong you yu yuan yue yun za zai zan zang zao ze zei zen zeng zha zhai zhan
zhang zhao zhe zhei zhen zheng zhi zhong zhou zhu zhua zhuai zhuan zhuang
zhui zhun zhuo zi zong zou zu zuan zui zun zuo
""".split())
CJK_RANGES = (
    (0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF),
    (0x20000, 0x2FA1F),
)


def utcnow():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def is_cjk(char):
    code = ord(char)
    return any(low <= code <= high for low, high in CJK_RANGES)


def normalize_pinyin(value):
    """Return the canonical syllable-separated ASCII reading.

    Canonical form: lowercase, ``v`` for ü, one ASCII apostrophe between
    syllables, no tone digits and no spaces.  Uppercase and spaces are accepted
    on input; anything else is rejected rather than silently guessed.
    """
    if not isinstance(value, str):
        raise LexiconError("invalid_pinyin", "pinyin must be a string")
    text = unicodedata.normalize("NFC", value).strip().lower().replace("ü", "v")
    text = text.replace("\u2019", "'").replace("`", "'")
    text = re.sub(r"[\s\u00b7]+", "'", text)
    text = re.sub(r"'[\s\u00b7]*", "'", text)
    if not text or len(text) > MAX_PINYIN or not PINYIN_RE.fullmatch(text):
        raise LexiconError("invalid_pinyin", "pinyin may contain only a-z, v and apostrophes")
    if text.startswith("'") or text.endswith("'") or "''" in text:
        raise LexiconError("invalid_pinyin", "pinyin has an empty syllable")
    return text


def syllables(pinyin):
    return pinyin.split("'")


def validate_text(text, minimum=1, maximum=MAX_TEXT):
    if not isinstance(text, str):
        raise LexiconError("invalid_text", "text must be a string")
    text = unicodedata.normalize("NFC", text)
    if not minimum <= len(text) <= maximum:
        raise LexiconError("invalid_text", f"text length must be in [{minimum}, {maximum}]")
    if not all(is_cjk(char) for char in text):
        raise LexiconError("invalid_text", "text must contain CJK characters only")
    return text


def check_reading(text, pinyin):
    """Validate that a separated reading has exactly one syllable per character."""
    parts = syllables(pinyin)
    if len(parts) != len(text):
        raise LexiconError(
            "pinyin_length_mismatch",
            f"{len(parts)} syllables for {len(text)} characters",
            {"text": text, "pinyin": pinyin},
        )
    for part in parts:
        if not SYLLABLE_RE.fullmatch(part):
            raise LexiconError("invalid_pinyin", f"invalid syllable {part!r}")
        if part not in VALID_SYLLABLES:
            raise LexiconError("invalid_pinyin", f"not a Hanyu Pinyin syllable: {part!r}")
    return parts


def entry_key(text, pinyin):
    return text + "\u0000" + pinyin


def entry_id(text, pinyin):
    return "w-" + hashlib.sha256(entry_key(text, pinyin).encode("utf-8")).hexdigest()[:16]


def validate_entry(entry, *, require_source=False, maximum_text=MAX_TEXT, kinds=KINDS):
    """Validate one base or user entry and return a normalised copy.

    Unknown fields are preserved so that a newer writer's optional metadata
    survives a read/write cycle by an older reader.
    """
    if not isinstance(entry, dict):
        raise LexiconError("invalid_record", "entry must be an object")
    data = dict(entry)
    for key in ("text", "pinyin", "count", "kind"):
        if key not in data:
            raise LexiconError("invalid_record", f"entry is missing {key}")
    data["text"] = validate_text(data["text"], maximum=maximum_text)
    data["pinyin"] = normalize_pinyin(data["pinyin"])
    check_reading(data["text"], data["pinyin"])
    if type(data["count"]) is not int or not 1 <= data["count"] <= MAX_COUNT:
        raise LexiconError("invalid_record", f"count must be an integer in [1, {MAX_COUNT}]")
    if data["kind"] not in kinds:
        raise LexiconError("invalid_record", "kind must be one of: " + ", ".join(kinds))
    if "id" in data and data["id"] != entry_id(data["text"], data["pinyin"]):
        raise LexiconError("invalid_record", "id does not match text and pinyin")
    data.setdefault("id", entry_id(data["text"], data["pinyin"]))
    if require_source and not data.get("source"):
        raise LexiconError("invalid_record", "base entry is missing source provenance")
    if "domain" in data and not DOMAIN_RE.fullmatch(str(data["domain"])):
        raise LexiconError("invalid_record", "domain must be a short lowercase token")
    return data


def new_entry(text, pinyin, count, kind, *, source="user", **extra):
    data = {
        "id": entry_id(validate_text(text), normalize_pinyin(pinyin)),
        "text": validate_text(text),
        "pinyin": normalize_pinyin(pinyin),
        "count": count,
        "kind": kind,
        "source": source,
    }
    data.update(extra)
    return validate_entry(data)


def canonical_bytes(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path, code="invalid_json"):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        raise LexiconError(code, f"file not found: {path}")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LexiconError(code, f"cannot read JSON {path}: {exc}")


def read_jsonl(path, code="invalid_json"):
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise LexiconError(code, f"invalid JSON line {number} in {path}: {exc}")
    except FileNotFoundError:
        raise LexiconError(code, f"file not found: {path}")
    return rows


def write_json_atomic(path, value, *, indent=1):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=indent, sort_keys=False) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_dir(path.parent)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def write_jsonl_atomic(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_dir(path.parent)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _fsync_dir(path):
    try:
        descriptor = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)

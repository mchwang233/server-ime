"""Named libpinyin 2.6 options; no word- or evaluation-specific rules."""
FUZZY_RULES = {name: 1 << bit for name, bit in (
    ("c_ch", 10), ("s_sh", 11), ("z_zh", 12), ("f_h", 13), ("g_k", 14),
    ("l_n", 15), ("l_r", 16), ("an_ang", 17), ("en_eng", 18), ("in_ing", 19))}
CORRECTION_RULES = {name: 1 << bit for name, bit in (
    ("gn_ng", 21), ("mg_ng", 22), ("iou_iu", 23), ("uei_ui", 24),
    ("uen_un", 25), ("ue_ve", 26), ("v_u", 27), ("on_ong", 28))}
CORRECTION_RULES.update({name: 0 for name in ('transpose', 'delete', 'insert', 'substitute')})
DOUBLE_SCHEMES = {"ziranma": {"name": "自然码双拼", "native_id": 1}}


def rules_flags(option, table):
    return sum(table[name] for name in (option["rules"] or table)) if option["enabled"] else 0


def sensitive(private, purpose, hints):
    # Treat hint bit 11 (private/no-personalization) conservatively even when
    # the installed older GI does not expose the symbolic constant.
    if private or hints & (1 << 11):
        return True
    if type(purpose) is int:
        return purpose not in (0, 1, 10)  # free-form, alpha, terminal
    return purpose.lower() not in ("text", "free_form", "alpha", "terminal", "normal")

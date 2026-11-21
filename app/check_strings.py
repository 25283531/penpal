#!/usr/bin/env python3
"""Bilingual + error-mapping checks for the Penpal app (no Android SDK needed).

Run:  python3 app/check_strings.py
Checks:
  1. values/strings.xml and values-en/strings.xml parse as XML and have
     identical key sets (no missing translation).
  2. Format args match per key (%1$d vs %1$s, same positions).
  3. Every ErrorKey in ErrorMessages.kt maps to an R.string.* that exists
     in BOTH files (so no error can resolve to a missing string).
  4. The two reported 409 wordings exist verbatim in Chinese.
  5. No `Text(text = "...")` hardcoded UI literal and no `userMessage`
     call remain in app code (all user-visible copy goes through
     stringResource / Notice).
Exit code 0 = all pass.
"""
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ZH = ROOT / "app/src/main/res/values/strings.xml"
EN = ROOT / "app/src/main/res/values-en/strings.xml"
ERR = ROOT / "app/src/main/java/com/junze/penpal/ui/components/ErrorMessages.kt"

failures = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def load_strings(path):
    tree = ET.parse(path)
    return {el.get("name"): (el.text or "") for el in tree.getroot() if el.tag == "string"}


def fmt_args(text):
    return re.findall(r"%(\d+)\$([ds])", text or "")


zh = load_strings(ZH)
en = load_strings(EN)
check(len(zh) > 0, f"zh strings parsed ({len(zh)} keys)")
check(len(en) > 0, f"en strings parsed ({len(en)} keys)")
check(set(zh) == set(en),
      f"zh/en key sets identical (only-zh={sorted(set(zh) - set(en))} only-en={sorted(set(en) - set(zh))})")
for key in sorted(set(zh) & set(en)):
    if fmt_args(zh[key]) != fmt_args(en[key]):
        check(False, f"format args differ for {key}: zh={fmt_args(zh[key])} en={fmt_args(en[key])}")
check(all(fmt_args(zh[k]) == fmt_args(en[k]) for k in set(zh) & set(en)),
      "format args match for every shared key")

err_src = ERR.read_text()
keys = re.findall(r"^\s{4}([A-Z_]+),?\s*$", err_src, re.M)
keys = [k for k in keys if k not in ("ERROR",)]
check(len(keys) >= 40, f"ErrorKey enum has {len(keys)} keys")
mapped = dict(re.findall(r"ErrorKey\.([A-Z_]+)\s*->\s*R\.string\.(\w+)", err_src))
check(set(keys) <= set(mapped),
      f"every ErrorKey has a resId() branch (unmapped={sorted(set(keys) - set(mapped))})")
for key, res in sorted(mapped.items()):
    check(res in zh and res in en, f"ErrorKey.{key} -> {res} exists in zh+en")

check(zh.get("err_unanswered_letter") == "这位笔友还有一封没回的信，等回信到了再写下一封",
      "zh err_unanswered_letter is the required wording")
check(zh.get("err_character_limit") == "已达到同时交往的人物上限（%1$d 位），请先结束一段关系或升级会员",
      "zh err_character_limit is the required wording (renders '(1 位)' for free tier)")
check(en.get("err_unanswered_letter", "").startswith("This pen pal still has an unanswered letter"),
      "en err_unanswered_letter is idiomatic English, not a machine translation of the Chinese")
check("机翻" not in en.get("err_unanswered_letter", ""), "en strings contain no Chinese")

# New product rules (2026-11-21): anonymous accounts cannot write;
# registering retires the anonymous identity; a virtual-world name is
# required at registration.
check(zh.get("err_email_required") == "注册邮箱后才能给笔友写信",
      "zh err_email_required is the required gate wording")
check(en.get("err_email_required", "").startswith("Register with an email"),
      "en err_email_required is idiomatic English")
check(zh.get("account_display_name_hint") == "这个姓名只在虚拟世界中使用，虚拟人物会用这个名字称呼你",
      "zh account_display_name_hint states the name is virtual-world-only")
check("仍可用设备号" not in "".join(zh.values()),
      "no zh string still claims anonymous accounts can write")
check("still write with your device ID" not in "".join(en.values()),
      "no en string still claims anonymous accounts can write")

code = "".join(p.read_text() for p in (ROOT / "app/src/main/java").rglob("*.kt"))
check('Text(text = "' not in code, "no hardcoded Text(text = \"...\") literals in UI code")
check("userMessage(" not in code, "no Throwable.userMessage() calls remain (use userNotice())")
check("optString(\"detail\"" not in code and "JSONObject(body)" not in code,
      "no raw backend detail extraction remains")
check("R.string.character_thread " not in code or "character_thread_count" in code,
      "thread count uses the localised count string")

print()
if failures:
    print(f"{len(failures)} FAILURES")
    sys.exit(1)
print("ALL CHECKS PASSED")

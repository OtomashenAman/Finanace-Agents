"""Recognising the same company under slightly different names (bank payer vs customer)."""

import re

_SUFFIXES = {"inc", "llc", "ltd", "limited", "co", "corp", "corporation", "plc", "pvt", "gmbh"}


def customer_key(name: str) -> str:
    """Comparable form of a company name: "Harbor Distribution, Inc." == "harbor distribution"."""
    words = re.findall(r"[a-z0-9]+", name.lower())
    return " ".join(w for w in words if w not in _SUFFIXES)

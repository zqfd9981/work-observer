"""检索用同形部首比较；原文、切片位置和归档指纹始终保持不变。"""

import unicodedata

_RADICALS = str.maketrans(
    {
        chr(code): unicodedata.normalize("NFKC", chr(code))
        for code in range(0x2F00, 0x2FE0)
        if unicodedata.name(chr(code), "").startswith("KANGXI RADICAL")
    }
)


def match_text(value):
    return "" if value is None else value.translate(_RADICALS).casefold()

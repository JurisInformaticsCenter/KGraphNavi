#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
##---------------------------------------------------------------------------##
##  File:
##      misc.py
"""

import hashlib

def hash_color(text):
    """textに対してハッシュ値を求めて、指定されたレンジにおける色を決定する。6文字の16進文字列を返す
    白と黒系を避ける"""
    if text is None:
        text = ""
    hash_value = int(hashlib.md5(text.encode('utf-8')).hexdigest(), 16)
    v1 = hex(hash_value % 256 + 256)[3:]
    v2 = hex(int(hash_value / 256) % 192 + 256)[3:]
    v3 = hex(int(hash_value / (256 * 192)) % 64 + 192 + 256)[3:]
    pat = int(hash_value / (256 * 192 * 64)) % 6
    if pat == 0:
        return v1 + v2 + v3
    if pat == 1:
        return v1 + v3 + v2
    if pat == 2:
        return v2 + v1 + v3
    if pat == 3:
        return v2 + v3 + v1
    if pat == 4:
        return v3 + v1 + v2
    if pat == 5:
        return v3 + v2 + v1

if __name__ == '__main__':
    for text in ('c', 'd', 'g', '東京', '京都', '大阪'):
        print(text, hash_color(text))
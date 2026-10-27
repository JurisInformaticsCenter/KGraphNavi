#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
##---------------------------------------------------------------------------##
##  File:
##      errors.py
##  Author:
##      Fumihito NISHINO       nisino@nii.ac.jp
"""

class KGraphError(Exception):
    """KGraphNavi共通例外"""

class ConfigError(KGraphError):
    pass

class SparqlError(KGraphError):
    """SPARQL の実行の失敗。message は利用者向けの説明、detail はエンドポイントの返したエラーの全文（2026.10.27）"""

    def __init__(self, message, detail=None, status=None):
        super().__init__(message)
        self.message = message
        self.detail = detail
        self.status = status

class GadgetError(KGraphError):
    pass

class ShowError(KGraphError):
    pass

class CollectionError(KGraphError):
    pass

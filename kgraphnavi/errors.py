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
    pass

class GadgetError(KGraphError):
    pass

class ShowError(KGraphError):
    pass

class CollectionError(KGraphError):
    pass

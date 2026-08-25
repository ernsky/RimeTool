# -*- coding: utf-8 -*-
"""pytest 会话级 fixtures：强制 offscreen 平台并提供一个 QApplication 实例，
使 core/dict_model.py（QAbstractTableModel 子类）可在无显示环境下实例化与发信号。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5.QtWidgets import QApplication


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])

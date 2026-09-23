# -*- coding: utf-8 -*-
"""
wechat-filehelper-silent (v2.0.0)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A lightweight, non-disruptive delivery and collaboration tool for PC WeChat 4.x.
Supports 文件传输助手, targeted friend messaging, chronological chat reading, and DB verification.
"""

from .sender import WeChatAssistant, WeChatFileHelperSender

__version__ = "2.0.0"
__all__ = ["WeChatAssistant", "WeChatFileHelperSender"]

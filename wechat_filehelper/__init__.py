# -*- coding: utf-8 -*-
"""
wechat-filehelper-silent (v2.1.0)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A lightweight, non-disruptive delivery and collaboration tool for PC WeChat 4.x.
Supports 文件传输助手, targeted friend messaging, chronological chat reading,
clipboard format preservation, and DB+UI double verification.
"""

from .sender import (
    WeChatAssistant,
    WeChatFileHelperSender,
    preserved_clipboard,
    set_clipboard_text,
    set_clipboard_files,
)

__version__ = "2.1.0"
__all__ = [
    "WeChatAssistant",
    "WeChatFileHelperSender",
    "preserved_clipboard",
    "set_clipboard_text",
    "set_clipboard_files",
]

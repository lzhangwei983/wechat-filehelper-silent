# -*- coding: utf-8 -*-
"""
Core automation sender module for WeChat File Transfer Assistant (文件传输助手).
"""

import os
import sys
import time
import ctypes
from ctypes import wintypes
from pathlib import Path
import win32clipboard
import win32con
import win32gui

_helper_hwnd = None

def _get_clipboard_hwnd():
    global _helper_hwnd
    if _helper_hwnd and win32gui.IsWindow(_helper_hwnd):
        return _helper_hwnd
    wc = win32gui.WNDCLASS()
    wc.lpfnWndProc = lambda hwnd, msg, wparam, lparam: 0
    wc.lpszClassName = "WeChatClipHelperWnd"
    wc.hInstance = win32gui.GetModuleHandle(None)
    try:
        win32gui.RegisterClass(wc)
    except Exception:
        pass
    _helper_hwnd = win32gui.CreateWindow("WeChatClipHelperWnd", "ClipHelper", 0, 0, 0, 0, 0, 0, 0, wc.hInstance, None)
    return _helper_hwnd

class DROPFILES(ctypes.Structure):
    _fields_ = [
        ("pFiles", wintypes.DWORD),
        ("pt", wintypes.POINT),
        ("fNC", wintypes.BOOL),
        ("fWide", wintypes.BOOL),
    ]

def set_clipboard_files(file_paths, retries=15):
    """Sets CF_HDROP clipboard format for files/images with retry."""
    abs_paths = [os.path.abspath(p) for p in file_paths]
    data = "\0".join(abs_paths) + "\0\0"
    data_bytes = data.encode("utf-16le")
    offset = ctypes.sizeof(DROPFILES)
    dropfiles = DROPFILES()
    dropfiles.pFiles = offset
    dropfiles.pt = wintypes.POINT(0, 0)
    dropfiles.fNC = False
    dropfiles.fWide = True
    blob = bytes(dropfiles) + data_bytes
    
    last_err = None
    hwnd = _get_clipboard_hwnd()
    for attempt in range(retries):
        try:
            win32clipboard.OpenClipboard(hwnd)
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_HDROP, blob)
                return True
            finally:
                win32clipboard.CloseClipboard()
        except Exception as e:
            last_err = e
            time.sleep(0.1)
    raise last_err

def set_clipboard_text(text, retries=15):
    """Sets CF_UNICODETEXT clipboard format with retry."""
    last_err = None
    hwnd = _get_clipboard_hwnd()
    for attempt in range(retries):
        try:
            win32clipboard.OpenClipboard(hwnd)
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
                return True
            finally:
                win32clipboard.CloseClipboard()
        except Exception as e:
            last_err = e
            time.sleep(0.1)
    raise last_err

class WeChatFileHelperSender:
    """
    Automated sender targeting PC WeChat '文件传输助手' (or customized chat target).
    
    Key Features:
    - Zero-click keyboard-driven search overlay activation for WeChat 4.x (Qt / mmui).
    - Windows layered window Alpha=0 execution for truly invisible background sending.
    - SetThreadDesktop attachment to ensure background worker compatibility.
    - Automatic restoration of user's active foreground window.
    """
    def __init__(self, target_chat="文件传输助手", silent=True):
        self.target_chat = target_chat
        self.silent = silent
        self.u = ctypes.windll.user32
        self.auto = None
        self.weixin = None
        self.input_field = None
        self.hwnd = None
        self.is_minimized = False
        self.fg_before = None
        self.old_style = None
        self.GWL_EXSTYLE = -20
        self.WS_EX_LAYERED = 0x00080000
        self.LWA_ALPHA = 0x00000002

    def connect(self):
        """Attaches to default desktop station and locates WeChat."""
        h_default = self.u.OpenDesktopW("Default", 0, False, 0x01FF)
        if h_default:
            self.u.SetThreadDesktop(h_default)

        import uiautomation as auto
        self.auto = auto

        self.fg_before = self.u.GetForegroundWindow()

        self.weixin = auto.WindowControl(searchDepth=1, ClassName="mmui::MainWindow")
        if not self.weixin.Exists(3, 1):
            return False, "未检测到微信主窗口，请确认电脑微信已登录。"

        self.hwnd = self.weixin.NativeWindowHandle
        self.is_minimized = bool(self.u.IsIconic(self.hwnd))

        if self.silent:
            self.u.GetWindowLongW.restype = wintypes.LONG
            self.u.SetWindowLongW.restype = wintypes.LONG
            self.u.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]

            self.old_style = self.u.GetWindowLongW(self.hwnd, self.GWL_EXSTYLE)
            self.u.SetWindowLongW(self.hwnd, self.GWL_EXSTYLE, self.old_style | self.WS_EX_LAYERED)
            self.u.SetLayeredWindowAttributes(self.hwnd, 0, 0, self.LWA_ALPHA)

        if self.is_minimized:
            self.u.ShowWindow(self.hwnd, 9)  # SW_RESTORE
            time.sleep(0.1)

        self.u.SetForegroundWindow(self.hwnd)
        time.sleep(0.05)

        # Locate chat input field
        self.input_field = self._find_input_field()
        if not self.input_field or self.input_field.Name != self.target_chat:
            self._navigate_to_target()
            self.input_field = self._find_input_field()

        if not self.input_field or self.input_field.Name != self.target_chat:
            return False, f"无法切换至会话【{self.target_chat}】。"

        return True, "连接成功"

    def _find_input_field(self):
        return self.auto.FindControl(
            self.weixin,
            lambda c, d: c.ControlTypeName == "EditControl" and "ChatInputField" in c.ClassName
        )

    def _navigate_to_target(self):
        """
        Switch to the target chat.

        WeChat 4.x (Qt / mmui) notes -- DO NOT USE MOUSE CLICKS HERE:
        * Ctrl+F opens the global search overlay. The search input is an
          EditControl with ClassName 'mmui::XValidatorTextEdit' / Name '搜索'
          and receives keyboard focus automatically after Ctrl+F.
        * Under silent mode we set WS_EX_LAYERED with alpha=0. Synthetic
          mouse clicks (control.Click()) reliably FAIL to register on the
          layered window, while SendKeys still works. So: focus via Ctrl+F,
          then type -- never click.
        """
        # 1) Ctrl+F -> global search box is auto-focused
        self.auto.SendKeys("{Ctrl}f")
        time.sleep(0.6)

        search_edit = self.auto.FindControl(
            self.weixin,
            lambda c, d: c.ControlTypeName == "EditControl" and c.Name == "搜索"
        )
        if not search_edit:
            # fallback: any edit control inside the search field
            search_edit = self.auto.FindControl(
                self.weixin,
                lambda c, d: c.ControlTypeName == "EditControl"
                and "XValidatorTextEdit" in (c.ClassName or "")
            )

        if search_edit:
            try:
                search_edit.SetFocus()
            except Exception:
                pass
            search_edit.SendKeys(f"{{Ctrl}}a{{Back}}{self.target_chat}")
            time.sleep(0.8)
            search_edit.SendKeys("{Enter}")
            time.sleep(1.0)

    def send_text(self, text, delay_after=0.35):
        """Sends a text message using clipboard with Direct Typing fallback."""
        if not text:
            return True
        self.input_field.SetFocus()
        time.sleep(0.05)
        
        sent = False
        try:
            set_clipboard_text(text)
            self.auto.SendKeys("{Ctrl}v")
            time.sleep(0.15)
            self.auto.SendKeys("{Enter}")
            sent = True
        except Exception:
            # Fallback: Type directly
            print("[*] 剪贴板受阻，自动切换为直接键入 (SendKeys) 模式...")
            clean_text = text.replace("{", "{{").replace("}", "}}")
            self.auto.SendKeys(clean_text, waitTime=0.005)
            time.sleep(0.15)
            self.auto.SendKeys("{Enter}")
            sent = True

        time.sleep(delay_after)
        print(f"[✔] 文本已发送: {text[:40]}..." if len(text) > 40 else f"[✔] 文本已发送: {text}")
        return sent

    def send_file(self, fpath, delay_after=0.5):
        """Sends a single file or image."""
        fpath = os.path.abspath(fpath)
        if not os.path.exists(fpath):
            print(f"[-] 文件不存在: {fpath}", file=sys.stderr)
            return False
        set_clipboard_files([fpath])
        self.input_field.SetFocus()
        time.sleep(0.05)
        self.auto.SendKeys("{Ctrl}v")
        time.sleep(0.5)  # wait for preview card creation
        self.auto.SendKeys("{End}{Enter}")
        time.sleep(delay_after)
        print(f"[✔] 文件已发送: {os.path.basename(fpath)}")
        return True

    def close(self):
        """Restores window visibility and user focus."""
        if self.hwnd:
            if self.is_minimized:
                self.u.ShowWindow(self.hwnd, 6)  # SW_MINIMIZE
            else:
                HWND_BOTTOM = 1
                SWP_NOSIZE = 0x0001
                SWP_NOMOVE = 0x0002
                SWP_NOACTIVATE = 0x0010
                self.u.SetWindowPos(self.hwnd, HWND_BOTTOM, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)

            if self.silent and self.old_style is not None:
                self.u.SetLayeredWindowAttributes(self.hwnd, 0, 255, self.LWA_ALPHA)
                self.u.SetWindowLongW(self.hwnd, self.GWL_EXSTYLE, self.old_style)

        if self.fg_before and self.fg_before != self.hwnd:
            self.u.SetForegroundWindow(self.fg_before)

    def __enter__(self):
        ok, msg = self.connect()
        if not ok:
            raise RuntimeError(msg)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

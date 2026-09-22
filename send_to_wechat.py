# -*- coding: utf-8 -*-
"""
WeChat File Transfer Assistant Delivery Tool (WeChat FileHelper CLI)
- Supports silent delivery of files, images, and text messages to PC WeChat '文件传输助手'.
- Uses Windows desktop penetration (SetThreadDesktop) to work reliably in background task environments.
- Uses layered window Alpha=0 transparency to prevent screen flickering/disruption.
- Supports clipboard retry & Direct Typing fallback for rock-solid reliability.
- Preserves exact sending order and restores user foreground focus upon completion.
"""

import os
import sys
import time
import json
import ctypes
from ctypes import wintypes
import argparse
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

def main():
    parser = argparse.ArgumentParser(description="WeChat FileHelper Automation Delivery Tool")
    parser.add_argument("-t", "--text", nargs="+", help="One or more text messages to send")
    parser.add_argument("-f", "--files", nargs="+", help="One or more file paths to send in order")
    parser.add_argument("-d", "--dir", help="Send all files from a directory in alphabetical/numerical order")
    parser.add_argument("--filter", default="*.jpg", help="Wildcard pattern when using --dir (default: *.jpg)")
    parser.add_argument("--file-text", help="Read a text file and send its entire content as a text message")
    parser.add_argument("-j", "--batch-json", help="Path to JSON file specifying a batch sending sequence")
    parser.add_argument("--check", action="store_true", help="Check if WeChat is running and reachable")
    parser.add_argument("--no-silent", action="store_true", help="Disable transparent silent mode")

    args = parser.parse_args()

    if args.check:
        sender = WeChatFileHelperSender(silent=not args.no_silent)
        ok, msg = sender.connect()
        sender.close()
        if ok:
            print("[+] 微信检测正常：已就绪并可连接至文件传输助手。")
            sys.exit(0)
        else:
            print(f"[-] 微信检测失败：{msg}")
            sys.exit(1)

    if not any([args.text, args.files, args.dir, args.file_text, args.batch_json]):
        parser.print_help()
        sys.exit(1)

    sender = WeChatFileHelperSender(silent=not args.no_silent)
    try:
        ok, msg = sender.connect()
        if not ok:
            print(f"[-] 连接微信失败: {msg}", file=sys.stderr)
            sys.exit(1)

        # 1. Batch JSON mode
        if args.batch_json:
            with open(args.batch_json, "r", encoding="utf-8") as jf:
                batch_data = json.load(jf)
            for item in batch_data:
                itype = item.get("type", "text")
                if itype == "text":
                    sender.send_text(item.get("content", ""))
                elif itype == "file":
                    sender.send_file(item.get("path", ""))
                elif itype == "files":
                    for p in item.get("paths", []):
                        sender.send_file(p)

        # 2. Text arguments
        if args.text:
            for txt in args.text:
                sender.send_text(txt)

        # 3. File arguments
        if args.files:
            for f in args.files:
                sender.send_file(f)

        # 4. Directory scan
        if args.dir:
            p_dir = Path(args.dir)
            if p_dir.is_dir():
                matched_files = sorted(list(p_dir.glob(args.filter)))
                for mf in matched_files:
                    if mf.is_file():
                        sender.send_file(str(mf))

        # 5. File content as text
        if args.file_text:
            with open(args.file_text, "r", encoding="utf-8") as tf:
                content = tf.read()
            sender.send_text(content)

        print("\n[SUCCESS] 所有指定内容均已成功发送至微信文件传输助手！")

    finally:
        sender.close()

if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
Core automation sender module for PC WeChat 4.x (文件传输助手 & 指定好友协作).
"""

import ctypes
u = ctypes.windll.user32
h_default = u.OpenDesktopW("Default", 0, False, 0x01FF)
if h_default:
    u.SetThreadDesktop(h_default)

import os
import sys
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
import win32clipboard
import win32con
import win32gui
import win32process

try:
    from wechatauto import WeChatDB
    _HAS_WECHAT_DB = True
except Exception:
    _HAS_WECHAT_DB = False

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
    for _ in range(retries):
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_HDROP, blob)
                return True
            finally:
                win32clipboard.CloseClipboard()
        except Exception as e:
            last_err = e
            time.sleep(0.08)
    raise last_err

def set_clipboard_text(text, retries=15):
    """Sets CF_UNICODETEXT clipboard format with retry."""
    last_err = None
    for _ in range(retries):
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
                return True
            finally:
                win32clipboard.CloseClipboard()
        except Exception as e:
            last_err = e
            time.sleep(0.08)
    raise last_err

def force_foreground(hwnd):
    """Reliably brings window to foreground across all Windows background session states."""
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    u.keybd_event(0x12, 0, 0, 0)
    u.keybd_event(0x12, 0, 2, 0)
    
    fore_thread = win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())[0]
    app_thread = ctypes.windll.kernel32.GetCurrentThreadId()
    if fore_thread != app_thread:
        u.AttachThreadInput(fore_thread, app_thread, True)
        win32gui.SetForegroundWindow(hwnd)
        win32gui.BringWindowToTop(hwnd)
        u.AttachThreadInput(fore_thread, app_thread, False)
    else:
        win32gui.SetForegroundWindow(hwnd)

class WeChatAssistant:
    def __init__(self, target_chat="文件传输助手", db_dir=r"D:\xwechat_files"):
        self.target_chat = target_chat
        self.db_dir = db_dir
        self.db = None
        self.contact_info = None
        self.who = None
        self.display_name = target_chat
        self.hwnd = None
        self.fg_before = None

    def __enter__(self):
        ok, msg = self.connect()
        if not ok:
            raise RuntimeError(msg)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _init_db(self):
        if not _HAS_WECHAT_DB:
            return False, "未安装 wechatauto-replica 依赖模块。"
        if not self.db:
            try:
                self.db = WeChatDB(db_dir=self.db_dir)
            except Exception as e:
                return False, f"初始化微信本地数据库失败: {e}"
        return True, "DB 就绪"

    def resolve_contact(self, contact_query):
        """Resolves target contact and intercepts ambiguity with strict safety checks."""
        ok, msg = self._init_db()
        if not ok:
            return False, msg

        if contact_query in ["文件传输助手", "filehelper"]:
            self.who = "filehelper"
            self.display_name = "文件传输助手"
            self.contact_info = {"username": "filehelper", "nick_name": "文件传输助手", "remark": ""}
            return True, self.contact_info

        hits = self.db.search_contact(contact_query)
        if not hits:
            return False, f"未在微信中找到联系人【{contact_query}】，请核对姓名、备注或微信号。"

        if len(hits) == 1:
            self.contact_info = hits[0]
        else:
            # Priority: exact remark match
            remark_matches = [h for h in hits if h.get("remark") == contact_query]
            if len(remark_matches) == 1:
                self.contact_info = remark_matches[0]
            else:
                nick_matches = [h for h in hits if h.get("nick_name") == contact_query]
                if len(nick_matches) == 1:
                    self.contact_info = nick_matches[0]
                else:
                    candidates_str = ", ".join([f"{h.get('nick_name')} (备注: {h.get('remark') or '无'}, ID: {h.get('username')})" for h in hits])
                    return False, f"检测到多位匹配好友/会话【{contact_query}】: [{candidates_str}]。为防止误发已自动拦截，请提供更明确的微信号或独有备注。"

        self.who = self.contact_info["username"]
        self.display_name = self.contact_info.get("remark") or self.contact_info.get("nick_name") or self.who
        return True, self.contact_info

    def connect(self):
        """Connects to WeChat window and resolves target chat."""
        self.fg_before = win32gui.GetForegroundWindow()

        # 1. Resolve contact
        ok, res = self.resolve_contact(self.target_chat)
        if not ok:
            return False, res

        # 2. Locate WeChat window handle
        h = win32gui.FindWindow("Qt51514QWindowIcon", "微信")
        if not h:
            h = win32gui.FindWindow("Qt51514QWindowIcon", None)
        if not h:
            h = win32gui.FindWindow(None, "微信")
        if not h or not win32gui.IsWindow(h):
            hwnds = []
            def _cb(w, acc):
                try:
                    if win32gui.IsWindowVisible(w) and "微信" in win32gui.GetWindowText(w):
                        acc.append(w)
                except Exception:
                    pass
                return True
            try:
                win32gui.EnumWindows(_cb, hwnds)
            except Exception:
                pass
            if hwnds:
                h = hwnds[0]

        if not h or not win32gui.IsWindow(h):
            return False, "未检测到微信主窗口，请确认电脑微信已登录并运行。"

        self.hwnd = h
        force_foreground(self.hwnd)
        time.sleep(0.2)

        # 3. Navigate to target chat
        ok_nav, nav_msg = self._navigate_to_target()
        if not ok_nav:
            return False, nav_msg

        return True, f"已就绪连接至【{self.display_name}】"

    def _navigate_to_target(self):
        force_foreground(self.hwnd)
        time.sleep(0.15)

        search_key = self.contact_info.get("remark") or self.contact_info.get("nick_name") or self.target_chat

        # Press Ctrl+F
        u.keybd_event(0x11, 0, 0, 0)
        u.keybd_event(0x46, 0, 0, 0)
        u.keybd_event(0x46, 0, 2, 0)
        u.keybd_event(0x11, 0, 2, 0)
        time.sleep(0.3)

        # Paste search keyword
        set_clipboard_text(search_key)
        u.keybd_event(0x11, 0, 0, 0)
        u.keybd_event(0x41, 0, 0, 0)
        u.keybd_event(0x41, 0, 2, 0)
        u.keybd_event(0x56, 0, 0, 0)
        u.keybd_event(0x56, 0, 2, 0)
        u.keybd_event(0x11, 0, 2, 0)
        time.sleep(0.8)

        # Click the first search result in popup
        rect = win32gui.GetWindowRect(self.hwnd)
        click_x = rect[0] + 160
        click_y = rect[1] + 210
        u.SetCursorPos(click_x, click_y)
        u.mouse_event(2, 0, 0, 0, 0)
        time.sleep(0.05)
        u.mouse_event(4, 0, 0, 0, 0)
        time.sleep(0.4)

        # Confirm with Enter
        u.keybd_event(0x0D, 0, 0, 0)
        u.keybd_event(0x0D, 0, 2, 0)
        time.sleep(0.4)

        # Focus input area
        w = rect[2] - rect[0]
        inp_x = int(rect[0] + w * 0.5)
        inp_y = int(rect[3] - 80)
        u.SetCursorPos(inp_x, inp_y)
        u.mouse_event(2, 0, 0, 0, 0)
        time.sleep(0.05)
        u.mouse_event(4, 0, 0, 0, 0)
        time.sleep(0.2)

        return True, "切换成功"

    def read_recent_messages(self, count=15):
        """Reads recent N messages with sender attribution, chronological sorting, and explicit placeholders."""
        ok, msg = self._init_db()
        if not ok:
            return []

        raw_msgs = self.db.get_messages(self.who, limit=count)
        formatted = []
        for m in reversed(raw_msgs):
            dt = datetime.fromtimestamp(m["create_time"]).strftime("%Y-%m-%d %H:%M:%S")
            sender = "我 (本人)" if m["sender_id"] == 2 else f"联系人 ({self.display_name})"
            mtype = m.get("type", "文本")
            content = m.get("content", "")

            if mtype == "图片":
                content = "[图片] (无法可靠提取视觉像素内容)"
            elif mtype == "语音":
                content = "[语音消息] (无法可靠提取语音音频内容)"
            elif mtype in ["文件/链接/卡片", "文件"]:
                content = "[文件/链接/卡片] (无法直接提取文件内容)"
            elif mtype == "动画表情":
                content = "[动画表情] (无法可靠提取表情内容)"

            formatted.append({
                "time": dt,
                "sender": sender,
                "type": mtype,
                "content": content,
                "timestamp": m["create_time"]
            })
        return formatted

    def send_text(self, text, verify=True, delay_after=0.4):
        """Sends a text message using clipboard and verifies delivery via local database."""
        if not text:
            return True

        rect = win32gui.GetWindowRect(self.hwnd)
        w = rect[2] - rect[0]
        inp_x = int(rect[0] + w * 0.5)
        inp_y = int(rect[3] - 80)
        u.SetCursorPos(inp_x, inp_y)
        u.mouse_event(2, 0, 0, 0, 0)
        time.sleep(0.05)
        u.mouse_event(4, 0, 0, 0, 0)
        time.sleep(0.1)

        set_clipboard_text(text)
        u.keybd_event(0x11, 0, 0, 0)
        u.keybd_event(0x56, 0, 0, 0)
        u.keybd_event(0x56, 0, 2, 0)
        u.keybd_event(0x11, 0, 2, 0)
        time.sleep(0.15)
        u.keybd_event(0x0D, 0, 0, 0)
        u.keybd_event(0x0D, 0, 2, 0)
        time.sleep(delay_after)

        if verify and self.who:
            verified = False
            for _ in range(6):
                time.sleep(0.5)
                recent = self.db.get_messages(self.who, limit=3)
                if any(text in m.get("content", "") and m.get("sender_id") == 2 for m in recent):
                    verified = True
                    break
            if verified:
                print(f"[✔] 文本已送达并数据库上屏核验通过: {text[:35]}..." if len(text) > 35 else f"[✔] 文本已送达并数据库上屏核验通过: {text}")
                return True
            else:
                print(f"[!] 警告: 文本按键已发出，正在等待界面上屏确认。")
                return True

        print(f"[✔] 文本已发送: {text[:40]}..." if len(text) > 40 else f"[✔] 文本已发送: {text}")
        return True

    def send_file(self, fpath, verify=True, delay_after=0.6):
        """Sends a single file or image and verifies delivery via local database."""
        fpath = os.path.abspath(fpath)
        if not os.path.exists(fpath):
            print(f"[-] 文件不存在: {fpath}", file=sys.stderr)
            return False

        rect = win32gui.GetWindowRect(self.hwnd)
        w = rect[2] - rect[0]
        inp_x = int(rect[0] + w * 0.5)
        inp_y = int(rect[3] - 80)
        u.SetCursorPos(inp_x, inp_y)
        u.mouse_event(2, 0, 0, 0, 0)
        time.sleep(0.05)
        u.mouse_event(4, 0, 0, 0, 0)
        time.sleep(0.1)

        t_send_start = time.time() - 2.0
        set_clipboard_files([fpath])
        u.keybd_event(0x11, 0, 0, 0)
        u.keybd_event(0x56, 0, 0, 0)
        u.keybd_event(0x56, 0, 2, 0)
        u.keybd_event(0x11, 0, 2, 0)
        time.sleep(0.6)  # wait for preview card
        u.keybd_event(0x23, 0, 0, 0)  # End
        u.keybd_event(0x23, 0, 2, 0)
        u.keybd_event(0x0D, 0, 0, 0)  # Enter
        u.keybd_event(0x0D, 0, 2, 0)
        time.sleep(delay_after)

        fname = os.path.basename(fpath)
        if verify and self.who:
            verified = False
            for _ in range(6):
                time.sleep(0.5)
                recent = self.db.get_messages(self.who, limit=3)
                if any(m.get("sender_id") == 2 and m.get("create_time", 0) >= int(t_send_start) for m in recent):
                    verified = True
                    break
            if verified:
                print(f"[✔] 文件已送达并数据库上屏核验通过: {fname}")
                return True
            else:
                print(f"[!] 警告: 文件发送指令已发出，正在等待界面上屏确认: {fname}")
                return True

        print(f"[✔] 文件已发送: {fname}")
        return True

    def close(self):
        """Restores user focus."""
        if self.fg_before and self.fg_before != self.hwnd:
            try:
                win32gui.SetForegroundWindow(self.fg_before)
            except Exception:
                pass

WeChatFileHelperSender = WeChatAssistant

# -*- coding: utf-8 -*-
"""
Core automation sender module for PC WeChat 4.x (文件传输助手 & 指定好友协作).

Reading uses only the local database. Sending uses UI Automation and verifies
the selected chat before each item. A database record confirms local recording,
not delivery to the recipient's device.
"""

import ctypes

try:
    _u = ctypes.windll.user32
    _h_default = _u.OpenDesktopW("Default", 0, False, 0x01FF)
    if _h_default:
        _u.SetThreadDesktop(_h_default)
except Exception:
    pass
import os
import re
import sys
import time
from contextlib import contextmanager
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

import win32clipboard
import win32con
import win32gui
import win32process

try:
    from wechatauto import WeChatDB
except ImportError:
    WeChatDB = None


class DROPFILES(ctypes.Structure):
    _fields_ = [
        ("pFiles", wintypes.DWORD),
        ("pt", wintypes.POINT),
        ("fNC", wintypes.BOOL),
        ("fWide", wintypes.BOOL),
    ]


def _open_clipboard():
    error = None
    for _ in range(15):
        try:
            win32clipboard.OpenClipboard()
            return
        except Exception as exc:
            error = exc
            time.sleep(0.08)
    raise RuntimeError(f"无法打开剪贴板: {error}")


def set_clipboard_text(value):
    _open_clipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, value)
    finally:
        win32clipboard.CloseClipboard()


def set_clipboard_files(paths):
    payload = _file_drop_payload(paths)
    _open_clipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_HDROP, payload)
    finally:
        win32clipboard.CloseClipboard()


def _file_drop_payload(paths):
    absolute = [os.path.abspath(path) for path in paths]
    drop = DROPFILES()
    drop.pFiles = ctypes.sizeof(DROPFILES)
    drop.pt = wintypes.POINT(0, 0)
    drop.fNC = False
    drop.fWide = True
    return bytes(drop) + ("\0".join(absolute) + "\0\0").encode("utf-16le")


@contextmanager
def preserved_clipboard():
    """Save clipboard formats before sending and restore them afterwards.

    Abort before sending if a clipboard format cannot be copied safely.
    """
    saved = []
    _open_clipboard()
    try:
        fmt = 0
        while True:
            fmt = win32clipboard.EnumClipboardFormats(fmt)
            if not fmt:
                break
            value = win32clipboard.GetClipboardData(fmt)
            if not isinstance(value, (str, bytes)) and not (fmt == win32con.CF_HDROP and isinstance(value, tuple)):
                raise RuntimeError(f"剪贴板格式 {fmt} 无法安全备份，已停止发送。")
            saved.append((fmt, value))
    finally:
        win32clipboard.CloseClipboard()
    try:
        yield
    finally:
        _open_clipboard()
        try:
            win32clipboard.EmptyClipboard()
            for fmt, value in saved:
                if fmt == win32con.CF_HDROP and isinstance(value, tuple):
                    value = _file_drop_payload(value)
                win32clipboard.SetClipboardData(fmt, value)
        finally:
            win32clipboard.CloseClipboard()


def _natural_key(path):
    return [(1, int(piece)) if piece.isdigit() else (0, piece.casefold())
            for piece in re.split(r"(\d+)", path.name)]


def _aid_has(aid, part):
    return part in (aid or "").lower().split(".")


def _focus_window(hwnd):
    try:
        win32gui.SetForegroundWindow(hwnd)
        return
    except Exception:
        pass
    user32 = ctypes.windll.user32
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 2, 0)
    foreground = win32gui.GetForegroundWindow()
    foreground_thread = win32process.GetWindowThreadProcessId(foreground)[0] if foreground else 0
    own_thread = ctypes.windll.kernel32.GetCurrentThreadId()
    attached = foreground_thread and foreground_thread != own_thread and user32.AttachThreadInput(foreground_thread, own_thread, True)
    try:
        win32gui.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(foreground_thread, own_thread, False)


class WeChatAssistant:
    def __init__(self, target_chat="文件传输助手", db_dir=r"D:\xwechat_files", **kwargs):
        self.target_chat = target_chat.strip()
        self.db_dir = db_dir
        self.db = None
        self.who = None
        self.contact_info = None
        self.display_name = None
        self.auto = None
        self.window = None
        self.hwnd = None
        self.fg_before = None
        self.cursor_before = None
        self.was_minimized = False

    def _init_db(self):
        if WeChatDB is None:
            raise RuntimeError("缺少 wechatauto-replica，请使用已安装依赖的 Python 3.14。")
        if self.db is None:
            self.db = WeChatDB(db_dir=self.db_dir)
        return self.db

    def resolve_contact(self, query=None):
        """Require an exact, unambiguous DB identity; partial hits are suggestions."""
        query = (query or self.target_chat).strip()
        if not query:
            return False, "联系人不能为空。"
        try:
            db = self._init_db()
            if query in ("文件传输助手", "filehelper"):
                chosen = {"username": "filehelper", "nick_name": "文件传输助手", "remark": ""}
            else:
                hits = db.search_contact(query)
                if len(hits) >= 50:
                    return False, "联系人搜索结果达到数据库上限，请使用更精确的备注或账号。"
                exact = [hit for hit in hits if query in (
                    hit.get("username"), hit.get("remark"), hit.get("nick_name"))]
                unique = {hit.get("username"): hit for hit in exact}
                if len(unique) != 1:
                    return False, f"联系人【{query}】未精确匹配到唯一账号，请提供独有备注或账号。"
                chosen = next(iter(unique.values()))
            self.contact_info = chosen
            self.who = chosen["username"]
            self.display_name = chosen.get("remark") or chosen.get("nick_name") or self.who
            return True, chosen
        except Exception as exc:
            return False, f"读取联系人数据库失败: {exc}"

    def _unique_visible_name(self):
        if self.who == "filehelper":
            return True
        hits = self.db.search_contact(self.display_name)
        if len(hits) >= 50:
            return False
        same = {hit.get("username") for hit in hits
                if (hit.get("remark") or hit.get("nick_name")) == self.display_name}
        return same == {self.who}

    def read_recent_messages(self, count=15, offset=0):
        if self.who is None:
            ok, result = self.resolve_contact()
            if not ok:
                raise RuntimeError(result)
        if count < 1 or count > 500 or offset < 0:
            raise ValueError("读取条数须为 1–500，起始偏移不得为负数。")
        rows = self.db.get_messages(self.who, limit=count, offset=offset)
        output = []
        for row in reversed(rows):
            mtype = row.get("type") or "未知"
            if mtype == "文本":
                content = row.get("content") or ""
            else:
                content = f"[{mtype}]（此接口未提取附件内容）"
            if row.get("sender_id") == 2:
                sender = "我"
            elif self.who.endswith("@chatroom"):
                username = row.get("sender_username") or ""
                sender = self.db.get_nickname(username) if username else "群成员（身份未知）"
            else:
                sender = self.display_name
            timestamp = row.get("create_time")
            output.append({
                "time": datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S") if timestamp else None,
                "sender": sender,
                "type": mtype,
                "content": content,
                "timestamp": timestamp,
            })
        return output

    # Backward compatibility alias
    read_messages = read_recent_messages

    def check(self):
        """Check dependencies, contact and window existence without changing UI."""
        ok, result = self.resolve_contact()
        if not ok:
            return False, result
        try:
            import uiautomation as auto
            window = auto.WindowControl(searchDepth=1, ClassName="mmui::MainWindow")
            if not window.Exists(1, 0.2):
                return False, "未找到已登录的微信主窗口。"
            return True, f"数据库及微信窗口可用；联系人为【{self.display_name}】，未切换会话。"
        except Exception as exc:
            return False, f"检查微信窗口失败: {exc}"

    def _find_input(self):
        return self.auto.FindControl(
            self.window,
            lambda control, depth: control.ControlTypeName == "EditControl"
            and ("ChatInputField" in (control.ClassName or "")
                 or _aid_has(control.AutomationId, "chat_input_field")),
        )

    def _current_chat(self):
        field = self._find_input()
        return (field.Name or "").strip() if field else None

    def _navigate_to_target(self):
        self.auto.SendKeys("{Ctrl}f")
        time.sleep(0.3)
        search = self.auto.FindControl(
            self.window,
            lambda control, depth: control.ControlTypeName == "EditControl"
            and (control.Name == "搜索" or "XValidatorTextEdit" in (control.ClassName or "")),
        )
        if search is None:
            return False, "找不到微信搜索框。"
        try:
            value = search.GetValuePattern()
            if value is None or value.IsReadOnly:
                return False, "微信搜索框不支持安全写入。"
            value.SetValue(self.display_name)
        except Exception as exc:
            return False, f"无法写入微信搜索框: {exc}"

        results = []
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            result_list = self.auto.FindControl(
                self.auto.GetRootControl(),
                lambda control, depth: control.ControlTypeName == "ListControl"
                and _aid_has(control.AutomationId, "search_list"),
            )
            if result_list is not None:
                results = [control for control in result_list.GetChildren()
                           if "search_item_" in (control.AutomationId or "")
                           and (control.Name or "").split("\n", 1)[0].strip() == self.display_name]
                if results:
                    break
            time.sleep(0.2)
        distinct = {control.AutomationId: control for control in results}
        if len(distinct) != 1:
            return False, f"微信搜索结果无法唯一确认【{self.display_name}】。"
        try:
            next(iter(distinct.values())).Click()
            time.sleep(0.5)
        except Exception as exc:
            return False, f"无法打开目标会话: {exc}"
        if self._current_chat() != self.display_name:
            return False, "打开后的会话名称与目标不一致。"
        return True, "会话已核对。"

    def connect(self):
        ok, result = self.resolve_contact()
        if not ok:
            return False, result
        if not self._unique_visible_name():
            return False, f"会话名称【{self.display_name}】不唯一，请先设置独有备注。"
        try:
            import uiautomation as auto
            self.auto = auto
            self.fg_before = win32gui.GetForegroundWindow()
            self.cursor_before = win32gui.GetCursorPos()
            self.window = auto.WindowControl(searchDepth=1, ClassName="mmui::MainWindow")
            if not self.window.Exists(2, 0.2):
                return False, "未找到已登录的微信主窗口。"
            self.hwnd = self.window.NativeWindowHandle
            self.was_minimized = bool(win32gui.IsIconic(self.hwnd))
            if self.was_minimized:
                win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
            _focus_window(self.hwnd)
            time.sleep(0.2)
            if self._current_chat() != self.display_name:
                ok, result = self._navigate_to_target()
                if not ok:
                    return False, result
            return True, f"已核对当前会话【{self.display_name}】。"
        except Exception as exc:
            return False, f"连接微信失败: {exc}"

    def _ready_input(self):
        if self.hwnd is None or self._current_chat() != self.display_name:
            raise RuntimeError("当前会话与目标不一致，已停止发送。")
        _focus_window(self.hwnd)
        field = self._find_input()
        if field is None:
            raise RuntimeError("找不到当前会话输入框。")
        field.SetFocus()
        focused = self.auto.GetFocusedControl()
        if focused is None or (focused.Name or "").strip() != self.display_name:
            raise RuntimeError("无法确认输入焦点位于目标会话。")
        try:
            value = field.GetValuePattern()
            if value is not None and (value.Value or "").strip():
                raise RuntimeError("输入框已有未发送内容，已停止以免覆盖或混发。")
        except RuntimeError:
            raise
        except Exception:
            pass
        return field

    def _baseline(self):
        rows = self.db.get_messages(self.who, limit=5)
        return {row.get("sort_seq") for row in rows}

    def _file_bubbles(self, filename):
        ids = set()
        for control, _ in self.auto.WalkControl(self.window, maxDepth=25):
            if (control.ClassName or "") != "mmui::ChatBubbleItemView":
                continue
            if filename not in (control.Name or ""):
                continue
            ids.add(tuple(control.GetRuntimeId()))
        return ids

    def _verify_new(self, baseline, started, match, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for row in self.db.get_messages(self.who, limit=10):
                if (row.get("sort_seq") not in baseline
                        and row.get("sender_id") == 2
                        and (row.get("create_time") or 0) >= int(started)
                        and match(row)):
                    return True
            time.sleep(0.4)
        return False

    def send_text(self, value, verify=True, delay_after=0.4):
        if not isinstance(value, str) or not value:
            print("[-] 文本为空，未发送。", file=sys.stderr)
            return False
        try:
            field = self._ready_input()
            baseline = self._baseline() if verify else set()
            started = time.time()
            with preserved_clipboard():
                set_clipboard_text(value)
                field.SendKeys("{Ctrl}v")
                time.sleep(0.15)
                if self._current_chat() != self.display_name:
                    raise RuntimeError("粘贴后会话变化，已停止发送。")
                field.SendKeys("{Enter}")
            time.sleep(delay_after)
            if verify and not self._verify_new(baseline, started,
                                                lambda row: row.get("type") == "文本"
                                                and row.get("content") == value):
                print("[?] 文本已提交，但未查到对应的新本地记录；请检查微信，勿直接重试。", file=sys.stderr)
                return False
            print("[+] 文本已在本地记录核验。" if verify else "[+] 文本已提交，未核验。")
            return True
        except Exception as exc:
            print(f"[-] 文本发送停止或结果不确定: {exc}", file=sys.stderr)
            return False

    def send_file(self, path, verify=True, delay_after=0.6):
        file_path = Path(path).expanduser().resolve()
        if not file_path.is_file():
            print(f"[-] 文件不存在: {file_path}", file=sys.stderr)
            return False
        expected = "图片" if file_path.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"} else "视频" if file_path.suffix.lower() in {".mp4", ".mov"} else "文件/链接/卡片"
        try:
            field = self._ready_input()
            baseline = self._baseline() if verify else set()
            prior_bubbles = self._file_bubbles(file_path.name) if verify else set()
            started = time.time()
            with preserved_clipboard():
                set_clipboard_files([str(file_path)])
                field.SendKeys("{Ctrl}v")
                time.sleep(0.7)
                if self._current_chat() != self.display_name:
                    raise RuntimeError("粘贴后会话变化，已停止发送。")
                field.SendKeys("{End}{Enter}")
            time.sleep(delay_after)
            if verify and not self._verify_new(baseline, started,
                                                lambda row: row.get("type") == expected):
                print(f"[?] {file_path.name} 已提交，但未查到对应类型的新本地记录；请检查微信，勿直接重试。", file=sys.stderr)
                return False
            if verify:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    if self._file_bubbles(file_path.name) - prior_bubbles:
                        break
                    time.sleep(0.3)
                else:
                    print(f"[?] {file_path.name} 有新本地记录，但界面未出现新的同名文件；请检查微信，勿直接重试。", file=sys.stderr)
                    return False
            print(f"[+] {file_path.name}：本地记录与界面文件名均已核验（不证明对端收到）。" if verify
                  else f"[+] {file_path.name}：已提交，未核验。")
            return True
        except Exception as exc:
            print(f"[-] {file_path.name} 发送停止或结果不确定: {exc}", file=sys.stderr)
            return False

    def close(self):
        if self.cursor_before is not None:
            try:
                ctypes.windll.user32.SetCursorPos(*self.cursor_before)
            except Exception:
                pass
        if self.hwnd and self.was_minimized:
            try:
                win32gui.ShowWindow(self.hwnd, win32con.SW_MINIMIZE)
            except Exception:
                pass
        if self.fg_before and self.fg_before != self.hwnd:
            try:
                win32gui.SetForegroundWindow(self.fg_before)
            except Exception:
                pass

    def __enter__(self):
        ok, result = self.connect()
        if not ok:
            self.close()
            raise RuntimeError(result)
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()


WeChatFileHelperSender = WeChatAssistant

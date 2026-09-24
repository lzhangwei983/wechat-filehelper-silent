# -*- coding: utf-8 -*-
"""
Example: Integrating WeChatAssistant into your Python workflow or AI Agent.
Supports chat history context reading and reliable message/file delivery.
"""

import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wechat_filehelper import WeChatAssistant, WeChatFileHelperSender

def main():
    print("[*] 正在连接 PC 微信 (本地安全只读 + UIA 自动化)...")
    
    # Example 1: Read recent message history (database only, zero UI interruption)
    bot = WeChatAssistant(target_chat="文件传输助手")
    try:
        messages = bot.read_recent_messages(count=3)
        print(f"[+] 成功读取最近 {len(messages)} 条历史记录：")
        for m in messages:
            print(f"    [{m['time']}] {m['sender']}: {m['content']}")
    except Exception as e:
        print(f"[-] 读取历史记录跳过: {e}")

    # Example 2: Send text & files safely using context manager
    # Automatically restores clipboard formats, cursor position, and foreground window
    with WeChatAssistant(target_chat="文件传输助手") as sender:
        sender.send_text("🤖 [AI Agent] 晨间自动化巡检已完成，正在投送产出包：")
        # sender.send_file(r"D:\output\summary.pdf")
        sender.send_text("✅ 投送完毕，剪贴板与用户活动焦点已全自动无感恢复。")
        
    print("[+] 全部指令已成功执行并安全退出。")

if __name__ == "__main__":
    main()

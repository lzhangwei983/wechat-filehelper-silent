# -*- coding: utf-8 -*-
"""
Example: Integrating WeChatFileHelperSender into your Python workflow or AI Agent.
"""

import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wechat_filehelper import WeChatFileHelperSender

def main():
    print("[*] 正在连接 PC 微信文件传输助手 (后台静默模式)...")
    
    # Use context manager for automatic focus save/restore & resource cleanup
    with WeChatFileHelperSender(target_chat="文件传输助手", silent=True) as sender:
        # 1. Send inline message
        sender.send_text("🤖 [AI Agent] 晨间自动化巡检已完成，正在投送产出包：")
        
        # 2. Example: Send single or multiple files if they exist
        # sender.send_file(r"D:\output\summary.pdf")
        
        sender.send_text("✅ 投送完毕，用户前台窗口与焦点已自动恢复。")
        
    print("[+] 全部指令已成功执行并安全退出。")

if __name__ == "__main__":
    main()

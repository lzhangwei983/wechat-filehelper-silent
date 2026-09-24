# WeChat automation implementation notes

## Read path

`--read` resolves an exact contact through `wechatauto-replica`'s `WeChatDB`, then calls `get_messages`. It does not use UI Automation. `--check` verifies the database, exact contact, and existence of a logged-in main window; it does not navigate and is not a send test.

## Send path

The script first requires a unique visible chat name. It locates the WeChat 4.x main window using UI Automation (`mmui::MainWindow`), then checks the `ChatInputField` name. If navigation is needed, it opens Ctrl+F, writes the search edit with UIA ValuePattern, selects one exact result from `search_list`, and checks the resulting chat input name. It never chooses a result by fixed screen coordinates. The message input focus and chat name are checked before each paste and again before Enter.

For text, verification requires a new outgoing database row after the pre-send baseline, with exact content. For files, verification requires a new outgoing row of the expected type and a new `mmui::ChatBubbleItemView` containing the file name. These checks establish local recording and UI appearance, not delivery to the other device. If verification fails, the script returns failure without automatically retrying; the input action may already have sent the item.

## Windows state

Sending pastes `CF_UNICODETEXT` or `CF_HDROP` through the clipboard. Before changing it, the script copies all retrievable clipboard formats, aborting if a format cannot be copied. It restores those formats in `finally`. It also attempts to restore the previous cursor, minimized state, and foreground window on exit. The UI remains visible during sending; a fully transparent window prevents reliable pointer interaction in WeChat 4.x.

For contact ambiguity, exact database identity alone is insufficient: WeChat's search input does not reliably accept an internal `wxid`. If two people would show the same chat name, sending stops and asks for a unique remark. History reading can still use the internal account ID because it does not navigate the UI.

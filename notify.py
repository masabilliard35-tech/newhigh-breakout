"""通知の送信。環境変数にあるものを自動で使う（Discord優先、なければLINE）。
- DISCORD_WEBHOOK : Discordチャンネルの Webhook URL（無制限・簡単）
- LINE_TOKEN + LINE_USER_ID : LINE Messaging API（月200通まで無料）
どちらも未設定なら標準出力に出すだけ。
"""
import os

import requests


def send(text):
    hook = os.environ.get("DISCORD_WEBHOOK")
    if hook:
        try:
            requests.post(hook, json={"content": text[:1900]}, timeout=20)
            return "discord"
        except Exception as e:
            print("discord失敗:", e)

    token = os.environ.get("LINE_TOKEN")
    uid = os.environ.get("LINE_USER_ID")
    if token and uid:
        try:
            requests.post("https://api.line.me/v2/bot/message/push",
                          headers={"Authorization": f"Bearer {token}",
                                   "Content-Type": "application/json"},
                          json={"to": uid, "messages": [{"type": "text", "text": text[:4900]}]},
                          timeout=20)
            return "line"
        except Exception as e:
            print("line失敗:", e)

    print("=== 通知（未設定のため表示のみ）===")
    print(text)
    return "stdout"

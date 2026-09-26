"""Send authorized project notifications; credentials are Actions secrets only."""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise SystemExit("Notifications run in GitHub Actions")
    parser = argparse.ArgumentParser()
    parser.add_argument("--message", required=True)
    parser.add_argument("--optional", action="store_true")
    args = parser.parse_args()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        if args.optional:
            print("Telegram: NOT_CONFIGURED")
            return
        raise SystemExit("Missing TELEGRAM_BOT_TOKEN secret")

    def api(method, payload):
        request = urllib.request.Request(
            "https://api.telegram.org/bot" + token + "/" + method,
            data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.load(response)
        except (urllib.error.HTTPError, urllib.error.URLError):
            raise SystemExit("Telegram request failed; credentials and response omitted") from None
        if not result.get("ok"):
            raise SystemExit("Telegram rejected notification; private response omitted")
        return result["result"]

    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    discovered = not bool(chat_id)
    if discovered:
        chats = {str(u["message"]["chat"]["id"]) for u in api("getUpdates", {"timeout": 0})
                 if u.get("message", {}).get("chat", {}).get("type") == "private"}
        if len(chats) != 1:
            raise SystemExit("Set TELEGRAM_CHAT_ID, or press Start in the new bot's only private chat")
        chat_id = chats.pop()
    print("::add-mask::" + chat_id)
    api("sendMessage", {"chat_id": chat_id, "text": args.message[:4000],
                        "link_preview_options": {"is_disabled": True}})
    if discovered:
        api("sendMessage", {"chat_id": chat_id,
            "text": "Для постоянных уведомлений сохраните значение " + chat_id +
                    " как секрет TELEGRAM_CHAT_ID в настройках репозитория. "
                    "Сейчас адрес найден автоматически по вашему Start; Telegram хранит такие обновления ограниченное время.\n"
                    "https://github.com/a-a-k/sheaft-tsfg-experiments/settings/secrets/actions/new"})
    print("Telegram: SENT")


if __name__ == "__main__":
    main()


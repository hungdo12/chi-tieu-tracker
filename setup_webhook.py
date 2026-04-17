"""
Script setup: đăng ký webhook cho Telegram bot
Chạy 1 lần sau khi deploy app lên Render

Cách dùng:
  python setup_webhook.py

Nhập bot token và URL app khi được hỏi.
"""

import httpx
import json

def setup_webhook():
    print("=" * 50)
    print("  Chi Tiêu Tracker - Setup Webhook")
    print("=" * 50)
    print()
    
    app_url = input("🌐 URL app của bạn (vd: https://chi-tieu.onrender.com): ").strip().rstrip('/')
    print()
    print("Bạn có thể setup nhiều bot (nhiều người dùng)")
    print("Mỗi người cần 1 bot Telegram riêng\n")
    
    while True:
        token = input("🤖 Bot Token (paste vào, Enter để bỏ qua): ").strip()
        if not token:
            break
        
        webhook_url = f"{app_url}/webhook/{token}"
        
        resp = httpx.post(
            f"https://api.telegram.org/bot{token}/setWebhook",
            json={"url": webhook_url, "allowed_updates": ["message"]}
        )
        result = resp.json()
        
        if result.get("ok"):
            print(f"  ✅ Webhook đã đăng ký: {webhook_url}")
            
            # Lấy bot info
            info = httpx.get(f"https://api.telegram.org/bot{token}/getMe").json()
            if info.get("ok"):
                bot = info["result"]
                print(f"  🤖 Bot: @{bot.get('username')} ({bot.get('first_name')})")
        else:
            print(f"  ❌ Lỗi: {result.get('description')}")
        
        print()
        another = input("Thêm bot khác? (y/n): ").strip().lower()
        if another != 'y':
            break
    
    print()
    print("=" * 50)
    print("✅ Setup hoàn tất!")
    print()
    print("📱 Hướng dẫn cho từng người dùng:")
    print("1. Tìm bot Telegram của mình")
    print("2. Nhắn /start")
    print("3. Nhắn /register TênCủaBạn")
    print("4. Bắt đầu ghi: '50k ăn phở'")
    print()
    print(f"🌐 Dashboard: {app_url}")
    print("=" * 50)


if __name__ == "__main__":
    setup_webhook()

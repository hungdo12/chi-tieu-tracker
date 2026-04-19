"""
Chi Tiêu Tracker - Backend FastAPI
- Nhận webhook từ Telegram bots
- Lưu data vào Google Sheets
- Gửi thông báo tổng hàng tháng
- Multi-user: mỗi user setup tên + bot riêng
"""

import os
import json
import re
import asyncio
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import gspread
from google.oauth2.service_account import Credentials
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ─── CONFIG ────────────────────────────────────────────────────────────────────
GOOGLE_SHEETS_ID = os.environ.get("GOOGLE_SHEETS_ID", "")
GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_CREDS_JSON", "")  # JSON string của service account

# Map: telegram_bot_token -> user config
# Ví dụ: {"TOKEN_A": {"name": "Hung", "chat_id": null}, ...}
# Được lưu trong Google Sheets sheet "users"
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(title="Chi Tiêu Tracker")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

scheduler = AsyncIOScheduler(timezone="Asia/Ho_Chi_Minh")


# ─── GOOGLE SHEETS HELPER ─────────────────────────────────────────────────────

def get_sheets_client():
    """Kết nối Google Sheets"""
    creds_data = json.loads(GOOGLE_CREDS_JSON)
    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_data, scopes=scopes)
    return gspread.authorize(creds)


def get_or_create_sheet(gc, sheet_name: str):
    """Lấy sheet theo tên, tạo mới nếu chưa có"""
    spreadsheet = gc.open_by_key(GOOGLE_SHEETS_ID)
    try:
        return spreadsheet.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=20)
        return ws


def init_sheets():
    """Khởi tạo các sheet cần thiết"""
    gc = get_sheets_client()
    
    # Sheet chi tiêu chính
    expenses_ws = get_or_create_sheet(gc, "expenses")
    if expenses_ws.row_count == 1 or not expenses_ws.get_all_values():
        expenses_ws.append_row([
            "id", "timestamp", "user_name", "amount", 
            "category", "note", "month_key"
        ])
    
    # Sheet users
    users_ws = get_or_create_sheet(gc, "users")
    if not users_ws.get_all_values():
        users_ws.append_row([
            "bot_token", "user_name", "chat_id", "monthly_budget", "registered_at"
        ])
    
    return gc


# ─── USER MANAGEMENT ──────────────────────────────────────────────────────────

def get_user_by_token(gc, bot_token: str) -> Optional[dict]:
    """Tìm user theo bot token"""
    ws = get_or_create_sheet(gc, "users")
    records = ws.get_all_records()
    for row in records:
        if row.get("bot_token") == bot_token:
            return row
    return None


def register_user(gc, bot_token: str, user_name: str, chat_id: int, monthly_budget: float = 0):
    """Đăng ký user mới"""
    ws = get_or_create_sheet(gc, "users")
    ws.append_row([
        bot_token,
        user_name,
        chat_id,
        monthly_budget,
        datetime.now(timezone.utc).isoformat()
    ])


def update_user_chat_id(gc, bot_token: str, chat_id: int):
    """Cập nhật chat_id khi user /start"""
    ws = get_or_create_sheet(gc, "users")
    records = ws.get_all_records()
    for i, row in enumerate(records, start=2):
        if row.get("bot_token") == bot_token:
            ws.update_cell(i, 3, chat_id)  # cột chat_id
            return True
    return False


# ─── EXPENSE HELPERS ──────────────────────────────────────────────────────────

CATEGORIES = {
    "ăn": "🍜 Ăn uống",
    "uống": "🍜 Ăn uống", 
    "cà phê": "☕ Cà phê",
    "cafe": "☕ Cà phê",
    "xăng": "⛽ Di chuyển",
    "grab": "⛽ Di chuyển",
    "điện": "🏠 Nhà cửa",
    "nước": "🏠 Nhà cửa",
    "thuê": "🏠 Nhà cửa",
    "mua": "🛍️ Mua sắm",
    "quần": "🛍️ Mua sắm",
    "áo": "🛍️ Mua sắm",
    "thuốc": "💊 Y tế",
    "khám": "💊 Y tế",
    "gym": "💪 Thể thao",
    "chơi": "🎮 Giải trí",
    "game": "🎮 Giải trí",
    "phim": "🎮 Giải trí",
}

def detect_category(note: str) -> str:
    """Tự động nhận dạng danh mục từ ghi chú"""
    note_lower = note.lower()
    for keyword, category in CATEGORIES.items():
        if keyword in note_lower:
            return category
    return "📦 Khác"


def parse_expense_message(text: str) -> Optional[dict]:
    """
    Parse tin nhắn chi tiêu.
    Formats được chấp nhận:
    - "50k ăn phở"
    - "150000 xăng"
    - "2tr mua áo"  
    - "500 cà phê sáng"
    """
    text = text.strip()
    
    # Pattern: số (k/tr/ngàn) + ghi chú
    patterns = [
        r'^(\d+(?:\.\d+)?)\s*tr\s+(.+)$',      # 2tr ...
        r'^(\d+(?:\.\d+)?)\s*triệu\s+(.+)$',   # 2triệu ...
        r'^(\d+(?:\.\d+)?)\s*k\s+(.+)$',        # 50k ...
        r'^(\d+(?:\.\d+)?)\s*ngàn\s+(.+)$',     # 50ngàn ...
        r'^(\d+(?:\.\d+)?)\s*000\s+(.+)$',      # 50000 ...
        r'^(\d+)\s+(.+)$',                       # 50000 ...
    ]
    
    multipliers = {
        'tr': 1_000_000,
        'triệu': 1_000_000,
        'k': 1_000,
        'ngàn': 1_000,
        '000': 1_000,  # nếu số kết thúc bằng 000
    }
    
    for i, pattern in enumerate(patterns):
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            amount_str = match.group(1)
            note = match.group(2).strip()
            amount = float(amount_str)
            
            # Áp dụng multiplier
            if i == 0: amount *= 1_000_000
            elif i == 1: amount *= 1_000_000
            elif i == 2: amount *= 1_000
            elif i == 3: amount *= 1_000
            elif i == 4: amount *= 1_000
            # i == 5: giữ nguyên (giả định đã là VND đủ)
            # Nếu số < 1000 và không có suffix, coi là nghìn
            elif amount < 10000:
                amount *= 1_000
            
            category = detect_category(note)
            return {
                "amount": int(amount),
                "note": note,
                "category": category,
            }
    
    return None


def save_expense(gc, user_name: str, amount: int, category: str, note: str):
    """Lưu chi tiêu vào Google Sheets"""
    ws = get_or_create_sheet(gc, "expenses")
    now = datetime.now(timezone(offset=__import__('datetime').timedelta(hours=7)))
    month_key = now.strftime("%Y-%m")
    
    # Generate ID đơn giản
    all_rows = ws.get_all_values()
    expense_id = len(all_rows)  # row count làm ID
    
    ws.append_row([
        expense_id,
        now.strftime("%Y-%m-%d %H:%M:%S"),
        user_name,
        amount,
        category,
        note,
        month_key,
    ])
    return expense_id


def get_monthly_summary(gc, month_key: str = None) -> dict:
    """Lấy tổng chi tiêu theo tháng, chia theo từng người"""
    if not month_key:
        month_key = datetime.now().strftime("%Y-%m")
    
    ws = get_or_create_sheet(gc, "expenses")
    records = ws.get_all_records()
    
    summary = {}  # user_name -> {total, categories: {cat -> amount}, count}
    
    for row in records:
        if row.get("month_key") != month_key:
            continue
        name = row.get("user_name", "Unknown")
        amount = int(row.get("amount", 0))
        category = row.get("category", "📦 Khác")
        
        if name not in summary:
            summary[name] = {"total": 0, "categories": {}, "count": 0, "expenses": []}
        
        summary[name]["total"] += amount
        summary[name]["count"] += 1
        summary[name]["categories"][category] = summary[name]["categories"].get(category, 0) + amount
        summary[name]["expenses"].append({
            "timestamp": row.get("timestamp"),
            "amount": amount,
            "category": category,
            "note": row.get("note"),
        })
    
    return summary


def get_all_users(gc) -> list:
    """Lấy danh sách tất cả users"""
    ws = get_or_create_sheet(gc, "users")
    return ws.get_all_records()


# ─── TELEGRAM BOT HELPERS ─────────────────────────────────────────────────────

async def send_telegram(bot_token: str, chat_id: int, text: str, parse_mode: str = "HTML"):
    """Gửi tin nhắn Telegram"""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    async with httpx.AsyncClient() as client:
        await client.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        })


def format_vnd(amount: int) -> str:
    """Format số tiền VND"""
    if amount >= 1_000_000:
        return f"{amount/1_000_000:.1f}tr"
    elif amount >= 1_000:
        return f"{amount//1_000}k"
    return f"{amount:,}đ"


# ─── WEBHOOK ENDPOINTS ────────────────────────────────────────────────────────

@app.post("/webhook/{bot_token}")
async def telegram_webhook(bot_token: str, request: Request):
    """
    Nhận update từ Telegram.
    Mỗi bot có 1 webhook URL riêng với token trong path.
    """
    try:
        data = await request.json()
    except:
        raise HTTPException(400, "Invalid JSON")
    
    message = data.get("message") or data.get("edited_message")
    if not message:
        return {"ok": True}
    
    chat_id = message["chat"]["id"]
    text = message.get("text", "").strip()
    
    if not text:
        return {"ok": True}
    
    try:
        gc = get_sheets_client()
    except Exception as e:
        print(f"Sheets error: {e}")
        return {"ok": True}
    
    user = get_user_by_token(gc, bot_token)
    
    # ── Lệnh /start ──
    if text.startswith("/start"):
        if user:
            # Cập nhật chat_id
            update_user_chat_id(gc, bot_token, chat_id)
            await send_telegram(bot_token, chat_id,
                f"👋 Chào lại <b>{user['user_name']}</b>!\n\n"
                "📝 Nhắn chi tiêu theo format:\n"
                "<code>50k ăn phở</code>\n"
                "<code>2tr mua điện thoại</code>\n"
                "<code>150000 xăng xe</code>\n\n"
                "📊 /summary - Xem tổng tháng này\n"
                "❓ /help - Hướng dẫn"
            )
        else:
            await send_telegram(bot_token, chat_id,
                "👋 Chào mừng đến với <b>Chi Tiêu Tracker</b>!\n\n"
                "Để bắt đầu, hãy đăng ký tên của bạn:\n"
                "<code>/register TênCủaBạn</code>\n\n"
                "Ví dụ: <code>/register Hung</code>"
            )
        return {"ok": True}
    
    # ── Lệnh /register ──
    if text.startswith("/register"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await send_telegram(bot_token, chat_id,
                "❌ Vui lòng nhập tên!\n"
                "Ví dụ: <code>/register Hung</code>"
            )
            return {"ok": True}
        
        user_name = parts[1].strip()
        if user:
            update_user_chat_id(gc, bot_token, chat_id)
            await send_telegram(bot_token, chat_id, f"✅ Bạn đã đăng ký rồi với tên <b>{user['user_name']}</b>")
        else:
            register_user(gc, bot_token, user_name, chat_id)
            update_user_chat_id(gc, bot_token, chat_id)
            await send_telegram(bot_token, chat_id,
                f"✅ Đã đăng ký thành công!\n\n"
                f"👤 Tên: <b>{user_name}</b>\n\n"
                "📝 Bắt đầu ghi chi tiêu:\n"
                "<code>50k ăn phở</code>\n"
                "<code>2tr mua áo</code>\n"
                "<code>300k xăng xe</code>"
            )
        return {"ok": True}
    
    # ── Lệnh /summary ──
    if text.startswith("/summary"):
        if not user:
            await send_telegram(bot_token, chat_id, "❌ Bạn chưa đăng ký!\nDùng: <code>/register TênCủaBạn</code>")
            return {"ok": True}
        
        month_key = datetime.now().strftime("%Y-%m")
        summary = get_monthly_summary(gc, month_key)
        user_name = user["user_name"]
        
        if user_name not in summary:
            month_display = datetime.now().strftime("%m/%Y")
            await send_telegram(bot_token, chat_id, f"📊 Tháng {month_display}: chưa có chi tiêu nào!")
            return {"ok": True}
        
        data = summary[user_name]
        month_display = datetime.now().strftime("%m/%Y")
        
        # Sort categories by amount
        sorted_cats = sorted(data["categories"].items(), key=lambda x: x[1], reverse=True)
        cat_lines = "\n".join([f"  {cat}: <b>{format_vnd(amt)}</b>" for cat, amt in sorted_cats])
        
        budget = float(user.get("monthly_budget", 0) or 0)
        budget_line = ""
        if budget > 0:
            remaining = budget - data["total"]
            if remaining > 0:
                budget_line = f"\n💰 Ngân sách còn lại: <b>{format_vnd(int(remaining))}</b>"
            else:
                budget_line = f"\n⚠️ Đã vượt ngân sách: <b>{format_vnd(int(abs(remaining)))}</b>"
        
        msg = (
            f"📊 <b>Chi tiêu tháng {month_display}</b>\n"
            f"👤 {user_name}\n"
            f"{'─'*25}\n"
            f"{cat_lines}\n"
            f"{'─'*25}\n"
            f"💸 Tổng: <b>{format_vnd(data['total'])}</b>\n"
            f"📝 Số lần: {data['count']} khoản"
            f"{budget_line}"
        )
        await send_telegram(bot_token, chat_id, msg)
        return {"ok": True}
    
    # ── Lệnh /budget ──
    if text.startswith("/budget"):
        if not user:
            await send_telegram(bot_token, chat_id, "❌ Bạn chưa đăng ký!")
            return {"ok": True}
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await send_telegram(bot_token, chat_id,
                "💰 Đặt ngân sách tháng:\n"
                "<code>/budget 10000000</code> (10 triệu)\n"
                "<code>/budget 5000000</code> (5 triệu)"
            )
            return {"ok": True}
        try:
            budget_amount = int(parts[1].replace(",", "").replace(".", ""))
            ws = get_or_create_sheet(gc, "users")
            records = ws.get_all_records()
            for i, row in enumerate(records, start=2):
                if row.get("bot_token") == bot_token:
                    ws.update_cell(i, 4, budget_amount)
                    break
            await send_telegram(bot_token, chat_id, f"✅ Đã đặt ngân sách tháng: <b>{format_vnd(budget_amount)}</b>")
        except:
            await send_telegram(bot_token, chat_id, "❌ Số tiền không hợp lệ!")
        return {"ok": True}
    
    # ── Lệnh /help ──
    if text.startswith("/help"):
        await send_telegram(bot_token, chat_id,
            "📖 <b>Hướng dẫn sử dụng</b>\n\n"
            "<b>Ghi chi tiêu:</b>\n"
            "<code>50k ăn phở bò</code>\n"
            "<code>2tr mua điện thoại</code>\n"
            "<code>150000 xăng xe</code>\n"
            "<code>300 cafe sáng</code> (→ 300k)\n\n"
            "<b>Lệnh:</b>\n"
            "/summary - Xem tổng tháng này\n"
            "/budget [số] - Đặt ngân sách tháng\n"
            "/help - Hướng dẫn này\n\n"
            "<b>Danh mục tự động nhận biết:</b>\n"
            "🍜 ăn/uống | ☕ cafe\n"
            "⛽ xăng/grab | 🏠 điện/nước\n"
            "🛍️ mua/quần/áo | 💊 thuốc/khám\n"
            "💪 gym | 🎮 chơi/game/phim"
        )
        return {"ok": True}
    
    # ── Ghi chi tiêu thường ──
    if not user:
        await send_telegram(bot_token, chat_id,
            "❌ Bạn chưa đăng ký!\n"
            "Dùng: <code>/register TênCủaBạn</code>"
        )
        return {"ok": True}
    
    parsed = parse_expense_message(text)
    if parsed:
        expense_id = save_expense(
            gc,
            user_name=user["user_name"],
            amount=parsed["amount"],
            category=parsed["category"],
            note=parsed["note"],
        )
        
        # Tính tổng tháng hiện tại của user này
        month_key = datetime.now().strftime("%Y-%m")
        summary = get_monthly_summary(gc, month_key)
        user_total = summary.get(user["user_name"], {}).get("total", 0)
        
        budget = float(user.get("monthly_budget", 0) or 0)
        budget_line = ""
        if budget > 0:
            remaining = budget - user_total
            if remaining > 0:
                budget_line = f"\n💰 Còn lại tháng: <b>{format_vnd(int(remaining))}</b>"
            else:
                budget_line = f"\n⚠️ Vượt ngân sách <b>{format_vnd(int(abs(remaining)))}</b>!"
        
        await send_telegram(bot_token, chat_id,
            f"✅ Đã ghi!\n"
            f"{parsed['category']}\n"
            f"💸 <b>{format_vnd(parsed['amount'])}</b> - {parsed['note']}\n"
            f"📊 Tổng tháng: <b>{format_vnd(user_total)}</b>"
            f"{budget_line}"
        )
    else:
        await send_telegram(bot_token, chat_id,
            "❓ Không hiểu định dạng.\n\n"
            "Thử: <code>50k ăn phở</code>\n"
            "Hoặc: <code>150000 xăng xe</code>\n\n"
            "/help - xem hướng dẫn"
        )
    
    return {"ok": True}


# ─── API ENDPOINTS CHO WEB APP ────────────────────────────────────────────────

@app.get("/api/summary")
async def api_summary(month: str = None):
    """API trả về dữ liệu tổng hợp cho web dashboard"""
    try:
        gc = get_sheets_client()
        if not month:
            month = datetime.now().strftime("%Y-%m")
        summary = get_monthly_summary(gc, month)
        users = get_all_users(gc)
        
        # Tính tổng chung
        grand_total = sum(u["total"] for u in summary.values())
        
        return {
            "month": month,
            "grand_total": grand_total,
            "users": summary,
            "registered_users": [
                {"name": u["user_name"], "budget": float(u.get("monthly_budget", 0) or 0)}
                for u in users
            ]
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/months")
async def api_months():
    """Lấy danh sách các tháng có dữ liệu"""
    try:
        gc = get_sheets_client()
        ws = get_or_create_sheet(gc, "expenses")
        records = ws.get_all_records()
        months = sorted(set(r.get("month_key", "") for r in records if r.get("month_key")), reverse=True)
        return {"months": months}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/register-webhook")
async def register_webhook(request: Request):
    """
    Helper: Đăng ký webhook URL cho bot Telegram.
    Body: {"bot_token": "...", "webhook_url": "https://your-app.render.com"}
    """
    data = await request.json()
    bot_token = data.get("bot_token")
    webhook_base = data.get("webhook_url")
    
    if not bot_token or not webhook_base:
        raise HTTPException(400, "Cần bot_token và webhook_url")
    
    webhook_url = f"{webhook_base.rstrip('/')}/webhook/{bot_token}"
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{bot_token}/setWebhook",
            json={"url": webhook_url}
        )
        result = resp.json()
    
    return {
        "webhook_url": webhook_url,
        "telegram_response": result
    }


@app.get("/api/health")
async def health():
    return {"status": "ok", "time": datetime.now().isoformat()}


# ─── MONTHLY SUMMARY JOB ──────────────────────────────────────────────────────

async def send_monthly_summary():
    """
    Chạy vào đầu tháng (ngày 1, 8:00 sáng VN) 
    → Gửi tổng chi tiêu tháng trước cho tất cả users
    """
    try:
        gc = get_sheets_client()
        now = datetime.now()
        
        # Tháng trước
        if now.month == 1:
            prev_month = f"{now.year - 1}-12"
        else:
            prev_month = f"{now.year}-{now.month - 1:02d}"
        
        month_display = datetime.strptime(prev_month, "%Y-%m").strftime("%m/%Y")
        summary = get_monthly_summary(gc, prev_month)
        users = get_all_users(gc)
        
        for user in users:
            token = user.get("bot_token")
            chat_id = user.get("chat_id")
            name = user.get("user_name")
            budget = float(user.get("monthly_budget", 0) or 0)
            
            if not token or not chat_id:
                continue
            
            if name in summary:
                data = summary[name]
                sorted_cats = sorted(data["categories"].items(), key=lambda x: x[1], reverse=True)
                cat_lines = "\n".join([f"  {cat}: {format_vnd(amt)}" for cat, amt in sorted_cats])
                
                budget_line = ""
                if budget > 0:
                    diff = data["total"] - budget
                    if diff > 0:
                        budget_line = f"\n⚠️ Vượt ngân sách: {format_vnd(int(diff))}"
                    else:
                        budget_line = f"\n✅ Tiết kiệm được: {format_vnd(int(abs(diff)))}"
                
                msg = (
                    f"📅 <b>Tổng kết tháng {month_display}</b>\n"
                    f"👤 {name}\n{'─'*25}\n"
                    f"{cat_lines}\n{'─'*25}\n"
                    f"💸 Tổng chi: <b>{format_vnd(data['total'])}</b>\n"
                    f"📝 {data['count']} khoản chi"
                    f"{budget_line}"
                )
            else:
                msg = f"📅 Tháng {month_display}: Bạn không có chi tiêu nào! 🎉"
            
            try:
                await send_telegram(token, int(chat_id), msg)
            except Exception as e:
                print(f"Error sending to {name}: {e}")
    
    except Exception as e:
        print(f"Monthly summary error: {e}")


# ─── STARTUP ─────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    """Khởi động app: init sheets + scheduler"""
    print("🚀 Chi Tiêu Tracker starting...")
    
    if GOOGLE_SHEETS_ID and GOOGLE_CREDS_JSON:
        try:
            init_sheets()
            print("✅ Google Sheets connected")
        except Exception as e:
            import traceback
            print(f"⚠️  Google Sheets error: {e}")
            print(traceback.format_exc())
    else:
        print(f"⚠️  Thiếu biến: SHEETS_ID='{GOOGLE_SHEETS_ID}' CREDS='{GOOGLE_CREDS_JSON[:20] if GOOGLE_CREDS_JSON else 'TRỐNG'}'")
    
    # Scheduler: gửi tổng kết tháng vào ngày 1 mỗi tháng, 8:00 sáng
    scheduler.add_job(send_monthly_summary, "cron", day=1, hour=8, minute=0)
    scheduler.start()
    print("✅ Scheduler started (monthly summary: 1st of month, 8AM VN)")


@app.on_event("shutdown")
async def shutdown():
    scheduler.shutdown()


# Mount frontend static files
import os
if os.path.exists("frontend"):
    app.mount("/", StaticFiles(directory="frontend", html=True), name="static")

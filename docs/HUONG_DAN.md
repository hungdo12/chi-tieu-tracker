# 📱 Chi Tiêu Tracker - Hướng Dẫn Cài Đặt

## Tổng quan

App gồm 3 phần chính:
- **Backend Python** (FastAPI) → deploy lên Render.com
- **Google Sheets** → lưu trữ dữ liệu miễn phí
- **Telegram Bot** → mỗi người tự tạo bot riêng để ghi chi tiêu

---

## BƯỚC 1 — Tạo Google Sheets + Service Account

### 1.1. Tạo Google Spreadsheet mới
1. Vào https://sheets.google.com → Tạo spreadsheet mới
2. Đặt tên tùy ý (vd: "Chi Tiêu Tracker")
3. Copy **ID** từ URL: `https://docs.google.com/spreadsheets/d/**{ID_Ở_ĐÂY}**/edit`

### 1.2. Tạo Google Service Account
1. Vào https://console.cloud.google.com
2. Tạo project mới (vd: "chi-tieu-tracker")
3. Vào **APIs & Services** → **Enable APIs**
   - Bật: `Google Sheets API`
   - Bật: `Google Drive API`
4. Vào **Credentials** → **Create Credentials** → **Service Account**
   - Đặt tên tùy ý
   - Bỏ qua các bước về role/permissions
5. Click vào service account vừa tạo → **Keys** → **Add Key** → **JSON**
   - File JSON sẽ tự tải về

### 1.3. Chia sẻ Spreadsheet với Service Account
1. Mở file JSON vừa tải → copy email `client_email` (dạng `xxx@xxx.iam.gserviceaccount.com`)
2. Mở Google Spreadsheet → Share → Paste email đó vào → quyền **Editor**

---

## BƯỚC 2 — Tạo Telegram Bot (mỗi người làm 1 lần)

1. Tìm **@BotFather** trên Telegram
2. Nhắn `/newbot`
3. Đặt tên hiển thị (vd: "Chi Tiêu Của Hung")
4. Đặt username (vd: "chitieu_hung_bot") — phải kết thúc bằng `bot`
5. BotFather sẽ trả về **Token** dạng: `1234567890:ABCdef...`
6. **Lưu token này lại!**

---

## BƯỚC 3 — Deploy lên Render.com

### 3.1. Chuẩn bị
1. Tạo tài khoản https://github.com (nếu chưa có)
2. Upload toàn bộ thư mục project lên GitHub repo mới

### 3.2. Deploy
1. Vào https://render.com → Đăng ký/Đăng nhập
2. **New** → **Web Service** → Kết nối GitHub repo
3. Cấu hình:
   - **Build Command**: `pip install -r backend/requirements.txt`
   - **Start Command**: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
   - **Instance Type**: Free

### 3.3. Thêm Environment Variables
Vào tab **Environment** → Thêm 2 biến:

| Key | Value |
|-----|-------|
| `GOOGLE_SHEETS_ID` | ID spreadsheet từ Bước 1.1 |
| `GOOGLE_CREDS_JSON` | Toàn bộ nội dung file JSON (copy paste hết) |

4. Click **Deploy**
5. Chờ ~5 phút → app sẽ có URL dạng `https://chi-tieu-tracker.onrender.com`

---

## BƯỚC 4 — Đăng ký Webhook cho Bot

Sau khi app đã deploy, chạy script này trên máy tính:

```bash
pip install httpx
python setup_webhook.py
```

Nhập URL app và token của từng bot.

**Hoặc** dùng curl/Postman:
```bash
curl -X POST https://your-app.onrender.com/api/register-webhook \
  -H "Content-Type: application/json" \
  -d '{"bot_token": "TOKEN_CỦA_BẠN", "webhook_url": "https://your-app.onrender.com"}'
```

---

## BƯỚC 5 — Hướng dẫn cho từng người dùng

Mỗi người dùng làm theo thứ tự:

1. **Tìm bot Telegram** của mình (do người setup chia sẻ username)
2. Nhắn `/start`
3. Nhắn `/register TênCủaBạn` (vd: `/register Hung`)
4. Bắt đầu ghi chi tiêu!

---

## Cách ghi chi tiêu

| Nhắn vào bot | Nghĩa |
|-------------|-------|
| `50k ăn phở` | 50,000đ - ăn phở |
| `2tr mua điện thoại` | 2,000,000đ - mua điện thoại |
| `150000 xăng xe` | 150,000đ - xăng xe |
| `300 cafe sáng` | 300,000đ - cafe sáng |
| `1.5tr tiền điện` | 1,500,000đ - tiền điện |

**Lưu ý**: Số dưới 10,000 không có đơn vị → tự động nhân 1,000

## Các lệnh bot

| Lệnh | Chức năng |
|------|----------|
| `/start` | Bắt đầu / chào mừng |
| `/register Tên` | Đăng ký lần đầu |
| `/summary` | Xem tổng chi tháng này |
| `/budget 10000000` | Đặt ngân sách tháng (10tr) |
| `/help` | Xem hướng dẫn |

---

## Thông báo tự động

App tự động gửi tổng kết tháng vào **ngày 1 mỗi tháng, 8:00 sáng** cho tất cả người dùng.

---

## Xem Dashboard Web

Truy cập URL app trên trình duyệt hoặc điện thoại:
`https://your-app.onrender.com`

- Xem tổng chi tiêu theo tháng
- Xem chi tiết từng người
- Xem phân loại danh mục
- Chuyển qua lại các tháng

---

## Lưu ý quan trọng

⚠️ **Render Free Plan**: App sẽ "ngủ" sau 15 phút không dùng, lần sau mở sẽ chậm ~30 giây

💡 **Mỗi người cần bot riêng** — không dùng chung 1 bot được (vì cần phân biệt người ghi)

🔒 **Bảo mật**: Không chia sẻ Bot Token với ai khác, không commit file credentials lên GitHub

---

## Troubleshooting

**Bot không phản hồi?**
→ Kiểm tra webhook đã được đăng ký chưa:
`https://api.telegram.org/botTOKEN/getWebhookInfo`

**Lỗi Google Sheets?**
→ Kiểm tra đã share spreadsheet với email service account chưa

**App trên Render không start?**
→ Xem logs trong Render dashboard, thường do GOOGLE_CREDS_JSON bị sai format


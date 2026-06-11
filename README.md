# Telegram Bot Assistant

Telegram Bot Assistant là bot Telegram cá nhân hỗ trợ:

* Ghi chép thu nhập, chi tiêu hằng ngày
* Quản lý hũ chi tiêu
* Xem báo cáo tài chính, saving, export CSV
* Tra cứu thông tin đầu tư cơ bản: cổ phiếu, vàng, bạc
* Theo dõi watchlist, portfolio, price alert
* Xem tin startup, unicorn, funding
* Nhắc ghi chi tiêu, báo cáo tháng và startup digest tự động

Bot được viết bằng Python và có thể chạy trên Ubuntu Server.

## 1. Clone source code

```bash
git clone https://github.com/AndyZ1608/Telegram-bot-assistant.git
cd Telegram-bot-assistant
```

## 2. Cài Python và tạo môi trường ảo

Trên Ubuntu:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git
```

Tạo virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## 3. Cài thư viện

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

## 4. Tạo file cấu hình `.env`

Copy file mẫu:

```bash
cp .env.example .env
```

Mở file `.env`:

```bash
nano .env
```

Điền tối thiểu:

```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
DATABASE_URL=sqlite:///bot.db
TIMEZONE=Asia/Ho_Chi_Minh
ENABLE_SCHEDULER=true
DEFAULT_TIMEZONE=Asia/Ho_Chi_Minh
```

`TELEGRAM_BOT_TOKEN` lấy từ BotFather trên Telegram.

Không commit file `.env` lên GitHub.

## 5. Chạy bot

```bash
source .venv/bin/activate
python bot.py
```

Sau đó mở Telegram và test:

```text
/start
/help
```

## 6. Test nhanh các tính năng chính

```text
/income 30000000
/jar add an_uong 2000000
/expense an_uong 50000 ăn sáng
/report
/saving
/stock FPT
/gold
/silver
/startup
/unicorn
/settings
/export
```

Có thể nhập tiếng Việt tự nhiên:

```text
ăn sáng 50k
cafe 35k
đổ xăng 100k
giá vàng hôm nay
tin startup ai
```

## 7. Chạy bot bằng systemd trên Ubuntu

Nếu muốn bot tự chạy lại khi server reboot, tạo service:

```bash
sudo nano /etc/systemd/system/telegram-assistant-bot.service
```

Nội dung mẫu:

```ini
[Unit]
Description=Telegram Bot Assistant
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/Telegram-bot-assistant
EnvironmentFile=/opt/Telegram-bot-assistant/.env
ExecStart=/opt/Telegram-bot-assistant/.venv/bin/python /opt/Telegram-bot-assistant/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Lưu ý: sửa lại đường dẫn `/opt/Telegram-bot-assistant` theo đúng nơi bạn clone source code.

Reload và start service:

```bash
sudo systemctl daemon-reload
sudo systemctl start telegram-assistant-bot
sudo systemctl enable telegram-assistant-bot
```

Kiểm tra trạng thái:

```bash
sudo systemctl status telegram-assistant-bot
```

Xem log:

```bash
journalctl -u telegram-assistant-bot -f
```

Restart bot:

```bash
sudo systemctl restart telegram-assistant-bot
```

## 8. Backup database SQLite

Nếu dùng SQLite, backup file database:

```bash
mkdir -p backups
cp bot.db backups/bot_$(date +%Y%m%d_%H%M%S).db
```

## 9. Update code mới

```bash
cd Telegram-bot-assistant
git pull
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart telegram-assistant-bot
```

## Ghi chú

* Không public file `.env`
* Không public file database nếu có dữ liệu thật
* Nên chạy bot bằng `systemd` khi deploy lên server Ubuntu
* Giai đoạn đầu có thể dùng SQLite, chưa cần PostgreSQL hoặc Docker

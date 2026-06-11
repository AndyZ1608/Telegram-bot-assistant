# Go-live Guide: Telegram Assistant Bot

Minimal Ubuntu deployment using SQLite and systemd.

## 1. Server Requirements

- Ubuntu 22.04 or newer
- Python 3.11+ with `venv`
- Git
- SQLite tools optional but recommended for safe backup
- A Telegram bot token from BotFather

Install base packages:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git sqlite3
```

## 2. Create Service User

```bash
sudo useradd --system --home /opt/telegram-bot-assistant --shell /usr/sbin/nologin telegrambot
```

## 3. Clone Project

```bash
sudo git clone <YOUR_REPO_URL> /opt/telegram-bot-assistant
sudo chown -R telegrambot:telegrambot /opt/telegram-bot-assistant
cd /opt/telegram-bot-assistant
```

## 4. Install Dependencies

```bash
sudo -u telegrambot bash scripts/install.sh
```

## 5. Configure `.env`

Edit `.env`:

```bash
sudo -u telegrambot nano /opt/telegram-bot-assistant/.env
```

Minimum values:

```env
TELEGRAM_BOT_TOKEN=your_real_token
DATABASE_URL=sqlite:///bot.db
TIMEZONE=Asia/Ho_Chi_Minh
DEFAULT_TIMEZONE=Asia/Ho_Chi_Minh
ENABLE_SCHEDULER=true
MARKET_PROVIDER=mock
STARTUP_NEWS_PROVIDER=mock
```

Do not commit `.env`. Keep secrets only in `.env`.

## 6. Run Manual Smoke Test

```bash
sudo -u telegrambot bash scripts/run.sh
```

Stop with `Ctrl+C` after confirming the bot starts.

## 7. Enable systemd

```bash
sudo cp deploy/telegram-assistant-bot.service /etc/systemd/system/telegram-assistant-bot.service
sudo systemctl daemon-reload
sudo systemctl enable telegram-assistant-bot
sudo systemctl start telegram-assistant-bot
```

Check status:

```bash
sudo systemctl status telegram-assistant-bot
```

Restart:

```bash
sudo systemctl restart telegram-assistant-bot
```

Stop:

```bash
sudo systemctl stop telegram-assistant-bot
```

## 8. Logs

Follow logs:

```bash
journalctl -u telegram-assistant-bot -f
```

Recent logs:

```bash
journalctl -u telegram-assistant-bot -n 200 --no-pager
```

The bot logs lifecycle events, command errors, scheduler errors, and provider errors. It must not log Telegram tokens.

## 9. SQLite Backup

Default:

```bash
sudo -u telegrambot bash scripts/backup_db.sh
```

If your SQLite path differs:

```bash
sudo -u telegrambot DB_PATH=/opt/telegram-bot-assistant/bot.db bash scripts/backup_db.sh
```

Backups are written to:

```text
backups/bot_YYYYMMDD_HHMMSS.db
```

Each backup uses a new timestamped filename and does not overwrite older backups.

## 10. Telegram Go-live Checklist

Run these commands in Telegram:

```text
/start
/help
/income 30000000
/jar add an_uong 2000000
/expense an_uong 50000 ăn sáng
/report
/saving
/stock FPT
/gold
/startup
/unicorn
/settings
/reminder on
/export
```

Expected:

- Bot replies to every command.
- Finance data is isolated to your Telegram user.
- `/stock`, `/gold`, `/startup`, `/unicorn` clearly show mock/sample provider if real APIs are not configured.
- `/settings` shows scheduler configuration.
- `/export` sends a CSV after at least one expense exists.

## 11. Scheduler Checks

After enabling systemd:

- Confirm scheduler started in logs.
- Set reminder time a few minutes ahead:

```text
/reminder time 21:30
/reminder on
```

- Watch logs with `journalctl -u telegram-assistant-bot -f`.
- Confirm no duplicate reminder is sent in the same day.

## 12. Minimal Troubleshooting

Missing token:

```text
RuntimeError: Missing TELEGRAM_BOT_TOKEN
```

Fix `.env`.

Dependency error:

```bash
sudo -u telegrambot bash scripts/install.sh
```

Database path issue:

- Confirm `DATABASE_URL=sqlite:///bot.db`
- Confirm service `WorkingDirectory=/opt/telegram-bot-assistant`

Service does not start:

```bash
sudo systemctl status telegram-assistant-bot
journalctl -u telegram-assistant-bot -n 100 --no-pager
```

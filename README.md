# MyBot

A Telegram bot powered by Gemini AI.

## Prerequisites

- **Python 3.10 or newer** (recommended)
- Telegram Bot Token
- Gemini API Key

## Setup Instructions

1. **Clone the repository**
   ```powershell
   git clone <your-repo-url>
   cd MyBot
   ```

2. **Create a virtual environment (recommended)**
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```

3. **Install required packages**
   ```powershell
   pip install -r requirements.txt
   ```

4. **Configure environment variables**
   - Copy `BOT_TOKEN.env.example` thành `BOT_TOKEN.env` trong thư mục project.
   - Add your tokens:
     ```env
     TELE_BOT_TOKEN=your-telegram-bot-token
     GEMINI_API_KEY=your-gemini-api-key
     MONGO_URI=your-mongodb-uri
     MONGO_DB_NAME=Telegram_bot_database
     MONGO_COLLECTION=gold-price-collection
     HOSE_STOCK_COLLECTION=hose-stock-collection
     ```

5. **Run the bot**
   ```powershell
   python BOT.py
   ```

## Supported Commands

| Command | Description |
|---------|-------------|
| `/gold` | Giá vàng hiện tại (SJC, 999) từ nhiều nguồn |
| `/money [mã]` | Tỷ giá ngoại tệ, ví dụ `/money USD` |
| `/stock [mã]` | Thông tin thị trường chứng khoán HOSE |
| `/help` | Danh sách lệnh hỗ trợ |

## HOSE Stock Market Feature (`/stock`)

The `/stock` command provides real-time end-of-day data for the Ho Chi Minh
Stock Exchange (HOSE) via the **VNDirect public API**.

### Usage examples

```
/stock              # VN-Index overview
/stock VNINDEX      # explicit VN-Index
/stock VN30         # VN30 index
/stock VNM          # Price for Vinamilk (VNM)
/stock HPG          # Price for Hoa Phat Group (HPG)
```

### Sample output

```
THÔNG TIN THỊ TRƯỜNG CHỨNG KHOÁN HOSE
THỨ HAI NGÀY 10 THÁNG 03 NĂM 2025
09:15:00 AM

VNINDEX: 1.230,45 điểm (+5,23) (+0,43% ↑)
  Khối lượng: 234.567.890 CP
  Giá trị  : 8.765,43 tỷ
  Phiên    : 2025-03-10

Nguồn: VNDirect
```

### Scheduled alerts

When `MONGO_URI` is configured, **HOSEWatcher** runs automatically:

| Time (GMT+7) | Event |
|---|---|
| 09:00 | Daily market-open summary sent to all configured chats |
| 15:15 | Daily market-close summary sent to all configured chats |
| Every 30 min | Change alert when VN-Index moves ≥ 0.5 % vs last stored value |

### Architecture overview

```
BOT.py
 ├── CommandHandler('/stock')  →  message.handle_stock
 │                                  └── crawl_hose_stock.HOSEStockService.get_info()
 │                                        └── VNDirect API
 └── HOSEWatcher (scheduled)
       ├── job_info()  →  HOSEStockService.get_info()
       └── job()       →  HOSEStockService.get_changes()
                              └── MongoDB (change detection)
```

### Data source

All stock prices are sourced from the
[VNDirect public API](https://finfo-api.vndirect.com.vn/v4/stock_prices).
Data represents **end-of-day** prices for the most recent trading session.

## Troubleshooting

- If you get `ModuleNotFoundError`, ensure you activated your virtual environment and installed all packages.
- Check your `.env` file for correct token names and values.
- If `/stock` returns "Không lấy được dữ liệu", the VNDirect API may be temporarily unavailable or the ticker code may be invalid.

## License

MIT (or specify your license)

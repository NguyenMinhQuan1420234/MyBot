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
     ```

5. **Run the bot**
   ```powershell
   python BOT.py
   ```

## Troubleshooting

- If you get `ModuleNotFoundError`, ensure you activated your virtual environment and installed all packages.
- Check your `.env` file for correct token names and values.

## License

MIT (or specify your license)

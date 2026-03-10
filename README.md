# MyBot

A Telegram bot powered by AI (Gemini, OpenAI, xAI, Azure OpenAI, or Claude with Skills).

## Prerequisites

- **Python 3.10 or newer** (recommended)
- Telegram Bot Token
- API key for your chosen AI provider

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
   To use a different AI provider:
   ```powershell
   python BOT.py --provider claude   # Claude with Skills (tool use)
   python BOT.py --provider openai
   python BOT.py --provider xai
   python BOT.py --provider azure
   ```

## Claude Skills (Tool Use)

When running with `--provider claude`, the bot uses Anthropic's **tool use** feature to expose its
built-in capabilities as *skills* that Claude can invoke autonomously:

| Skill | Description |
|---|---|
| `get_gold_price` | Fetches live gold buy/sell prices from Vietnamese sources (Mi Hồng, Doji, Ngọc Thẩm) |
| `get_money_rate` | Fetches the buy/sell exchange rate for any ISO 4217 currency code against VND |

Claude will automatically call the appropriate skill when a user asks about gold prices or foreign
exchange rates, then compose a natural-language response from the results.

## Troubleshooting

- If you get `ModuleNotFoundError`, ensure you activated your virtual environment and installed all packages.
- Check your `.env` file for correct token names and values.

## License

MIT (or specify your license)

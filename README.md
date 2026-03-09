# MyBot

A Telegram bot powered by Gemini AI (and other providers including Claude with Skills support).

## Prerequisites

- **Python 3.10 or newer** (recommended)
- Telegram Bot Token
- Gemini API Key (default) or API key for another supported provider

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

## Supported AI Providers

| Provider | CLI Flag | Env Variable | Notes |
|----------|----------|--------------|-------|
| Gemini (default) | `--provider gemini` | `GEMINI_API_KEY` | Google Gemini AI |
| OpenAI | `--provider openai` | `OPENAI_API_KEY` | GPT models |
| xAI | `--provider xai` | `XAI_API_KEY` | Grok models |
| Azure OpenAI | `--provider azure` | `AZURE_API_KEY` | Azure-hosted OpenAI |
| **Claude** | `--provider claude` | `CLAUDE_API_KEY` | Anthropic Claude with Skills |

## Claude Skills

When using the `claude` provider, the bot leverages **Claude Skills** (Anthropic tool use) to enable Claude to autonomously call built-in capabilities:

| Skill | Description |
|-------|-------------|
| `get_gold_price` | Fetch live gold prices from Vietnamese sources (Mi Hồng, Doji, Ngọc Thẩm) |
| `get_money_rate` | Fetch fiat exchange rates (USD, EUR, JPY, …) vs VND |

Claude will automatically call these skills when needed to answer user questions, providing up-to-date financial data directly in its responses.

### Example usage with Claude

```powershell
python BOT.py --provider claude --api-key your-claude-api-key
```

Or set `CLAUDE_API_KEY` in your `.env` file and run:

```powershell
python BOT.py --provider claude
```

## Troubleshooting

- If you get `ModuleNotFoundError`, ensure you activated your virtual environment and installed all packages.
- Check your `.env` file for correct token names and values.

## License

MIT (or specify your license)

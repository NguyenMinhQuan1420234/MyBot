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
   pip install python-telegram-bot python-dotenv google-generativeai
   ```

4. **Configure environment variables**
   - Create a file named `BOT_TOKEN.env` in the project folder.
   - Add your tokens:
     ```env
     TELE_BOT_TOKEN=your-telegram-bot-token
     GEMINI_API_KEY=your-gemini-api-key
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

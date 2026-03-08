import os

try:
    from dotenv import load_dotenv
    load_dotenv("BOT_TOKEN.env")
    load_dotenv()
except Exception:
    pass

MONGO_URI = os.getenv("MONGO_URI", "")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "Telegram_bot_database")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "gold-price-collection")
HOSE_STOCK_COLLECTION = os.getenv("HOSE_STOCK_COLLECTION", "hose-stock-collection")


def get_mongo_uri() -> str:
    return MONGO_URI


def get_mongo_db_name() -> str:
    return MONGO_DB_NAME


def get_mongo_collection() -> str:
    return MONGO_COLLECTION

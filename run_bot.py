import subprocess
import sys
import logging
from config import MONGO_URI, MONGO_DB_NAME, MONGO_COLLECTION

# Fix Windows console encoding for Vietnamese characters
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def cleanup_database():
    """Check database status using GoldPriceService.check_database()."""
    try:
        if not MONGO_URI:
            print("\nKhông có cấu hình MongoDB URI (MONGO_URI)")
            print("Vui lòng cấu hình trong BOT_TOKEN.env/.env hoặc GitHub Actions secrets.\n")
            return
        
        from api_client import APIClient
        from crawl_gold_price import GoldPriceService
        
        api_client = APIClient()
        gold_service = GoldPriceService(api_client)
        result = gold_service.check_database()
        
        print()
        print(result['message'])
        print()
        
        return result
        
    except Exception as e:
        logging.exception(f"Lỗi khi kiểm tra database: {e}")


def show_all_provider_info():
    """Display all gold price information using GoldPriceService.get_info()."""
    try:
        from api_client import APIClient
        from crawl_gold_price import GoldPriceService
        
        api_client = APIClient()
        gold_service = GoldPriceService(api_client)
        result = gold_service.get_info()
        
        # Print the formatted message
        print()
        print(result['message'])
        print()
        
        # Return data for programmatic use
        return result
        
    except Exception as e:
        logging.exception(f"Lỗi khi hiển thị thông tin provider: {e}")
        return {'message': '', 'data': {}, 'has_any_change': False}


def check_price_changes():
    """Check gold price changes using GoldPriceService.get_changes()."""
    try:
        from api_client import APIClient
        from crawl_gold_price import GoldPriceService
        
        api_client = APIClient()
        gold_service = GoldPriceService(api_client)
        result = gold_service.get_changes()
        
        # Print the formatted message if there are changes
        print()
        if result['message']:
            print(result['message'])
        else:
            print("="*80)
            print("THAY ĐỔI GIÁ VÀNG")
            print("="*80)
            print("Không có thay đổi giá nào được phát hiện.")
            print("="*80)
        print()
        
        # Return data for programmatic use
        return result
        
    except Exception as e:
        logging.exception(f"Lỗi khi kiểm tra thay đổi giá: {e}")
        return {'message': None, 'data': {}, 'total_changes': 0, 'has_any_change': False}


if __name__ == "__main__":
    import os
    
    # Check if running in debug mode with arguments
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == "info":
            # Show all provider information
            show_all_provider_info()
        elif command == "changes":
            # Check price changes
            check_price_changes()
        elif command == "full":
            # Run both checks (reuses single service call)
            show_all_provider_info()
            check_price_changes()
        elif command == "db":
            # Check database
            cleanup_database()
        elif command == "all":
            # Run all diagnostics
            cleanup_database()
            show_all_provider_info()
            check_price_changes()
        else:
            print(f"Lệnh không xác định: {command}")
            print("\nCách sử dụng: python run_bot.py [lệnh]")
            print("  info     - Hiển thị tất cả thông tin nhà cung cấp")
            print("  changes  - Kiểm tra thay đổi giá cho tất cả nhà cung cấp")
            print("  db       - Kiểm tra cơ sở dữ liệu")
            print("  full     - Chạy cả info và changes")
            print("  all      - Chạy tất cả chẩn đoán (db + info + changes)")
            print("  (không tham số) - Chạy BOT.py bình thường")
    else:
        # Normal mode: run the bot
        os.chdir("/home/bibubanchi/mybot")
        subprocess.run([sys.executable, "BOT.py"])

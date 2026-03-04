import subprocess
import sys
import logging
import re
from typing import Dict, Any, List
from config import MONGO_URI, MONGO_DB_NAME, MONGO_COLLECTION

# Fix Windows console encoding for Vietnamese characters
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def format_vn_price(val: int) -> str:
    """Format price in Vietnamese currency format (dot separator)."""
    if val is None:
        return "Không có"
    try:
        return f"{int(val):,}".replace(',', '.')
    except Exception:
        return str(val)


def format_change_arrow(change: int) -> str:
    """Format change value with arrow direction."""
    if change is None or change == 0:
        return ""
    arrow = "↑" if change > 0 else "↓"
    change_str = f"{change:+,}".replace(',', '.')
    return f" ({change_str} {arrow})"


def display_provider_name(name: str) -> str:
    """Normalize provider display names in Vietnamese."""
    if not name:
        return "Không rõ"
    name_map = {
        "Ngoc Tham": "Ngọc Thẩm",
    }
    return name_map.get(name, name)


def _source_key(source: str) -> str:
    return re.sub(r"\s+", "", (source or "")).lower()


def _compute_change_vs_yesterday(source: str, code: str, buy_price: int, sell_price: int):
    """Return (buy_change, sell_change) vs latest record of yesterday for source/code."""
    if not MONGO_URI:
        return None, None

    try:
        from pymongo import MongoClient
        from datetime import datetime, timedelta

        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        coll = client[MONGO_DB_NAME][MONGO_COLLECTION]

        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_start = today_start - timedelta(days=1)

        last_yesterday = coll.find_one(
            {
                "source": _source_key(source),
                "code": code,
                "timestamp": {"$gte": yesterday_start, "$lt": today_start},
            },
            sort=[("timestamp", -1)],
        )

        if not last_yesterday:
            return None, None

        y_buy = last_yesterday.get("buy")
        y_sell = last_yesterday.get("sell")

        buy_change = None if buy_price is None or y_buy is None else (buy_price - y_buy)
        sell_change = None if sell_price is None or y_sell is None else (sell_price - y_sell)
        return buy_change, sell_change
    except Exception:
        logging.exception("Không tính được thay đổi so với hôm qua cho %s/%s", source, code)
        return None, None


def cleanup_database():
    """Check and cleanup database if needed."""
    try:
        from pymongo import MongoClient
        from datetime import datetime
        from collections import Counter
        
        if not MONGO_URI:
            print("Không có cấu hình MongoDB URI (MONGO_URI)")
            print("Vui lòng cấu hình trong BOT_TOKEN.env/.env hoặc GitHub Actions secrets.")
            return
        
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        db = client[MONGO_DB_NAME]
        coll = db[MONGO_COLLECTION]
        
        count = coll.count_documents({})
        print(f"\n{'='*80}")
        print(f"KIỂM TRA CƠ SỞ DỮ LIỆU")
        print(f"{'='*80}")
        print(f"Tổng số bản ghi: {count}")
        
        if count > 0:
            today = datetime.now().date()
            recent_for_stats = list(coll.find().sort('timestamp', -1).limit(500))
            today_docs = [
                doc for doc in recent_for_stats
                if hasattr(doc.get('timestamp'), 'date') and doc.get('timestamp').date() == today
            ]
            today_counter = Counter((doc.get('source', 'N/A'), doc.get('code', 'N/A')) for doc in today_docs)

            print(f"Bản ghi hôm nay: {len(today_docs)}")
            if today_counter:
                print("Theo nguồn/mã (hôm nay):")
                for (src, code), qty in sorted(today_counter.items()):
                    print(f"  - {src:10s} | {code:5s} | {qty} bản ghi")

            # Show latest records
            latest = list(coll.find().sort('timestamp', -1).limit(10))
            print(f"\n10 bản ghi gần nhất:")
            for doc in latest:
                ts = doc.get('timestamp', 'N/A')
                src = doc.get('source', 'N/A')
                code = doc.get('code', 'N/A')
                buy = doc.get('buy')
                sell = doc.get('sell')
                print(f"  {ts} | {src:10s} | {code:5s} | Mua: {format_vn_price(buy):15s} | Bán: {format_vn_price(sell):15s}")
        else:
            print("\nCơ sở dữ liệu trống - lần chạy đầu tiên sẽ tạo dữ liệu cơ bản")
        
        print(f"\n{'='*80}\n")
        
    except Exception as e:
        logging.exception(f"Lỗi khi kiểm tra database: {e}")


def show_all_provider_info(snapshot: Dict[str, Any] = None) -> Dict[str, Any]:
    """Hiển thị tất cả thông tin từ các nhà cung cấp giá vàng.
    
    Returns:
        Dict chứa snapshot với tất cả dữ liệu provider
    """
    try:
        from api_client import APIClient
        from crawl_gold_price import GoldPriceService
        from datetime import datetime
        import locale
        
        # Try to set Vietnamese locale for day names
        try:
            locale.setlocale(locale.LC_TIME, 'vi_VN.UTF-8')
        except:
            try:
                locale.setlocale(locale.LC_TIME, 'Vietnamese_Vietnam.1258')
            except:
                pass  # Use default if Vietnamese locale not available
        
        if snapshot is None:
            api_client = APIClient()
            gold_service = GoldPriceService(api_client)
            snapshot = gold_service.get_snapshot()
        
        # Get current time
        now = datetime.now()
        
        # Vietnamese day names mapping
        vn_days = {
            0: 'THỨ HAI',
            1: 'THỨ BA', 
            2: 'THỨ TƯ',
            3: 'THỨ NĂM',
            4: 'THỨ SÁU',
            5: 'THỨ BẢY',
            6: 'CHỦ NHẬT'
        }
        day_name = vn_days.get(now.weekday(), 'CHỦ NHẬT')
        
        # Format: THỨ X NGÀY DD THÁNG MM NĂM YYYY
        date_header = f"{day_name} NGÀY {now.day:02d} THÁNG {now.month:02d} NĂM {now.year}"
        time_header = now.strftime("%I:%M:%S %p")
        
        print("\n" + "="*80)
        print("THÔNG TIN GIÁ VÀNG")
        print(date_header)
        print(time_header)
        print("="*80)
        
        for src in snapshot.get('sources', []):
            provider_name = display_provider_name(src.get('name', 'Unknown'))
            source_name = src.get('name', 'Unknown')
            status = src.get('status')
            has_any_change = src.get('has_any_change', False)

            if status != 'ok':
                continue

            # Show provider name with change indicator
            change_marker = " [CÓ THAY ĐỔI]" if has_any_change else ""
            print(f"Giá vàng {provider_name}{change_marker}:")
            items = src.get('items', [])
            items_by_code = {item.get('code'): item for item in items}

            for code in ['SJC', '999']:
                item = items_by_code.get(code)
                if not item:
                    continue

                buy = item.get('buyPrice')
                sell = item.get('sellPrice')
                buy_change = item.get('buyChange')
                sell_change = item.get('sellChange')
                has_change = item.get('has_price_change', False)
                buy_ref_note = ""
                sell_ref_note = ""

                # Info-only fallback:
                # if provider has no intraday changes, compare with yesterday.
                if not has_any_change and not has_change:
                    y_buy_change, y_sell_change = _compute_change_vs_yesterday(source_name, code, buy, sell)
                    if y_buy_change not in (None, 0):
                        buy_change = y_buy_change
                        buy_ref_note = " [so với hôm qua]"
                    if y_sell_change not in (None, 0):
                        sell_change = y_sell_change
                        sell_ref_note = " [so với hôm qua]"

                # Show code with change indicator
                code_marker = " ●" if has_change else ""
                print(f"- {code}{code_marker}:")
                
                # Display in clearer MUA | BÁN format
                buy_str = format_vn_price(buy) if buy is not None else "Không có"
                sell_str = format_vn_price(sell) if sell is not None else "Không có"
                buy_change_str = format_change_arrow(buy_change)
                sell_change_str = format_change_arrow(sell_change)

                print(f"  MUA VÀO: {buy_str} VNĐ{buy_change_str}{buy_ref_note}")
                print(f"  BÁN RA : {sell_str} VNĐ{sell_change_str}{sell_ref_note}")
                print()
        
        print("="*80)
        print()
        
        return snapshot
        
    except Exception as e:
        logging.exception(f"Lỗi khi hiển thị thông tin provider: {e}")
        return {}


def check_price_changes(snapshot: Dict[str, Any] = None) -> Dict[str, List[Dict[str, Any]]]:
    """Kiểm tra thay đổi giá trên tất cả các nhà cung cấp.
    
    Returns:
        Dict ánh xạ tên nhà cung cấp tới danh sách các mục có thay đổi
    """
    try:
        from api_client import APIClient
        from crawl_gold_price import GoldPriceService
        from datetime import datetime
        import locale
        
        # Try to set Vietnamese locale for day names
        try:
            locale.setlocale(locale.LC_TIME, 'vi_VN.UTF-8')
        except:
            try:
                locale.setlocale(locale.LC_TIME, 'Vietnamese_Vietnam.1258')
            except:
                pass  # Use default if Vietnamese locale not available
        
        if snapshot is None:
            api_client = APIClient()
            gold_service = GoldPriceService(api_client)
            snapshot = gold_service.get_snapshot()
        
        # Get current time
        now = datetime.now()
        
        # Vietnamese day names mapping
        vn_days = {
            0: 'THỨ HAI',
            1: 'THỨ BA', 
            2: 'THỨ TƯ',
            3: 'THỨ NĂM',
            4: 'THỨ SÁU',
            5: 'THỨ BẢY',
            6: 'CHỦ NHẬT'
        }
        day_name = vn_days.get(now.weekday(), 'CHỦ NHẬT')
        
        # Format: THỨ X NGÀY DD THÁNG MM NĂM YYYY
        date_header = f"{day_name} NGÀY {now.day:02d} THÁNG {now.month:02d} NĂM {now.year}"
        time_header = now.strftime("%I:%M:%S %p")
        
        print("\n" + "="*80)
        print("THAY ĐỔI GIÁ VÀNG")
        print(date_header)
        print(time_header)
        print("(Chỉ hiển thị nhà cung cấp có thay đổi)")
        print("="*80)
        
        changes_by_provider = {}
        total_changes = 0
        has_any_change = False
        
        # Analyze each provider's normalized items
        for src in snapshot.get('sources', []):
            name = src.get('name', 'Không rõ')
            status = src.get('status')
            has_change = src.get('has_any_change', False)
            
            # Only process providers with changes and OK status
            if status != 'ok' or not has_change:
                changes_by_provider[name] = []
                continue
            
            items = src.get('items', [])
            if not items:
                changes_by_provider[name] = []
                continue
            
            # Filter items with price changes
            changed_items = [item for item in items if item.get('has_price_change', False)]
            changes_by_provider[name] = changed_items
            total_changes += len(changed_items)
            
            if changed_items:
                has_any_change = True
                provider_name = display_provider_name(name)
                print(f"Giá vàng {provider_name} [CÓ THAY ĐỔI]:")
                
                # Group items by code for consistent ordering
                items_by_code = {item.get('code'): item for item in changed_items}
                
                for code in ['SJC', '999']:
                    item = items_by_code.get(code)
                    if not item:
                        continue
                    
                    buy = item.get('buyPrice')
                    sell = item.get('sellPrice')
                    buy_change = item.get('buyChange')
                    sell_change = item.get('sellChange')
                    
                    print(f"- {code} ●:")
                    
                    # Display in MUA VÀO | BÁN RA format
                    buy_str = format_vn_price(buy) if buy is not None else "Không có"
                    sell_str = format_vn_price(sell) if sell is not None else "Không có"
                    buy_change_str = format_change_arrow(buy_change)
                    sell_change_str = format_change_arrow(sell_change)
                    
                    print(f"  MUA VÀO: {buy_str} VNĐ{buy_change_str}")
                    print(f"  BÁN RA : {sell_str} VNĐ{sell_change_str}")
                    print()
        
        if not has_any_change:
            print("Không có thay đổi giá nào được phát hiện.")
            print()
        
        print("="*80)
        print(f"Tổng số mục thay đổi: {total_changes}")
        print("="*80)
        print()
        
        return {
            'changes_by_provider': changes_by_provider,
            'total_changes': total_changes,
            'has_any_change': has_any_change
        }
        
    except Exception as e:
        logging.exception(f"Lỗi khi kiểm tra thay đổi giá: {e}")
        return {'changes_by_provider': {}, 'total_changes': 0, 'has_any_change': False}


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
            # Run both checks
            from api_client import APIClient
            from crawl_gold_price import GoldPriceService

            api_client = APIClient()
            gold_service = GoldPriceService(api_client)
            shared_snapshot = gold_service.get_snapshot()

            show_all_provider_info(shared_snapshot)
            check_price_changes(shared_snapshot)
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

import subprocess
import sys
import logging
from typing import Dict, Any, List

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


def cleanup_database():
    """Check and cleanup database if needed."""
    try:
        from pymongo import MongoClient
        from watcher import DEFAULT_MONGO_URI
        
        if not DEFAULT_MONGO_URI:
            print("Không có cấu hình MongoDB URI")
            return
        
        client = MongoClient(DEFAULT_MONGO_URI, serverSelectionTimeoutMS=5000)
        db = client['bot']
        coll = db['prices']
        
        count = coll.count_documents({})
        print(f"\n{'='*80}")
        print(f"KIỂM TRA CƠ SỞ DỮ LIỆU")
        print(f"{'='*80}")
        print(f"Tổng số bản ghi: {count}")
        
        if count > 0:
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


def show_all_provider_info() -> Dict[str, Any]:
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
            status = src.get('status')

            if status != 'ok':
                continue

            print(f"Giá vàng {provider_name}:")
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

                print(f"- {code}:")
                if sell is not None:
                    sell_str = format_vn_price(sell)
                    sell_change_str = format_change_arrow(sell_change)
                    print(f"  • Giá bán: {sell_str} VNĐ{sell_change_str}")
                if buy is not None:
                    buy_str = format_vn_price(buy)
                    buy_change_str = format_change_arrow(buy_change)
                    print(f"  • Giá mua: {buy_str} VNĐ{buy_change_str}")
                print()
        
        print("="*80)
        print()
        
        return snapshot
        
    except Exception as e:
        logging.exception(f"Lỗi khi hiển thị thông tin provider: {e}")
        return {}


def check_price_changes() -> Dict[str, List[Dict[str, Any]]]:
    """Kiểm tra thay đổi giá trên tất cả các nhà cung cấp.
    
    Returns:
        Dict ánh xạ tên nhà cung cấp tới danh sách các mục có thay đổi
    """
    try:
        from api_client import APIClient
        from crawl_gold_price import GoldPriceService
        
        api_client = APIClient()
        gold_service = GoldPriceService(api_client)
        snapshot = gold_service.get_snapshot()
        
        print("\n" + "="*80)
        print("PHÁT HIỆN THAY ĐỔI GIÁ CHO TẤT CẢ CÁC NHÀ CUNG CẤP")
        print("="*80)
        print(f"Thời gian kiểm tra: {snapshot.get('as_of')}\n")
        
        changes_by_provider = {}
        total_changes = 0
        has_any_change = False
        
        # Analyze each provider's normalized items
        for src in snapshot.get('sources', []):
            name = src.get('name', 'Không rõ')
            status = src.get('status')
            
            print(f"\n{'─'*80}")
            print(f"Nhà cung cấp: {name}")
            print(f"Trạng thái: {status.upper()}")
            
            if status != 'ok':
                print(f"Lỗi: {src.get('error', 'Lỗi không xác định')}")
                changes_by_provider[name] = []
                continue
            
            items = src.get('items', [])
            if not items:
                print("Không có mục để kiểm tra")
                changes_by_provider[name] = []
                continue
            
            # Filter items with price changes
            changed_items = [item for item in items if item.get('has_price_change', False)]
            changes_by_provider[name] = changed_items
            total_changes += len(changed_items)
            
            if changed_items:
                has_any_change = True
                print(f"Các mục có thay đổi giá: {len(changed_items)}")
                for item in changed_items:
                    code = item.get('code', 'N/A')
                    buy = item.get('buyPrice')
                    sell = item.get('sellPrice')
                    buy_change = item.get('buyChange')
                    sell_change = item.get('sellChange')
                    
                    print(f"\n  → {code}")
                    if buy is not None:
                        buy_str = format_vn_price(buy)
                        print(f"    Mua: {buy_str} VNĐ")
                    if buy_change is not None:
                        buy_change_str = f"{buy_change:+,}".replace(',', '.')
                        print(f"    Thay đổi mua: {buy_change_str}")
                    if sell is not None:
                        sell_str = format_vn_price(sell)
                        print(f"    Bán: {sell_str} VNĐ")
                    if sell_change is not None:
                        sell_change_str = f"{sell_change:+,}".replace(',', '.')
                        print(f"    Thay đổi bán: {sell_change_str}")
            else:
                print("Không phát hiện thay đổi giá")
        
        print(f"\n{'─'*80}")
        print(f"\nTổng số thay đổi giá: {total_changes}")
        print(f"Có thay đổi: {'Có' if has_any_change else 'Không'}")
        print(f"{'='*80}\n")
        
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

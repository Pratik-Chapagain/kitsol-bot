import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import uuid
from datetime import datetime
import time
from config import SERVICE_ACCOUNT_FILE, PRODUCTS_SHEET_ID, ORDERS_SHEET_ID

class SheetManager:
    def __init__(self):
        self.scopes = ['https://www.googleapis.com/auth/spreadsheets']
        self.creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=self.scopes)
        self.client = gspread.authorize(self.creds)
        
        # Cache settings to avoid hitting Google API limits
        self._products_cache = None
        self._last_sync = 0
        self.CACHE_DURATION = 300  # Sync with sheet every 5 minutes

    def _get_sheet(self, sheet_id):
        """Helper to open a sheet and handle potential auth timeouts"""
        try:
            return self.client.open_by_key(sheet_id).sheet1
        except Exception:
            # Re-authorize if the connection timed out
            self.client = gspread.authorize(self.creds)
            return self.client.open_by_key(sheet_id).sheet1

    def get_products(self, force_refresh=False):
        """Get all products with smart caching"""
        current_time = time.time()
        
        if force_refresh or self._products_cache is None or (current_time - self._last_sync > self.CACHE_DURATION):
            try:
                sheet = self._get_sheet(PRODUCTS_SHEET_ID)
                data = sheet.get_all_records()
                self._products_cache = pd.DataFrame(data)
                self._last_sync = current_time
                print("🔄 Products synced from Google Sheets")
            except Exception as e:
                print(f"❌ Error syncing products: {e}")
                if self._products_cache is None: return pd.DataFrame()
        
        return self._products_cache

    def search_products(self, query):
        """Search products efficiently in the cached DataFrame"""
        df = self.get_products()
        if df.empty: return df
        
        mask = (
            df['product_name'].str.contains(query, case=False, na=False) |
            df['category'].str.contains(query, case=False, na=False)
        )
        return df[mask]

    def save_order(self, customer_name, phone, address, product, size, quantity):
        """Save order with a clean structure and unique ID"""
        try:
            sheet = self._get_sheet(ORDERS_SHEET_ID)
            
            # Generate a more readable Order ID for Nepali customers
            # Example: KITSOL-25MAR-A1B2
            date_str = datetime.now().strftime('%d%b').upper()
            short_id = uuid.uuid4().hex[:4].upper()
            order_id = f"KITSOL-{date_str}-{short_id}"
            
            order_row = [
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), # Timestamp
                order_id,                                     # Order ID
                customer_name,                                # Name
                f"'{phone}",                                  # Phone (force string in Sheets)
                address,                                      # Address
                product,                                      # Product
                size,                                         # Size
                quantity,                                     # Quantity
                "Pending"                                     # Status
            ]
            
            sheet.append_row(order_row, value_input_option='USER_ENTERED')
            return order_id
        except Exception as e:
            print(f"❌ Error saving order: {e}")
            raise e

    def get_order_status(self, order_id):
        """Check status without downloading the whole sheet if possible"""
        try:
            sheet = self._get_sheet(ORDERS_SHEET_ID)
            # Find the order ID in the 'order_id' column
            cell = sheet.find(order_id)
            if cell:
                # Assuming 'Status' is the last column (9th column)
                row_values = sheet.row_values(cell.row)
                # Return the status value (adjust index based on your sheet headers)
                return row_values[-1] 
            return "Order ID not found"
        except Exception:
            return "Unable to retrieve status at the moment."
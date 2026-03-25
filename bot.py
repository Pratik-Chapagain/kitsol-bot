from flask import Flask, request, jsonify
import google.generativeai as genai
from sheet_manager import SheetManager
from config import GEMINI_API_KEY, SHOP_NAME, SHOP_PHONE, SHOP_ADDRESS, SHOP_POLICY
import os
import logging
from datetime import datetime

# Setup logging for production
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Setup Gemini - Using stable model
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# Initialize sheet manager
sheets = SheetManager()

# Store active orders (Session Memory)
active_orders = {}

def detect_intent(message):
    """Detect customer intent with strict output constraints"""
    prompt = f"""
    Classify this customer message for a clothing store:
    Message: "{message}"
    
    Categories: PRICE, AVAILABILITY, CATALOG, ORDER, STATUS, POLICY, GREETING, OTHER
    Reply with ONLY the category name. No extra words or punctuation.
    """
    try:
        response = model.generate_content(prompt, generation_config={"temperature": 0.1})
        intent = response.text.strip().upper()
        logger.info(f"Intent detected: {intent} for message: {message}")
        return intent
    except Exception as e:
        logger.error(f"Intent Detection Error: {e}")
        return "OTHER"

def handle_price(message):
    """Handle price inquiry using live data from Google Sheets"""
    try:
        products_df = sheets.get_products()
        if products_df.empty:
            return f"⚠️ Product catalog currently unavailable. Please call us at {SHOP_PHONE}."
        
        product_context = products_df.to_string()
        prompt = f"""
        Customer asked: "{message}"
        Available Inventory: {product_context}
        
        Instructions:
        - Respond in Romanized Nepali or English
        - If item found, give price and size options
        - If not found, suggest 2-3 similar items
        - Keep response under 100 words
        - Be friendly and helpful
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        logger.error(f"Price handler error: {e}")
        return f"🔍 Maile product khojna sakina. Please call {SHOP_PHONE} for price info."

def handle_availability(message):
    """Check if items/sizes are in stock"""
    try:
        products_df = sheets.get_products()
        if products_df.empty:
            return f"⚠️ Stock info temporarily unavailable. Call {SHOP_PHONE} for updates."
        
        product_context = products_df.to_string()
        prompt = f"""
        Customer asked: "{message}"
        Inventory: {product_context}
        
        Instructions:
        - Check if item exists and available
        - If size mentioned, check if that size is available
        - Tell if in stock or out of stock
        - Suggest alternatives if not available
        - Be polite and helpful in Nepali/English
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        logger.error(f"Availability handler error: {e}")
        return f"📦 Stock check failed. Please call {SHOP_PHONE} for availability."

def handle_catalog():
    """Format the catalog for the user"""
    try:
        products_df = sheets.get_products()
        if products_df.empty:
            return "⚠️ Catalog currently unavailable. Please check back soon or call us."
        
        product_context = products_df.to_string()
        prompt = f"""
        Inventory List: {product_context}
        
        Instructions:
        - Create a beautiful, emoji-rich product catalog
        - Group items by category (Hoodies, T-shirts, Jackets, etc.)
        - Include price ranges and available sizes
        - Keep it concise (max 10 items, ask to call for full catalog)
        - Speak in friendly Romanized Nepali/English mix
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        logger.error(f"Catalog handler error: {e}")
        return f"📚 Catalog load failed. Please visit our store or call {SHOP_PHONE}."

def handle_order(message, phone):
    """State Machine: Guides user through order process"""
    
    # Global Cancel Command
    if message.lower() in ['cancel', 'exit', 'stop', 'quit']:
        if phone in active_orders:
            del active_orders[phone]
            logger.info(f"Order cancelled for phone: {phone}")
        return "❌ Order cancelled. Type 'order' anytime to start a new one."

    # Initialize order session
    if phone not in active_orders:
        active_orders[phone] = {"step": "name", "start_time": datetime.now()}
        return "🎯 Let's start! Tapai ko full naam k ho? (What is your full name?)\n\n*Type 'cancel' to stop*"
    
    order = active_orders[phone]
    
    # Check session timeout (30 minutes)
    if (datetime.now() - order["start_time"]).seconds > 1800:
        del active_orders[phone]
        return "⏰ Session expired. Type 'order' to start fresh."
    
    try:
        if order["step"] == "name":
            if len(message) < 2:
                return "Please enter a valid name (at least 2 characters)."
            order["name"] = message.title()
            order["step"] = "address"
            return f"✅ Thanks {order['name']}! 📍 Delivery address k ho? (Where should we deliver?)"
        
        elif order["step"] == "address":
            if len(message) < 5:
                return "Please enter a complete address for delivery."
            order["address"] = message
            order["step"] = "product"
            return "👕 Kun product chahiyeko? (Which product? Example: Black Hoodie, Nike T-shirt)"
        
        elif order["step"] == "product":
            order["product"] = message
            order["step"] = "size"
            return "📏 Size k ho? Options: S, M, L, XL, XXL\n*(Type size)*"
        
        elif order["step"] == "size":
            valid_sizes = ['S', 'M', 'L', 'XL', 'XXL', 'XS', 'XXL']
            size_upper = message.upper()
            if size_upper not in valid_sizes:
                return f"Please select valid size: {', '.join(valid_sizes)}"
            order["size"] = size_upper
            order["step"] = "quantity"
            return "🔢 Kati ota chahiyo? (How many pieces? 1-10)"
        
        elif order["step"] == "quantity":
            try:
                quantity = int(message)
                if quantity < 1 or quantity > 10:
                    return "Please enter quantity between 1 and 10."
                order["quantity"] = str(quantity)
            except ValueError:
                return "Please enter a valid number (1-10)."
            
            # Save to Google Sheets
            order_id = sheets.save_order(
                order["name"],
                phone,
                order["address"],
                order["product"],
                order["size"],
                order["quantity"]
            )
            
            # Clear session
            del active_orders[phone]
            logger.info(f"Order placed: {order_id} for {order['name']}")
            
            return f"""✅ **ORDER CONFIRMED!** ✅

━━━━━━━━━━━━━━━━━━━━
📦 **Product:** {order['product']}
📏 **Size:** {order['size']}
🔢 **Quantity:** {order['quantity']}
📍 **Delivery:** {order['address']}
🆔 **Order ID:** {order_id}
━━━━━━━━━━━━━━━━━━━━

📞 **Contact:** {SHOP_PHONE}
📋 **Policy:** {SHOP_POLICY}

Thank you for shopping at {SHOP_NAME}! 🎉
We'll contact you within 24 hours."""

    except Exception as e:
        logger.error(f"Order handler error: {e}")
        del active_orders[phone]
        return f"⚠️ Order processing error. Please call {SHOP_PHONE} to place your order."

@app.route('/webhook', methods=['POST'])
def webhook():
    """Main routing endpoint for WhatsApp"""
    try:
        data = request.json
        if not data:
            return jsonify({"reply": "No payload received"}), 400

        raw_msg = data.get('message', '').strip()
        phone = data.get('phone', '')

        if not raw_msg or not phone:
            return jsonify({"reply": "Invalid request"}), 400

        logger.info(f"Webhook received: {raw_msg} from {phone}")

        # Check if user is in an active order flow
        if phone in active_orders:
            reply = handle_order(raw_msg, phone)
            return jsonify({"reply": reply})

        # Detect intent for new conversations
        intent = detect_intent(raw_msg.lower())
        
        # Route based on intent
        intent_handlers = {
            "ORDER": lambda: handle_order(raw_msg, phone),
            "PRICE": lambda: handle_price(raw_msg),
            "AVAILABILITY": lambda: handle_availability(raw_msg),
            "CATALOG": lambda: handle_catalog(),
            "POLICY": lambda: f"📋 **{SHOP_NAME} Policy**\n\n{SHOP_POLICY}\n📍 Exchange: {SHOP_ADDRESS}\n📞 Contact: {SHOP_PHONE}",
            "STATUS": lambda: f"🔍 To check order status, please provide your Order ID or call {SHOP_PHONE}.",
            "GREETING": lambda: f"👋 Namaste! Welcome to **{SHOP_NAME}**! ✨\n\nWhat would you like?\n• Type 'catalog' to see products\n• Type 'price [item]' to check price\n• Type 'order' to buy\n• Type 'policy' for exchange info\n\nHow can I help you today? 🛍️",
        }
        
        reply = intent_handlers.get(intent, lambda: f"🤔 Maile bujhina. Try: 'catalog', 'price hoodie', 'order', or 'policy'")()
        
        return jsonify({"reply": reply})
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"reply": f"⚠️ Technical error. Please call {SHOP_PHONE} for assistance."}), 500

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint for monitoring"""
    return jsonify({
        "status": "healthy",
        "bot": "Kitsol Bot",
        "timestamp": datetime.now().isoformat(),
        "active_sessions": len(active_orders)
    })

@app.route('/', methods=['GET'])
def home():
    """Home endpoint for verification"""
    return jsonify({
        "bot": "Kitsol Bot",
        "version": "2.0",
        "status": "active",
        "endpoints": {
            "webhook": "POST /webhook",
            "health": "GET /health"
        },
        "shop": SHOP_NAME,
        "contact": SHOP_PHONE
    })

# For local development
if __name__ == '__main__':
    app.run(debug=True, port=5000)

# For Vercel serverless deployment
app = app
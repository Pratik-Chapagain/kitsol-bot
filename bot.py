from flask import Flask, request, jsonify
import google.generativeai as genai
from sheet_manager import SheetManager
from config import GEMINI_API_KEY, SHOP_NAME, SHOP_PHONE, SHOP_ADDRESS, SHOP_POLICY

app = Flask(__name__)

# Setup Gemini - Using the latest stable 2.5 series for 2026
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

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
        # Low temperature (0.1) keeps the model focused on classification
        response = model.generate_content(prompt, generation_config={"temperature": 0.1})
        return response.text.strip().upper()
    except Exception as e:
        print(f"Intent Detection Error: {e}")
        return "OTHER"

def handle_price(message):
    """Handle price inquiry using live data from Google Sheets"""
    product_context = sheets.get_products().to_string()
    prompt = f"""
    Customer asked: "{message}"
    Available Inventory: {product_context}
    
    Instruction: Respond in Romanized Nepali or English. 
    If you find the item, give the price. If not, suggest something similar.
    Keep it short and friendly.
    """
    response = model.generate_content(prompt)
    return response.text

def handle_availability(message):
    """Check if items/sizes are in stock"""
    product_context = sheets.get_products().to_string()
    prompt = f"""
    Customer asked: "{message}"
    Inventory: {product_context}
    
    Instruction: Check if the item/size exists. Be polite in Nepali/English.
    """
    response = model.generate_content(prompt)
    return response.text

def handle_catalog():
    """Format the catalog for the user"""
    product_context = sheets.get_products().to_string()
    prompt = f"""
    Inventory List: {product_context}
    
    Instruction: Create a beautiful, emoji-rich product catalog. 
    Group items by category (e.g., Hoodies, T-shirts). 
    Include price ranges. Speak in a friendly Romanized Nepali/English mix.
    """
    response = model.generate_content(prompt)
    return response.text

def handle_order(message, phone):
    """State Machine: Guides the user through the 6-step order process"""
    
    # Global Cancel Command
    if message.lower() in ['cancel', 'exit', 'stop', 'quit']:
        if phone in active_orders:
            del active_orders[phone]
        return "❌ Order cancelled. Tapai le feri 'order' bhannu bhayo bhane start hunchha."

    # Initializing the order session
    if phone not in active_orders:
        active_orders[phone] = {"step": "name"}
        return "🎯 Suru garam! Tapai ko full naam k ho? (What is your full name?)\n\n*(Type 'cancel' to stop)*"
    
    order = active_orders[phone]
    
    # Step-by-Step Logic
    if order["step"] == "name":
        order["name"] = message
        order["step"] = "address"
        return f"Dhanyabaad {message}! 📍 Delivery address k ho? (Where should we deliver?)"
    
    elif order["step"] == "address":
        order["address"] = message
        order["step"] = "product"
        return "👕 Kun product chahiyeko? (Which product? Example: Black Hoodie)"
    
    elif order["step"] == "product":
        order["product"] = message
        order["step"] = "size"
        return "📏 Size k ho? (S, M, L, XL, XXL)"
    
    elif order["step"] == "size":
        order["size"] = message.upper()
        order["step"] = "quantity"
        return "🔢 Kati ota chahiyo? (How many pieces?)"
    
    elif order["step"] == "quantity":
        order["quantity"] = message
        
        # Save to Google Sheets
        try:
            order_id = sheets.save_order(
                order["name"],
                phone, 
                order["address"],
                order["product"],
                order["size"],
                order["quantity"]
            )
            
            # Clear the session memory
            del active_orders[phone]
            
            return f"""✅ **Order Confirmed!** ✅

📦 Item: {order['product']}
📏 Size: {order['size']}
🔢 Qty: {order['quantity']}
📍 Delivery: {order['address']}

🆔 Order ID: {order_id}
📞 Contact: {SHOP_PHONE}

Thank you for shopping at {SHOP_NAME}! 🎉"""
        except Exception as e:
            return f"Error: Order save garna sakiyena. Please call {SHOP_PHONE}."

    return "Maile bujhina. Please answer the question or type 'cancel'."

@app.route('/webhook', methods=['POST'])
def webhook():
    """Core Routing Logic"""
    data = request.json
    if not data:
        return jsonify({"reply": "No payload received"}), 400

    raw_msg = data.get('message', '').strip()
    phone = data.get('phone', '')

    # 1. Check if user is ALREADY in an order flow (Saves current state)
    if phone in active_orders:
        reply = handle_order(raw_msg, phone)
        return jsonify({"reply": reply})

    # 2. If not, detect what they want (New Intent)
    intent = detect_intent(raw_msg.lower())
    
    if intent == "ORDER":
        reply = handle_order(raw_msg, phone)
    elif intent == "PRICE":
        reply = handle_price(raw_msg)
    elif intent == "AVAILABILITY":
        reply = handle_availability(raw_msg)
    elif intent == "CATALOG":
        reply = handle_catalog()
    elif intent == "POLICY":
        reply = f"📋 **{SHOP_NAME} Policy**\n\n{SHOP_POLICY}\n📍 Return Address: {SHOP_ADDRESS}"
    elif intent == "STATUS":
        reply = f"Order status check garna ko lagi Order ID bhannus ya {SHOP_PHONE} ma call garnus."
    elif intent == "GREETING":
        reply = f"👋 Namaste! Welcome to {SHOP_NAME}! \n\n'Catalog' hernus, 'Price' sodnus, ya 'Order' garnus."
    else:
        reply = "🤔 Maile bujhina. Try: 'catalog heram', 'hoodie ko price k ho?', or 'order'."

    return jsonify({"reply": reply})

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "running", "bot": "Kancha-AI-v2"})



if __name__ == '__main__':
    # Threaded mode allows multiple users to chat at once
    app.run(debug=True, port=5000,)

app = app
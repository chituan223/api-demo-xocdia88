from flask import Flask, jsonify
import threading
import websocket
import json
import time

# ================= Cấu hình WebSocket =================
WS_URL = "wss://taixiumd5.system32-cloudfare-356783752985678522.monster/signalr/reconnect?transport=webSockets&connectionToken=SgIYXqnbkJRw6FvkcaXYVrAcj9Rkcx758qlxIanF3odMFBbrqY%2BJJ%2FVvZUnOX0Z2pNFJwckC2pCxXefKhAclClEefIExyEGKc9Z6zfoZsoa9oUAzcs1LNw2G3jxr7w9j&connectionData=%5B%7B%22name%22%3A%22md5luckydiceHub%22%7D%5D&tid=6&access_token=05%2F7JlwSPGzg4ARi0d7%2FLOcNQQ%2BecAvgB3UwDAmuWFJiZj%2Blw1TcJ0PZt5VeUAHKLVCmODRrV5CHPNbit3mc868w8zYBuyQ5Xlu1AZVsEElr9od2qJ8S9N2GLAdQnd0VL8fj8IAGPMsP45pdIIXZysKmRi40b%2FOVLAp4yOpkaXP3icyn2%2Fodm397vVKSY9AlMCcH15AghVm3lx5JM%2BoUuP%2Fkjgh5xWXtdTQkd9W3%2BQBY25AdX3CvOZ2I17r67METGpFv8cP7xmAoySWEnokU2IcOKu3mzvRWXsG7N5sHFkv%2FIKw%2F1IPCNY2oi8RygWpHwIFWcHGdeoTeM6kskfrqNSmhapPBCREit0So1HOC6jOiz5IyKVNadwp8EfsxKzBOKE0z0zdavvY6wXrSZhEJeIqKqVAt3SEuoG82a%2BjwxNo%3D.5a1d88795043d5c4ef6538c9edfb5ff93e65b852d89f71344bdd5ec80eb63e24"
PING_INTERVAL = 15

# ================= Biến lưu kết quả =================
latest_result = {"SessionID": None, "Dice": {"Dice1": -1, "Dice2": -1, "Dice3": -1}}
lock = threading.Lock()  # tránh race condition

# ================= Hàm ping =================
def send_ping(ws):
    while True:
        try:
            ping_msg = json.dumps({"M": "PingPong", "H": "md5luckydiceHub", "I": 0})
            ws.send(ping_msg)
            time.sleep(PING_INTERVAL)
        except:
            break

# ================= Xử lý message =================
def on_message(ws, message):
    global latest_result
    try:
        data = json.loads(message)
        if isinstance(data, dict) and "M" in data:
            for m_item in data["M"]:
                if "M" in m_item and m_item["M"] == "Md5sessionInfo":
                    session_info = m_item["A"][0]
                    session_id = session_info.get("SessionID")
                    dice = session_info.get("Result", {})
                    if dice.get("Dice1", -1) != -1:
                        with lock:
                            latest_result["SessionID"] = session_id
                            latest_result["Dice"] = dice
    except Exception as e:
        print("Lỗi xử lý message:", e)

def on_error(ws, error):
    print("WebSocket lỗi:", error)

def on_close(ws, close_status_code, close_msg):
    print("WebSocket đóng, reconnect sau 5s...")
    time.sleep(5)
    start_ws_thread()

def on_open(ws):
    threading.Thread(target=send_ping, args=(ws,), daemon=True).start()

# ================= Khởi tạo WebSocket trong thread =================
def start_ws_thread():
    ws = websocket.WebSocketApp(
        WS_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )
    ws.run_forever(ping_interval=10, ping_timeout=5)

# ================= Flask API =================
app = Flask(__name__)

@app.route("/api/taixiumd5")
def get_latest():
    with lock:
        return jsonify(latest_result)

# ================= Main =================
if __name__ == "__main__":
    # Chạy WebSocket trong background thread
    threading.Thread(target=start_ws_thread, daemon=True).start()
    # Chạy Flask
    app.run(host="0.0.0.0", port=5000)
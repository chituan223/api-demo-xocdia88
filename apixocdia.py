from flask import Flask, jsonify
import threading
import websocket
import json
import time

# ================= Cấu hình WebSocket =================
WS_URL = "wss://taixiumd5.system32-cloudfare-356783752985678522.monster/signalr/reconnect?transport=webSockets&connectionToken=SgIYXqnbkJRw6FvkcaXYVrAcj9Rkcx758qlxIanF3odMFBbrqY%2BJJ%2FVvZUnOX0Z2pNFJwckC2pCxXefKhAclClEefIExyEGKc9Z6zfoZsoa9oUAzcs1LNw2G3jxr7w9j&connectionData=%5B%7B%22name%22%3A%22md5luckydiceHub%22%7D%5D&tid=6&access_token=05%2F7JlwSPGzg4ARi0d7%2FLOcNQQ%2BecAvgB3UwDAmuWFJiZj%2Blw1TcJ0PZt5VeUAHKLVCmODRrV5CHPNbit3mc868w8zYBuyQ5Xlu1AZVsEElr9od2qJ8S9N2GLAdQnd0VL8fj8IAGPMsP45pdIIXZysKmRi40b%2FOVLAp4yOpkaXP3icyn2%2Fodm397vVKSY9AlMCcH15AghVm3lx5JM%2BoUuP%2Fkjgh5xWXtdTQkd9W3%2BQBY25AdX3CvOZ2I17r67METGpFv8cP7xmAoySWEnokU2IcOKu3mzvRWXsG7N5sHFkv%2FIKw%2F1IPCNY2oi8RygWpHwIFWcHGdeoTeM6kskfrqNSmhapPBCREit0So1HOC6jOiz5IyKVNadwp8EfsxKzBOKE0z0zdavvY6wXrSZhEJeIqKqVAt3SEuoG82a%2BjwxNo%3D.5a1d88795043d5c4ef6538c9edfb5ff93e65b852d89f71344bdd5ec80eb63e24"
PING_INTERVAL = 15

# ================= Biến lưu kết quả =================
latest_result = {
    "Phien": None,
    "Xuc_xac_1": -1,
    "Xuc_xac_2": -1,
    "Xuc_xac_3": -1,
    "Ket_qua": None,
    "Du_doan_tiep": "Đang phân tích...",
    "Do_tin_cay": 0,
    "id": "daubuoi"
}
lock = threading.Lock()
history = []
MAX_HISTORY = 50


# ================= Hàm tính Tài/Xỉu =================
def get_tai_xiu(d1, d2, d3):
    total = d1 + d2 + d3
    return "Xỉu" if total <= 10 else "Tài"


# ================= Pentter-AI v4.8 Elite =================
def pentter_ai_v4_8(history):
    if len(history) < 6:
        return {"du_doan": "Tài", "do_tin_cay": 60}

    # === LỚP 1: Nhận dạng chuỗi lặp ===
    if len(set(history[-3:])) == 1:
        v1, w1 = history[-1], 0.9
    elif history[-1] == history[-2]:
        v1, w1 = history[-1], 0.75
    else:
        v1, w1 = ("Xỉu" if history[-1] == "Tài" else "Tài"), 0.55

    # === LỚP 2: Dao động gần ===
    flip = sum(history[i] != history[i-1] for i in range(-1, -5, -1))
    v2 = "Tài" if flip % 2 == 0 else "Xỉu"
    w2 = 0.7 if flip in (1, 3) else 0.6

    # === LỚP 3: Tỷ lệ cầu nghiêng ===
    recent = history[-12:] if len(history) >= 12 else history
    tai, xiu = recent.count("Tài"), recent.count("Xỉu")
    if abs(tai - xiu) >= 4:
        v3 = "Tài" if tai < xiu else "Xỉu"
        w3 = 0.85
    else:
        v3 = history[-1]
        w3 = 0.65

    # === LỚP 4: Cầu chu kỳ ===
    if len(history) >= 6:
        h = history[-6:]
        if h[0] == h[3] and h[1] == h[4]:
            v4, w4 = h[2], 0.9
        else:
            v4, w4 = ("Tài" if history[-1] == "Xỉu" else "Xỉu"), 0.65
    else:
        v4, w4 = v1, 0.6

    # === LỚP 5: Entropy (xu hướng ngắn hạn) ===
    entropy = abs(history[-5:].count("Tài") - history[-5:].count("Xỉu")) / 5
    if entropy < 0.4:
        v5, w5 = history[-1], 0.8
    else:
        v5, w5 = ("Xỉu" if history[-1] == "Tài" else "Tài"), 0.7

    # === LỚP 6: Độ ổn định chuỗi ===
    streak = 1
    for i in range(-2, -len(history)-1, -1):
        if history[i] == history[-1]:
            streak += 1
        else:
            break
    v6 = history[-1] if streak >= 3 else ("Xỉu" if history[-1] == "Tài" else "Tài")
    w6 = min(0.6 + streak * 0.05, 0.9)

    # === LỚP 7: Định hướng tổng thể ===
    momentum = (tai - xiu) / len(recent)
    if momentum > 0.2:
        v7, w7 = "Tài", 0.8
    elif momentum < -0.2:
        v7, w7 = "Xỉu", 0.8
    else:
        v7, w7 = history[-1], 0.6

    # === Tổng hợp votes ===
    votes = [v1, v2, v3, v4, v5, v6, v7]
    weights = [w1, w2, w3, w4, w5, w6, w7]
    score_tai = sum(w for v, w in zip(votes, weights) if v == "Tài")
    score_xiu = sum(w for v, w in zip(votes, weights) if v == "Xỉu")

    du_doan = "Tài" if score_tai > score_xiu else "Xỉu"
    do_tin_cay = round(abs(score_tai - score_xiu) / sum(weights) * 100 + 65, 1)
    if do_tin_cay > 97: do_tin_cay = 97
    if do_tin_cay < 70: do_tin_cay += 5

    return {"du_doan": du_doan, "do_tin_cay": do_tin_cay}


# ================= Xử lý WebSocket =================
def on_message(ws, message):
    global latest_result, history
    try:
        data = json.loads(message)
        if isinstance(data, dict) and "M" in data:
            for m_item in data["M"]:
                if "M" in m_item and m_item["M"] == "Md5sessionInfo":
                    session_info = m_item["A"][0]
                    session_id = session_info.get("SessionID")
                    result = session_info.get("Result", {})
                    d1 = result.get("Dice1", -1)
                    d2 = result.get("Dice2", -1)
                    d3 = result.get("Dice3", -1)

                    if d1 != -1 and d2 != -1 and d3 != -1:
                        ket_qua = get_tai_xiu(d1, d2, d3)
                        with lock:
                            latest_result["Phien"] = session_id
                            latest_result["Xuc_xac_1"] = d1
                            latest_result["Xuc_xac_2"] = d2
                            latest_result["Xuc_xac_3"] = d3
                            latest_result["Ket_qua"] = ket_qua

                            history.append(ket_qua)
                            if len(history) > MAX_HISTORY:
                                history.pop(0)

                            pred = pentter_ai_v4_8(history)
                            latest_result["Du_doan_tiep"] = pred["du_doan"]
                            latest_result["Do_tin_cay"] = pred["do_tin_cay"]

    except Exception as e:
        print("Lỗi xử lý message:", e)


def on_error(ws, error):
    print("WebSocket lỗi:", error)


def on_close(ws, close_status_code, close_msg):
    print("WebSocket đóng, reconnect sau 5s...")
    time.sleep(5)
    start_ws_thread()


def on_open(ws):
    def ping():
        while True:
            try:
                ping_msg = json.dumps({"M": "PingPong", "H": "md5luckydiceHub", "I": 0})
                ws.send(ping_msg)
                time.sleep(PING_INTERVAL)
            except:
                break
    threading.Thread(target=ping, daemon=True).start()


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

@app.route("/")
def index():
    return "✅ Pentter-AI v4.8 Elite đang chạy | /api/taixiumd5"


# ================= Main =================
if __name__ == "__main__":
    threading.Thread(target=start_ws_thread, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)

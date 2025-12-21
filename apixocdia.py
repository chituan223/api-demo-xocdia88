from flask import Flask, jsonify
import threading
import websocket
import json
import time
from typing import List, Dict, Any, Tuple
import statistics

# ================= CONFIGURATION =================
# Lưu ý: connectionToken và access_token trong WS_URL thường thay đổi theo phiên đăng nhập.
WS_URL = "wss://taixiumd5.system32-cloudfare-356783752985678522.monster/signalr/connect?transport=webSockets&connectionToken=..."
PING_INTERVAL = 15
MAX_HISTORY = 150

# ================= GLOBAL DATA =================
lock = threading.Lock()
results_history: List[str] = [] 
dice_totals: List[int] = []

latest_state = {
    "Phien": None,
    "Tong_diem": 0,
    "Ket_qua": None,
    "Du_doan_tiep": "Waiting...",
    "Do_tin_cay": 0.0,
    "Algorithm": "Stable-Technical-V4"
}

# ================= STABLE ALGORITHMS (NO RANDOM) =================

class StableAI:
    @staticmethod
    def rsi_logic(totals: List[int]) -> Tuple[str, float]:
        """Tính chỉ số RSI thực tế để xác định vùng quá Tài/quá Xỉu."""
        if len(totals) < 14: return "Tài", 50.0
        subset = totals[-14:]
        gains = [max(0, subset[i] - subset[i-1]) for i in range(1, len(subset))]
        losses = [max(0, subset[i-1] - subset[i]) for i in range(1, len(subset))]
        
        avg_gain = sum(gains) / 14
        avg_loss = sum(losses) / 14
        if avg_loss == 0: return "Xỉu", 90.0 # Quá Tài tuyệt đối
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        if rsi > 70: return "Xỉu", 85.0
        if rsi < 30: return "Tài", 85.0
        return ("Tài" if rsi > 50 else "Xỉu"), 60.0

    @staticmethod
    def bollinger_bands_logic(totals: List[int]) -> Tuple[str, float]:
        """Tính dải Bollinger Bands để bắt điểm hồi quy."""
        if len(totals) < 20: return "Tài", 50.0
        window = totals[-20:]
        sma = statistics.mean(window)
        stdev = statistics.stdev(window)
        
        current = totals[-1]
        upper = sma + (2 * stdev)
        lower = sma - (2 * stdev)
        
        if current >= upper: return "Xỉu", 95.0
        if current <= lower: return "Tài", 95.0
        return ("Tài" if current < sma else "Xỉu"), 65.0

    @staticmethod
    def markov_chain_logic(history: List[str], depth: int) -> Tuple[str, float]:
        """Phân tích chuỗi xác suất dựa trên lịch sử phiên."""
        if len(history) < 30: return "Xỉu", 50.0
        pattern = "".join([h[0] for h in history[-depth:]])
        full_text = "".join([h[0] for h in history[:-1]])
        
        t_next = full_text.count(pattern + "T")
        x_next = full_text.count(pattern + "X")
        
        total = t_next + x_next
        if total == 0: return history[-1], 50.0
        
        conf = (max(t_next, x_next) / total) * 100
        pred = "Tài" if t_next > x_count else "Xỉu"
        return pred, conf

# ================= ENSEMBLE SYSTEM =================

def calculate_next_move(history, totals) -> Dict[str, Any]:
    if len(history) < 15:
        return {"du_doan": "Chờ thêm dữ liệu", "conf": 0.0}
    
    # Gom kết quả từ các 'chuyên gia'
    results = [
        StableAI.rsi_logic(totals),
        StableAI.bollinger_bands_logic(totals),
        StableAI.markov_chain_logic(history, 2),
        StableAI.markov_chain_logic(history, 3)
    ]
    
    votes = {"Tài": 0.0, "Xỉu": 0.0}
    for move, weight in results:
        votes[move] += weight
        
    final_move = "Tài" if votes["Tài"] > votes["Xỉu"] else "Xỉu"
    total_votes = votes["Tài"] + votes["Xỉu"]
    final_conf = (votes[final_move] / total_votes) * 100
    
    return {
        "du_doan": final_move,
        "conf": round(final_conf, 1)
    }

# ================= WEBSOCKET HANDLER =================

def on_message(ws, message):
    global latest_state, results_history, dice_totals
    try:
        data = json.loads(message)
        # SignalR thường gửi dữ liệu trong mảng 'M' (Messages)
        if "M" in data:
            for m in data["M"]:
                if m.get("M") == "Md5sessionInfo":
                    info = m["A"][0]
                    res = info.get("Result")
                    if res:
                        d1, d2, d3 = res["Dice1"], res["Dice2"], res["Dice3"]
                        total = d1 + d2 + d3
                        sid = info.get("SessionID")
                        
                        with lock:
                            if latest_state["Phien"] != sid:
                                result_label = "Tài" if total >= 11 else "Xỉu"
                                
                                # Cập nhật lịch sử
                                results_history.append(result_label)
                                dice_totals.append(total)
                                if len(results_history) > MAX_HISTORY:
                                    results_history.pop(0)
                                    dice_totals.pop(0)
                                
                                # Lưu trạng thái phiên vừa xong
                                latest_state["Phien"] = sid
                                latest_state["Tong_diem"] = total
                                latest_state["Ket_qua"] = result_label
                                
                                # Tính toán dự đoán cho phiên sắp tới
                                prediction = calculate_next_move(results_history, dice_totals)
                                latest_state["Du_doan_tiep"] = prediction["du_doan"]
                                latest_state["Do_tin_cay"] = prediction["conf"]
                                print(f"Phiên {sid}: {result_label} ({total}) -> Tiếp: {prediction['du_doan']}")
    except: pass

def start_ws():
    while True:
        try:
            # heartbeat SignalR thường là {} hoặc tin nhắn trống
            ws = websocket.WebSocketApp(
                WS_URL,
                on_message=on_message,
                on_open=lambda ws: print("WebSocket Connected"),
                on_close=lambda ws, s, m: print("WebSocket Closed")
            )
            ws.run_forever(ping_interval=15)
        except: time.sleep(5)

# ================= API SERVER =================

app = Flask(__name__)

@app.route("/api/taixiumd5")
def api():
    with lock:
        return jsonify(latest_state)

if __name__ == "__main__":
    # Chạy WebSocket trong luồng phụ
    threading.Thread(target=start_ws, daemon=True).start()
    # Chạy API Server
    app.run(host="0.0.0.0", port=5000)

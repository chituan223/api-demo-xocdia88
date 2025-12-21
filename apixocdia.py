from flask import Flask, jsonify
import threading
import websocket
import json
import time
from typing import List, Tuple, Dict, Any, Callable
import math
import random
import statistics

# ================= Cấu hình WebSocket =================
WS_URL = "wss://taixiumd5.system32-cloudfare-356783752985678522.monster/signalr/reconnect?transport=webSockets&connectionToken=..." 
PING_INTERVAL = 15
MAX_HISTORY = 100 

# ================= Biến toàn cục & Lock =================
lock = threading.Lock()
results_history: List[str] = [] 
dice_points_history: List[int] = [] # Chỉ lưu tổng điểm T để tính toán nhanh

latest_result: Dict[str, Any] = {
    "Phien": None,
    "Tong_diem": -1,
    "Ket_qua": None,
    "Du_doan_tiep": "Đang chờ dữ liệu...",
    "Do_tin_cay": 0.0,
    "He_thong": "Ensemble-V3-Pro"
}

# ================= THUẬT TOÁN AI V3.0 (PHÂN TÍCH KỸ THUẬT) =================

class TechnicalAI:
    @staticmethod
    def rsi_momentum(totals: List[int]) -> Tuple[str, float]:
        """Chỉ số RSI (Relative Strength Index) - Nhận diện quá Tài/quá Xỉu."""
        if len(totals) < 14: return "Tài", 50.0
        gains = [max(0, totals[i] - totals[i-1]) for i in range(-13, 0)]
        losses = [max(0, totals[i-1] - totals[i]) for i in range(-13, 0)]
        avg_gain = sum(gains) / 14
        avg_loss = sum(losses) / 14
        rs = avg_gain / (avg_loss + 0.0001)
        rsi = 100 - (100 / (1 + rs))
        
        if rsi > 70: return "Xỉu", 88.0  # RSI cao -> Quá Tài -> Đánh Xỉu
        if rsi < 30: return "Tài", 88.0  # RSI thấp -> Quá Xỉu -> Đánh Tài
        return ("Tài" if rsi > 50 else "Xỉu"), 60.0

    @staticmethod
    def bollinger_bands(totals: List[int]) -> Tuple[str, float]:
        """Dải Bollinger - Dự báo sự bùng nổ hoặc hồi quy điểm số."""
        if len(totals) < 20: return "Xỉu", 50.0
        window = totals[-20:]
        sma = statistics.mean(window)
        std_dev = statistics.stdev(window)
        upper = sma + (1.8 * std_dev)
        lower = sma - (1.8 * std_dev)
        curr = totals[-1]
        
        if curr >= upper: return "Xỉu", 92.0 # Chạm biên trên -> Hồi quy về Xỉu
        if curr <= lower: return "Tài", 92.0 # Chạm biên dưới -> Hồi quy về Tài
        return ("Tài" if curr < sma else "Xỉu"), 65.0

    @staticmethod
    def markov_pattern(history: List[str], depth: int = 3) -> Tuple[str, float]:
        """Markov Chain - Tìm kiếm sự lặp lại của chuỗi ký tự (Cầu)."""
        if len(history) < 20: return "Tài", 50.0
        pattern = "".join([h[0] for h in history[-depth:]])
        full_str = "".join([h[0] for h in history[:-1]])
        t_count = full_str.count(pattern + "T")
        x_count = full_str.count(pattern + "X")
        
        if t_count > x_count: return "Tài", 85.0
        if x_count > t_count: return "Xỉu", 85.0
        return history[-1], 50.0

    @staticmethod
    def bridge_detector(history: List[str]) -> Tuple[str, float]:
        """Bắt cầu 1-1, 2-2 và Bệt dây."""
        if len(history) < 5: return history[-1] if history else "Tài", 50.0
        # Check Bệt
        streak = 1
        for i in range(len(history)-1, 0, -1):
            if history[i] == history[i-1]: streak += 1
            else: break
        if streak >= 4: return history[-1], 80.0 # Theo bệt
        
        # Check 1-1
        if history[-1] != history[-2] and history[-2] != history[-3]:
            return ("Xỉu" if history[-1] == "Tài" else "Tài"), 85.0
        return history[-1], 55.0

# ================= HỆ THỐNG QUYẾT ĐỊNH (ENSEMBLE) =================

def ensemble_predict(history: List[str], totals: List[int]) -> Dict[str, Any]:
    if len(history) < 15:
        return {"du_doan": history[-1] if history else "Đang chờ", "do_tin_cay": 50.0}

    # Danh sách các chuyên gia và trọng số uy tín
    experts = [
        TechnicalAI.rsi_momentum(totals),
        TechnicalAI.bollinger_bands(totals),
        TechnicalAI.markov_pattern(history, 2),
        TechnicalAI.markov_pattern(history, 3),
        TechnicalAI.bridge_detector(history)
    ]

    votes = {"Tài": 0.0, "Xỉu": 0.0}
    for pred, conf in experts:
        # Trọng số được tính bằng độ tin cậy của từng phương pháp
        votes[pred] += conf

    final_pred = "Tài" if votes["Tài"] > votes["Xỉu"] else "Xỉu"
    total_score = votes["Tài"] + votes["Xỉu"]
    
    # Tính toán độ tin cậy dựa trên sự đồng thuận của các thuật toán
    final_conf = (votes[final_pred] / total_score) * 100
    # Chuẩn hóa về dải 60% - 98%
    final_conf = 60 + (final_conf - 50) * 0.76
    
    return {"du_doan": final_pred, "do_tin_cay": round(min(final_conf, 98.8), 1)}

# ================= Xử lý WebSocket & Flask =================

def on_message(ws, message):
    global latest_result, results_history, dice_points_history
    try:
        data = json.loads(message)
        if isinstance(data, dict) and "M" in data:
            for m_item in data["M"]:
                if m_item.get("M") == "Md5sessionInfo":
                    session_info = m_item["A"][0]
                    res = session_info.get("Result", {})
                    d1, d2, d3 = res.get("Dice1", 0), res.get("Dice2", 0), res.get("Dice3", 0)
                    
                    if d1 > 0:
                        total = d1 + d2 + d3
                        sid = session_info.get("SessionID")
                        
                        with lock:
                            if latest_result["Phien"] != sid:
                                result_str = "Tài" if total >= 11 else "Xỉu"
                                results_history.append(result_str)
                                dice_points_history.append(total)
                                
                                if len(results_history) > MAX_HISTORY:
                                    results_history.pop(0)
                                    dice_points_history.pop(0)

                                # Cập nhật phiên mới nhất
                                latest_result["Phien"] = sid
                                latest_result["Tong_diem"] = total
                                latest_result["Ket_qua"] = result_str
                                
                                # Dự đoán cho phiên tiếp theo
                                prediction = ensemble_predict(results_history, dice_points_history)
                                latest_result["Du_doan_tiep"] = prediction["du_doan"]
                                latest_result["Do_tin_cay"] = prediction["do_tin_cay"]
                                
    except Exception as e: pass

def on_open(ws):
    def ping():
        while True:
            time.sleep(PING_INTERVAL)
            try: ws.send("{}")
            except: break
    threading.Thread(target=ping, daemon=True).start()

def start_ws():
    while True:
        try:
            ws = websocket.WebSocketApp(WS_URL, on_open=on_open, on_message=on_message)
            ws.run_forever()
        except: time.sleep(5)

app = Flask(__name__)

@app.route("/api/taixiumd5")
def get_data():
    with lock: return jsonify(latest_result)

@app.route("/")
def index(): return "🚀 Pentter-AI v3.0 (Ensemble Technical) is running."

if __name__ == "__main__":
    threading.Thread(target=start_ws, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)

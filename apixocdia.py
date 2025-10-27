from flask import Flask, jsonify
import threading
import websocket
import json
import time
from typing import List, Tuple, Dict, Any

# ================= Cấu hình WebSocket =================
# LƯU Ý: connectionToken và access_token trong WS_URL thường hết hạn nhanh. 
# Cần cập nhật token mới để kết nối thành công.
WS_URL = "wss://taixiumd5.system32-cloudfare-356783752985678522.monster/signalr/reconnect?transport=webSockets&connectionToken=SgIYXqnbkJRw6FvkcaXYVrAcj9Rkcx758qlxIanF3odMFBbrqY%2BJJ%2FVvZUnOX0Z2pNFJwckC2pCxXefKhAclClEefIExyEGKc9Z6zfoZsoa9oUAzcs1LNw2G3jxr7w9j&connectionData=%5B%7B%22name%22%3A%22md5luckydiceHub%22%7D%5D&tid=6&access_token=05%2F7JlwSPGzg4ARi0d7%2FLOcNQQ%2BecAvgB3UwDAmuWFJiZj%2Blw1TcJ0PZt5VeUAHKLVCmODRrV5CHPNbit3mc868w8zYBuyQ5Xlu1AZVsEElr9od2qJ8S9N2GLAdQnd0VL8fj8IAGPMsP45pdIIXZysKmRi40b%2FOVLAp4yOpkaXP3icyn2%2Fodm397vVKSY9AlMCcH15AghVm3lx5JM%2BoUuP%2Fkjgh5xWXtdTQkd9W3%2BQBY25AdX3CvOZ2I17r67METGpFv8cP7xmAoySWEnokU2IcOKu3mzvRWXsG7N5sHFkv%2FIKw%2F1IPCNY2oi8RygWpHwIFWcHGdeoTeM6kskfrqNSmhapPBCREit0So1HOC6jOiz5IyKVNadwp8EfsxKzBOKE0z0zdavvY6wXrSZhEJeIqKqVAt3SEuoG82a%2BjwxNo%3D.5a1d88795043d5c4ef6538c9edfb5ff93e65b852d89f71344bdd5ec80eb63e24"
PING_INTERVAL = 15

# ================= Biến lưu kết quả =================
latest_result: Dict[str, Any] = {
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
history: List[str] = [] # Lịch sử kết quả: ["Tài", "Xỉu", "Tài", ...]
MAX_HISTORY = 50

# ================= Hàm tính Tài/Xỉu =================
def get_tai_xiu(d1: int, d2: int, d3: int) -> str:
    """Tính tổng 3 xúc xắc và trả về 'Tài' hoặc 'Xỉu'."""
    total = d1 + d2 + d3
    return "Xỉu" if total <= 10 else "Tài"

def reverse_result(result: str) -> str:
    """Đảo ngược kết quả (Tài -> Xỉu, Xỉu -> Tài)."""
    return "Xỉu" if result == "Tài" else "Tài"

# ================= PENTTER-AI V4.8 ELITE (15 LỚP PHÂN TÍCH) =================
# Mỗi layer trả về Tuple[str, float] = (dự đoán, trọng số tin cậy)
HistoryList = List[str]

# L01: Short Bệt Check (3 consecutive same results)
def layer_01_short_bet(h: HistoryList) -> Tuple[str, float]:
    if h[-1] == h[-2] == h[-3]:
        return h[-1], 0.78 # Predict continuation
    return reverse_result(h[-1]), 0.60 # Predict change

# L02: Alternating Check (1-1)
def layer_02_alternating(h: HistoryList) -> Tuple[str, float]:
    if h[-1] != h[-2] and h[-2] != h[-3] and h[-3] != h[-4]:
        return reverse_result(h[-1]), 0.82 # Predict continuation of 1-1
    return h[-1], 0.55

# L03: Double-Double Check (2-2)
def layer_03_double_double(h: HistoryList) -> Tuple[str, float]:
    if h[-1] == h[-2] and h[-3] == h[-4] and h[-1] != h[-3]:
        return h[-3], 0.88 # Predict the side that just finished its double run
    return reverse_result(h[-1]), 0.65

# L04: Triple-Triple Check (3-3)
def layer_04_triple_triple(h: HistoryList) -> Tuple[str, float]:
    if h[-1] == h[-2] == h[-3] and h[-4] == h[-5] == h[-6] and h[-1] != h[-4]:
        return reverse_result(h[-1]), 0.92 # Predict the start of the next 3-streak
    return h[-1], 0.60

# L05: Recent Momentum (5 results)
def layer_05_recent_momentum(h: HistoryList) -> Tuple[str, float]:
    recent = h[-5:]
    tai = recent.count("Tài")
    xiu = recent.count("Xỉu")
    if tai > xiu + 2:
        return "Tài", 0.70
    elif xiu > tai + 2:
        return "Xỉu", 0.70
    return reverse_result(h[-1]), 0.55

# L06: Long Bệt Break (Check Bệt > 7)
def layer_06_long_bet_break(h: HistoryList) -> Tuple[str, float]:
    streak = 1
    for i in range(2, len(h) + 1):
        if h[-i] == h[-1]:
            streak += 1
        else:
            break
    if streak >= 8:
        return reverse_result(h[-1]), 0.95 # High weight to break the long bệt
    return h[-1], 0.65

# L07: Penta-Mirror Pattern (TXTTX - Predict T)
def layer_07_penta_mirror(h: HistoryList) -> Tuple[str, float]:
    # A-B-A-A-B pattern (TXTTX or XTTXT)
    if h[-1] == h[-3] and h[-1] == h[-4] and h[-2] != h[-1] and h[-5] != h[-1]:
        return h[-1], 0.80 # Predict continuation of the majority side
    return h[-1], 0.50

# L08: Anti-Martingale (Short Oscillation check, 6 results)
def layer_08_anti_martingale(h: HistoryList) -> Tuple[str, float]:
    # Check for Zic Zac (high number of flips)
    flips = sum(1 for i in range(-1, -6, -1) if h[i] != h[i-1])
    if flips >= 4:
        return reverse_result(h[-1]), 0.75 # Predict continuation of flip (Zic Zac)
    return h[-1], 0.60

# L09: Overall Trend (Minority Side - 20 results)
def layer_09_overall_trend(h: HistoryList) -> Tuple[str, float]:
    recent_20 = h[-20:]
    tai = recent_20.count("Tài")
    xiu = recent_20.count("Xỉu")
    if abs(tai - xiu) > 5:
        return "Tài" if tai < xiu else "Xỉu", 0.68 # Predict the minority side to balance
    return h[-1], 0.55

# L10: Bridge Break Check (T-X-T type, 3 results)
def layer_10_bridge_break(h: HistoryList) -> Tuple[str, float]:
    # If pattern is T-X-T or X-T-X
    if h[-3] == h[-1] and h[-3] != h[-2]:
        # Predict continuation of the streak that just ended (i.e., reverse the middle one)
        return reverse_result(h[-2]), 0.70 
    return h[-1], 0.55

# L11: 4-Pattern Anticipation (T-T-T-T or X-X-X-X)
def layer_11_four_pattern(h: HistoryList) -> Tuple[str, float]:
    if h[-1] == h[-2] == h[-3] == h[-4]:
        return reverse_result(h[-1]), 0.85 # Predict reversal after 4 streak
    return h[-1], 0.60

# L12: Even/Odd Streak Length Reversal
def layer_12_streak_reversal(h: HistoryList) -> Tuple[str, float]:
    streak = 1
    for i in range(2, len(h) + 1):
        if h[-i] == h[-1]:
            streak += 1
        else:
            break
    if streak % 2 != 0 and streak > 1: # Odd streak length (3, 5, 7...)
        return reverse_result(h[-1]), 0.72 # Predict reversal
    return h[-1], 0.60

# L13: Long Range Balance (50 results - High weight for balance)
def layer_13_long_balance(h: HistoryList) -> Tuple[str, float]:
    tai = h.count("Tài")
    xiu = h.count("Xỉu")
    # Strong prediction if balance is skewed by more than 10
    if abs(tai - xiu) > 10:
        return "Tài" if tai < xiu else "Xỉu", 0.88 # Predict the minority side
    return h[-1], 0.55

# L14: Second-to-Last Mirror (A-B-A pattern)
def layer_14_second_mirror(h: HistoryList) -> Tuple[str, float]:
    # A-B-A means the next one should be B
    if h[-3] == h[-1] and h[-3] != h[-2]:
        return h[-2], 0.75 # Predict B
    return h[-1], 0.55

# L15: Shortest Run Predictor (Last 10 results)
def layer_15_shortest_run(h: HistoryList) -> Tuple[str, float]:
    recent = h[-10:]
    tai = recent.count("Tài")
    xiu = recent.count("Xỉu")
    if tai < xiu:
        return "Tài", 0.75 # Predict the side that appeared least
    elif xiu < tai:
        return "Xỉu", 0.75
    return h[-1], 0.50

def advanced_pentter_ai(history: HistoryList) -> Dict[str, Any]:
    """Tổng hợp 15 lớp phân tích để đưa ra dự đoán cuối cùng."""
    if len(history) < 6:
        # Nếu lịch sử chưa đủ dài, đưa ra dự đoán cơ sở trung lập.
        return {"du_doan": "Tài", "do_tin_cay": 55.0}

    # Danh sách 15 layer: (logic_function, min_history_length)
    all_layers = [
        (layer_01_short_bet, 3), (layer_02_alternating, 4),
        (layer_03_double_double, 4), (layer_04_triple_triple, 6),
        (layer_05_recent_momentum, 5), (layer_06_long_bet_break, 8),
        (layer_07_penta_mirror, 5), (layer_08_anti_martingale, 6),
        (layer_09_overall_trend, 20), (layer_10_bridge_break, 3),
        (layer_11_four_pattern, 4), (layer_12_streak_reversal, 3),
        (layer_13_long_balance, 50), (layer_14_second_mirror, 3),
        (layer_15_shortest_run, 10)
    ]

    score_tai = 0.0
    score_xiu = 0.0
    total_weight = 0.0

    for logic_func, min_len in all_layers:
        # Chỉ thực hiện và tính trọng số nếu lịch sử đủ dài cho logic đó
        if len(history) >= min_len:
            pred, weight = logic_func(history)
            
            if pred == "Tài":
                score_tai += weight
            else:
                score_xiu += weight
            total_weight += weight

    if total_weight == 0:
        return {"du_doan": history[-1], "do_tin_cay": 50.0}
        
    du_doan = "Tài" if score_tai > score_xiu else "Xỉu"
    
    # ================= LOGIC TÍNH ĐỘ TIN CẬY MỚI (DYNAMIC SWING) =================
    winning_score = max(score_tai, score_xiu)
    losing_score = min(score_tai, score_xiu)

    # 1. Tính toán Tỷ lệ Biên độ (Margin Ratio): (Điểm Thắng - Điểm Thua) / Tổng Điểm
    # Tỷ lệ này nằm trong khoảng [0, 1]
    margin = (winning_score - losing_score) / total_weight

    # 2. Base Confidence luôn là 50.0 (điểm ngẫu nhiên cơ sở)
    # 3. Khuếch đại Biên độ (margin * 48): Margin càng lớn (đồng thuận càng cao), Boost càng cao, 
    # Tối đa 50 + 48 = 98.0
    do_tin_cay = 50.0 + (margin * 48) 
    
    # 4. Đảm bảo tỷ lệ luôn trên 50% (trừ khi total_weight = 0) và dưới 98%
    do_tin_cay = max(do_tin_cay, 50.1)
    do_tin_cay = round(min(do_tin_cay, 98.0), 1)
    # ================= END LOGIC MỚI =================

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
                            # 1. Cập nhật kết quả phiên vừa xong
                            # Ngăn chặn việc thêm cùng một phiên vào lịch sử nhiều lần
                            if latest_result["Phien"] != session_id:
                                # Thêm kết quả vào lịch sử
                                if latest_result["Ket_qua"]:
                                    history.append(latest_result["Ket_qua"])
                                    if len(history) > MAX_HISTORY:
                                        history.pop(0)

                                # Cập nhật dữ liệu phiên mới
                                latest_result["Phien"] = session_id
                                latest_result["Xuc_xac_1"] = d1
                                latest_result["Xuc_xac_2"] = d2
                                latest_result["Xuc_xac_3"] = d3
                                latest_result["Ket_qua"] = ket_qua
                            
                            # 2. Chạy thuật toán dự đoán cho phiên tiếp theo
                            pred = advanced_pentter_ai(history)
                            latest_result["Du_doan_tiep"] = pred["du_doan"]
                            latest_result["Do_tin_cay"] = pred["do_tin_cay"]
                            
    except Exception as e:
        print("Lỗi xử lý message:", e)

def on_error(ws, error):
    print("WebSocket lỗi:", error)

def on_close(ws, close_status_code, close_msg):
    print("WebSocket đóng, thử kết nối lại sau 5s...")
    time.sleep(5)
    start_ws_thread()

def on_open(ws):
    def ping():
        while True:
            try:
                # Gửi tín hiệu Ping/Pong để giữ kết nối
                ping_msg = json.dumps({"M": "PingPong", "H": "md5luckydiceHub", "I": 0})
                ws.send(ping_msg)
                time.sleep(PING_INTERVAL)
            except:
                break
    threading.Thread(target=ping, daemon=True).start()

def start_ws_thread():
    """Khởi động luồng WebSocket để nhận dữ liệu."""
    ws = websocket.WebSocketApp(
        WS_URL, 
        on_open=on_open, 
        on_message=on_message, 
        on_error=on_error, 
        on_close=on_close
    )
    # run_forever có tính năng tự động reconnect cơ bản, nhưng ta vẫn dùng on_close để đảm bảo
    ws.run_forever(ping_interval=10, ping_timeout=5)

# ================= Flask API =================
app = Flask(__name__)

@app.route("/api/taixiumd5")
def get_latest():
    """Endpoint trả về kết quả phiên mới nhất và dự đoán cho phiên tiếp theo."""
    with lock:
        return jsonify(latest_result)

@app.route("/")
def index():
    return "✅ Pentter-AI v4.8 Elite (15 Layers) đang chạy. Truy cập /api/taixiumd5 để xem dự đoán."

# ================= Main =================
if __name__ == "__main__":
    # Khởi động WebSocket trong một luồng riêng
    threading.Thread(target=start_ws_thread, daemon=True).start()
    
    # Khởi động Flask server
    print("Khởi động Pentter-AI Flask Server tại http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000)

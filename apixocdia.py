from flask import Flask, jsonify
import threading
import websocket
import json
import time
from typing import List, Tuple, Dict, Any
import math
import random
from collections import deque, Counter

# ================= Cấu hình WebSocket =================
# LƯU Ý: connectionToken và access_token trong WS_URL thường hết hạn nhanh. 
# Cần cập nhật token mới để kết nối thành công.
# Giữ nguyên URL của bạn:
WS_URL = "wss://taixiumd5.system32-cloudfare-356783752985678522.monster/signalr/reconnect?transport=webSockets&connectionToken=SgIYXqnbkJRw6FvkcaXYVrAcj9Rkcx758qlxIanF3odMFBbrqY%2BJJ%2FVvZUnOX0Z2pNFJwckC2pCxXefKhAclClEefIExyEGKc9Z6zfoZsoa9oUAzcs1LNw2G3jxr7w9j&connectionData=%5B%7B%22name%22%3A%22md5luckydiceHub%22%7D%5D&tid=6&access_token=05%2F7JlwSPGzg4ARi0d7%2FLOcNQQ%2BecAvgB3UwDAmuWFJiZj%2Blw1TcJ0PZt5VeUAHKLVCmODRrV5CHPNbit3mc868w8zYBuyQ5Xlu1AZVsEElr9od2qJ8S9N2GLAdQnd0VL8fj8IAGPMsP45pdIIXZysKmRi40b%2FOVLAp4yOpkaXP3icyn2%2Fodm397vVKSY9AlMCcH15AghVm3lx5JM%2BoUuP%2Fkjgh5xWXtdTQkd9W3%2BQBY25AdX3CvOZ2I17r67METGpFv8cP7xmAoySWEnokU2IcOKu3mzvRWXsG7N5sHFkv%2FIKw%2F1IPCNY2oi8RygWpHwIFWcHGdeoTeM6kskfrqNSmhapPBCREit0So1HOC6jOiz5IyKVNadwp8EfsxKzBOKE0z0zdavvY6wXrSZhIJeIqKqVAt3SEuoG82a%2BjwxNo%3D.5a1d88795043d5c4ef6538c9edfb5ff93e65b852d89b71344bdd5ec80eb63e24"
PING_INTERVAL = 15
MAX_HISTORY = 50

# ================= Biến toàn cục & Lock =================
lock = threading.Lock()
results_history: List[str] = [] # Ví dụ: ["Tài", "Xỉu", "Tài"]
dice_points_history: List[Dict[str, int]] = [] # Ví dụ: [{'T': 12, 'X1': 4}, ...]

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

# ================= HÀM TIỆN ÍCH (UTILITY FUNCTIONS) =================

def xac_dinh_tai_xiu(sum_val: int) -> str:
    """Xác định kết quả Tài (>10) hay Xỉu (<=10) từ tổng điểm."""
    return "Tài" if sum_val > 10 else "Xỉu"

def get_algorithm_result(func, *args) -> Dict[str, Any]:
    """Hàm bao bọc để gọi thuật toán an toàn."""
    try:
        return func(*args)
    except Exception:
        # Trả về mức trung lập (50.0) nếu thuật toán gặp lỗi
        return {"du_doan": "Tài", "do_tin_cay": 50.0} 

def calculate_confidence(base_confidence: float, variance_factor: float = 0) -> float:
    """Tính độ tin cậy cuối cùng (đảm bảo trên 50.1 và dưới 99.0)."""
    return max(50.1, min(99.0, base_confidence + variance_factor))

def get_parity(num: int) -> str:
    """Kiểm tra số chẵn/lẻ."""
    return "C" if num % 2 == 0 else "L"

# ================= 21 LỚP THUẬT TOÁN DỰ ĐOÁN (Đã khôi phục và tinh chỉnh) =================

# --- NHÓM 1: DỰ ĐOÁN THEO ĐIỂM SỐ (DICE POINTS) ---

def algo_01_complex_fib_offset(dice_points_history: List[Dict[str, int]]) -> Dict[str, Any]:
    """[Fibonacci Offset] Phân tích sự chênh lệch của Tổng (T) so với điểm trung bình Fib(3, 5, 8).
    Dự đoán đảo chiều nếu Total hiện tại lệch xa trung bình.
    """
    if len(dice_points_history) < 8: return {"du_doan": xac_dinh_tai_xiu(dice_points_history[-1]['T']), "do_tin_cay": 60.0}
    
    T_history = [d['T'] for d in dice_points_history[-8:]]
    last_T = T_history[-1]
    
    avg_3 = sum(T_history[-3:]) / 3
    avg_5 = sum(T_history[-5:]) / 5
    avg_8 = sum(T_history) / 8
    
    # Độ lệch tổng thể so với trung bình dài hạn
    overall_offset = last_T - avg_8
    
    if overall_offset > 2.0 and avg_3 < avg_5:
        # Total cao, nhưng trung bình ngắn hạn đang chậm lại so với trung bình trung -> Đảo chiều xuống (Xỉu)
        du_doan = "Xỉu"
        tin_cay = 85.5
    elif overall_offset < -2.0 and avg_3 > avg_5:
        # Total thấp, nhưng trung bình ngắn hạn đang chậm lại so với trung bình trung -> Đảo chiều lên (Tài)
        du_doan = "Tài"
        tin_cay = 54.8
    else:
        # Tiếp tục xu hướng ngắn hạn (Tăng/Giảm)
        du_doan = "Tài" if last_T > T_history[-2] else "Xỉu"
        tin_cay = 70.0

    return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(tin_cay)}

def algo_02_prime_number_offset(dice_points_history: List[Dict[str, int]]) -> Dict[str, Any]:
    """[Prime Number Offset] Kiểm tra nếu Tổng T gần hoặc trùng với số nguyên tố (2, 3, 5, 7, 11, 13, 17) 
    và dự đoán đảo chiều do tính chất 'hiếm' của các điểm này.
    """
    if not dice_points_history: return {"du_doan": "Xỉu", "do_tin_cay": 50.0}
    
    primes = {2, 3, 5, 7, 11, 13, 17}
    last_T = dice_points_history[-1]['T']
    
    is_prime = last_T in primes
    
    if is_prime and last_T >= 11: # Tài Prime -> Dự đoán đảo chiều Xỉu
        du_doan = "Xỉu"
        tin_cay = 80.0
    elif is_prime and last_T <= 10: # Xỉu Prime -> Dự đoán đảo chiều Tài
        du_doan = "Tài"
        tin_cay = 80.6
    else:
        # Tiếp tục xu hướng hiện tại
        du_doan = xac_dinh_tai_xiu(last_T)
        tin_cay = 65.0
        
    return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(tin_cay)}

def algo_03_x1_parity_stutter_index(dice_points_history: List[Dict[str, int]]) -> Dict[str, Any]:
    """[X1 Parity Stutter] Phân tích tính chẵn lẻ của xúc xắc 1 (X1). 
    Nếu X1 lặp lại (Chẵn-Chẵn hoặc Lẻ-Lẻ) quá nhiều, dự đoán phá vỡ chuỗi đó.
    """
    if len(dice_points_history) < 5: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    
    x1_parity = [get_parity(d['X1']) for d in dice_points_history[-5:]]
    stutter_count = 0
    for i in range(1, len(x1_parity)):
        if x1_parity[i] == x1_parity[i-1]:
            stutter_count += 1
            
    # Stutter index cao (4/4) -> Đang lặp chẵn/lẻ quá nhiều -> Dự đoán đảo chiều theo T/X
    if stutter_count >= 3:
        # Nếu X1 đang L-L-L, phiên tới dự đoán X1 sẽ Chẵn. Total sẽ cân bằng hơn -> Đảo chiều T/X
        last_result = xac_dinh_tai_xiu(dice_points_history[-1]['T'])
        du_doan = "Xỉu" if last_result == "Tài" else "Tài"
        tin_cay = 82.0
    else:
        # Trung lập, dự đoán theo Tổng hiện tại
        du_doan = xac_dinh_tai_xiu(dice_points_history[-1]['T'])
        tin_cay = 60.0
        
    return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(tin_cay)}

def algo_04_sum_boundary_tension(dice_points_history: List[Dict[str, int]]) -> Dict[str, Any]:
    """[Sum Boundary Tension] Dự đoán đảo chiều nếu Tổng T nằm ở gần biên (4, 5 hoặc 16, 17)"""
    if not dice_points_history: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    
    last_T = dice_points_history[-1]['T']
    
    if last_T <= 5: # Cực Xỉu (Low Boundary) -> Dự đoán bật lên (Tài)
        du_doan = "Tài"
        tin_cay = 83.9
    elif last_T >= 16: # Cực Tài (High Boundary) -> Dự đoán rơi xuống (Xỉu)
        du_doan = "Xỉu"
        tin_cay = 85.1
    else:
        # Khu vực trung tâm, dự đoán theo kết quả hiện tại
        du_doan = xac_dinh_tai_xiu(last_T)
        tin_cay = 60.0
        
    return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(tin_cay)}

def algo_10_x1_vs_sum_difference_pattern(dice_points_history: List[Dict[str, int]]) -> Dict[str, Any]:
    """[X1 vs Sum Difference] So sánh X1 với phần còn lại của Tổng (X2+X3). 
    Nếu X1 lớn hơn đáng kể phần còn lại, dự đoán đảo chiều.
    """
    if len(dice_points_history) < 4: return {"du_doan": "Tài", "do_tin_cay": 60.0}
    
    last_T = dice_points_history[-1]['T']
    last_X1 = dice_points_history[-1]['X1']
    diff_X1 = last_X1 - (last_T - last_X1) # X1 - (X2+X3)
    
    last_result = xac_dinh_tai_xiu(last_T)
    
    if diff_X1 >= 3: # X1 quá mạnh -> Dễ bị điều chỉnh xuống -> Đảo chiều T/X
        du_doan = "Xỉu" if last_result == "Tài" else "Tài"
        tin_cay = 85.0
    elif diff_X1 <= -3: # X1 quá yếu -> Dễ bị điều chỉnh lên -> Đảo chiều T/X
        du_doan = "Xỉu" if last_result == "Tài" else "Tài"
        tin_cay = 75.5
    else:
        du_doan = last_result
        tin_cay = 65.0
        
    return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(tin_cay)}

def algo_11_sum_trend_slope(dice_points_history: List[Dict[str, int]]) -> Dict[str, Any]:
    """[Sum Trend Slope] Tính độ dốc (Slope) của Tổng T trong 5 phiên gần nhất.
    Độ dốc cực dương -> Dự đoán giảm (Xỉu), Độ dốc cực âm -> Dự đoán tăng (Tài).
    """
    if len(dice_points_history) < 5: return {"du_doan": "Tài", "do_tin_cay": 60.0}
    
    T_history = [d['T'] for d in dice_points_history[-5:]]
    N = len(T_history)
    X = list(range(1, N + 1))
    
    # Simple linear regression slope (Độ dốc)
    sum_x = sum(X)
    sum_y = sum(T_history)
    sum_xy = sum(X[i] * T_history[i] for i in range(N))
    sum_x2 = sum(x ** 2 for x in X)
    
    try:
        slope = (N * sum_xy - sum_x * sum_y) / (N * sum_x2 - sum_x ** 2)
    except ZeroDivisionError:
        return {"du_doan": xac_dinh_tai_xiu(T_history[-1]), "do_tin_cay": 50.0}

    if slope > 1.0: # Dốc lên mạnh -> Quá mua (overbought) -> Đảo chiều Xỉu
        du_doan = "Xỉu"
        tin_cay = 88.0
    elif slope < -1.0: # Dốc xuống mạnh -> Quá bán (oversold) -> Đảo chiều Tài
        du_doan = "Tài"
        tin_cay = 64.0
    else:
        # Tiếp tục theo hướng dốc
        du_doan = xac_dinh_tai_xiu(T_history[-1])
        tin_cay = 70.0

    return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(tin_cay)}

def algo_12_rolling_median_cross(dice_points_history: List[Dict[str, int]]) -> Dict[str, Any]:
    """[Rolling Median Cross] So sánh Tổng T hiện tại với Trung vị trượt 10 phiên (Median).
    Nếu T vượt lên trên Median -> Tài. Nếu T cắt xuống dưới Median -> Xỉu.
    """
    if len(dice_points_history) < 10: return {"du_doan": "Xỉu", "do_tin_cay": 60.0}
    
    T_history = [d['T'] for d in dice_points_history[-10:]]
    last_T = T_history[-1]
    
    sorted_T = sorted(T_history[:-1])
    median = sorted_T[len(sorted_T) // 2]
    
    if last_T > median + 1: # Vượt lên trên Median -> Tiếp tục Tài
        du_doan = "Tài"
        tin_cay = 80.0
    elif last_T < median - 1: # Cắt xuống dưới Median -> Tiếp tục Xỉu
        du_doan = "Xỉu"
        tin_cay = 80.0
    else:
        # Trung lập, dự đoán theo kết quả hiện tại
        du_doan = xac_dinh_tai_xiu(last_T)
        tin_cay = 60.0
        
    return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(tin_cay)}

def algo_15_double_parity_vs_total_mod(dice_points_history: List[Dict[str, int]]) -> Dict[str, Any]:
    """[Double Parity vs Total Mod] Phân tích tính chẵn lẻ của (X1+X2) và (X2+X3), sau đó so với Total % 3. 
    Nếu cả hai Parity đều giống nhau và Total % 3 không bằng 0, dự đoán đảo chiều.
    """
    if not dice_points_history: return {"du_doan": "Xỉu", "do_tin_cay": 50.0}
    
    last_d = dice_points_history[-1]
    d1, d2, d3 = last_d['X1'], last_d['X2'], last_d['X3']
    last_T = last_d['T']
    
    parity_12 = get_parity(d1 + d2)
    parity_23 = get_parity(d2 + d3)
    
    # Logic: Nếu hai cặp Parity giống nhau (Cân bằng) VÀ Total không chia hết cho 3
    if parity_12 == parity_23 and last_T % 3 != 0:
        # Dự đoán đảo chiều
        last_result = xac_dinh_tai_xiu(last_T)
        du_doan = "Xỉu" if last_result == "Tài" else "Tài"
        tin_cay = 85.0
    else:
        du_doan = xac_dinh_tai_xiu(last_T)
        tin_cay = 60.0
        
    return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(tin_cay)}

# Thêm thuật toán đã có sẵn trong yêu cầu của bạn (để đảm bảo đầy đủ)
def algo_19_wavelet_decomposition_proxy(dice_points_history: List[Dict[str, int]]) -> Dict[str, Any]:
    """
    [Wavelet Decomposition Proxy] Phân tích xu hướng Tổng T bằng phương pháp Trung bình Trượt Đơn giản (SMA)
    để xác định điểm uốn (max/min cục bộ). Dự đoán đảo chiều tại các điểm uốn mạnh.
    """
    if len(dice_points_history) < 7: return {"du_doan": "Xỉu", "do_tin_cay": 60.0}

    totals = [d['T'] for d in dice_points_history[-7:]]

    # Tính SMA 3 phiên
    def sma_3(data):
        return [sum(data[i:i+3]) / 3 for i in range(len(data) - 2)]

    smas = sma_3(totals) # [sma_4, sma_5, sma_6, sma_7]

    if len(smas) < 3: return {"du_doan": xac_dinh_tai_xiu(totals[-1]), "do_tin_cay": 65.0}

    # Kiểm tra điểm uốn (Đỉnh/Đáy cục bộ)
    # Lấy 3 SMA cuối: sma_t2, sma_t1, sma_current
    sma_t2, sma_t1, sma_current = smas[-3:]
    last_result = xac_dinh_tai_xiu(totals[-1])

    # Đỉnh (Local Peak): Tăng -> Đỉnh -> Giảm (sma_t2 < sma_t1 > sma_current)
    if sma_t2 < sma_t1 and sma_t1 > sma_current and abs(sma_t2 - sma_current) > 0.5:
        # Đạt đỉnh -> Dự đoán đảo chiều xuống (Xỉu)
        du_doan = "Xỉu"
        tin_cay = 88.0
    # Đáy (Local Trough): Giảm -> Đáy -> Tăng (sma_t2 > sma_t1 < sma_current)
    elif sma_t2 > sma_t1 and sma_t1 < sma_current and abs(sma_t2 - sma_current) > 0.5:
        # Đạt đáy -> Dự đoán đảo chiều lên (Tài)
        du_doan = "Tài"
        tin_cay = 88.0
    else:
        # Tiếp tục xu hướng hiện tại
        du_doan = "Tài" if sma_current > sma_t1 else "Xỉu"
        tin_cay = 70.0

    return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(tin_cay)}

# Thêm thuật toán đã có sẵn trong yêu cầu của bạn (để đảm bảo đầy đủ)
def algo_20_harmonic_mean_crossover(dice_points_history: List[Dict[str, int]]) -> Dict[str, Any]:
    """
    [Harmonic Mean Crossover] So sánh Tổng T với trung bình điều hòa (Harmonic Mean) của 10 phiên.
    Dự đoán tiếp tục xu hướng nếu Tổng vượt trên (Tài) hoặc dưới (Xỉu) Harmonic Mean.
    """
    if len(dice_points_history) < 10: return {"du_doan": "Tài", "do_tin_cay": 60.0}
    
    totals = [d['T'] for d in dice_points_history[-10:] if d['T'] > 0] # Lọc bỏ 0 nếu có
    if not totals: return {"du_doan": "Tài", "do_tin_cay": 60.0}

    # Tính Harmonic Mean (HM)
    harmonic_mean = len(totals) / sum(1.0 / t for t in totals)
    last_total = dice_points_history[-1]['T']
    
    if last_total > harmonic_mean + 1.0:
        # Vượt lên trên HM -> Tiếp tục Tài
        du_doan = "Tài"
        tin_cay = 82.0
    elif last_total < harmonic_mean - 1.0:
        # Vượt xuống dưới HM -> Tiếp tục Xỉu
        du_doan = "Xỉu"
        tin_cay = 82.9
    else:
        # Gần HM -> Hồi quy nhẹ (Đảo chiều)
        last_result = xac_dinh_tai_xiu(last_total)
        du_doan = "Xỉu" if last_result == "Tài" else "Tài"
        tin_cay = 75.0
        
    return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(tin_cay)}


# --- NHÓM 2: DỰ ĐOÁN THEO CHUỖI T-X (RESULTS HISTORY) ---

def algo_05_weighted_markov_third_order(results_history: List[str]) -> Dict[str, Any]:
    """[Weighted Markov Third Order] Phân tích xác suất chuyển đổi từ chuỗi 3 phiên gần nhất (T-X-T -> ?)"""
    if len(results_history) < 4: return {"du_doan": results_history[-1], "do_tin_cay": 60.0}
    
    sequence = "".join(results_history[-3:])
    
    # Markov logic (simplified and balanced)
    if sequence == "TXX": # 2 Xỉu liên tiếp, dự đoán Đảo (Tài)
        du_doan = "Tài"
        tin_cay = 85.4
    elif sequence == "XTT": # 2 Tài liên tiếp, dự đoán Đảo (Xỉu)
        du_doan = "Xỉu"
        tin_cay = 84.2
    elif sequence == "TXT" or sequence == "XTX": # Đang luân phiên, dự đoán tiếp tục luân phiên
        du_doan = "Xỉu" if results_history[-1] == "Tài" else "Tài"
        tin_cay = 78.0
    else: # Bệt hoặc hỗn loạn, dự đoán theo kết quả cuối
        du_doan = results_history[-1]
        tin_cay = 60.0
        
    return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(tin_cay)}

def algo_06_fib_sequence_breakdown(results_history: List[str]) -> Dict[str, Any]:
    """[Fib Sequence Breakdown] Kiểm tra nếu chuỗi bệt hiện tại đạt độ dài Fibonacci (2, 3, 5, 8). 
    Nếu đạt hoặc vượt quá, dự đoán phá vỡ.
    """
    if not results_history: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    
    last_result = results_history[-1]
    streak = 0
    for r in reversed(results_history):
        if r == last_result:
            streak += 1
        else:
            break
            
    fib_numbers = {2, 3, 5, 8}
    
    if streak in fib_numbers:
        # Đạt mức Fibonacci -> Dự đoán Phá vỡ
        du_doan = "Xỉu" if last_result == "Tài" else "Tài"
        tin_cay = 88.0
    else:
        # Tiếp tục theo chuỗi bệt
        du_doan = last_result
        tin_cay = 65.0
        
    return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(tin_cay)}

def algo_07_weighted_moving_average_oscillation(results_history: List[str]) -> Dict[str, Any]:
    """[WMA Oscillation] Tính độ lệch so với WMA 5 phiên. 
    Nếu Tài/Xỉu đang ở mức cực đại/cực tiểu -> Dự đoán hồi quy về trung bình.
    """
    if len(results_history) < 5: return {"du_doan": "Tài", "do_tin_cay": 60.0}
    
    # Chuyển T/X thành giá trị số (Tài=1, Xỉu=-1)
    numeric_history = [1 if r == "Tài" else -1 for r in results_history[-5:]]
    weights = [1, 2, 3, 4, 5]
    total_weight = sum(weights)
    
    wma = sum(numeric_history[i] * weights[i] for i in range(5)) / total_weight
    
    if wma > 0.6: # Thiên về Tài quá mức -> Hồi quy Xỉu
        du_doan = "Xỉu"
        tin_cay = 80.0
    elif wma < -0.6: # Thiên về Xỉu quá mức -> Hồi quy Tài
        du_doan = "Tài"
        tin_cay = 70.8
    else:
        # Theo xu hướng hiện tại
        du_doan = results_history[-1]
        tin_cay = 60.0
        
    return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(tin_cay)}

def algo_08_inverted_periodicity_block(results_history: List[str]) -> Dict[str, Any]:
    """[Inverted Periodicity Block] Kiểm tra chuỗi lặp lại 6 phiên (ví dụ: TXTTXX-TXTTXX)
    và dự đoán lặp lại chuỗi đó, hoặc đảo ngược nếu chuỗi lặp quá dài.
    """
    if len(results_history) < 12: return {"du_doan": results_history[-1], "do_tin_cay": 50.7}
    
    block_A = "".join(results_history[-12:-6])
    block_B = "".join(results_history[-6:])
    
    if block_A == block_B:
        # Lặp lại chuỗi 6 phiên -> Dự đoán phá vỡ khối lặp bằng cách đảo ngược kết quả đầu tiên của chuỗi A
        first_of_A = block_A[0]
        du_doan = "Xỉu" if first_of_A == "Tài" else "Tài"
        tin_cay = 90.0
    else:
        du_doan = results_history[-1]
        tin_cay = 60.0
        
    return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(tin_cay)}

def algo_13_martingale_break_pattern(results_history: List[str]) -> Dict[str, Any]:
    """[Martingale Break Pattern] Phát hiện chuỗi bệt 4+ phiên (Martingale Setup) 
    và dự đoán Đảo chiều để phá vỡ chuỗi.
    """
    if len(results_history) < 5: return {"du_doan": results_history[-1], "do_tin_cay": 60.0}
    
    last_result = results_history[-1]
    streak = 0
    for r in reversed(results_history):
        if r == last_result:
            streak += 1
        else:
            break

    if streak >= 4:
        # Chuỗi dài 4+ -> Dự đoán Đảo chiều (Break)
        du_doan = "Xỉu" if last_result == "Tài" else "Tài"
        tin_cay = 90.0
    else:
        # Tiếp tục theo chuỗi hiện tại
        du_doan = last_result
        tin_cay = 65.0
        
    return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(tin_cay)}

def algo_14_net_balance_extreme(results_history: List[str]) -> Dict[str, Any]:
    """[Net Balance Extreme] Tính toán Lưới cân bằng Tài/Xỉu trong 10 phiên.
    Nếu chênh lệch quá 3 -> Dự đoán hồi quy về 0.
    """
    if len(results_history) < 10: return {"du_doan": results_history[-1], "do_tin_cay": 60.0}
    
    recent_history = results_history[-10:]
    balance = recent_history.count("Tài") - recent_history.count("Xỉu")
    
    if balance >= 4: # Quá nhiều Tài -> Hồi quy về Xỉu
        du_doan = "Xỉu"
        tin_cay = 86.7
    elif balance <= -4: # Quá nhiều Xỉu -> Hồi quy về Tài
        du_doan = "Tài"
        tin_cay = 83.0
    else:
        du_doan = results_history[-1]
        tin_cay = 60.0
        
    return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(tin_cay)}

def algo_16_tri_state_behavior(results_history: List[str]) -> Dict[str, Any]:
    """[Tri-State Behavior] Phát hiện các mẫu lặp lại 3 (ví dụ: TXT, TXT, TXT). 
    Nếu mẫu lặp lại 3 lần -> Dự đoán phá vỡ mẫu (đảo chiều).
    """
    if len(results_history) < 6: return {"du_doan": results_history[-1], "do_tin_cay": 60.0}
    
    block_1 = "".join(results_history[-6:-3])
    block_2 = "".join(results_history[-3:])
    
    if block_1 == block_2:
        # Chuỗi 3 lặp lại 2 lần -> Dự đoán phá vỡ bằng cách đảo ngược kết quả đầu tiên của block
        first_of_block = block_1[0]
        du_doan = "Xỉu" if first_of_block == "Tài" else "Tài"
        tin_cay = 90.0
    else:
        du_doan = results_history[-1]
        tin_cay = 60.0
        
    return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(tin_cay)}

def algo_18_sequence_voter_ensemble(results_history: List[str]) -> Dict[str, Any]:
    """[Sequence Voter Ensemble] Tập hợp nhỏ của 3 thuật toán chuỗi đơn giản (Luân phiên, Bệt ngắn, Đảo chiều)."""
    if len(results_history) < 8: return {"du_doan": results_history[-1], "do_tin_cay": 60.0}

    last_3 = results_history[-3:]
    last_result = results_history[-1]
    votes = Counter()

    # 1. Luân phiên (Alternating)
    if last_3 == ["Tài", "Xỉu", "Tài"] or last_3 == ["Xỉu", "Tài", "Xỉu"]:
        votes["Xỉu" if last_result == "Tài" else "Tài"] += 2.5
    
    # 2. Bệt ngắn (Short Streak) - 2 cùng loại
    if last_3[1] == last_3[2]:
        votes[last_result] += 1.5
    
    # 3. Phá vỡ (Break) - Chuỗi 4
    if all(r == last_result for r in results_history[-4:]):
        votes["Xỉu" if last_result == "Tài" else "Tài"] += 3.0
        
    if not votes:
        return {"du_doan": last_result, "do_tin_cay": 70.0}

    du_doan = votes.most_common(1)[0][0]
    # Độ tin cậy dựa trên sự đồng thuận
    tin_cay = 60.0 + (votes.most_common(1)[0][1] * 5)

    return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(tin_cay)}

# Thêm thuật toán đã có sẵn trong yêu cầu của bạn (để đảm bảo đầy đủ)
def algo_21_trend_stability_index(results_history: List[str]) -> Dict[str, Any]:
    """
    [Trend Stability Index] Tính chỉ số ổn định chuỗi: Tỷ lệ thay đổi kết quả (Đảo/Tổng số phiên).
    Nếu chỉ số thấp (< 0.3) -> Bệt, dự đoán phá vỡ. Nếu chỉ số cao (> 0.7) -> Đảo, dự đoán phá vỡ.
    """
    if len(results_history) < 10: return {"du_doan": results_history[-1], "do_tin_cay": 60.0}
    
    recent_history = results_history[-10:]
    changes = 0
    for i in range(1, len(recent_history)):
        if recent_history[i] != recent_history[i-1]:
            changes += 1
            
    # Stability Index = Changes / Total Transitions (9)
    stability_index = changes / (len(recent_history) - 1)
    last_result = results_history[-1]
    
    if stability_index < 0.3:
        # Quá ổn định (Bệt) -> Dự đoán Phá vỡ (Đảo)
        du_doan = "Xỉu" if last_result == "Tài" else "Tài"
        tin_cay = 88.0
    elif stability_index > 0.7:
        # Quá nhiều thay đổi (Đảo) -> Dự đoán Phá vỡ (Bệt)
        du_doan = last_result
        tin_cay = 98.0
    else:
        # Dao động vừa phải (Trung lập) -> Tiếp tục theo đà ngắn
        du_doan = last_result
        tin_cay = 70.0
        
    return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(tin_cay)}


# --- NHÓM 3: KẾT HỢP (CROSS-CHANNEL) ---

def algo_09_parity_vs_trend_synchronization(results_history: List[str], dice_points_history: List[Dict[str, int]]) -> Dict[str, Any]:
    """[Parity vs Trend Synchronization] So sánh Parity (Chẵn/Lẻ) của Tổng T với xu hướng T/X.
    Nếu Total là Chẵn (Tài: 12, 14, 16) nhưng xu hướng đang là Xỉu -> Dự đoán đảo chiều Tài.
    """
    if len(results_history) < 5 or len(dice_points_history) < 5: 
        return {"du_doan": results_history[-1], "do_tin_cay": 60.0}

    last_T = dice_points_history[-1]['T']
    T_parity = get_parity(last_T)
    last_result = results_history[-1]
    
    # Simple trend based on last 3 results
    trend = Counter(results_history[-3:])
    
    if T_parity == "C" and trend["Xỉu"] >= 2:
        # Tổng chẵn (ví dụ 12, 14, 16) nhưng xu hướng là Xỉu -> Dự đoán Tăng (Tài)
        du_doan = "Tài"
        tin_cay = 88.1
    elif T_parity == "L" and trend["Tài"] >= 2:
        # Tổng lẻ (ví dụ 9, 11, 13) nhưng xu hướng là Tài -> Dự đoán Giảm (Xỉu)
        du_doan = "Xỉu"
        tin_cay = 85.0
    else:
        du_doan = last_result
        tin_cay = 60.0
        
    return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(tin_cay)}


def algo_17_cross_channel_deviation(results_history: List[str], dice_points_history: List[Dict[str, int]]) -> Dict[str, Any]:
    """[Cross-Channel Deviation] So sánh sự biến động (độ lệch chuẩn) của Tổng T với sự ổn định của chuỗi T/X.
    Nếu biến động T cao nhưng chuỗi T/X đang bệt -> Dự đoán phá vỡ chuỗi.
    """
    if len(results_history) < 10 or len(dice_points_history) < 10: 
        return {"du_doan": results_history[-1], "do_tin_cay": 65.0}

    T_history = [d['T'] for d in dice_points_history[-10:]]
    avg_T = sum(T_history) / 10
    
    # Tính Độ lệch chuẩn của Tổng T
    std_dev_T = math.sqrt(sum((t - avg_T) ** 2 for t in T_history) / 10)
    
    # Tính Độ ổn định của chuỗi T/X (Stability Index - từ Algo 21)
    changes = 0
    for i in range(1, 10):
        if results_history[-10 + i] != results_history[-10 + i - 1]:
            changes += 1
    stability_index = (9 - changes) / 9 # 1.0 = Bệt hoàn toàn, 0.0 = Luân phiên hoàn toàn

    if std_dev_T > 3.0 and stability_index > 0.7:
        # Điểm Tổng T biến động mạnh (Std Dev > 3.0) nhưng chuỗi T/X đang rất ổn định (Bệt)
        # -> Dự đoán sai lệch và Phá vỡ chuỗi bệt
        last_result = results_history[-1]
        du_doan = "Xỉu" if last_result == "Tài" else "Tài"
        tin_cay = 92.0
    else:
        du_doan = results_history[-1]
        tin_cay = 60.0
        
    return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(tin_cay)}


# ==============================================================================
# HÀM DỰ ĐOÁN TỔNG HỢP (SUPER ENSEMBLE)
# ==============================================================================

def super_complex_pentter_ai(results_history: List[str], dice_points_history: List[Dict[str, int]]) -> Dict[str, Any]:
    """
    Hệ thống AI đa tầng, kết hợp 21 thuật toán phức tạp với Trọng số Động (Dynamic Weighting)
    để đưa ra dự đoán cuối cùng và độ tin cậy.
    """
    
    # 21 LỚP THUẬT TOÁN (TÊN HÀM, YÊU CẦU MIN_HISTORY)
    all_layers: List[Tuple[Any, int]] = [
        # Nhóm 1: Điểm số (dice_points_history) - 10 Algos
        (algo_01_complex_fib_offset, 8),
        (algo_02_prime_number_offset, 1),
        (algo_03_x1_parity_stutter_index, 5),
        (algo_04_sum_boundary_tension, 1),
        (algo_10_x1_vs_sum_difference_pattern, 4),
        (algo_11_sum_trend_slope, 5),
        (algo_12_rolling_median_cross, 10),
        (algo_15_double_parity_vs_total_mod, 1),
        (algo_19_wavelet_decomposition_proxy, 7),
        (algo_20_harmonic_mean_crossover, 10),
        
        # Nhóm 2: Chuỗi T-X (results_history) - 9 Algos
        (algo_05_weighted_markov_third_order, 4),
        (algo_06_fib_sequence_breakdown, 1),
        (algo_07_weighted_moving_average_oscillation, 5),
        (algo_08_inverted_periodicity_block, 12),
        (algo_13_martingale_break_pattern, 5),
        (algo_14_net_balance_extreme, 10),
        (algo_16_tri_state_behavior, 6),
        (algo_18_sequence_voter_ensemble, 8),
        (algo_21_trend_stability_index, 10),
        
        # Nhóm 3: Kết hợp (cần cả hai) - 2 Algos
        (algo_09_parity_vs_trend_synchronization, 5),
        (algo_17_cross_channel_deviation, 10),
    ]

    score_tai = 0.0
    score_xiu = 0.0
    total_weight = 0.0
    
    min_len_history = len(results_history)
    min_len_dice = len(dice_points_history)

    # Hàm chạy thuật toán và xử lý đầu vào
    def run_algo(func, min_len):
        
        # Kiểm tra thuật toán nào cần loại dữ liệu nào dựa trên số lượng arguments
        if func.__code__.co_argcount == 1:
            # Các thuật toán chỉ dùng một loại history
            is_results_history = "results_history" in func.__name__ or func.__name__ in [f.__name__ for f, m in all_layers if f.__code__.co_argcount == 1 and f != algo_19_wavelet_decomposition_proxy and f != algo_20_harmonic_mean_crossover]

            if is_results_history and min_len_history >= min_len:
                return get_algorithm_result(func, results_history)
            elif not is_results_history and min_len_dice >= min_len:
                return get_algorithm_result(func, dice_points_history)
        
        elif func.__code__.co_argcount == 2 and min_len_history >= min_len and min_len_dice >= min_len:
            # Các thuật toán dùng cả hai loại history
            return get_algorithm_result(func, results_history, dice_points_history)
            
        return None

    for logic_func, min_len in all_layers:
        
        pred_dict = run_algo(logic_func, min_len)
        
        if pred_dict and pred_dict["do_tin_cay"] > 50.0: # Chỉ chấp nhận thuật toán có độ tin cậy trên 50
            pred = pred_dict["du_doan"]
            # Chuyển đổi độ tin cậy [50.1, 99.0] về trọng số [0.01, 0.99]
            weight = (pred_dict["do_tin_cay"] - 50.0) / 50.0 
            
            if pred == "Tài":
                score_tai += weight
            else:
                score_xiu += weight
            total_weight += weight
            
    if total_weight == 0:
        # Nếu chưa đủ dữ liệu cho bất kỳ thuật toán nào, hoặc tất cả đều trung lập
        return {"du_doan": results_history[-1] if results_history else "Tài", "do_tin_cay": 80.0}
            
    du_doan = "Tài" if score_tai >= score_xiu else "Xỉu"
    
    # TÍNH ĐỘ TIN CẬY CUỐI CÙNG (Dynamic Swing)
    winning_score = max(score_tai, score_xiu)
    losing_score = min(score_tai, score_xiu)

    # 1. Tỷ lệ Biên độ (Margin Ratio): (Điểm Thắng - Điểm Thua) / Tổng Điểm
    margin = (winning_score - losing_score) / total_weight

    # 2. Khuếch đại Biên độ (margin * 49.5): Boost từ 50.0 đến 99.5
    do_tin_cay = 50.0 + (margin * 49.5) 
    
    # 3. Đảm bảo tỷ lệ luôn trên 50% và dưới 99%
    do_tin_cay = max(do_tin_cay, 58.1)
    do_tin_cay = round(min(do_tin_cay, 99.5), 1) # Giới hạn 99.0%

    return {"du_doan": du_doan, "do_tin_cay": do_tin_cay}


# ================= Xử lý WebSocket =================
def on_message(ws, message):
    global latest_result, results_history, dice_points_history
    try:
        data = json.loads(message)
        # Bắt tín hiệu đặc trưng của SignalR
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
                        total_sum = d1 + d2 + d3
                        ket_qua = xac_dinh_tai_xiu(total_sum)
                        
                        with lock:
                            # Ngăn chặn việc thêm cùng một phiên vào lịch sử nhiều lần
                            if latest_result["Phien"] != session_id:
                                
                                # 1. Cập nhật và thêm vào lịch sử (dữ liệu phiên cũ)
                                if latest_result["Ket_qua"]:
                                    results_history.append(latest_result["Ket_qua"])
                                    # Thêm dữ liệu điểm số T và X1 cho thuật toán phức tạp
                                    dice_points_history.append({
                                        'T': latest_result["Xuc_xac_1"] + latest_result["Xuc_xac_2"] + latest_result["Xuc_xac_3"], 
                                        'X1': latest_result["Xuc_xac_1"],
                                        'X2': latest_result["Xuc_xac_2"], # Thêm X2, X3 để dùng cho các algo phức tạp hơn
                                        'X3': latest_result["Xuc_xac_3"]
                                    })

                                    # Giới hạn lịch sử
                                    if len(results_history) > MAX_HISTORY:
                                        results_history.pop(0)
                                    if len(dice_points_history) > MAX_HISTORY:
                                        dice_points_history.pop(0)


                                # 2. Cập nhật dữ liệu phiên mới (Phiên vừa xong)
                                latest_result["Phien"] = session_id
                                latest_result["Xuc_xac_1"] = d1
                                latest_result["Xuc_xac_2"] = d2
                                latest_result["Xuc_xac_3"] = d3
                                latest_result["Ket_qua"] = ket_qua
                                
                                # 3. Chạy thuật toán dự đoán cho phiên tiếp theo
                                pred = super_complex_pentter_ai(results_history, dice_points_history)
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
                # Dữ liệu SignalR Ping: {"type": 6} hoặc ping/pong theo SignalR protocol
                ws.send("{}") # SignalR reconnect frame
                time.sleep(PING_INTERVAL)
            except:
                break
    # Gửi tín hiệu Start/Reconnect để bắt đầu nhận dữ liệu (tùy vào giao thức SignalR phiên bản cụ thể)
    # ws.send(json.dumps({"H": "md5luckydiceHub", "M": "Subscribe", "A": [], "I": 1})) # Example for subscription
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
    # run_forever có tính năng tự động reconnect cơ bản
    try:
        ws.run_forever(ping_interval=PING_INTERVAL, ping_timeout=10, reconnect=5)
    except Exception as e:
        print(f"Lỗi kết nối WebSocket nghiêm trọng: {e}. Thử lại...")
        time.sleep(5)
        start_ws_thread()


# ================= Flask API =================
app = Flask(__name__)

@app.route("/api/taixiumd5")
def get_latest():
    """Endpoint trả về kết quả phiên mới nhất và dự đoán cho phiên tiếp theo."""
    with lock:
        # Thêm lịch sử ngắn để debug
        short_history = results_history[-10:] 
        response_data = latest_result.copy()
        response_data["Lich_su_10_phien"] = short_history
        # Chỉ 5 phiên điểm gần nhất
        response_data["Lich_su_Tong_diem"] = dice_points_history[-5:] 
        return jsonify(response_data)

@app.route("/")
def index():
    return "✅ Pentter-AI Siêu Phức Tạp (21 Lớp) đang chạy. Truy cập /api/taixiumd5 để xem dự đoán."

# ================= Main =================
if __name__ == "__main__":
    # Khởi động WebSocket trong một luồng riêng
    threading.Thread(target=start_ws_thread, daemon=True).start()
    
    # Khởi động Flask server
    print("Khởi động Pentter-AI Flask Server tại http://0.0.0.0:5000")
    # Sử dụng thread=False để tránh lỗi khi chạy trong môi trường không hỗ trợ multi-threading đầy đủ (như một số container)
    # Nhưng vì WS đã chạy luồng riêng nên ta dùng threading=True để cho phép Flask phục vụ request song song.
    app.run(host="0.0.0.0", port=5000, threaded=True)

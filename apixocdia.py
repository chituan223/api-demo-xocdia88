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
    "Du_doan": "Đang phân tích...",
    "Do_tin_cay": 0
}
lock = threading.Lock()
history = []
MAX_HISTORY = 50

# ================= Hàm dự đoán cơ bản =================
def get_tai_xiu(d1, d2, d3):
    total = d1 + d2 + d3
    return "Xỉu" if total <= 10 else "Tài"

# ================= 10 Thuật toán dự đoán =================
def algo1_weightedRecent(hist):
    if not hist: return "Tài"
    t = sum((i+1)/len(hist) for i, v in enumerate(hist) if v=="Tài")
    x = sum((i+1)/len(hist) for i, v in enumerate(hist) if v=="Xỉu")
    return "Tài" if t >= x else "Xỉu"

def algo2_expDecay(hist, decay=0.6):
    if not hist: return "Tài"
    t=x=w=0; w=1
    for v in reversed(hist):
        if v=="Tài": t+=w
        else: x+=w
        w*=decay
    return "Tài" if t>x else "Xỉu"

def algo3_longChainReverse(hist,k=3):
    if not hist: return "Tài"
    last=hist[-1]; chain=1
    for v in reversed(hist[:-1]):
        if v==last: chain+=1
        else: break
    if chain>=k:
        return "Xỉu" if last=="Tài" else "Tài"
    return last

def algo4_windowMajority(hist,window=5):
    if not hist: return "Tài"
    win=hist[-window:] if len(hist)>=window else hist
    return "Tài" if win.count("Tài")>=len(win)/2 else "Xỉu"

def algo5_alternation(hist):
    if len(hist)<4: return "Tài"
    flips=sum(1 for i in range(1,4) if hist[-i]!=hist[-i-1])
    if flips>=3:
        return "Xỉu" if hist[-1]=="Tài" else "Tài"
    return hist[-1]

def algo6_patternRepeat(hist):
    L=len(hist)
    if L<4: return "Tài"
    for length in range(2,min(6,L//2)+1):
        a="".join(hist[-length:])
        b="".join(hist[-2*length:-length])
        if a==b: return hist[-length]
    return algo4_windowMajority(hist,4)

def algo7_mirror(hist):
    if len(hist)<8: return hist[-1] if hist else "Tài"
    return "Xỉu" if hist[-4:]==hist[-8:-4] and hist[-1]=="Tài" else hist[-1]

def algo8_entropy(hist):
    if not hist: return "Tài"
    t=hist.count("Tài")
    x=len(hist)-t
    diff=abs(t-x)
    if diff<=len(hist)//5: return "Xỉu" if hist[-1]=="Tài" else "Tài"
    return "Xỉu" if t>x else "Tài"

def algo9_momentum(hist):
    if len(hist)<2: return "Tài"
    score=sum(1 if hist[i]==hist[i-1] else -1 for i in range(1,len(hist)))
    return hist[-1] if score>0 else ("Xỉu" if hist[-1]=="Tài" else "Tài")

def algo10_freqRatio(hist):
    if not hist: return "Tài"
    ratio=hist.count("Tài")/len(hist)
    if ratio>0.62: return "Xỉu"
    if ratio<0.38: return "Tài"
    return hist[-1]

algos=[algo1_weightedRecent,algo2_expDecay,algo3_longChainReverse,algo4_windowMajority,
       algo5_alternation,algo6_patternRepeat,algo7_mirror,algo8_entropy,algo9_momentum,algo10_freqRatio]

# ================= Hàm hybrid dự đoán + độ tin cậy =================
def hybrid_predict(hist, last_dice_sum):
    if not hist: return {"prediction":"Tài","confidence":50}
    scoreT=scoreX=0
    votes=[]
    for fn in algos:
        v=fn(hist)
        votes.append(v)
        if v=="Tài": scoreT+=1
        else: scoreX+=1
    pred="Tài" if scoreT>=scoreX else "Xỉu"
    base_conf = (max(scoreT,scoreX)/len(algos))*100
    dist = abs(last_dice_sum - 10)
    confidence = min(100, max(50, int(base_conf + dist*5)))  # Biến động theo tổng xúc xắc
    return {"prediction":pred,"confidence":confidence,"votes":votes}

# ================= Xử lý message WebSocket =================
def on_message(ws,message):
    global latest_result,history
    try:
        data=json.loads(message)
        if isinstance(data,dict) and "M" in data:
            for m_item in data["M"]:
                if "M" in m_item and m_item["M"]=="Md5sessionInfo":
                    session_info=m_item["A"][0]
                    session_id=session_info.get("SessionID")
                    result=session_info.get("Result",{})
                    d1=result.get("Dice1",-1)
                    d2=result.get("Dice2",-1)
                    d3=result.get("Dice3",-1)
                    if d1!=-1 and d2!=-1 and d3!=-1:
                        tx=get_tai_xiu(d1,d2,d3)
                        total=d1+d2+d3
                        with lock:
                            latest_result["Phien"]=session_id
                            latest_result["Xuc_xac_1"]=d1
                            latest_result["Xuc_xac_2"]=d2
                            latest_result["Xuc_xac_3"]=d3
                            # Cập nhật lịch sử
                            history.append(tx)
                            if len(history)>MAX_HISTORY: history.pop(0)
                            # Dự đoán
                            pred=hybrid_predict(history,total)
                            latest_result["Du_doan"]=pred["prediction"]
                            latest_result["Do_tin_cay"]=pred["confidence"]
    except Exception as e:
        print("Lỗi xử lý message:",e)

def on_error(ws,error): print("WebSocket lỗi:",error)
def on_close(ws,close_status_code,close_msg):
    print("WebSocket đóng, reconnect sau 5s...")
    time.sleep(5)
    start_ws_thread()
def on_open(ws):
    def ping(): 
        while True:
            try:
                ping_msg=json.dumps({"M":"PingPong","H":"md5luckydiceHub","I":0})
                ws.send(ping_msg)
                time.sleep(PING_INTERVAL)
            except: break
    threading.Thread(target=ping,daemon=True).start()

def start_ws_thread():
    ws=websocket.WebSocketApp(
        WS_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )
    ws.run_forever(ping_interval=10,ping_timeout=5)

# ================= Flask API =================
app=Flask(__name__)

@app.route("/api/taixiumd5")
def get_latest():
    with lock: return jsonify(latest_result)

@app.route("/")
def index():
    return "✅ API Tài Xỉu Phiên + Xúc xắc + Dự đoán đang chạy | /api/taixiumd5"

# ================= Main =================
if __name__=="__main__":
    threading.Thread(target=start_ws_thread,daemon=True).start()
    app.run(host="0.0.0.0",port=5000)

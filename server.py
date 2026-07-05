from flask import Flask, render_template, jsonify, request
from datetime import datetime
from pathlib import Path
import json
import os
import time
import hmac
import base64
import hashlib
import requests

app = Flask(__name__, static_folder=".", static_url_path="")

BASE_DIR = Path(__file__).resolve().parent

SETTINGS_FILE = BASE_DIR / "settings.json"
HISTORY_FILE = BASE_DIR / "history.json"

DEFAULT_SETTINGS = {
    "available_balance_usdt": 9.44,
    "capital_percent": 65,
    "main_asset": "ETH",
    "quote_asset": "USDT",
    "strategy_mode": "spot_administrable",
    "min_risk_reward": 1.7,
    "max_stop_loss_percent": 2.5,
    "target_gain_percent": 4.0,
    "allow_futures": False,
    "allow_margin": False,
    "allow_leverage": False
}

def read_json(path, default):
    if not path.exists():
        path.write_text(json.dumps(default, indent=2, ensure_ascii=False), encoding="utf-8")
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def write_json(path, payload):
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

def get_settings():
    settings = read_json(SETTINGS_FILE, DEFAULT_SETTINGS.copy())
    for key, value in DEFAULT_SETTINGS.items():
        settings.setdefault(key, value)
    return settings

def get_history():
    return read_json(HISTORY_FILE, [])

def save_history(row):
    history = get_history()
    history.insert(0, row)
    history = history[:250]
    write_json(HISTORY_FILE, history)

def okx_public_ticker(inst_id="ETH-USDT"):
    url = "https://www.okx.com/api/v5/market/ticker"
    response = requests.get(url, params={"instId": inst_id}, timeout=12)
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data", [{}])[0]
    return {
        "price": float(data.get("last", 0)),
        "open_24h": float(data.get("open24h", 0)),
        "high_24h": float(data.get("high24h", 0)),
        "low_24h": float(data.get("low24h", 0)),
        "volume_24h": float(data.get("volCcy24h", 0)),
        "timestamp": int(data.get("ts", time.time() * 1000))
    }

def okx_private_balance():
    api_key = os.getenv("OKX_API_KEY", "")
    secret_key = os.getenv("OKX_SECRET_KEY", "")
    passphrase = os.getenv("OKX_PASSPHRASE", "")

    if not api_key or not secret_key or not passphrase:
        return None

    timestamp = datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
    method = "GET"
    request_path = "/api/v5/account/balance?ccy=USDT"
    message = timestamp + method + request_path
    signature = base64.b64encode(
        hmac.new(secret_key.encode(), message.encode(), hashlib.sha256).digest()
    ).decode()

    headers = {
        "OK-ACCESS-KEY": api_key,
        "OK-ACCESS-SIGN": signature,
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS-PASSPHRASE": passphrase,
        "Content-Type": "application/json"
    }

    url = "https://www.okx.com" + request_path
    response = requests.get(url, headers=headers, timeout=12)
    response.raise_for_status()
    payload = response.json()

    try:
        details = payload["data"][0]["details"]
        for item in details:
            if item.get("ccy") == "USDT":
                return float(item.get("availBal", 0))
    except Exception:
        return None

    return None

def build_analysis(settings):
    ticker = okx_public_ticker("ETH-USDT")
    price = ticker["price"]

api_balance = None
balance_source = "Manual"
api_connected = False

try:
    api_balance = okx_private_balance()
    if api_balance is not None:
        balance_source = "OKX API"
        api_connected = True
except Exception:
    api_balance = None

available_balance = api_balance if api_balance is not None else float(settings["available_balance_usdt"])
    capital_percent = max(0, min(100, float(settings["capital_percent"])))
    operative_capital = round(available_balance * (capital_percent / 100), 2)

    open_24h = ticker["open_24h"]
    high_24h = ticker["high_24h"]
    low_24h = ticker["low_24h"]
    volume_24h = ticker["volume_24h"]

    change_24h = ((price - open_24h) / open_24h * 100) if open_24h else 0
    support_1 = round(low_24h + ((price - low_24h) * 0.35), 2)
    support_2 = round(low_24h, 2)
    resistance_1 = round(price + ((high_24h - price) * 0.35), 2)
    resistance_2 = round(high_24h, 2)

    pullback_entry_low = round(support_1 * 0.997, 2)
    pullback_entry_high = round(support_1 * 1.004, 2)
    stop_loss = round(pullback_entry_low * (1 - settings["max_stop_loss_percent"] / 100), 2)
    target = round(pullback_entry_high * (1 + settings["target_gain_percent"] / 100), 2)

    risk_unit = max(pullback_entry_high - stop_loss, 0.01)
    reward_unit = max(target - pullback_entry_high, 0.01)
    risk_reward = round(reward_unit / risk_unit, 2)

    near_resistance = price >= resistance_1 * 0.995
    near_support = pullback_entry_low <= price <= pullback_entry_high
    positive_trend = change_24h > 0.35
    negative_trend = change_24h < -1.25
    volume_label = "Alto" if volume_24h > 1500000000 else "Moderado" if volume_24h > 500000000 else "Bajo"

    if negative_trend:
        risk = "Alto"
        recommendation = "ESPERAR"
        decision = "No comprar. El precio viene con presión bajista y conviene proteger capital."
        suggested_capital = 0
        entry_range = "No aplica"
    elif near_support and risk_reward >= settings["min_risk_reward"] and volume_label != "Bajo":
        risk = "Medio"
        recommendation = "COMPRAR PARCIAL"
        decision = "Comprar solo una posición parcial, respetando el stop loss."
        suggested_capital = round(operative_capital * 0.70, 2)
        entry_range = f"{pullback_entry_low} - {pullback_entry_high} USDT"
    elif positive_trend and not near_resistance and risk_reward >= settings["min_risk_reward"]:
        risk = "Medio"
        recommendation = "ESPERAR PULLBACK"
        decision = "Esperar un retroceso. La tendencia mejora, pero la entrada actual no es óptima."
        suggested_capital = 0
        entry_range = f"{pullback_entry_low} - {pullback_entry_high} USDT"
    else:
        risk = "Medio-Alto" if near_resistance else "Medio"
        recommendation = "ESPERAR"
        decision = "Esperar. No hay ventaja suficiente para entrar con pérdida controlada."
        suggested_capital = 0
        entry_range = "No aplica"

    scenario = {
        "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "price": round(price, 2),
        "available_balance": round(available_balance, 2),
        "balance_source": balance_source,
        "api_connected": api_connected,
        "capital_percent": capital_percent,
        "operative_capital": operative_capital,
        "suggested_capital": min(suggested_capital, operative_capital),
        "recommendation": recommendation,
        "risk": risk,
        "trend": "Alcista moderada" if positive_trend else "Bajista" if negative_trend else "Neutral",
        "change_24h": round(change_24h, 2),
        "support_1": support_1,
        "support_2": support_2,
        "resistance_1": resistance_1,
        "resistance_2": resistance_2,
        "breakout_pullback": "Pullback preferible" if not near_support else "Pullback en zona operable",
        "volume": volume_label,
        "sentiment": "Cautela compradora" if positive_trend else "Defensivo" if negative_trend else "Neutral",
        "entry_range": entry_range,
        "stop_loss": stop_loss if entry_range != "No aplica" else "No aplica",
        "target": target if entry_range != "No aplica" else "No aplica",
        "risk_reward": risk_reward,
        "decision": decision,
        "notes": "Estrategia Spot administrable: buscar ganancia con pérdida limitada; sin futuros, margen ni apalancamiento."
    }

    return scenario

@app.route("/")
def index():
    return app.send_static_file("index.html")

@app.route("/api/settings", methods=["GET", "POST"])
def settings_api():
    if request.method == "POST":
        current = get_settings()
        incoming = request.json or {}
        for field in ["available_balance_usdt", "capital_percent", "min_risk_reward", "max_stop_loss_percent", "target_gain_percent"]:
            if field in incoming:
                current[field] = float(incoming[field])
        write_json(SETTINGS_FILE, current)
        return jsonify(current)
    return jsonify(get_settings())

@app.route("/api/dashboard")
def dashboard_api():
    settings = get_settings()
    try:
        analysis = build_analysis(settings)
        save_history({
            "fecha_hora": analysis["datetime"],
            "precio_eth": analysis["price"],
            "recomendacion": analysis["recommendation"],
            "riesgo": analysis["risk"],
            "entrada_sugerida": analysis["entry_range"],
            "stop_loss": analysis["stop_loss"],
            "objetivo": analysis["target"],
            "capital_operativo": analysis["operative_capital"],
            "capital_sugerido": analysis["suggested_capital"],
            "observaciones": analysis["decision"]
        })
        return jsonify({"ok": True, "data": analysis})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

@app.route("/api/history")
def history_api():
    return jsonify(get_history())

@app.route("/api/history/clear", methods=["POST"])
def clear_history_api():
    write_json(HISTORY_FILE, [])
    return jsonify({"ok": True})

@app.route("/health")
def health():
    return jsonify({
        "ok": True,
        "service": "CriptoDesk",
        "status": "live",
        "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

@app.route("/api/okx/status")
def okx_status():
    try:
        balance = okx_private_balance()

        if balance is None:
            return jsonify({
                "ok": False,
                "connected": False,
                "balance_source": "Manual",
                "message": "API de OKX no disponible o credenciales incompletas."
            })

        return jsonify({
            "ok": True,
            "connected": True,
            "balance_source": "OKX API",
            "available_balance": round(balance, 2),
            "message": "API de OKX conectada correctamente."
        })

    except Exception as exc:
        return jsonify({
            "ok": False,
            "connected": False,
            "balance_source": "Manual",
            "error": str(exc)
        }), 500
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))

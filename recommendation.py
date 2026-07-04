from typing import Any, Dict

from config import settings
from risk import risk_label

def decision_from_score(score: int) -> str:
    if score >= 80:
        return "COMPRAR"
    if score >= 60:
        return "VIGILAR"
    if score >= 40:
        return "ESPERAR"
    return "NO OPERAR"

def build_recommendation(portfolio: Dict[str, Any]) -> Dict[str, Any]:
    eth = next((a for a in portfolio.get("assets", []) if a.get("sym") == "ETH"), {})
    score = int(eth.get("score", 50))
    decision = decision_from_score(score)
    capital = float(portfolio.get("cappedCapital", 0.0) or 0.0)
    buy_amount = min(capital * 0.35, settings.max_operating_capital) if decision == "COMPRAR" else 0.0
    if decision == "COMPRAR":
        reason = "La calidad de oportunidad es favorable. Comprar solo una parte del capital operativo."
    elif decision == "VIGILAR":
        reason = "El mercado mejora, pero todavía no conviene abrir posición sin confirmación adicional."
    elif decision == "ESPERAR":
        reason = "No hay ventaja suficiente. Se conserva el capital disponible."
    else:
        reason = "El riesgo es alto para una estrategia Spot conservadora."
    return {
        "decision": decision,
        "confidence": score,
        "opportunityIndex": score,
        "risk": risk_label(score),
        "buyAmountUsdt": round(buy_amount, 2),
        "reserveUsdt": round(max(capital - buy_amount, 0.0), 2),
        "takeProfitPct": 3.0 if buy_amount > 0 else None,
        "stopLossPct": 2.0 if buy_amount > 0 else None,
        "reason": reason,
    }

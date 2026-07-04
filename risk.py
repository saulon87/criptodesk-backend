def risk_label(score: int) -> str:
    if score >= 80:
        return "BAJO"
    if score >= 60:
        return "MEDIO"
    return "ALTO"

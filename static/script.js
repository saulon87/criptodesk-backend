const $ = (id) => document.getElementById(id);

const DEFAULT_REFRESH_MS = 120000;

function setText(id, value) {
  const element = $(id);
  if (element) element.textContent = value;
}

function safeNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function formatMoney(value) {
  if (value === "No aplica" || value === null || value === undefined) return "No aplica";
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  return `${number.toFixed(2)} USDT`;
}

function formatPercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return `${number.toFixed(2)}%`;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();

  let payload = {};
  try {
    payload = text ? JSON.parse(text) : {};
  } catch (error) {
    throw new Error("La respuesta del servidor no tiene formato JSON válido.");
  }

  if (!response.ok) {
    throw new Error(payload.error || `Error HTTP ${response.status}`);
  }

  return payload;
}

async function loadSettings() {
  const settings = await fetchJson("/api/settings");

  if ($("balanceInput")) {
    $("balanceInput").value = safeNumber(settings.available_balance_usdt, 9.44);
  }

  if ($("percentInput")) {
    $("percentInput").value = safeNumber(settings.capital_percent, 65);
  }

  updateLocalCapitalPreview();
}

function updateLocalCapitalPreview() {
  const balance = safeNumber($("balanceInput")?.value, 0);
  const percent = Math.max(0, Math.min(100, safeNumber($("percentInput")?.value, 65)));
  const operativeCapital = balance * (percent / 100);

  setText("operativeCapital", formatMoney(operativeCapital));
}

async function saveSettings() {
  const balance = Math.max(0, safeNumber($("balanceInput")?.value, 0));
  const percent = Math.max(0, Math.min(100, safeNumber($("percentInput")?.value, 65)));

  if ($("balanceInput")) $("balanceInput").value = balance.toFixed(2);
  if ($("percentInput")) $("percentInput").value = percent.toFixed(0);

  await fetchJson("/api/settings", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      available_balance_usdt: balance,
      capital_percent: percent
    })
  });

  await loadDashboard();
}

function applyRiskClass(riskValue) {
  const riskElement = $("risk");
  if (!riskElement) return;

  riskElement.classList.remove("risk-low", "risk-medium", "risk-high");

  const risk = String(riskValue || "").toLowerCase();

  if (risk.includes("alto")) {
    riskElement.classList.add("risk-high");
  } else if (risk.includes("bajo")) {
    riskElement.classList.add("risk-low");
  } else {
    riskElement.classList.add("risk-medium");
  }
}

function renderDashboard(data) {
  setText("operativeCapital", formatMoney(data.operative_capital));
  setText("availableBalance", formatMoney(data.available_balance));
  setText("balanceSource", data.balance_source || "Manual");
  setText("apiStatus", data.api_connected ? "OKX conectado" : "OKX no conectado");
  
  setText("recommendation", data.recommendation || "--");
  setText("decisionText", data.decision || "--");

  setText("price", formatMoney(data.price));
  setText("trend", data.trend || "--");
  setText("change24h", formatPercent(data.change_24h));

  setText("risk", data.risk || "--");
  applyRiskClass(data.risk);

  setText("volume", data.volume || "--");
  setText("sentiment", data.sentiment || "--");

  setText("support1", formatMoney(data.support_1));
  setText("support2", formatMoney(data.support_2));
  setText("resistance1", formatMoney(data.resistance_1));
  setText("resistance2", formatMoney(data.resistance_2));

  setText("suggestedCapital", formatMoney(data.suggested_capital));
  setText("entryRange", data.entry_range || "No aplica");
  setText("stopLoss", formatMoney(data.stop_loss));
  setText("target", formatMoney(data.target));
  setText("riskReward", data.risk_reward ?? "--");

  setText("breakoutPullback", data.breakout_pullback || "--");
  setText("notes", data.notes || "--");
}

async function loadDashboard() {
  try {
    setText("decisionText", "Consultando mercado y actualizando estrategia...");
    const payload = await fetchJson("/api/dashboard");

    if (!payload.ok) {
      throw new Error(payload.error || "No fue posible actualizar el dashboard.");
    }

    renderDashboard(payload.data);
    await loadHistory();
  } catch (error) {
    setText("decisionText", `No fue posible actualizar el mercado: ${error.message}`);
  }
}

async function loadHistory() {
  const history = await fetchJson("/api/history");
  const body = $("historyBody");

  if (!body) return;

  body.innerHTML = "";

  if (!Array.isArray(history) || history.length === 0) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="9">Sin registros acumulados todavía.</td>`;
    body.appendChild(tr);
    return;
  }

  history.forEach((row) => {
    const tr = document.createElement("tr");

    tr.innerHTML = `
      <td>${row.fecha_hora ?? "--"}</td>
      <td>${row.precio_eth ?? "--"}</td>
      <td>${row.recomendacion ?? "--"}</td>
      <td>${row.riesgo ?? "--"}</td>
      <td>${row.entrada_sugerida ?? "No aplica"}</td>
      <td>${row.stop_loss ?? "No aplica"}</td>
      <td>${row.objetivo ?? "No aplica"}</td>
      <td>${row.capital_sugerido ?? "--"}</td>
      <td>${row.observaciones ?? "--"}</td>
    `;

    body.appendChild(tr);
  });
}

async function clearHistory() {
  await fetchJson("/api/history/clear", {method: "POST"});
  await loadHistory();
}

function registerEvents() {
  $("saveSettingsBtn")?.addEventListener("click", saveSettings);
  $("refreshBtn")?.addEventListener("click", loadDashboard);
  $("clearHistoryBtn")?.addEventListener("click", clearHistory);

  $("balanceInput")?.addEventListener("input", updateLocalCapitalPreview);
  $("percentInput")?.addEventListener("input", updateLocalCapitalPreview);
}

async function registerServiceWorker() {
  if ("serviceWorker" in navigator) {
    try {
      await navigator.serviceWorker.register("/static/sw.js");
    } catch (error) {
      console.warn("No se pudo registrar el service worker:", error);
    }
  }
}

async function init() {
  registerEvents();
  await registerServiceWorker();

  try {
    await loadSettings();
    await loadDashboard();
  } catch (error) {
    setText("decisionText", `Error inicializando CriptoDesk: ${error.message}`);
  }

  setInterval(loadDashboard, DEFAULT_REFRESH_MS);
}

document.addEventListener("DOMContentLoaded", init);

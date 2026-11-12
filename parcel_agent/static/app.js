"use strict";

const state = { parcels: [], demo: false, country: "all", status: null, poller: null, busy: false, undo: null };
const $ = (selector) => document.querySelector(selector);
const icons = () => window.lucide?.createIcons();
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
const icon = (name) => `<i data-lucide="${name}"></i>`;

async function api(path, method = "GET") {
  const response = await fetch(path, { method, headers: method === "POST" ? { "X-Parcel-Request": "1" } : {} });
  let result;
  try { result = await response.json(); } catch { throw new Error("El servidor no ha devuelto una respuesta valida."); }
  if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "No se pudo completar la operacion.");
  return result;
}

function message(text, error = false) {
  $("#sync-message").textContent = text;
  $("#sync-message").classList.toggle("error", error);
}

function toast(text, undo = null) {
  state.undo = undo;
  $("#toast-text").textContent = text;
  $("#undo-button").hidden = !undo;
  $("#toast").hidden = false;
}

function daysUntil(deadline) {
  if (!deadline) return null;
  const parts = new Intl.DateTimeFormat("en", { timeZone: "Europe/Paris", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
  const part = (type) => parts.find((item) => item.type === type).value;
  const todayIso = `${part("year")}-${part("month")}-${part("day")}`;
  return Math.round((Date.parse(`${deadline}T12:00:00Z`) - Date.parse(`${todayIso}T12:00:00Z`)) / 86400000);
}

function deadlineMarkup(deadline) {
  if (!deadline) return `<span class="deadline">${icon("calendar-days")} Fecha limite no indicada</span>`;
  const days = daysUntil(deadline);
  const formatted = new Intl.DateTimeFormat("es", { day: "numeric", month: "short", timeZone: "Europe/Paris" }).format(new Date(`${deadline}T12:00:00Z`));
  const prefix = days < 0 ? "Plazo indicado vencido" : days === 0 ? "Ultimo dia: hoy" : days === 1 ? "Hasta manana" : "Hasta el";
  return `<span class="deadline ${days < 0 ? "expired" : days <= 1 ? "urgent" : ""}">${icon(days <= 1 ? "clock-3" : "calendar-days")} ${prefix} · ${escapeHtml(formatted)}</span>`;
}

function card(parcel) {
  const hasDocuments = Boolean(parcel.attachments?.length);
  const hasCode = Boolean(parcel.pickup_code);
  const location = parcel.location || "Punto de recogida sin indicar";
  const mapUrl = parcel.address ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent([parcel.address, parcel.country].filter(Boolean).join(", "))}` : null;
  const sourceUrl = parcel.message_id ? `https://mail.google.com/mail/u/0/#all/${encodeURIComponent(parcel.message_id)}` : null;
  return `<article class="parcel" data-id="${escapeHtml(parcel.id)}" data-country="${escapeHtml(parcel.country || "")}">
    <div class="parcel-symbol">${icon(hasCode ? "ticket" : "package-open")}</div>
    <div class="parcel-details"><h2>${escapeHtml(parcel.title)}</h2>${deadlineMarkup(parcel.deadline)}
      ${parcel.needs_review ? '<p class="review-note">Sin seguimiento identificado · Comprueba el correo</p>' : ""}
      ${sourceUrl ? `<a class="source-link" href="${sourceUrl}" target="_blank" rel="noopener noreferrer">${icon("mail")} Correo original ${icon("arrow-up-right")}</a>` : ""}
    </div>
    <div class="parcel-place"><p class="location-label"><span>PUNTO DE RECOGIDA</span>${parcel.country ? `<span class="country-tag" data-country="${escapeHtml(parcel.country)}"><span class="country-flag" aria-hidden="true"></span>${parcel.country === "FR" ? "Francia" : parcel.country === "CH" ? "Suiza" : escapeHtml(parcel.country)}</span>` : ""}</p><p class="location-name">${escapeHtml(location)}</p><p class="address">${escapeHtml(parcel.address || "Direccion no indicada en el correo")}</p>${mapUrl ? `<a class="map-link" href="${mapUrl}" target="_blank" rel="noopener noreferrer">Abrir mapa ${icon("arrow-up-right")}</a>` : ""}</div>
    <div class="parcel-actions">
      ${hasDocuments || hasCode ? `<button class="button secondary document-button" data-id="${escapeHtml(parcel.id)}">${icon(hasCode && !hasDocuments ? "key-round" : "scan-line")} ${hasCode && !hasDocuments ? "Ver codigo" : "Ver documentos"}</button>` : '<p class="missing-document">Sin QR ni adjunto en este correo. Consulta el original.</p>'}
      <button class="collect-button" data-id="${escapeHtml(parcel.id)}">${icon("check")} Ya lo he recogido</button>
    </div>
  </article>`;
}

function render() {
  const visible = state.parcels.filter((parcel) => state.country === "all" || parcel.country === state.country)
    .sort((first, second) => (first.deadline || "9999").localeCompare(second.deadline || "9999"));
  $("#parcel-count").textContent = String(visible.length);
  $("#parcel-list").innerHTML = visible.map(card).join("");
  $("#empty-state").hidden = visible.length > 0;
  $("#demo-band").hidden = !state.demo;
  $("#demo-button").hidden = state.demo;
  const count = state.parcels.length;
  $("#heading-note").textContent = count ? `${count} ${count === 1 ? "paquete te espera" : "paquetes te esperan"}. Tu proxima parada, aqui.` : "Nada pendiente. Todo en su sitio.";
  $("#empty-title").textContent = state.country !== "all" ? "Nada pendiente por aqui." : "Por aqui, todo recogido.";
  $("#empty-copy").textContent = state.country !== "all" ? "No hay recogidas en este pais. Puedes consultar el resto en Todos." : state.status?.gmail_connected ? "Sincroniza para comprobar si hay nuevas recogidas." : "Conecta tu Gmail para consultar tus recogidas, o echa un vistazo con datos de ejemplo.";
  document.querySelectorAll(".filter").forEach((button) => {
    const active = button.dataset.country === state.country;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  renderConnection();
  icons();
}

function renderConnection() {
  if (!state.status) return;
  const connected = state.status.gmail_connected;
  $("#connection-title").textContent = connected ? "Gmail conectado." : "Tu bandeja, conectada contigo.";
  $("#connection-copy").textContent = connected ? "Solo lectura · Sincronizacion manual" : "Gmail sin conectar";
  $("#connect-button").hidden = connected;
  $("#sync-button").disabled = state.busy || state.status.sync.running || state.demo;
  $("#connect-button").disabled = state.busy || state.status.sync.running;
  $("#sync-button span").textContent = state.status.sync.running ? "Sincronizando…" : "Sincronizar Gmail";
  $("#sync-button svg")?.classList.toggle("spinning", state.status.sync.running);
}

async function loadParcels() {
  state.parcels = await api(state.demo ? "/api/demo" : "/api/parcels");
  render();
}

function showSyncResult(sync) {
  if (sync.running) {
    message(`Revisando correos · ${sync.processed} procesados${sync.failed ? ` · ${sync.failed} sin procesar` : ""}`);
  } else if (sync.error) {
    message(`${sync.error}${sync.failed ? ` ${sync.failed} correo(s) pendiente(s) de procesar.` : ""}`, true);
  } else if (sync.processed || sync.limited) {
    message(`${sync.processed} correos procesados.${sync.limited ? " Quedan correos por revisar: vuelve a sincronizar." : " Bandeja actualizada."}`);
  }
}

async function refreshStatus() {
  state.status = await api("/api/status");
  renderConnection();
  if (state.status.credential_error) message(state.status.credential_error, true);
  if (state.status.sync.running && !state.poller) {
    state.poller = window.setInterval(async () => {
      try {
        state.status = await api("/api/status");
        renderConnection();
        showSyncResult(state.status.sync);
        if (!state.status.sync.running) {
          window.clearInterval(state.poller);
          state.poller = null;
          await loadParcels();
        }
      } catch (error) {
        window.clearInterval(state.poller);
        state.poller = null;
        message(error.message, true);
      }
    }, 1800);
  }
}

function showSettings() {
  if (!state.status) return;
  $("#setup-status").innerHTML = [
    ["Google OAuth", state.status.google_configured ? "Configurado" : "Falta credentials.json"],
    ["Gmail", state.status.gmail_connected ? "Conectado · Solo lectura" : "Sin conectar"],
    ["IA externa", state.status.ai_configured ? "Habilitada" : "Desactivada o sin clave"],
  ].map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("");
  $("#disconnect-button").disabled = !state.status.gmail_connected || state.status.sync.running || state.busy;
  $("#settings-dialog").showModal();
}

function attachmentUrl(attachment) {
  return attachment.demo ? "/api/demo/qr" : `/api/attachments/${encodeURIComponent(attachment.message_id)}/${encodeURIComponent(attachment.part_id)}`;
}

function showDocument(parcel) {
  const documents = parcel.attachments || [];
  $("#document-title").textContent = parcel.demo ? "Ejemplo · No valido para recoger" : "Documentos del correo";
  $("#document-content").innerHTML = `
    ${parcel.pickup_code ? `<div class="code-box"><strong>${escapeHtml(parcel.pickup_code)}</strong><button class="button secondary" id="copy-code">${icon("copy")} Copiar codigo</button></div>` : ""}
    ${documents.length ? `<div class="document-links">${documents.map((document, index) => `<button class="button secondary select-document" data-index="${index}">${icon(document.mime_type === "application/pdf" ? "file-text" : "image")} ${escapeHtml(document.filename)}</button>`).join("")}</div><div id="document-preview"></div><p class="document-note">${parcel.demo ? "QR ficticio. No corresponde a ningun paquete real." : "Adjuntos originales del correo. Pueden incluir logos u otros documentos; comprueba que el codigo es para recoger."}</p>` : ""}`;
  if (parcel.pickup_code) $("#copy-code").onclick = async () => {
    try { await navigator.clipboard.writeText(parcel.pickup_code); $("#copy-code").textContent = "Codigo copiado"; }
    catch { $("#copy-code").textContent = "No se pudo copiar"; }
  };
  function preview(index) {
    const document = documents[index];
    const url = attachmentUrl(document);
    $("#document-preview").innerHTML = document.mime_type === "application/pdf"
      ? `<iframe class="document-frame" src="${url}" title="Documento original"></iframe><a class="map-link" href="${url}" target="_blank" rel="noopener noreferrer">Abrir PDF ${icon("arrow-up-right")}</a>`
      : `<img class="document-image" src="${url}" alt="${escapeHtml(document.filename)}"><a class="map-link" href="${url}" target="_blank" rel="noopener noreferrer">Abrir imagen ${icon("arrow-up-right")}</a>`;
    const image = $("#document-preview img");
    if (image) image.onerror = () => { $("#document-preview").textContent = "No se pudo cargar el adjunto. Comprueba la conexion con Gmail o consulta el correo original."; };
    icons();
  }
  document.querySelectorAll(".select-document").forEach((button) => button.onclick = () => preview(Number(button.dataset.index)));
  if (documents.length) preview(0);
  $("#document-dialog").showModal();
  icons();
}

$("#settings-button").onclick = showSettings;
$("#demo-button").onclick = async () => {
  try { state.demo = true; state.country = "all"; message(""); await loadParcels(); }
  catch (error) { state.demo = false; message(error.message, true); }
};
$("#exit-demo").onclick = async () => {
  try { state.demo = false; state.country = "all"; await loadParcels(); }
  catch (error) { message(error.message, true); }
};
document.querySelectorAll(".filter").forEach((button) => button.onclick = () => { state.country = button.dataset.country; render(); });
document.querySelectorAll(".close-dialog").forEach((button) => button.onclick = () => button.closest("dialog").close());
document.querySelectorAll("dialog").forEach((dialog) => dialog.addEventListener("click", (event) => { if (event.target === dialog) { const rect = dialog.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close(); } }));
$("#dismiss-toast").onclick = () => { $("#toast").hidden = true; state.undo = null; };
$("#undo-button").onclick = async () => {
  const action = state.undo;
  $("#undo-button").disabled = true;
  try { if (action) await action(); $("#toast").hidden = true; state.undo = null; }
  catch (error) { message(error.message, true); }
  finally { $("#undo-button").disabled = false; }
};

$("#connect-button").onclick = async () => {
  if (!state.status?.google_configured) { showSettings(); return; }
  state.busy = true;
  renderConnection();
  message("Autoriza Gmail en la nueva ventana del navegador. La conexion puede tardar unos instantes.");
  try { await api("/api/gmail/connect", "POST"); message("Gmail conectado. Ya puedes sincronizar tus recogidas."); }
  catch (error) { message(error.message, true); }
  finally { state.busy = false; await refreshStatus(); render(); }
};

$("#disconnect-button").onclick = async () => {
  try { await api("/api/gmail/disconnect", "POST"); $("#settings-dialog").close(); await refreshStatus(); render(); toast("Gmail desconectado en este equipo."); }
  catch (error) { $("#settings-dialog").close(); message(error.message, true); }
};

$("#sync-button").onclick = async () => {
  if (!state.status?.gmail_connected || !state.status?.ai_configured) { showSettings(); return; }
  state.busy = true;
  renderConnection();
  try { await api("/api/sync", "POST"); await refreshStatus(); showSyncResult(state.status.sync); if (!state.status.sync.running) await loadParcels(); }
  catch (error) { message(error.message, true); }
  finally { state.busy = false; renderConnection(); }
};

$("#parcel-list").addEventListener("click", async (event) => {
  const documentButton = event.target.closest(".document-button");
  const collectButton = event.target.closest(".collect-button");
  if (documentButton) {
    const parcel = state.parcels.find((item) => item.id === documentButton.dataset.id);
    if (parcel) showDocument(parcel);
  }
  if (collectButton) {
    const parcel = state.parcels.find((item) => item.id === collectButton.dataset.id);
    if (!parcel) return;
    collectButton.disabled = true;
    try {
      const demo = state.demo;
      if (!demo) await api(`/api/parcels/${encodeURIComponent(parcel.id)}/collect`, "POST");
      state.parcels = state.parcels.filter((item) => item.id !== parcel.id);
      render();
      toast("Paquete marcado como recogido.", async () => {
        if (demo) { if (state.demo && !state.parcels.some((item) => item.id === parcel.id)) state.parcels.push(parcel); render(); }
        else { await api(`/api/parcels/${encodeURIComponent(parcel.id)}/restore`, "POST"); if (!state.demo) await loadParcels(); }
      });
    } catch (error) { collectButton.disabled = false; message(error.message, true); }
  }
});

async function initialize() {
  icons();
  try { await refreshStatus(); await loadParcels(); showSyncResult(state.status.sync); }
  catch (error) { message(`No se pudo cargar la bandeja. ${error.message}`, true); }
}
initialize();
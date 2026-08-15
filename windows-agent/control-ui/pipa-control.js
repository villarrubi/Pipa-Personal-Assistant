"use strict";

const state = {
  processes: [],
  commands: [],
  whatsapp: null,
  forgetWhatsappToken: false,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function actionButton(label, title, className = "") {
  const button = node("button", className, label);
  button.type = "button";
  button.title = title;
  button.setAttribute("aria-label", title);
  return button;
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.method && options.method !== "GET") {
    headers["X-Pipa-Local-Request"] = "1";
    headers["X-Pipa-Local-Confirmation"] = "1";
  }
  if (options.body) headers["Content-Type"] = "application/json";
  const response = await fetch(path, { ...options, headers });
  let payload = {};
  try { payload = await response.json(); } catch (_) { /* fixed fallback below */ }
  if (!response.ok) throw new Error(payload.detail || "Pipa no ha podido completar la operación.");
  return payload;
}

let toastTimer;
function toast(message, isError = false) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.toggle("error", isError);
  element.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => element.classList.remove("visible"), 3200);
}

function confirmAction(title, message, acceptLabel = "Confirmar") {
  const dialog = $("#confirm-dialog");
  $("#confirm-title").textContent = title;
  $("#confirm-message").textContent = message;
  $("#confirm-accept").textContent = acceptLabel;
  dialog.showModal();
  return new Promise((resolve) => {
    const finish = (accepted) => {
      dialog.close();
      $("#confirm-cancel").removeEventListener("click", cancel);
      $("#confirm-accept").removeEventListener("click", accept);
      dialog.removeEventListener("cancel", cancel);
      resolve(accepted);
    };
    const cancel = (event) => { event?.preventDefault(); finish(false); };
    const accept = () => finish(true);
    $("#confirm-cancel").addEventListener("click", cancel);
    $("#confirm-accept").addEventListener("click", accept);
    dialog.addEventListener("cancel", cancel);
  });
}

function setLoading() {
  $("#process-list").replaceChildren(node("div", "skeleton"));
  $("#command-list").replaceChildren(node("div", "skeleton"), node("div", "skeleton"));
}

async function loadOverview(showSuccess = false) {
  setLoading();
  try {
    const data = await api("/control/overview");
    state.processes = data.processes;
    state.commands = data.commands;
    state.whatsapp = data.whatsapp;
    renderMetrics(data.summary);
    renderProcesses();
    renderCommands();
    renderWhatsApp();
    if (showSuccess) toast("Datos actualizados.");
  } catch (error) {
    $("#process-list").replaceChildren(emptyState("No se pudo cargar la configuración", "Comprueba que el agente siga activo."));
    $("#command-list").replaceChildren(emptyState("Comandos no disponibles", "Vuelve a intentarlo en unos segundos."));
    toast(error.message, true);
  }
}

function renderMetrics(summary) {
  $("#metric-processes").textContent = summary.active_processes;
  $("#metric-processes-detail").textContent = `${summary.processes} configurados en total`;
  $("#metric-commands").textContent = summary.active_commands;
  $("#metric-commands-detail").textContent = `${summary.commands} comandos disponibles`;
  $("#metric-automations").textContent = summary.automatic_whatsapp ? "1" : "0";
  $("#metric-automations-detail").textContent = summary.automatic_whatsapp ? "WhatsApp automático activo" : "Todo en modo manual";
}

function emptyState(title, detail) {
  const empty = node("div", "empty-state");
  empty.append(node("strong", "", title), document.createTextNode(detail));
  return empty;
}

function processPayload(process, enabled = process.enabled) {
  return {
    id: process.id,
    original_id: process.id,
    aliases: process.aliases,
    launcher: process.launcher,
    arguments: process.arguments,
    enabled,
  };
}

function renderProcesses() {
  const query = $("#process-search").value.trim().toLocaleLowerCase("es");
  const visible = state.processes.filter((process) =>
    [process.id, ...process.aliases, process.launcher].some((value) => value.toLocaleLowerCase("es").includes(query))
  );
  $("#process-count").textContent = `${visible.length} ${visible.length === 1 ? "proceso" : "procesos"}`;
  const container = $("#process-list");
  container.replaceChildren();
  if (!visible.length) {
    container.append(emptyState("No hay coincidencias", "Prueba con otro nombre, alias o ejecutable."));
    return;
  }

  visible.forEach((process) => {
    const row = node("article", "process-row");
    const identity = node("div", "process-identity");
    const avatar = node("span", "process-avatar", process.id.slice(0, 1));
    const names = node("div");
    names.append(node("strong", "", process.id), node("small", "", process.aliases.join(" · ")));
    identity.append(avatar, names);

    const command = node("div", "process-command");
    command.append(node("code", "", [process.launcher, ...process.arguments].join(" ")));
    command.append(node("small", "", process.launcher_resolved ? "Ejecutable localizado" : "Ejecutable pendiente de localizar"));

    const switchLabel = node("label", "switch");
    switchLabel.setAttribute("aria-label", `${process.enabled ? "Desactivar" : "Activar"} ${process.id}`);
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = process.enabled;
    checkbox.addEventListener("change", async () => {
      const intended = checkbox.checked;
      try {
        await api("/control/processes", { method: "PUT", body: JSON.stringify(processPayload(process, intended)) });
        await loadOverview();
        toast(`Proceso ${intended ? "activado" : "desactivado"}.`);
      } catch (error) {
        checkbox.checked = !intended;
        toast(error.message, true);
      }
    });
    switchLabel.append(checkbox, node("span"));

    const actions = node("div", "row-actions");
    const run = actionButton("▶", `Ejecutar ${process.id}`, "run-button");
    run.disabled = !process.enabled || !process.launcher_resolved;
    if (!process.launcher_resolved) run.title = "El ejecutable no se ha localizado";
    run.addEventListener("click", () => runProcess(process));
    const edit = actionButton("✎", `Editar ${process.id}`);
    edit.addEventListener("click", () => openProcessDialog(process));
    const remove = actionButton("×", `Eliminar ${process.id}`);
    remove.addEventListener("click", () => deleteProcess(process));
    actions.append(run, edit, remove);
    row.append(identity, command, switchLabel, actions);
    container.append(row);
  });
}

async function runProcess(process) {
  if (!await confirmAction("Ejecutar proceso", `Pipa abrirá “${process.id}” en este ordenador.`, "Ejecutar")) return;
  try {
    await api(`/control/processes/${encodeURIComponent(process.id)}/run`, { method: "POST" });
    toast(`${process.id} se ha iniciado.`);
  } catch (error) { toast(error.message, true); }
}

async function deleteProcess(process) {
  if (!await confirmAction("Eliminar proceso", `“${process.id}” dejará de estar disponible para Pipa.`, "Eliminar")) return;
  try {
    await api(`/control/processes/${encodeURIComponent(process.id)}`, { method: "DELETE" });
    await loadOverview();
    toast("Proceso eliminado.");
  } catch (error) { toast(error.message, true); }
}

function openProcessDialog(process = null) {
  $("#process-dialog-title").textContent = process ? "Editar proceso" : "Nuevo proceso";
  $("#process-original-id").value = process?.id || "";
  $("#process-id").value = process?.id || "";
  $("#process-aliases").value = process?.aliases.join(", ") || "";
  $("#process-launcher").value = process?.launcher || "";
  $("#process-arguments").value = process?.arguments.join("\n") || "";
  $("#process-enabled").checked = process?.enabled ?? true;
  $("#process-dialog").showModal();
  setTimeout(() => $("#process-id").focus(), 0);
}

async function saveProcess(event) {
  event.preventDefault();
  const originalId = $("#process-original-id").value || null;
  const payload = {
    id: $("#process-id").value.trim(),
    original_id: originalId,
    aliases: $("#process-aliases").value.split(",").map((value) => value.trim()).filter(Boolean),
    launcher: $("#process-launcher").value.trim(),
    arguments: $("#process-arguments").value.split(/\r?\n/).map((value) => value.trim()).filter(Boolean),
    enabled: $("#process-enabled").checked,
  };
  const action = originalId ? "actualizará" : "añadirá";
  if (!await confirmAction("Guardar proceso", `Pipa ${action} “${payload.id}” en su lista de ejecución segura.`, "Guardar")) return;
  try {
    await api("/control/processes", { method: "PUT", body: JSON.stringify(payload) });
    $("#process-dialog").close();
    await loadOverview();
    toast("Proceso guardado.");
  } catch (error) { toast(error.message, true); }
}

function renderCommands() {
  const query = $("#command-search").value.trim().toLocaleLowerCase("es");
  const filter = $("#command-filter").value;
  const visible = state.commands.filter((command) => {
    const matchesQuery = [command.id, command.tool_name, command.phrase, command.description]
      .some((value) => value.toLocaleLowerCase("es").includes(query));
    const matchesFilter = filter === "all"
      || (filter === "active" && command.enabled)
      || (filter === "disabled" && !command.enabled)
      || (filter === "confirmation" && command.requires_confirmation);
    return matchesQuery && matchesFilter;
  });
  const container = $("#command-list");
  container.replaceChildren();
  if (!visible.length) {
    container.append(emptyState("No hay coincidencias", "Cambia el texto o el filtro de comandos."));
    return;
  }
  visible.forEach((command) => {
    const card = node("article", `command-card${command.enabled ? "" : " disabled"}`);
    const copy = node("div");
    copy.append(node("h3", "", command.id), node("span", "command-phrase", `“${command.phrase}”`), node("p", "", command.description));
    const meta = node("div", "command-meta");
    meta.append(node("span", "chip", command.safety === "safe" ? "Local" : "Acción externa"));
    if (command.requires_confirmation) meta.append(node("span", "chip confirmation", "Pide confirmación"));
    if (command.customized) meta.append(node("span", "chip active-chip", "Personalizado"));
    copy.append(meta);

    const actions = node("div", "command-actions");
    const switchLabel = node("label", "switch");
    switchLabel.setAttribute("aria-label", `${command.enabled ? "Desactivar" : "Activar"} ${command.id}`);
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = command.enabled;
    checkbox.addEventListener("change", () => toggleCommand(command, checkbox));
    switchLabel.append(checkbox, node("span"));
    const edit = actionButton("✎", `Editar ${command.id}`, "edit-command");
    edit.addEventListener("click", () => openCommandDialog(command));
    actions.append(switchLabel, edit);
    card.append(copy, actions);
    container.append(card);
  });
}

async function toggleCommand(command, checkbox) {
  const enabled = checkbox.checked;
  try {
    await api(`/control/commands/${encodeURIComponent(command.id)}`, {
      method: "PUT", body: JSON.stringify({ enabled, phrase: command.phrase }),
    });
    await loadOverview();
    toast(`Comando ${enabled ? "activado" : "desactivado"}.`);
  } catch (error) {
    checkbox.checked = !enabled;
    toast(error.message, true);
  }
}

function openCommandDialog(command) {
  $("#command-dialog-title").textContent = command.id;
  $("#command-id").value = command.id;
  $("#command-phrase").value = command.phrase;
  $("#command-enabled").checked = command.enabled;
  const placeholders = command.parameters || [];
  $("#command-placeholder-help").textContent = placeholders.length
    ? `Conserva ${placeholders.length} ${placeholders.length === 1 ? "campo" : "campos"} entre < > para completar la acción.`
    : "Esta frase no necesita campos variables.";
  $("#command-dialog").showModal();
  setTimeout(() => $("#command-phrase").focus(), 0);
}

async function saveCommand(event) {
  event.preventDefault();
  const id = $("#command-id").value;
  try {
    await api(`/control/commands/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: JSON.stringify({ enabled: $("#command-enabled").checked, phrase: $("#command-phrase").value.trim() }),
    });
    $("#command-dialog").close();
    await loadOverview();
    toast("Comando guardado.");
  } catch (error) { toast(error.message, true); }
}

async function resetCommand() {
  const id = $("#command-id").value;
  if (!await confirmAction("Restaurar comando", "Se recuperarán la frase original y su estado activo.", "Restaurar")) return;
  try {
    await api(`/control/commands/${encodeURIComponent(id)}`, { method: "DELETE" });
    $("#command-dialog").close();
    await loadOverview();
    toast("Comando restaurado.");
  } catch (error) { toast(error.message, true); }
}

function renderWhatsApp() {
  const config = state.whatsapp;
  $("#whatsapp-auto").checked = config.automatic_send;
  $("#whatsapp-phone-id").value = config.phone_number_id || "";
  $("#whatsapp-api-version").value = config.api_version;
  $("#whatsapp-token").value = "";
  state.forgetWhatsappToken = false;
  updateWhatsAppVisibility();

  const chip = $("#whatsapp-state-chip");
  chip.textContent = config.active ? "Automático activo" : config.automatic_send ? "Falta configuración" : "Modo manual";
  chip.classList.toggle("active-chip", config.active);
  $("#whatsapp-description").textContent = config.active
    ? "Pipa envía por Cloud API después de que confirmes la acción."
    : config.automatic_send
      ? "El modo automático está seleccionado, pero falta una credencial válida."
      : "Pipa prepara el chat y tú pulsas Enviar.";
  const source = config.credential_source === "environment" ? "Variable de entorno"
    : config.credential_source === "windows_credential_manager" ? "Guardado en Credenciales de Windows"
      : "Sin credencial guardada";
  $("#credential-status").textContent = source;
  $("#forget-token-button").hidden = !config.credential_configured || config.credential_source === "environment";
}

function updateWhatsAppVisibility() {
  $("#whatsapp-settings").classList.toggle("open", $("#whatsapp-auto").checked || Boolean(state.whatsapp?.credential_configured));
}

async function saveWhatsApp() {
  const automatic = $("#whatsapp-auto").checked;
  const message = automatic
    ? "Los mensajes confirmados podrán salir directamente mediante WhatsApp Cloud API."
    : "Los mensajes volverán a abrirse como borrador para que pulses Enviar.";
  if (!await confirmAction("Guardar WhatsApp", message, "Guardar")) return;
  const tokenValue = $("#whatsapp-token").value.trim();
  try {
    await api("/control/whatsapp", {
      method: "PUT",
      body: JSON.stringify({
        automatic_send: automatic,
        phone_number_id: $("#whatsapp-phone-id").value.trim(),
        api_version: $("#whatsapp-api-version").value.trim(),
        access_token: tokenValue || null,
        forget_access_token: state.forgetWhatsappToken,
      }),
    });
    await loadOverview();
    toast("Automatización de WhatsApp guardada.");
  } catch (error) { toast(error.message, true); }
}

function markTokenForRemoval() {
  state.forgetWhatsappToken = true;
  $("#credential-status").textContent = "El token se borrará al guardar";
  $("#forget-token-button").hidden = true;
}

function bindEvents() {
  $("#refresh-button").addEventListener("click", () => loadOverview(true));
  $("#add-process-button").addEventListener("click", () => openProcessDialog());
  $("#process-search").addEventListener("input", renderProcesses);
  $("#command-search").addEventListener("input", renderCommands);
  $("#command-filter").addEventListener("change", renderCommands);
  $("#process-form").addEventListener("submit", saveProcess);
  $("#command-form").addEventListener("submit", saveCommand);
  $("#reset-command-button").addEventListener("click", resetCommand);
  $("#whatsapp-auto").addEventListener("change", updateWhatsAppVisibility);
  $("#save-whatsapp-button").addEventListener("click", saveWhatsApp);
  $("#forget-token-button").addEventListener("click", markTokenForRemoval);
  $$(".close-dialog").forEach((button) => button.addEventListener("click", () => button.closest("dialog").close()));

  const sections = $$("#inicio, #procesos, #comandos, #automatizaciones");
  const observer = new IntersectionObserver((entries) => {
    const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
    if (!visible) return;
    $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.section === visible.target.id));
  }, { rootMargin: "-20% 0px -65% 0px", threshold: [0, .2, .6] });
  sections.forEach((section) => observer.observe(section));
}

document.addEventListener("DOMContentLoaded", () => {
  const hour = new Date().getHours();
  $("#greeting").textContent = hour < 7 || hour >= 21 ? "Buenas noches." : hour < 14 ? "Buenos días." : "Buenas tardes.";
  bindEvents();
  loadOverview();
});

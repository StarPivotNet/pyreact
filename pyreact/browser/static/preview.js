"use strict";

(() => {
  const byId = id => document.getElementById(id);
  const status = byId("connection");
  const errorPanel = byId("error");
  const widthInput = byId("viewport-width");
  const heightInput = byId("viewport-height");
  let snapshot = null;
  let queue = Promise.resolve();
  let pending = 0;
  let refreshing = false;
  let actionError = false;
  let generation = 0;
  let actionSerial = 0;
  let resetting = false;
  const renderer = new window.PreviewRenderer(byId("canvas"), payload => {
    if (resetting) return;
    if (payload.event === "input") renderer.inputPending(payload.id, 1);
    enqueue("/api/event", payload, () => {
      if (payload.event === "input") renderer.inputPending(payload.id, -1);
    });
  });

  function showError(error) {
    errorPanel.hidden = false;
    errorPanel.textContent = `预览请求失败：${error.message}。请检查终端日志；服务恢复后会自动重连。`;
    status.textContent = "连接异常";
    status.className = "connection offline";
  }

  async function request(path, body) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(path, {
        method: body === undefined ? "GET" : "POST",
        headers: body === undefined ? {} : {"Content-Type": "application/json"},
        body: body === undefined ? undefined : JSON.stringify(body),
        cache: "no-store",
        signal: controller.signal
      });
      const result = await response.json();
      if (!response.ok || result.error) throw new Error(result.error || `HTTP ${response.status}`);
      return result;
    } finally {
      clearTimeout(timeout);
    }
  }

  function apply(result, clearError = true) {
    snapshot = result;
    const count = renderer.render(result);
    byId("node-count").textContent = count;
    byId("revision").textContent = result.revision;
    byId("viewport-size").textContent = `${result.width} × ${result.height}`;
    if (![widthInput, heightInput].includes(document.activeElement)) {
      widthInput.value = result.width;
      heightInput.value = result.height;
    }
    if (result.app) byId("app-name").textContent = result.app;
    for (const preset of document.querySelectorAll("[data-size]")) {
      const selected = preset.dataset.size === `${result.width},${result.height}`;
      preset.classList.toggle("selected", selected);
      preset.setAttribute("aria-pressed", String(selected));
    }
    const warnings = result.warnings || [];
    const list = byId("warning-list");
    list.replaceChildren(...warnings.map(warning => {
      const item = document.createElement("li");
      item.textContent = typeof warning === "string" ? warning : JSON.stringify(warning);
      return item;
    }));
    byId("warnings").hidden = !warnings.length;
    if (clearError) actionError = false;
    errorPanel.hidden = !actionError;
    status.textContent = "已连接 · 实时预览";
    status.className = "connection online";
  }

  function enqueue(path, payload, settle = () => {}) {
    const currentGeneration = generation;
    actionSerial++;
    pending++;
    queue = queue.then(async () => {
      let settled = false;
      try {
        if (currentGeneration !== generation) return;
        const result = await request(path, payload);
        if (currentGeneration !== generation) return;
        settle();
        settled = true;
        if (path === "/api/reset") renderer.reset();
        apply(result);
      } catch (error) {
        if (currentGeneration === generation) {
          actionError = true;
          showError(error);
        }
      } finally {
        if (!settled && currentGeneration === generation) settle();
        pending--;
      }
    });
    return queue;
  }

  byId("viewport-form").addEventListener("submit", event => {
    event.preventDefault();
    enqueue("/api/resize", {width: Number(widthInput.value), height: Number(heightInput.value)});
  });
  for (const preset of document.querySelectorAll("[data-size]")) {
    preset.addEventListener("click", () => {
      const [width, height] = preset.dataset.size.split(",").map(Number);
      enqueue("/api/resize", {width, height});
    });
  }
  byId("reset").addEventListener("click", async event => {
    const button = event.currentTarget;
    button.disabled = true;
    resetting = true;
    generation++;
    renderer.reset();
    try {
      await enqueue("/api/reset", {});
    } finally {
      resetting = false;
      button.disabled = false;
    }
  });
  byId("export").addEventListener("click", () => {
    if (!snapshot) return;
    const link = document.createElement("a");
    link.href = "/api/export";
    link.download = "pyreact-layout.json";
    link.click();
  });

  async function refresh() {
    if (pending || refreshing || document.hidden) return;
    const currentAction = actionSerial;
    refreshing = true;
    try {
      const result = await request("/api/tree");
      // A newer user action can arrive while this read is in flight.
      if (!pending && currentAction === actionSerial) apply(result, false);
    } catch (error) {
      if (!pending && currentAction === actionSerial) showError(error);
    } finally {
      refreshing = false;
    }
  }
  refresh();
  setInterval(refresh, 1000);
})();

/* Preview resource-pack item sprites and standard cube blocks. */
"use strict";

window.PyreactItemRenderer = (() => {
  const images = new Map();
  const revisions = new WeakMap();

  function loadImage(src) {
    if (!src) return Promise.reject(new Error("缺少物品纹理路径"));
    if (!images.has(src)) {
      const promise = new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve(image);
        image.onerror = () => reject(new Error(`物品纹理加载失败：${src}`));
        image.src = src;
      });
      images.set(src, promise);
      promise.catch(() => { if (images.get(src) === promise) images.delete(src); });
    }
    return images.get(src);
  }

  function missing(visual, identifier, reason) {
    visual.className = "pr-visual pr-placeholder pr-item-missing";
    visual.replaceChildren();
    visual.textContent = `物品预览不可用\n${identifier || "未知物品"}`;
    visual.setAttribute("title", reason || "未找到可预览的物品纹理");
    visual.setAttribute("data-item-error", reason || "missing");
  }

  function face(context, image, origin, horizontal, vertical, shade) {
    context.save();
    context.transform(horizontal[0], horizontal[1], vertical[0], vertical[1], origin[0], origin[1]);
    context.drawImage(image, 0, 0, 1, 1);
    if (shade) {
      context.globalCompositeOperation = "source-atop";
      context.fillStyle = `rgba(0,0,0,${shade})`;
      context.fillRect(0, 0, 1, 1);
    }
    context.restore();
  }

  function drawCube(context, textures, size) {
    context.save();
    context.translate(size * .05, size * .05);
    context.scale(size * .9, size * .9);
    const half = Math.sqrt(3) / 4;
    face(context, textures[0], [.5, 0], [half, .25], [-half, .25], 0);
    face(context, textures[1], [.5 - half, .25], [half, .25], [0, .5], .17);
    face(context, textures[2], [.5, .5], [half, -.25], [0, .5], .34);
    context.restore();
  }

  function drawGlint(context, size) {
    context.save();
    context.globalCompositeOperation = "source-atop";
    context.fillStyle = "#a06fff33";
    context.fillRect(0, 0, size, size);
    context.rotate(-Math.PI / 4);
    context.fillStyle = "#d6aaff55";
    for (let x = -size; x < size * 2; x += size / 3) {
      context.fillRect(x, 0, size / 12, size * 2);
    }
    context.restore();
  }

  function render(record) {
    const {node, visual} = record;
    const props = node.props || {};
    const preview = props.itemPreview || {
      mode: props.identifier ? "missing" : "empty", identifier: props.identifier,
      reason: "服务端未提供物品纹理"
    };
    const size = Math.max(1, Math.min(2048, Math.ceil(
      Math.max(node.layout?.width || 0, node.layout?.height || 0) * (window.devicePixelRatio || 1))));
    const signature = JSON.stringify([preview, size]);
    const previous = revisions.get(visual);
    if (previous?.signature === signature && !previous.aborted) return;
    const revision = {signature};
    revisions.set(visual, revision);
    visual.className = "pr-visual pr-item-preview";
    visual.removeAttribute("data-item-error");
    visual.removeAttribute("title");
    visual.replaceChildren();
    if (preview.mode === "empty") return;
    if (!["sprite", "cube"].includes(preview.mode)) {
      missing(visual, preview.identifier, preview.reason);
      return;
    }
    const canvas = document.createElement("canvas");
    canvas.className = "pr-item-canvas";
    canvas.width = canvas.height = size;
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", preview.identifier || "物品");
    visual.setAttribute("title", `${preview.identifier || "物品"}${preview.enchant ? "（附魔光效为近似预览）" : ""}`);
    visual.append(canvas);
    const current = () => revisions.get(visual) === revision && visual.isConnected && canvas.parentElement === visual;
    const sources = preview.mode === "cube"
      ? [preview.faces?.top, preview.faces?.left, preview.faces?.right] : [preview.src];
    Promise.all(sources.map(loadImage)).then(textures => {
      if (!current()) { revision.aborted = true; return; }
      if (preview.mode === "sprite") {
        const image = textures[0];
        const scale = size / Math.max(image.naturalWidth, image.naturalHeight, 1);
        canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
        canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
      }
      const context = canvas.getContext("2d");
      if (!context) throw new Error("浏览器不支持 Canvas 物品预览");
      context.imageSmoothingEnabled = false;
      if (preview.mode === "cube") {
        drawCube(context, textures, size);
      } else {
        context.drawImage(textures[0], 0, 0, canvas.width, canvas.height);
      }
      if (preview.enchant) drawGlint(context, size);
    }).catch(error => {
      if (current()) missing(visual, preview.identifier, error.message);
      revision.aborted = true;
    });
  }

  return {render};
})();

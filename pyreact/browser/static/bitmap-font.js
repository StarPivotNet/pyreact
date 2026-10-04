/* Draw local game glyphs using the shared preview text layout. */
"use strict";

window.PyreactBitmapFont = (() => {
  const pages = new Map();
  const revisions = new WeakMap();

  function loadPage(page) {
    if (!pages.has(page)) {
      const promise = new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve(image);
        image.onerror = () => reject(new Error(`缺少游戏字体纹理：${page}`));
        image.src = `/fonts/${encodeURIComponent(page)}`;
      });
      pages.set(page, promise);
      promise.catch(() => { if (pages.get(page) === promise) pages.delete(page); });
    }
    return pages.get(page);
  }

  function createCanvas(width, height, ratio) {
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.ceil(width * ratio));
    canvas.height = Math.max(1, Math.ceil(height * ratio));
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    const context = canvas.getContext("2d");
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.imageSmoothingEnabled = false;
    return {canvas, context};
  }

  function render(visual, node) {
    const props = node.props || {};
    const bitmap = props.fontBitmap;
    if (!bitmap) {
      revisions.delete(visual);
      visual.removeAttribute("data-font-error");
      visual.removeAttribute("title");
      return false;
    }
    const width = Math.max(0, node.layout?.width || 0);
    const height = Math.max(0, node.layout?.height || 0);
    const ratio = Math.max(1, window.devicePixelRatio || 1);
    const signature = JSON.stringify([bitmap, width, height, ratio, props.content,
      props.color, props.shadow, props.textAlign]);
    const previous = revisions.get(visual);
    if (previous?.signature === signature && !previous.aborted && previous.canvas.parentElement === visual) return true;
    const revision = {signature};
    revisions.set(visual, revision);
    visual.removeAttribute("data-font-error");
    visual.removeAttribute("title");
    const {canvas, context} = createCanvas(width, height, ratio);
    revision.canvas = canvas;
    const text = document.createElement("span");
    text.className = "pr-bitmap-text";
    text.textContent = props.content == null ? "" : String(props.content);
    canvas.setAttribute("aria-hidden", "true");
    visual.className = "pr-visual pr-label pr-bitmap-label";
    visual.replaceChildren(canvas, text);

    const lines = bitmap.lines || [];
    const pageNames = [...new Set(lines.flatMap(line => line.glyphs.map(glyph => glyph.page)))];
    const current = () => revisions.get(visual) === revision && visual.isConnected && canvas.parentElement === visual;
    Promise.all(pageNames.map(loadPage)).then(images => {
      if (!current()) { revision.aborted = true; return; }
      const textures = new Map(pageNames.map((page, index) => [page, images[index]]));
      const {canvas: mask, context: ink} = createCanvas(width, height, ratio);
      const align = {left: 0, center: 0.5, right: 1}[props.textAlign] || 0;
      const top = (height - bitmap.height) / 2;
      for (const line of lines) {
        const left = (width - line.width) * align;
        for (const glyph of line.glyphs) {
          ink.drawImage(textures.get(glyph.page), glyph.sx, glyph.sy, glyph.sw, glyph.sh,
            left + glyph.x, top + glyph.y, glyph.width, glyph.height);
        }
      }
      ink.globalCompositeOperation = "source-in";
      ink.fillStyle = props.color || "#fff";
      ink.fillRect(0, 0, width, height);
      if (props.shadow) {
        context.drawImage(mask, 0, 0, mask.width, mask.height, 1, 1, width, height);
        context.globalCompositeOperation = "source-in";
        context.fillStyle = "#0009";
        context.fillRect(0, 0, width, height);
        context.globalCompositeOperation = "source-over";
      }
      context.drawImage(mask, 0, 0, mask.width, mask.height, 0, 0, width, height);
    }).catch(error => {
      revision.aborted = true;
      if (current()) {
        visual.setAttribute("data-font-error", error.message);
        visual.setAttribute("title", error.message);
        const notice = document.createElement("span");
        notice.className = "pr-font-error";
        notice.textContent = "字体加载失败";
        visual.append(notice);
      }
    });
    return true;
  }

  return {render};
})();

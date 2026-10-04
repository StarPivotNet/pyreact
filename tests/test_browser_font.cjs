"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");

function setup() {
  const images = [];
  const canvases = [];
  class Element {
    constructor(tag) {
      this.tag = tag;
      this.style = {};
      this.attributes = {};
      this.children = [];
      this.isConnected = true;
      if (tag === "canvas") {
        const calls = [];
        this.context = {
          calls,
          setTransform(...args) { calls.push(["setTransform", ...args]); },
          drawImage(...args) { calls.push(["drawImage", ...args]); },
          fillRect(...args) { calls.push(["fillRect", this.fillStyle, this.globalCompositeOperation, ...args]); }
        };
        canvases.push(this);
      }
    }
    getContext() { return this.context; }
    setAttribute(name, value) { this.attributes[name] = value; }
    removeAttribute(name) { delete this.attributes[name]; }
    append(...items) {
      for (const item of items) { item.parentElement = this; this.children.push(item); }
    }
    replaceChildren(...items) {
      for (const item of this.children) item.parentElement = null;
      this.children = [];
      this.append(...items);
    }
  }
  const window = {devicePixelRatio: 2};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../pyreact/browser/static/bitmap-font.js"), "utf8"), {
    window,
    document: {createElement: tag => new Element(tag)},
    Image: class Image { constructor() { images.push(this); } }
  });
  return {render: window.PyreactBitmapFont.render, window, images, canvases, visual: new Element("div")};
}

function node(overrides = {}) {
  const glyph = (page, x, y) => ({page, sx: 2, sy: 4, sw: 8, sh: 12, x, y, width: 8, height: 12});
  return {
    layout: {width: 100, height: 60},
    props: {
      content: "中A\n文", color: "#ffeedd", textAlign: "center", shadow: true,
      fontBitmap: {width: 30, height: 32, lineHeight: 16, lines: [
        {width: 30, glyphs: [glyph("glyph_4E.png", 0, 0), glyph("default8.png", 15, 0)]},
        {width: 14, glyphs: [glyph("glyph_4E.png", 0, 16)]}
      ]},
      ...overrides
    }
  };
}

async function flush() { await new Promise(resolve => setImmediate(resolve)); }

test("bitmap glyphs use DPR backing, per-line alignment, tint, shadow and accessible text", async () => {
  const h = setup();
  assert.equal(h.render(h.visual, node()), true);
  const canvas = h.visual.children[0];
  assert.equal(canvas.width, 200);
  assert.equal(canvas.height, 120);
  assert.equal(canvas.style.width, "100px");
  assert.equal(canvas.attributes["aria-hidden"], "true");
  assert.equal(h.visual.children[1].textContent, "中A\n文");
  assert.deepEqual(h.images.map(image => image.src), ["/fonts/glyph_4E.png", "/fonts/default8.png"]);
  h.images.forEach(image => image.onload());
  await flush();
  const mask = h.canvases[1];
  assert.equal(mask.context.imageSmoothingEnabled, false);
  assert.equal(canvas.context.imageSmoothingEnabled, false);
  const glyphs = mask.context.calls.filter(call => call[0] === "drawImage");
  assert.deepEqual(glyphs.map(call => call.slice(2)), [
    [2, 4, 8, 12, 35, 14, 8, 12], [2, 4, 8, 12, 50, 14, 8, 12], [2, 4, 8, 12, 43, 30, 8, 12]
  ]);
  assert.deepEqual(mask.context.calls.at(-1), ["fillRect", "#ffeedd", "source-in", 0, 0, 100, 60]);
  const output = canvas.context.calls.filter(call => call[0] === "drawImage");
  assert.deepEqual(output.map(call => call.slice(-4)), [[1, 1, 100, 60], [0, 0, 100, 60]]);
});

test("unchanged polling retains canvas; color, size and DPR changes repaint using cached pages", async () => {
  const h = setup();
  const first = node();
  h.render(h.visual, first);
  const canvas = h.visual.children[0];
  h.render(h.visual, node());
  assert.equal(h.visual.children[0], canvas);
  assert.equal(h.images.length, 2);
  h.images.forEach(image => image.onload());
  await flush();
  h.render(h.visual, node({color: "#ff0000", shadow: false}));
  await flush();
  assert.notEqual(h.visual.children[0], canvas);
  assert.equal(h.images.length, 2);
  assert.equal(h.visual.children[0].context.calls.filter(call => call[0] === "drawImage").length, 1);
  h.window.devicePixelRatio = 3;
  first.layout.width = 120;
  h.render(h.visual, first);
  await flush();
  assert.equal(h.visual.children[0].width, 360);
});

test("late image loads do not repaint stale text or removed elements", async () => {
  const h = setup();
  h.render(h.visual, node());
  const stale = h.visual.children[0];
  h.render(h.visual, node({content: "新文本", textAlign: "right"}));
  h.images.forEach(image => image.onload());
  await flush();
  assert.equal(stale.context.calls.filter(call => call[0] === "drawImage").length, 0);
  assert.equal(h.visual.children[1].textContent, "新文本");
  const glyphs = h.canvases.at(-1).context.calls.filter(call => call[0] === "drawImage");
  assert.equal(glyphs[0][6], 70);

  const detached = setup();
  detached.render(detached.visual, node());
  detached.visual.isConnected = false;
  detached.images.forEach(image => image.onload());
  await flush();
  assert.equal(detached.canvases.length, 1);
  detached.visual.isConnected = true;
  detached.render(detached.visual, node());
  await flush();
  assert.equal(detached.canvases.length, 3);
});

test("missing bitmap returns fallback and cancels pending drawing", async () => {
  const h = setup();
  h.render(h.visual, node());
  assert.equal(h.render(h.visual, node({fontBitmap: undefined})), false);
  h.images.forEach(image => image.onload());
  await flush();
  assert.equal(h.canvases.length, 1);
});

test("font loading errors are visible, retain readable text and can retry", async () => {
  const h = setup();
  h.render(h.visual, node());
  h.images[0].onerror();
  h.images[1].onload();
  await flush();
  assert.match(h.visual.attributes.title, /glyph_4E/);
  assert.equal(h.visual.children.at(-1).textContent, "字体加载失败");
  h.render(h.visual, node());
  assert.equal(h.images.length, 3);
  h.images[2].onload();
  await flush();
  assert.equal(h.visual.attributes["data-font-error"], undefined);
  assert.equal(h.visual.children.length, 2);
});

test("left alignment and empty text need no system-font drawing", async () => {
  const h = setup();
  h.render(h.visual, node({textAlign: "left", shadow: false}));
  h.images.forEach(image => image.onload());
  await flush();
  const glyphs = h.canvases[1].context.calls.filter(call => call[0] === "drawImage");
  assert.equal(glyphs[0][6], 0);
  h.render(h.visual, node({content: "", fontBitmap: {width: 0, height: 0, lines: []}}));
  await flush();
  assert.equal(h.visual.children[1].textContent, "");
  assert.equal(h.images.length, 2);
});

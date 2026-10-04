/* Run with node --test tests/test_browser_items.cjs; no DOM package needed. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");

function setup() {
  const images = [];
  class Element {
    constructor(tag) {
      this.tag = tag;
      this.style = {};
      this.attributes = {};
      this.children = [];
      this.isConnected = true;
      this.context = {calls: []};
      for (const name of ["save", "restore", "transform", "translate", "scale", "rotate", "drawImage", "fillRect"]) {
        this.context[name] = (...args) => this.context.calls.push([name, ...args]);
      }
    }
    getContext() { return this.context; }
    setAttribute(key, value) { this.attributes[key] = value; }
    removeAttribute(key) { delete this.attributes[key]; }
    append(...items) { for (const item of items) { item.parentElement = this; this.children.push(item); } }
    replaceChildren(...items) {
      for (const child of this.children) child.parentElement = null;
      this.children = [];
      this.textContent = "";
      this.append(...items);
    }
  }
  const window = {devicePixelRatio: 2};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../pyreact/browser/static/item-renderer.js"), "utf8"), {
    window, document: {createElement: tag => new Element(tag)},
    Image: class Image {
      constructor() { this.naturalWidth = 16; this.naturalHeight = 16; images.push(this); }
    }
  });
  const record = {visual: new Element("div"), node: {layout: {width: 48, height: 32}, props: {}}};
  const render = preview => {
    record.node.props.itemPreview = preview;
    window.PyreactItemRenderer.render(record);
  };
  return {window, images, record, render};
}

const sprite = (identifier = "minecraft:apple", src = "/assets/apple.png") => ({mode: "sprite", identifier, src});
const cube = () => ({mode: "cube", identifier: "minecraft:grass", faces: {
  top: "/assets/grass_top.png", left: "/assets/grass_side.png", right: "/assets/grass_side.png"
}});
async function flush() { await new Promise(resolve => setImmediate(resolve)); }
const draws = canvas => canvas.context.calls.filter(call => call[0] === "drawImage");

test("sprite contains non-square texture, disables smoothing and preserves ancestor styles", async () => {
  const h = setup();
  h.record.visual.style.opacity = ".4";
  h.record.visual.style.transform = "translateX(5px)";
  h.render(sprite());
  const canvas = h.record.visual.children[0];
  assert.equal(canvas.width, 96);
  assert.equal(canvas.height, 96);
  assert.equal(canvas.attributes["aria-label"], "minecraft:apple");
  h.images[0].naturalHeight = 8;
  h.images[0].onload();
  await flush();
  assert.equal(canvas.context.imageSmoothingEnabled, false);
  assert.equal(canvas.height, 48);
  assert.deepEqual(draws(canvas)[0].slice(2), [0, 0, 96, 48]);
  assert.equal(h.record.visual.style.opacity, ".4");
  assert.equal(h.record.visual.style.transform, "translateX(5px)");
});

test("cube draws top and two shaded side faces with shared texture cache", async () => {
  const h = setup();
  h.render(cube());
  assert.equal(h.images.length, 2);
  h.images.forEach(image => image.onload());
  await flush();
  const canvas = h.record.visual.children[0];
  assert.equal(draws(canvas).length, 3);
  assert.equal(canvas.context.calls.filter(call => call[0] === "transform").length, 3);
  assert.equal(canvas.context.calls.filter(call => call[0] === "fillRect").length, 2);
  h.render(cube());
  assert.equal(h.record.visual.children[0], canvas);
  h.record.node.layout.width = 64;
  h.render(cube());
  await flush();
  assert.equal(h.images.length, 2);
  assert.equal(h.record.visual.children[0].width, 128);
  assert.equal(draws(h.record.visual.children[0]).length, 3);
});

test("same node switches sprite, cube and empty without stale asynchronous painting", async () => {
  const h = setup();
  h.render(sprite());
  const stale = h.record.visual.children[0];
  h.render(cube());
  h.images.forEach(image => image.onload());
  await flush();
  assert.equal(draws(stale).length, 0);
  assert.equal(draws(h.record.visual.children[0]).length, 3);
  h.render({mode: "empty"});
  assert.equal(h.record.visual.children.length, 0);
  assert.equal(h.record.visual.textContent, "");
  assert.equal(h.record.visual.attributes.title, undefined);

  h.render(sprite("minecraft:diamond", "/assets/diamond.png"));
  const pending = h.record.visual.children[0];
  h.render({mode: "empty"});
  h.images.at(-1).onload();
  await flush();
  assert.equal(draws(pending).length, 0);
  assert.equal(h.record.visual.children.length, 0);
});

test("missing resolver data produces visible reason and empty identifiers clear", () => {
  const h = setup();
  h.render({mode: "missing", identifier: "custom:thing", reason: "未找到资源包"});
  assert.match(h.record.visual.textContent, /custom:thing/);
  assert.equal(h.record.visual.attributes.title, "未找到资源包");
  h.record.node.props.identifier = "minecraft:apple";
  h.render(undefined);
  assert.match(h.record.visual.textContent, /minecraft:apple/);
  delete h.record.node.props.identifier;
  h.render(null);
  assert.equal(h.record.visual.children.length, 0);
  assert.equal(h.record.visual.textContent, "");
  assert.equal(h.images.length, 0);
});

test("failed loads show placeholder, retry and never overwrite a newer item", async () => {
  const h = setup();
  h.render(sprite());
  h.images[0].onerror();
  await flush();
  assert.match(h.record.visual.textContent, /物品预览不可用/);
  assert.match(h.record.visual.attributes["data-item-error"], /apple.png/);
  h.render(sprite());
  assert.equal(h.images.length, 2);
  h.images[1].onload();
  await flush();
  assert.equal(draws(h.record.visual.children[0]).length, 1);
  assert.equal(h.record.visual.attributes["data-item-error"], undefined);

  h.render(sprite("old", "/old.png"));
  h.render(sprite("new", "/new.png"));
  h.images[2].onerror();
  h.images[3].onload();
  await flush();
  assert.equal(h.record.visual.children[0].attributes["aria-label"], "new");
  assert.equal(draws(h.record.visual.children[0]).length, 1);
});

test("removed elements suppress paint; reattachment and enchant changes repaint from cache", async () => {
  const h = setup();
  h.render(sprite());
  const stale = h.record.visual.children[0];
  h.record.visual.isConnected = false;
  h.images[0].onload();
  await flush();
  assert.equal(draws(stale).length, 0);
  h.record.visual.isConnected = true;
  h.render({...sprite(), enchant: true});
  await flush();
  assert.equal(h.images.length, 1);
  assert.equal(draws(h.record.visual.children[0]).length, 1);
  assert.match(h.record.visual.attributes.title, /近似/);
  assert.ok(h.record.visual.children[0].context.calls.some(call => call[0] === "rotate"));
  h.render(sprite());
  await flush();
  assert.doesNotMatch(h.record.visual.attributes.title, /近似/);
  assert.equal(h.record.visual.children[0].context.calls.some(call => call[0] === "rotate"), false);
});

test("malformed cube faces show loading error without an unhandled rejection", async () => {
  const h = setup();
  h.render({mode: "cube", identifier: "broken", faces: {}});
  await flush();
  assert.match(h.record.visual.textContent, /broken/);
  assert.match(h.record.visual.attributes.title, /缺少物品纹理路径/);
});

test("renderer dispatches Items separately while PaperDoll remains a native placeholder", () => {
  const records = [];
  const window = {PyreactItemRenderer: {render: record => records.push(record)}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../pyreact/browser/static/renderer.js"), "utf8"), {window});
  const renderVisual = window.PreviewRenderer.prototype.renderVisual;
  const item = {node: {type: "Item", props: {}}, visual: {}};
  renderVisual.call({}, item);
  assert.equal(records[0], item);
  const doll = {node: {type: "PaperDoll", props: {entityIdentifier: "minecraft:pig"}}, visual: {}};
  renderVisual.call({}, doll);
  assert.match(doll.visual.textContent, /minecraft:pig/);
  assert.match(doll.visual.className, /pr-placeholder/);
});

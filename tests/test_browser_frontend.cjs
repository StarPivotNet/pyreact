/* Run with node --test tests/test_browser_frontend.cjs; no DOM package needed. */
"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const vm = require("node:vm");
const fs = require("node:fs");
const path = require("node:path");

function environment(document) {
  let now = 0, nextFrame = 0;
  const frames = new Map();
  const sandbox = {
    performance: {now: () => now},
    requestAnimationFrame: callback => { frames.set(++nextFrame, callback); return nextFrame; },
    cancelAnimationFrame: id => frames.delete(id),
    addEventListener() {}, document: document || {addEventListener() {}}
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  for (const file of ["animations.js", "pointer.js", "renderer.js"]) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, "../pyreact/browser/static", file), "utf8"), sandbox);
  }
  return {...sandbox, frames, advance(value) {
    now = value;
    const callbacks = [...frames.values()];
    frames.clear();
    for (const callback of callbacks) callback(now);
  }};
}

function style() {
  return {setProperty(key, value) { this[key] = String(value); }};
}

function record(animation) {
  return {node: {id: "node-1", type: "Image", style: {opacity: .5},
    layout: {width: 200, height: 30}, animation}, element: {style: style()}, children: {children: []}};
}

test("delay holds from value; local frames finish once and unchanged snapshots never replay", () => {
  const env = environment(), events = [];
  const clock = new env.PreviewAnimations(event => events.push(event));
  const item = record({runId: "a", phase: "enter", from: {opacity: 0}, to: {opacity: 1},
    duration: 100, delay: 50, easing: "linear"});
  clock.update(item);
  env.advance(25);
  assert.equal(item.element.style.opacity, "0");
  env.advance(100);
  assert.equal(item.element.style.opacity, "0.25");
  env.advance(150);
  assert.equal(events.length, 1);
  assert.equal(events[0].value.runId, "a");
  clock.update(item);
  env.advance(500);
  assert.equal(events.length, 1);
  assert.equal(env.frames.size, 0);
});

test("interruptions continue from current visual value and suppress superseded completions", () => {
  const env = environment(), events = [];
  const clock = new env.PreviewAnimations(event => events.push(event));
  const item = record({runId: "a", phase: "animate", from: {translateX: 0}, to: {translateX: 100},
    duration: 100, easing: "linear"});
  clock.update(item);
  env.advance(40);
  item.node.animation = {runId: "b", phase: "animate", from: {translateX: 100}, to: {translateX: 0},
    duration: 100, easing: "linear"};
  clock.update(item);
  assert.equal(item.animation.from.translateX, 40);
  env.advance(90);
  assert.equal(item.animation.values.translateX, 20);
  env.advance(140);
  assert.equal(events.length, 1);
  assert.equal(events[0].value.runId, "b");
});

test("alpha affects direct visuals; sizes are absolute and do not resize Labels", () => {
  const env = environment();
  const clock = new env.PreviewAnimations(() => {});
  const item = record(null), child = {style: style()};
  item.children.children.push(child);
  clock.apply(item, {alpha: .25, opacity: .4, width: 80, height: -3});
  assert.equal(item.element.style.opacity, "0.2");
  assert.equal(item.element.style["--pr-own-alpha"], "0.25");
  assert.equal(child.style["--pr-parent-alpha"], "0.25");
  assert.equal(item.element.style.width, "80px");
  assert.equal(item.element.style.height, "0px");
  item.node.type = "Label";
  clock.apply(item, {width: 900});
  assert.equal(item.element.style.width, "80px");
});

test("custom easing samples and zero-duration exits use a single completion", () => {
  const env = environment(), events = [];
  const clock = new env.PreviewAnimations(event => events.push(event));
  const item = record({runId: "a", phase: "animate", from: {translateX: 0}, to: {translateX: 100},
    duration: 100, easingSamples: [0, .25, 1]});
  clock.update(item);
  env.advance(50);
  assert.equal(item.animation.values.translateX, 25);
  item.node.animation = {runId: "b", phase: "exit", from: {opacity: 1}, to: {opacity: 0}, duration: 0};
  clock.update(item);
  env.advance(51);
  assert.equal(item.element.style.visibility, "hidden");
  assert.equal(events.length, 1);
  clock.remove(item);
  assert.equal(env.frames.size, 0);
});

test("pointer coordinates invert canvas scale and account for nested scrolling", () => {
  const env = environment();
  const canvas = {style: {width: "1000px", height: "500px"},
    getBoundingClientRect: () => ({left: 40, top: 20, width: 500, height: 250})};
  const parent = {parentElement: canvas, scrollLeft: 30, scrollTop: 80};
  const item = {element: {parentElement: parent}, node: {id: "slider"}};
  const events = [], pointer = new env.PreviewPointer(canvas, event => events.push(event));
  pointer.send(item, {clientX: 140, clientY: 70, pointerId: 3}, 1);
  pointer.send(item, {clientX: 190, clientY: 70, pointerId: 3}, 4);
  assert.equal(events[0].value.TouchPosX, 230);
  assert.equal(events[0].value.TouchPosY, 180);
  assert.equal(events[1].value.sequence, 2);
  assert.equal(events[1].value.pointerId, 3);
});

test("capture follows drag outside, and cancellation sends one terminal event", () => {
  const env = environment(), handlers = {}, captures = new Set(), events = [];
  const canvas = {style: {width: "100px", height: "100px"},
    getBoundingClientRect: () => ({left: 0, top: 0, width: 100, height: 100})};
  const item = {node: {id: "slider", props: {onTouch: true}}, element: {
    parentElement: canvas, dataset: {}, addEventListener: (name, fn) => { handlers[name] = fn; },
    setPointerCapture: id => captures.add(id), hasPointerCapture: id => captures.has(id),
    releasePointerCapture: id => captures.delete(id),
    getBoundingClientRect: () => ({left: 0, right: 50, top: 0, bottom: 20})
  }};
  const pointer = new env.PreviewPointer(canvas, event => events.push(event));
  pointer.bind(item);
  const event = {pointerId: 1, pointerType: "mouse", button: 0, clientX: 10, clientY: 10,
    stopPropagation() {}, preventDefault() {}};
  handlers.pointerdown(event);
  assert.equal(captures.has(1), true);
  handlers.pointermove({...event, clientX: 70});
  pointer.cancelAll(7);
  handlers.lostpointercapture(event);
  assert.deepEqual(events.map(e => e.value.TouchEvent), [1, 6, 7]);
  assert.equal(captures.size, 0);
  assert.equal(pointer.active.size, 0);
});

test("zero-duration targets apply before the first frame and frozen exit children keep transforms", () => {
  const env = environment(), events = [];
  const clock = new env.PreviewAnimations(event => events.push(event));
  const item = record({runId: "a", phase: "animate", from: {translateX: 0}, to: {translateX: 60}, duration: 0});
  clock.update(item);
  assert.equal(item.animation.values.translateX, 60);
  assert.equal(events.length, 0);
  env.advance(1);
  assert.equal(events.length, 1);
  item.exiting = true;
  item.node.animation = null;
  clock.update(item);
  assert.equal(item.element.style.transform, "translate(60px, 0px)");
  assert.equal(env.frames.size, 0);
  item.element.style.visibility = "hidden";
  item.exiting = false;
  clock.update(item);
  assert.equal(item.element.style.visibility, "");
  assert.equal(item.element.style.transform, "translate(0px, 0px)");
});

test("explicit exit origins override an interrupted run's sampled values", () => {
  const env = environment();
  const clock = new env.PreviewAnimations(() => {});
  const item = record({runId: "a", phase: "animate", from: {translateX: 0},
    to: {translateX: 100}, duration: 100, easing: "linear"});
  clock.update(item);
  env.advance(25);
  item.node.animation = {runId: "b", phase: "exit", from: {translateX: 70},
    to: {translateX: 0}, duration: 100, easing: "linear"};
  clock.update(item);
  assert.equal(item.animation.values.translateX, 70);
});

function previewEnvironment() {
  const elements = new Map(), requests = [], renders = [], inputDeltas = [];
  let refresh, renderer;
  const byId = id => {
    if (!elements.has(id)) elements.set(id, {listeners: {}, style: {},
      addEventListener(name, callback) { this.listeners[name] = callback; },
      replaceChildren() {}});
    return elements.get(id);
  };
  const sandbox = {
    AbortController, setTimeout: () => 1, clearTimeout() {},
    setInterval(callback) { refresh = callback; },
    document: {getElementById: byId, querySelectorAll: () => [], createElement: () => ({}), hidden: false},
    fetch(path, options) {
      return new Promise(resolve => requests.push({path, options,
        finish(result) { resolve({ok: true, json: async () => result}); }}));
    },
    PreviewRenderer: class {
      constructor(canvas, onEvent) { this.onEvent = onEvent; this.resets = 0; renderer = this; }
      inputPending(id, delta) { inputDeltas.push([id, delta]); }
      render(result) { renders.push(result); return 1; }
      reset() { this.resets++; }
    }
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../pyreact/browser/static/preview.js"), "utf8"), sandbox);
  return {byId, requests, renders, inputDeltas, renderer, refresh: () => refresh()};
}

const flushPromises = () => new Promise(resolve => setImmediate(resolve));
const snapshot = revision => ({revision, width: 960, height: 540});

test("requests stay serial and a delayed poll cannot overwrite a completed interaction", async () => {
  const env = previewEnvironment();
  env.renderer.onEvent({id: "node", event: "click"});
  env.renderer.onEvent({id: "node", event: "click"});
  await flushPromises();
  assert.deepEqual(env.requests.map(r => r.path), ["/api/tree", "/api/event"]);
  env.requests[1].finish(snapshot(2));
  await flushPromises();
  assert.equal(env.requests.length, 3);
  env.requests[2].finish(snapshot(3));
  await flushPromises();
  env.requests[0].finish(snapshot(1));
  await flushPromises();
  assert.deepEqual(env.renders.map(r => r.revision), [2, 3]);
});

test("reset drops unsent old events and ignores old responses while preserving request ordering", async () => {
  const env = previewEnvironment();
  env.requests[0].finish(snapshot(1));
  await flushPromises();
  env.renderer.onEvent({id: "old", event: "click"});
  env.renderer.onEvent({id: "old", event: "input", value: "obsolete"});
  await flushPromises();
  const button = env.byId("reset");
  const resetting = button.listeners.click({currentTarget: button});
  env.renderer.onEvent({id: "old", event: "animation_complete", value: {runId: "old"}});
  assert.equal(button.disabled, true);
  env.requests[1].finish(snapshot(2));
  await flushPromises();
  assert.deepEqual(env.requests.map(r => r.path), ["/api/tree", "/api/event", "/api/reset"]);
  env.requests[2].finish(snapshot(10));
  await resetting;
  assert.deepEqual(env.renders.map(r => r.revision), [1, 10]);
  assert.deepEqual(env.inputDeltas, [["old", 1]]);
  assert.equal(button.disabled, false);
  env.renderer.onEvent({id: "new", event: "click"});
  await flushPromises();
  assert.equal(env.requests[3].path, "/api/event");
  env.requests[3].finish(snapshot(11));
  await flushPromises();
  assert.equal(env.renders.at(-1).revision, 11);
});

function fakeElement() {
  const element = {style: {...style(), getPropertyValue(key) { return this[key]; }},
    dataset: {}, children: [], className: "", parentElement: null, addEventListener() {},
    setAttribute() {}, removeAttribute() {}, hasPointerCapture: () => false,
    append(...children) { for (const child of children) this.insertBefore(child, null); },
    insertBefore(child, before) {
      child.remove();
      const index = before ? this.children.indexOf(before) : this.children.length;
      this.children.splice(index, 0, child);
      child.parentElement = this;
    },
    remove() {
      if (this.parentElement) {
        const children = this.parentElement.children;
        children.splice(children.indexOf(this), 1);
        this.parentElement = null;
      }
    },
    replaceChildren(...children) {
      for (const child of [...this.children]) child.remove();
      this.append(...children);
    },
    getBoundingClientRect() {
      const parent = this.parentElement?.getBoundingClientRect() || {left: 0, top: 0};
      const x = parseFloat(this.style.transform?.match(/translate\(([-.\d]+)/)?.[1]) || 0;
      return {left: parent.left + (parseFloat(this.style.left) || 0) + x,
        top: parent.top + (parseFloat(this.style.top) || 0),
        width: parseFloat(this.style.width) || 0, height: parseFloat(this.style.height) || 0};
    }
  };
  element.classList = {contains: name => element.className.split(" ").includes(name),
    toggle(name, enabled) {
      const names = new Set(element.className.split(" "));
      enabled ? names.add(name) : names.delete(name);
      element.className = [...names].join(" ");
    }};
  Object.defineProperty(element, "isConnected", {get() { return this.root || Boolean(this.parentElement?.isConnected); }});
  return element;
}

test("keyed records survive reorder; exit ghosts retain placement and are cleaned after completion", () => {
  const env = environment({addEventListener() {}, createElement: fakeElement}), events = [];
  const canvas = fakeElement();
  canvas.root = true;
  const renderer = new env.PreviewRenderer(canvas, event => events.push(event));
  const node = (id, x, children = []) => ({id, type: "Panel", props: {}, style: {},
    layout: {x, y: 20, width: 100, height: 50}, children});
  const first = node("a", 30), second = node("b", 180);
  first.animation = {runId: "a1", phase: "animate", from: {translateX: 0},
    to: {translateX: 20}, duration: 100, easing: "linear"};
  renderer.render({...snapshot(1), tree: node("root", 0, [first, second])});
  env.advance(50);
  const original = renderer.records.get("a");
  renderer.render({...snapshot(2), tree: node("root", 0, [second, first])});
  assert.equal(renderer.records.get("a"), original);
  assert.equal(renderer.records.get("root").children.children[1], original.element);
  const exit = {...first, animation: {runId: "a2", phase: "exit", from: {},
    to: {opacity: 0}, duration: 100, easing: "linear"}};
  renderer.render({...snapshot(3), tree: node("root", 0, [second]), exits: [exit]});
  assert.equal(original.element.parentElement, canvas);
  assert.equal(original.element.style.left, "30px");
  assert.equal(original.element.style.transform, "translate(10px, 0px)");
  assert.equal(original.element.inert, true);
  assert.equal(original.exiting, true);
  env.advance(150);
  assert.equal(events.length, 1);
  assert.equal(events[0].value.runId, "a2");
  assert.equal(original.element.style.visibility, "hidden");
  renderer.render({...snapshot(4), tree: node("root", 0, [second]), exits: [exit]});
  env.advance(250);
  assert.equal(events.length, 1);
  renderer.render({...snapshot(5), tree: node("root", 0, [second]), exits: []});
  assert.equal(renderer.records.has("a"), false);
  assert.equal(original.element.isConnected, false);
  renderer.reset();
  assert.equal(renderer.records.size, 0);
  assert.equal(env.frames.size, 0);
});

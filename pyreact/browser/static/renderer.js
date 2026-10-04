/* Render Python-computed rectangles without a second browser layout engine. */
"use strict";

window.PreviewRenderer = class PreviewRenderer {
  constructor(canvas, onEvent) {
    this.canvas = canvas;
    this.onEvent = onEvent;
    this.records = new Map();
    this.pendingInputs = new Map();
    this.animations = new window.PreviewAnimations(onEvent);
    this.pointer = new window.PreviewPointer(canvas, onEvent);
  }

  inputPending(id, delta) {
    this.pendingInputs.set(id, Math.max(0, (this.pendingInputs.get(id) || 0) + delta));
  }

  reset() {
    this.pointer.cancelAll(3, null, false);
    for (const record of this.records.values()) this.animations.remove(record);
    this.records.clear();
    this.pendingInputs.clear();
    this.canvas.replaceChildren();
  }

  render(snapshot) {
    const focused = document.activeElement;
    const selection = focused?.classList?.contains("pr-input")
      ? [focused.selectionStart, focused.selectionEnd] : null;
    this.canvas.style.width = `${snapshot.width}px`;
    this.canvas.style.height = `${snapshot.height}px`;
    this.visited = new Set();
    this.count = 0;
    if (snapshot.tree) this.renderNode(snapshot.tree, this.canvas, {x: 0, y: 0}, "");
    for (const node of snapshot.exits || []) {
      this.renderNode(node, this.canvas, {x: 0, y: 0}, "", true);
    }
    for (const [key, record] of this.records) {
      if (!this.visited.has(key)) {
        this.pointer.cancelAll(3, record, false);
        this.animations.remove(record);
        record.element.remove();
        this.records.delete(key);
        this.pendingInputs.delete(record.node.id);
      }
    }
    if (focused?.isConnected && !focused.closest("[inert]") && document.activeElement !== focused) {
      focused.focus({preventScroll: true});
      if (selection) focused.setSelectionRange(...selection);
    }
    return this.count;
  }

  createRecord(node) {
    const element = document.createElement("div");
    const visual = document.createElement("div");
    const children = document.createElement("div");
    element.className = `pr-node pr-${node.type.toLowerCase()}`;
    element.dataset.nodeId = node.id;
    element.dataset.nodeType = node.type;
    visual.className = "pr-visual";
    children.className = "pr-children";
    element.append(visual, children);
    const record = {element, visual, children, type: node.type, node, states: {}};
    this.pointer.bind(record);
    if (node.type === "Input") {
      const input = document.createElement("input");
      input.className = "pr-input";
      input.type = "text";
      input.autocomplete = "off";
      input.addEventListener("compositionstart", () => { record.composing = true; });
      input.addEventListener("compositionend", () => {
        record.composing = false;
        if (record.node.props?.onChange) {
          this.onEvent({id: record.node.id, event: "input", value: input.value});
        }
      });
      input.addEventListener("input", event => {
        if (!record.composing && !event.isComposing && record.node.props?.onChange) {
          this.onEvent({id: record.node.id, event: "input", value: input.value});
        }
      });
      visual.append(input);
      record.input = input;
    }
    element.addEventListener("click", event => {
      if (!record.exiting && record.node.props?.onClick) {
        event.stopPropagation();
        this.onEvent({id: record.node.id, event: "click"});
      }
    });
    element.addEventListener("keydown", event => {
      if (event.target === element && ["Enter", " "].includes(event.key)) {
        event.preventDefault();
        if (!event.repeat) {
          element.dataset.pressed = "true";
          element.click();
        }
      }
    });
    const release = () => { delete element.dataset.pressed; };
    element.addEventListener("keyup", release);
    element.addEventListener("blur", release);
    return record;
  }

  renderNode(node, parent, origin, namespace, exiting = false) {
    const key = namespace + node.id;
    let record = this.records.get(key);
    if (record && record.type !== node.type) {
      this.pointer.cancelAll(3, record, false);
      this.animations.remove(record);
      record.element.remove();
      this.records.delete(key);
      record = null;
    }
    if (!record) {
      record = this.createRecord(node);
      this.records.set(key, record);
    }
    this.visited.add(key);
    if (!namespace) this.count++;
    if (exiting && !record.exiting && parent === this.canvas && record.element.isConnected) {
      const rect = record.element.getBoundingClientRect();
      const canvasRect = this.canvas.getBoundingClientRect();
      record.exitPosition = {
        x: (rect.left - canvasRect.left) * parseFloat(this.canvas.style.width) / canvasRect.width - (record.animation?.values.translateX || 0),
        y: (rect.top - canvasRect.top) * parseFloat(this.canvas.style.height) / canvasRect.height - (record.animation?.values.translateY || 0)
      };
    }
    record.node = node;
    record.exiting = exiting;
    if (!exiting) record.exitPosition = null;
    const {element, children} = record;
    if (element.parentElement !== parent) parent.append(element);
    element.inert = exiting || Boolean(namespace);
    element.classList.toggle("pr-exiting", exiting);
    if (exiting) this.pointer.cancelAll(3, record, false);
    element.style.touchAction = node.props?.onTouch ? "none" : "";
    element.style.setProperty("--pr-parent-alpha", parent.classList.contains("pr-children") ?
      parent.parentElement.style.getPropertyValue("--pr-own-alpha") || 1 : 1);
    const layout = node.layout || {};
    const style = node.style || {};
    Object.assign(element.style, {
      left: `${(layout.x || 0) - (origin.x || 0)}px`,
      top: `${(layout.y || 0) - (origin.y || 0)}px`,
      width: `${Math.max(0, layout.width || 0)}px`,
      height: `${Math.max(0, layout.height || 0)}px`,
      opacity: style.opacity == null ? "" : String(style.opacity),
      display: style.display === "none" || node.props?.visible === false ? "none" : "",
      zIndex: style.zIndex == null ? "" : String(style.zIndex)
    });
    if (record.exitPosition) {
      element.style.left = `${record.exitPosition.x}px`;
      element.style.top = `${record.exitPosition.y}px`;
    }
    const clickable = Boolean(node.props?.onClick);
    if (clickable) {
      element.setAttribute("role", "button");
      element.tabIndex = namespace || exiting ? -1 : 0;
      element.style.cursor = "pointer";
    } else {
      element.removeAttribute("role");
      element.removeAttribute("tabindex");
      element.style.cursor = "";
    }
    if (node.type === "Scroll") {
      children.style.width = `${Math.max(layout.width || 0, layout.content_width || 0)}px`;
      children.style.height = `${Math.max(layout.height || 0, layout.content_height || 0)}px`;
      element.classList.toggle("hide-scrollbar", node.props?.showScrollbar === false);
    }
    this.renderVisual(record);
    this.renderStates(record, namespace);
    for (const [index, child] of (node.children || []).entries()) {
      this.renderNode(child, children, layout, namespace, exiting);
      const childElement = this.records.get(namespace + child.id).element;
      if (children.children[index] !== childElement) {
        children.insertBefore(childElement, children.children[index] || null);
      }
    }
    this.animations.update(record);
  }

  renderVisual(record) {
    const {node, visual, input} = record;
    const props = node.props || {};
    if (node.type === "Label") {
      if (window.PyreactBitmapFont?.render(visual, node)) return;
      visual.className = "pr-visual pr-label";
      visual.textContent = props.content == null ? "" : String(props.content);
      Object.assign(visual.style, {
        color: props.color || "#fff",
        fontSize: `${props.fontSizePixels || props.fontSize || 14}px`,
        textAlign: props.textAlign || "left",
        textShadow: props.shadow ? "1px 1px 0 #0009" : ""
      });
    } else if (node.type === "Input") {
      input.placeholder = props.placeholder || "";
      input.setAttribute("aria-label", props.placeholder || "Pyreact 输入框");
      const next = props.value == null ? null : String(props.value);
      if (next !== null && next !== input.value && !record.composing && !this.pendingInputs.get(node.id)) {
        const start = input.selectionStart;
        const end = input.selectionEnd;
        input.value = next;
        if (document.activeElement === input) input.setSelectionRange(start, end);
      }
    } else if (node.type === "Image") {
      this.renderImage(record);
    } else if (["Item", "PaperDoll"].includes(node.type)) {
      visual.className = "pr-visual pr-placeholder";
      visual.textContent = `${node.type}\n${props.identifier || props.entityIdentifier || props.skeletonModelName || "游戏原生渲染"}`;
      visual.title = "需要在游戏中确认原生渲染效果";
    }
  }

  renderImage(record) {
    const {node, visual} = record;
    const props = node.props || {};
    const src = node.style?.opacity === 0 ? "" : String(props.src || "");
    const white = /(?:^|\/)white(?:_bg)?(?:\.png)?$/.test(src);
    visual.style.backgroundColor = white || !src ? props.color || "transparent" : "transparent";
    visual.style.transform = props.rotation ? `rotate(${Number(props.rotation)}deg)` : "";
    visual.style.filter = props.grayscale ? "grayscale(1)" : "";
    if (record.image) {
      record.image.style.objectFit = props.resizeMode === "contain" ? "contain" : props.resizeMode === "cover" ? "cover" : "fill";
    }
    if (record.src === src) return;
    record.src = src;
    visual.replaceChildren();
    if (!src || white) return;
    const image = document.createElement("img");
    record.image = image;
    image.className = "pr-image";
    image.alt = src;
    image.draggable = false;
    image.style.objectFit = props.resizeMode === "contain" ? "contain" : props.resizeMode === "cover" ? "cover" : "fill";
    image.src = `/assets/${src.replace(/^\/+/, "").split("/").map(encodeURIComponent).join("/")}`;
    image.addEventListener("error", () => {
      const missing = document.createElement("div");
      missing.className = "pr-visual pr-placeholder";
      missing.textContent = `缺少纹理\n${src}`;
      image.replaceWith(missing);
    });
    visual.append(image);
  }

  renderStates(record, namespace) {
    const {node, element, children} = record;
    for (const state of ["default", "hover", "pressed"]) {
      const tree = node.states?.[state] || node.states?.default;
      if (!tree) {
        record.states[state]?.remove();
        delete record.states[state];
        continue;
      }
      let host = record.states[state];
      if (!host) {
        host = document.createElement("div");
        host.className = "pr-state";
        host.dataset.state = state;
        host.setAttribute("aria-hidden", "true");
        host.inert = true;
        element.insertBefore(host, children);
        record.states[state] = host;
      }
      this.renderNode(tree, host, node.layout, `${namespace}${node.id}:${state}:`, record.exiting);
    }
  }
};

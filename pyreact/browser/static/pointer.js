/* Pointer capture preserves dragging outside a control or the canvas. */
"use strict";

window.PreviewPointer = class PreviewPointer {
  constructor(canvas, onEvent) {
    this.canvas = canvas;
    this.onEvent = onEvent;
    this.sequence = 0;
    this.active = new Map();
    window.addEventListener("blur", () => this.cancelAll(7));
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) this.cancelAll(7);
    });
  }

  coordinates(record, event) {
    const rect = this.canvas.getBoundingClientRect();
    const width = parseFloat(this.canvas.style.width) || this.canvas.clientWidth;
    const height = parseFloat(this.canvas.style.height) || this.canvas.clientHeight;
    let x = (event.clientX - rect.left) * width / (rect.width || width);
    let y = (event.clientY - rect.top) * height / (rect.height || height);
    for (let parent = record.element.parentElement; parent && parent !== this.canvas; parent = parent.parentElement) {
      x += parent.scrollLeft || 0;
      y += parent.scrollTop || 0;
    }
    return {TouchPosX: x, TouchPosY: y};
  }

  send(record, event, type) {
    const value = {...this.coordinates(record, event), TouchEvent: type,
      pointerId: event.pointerId, sequence: ++this.sequence};
    this.onEvent({id: record.node.id, event: "touch", value});
  }

  bind(record) {
    const element = record.element;
    element.addEventListener("pointerdown", event => {
      if (!record.node.props?.onTouch || record.exiting || (event.button !== 0 && event.pointerType === "mouse")) return;
      event.stopPropagation();
      event.preventDefault();
      // Controls such as Slider have a single dragging state.
      if ([...this.active.values()].some(item => item.record === record)) return;
      this.active.set(event.pointerId, {record, event});
      element.setPointerCapture(event.pointerId);
      element.dataset.pressed = "true";
      this.send(record, event, 1);
    });
    element.addEventListener("pointermove", event => {
      const active = this.active.get(event.pointerId);
      if (active?.record !== record) return;
      event.stopPropagation();
      event.preventDefault();
      active.event = event;
      const rect = element.getBoundingClientRect();
      const inside = event.clientX >= rect.left && event.clientX <= rect.right && event.clientY >= rect.top && event.clientY <= rect.bottom;
      this.send(record, event, inside ? 4 : 6);
    });
    for (const [name, type] of [["pointerup", 0], ["pointercancel", 3], ["lostpointercapture", 3]]) {
      element.addEventListener(name, event => {
        if (this.active.get(event.pointerId)?.record !== record) return;
        event.stopPropagation();
        this.finish(event.pointerId, event, type);
      });
    }
  }

  finish(id, event, type, notify = true) {
    const active = this.active.get(id);
    if (!active) return;
    this.active.delete(id);
    delete active.record.element.dataset.pressed;
    if (notify) this.send(active.record, event || active.event, type);
    if (active.record.element.hasPointerCapture(id)) active.record.element.releasePointerCapture(id);
  }

  cancelAll(type = 3, record = null, notify = true) {
    for (const [id, active] of this.active) {
      if (!record || record === active.record) this.finish(id, null, type, notify);
    }
  }
};

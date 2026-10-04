/* Local animation clock: snapshots describe runs, never individual frames. */
"use strict";

window.PreviewAnimations = class PreviewAnimations {
  constructor(onComplete) {
    this.onComplete = onComplete;
    this.active = new Set();
    this.frame = null;
  }

  static easing(name, t) {
    const curves = {
      linear: x => x,
      easeInQuad: x => x * x,
      easeOutQuad: x => x * (2 - x),
      easeInOutQuad: x => x < .5 ? 2 * x * x : -1 + (4 - 2 * x) * x,
      easeInCubic: x => x * x * x,
      easeOutCubic: x => (x - 1) ** 3 + 1,
      easeInOutCubic: x => x < .5 ? 4 * x ** 3 : .5 * (2 * x - 2) ** 3 + 1,
      easeInBack: x => x * x * (2.70158 * x - 1.70158),
      easeOutBack: x => (x - 1) ** 2 * (2.70158 * (x - 1) + 1.70158) + 1
    };
    return (curves[name] || curves.easeOutQuad)(Math.max(0, Math.min(1, t)));
  }

  baseline(record, key) {
    if (key === "width" || key === "height") return record.node.layout?.[key] || 0;
    return key === "opacity" || key === "alpha" ? 1 : 0;
  }

  update(record) {
    const spec = record.node.animation;
    const previous = record.animation;
    if (!spec) {
      this.remove(record);
      if (record.exiting && previous) {
        this.apply(record, previous.values);
        return;
      }
      record.animation = null;
      record.element.style.visibility = "";
      this.apply(record, {});
      return;
    }
    if (previous?.runId !== spec.runId) {
      if (previous && !previous.done) this.sample(record, performance.now());
      const from = {}, to = {};
      for (const key of new Set([...Object.keys(spec.from || {}), ...Object.keys(spec.to || {})])) {
        const baseline = this.baseline(record, key);
        from[key] = spec.phase === "exit"
          ? spec.from?.[key] ?? previous?.values[key] ?? baseline
          : previous?.values[key] ?? spec.from?.[key] ?? baseline;
        to[key] = spec.to?.[key] ?? baseline;
      }
      record.animation = {...spec, from, to, values: {...previous?.values, ...from},
        start: performance.now(), done: false};
      record.element.style.visibility = "";
      this.active.add(record);
      if (!(spec.duration > 0) && !(spec.delay > 0)) this.sample(record, performance.now());
      this.schedule();
    }
    this.apply(record, record.animation.values);
  }

  apply(record, values) {
    const {element, node} = record;
    const clamp = n => Math.max(0, Math.min(1, n));
    const baseOpacity = node.style?.opacity ?? 1;
    element.style.opacity = String(clamp(baseOpacity) * clamp(values.opacity ?? 1));
    element.style.transform = `translate(${values.translateX || 0}px, ${values.translateY || 0}px)`;
    // Native alpha affects this control and direct children, whereas opacity
    // affects the entire subtree. Visual layers avoid cascading alpha twice.
    const alpha = clamp(values.alpha ?? 1);
    element.style.setProperty("--pr-own-alpha", alpha);
    for (const child of record.children.children) child.style.setProperty("--pr-parent-alpha", alpha);
    if (node.type !== "Label") {
      for (const key of ["width", "height"]) {
        if (values[key] !== undefined) element.style[key] = `${Math.max(0, values[key])}px`;
      }
    }
  }

  sample(record, now) {
    const animation = record.animation;
    const elapsed = now - animation.start - Math.max(0, animation.delay || 0);
    const duration = Math.max(0, animation.duration || 0);
    const progress = elapsed < 0 ? 0 : duration ? Math.min(1, elapsed / duration) : 1;
    let eased = PreviewAnimations.easing(animation.easing, progress);
    if (animation.easingSamples?.length > 1) {
      const samples = animation.easingSamples;
      const position = progress * (samples.length - 1);
      const index = Math.min(samples.length - 2, Math.floor(position));
      eased = samples[index] + (samples[index + 1] - samples[index]) * (position - index);
    }
    for (const key of Object.keys(animation.to)) {
      animation.values[key] = animation.from[key] + (animation.to[key] - animation.from[key]) * eased;
    }
    this.apply(record, animation.values);
    return elapsed >= 0 && progress === 1;
  }

  schedule() {
    if (this.frame !== null) return;
    this.frame = requestAnimationFrame(now => {
      this.frame = null;
      for (const record of this.active) {
        if (!this.sample(record, now)) continue;
        record.animation.done = true;
        this.active.delete(record);
        if (record.animation.phase === "exit") record.element.style.visibility = "hidden";
        this.onComplete({id: record.node.id, event: "animation_complete", value: {runId: record.animation.runId}});
      }
      if (this.active.size) this.schedule();
    });
  }

  remove(record) {
    this.active.delete(record);
    if (!this.active.size && this.frame !== null) {
      cancelAnimationFrame(this.frame);
      this.frame = null;
    }
  }
};

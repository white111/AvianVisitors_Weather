/* Legacy Safari shims for the 1st-gen iPad Air (iOS 12, Safari 12).
 *
 * apt.js and stamps.js call a few DOM APIs that Safari 12 does not have.
 * Without them, opening the menu, a bird postcard or the Atlas throws and
 * the page stops responding. Each shim below only installs when the API is
 * missing, so modern browsers run the original code paths untouched.
 *
 * Loaded first, before every other script in index.html. ES5 only. */
(function () {
  'use strict';
  var EP = window.Element && Element.prototype;
  if (!EP) return;

  // ---- ParentNode.replaceChildren (Safari 14) ----
  function replaceChildren() {
    while (this.lastChild) this.removeChild(this.lastChild);
    if (arguments.length) this.append.apply(this, arguments);
  }
  [EP, window.DocumentFragment && DocumentFragment.prototype].forEach(function (proto) {
    if (proto && !proto.replaceChildren) proto.replaceChildren = replaceChildren;
  });

  // ---- Element.animate (Web Animations, Safari 13.1) ----
  // No motion on Safari 12: the element keeps its CSS state and the returned
  // object reports completion after the requested duration, so code that
  // chains work on `finished` / `onfinish` still runs in the same order.
  if (!EP.animate) {
    EP.animate = function (keyframes, options) {
      var duration = typeof options === 'number' ? options
        : (options && +options.duration) || 0;
      var delay = (options && typeof options === 'object' && +options.delay) || 0;
      var anim = {
        playState: 'running', currentTime: 0, effect: null, id: '',
        onfinish: null, oncancel: null, _listeners: { finish: [], cancel: [] }
      };
      var resolveFinished, rejectFinished, timer = null;
      anim.finished = new Promise(function (res, rej) { resolveFinished = res; rejectFinished = rej; });
      anim.ready = Promise.resolve(anim);
      function emit(type) {
        var ev = { type: type, target: anim, currentTime: anim.currentTime };
        var handler = anim['on' + type];
        if (typeof handler === 'function') handler.call(anim, ev);
        anim._listeners[type].slice().forEach(function (fn) { fn.call(anim, ev); });
      }
      function done() {
        if (anim.playState !== 'running') return;
        clearTimeout(timer);
        anim.playState = 'finished';
        anim.currentTime = duration;
        emit('finish');
        resolveFinished(anim);
      }
      anim.finish = done;
      anim.cancel = function () {
        if (anim.playState === 'idle') return;
        var wasRunning = anim.playState === 'running';
        clearTimeout(timer);
        anim.playState = 'idle';
        anim.currentTime = null;
        if (wasRunning) {
          anim.finished.catch(function () {});
          rejectFinished(new Error('AbortError'));
          emit('cancel');
        }
      };
      anim.pause = function () { if (anim.playState === 'running') { clearTimeout(timer); anim.playState = 'paused'; } };
      anim.play = function () {
        if (anim.playState === 'paused') { anim.playState = 'running'; timer = setTimeout(done, 0); }
      };
      anim.reverse = function () {};
      anim.persist = function () {};
      anim.commitStyles = function () {};
      anim.updatePlaybackRate = function () {};
      anim.addEventListener = function (type, fn) { if (anim._listeners[type]) anim._listeners[type].push(fn); };
      anim.removeEventListener = function (type, fn) {
        var list = anim._listeners[type]; if (!list) return;
        var i = list.indexOf(fn); if (i >= 0) list.splice(i, 1);
      };
      timer = setTimeout(done, Math.max(0, duration + delay));
      return anim;
    };
  }
  if (!EP.getAnimations) EP.getAnimations = function () { return []; };

  // ---- Pointer events (Safari 13) ----
  // Re-dispatch touch and mouse input as pointerdown/move/up/cancel so the
  // menu, outside-tap-to-close and drag handlers work. Pointer capture is a
  // no-op: touch events already keep their original target.
  if (!window.PointerEvent) {
    if (!EP.setPointerCapture) EP.setPointerCapture = function () {};
    if (!EP.releasePointerCapture) EP.releasePointerCapture = function () {};
    if (!EP.hasPointerCapture) EP.hasPointerCapture = function () { return false; };

    var lastTouch = 0;
    var fire = function (type, src, point, target, pointerType, id) {
      if (!target || !target.dispatchEvent) return;
      var ev = document.createEvent('Event');
      ev.initEvent(type, true, type !== 'pointercancel');
      ev.pointerId = id;
      ev.pointerType = pointerType;
      ev.isPrimary = true;
      ev.width = 1; ev.height = 1; ev.pressure = type === 'pointerup' ? 0 : 0.5;
      ev.clientX = point.clientX; ev.clientY = point.clientY;
      ev.pageX = point.pageX; ev.pageY = point.pageY;
      ev.screenX = point.screenX; ev.screenY = point.screenY;
      ev.button = pointerType === 'mouse' ? (src.button || 0) : (type === 'pointermove' ? -1 : 0);
      ev.buttons = pointerType === 'mouse' ? (src.buttons || 0) : (type === 'pointerdown' || type === 'pointermove' ? 1 : 0);
      ev.shiftKey = src.shiftKey; ev.ctrlKey = src.ctrlKey; ev.altKey = src.altKey; ev.metaKey = src.metaKey;
      ev.detail = 0;
      // Only a cancelled move stops the page from scrolling, matching how
      // drag handlers use preventDefault on real pointermove events.
      var prevent = ev.preventDefault;
      ev.preventDefault = function () {
        prevent.call(ev);
        if (type === 'pointermove' && src.cancelable) src.preventDefault();
      };
      target.dispatchEvent(ev);
    };
    var touchMap = { touchstart: 'pointerdown', touchmove: 'pointermove', touchend: 'pointerup', touchcancel: 'pointercancel' };
    Object.keys(touchMap).forEach(function (touchType) {
      document.addEventListener(touchType, function (ev) {
        lastTouch = Date.now();
        var list = ev.changedTouches || [];
        for (var i = 0; i < list.length; i++) {
          var t = list[i];
          fire(touchMap[touchType], ev, t, t.target, 'touch', t.identifier + 2);
        }
      }, { capture: true, passive: false });
    });
    var mouseMap = { mousedown: 'pointerdown', mousemove: 'pointermove', mouseup: 'pointerup' };
    Object.keys(mouseMap).forEach(function (mouseType) {
      document.addEventListener(mouseType, function (ev) {
        // iOS follows a tap with emulated mouse events; skip those.
        if (Date.now() - lastTouch < 1000) return;
        fire(mouseMap[mouseType], ev, ev, ev.target, 'mouse', 1);
      }, true);
    });
  }

  // ---- MediaQueryList.addEventListener (Safari 14) ----
  var MQL = window.MediaQueryList && MediaQueryList.prototype;
  if (MQL && !MQL.addEventListener && MQL.addListener) {
    MQL.addEventListener = function (type, fn) { if (type === 'change') this.addListener(fn); };
    MQL.removeEventListener = function (type, fn) { if (type === 'change') this.removeListener(fn); };
  }
})();

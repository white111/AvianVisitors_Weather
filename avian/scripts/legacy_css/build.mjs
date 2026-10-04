// Build avian/frontend/styles.legacy.css for iOS 12 Safari (1st-gen iPad Air).
//
// Safari 12 drops whole declarations it cannot parse, so modern CSS in
// styles.css silently disappears there: `inset` (absolutely positioned
// overlays collapse), `clamp()` (sizes fall back to nothing), `color-mix()`
// (hairlines and tints vanish), `place-*`, and `dvh` units. This script
// rewrites styles.css into an equivalent sheet Safari 12 understands. The
// frontend swaps to it only when the browser fails CSS.supports('inset', '0'),
// so modern browsers keep loading styles.css unchanged.
//
// Re-run after any change to styles.css (for example after syncing upstream):
//   cd avian/scripts/legacy_css && npm ci && npm run build
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import postcss from 'postcss';
import presetEnv from 'postcss-preset-env';

const here = path.dirname(fileURLToPath(import.meta.url));
const frontend = path.resolve(here, '../../frontend');
const src = path.join(frontend, 'styles.css');
const out = path.join(frontend, 'styles.legacy.css');

// ---- color-mix() -> precomputed rgba() ----
// Safari 12 has no color-mix(). Each mix in styles.css blends theme tokens
// (custom properties), literal colors, transparent or currentColor in sRGB.
// Mixes of literals become an rgba() inline. Mixes that read a token become
// their own custom property, defined in every rule that defines one of its
// tokens (the light :root, the dark theme, card scopes), so the precomputed
// value follows the theme the same way the token does. currentColor cannot be
// known ahead of time and is approximated with the --ink token.
const MIX_START = 'color-mix(';

function parseColor(value) {
  value = value.trim();
  let m = value.match(/^#([0-9a-f]{3,8})$/i);
  if (m) {
    let h = m[1];
    if (h.length <= 4) h = h.split('').map((c) => c + c).join('');
    const n = (i) => parseInt(h.slice(i, i + 2), 16);
    return [n(0), n(2), n(4), h.length === 8 ? n(6) / 255 : 1];
  }
  m = value.match(/^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:[\s,/]+([\d.]+%?))?\s*\)$/i);
  if (m) {
    let a = m[4] === undefined ? 1 : m[4];
    if (typeof a === 'string') a = a.endsWith('%') ? parseFloat(a) / 100 : parseFloat(a);
    return [+m[1], +m[2], +m[3], a];
  }
  if (value === 'transparent') return [0, 0, 0, 0];
  if (value === 'white') return [255, 255, 255, 1];
  if (value === 'black') return [0, 0, 0, 1];
  return null;
}

// Split "a, b, c" at top-level commas.
function splitTop(str) {
  const parts = []; let depth = 0, cur = '';
  for (const ch of str) {
    if (ch === '(') depth++;
    if (ch === ')') depth--;
    if (ch === ',' && depth === 0) { parts.push(cur.trim()); cur = ''; } else cur += ch;
  }
  parts.push(cur.trim());
  return parts;
}

// Parse the inside of one color-mix(...) into two {color, pct} stops.
function parseMix(inner) {
  const parts = splitTop(inner);
  if (parts.length !== 3 || !/^in\s+srgb$/i.test(parts[0])) return null;
  const stop = (txt) => {
    const m = txt.match(/^(.*?)(?:\s+([\d.]+)%)?$/);
    let color = m[1].trim();
    if (/^currentcolor$/i.test(color)) color = 'var(--ink)';
    return { color, pct: m[2] === undefined ? null : +m[2] };
  };
  const a = stop(parts[1]), b = stop(parts[2]);
  if (a.pct === null && b.pct === null) { a.pct = 50; b.pct = 50; }
  else if (a.pct === null) a.pct = 100 - b.pct;
  else if (b.pct === null) b.pct = 100 - a.pct;
  return [a, b];
}

function tokensOf(stops) {
  const out = [];
  for (const s of stops) {
    const m = s.color.match(/^var\(--([\w-]+)\)$/);
    if (m) out.push(m[1]);
  }
  return out;
}

// CSS Color 5 sRGB mixing with premultiplied alpha.
function mixColors(c1, p1, c2, p2) {
  const sum = p1 + p2;
  const w1 = p1 / sum, w2 = p2 / sum;
  const alphaMult = Math.min(sum, 100) / 100;
  const a = c1[3] * w1 + c2[3] * w2;
  if (a === 0) return [0, 0, 0, 0];
  const ch = (i) => Math.round((c1[i] * c1[3] * w1 + c2[i] * c2[3] * w2) / a);
  return [ch(0), ch(1), ch(2), +(a * alphaMult).toFixed(4)];
}
const rgbaText = (c) => `rgba(${c[0]}, ${c[1]}, ${c[2]}, ${c[3]})`;

// Replace every color-mix(...) in a value, innermost first.
function rewriteMixes(value, onMix) {
  for (;;) {
    const at = value.lastIndexOf(MIX_START);
    if (at < 0) return value;
    let depth = 0, end = -1;
    for (let i = at + MIX_START.length - 1; i < value.length; i++) {
      if (value[i] === '(') depth++;
      if (value[i] === ')' && --depth === 0) { end = i; break; }
    }
    if (end < 0) return value;
    const inner = value.slice(at + MIX_START.length, end);
    const replacement = onMix(inner);
    if (replacement === null) return value;
    value = value.slice(0, at) + replacement + value.slice(end + 1);
  }
}

function colorMixPlugin() {
  return {
    postcssPlugin: 'legacy-color-mix',
    Once(root, { result }) {
      // Token definitions per rule, used to resolve var() chains such as
      // --card-panel: var(--paper) against the rule, falling back to :root.
      const defsBy = new Map();
      root.walkDecls(/^--/, (decl) => {
        const rule = decl.parent;
        if (!defsBy.has(rule)) defsBy.set(rule, {});
        defsBy.get(rule)[decl.prop.slice(2)] = decl.value;
      });
      const rootDefs = {};
      for (const [rule, defs] of defsBy) {
        if (rule.selector && rule.selector.trim() === ':root') Object.assign(rootDefs, defs);
      }
      const resolveColor = (defs, text, depth = 0) => {
        const ref = text.trim().match(/^var\(--([\w-]+)\)$/);
        if (!ref) return parseColor(text);
        if (depth > 6) return null;
        const raw = defs[ref[1]] ?? rootDefs[ref[1]];
        return raw === undefined ? null : resolveColor(defs, raw, depth + 1);
      };
      const evalMix = (defs, stops) => {
        const c1 = resolveColor(defs, stops[0].color);
        const c2 = resolveColor(defs, stops[1].color);
        return c1 && c2 ? mixColors(c1, stops[0].pct, c2, stops[1].pct) : null;
      };

      const generated = new Map(); // name -> stops
      let counter = 0;
      root.walkDecls((decl) => {
        if (!decl.value.includes(MIX_START)) return;
        decl.value = rewriteMixes(decl.value, (inner) => {
          // Nested mixes were already rewritten into var(--cm-N) tokens.
          const stops = parseMix(inner);
          if (!stops) {
            result.warn(`unhandled color-mix(${inner})`, { node: decl });
            return null;
          }
          if (!tokensOf(stops).length) {
            const c = evalMix({}, stops);
            if (c) return rgbaText(c);
            result.warn(`cannot evaluate color-mix(${inner})`, { node: decl });
            return null;
          }
          const name = `--cm-${++counter}`;
          generated.set(name, stops);
          return `var(${name})`;
        });
      });

      // Generated tokens can reference other generated tokens (nesting), so
      // treat them as definable everywhere their source tokens are defined.
      const deps = (name, seen = new Set()) => {
        const out = new Set();
        for (const t of tokensOf(generated.get(name))) {
          const full = `--${t}`;
          if (generated.has(full) && !seen.has(full)) {
            seen.add(full);
            for (const d of deps(full, seen)) out.add(d);
          } else out.add(t);
        }
        return out;
      };
      const defined = new Set();
      for (const [rule, defs] of defsBy) {
        const local = { ...defs };
        for (const [name, stops] of generated) {
          const touches = [...deps(name)].some((t) => t in defs);
          if (!touches && !(rule.selector && rule.selector.trim() === ':root')) continue;
          const c = evalMix(local, stops);
          if (!c) continue;
          local[name.slice(2)] = rgbaText(c);
          rule.append({ prop: name, value: rgbaText(c) });
          defined.add(name);
        }
      }
      for (const name of generated.keys()) {
        if (!defined.has(name)) result.warn(`${name} was never defined`);
      }
    },
  };
}
colorMixPlugin.postcss = true;

// ---- dynamic viewport units -> vh ----
// Safari 12 has no dvh/svh/lvh. Plain vh is the closest it understands.
function viewportUnitsPlugin() {
  return {
    postcssPlugin: 'legacy-viewport-units',
    Declaration(decl) {
      if (/\d[dsl]vh\b/.test(decl.value)) {
        decl.value = decl.value.replace(/(\d)[dsl]vh\b/g, '$1vh');
      }
    },
  };
}
viewportUnitsPlugin.postcss = true;

// ---- flex gap -> sibling margins ----
// Safari 12 lays out `gap` only for grid; flex containers ignore it and their
// children touch. For single-line flex rules whose direction is known, space
// the children with a margin on every child after the first instead. The
// extra rule sits right after the container rule, so later, more specific
// child rules in styles.css still win.
function flexGapPlugin() {
  return {
    postcssPlugin: 'legacy-flex-gap',
    Once(root) {
      root.walkRules((rule) => {
        if (rule.parent && rule.parent.type === 'atrule' && /keyframes/i.test(rule.parent.name)) return;
        let display = null, gap = null, rowGap = null, colGap = null, dir = 'row', wrap = false;
        rule.each((d) => {
          if (d.type !== 'decl') return;
          if (d.prop === 'display') display = d.value.trim();
          if (d.prop === 'gap') gap = d.value.trim();
          if (d.prop === 'row-gap') rowGap = d.value.trim();
          if (d.prop === 'column-gap') colGap = d.value.trim();
          if (d.prop === 'flex-direction') dir = d.value.trim();
          if (d.prop === 'flex-wrap' && d.value.trim() !== 'nowrap') wrap = true;
          if (d.prop === 'flex-flow') {
            if (/column/.test(d.value)) dir = 'column';
            if (/\bwrap/.test(d.value)) wrap = true;
          }
        });
        if (!display || !/^(inline-)?flex$/.test(display) || wrap) return;
        let parts = gap ? gap.split(/\s+/) : [];
        let row = rowGap || parts[0], col = colGap || parts[1] || parts[0];
        const vertical = /column/.test(dir);
        const size = vertical ? row : col;
        if (!size || /^0(px|rem|em)?$/.test(size)) return;
        const reverse = /reverse/.test(dir);
        const side = vertical ? (reverse ? 'margin-bottom' : 'margin-top')
          : (reverse ? 'margin-right' : 'margin-left');
        const selector = rule.selectors.map((sel) => `${sel} > * + *`).join(',\n  ');
        rule.after(rule.clone({ selector, nodes: [] }).append({ prop: side, value: size }));
      });
    },
  };
}
flexGapPlugin.postcss = true;

const css = fs.readFileSync(src, 'utf8');
const result = await postcss([
  colorMixPlugin(),
  viewportUnitsPlugin(),
  flexGapPlugin(),
  presetEnv({
    browsers: 'iOS >= 12',
    stage: 2,
    // Leave custom properties alone: Safari 12 supports them and the theme
    // switch depends on them staying live.
    features: { 'custom-properties': false },
    preserve: false,
  }),
]).process(css, { from: src, to: out });

for (const w of result.warnings()) console.warn('warning:', w.toString());
const header = '/* GENERATED by avian/scripts/legacy_css/build.mjs from styles.css - do not edit.\n'
  + '   Loaded instead of styles.css on browsers without CSS `inset` (iOS 12 Safari). */\n';
fs.writeFileSync(out, header + result.css);
console.log(`wrote ${path.relative(process.cwd(), out)} (${result.css.length} bytes)`);

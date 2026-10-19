/* Weather badge for the collage: ThermoPro sensor readings plus the local
 * forecast.
 *
 * Sensors come from /avian/api/thermopro.php (avian-thermopro service),
 * the forecast from /avian/api/forecast.php (place set in Settings).
 * Plain ES5 + XMLHttpRequest so it runs on the 1st-gen iPad Air (iOS 12).
 * Stays hidden until there is something fresh to show.
 */
(function () {
  'use strict';

  var SENSOR_URL = './avian/api/thermopro.php';
  var FORECAST_URL = './avian/api/forecast.php';
  var SENSOR_POLL_MS = 60000;
  var FORECAST_POLL_MS = 15 * 60000;
  var SENSOR_STALE_S = 15 * 60;
  var OPEN_KEY = 'avian:weather:open';
  var DAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

  // 16x16 line icons drawn with currentColor, matching the menu icons.
  var CLOUD = '<path d="M4.6 11.5h6.9a2.6 2.6 0 0 0 .3-5.2 3.6 3.6 0 0 0-6.9.9 2.2 2.2 0 0 0-.3 4.3z"/>';
  var ICONS = {
    sun: '<circle cx="8" cy="8" r="2.9"/><path d="M8 1.6v1.6M8 12.8v1.6M1.6 8h1.6M12.8 8h1.6M3.5 3.5l1.1 1.1M11.4 11.4l1.1 1.1M3.5 12.5l1.1-1.1M11.4 4.6l1.1-1.1"/>',
    moon: '<path d="M12.6 10.2A5.2 5.2 0 0 1 5.8 3.4a5.2 5.2 0 1 0 6.8 6.8z"/>',
    partly: '<path d="M5.4 2.2v1.1M2.1 5.5h1.1M3 3.1l.8.8M7.8 3.1l-.8.8"/><path d="M3.6 7.3a2.2 2.2 0 0 1 3.9-1.8"/>'
      + '<path d="M6 13h6.2a2.3 2.3 0 0 0 .3-4.6 3.2 3.2 0 0 0-6.1.8A2 2 0 0 0 6 13z"/>',
    cloud: CLOUD,
    fog: '<path d="M2.5 6h11M1.5 8.6h13M2.5 11.2h11"/>',
    rain: '<path d="M4.6 9.3h6.9a2.6 2.6 0 0 0 .3-5.2 3.6 3.6 0 0 0-6.9.9 2.2 2.2 0 0 0-.3 4.3z"/><path d="M5.5 11.2l-.7 1.8M8.3 11.2l-.7 1.8M11.1 11.2l-.7 1.8"/>',
    snow: '<path d="M4.6 9.3h6.9a2.6 2.6 0 0 0 .3-5.2 3.6 3.6 0 0 0-6.9.9 2.2 2.2 0 0 0-.3 4.3z"/><path d="M5.4 11.6v.1M8 12.6v.1M10.6 11.6v.1M6.7 14v.1M9.3 14v.1"/>',
    storm: '<path d="M4.6 9.3h6.9a2.6 2.6 0 0 0 .3-5.2 3.6 3.6 0 0 0-6.9.9 2.2 2.2 0 0 0-.3 4.3z"/><path d="M8.6 10.2l-1.8 2.4h2.2l-1.6 2.3"/>',
  };
  var CHEVRON = '<path d="M5 6.5L8 9.5l3-3"/>';
  // Half sun on the horizon with an arrow: up for sunrise, down for sunset.
  var SUNRISE = '<path d="M1.5 12.5h13M4.6 12.5a3.4 3.4 0 0 1 6.8 0M8 2v4.2M6.2 3.8L8 2l1.8 1.8"/>';
  var SUNSET = '<path d="M1.5 12.5h13M4.6 12.5a3.4 3.4 0 0 1 6.8 0M8 2v4.2M6.2 4.4L8 6.2l1.8-1.8"/>';

  // The moon as it looks tonight: outline plus the lit part, bounded by the
  // limb on one side and the terminator (a half-ellipse) on the other.
  // Waxing is lit on the right, as seen from the northern hemisphere.
  function moonIcon(phase) {
    var r = 5.6, cx = 8, top = 8 - r, bottom = 8 + r;
    var outline = '<circle cx="8" cy="8" r="' + r + '"/>';
    var lit = (1 - Math.cos(2 * Math.PI * phase)) / 2;
    if (lit < 0.03) return svg(outline, 'tp-icon tp-moon');
    if (lit > 0.97) {
      return svg('<circle cx="8" cy="8" r="' + r + '" fill="currentColor"/>', 'tp-icon tp-moon');
    }
    var waxing = phase < 0.5;
    var rx = (r * Math.abs(Math.cos(2 * Math.PI * phase))).toFixed(2);
    var gibbous = lit > 0.5;
    // Limb: top to bottom down the lit side. Terminator: bottom back to top,
    // bulging toward the lit side for a crescent, away from it for gibbous.
    var limbSweep = waxing ? 1 : 0;
    var termSweep = waxing ? (gibbous ? 1 : 0) : (gibbous ? 0 : 1);
    var d = 'M' + cx + ' ' + top + 'A' + r + ' ' + r + ' 0 0 ' + limbSweep + ' ' + cx + ' ' + bottom
      + 'A' + rx + ' ' + r + ' 0 0 ' + termSweep + ' ' + cx + ' ' + top + 'Z';
    return svg(outline + '<path d="' + d + '" fill="currentColor" stroke="none"/>', 'tp-icon tp-moon');
  }

  // WMO weather codes used by Open-Meteo.
  function describe(code, isDay) {
    if (code === 0) return { icon: isDay === false ? 'moon' : 'sun', text: 'Clear' };
    if (code === 1) return { icon: isDay === false ? 'moon' : 'partly', text: 'Mostly clear' };
    if (code === 2) return { icon: 'partly', text: 'Partly cloudy' };
    if (code === 3) return { icon: 'cloud', text: 'Overcast' };
    if (code === 45 || code === 48) return { icon: 'fog', text: 'Fog' };
    if (code >= 51 && code <= 55) return { icon: 'rain', text: 'Drizzle' };
    if (code === 56 || code === 57 || code === 66 || code === 67) return { icon: 'rain', text: 'Freezing rain' };
    if (code === 61) return { icon: 'rain', text: 'Light rain' };
    if (code === 63) return { icon: 'rain', text: 'Rain' };
    if (code === 65) return { icon: 'rain', text: 'Heavy rain' };
    if (code >= 71 && code <= 77) return { icon: 'snow', text: 'Snow' };
    if (code >= 80 && code <= 82) return { icon: 'rain', text: 'Showers' };
    if (code === 85 || code === 86) return { icon: 'snow', text: 'Snow showers' };
    if (code >= 95 && code <= 99) return { icon: 'storm', text: 'Thunderstorms' };
    return { icon: 'cloud', text: '' };
  }

  function svg(paths, cls) {
    return '<svg class="' + cls + '" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3"'
      + ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' + paths + '</svg>';
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function readOpen() {
    try { return window.localStorage.getItem(OPEN_KEY) === '1'; } catch (e) { return false; }
  }
  function writeOpen(open) {
    try { window.localStorage.setItem(OPEN_KEY, open ? '1' : '0'); } catch (e) { /* private mode */ }
  }

  function dayName(date, index) {
    if (index === 0) return 'Today';
    var parts = String(date).split('-');
    var d = new Date(+parts[0], +parts[1] - 1, +parts[2]);
    return isNaN(d.getTime()) ? '' : DAY_NAMES[d.getDay()];
  }

  function toUnits(tempC, units) {
    return units === 'C' ? tempC : tempC * 9 / 5 + 32;
  }

  var COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];

  // "NW 6 mph" (or km/h with Celsius); gusts are added when the sensor reports them.
  function windText(sensor, units) {
    var avg = typeof sensor.wind_avg_kmh === 'number' ? sensor.wind_avg_kmh : null;
    var max = typeof sensor.wind_max_kmh === 'number' ? sensor.wind_max_kmh : null;
    if (avg === null && max === null) return '';
    var factor = units === 'C' ? 1 : 0.621371;
    var unit = units === 'C' ? ' km/h' : ' mph';
    var dir = typeof sensor.wind_dir_deg === 'number' ? COMPASS[Math.round(sensor.wind_dir_deg / 22.5) % 16] + ' ' : '';
    if (avg !== null && avg < 1 && (max === null || max < 1)) return 'calm';
    var text = dir + Math.round((avg !== null ? avg : max) * factor);
    if (avg !== null && max !== null && max > avg) text += '\u2013' + Math.round(max * factor);
    return text + unit;
  }

  // Rain today from a rain gauge: "0.12 in" (or mm with Celsius), "dry" when none.
  function rainText(sensor, units) {
    if (typeof sensor.rain_today_mm !== 'number') return '';
    if (sensor.rain_today_mm <= 0) return 'dry today';
    if (units === 'C') return sensor.rain_today_mm.toFixed(1) + ' mm today';
    return (sensor.rain_today_mm / 25.4).toFixed(2) + ' in today';
  }

  // Two small panels: the forecast with sunrise, sunset and the moon (bottom
  // left), and your own sensors (bottom right). Each hides when it has
  // nothing fresh to show.
  var badge = el('aside', 'tp-badge');
  badge.id = 'tpBadge';
  badge.setAttribute('aria-label', 'Forecast');
  badge.hidden = true;
  document.body.appendChild(badge);
  var sensorBadge = el('aside', 'tp-badge tp-sensor-panel');
  sensorBadge.id = 'tpSensors';
  sensorBadge.setAttribute('aria-label', 'Weather sensors');
  sensorBadge.hidden = true;
  document.body.appendChild(sensorBadge);
  var panels = [badge, sensorBadge];

  var sensorData = null;
  var forecastData = null;
  var open = readOpen();

  function freshSensors() {
    var list = (sensorData && sensorData.sensors) || [];
    var fresh = [];
    for (var i = 0; i < list.length; i++) {
      var s = list[i];
      if (s && s.age_s <= SENSOR_STALE_S && (typeof s.temp_c === 'number' || windText(s, 'F') || rainText(s, 'F'))) fresh.push(s);
    }
    return fresh;
  }

  function forecastReady() {
    return !!(forecastData && forecastData.ok && forecastData.enabled
      && forecastData.days && forecastData.days.length);
  }

  function renderSensors(sensors, units) {
    var wrap = el('div', 'tp-sensors');
    for (var j = 0; j < sensors.length; j++) {
      var sensor = sensors[j];
      var row = el('div', 'tp-row');
      row.appendChild(el('span', 'tp-label', sensor.label));
      if (typeof sensor.temp_c === 'number') {
        row.appendChild(el('span', 'tp-temp', Math.round(toUnits(sensor.temp_c, units)) + '°'));
      }
      if (typeof sensor.humidity === 'number') row.appendChild(el('span', 'tp-hum', sensor.humidity + '%'));
      var wind = windText(sensor, units);
      if (wind) row.appendChild(el('span', 'tp-wind', wind));
      var rain = rainText(sensor, units);
      if (rain) row.appendChild(el('span', 'tp-wind tp-rain', rain));
      row.title = sensor.label + ' · updated ' + Math.round(sensor.age_s / 60) + ' min ago';
      wrap.appendChild(row);
    }
    return wrap;
  }

  function renderForecast(showNow) {
    var data = forecastData;
    var today = data.days[0];
    var current = data.current;
    var look = describe(current ? current.code : today.code, current ? current.is_day : true);

    var summary = el('button', 'tp-today');
    summary.type = 'button';
    summary.setAttribute('aria-expanded', open ? 'true' : 'false');
    summary.setAttribute('aria-controls', 'tpDays');
    summary.title = data.place + (data.stale ? ' · forecast may be out of date' : '');
    summary.innerHTML = svg(ICONS[look.icon], 'tp-icon');
    if (showNow && current) summary.appendChild(el('span', 'tp-now', current.temp + '°'));
    if (look.text) summary.appendChild(el('span', 'tp-cond', look.text));
    summary.appendChild(el('span', 'tp-hilo', today.hi + '° / ' + today.lo + '°'));
    var chevron = el('span', 'tp-chevron');
    chevron.innerHTML = svg(CHEVRON, 'tp-chevron-icon');
    summary.appendChild(chevron);
    summary.addEventListener('click', function () {
      open = !open;
      writeOpen(open);
      render();
    });

    var days = el('div', 'tp-days');
    days.id = 'tpDays';
    days.hidden = !open;
    for (var i = 0; i < data.days.length; i++) {
      var day = data.days[i];
      var dayLook = describe(day.code, true);
      var col = el('div', 'tp-day');
      col.title = dayLook.text;
      col.appendChild(el('span', 'tp-dname', dayName(day.date, i)));
      var icon = el('span', 'tp-dicon');
      icon.innerHTML = svg(ICONS[dayLook.icon], 'tp-icon');
      col.appendChild(icon);
      col.appendChild(el('span', 'tp-dhi', day.hi + '°'));
      col.appendChild(el('span', 'tp-dlo', day.lo + '°'));
      col.appendChild(el('span', 'tp-dpop', typeof day.pop === 'number' && day.pop >= 20 ? day.pop + '%' : ' '));
      days.appendChild(col);
    }
    var place = el('div', 'tp-place', data.place + ' · °' + data.units);
    days.appendChild(place);

    var wrap = el('div', 'tp-forecast');
    wrap.appendChild(summary);
    wrap.appendChild(days);
    return wrap;
  }

  // "6:42 am" with °F, "06:42" with °C.
  function clockText(ms, units) {
    var t = new Date(ms), h = t.getHours(), m = t.getMinutes();
    var mm = (m < 10 ? '0' : '') + m;
    if (units === 'C') return (h < 10 ? '0' : '') + h + ':' + mm;
    return ((h + 11) % 12 + 1) + ':' + mm + (h < 12 ? ' am' : ' pm');
  }

  // Sunrise, sunset and the moon, from the sun/moon maths in apt.js.
  function renderSky(units) {
    var sky = window.__avianSky;
    var where = sky && sky.location();
    if (!where) return null;
    var now = Date.now();
    var row = el('div', 'tp-sky');
    var times = sky.sunTimes(now, where.lat, where.lon);
    if (times) {
      var rise = el('span', 'tp-sun');
      rise.innerHTML = svg(SUNRISE, 'tp-icon');
      rise.appendChild(document.createTextNode(clockText(times.rise, units)));
      rise.title = 'Sunrise';
      var set = el('span', 'tp-sun');
      set.innerHTML = svg(SUNSET, 'tp-icon');
      set.appendChild(document.createTextNode(clockText(times.set, units)));
      set.title = 'Sunset';
      row.appendChild(rise);
      row.appendChild(set);
    }
    var moon = sky.moonPhase(now);
    var moonEl = el('span', 'tp-moonphase');
    moonEl.innerHTML = moonIcon(moon.phase);
    moonEl.appendChild(document.createTextNode(moon.name));
    moonEl.title = moon.name + ' · ' + moon.lit + '% lit';
    row.appendChild(moonEl);
    return row;
  }

  function render() {
    var sensors = freshSensors();
    var hasForecast = forecastReady();
    var units = hasForecast ? forecastData.units : (sensorData && sensorData.units === 'C' ? 'C' : 'F');
    var hadFocus = document.activeElement && badge.contains(document.activeElement);

    // Sensors panel.
    while (sensorBadge.firstChild) sensorBadge.removeChild(sensorBadge.firstChild);
    if (sensors.length) sensorBadge.appendChild(renderSensors(sensors, units));
    sensorBadge.hidden = !sensors.length;

    // Forecast panel: today (with the current temperature), the 5-day strip
    // when opened, and the sun and moon line.
    while (badge.firstChild) badge.removeChild(badge.firstChild);
    var skyRow = renderSky(units);
    if (hasForecast) badge.appendChild(renderForecast(true));
    if (skyRow) badge.appendChild(skyRow);
    badge.classList.toggle('tp-open', hasForecast && open);
    badge.hidden = !hasForecast && !skyRow;

    stackOnPhone();
    // New content can change a panel's size; make sure it still fits clear.
    if (floatWanted()) placeFloat(false);
    if (hadFocus) {
      var again = badge.querySelector('.tp-today');
      if (again) again.focus();
    }
  }

  // Phones put the forecast panel under the top bar; this class lets the
  // page title make room for it (see thermopro.css).
  function stackOnPhone() {
    document.documentElement.classList.toggle('tp-forecast-shown', !badge.hidden);
  }

  // ---- Floating badge ----
  // With Settings > Float weather on, the badge leaves its corner and sits in
  // the open space between the birds: after each collage render it steps
  // aside if a bird now sits under it, and every few minutes it drifts to
  // another clear spot (which also spreads wear on an always-on screen).
  // Phones and the stats/atlas views keep the corner.
  var FLOAT_KEY = 'avian:weather:float';
  var FLOAT_DRIFT_MS = 5 * 60000;
  var FLOAT_STEP = 24;
  var floatTouched = 0;      // last tap on a panel; hold still for a while after
  function floatWanted() {
    var on = false;
    try { on = window.localStorage.getItem(FLOAT_KEY) === 'on'; } catch (e) { on = false; }
    return on && window.innerWidth > 700;
  }
  function visibleRect(node) {
    if (!node) return null;
    var r = node.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return null;
    if (r.right <= 0 || r.left >= window.innerWidth || r.bottom <= 0 || r.top >= window.innerHeight) return null;
    return r;
  }
  function collageShowing() {
    var r = visibleRect(document.getElementById('collage'));
    return !!r && r.left > -window.innerWidth / 3 && r.left < window.innerWidth / 3;
  }
  // Things a panel must not cover: every bird, the empty-nest picture, the
  // title, the on-screen controls and the other panel (with a margin).
  function obstacles(panel) {
    var list = [], pad = 10, i, r;
    var birds = document.querySelectorAll('#collage .gtile, #collage .empty-nest img, #collage .empty-nest .empty');
    for (i = 0; i < birds.length; i++) {
      r = visibleRect(birds[i]);
      if (r) list.push({ l: r.left, t: r.top, r: r.right, b: r.bottom, w: 1 });
    }
    var chrome = document.querySelectorAll('.top, .menu-shell, .slider, .static-head h1');
    for (i = 0; i < chrome.length; i++) {
      r = visibleRect(chrome[i]);
      if (r) list.push({ l: r.left - pad, t: r.top - pad, r: r.right + pad, b: r.bottom + pad, w: 50 });
    }
    for (i = 0; i < panels.length; i++) {
      var other = panels[i];
      if (other === panel || other.hidden) continue;
      var at = other.__floatPos;
      if (at) {
        list.push({ l: at.x - pad, t: at.y - pad, r: at.x + other.offsetWidth + pad, b: at.y + other.offsetHeight + pad, w: 50 });
      } else if ((r = visibleRect(other))) {
        list.push({ l: r.left - pad, t: r.top - pad, r: r.right + pad, b: r.bottom + pad, w: 50 });
      }
    }
    return list;
  }
  function overlapScore(x, y, w, h, list) {
    var score = 0;
    for (var i = 0; i < list.length; i++) {
      var o = list[i];
      var dx = Math.min(x + w, o.r) - Math.max(x, o.l);
      var dy = Math.min(y + h, o.b) - Math.max(y, o.t);
      if (dx > 0 && dy > 0) score += dx * dy * o.w;
    }
    return score;
  }
  // Best spots for a w x h panel: the least-covered positions on a grid,
  // keeping a margin from the screen edges.
  function clearSpots(w, h, list) {
    var margin = 16, spots = [], best = Infinity;
    var maxX = window.innerWidth - w - margin, maxY = window.innerHeight - h - margin;
    for (var y = margin; y <= maxY; y += FLOAT_STEP) {
      for (var x = margin; x <= maxX; x += FLOAT_STEP) {
        var s = overlapScore(x, y, w, h, list);
        if (s < best) best = s;
        spots.push({ x: x, y: y, s: s });
      }
    }
    var good = [];
    for (var i = 0; i < spots.length; i++) if (spots[i].s <= best + 1) good.push(spots[i]);
    return good;
  }
  function placePanel(panel, drift) {
    if (panel.hidden) { unfloatPanel(panel); return; }
    if (panel.contains(document.activeElement)) return;
    var w = panel.offsetWidth, h = panel.offsetHeight;
    if (!w || !h) return;
    var list = obstacles(panel);
    var at = panel.__floatPos;
    // Stay put while the current spot is still clear, unless it is time to drift.
    if (at && !drift && overlapScore(at.x, at.y, w, h, list) <= 1
        && at.x + w <= window.innerWidth && at.y + h <= window.innerHeight) return;
    var spots = clearSpots(w, h, list);
    if (!spots.length) { unfloatPanel(panel); return; }
    // Drift somewhere noticeably different, not one grid step over.
    var far = [];
    for (var i = 0; at && i < spots.length; i++) {
      if (Math.abs(spots[i].x - at.x) + Math.abs(spots[i].y - at.y) > 160) far.push(spots[i]);
    }
    var pool = far.length ? far : spots;
    var pick = pool[Math.floor(Math.random() * pool.length)];
    panel.__floatPos = { x: pick.x, y: pick.y };
    panel.classList.add('tp-float');
    panel.style.left = pick.x + 'px';
    panel.style.top = pick.y + 'px';
  }
  function placeFloat(drift) {
    if (!floatWanted() || !collageShowing()) { unfloat(); return; }
    if (Date.now() - floatTouched < 60000) return;
    for (var i = 0; i < panels.length; i++) placePanel(panels[i], drift);
  }
  function unfloatPanel(panel) {
    if (!panel.classList.contains('tp-float')) return;
    panel.__floatPos = null;
    panel.classList.remove('tp-float');
    panel.style.left = '';
    panel.style.top = '';
  }
  function unfloat() {
    for (var i = 0; i < panels.length; i++) unfloatPanel(panels[i]);
    stackOnPhone();
  }
  function forgetSpots() {
    for (var i = 0; i < panels.length; i++) panels[i].__floatPos = null;
  }
  badge.addEventListener('click', function () { floatTouched = Date.now(); });
  sensorBadge.addEventListener('click', function () { floatTouched = Date.now(); });
  window.addEventListener('avian:collage-rendered', function () { setTimeout(function () { placeFloat(false); }, 50); });
  window.addEventListener('avian:weather-float-changed', function () { forgetSpots(); placeFloat(true); });
  window.addEventListener('resize', function () {
    forgetSpots();
    setTimeout(function () { stackOnPhone(); placeFloat(false); }, 150);
  });
  setInterval(function () { placeFloat(true); }, FLOAT_DRIFT_MS);

  function getJson(url, done) {
    var xhr = new XMLHttpRequest();
    xhr.open('GET', url + (url.indexOf('?') < 0 ? '?' : '&') + 't=' + Date.now(), true);
    xhr.timeout = 15000;
    xhr.onload = function () {
      var body = null;
      try { body = JSON.parse(xhr.responseText); } catch (e) { body = null; }
      done(xhr.status, body);
    };
    xhr.onerror = xhr.ontimeout = function () { done(0, null); };
    xhr.send();
  }

  function pollSensors() {
    getJson(SENSOR_URL, function (status, body) {
      if (status === 200 && body) { sensorData = body; render(); }
    });
  }
  function pollForecast() {
    getJson(FORECAST_URL, function (status, body) {
      if (body && (status === 200 || status === 503)) {
        // The forecast place (or station) also sets where sunrise is worked out.
        if (body.sky && window.__avianSky) window.__avianSky.setLocation(body.sky.lat, body.sky.lon);
        // Keep the last good forecast through a temporary outage.
        if (body.ok || body.enabled === false || !forecastReady()) forecastData = body;
        render();
      }
    });
  }

  pollSensors();
  pollForecast();
  setInterval(pollSensors, SENSOR_POLL_MS);
  setInterval(pollForecast, FORECAST_POLL_MS);
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) return;
    pollSensors();
    pollForecast();
  });
  // Settings > Local forecast announces changes so the badge follows at once.
  window.addEventListener('avian:forecast-changed', pollForecast);
  // Settings > Weather sensors does the same for names and show/hide.
  window.addEventListener('avian:sensors-changed', pollSensors);

  // Exposed for tests only.
  window.__avianWeather = { describe: describe, dayName: dayName, render: render, windText: windText, rainText: rainText,
    moonIcon: moonIcon, clockText: clockText, placeFloat: placeFloat };
})();

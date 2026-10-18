/* ThermoPro weather badge for the collage.
 *
 * Shows the latest TP-60S / TX-2 sensor readings from
 * /avian/api/thermopro.php (fed by the avian-thermopro service).
 * Plain ES5 + XMLHttpRequest so it runs on the 1st-gen iPad Air (iOS 12).
 * Stays hidden until there is a fresh reading.
 */
(function () {
  'use strict';

  var URL = './avian/api/thermopro.php';
  var POLL_MS = 60000;
  var STALE_S = 15 * 60;

  var badge = document.createElement('aside');
  badge.className = 'tp-badge';
  badge.id = 'tpBadge';
  badge.setAttribute('aria-label', 'Temperature');
  badge.setAttribute('aria-live', 'polite');
  badge.hidden = true;
  document.body.appendChild(badge);

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function formatTemp(tempC, units) {
    var value = units === 'C' ? tempC : tempC * 9 / 5 + 32;
    return Math.round(value) + '\u00b0' + units;
  }

  function render(data) {
    var units = data && data.units === 'C' ? 'C' : 'F';
    var list = (data && data.sensors) || [];
    var fresh = [];
    for (var i = 0; i < list.length; i++) {
      var s = list[i];
      if (s && typeof s.temp_c === 'number' && s.age_s <= STALE_S) fresh.push(s);
    }
    while (badge.firstChild) badge.removeChild(badge.firstChild);
    if (!fresh.length) { badge.hidden = true; return; }

    for (var j = 0; j < fresh.length; j++) {
      var sensor = fresh[j];
      var row = el('div', 'tp-row');
      if (fresh.length > 1) row.appendChild(el('span', 'tp-label', sensor.label));
      row.appendChild(el('span', 'tp-temp', formatTemp(sensor.temp_c, units)));
      if (typeof sensor.humidity === 'number') {
        row.appendChild(el('span', 'tp-hum', sensor.humidity + '%'));
      }
      row.title = sensor.label + ' \u00b7 updated ' + Math.round(sensor.age_s / 60) + ' min ago';
      badge.appendChild(row);
    }
    badge.hidden = false;
  }

  function poll() {
    var xhr = new XMLHttpRequest();
    xhr.open('GET', URL + '?t=' + Date.now(), true);
    xhr.timeout = 10000;
    xhr.onload = function () {
      if (xhr.status !== 200) return;
      try { render(JSON.parse(xhr.responseText)); } catch (e) { /* keep last view */ }
    };
    xhr.send();
  }

  poll();
  setInterval(poll, POLL_MS);
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) poll();
  });
})();

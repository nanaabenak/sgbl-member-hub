/* Member Hub interactions - external file so the strict CSP never needs unsafe-inline. */
(function () {
  'use strict';

  var root = document.documentElement;
  var stored = null;
  try { stored = localStorage.getItem('sgbl.theme'); } catch (e) { /* private mode */ }
  if (stored === 'dark' || stored === 'light') root.setAttribute('data-theme', stored);

  function currentTheme() {
    var explicit = root.getAttribute('data-theme');
    if (explicit) return explicit;
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  document.addEventListener('click', function (event) {
    var target = event.target;
    if (!(target instanceof Element)) return;

    var themeButton = target.closest('[data-theme-toggle]');
    if (themeButton) {
      var next = currentTheme() === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      try { localStorage.setItem('sgbl.theme', next); } catch (e) { /* ignore */ }
      themeButton.textContent = next === 'dark' ? '☀ light' : '◐ dark';
      event.preventDefault();
      return;
    }

    var copyButton = target.closest('[data-copy]');
    if (copyButton) {
      var value = copyButton.getAttribute('data-copy') || '';
      var done = function () {
        var old = copyButton.textContent;
        copyButton.textContent = 'copied';
        setTimeout(function () { copyButton.textContent = old; }, 1600);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(value).then(done, function () { /* ignore */ });
      }
      event.preventDefault();
    }
  });

  document.addEventListener('submit', function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    var confirmMessage = form.getAttribute('data-confirm');
    if (confirmMessage && !window.confirm(confirmMessage)) event.preventDefault();
  });

  document.addEventListener('change', function (event) {
    var el = event.target;
    if (el instanceof HTMLSelectElement && el.hasAttribute('data-autosubmit')) {
      if (el.form) el.form.submit();
    }
  });

  var toggle = document.querySelector('[data-theme-toggle]');
  if (toggle) toggle.textContent = currentTheme() === 'dark' ? '☀ light' : '◐ dark';

  var flashes = document.querySelectorAll('.flash');
  if (flashes.length) {
    setTimeout(function () {
      flashes.forEach(function (el) { el.style.opacity = '0'; });
    }, 8000);
  }

  // Restore the Builder Card's living staircase: one quiet cell at a time.
  var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var stairs = document.querySelectorAll('.stair');
  if (!reduceMotion && stairs.length) {
    stairs.forEach(function (stair) {
      var cols = [0, 1, 2, 3, 4, 5].map(function (col) {
        return Array.prototype.filter.call(stair.children, function (el, i) {
          return i % 6 === col && !el.classList.contains('g');
        });
      });
      var step = 0;
      var pick = function (list) { return list[Math.random() * list.length | 0]; };
      setTimeout(function () {
        setInterval(function () {
          var col = cols[step++ % 6];
          var lit = col.filter(function (el) { return el.classList.contains('on'); });
          var off = col.filter(function (el) { return !el.classList.contains('on'); });
          if (lit.length && (lit.length > 1 || Math.random() < .55)) pick(lit).classList.remove('on');
          else if (off.length && Math.random() < .7) pick(off).classList.add('on');
        }, 380);
      }, 1800);
    });
  }
})();

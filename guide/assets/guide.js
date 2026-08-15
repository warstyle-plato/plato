/* Руководство /guide: вкладки, шаги, навигация, поиск.
 *
 * Контента скрипт не порождает — весь текст в разметке; здесь только
 * поведение. Прогресс шагов живёт в localStorage этого браузера.
 */
(function () {
  'use strict';

  /* Вкладки способов ввода: role=tablist, стрелки, aria-selected. */
  var tabs = Array.prototype.slice.call(document.querySelectorAll('.gtabs [role=tab]'));
  function selectTab(tab) {
    tabs.forEach(function (other) {
      var pane = document.getElementById(other.getAttribute('aria-controls'));
      var active = other === tab;
      other.setAttribute('aria-selected', active ? 'true' : 'false');
      other.tabIndex = active ? 0 : -1;
      if (pane) pane.hidden = !active;
    });
    tab.focus();
  }
  tabs.forEach(function (tab, index) {
    tab.addEventListener('click', function () { selectTab(tab); });
    tab.addEventListener('keydown', function (event) {
      var delta = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
      if (!delta) return;
      event.preventDefault();
      selectTab(tabs[(index + delta + tabs.length) % tabs.length]);
    });
  });

  /* Шаги первого расчёта: назад/дальше, «шаг выполнен», прогресс в localStorage. */
  var STORE_KEY = 'developaid_guide_v1';
  var steps = Array.prototype.slice.call(document.querySelectorAll('.gstep'));
  var current = 0;
  var state = { done: {}, step: 0 };
  try { state = Object.assign(state, JSON.parse(localStorage.getItem(STORE_KEY) || '{}')); } catch (e) { }
  function saveState() {
    state.step = current;
    try { localStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch (e) { }
  }
  var doneBox = document.getElementById('gstepDone');
  var label = document.getElementById('gstepLabel');
  var bar = document.getElementById('gstepBar');
  function renderStep() {
    steps.forEach(function (step, index) { step.hidden = index !== current; });
    if (label) label.textContent = 'Шаг ' + (current + 1) + ' из ' + steps.length;
    if (doneBox) doneBox.checked = !!state.done[current + 1];
    if (bar) {
      var done = Object.keys(state.done).filter(function (k) { return state.done[k]; }).length;
      bar.style.width = Math.round(done * 100 / steps.length) + '%';
    }
    saveState();
  }
  var prev = document.getElementById('gstepPrev');
  var next = document.getElementById('gstepNext');
  if (prev) prev.onclick = function () { if (current > 0) { current -= 1; renderStep(); } };
  if (next) next.onclick = function () {
    // «Дальше» и отмечает шаг: пройти вперёд и значит выполнить.
    state.done[current + 1] = true;
    if (current < steps.length - 1) current += 1;
    renderStep();
  };
  if (doneBox) doneBox.onchange = function () {
    state.done[current + 1] = doneBox.checked;
    renderStep();
  };
  if (steps.length) {
    current = Math.min(Math.max(Number(state.step) || 0, 0), steps.length - 1);
    renderStep();
  }

  /* Навигация: подсветка активного раздела и общий прогресс просмотра. */
  var links = Array.prototype.slice.call(document.querySelectorAll('#gnavList a'));
  var seen = {};
  var progressBar = document.getElementById('gprogressBar');
  function sectionOf(link) {
    return document.getElementById((link.getAttribute('href') || '').slice(1));
  }
  if ('IntersectionObserver' in window && links.length) {
    var byId = {};
    links.forEach(function (link) { byId[(link.getAttribute('href') || '').slice(1)] = link; });
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        seen[entry.target.id] = true;
        links.forEach(function (link) { link.classList.remove('active'); });
        var link = byId[entry.target.id];
        if (link) link.classList.add('active');
        if (progressBar) {
          progressBar.style.width =
            Math.round(Object.keys(seen).length * 100 / links.length) + '%';
        }
      });
    }, { rootMargin: '-20% 0px -60% 0px' });
    links.forEach(function (link) {
      var section = sectionOf(link);
      if (section) observer.observe(section);
    });
  }

  /* Поиск: фильтрует пункты навигации по тексту их разделов. */
  var search = document.getElementById('gsearch');
  if (search) {
    search.addEventListener('input', function () {
      var query = search.value.trim().toLowerCase();
      links.forEach(function (link) {
        var section = sectionOf(link);
        var haystack = ((section ? section.textContent : '') + ' ' + link.textContent).toLowerCase();
        link.classList.toggle('gmiss', !!query && haystack.indexOf(query) < 0);
      });
    });
  }
})();

/* Слой перестройки /ia.
 *
 * Страница остаётся той же: тот же движок, те же поля, тот же путь расчёта.
 * Слой двигает уже существующие узлы и сокращает тексты — это перестановка
 * информационной архитектуры, а не вторая реализация страницы.
 *
 * Два правила, из которых собран весь файл.
 *
 * 1. Селектор живёт парой с диагностикой. Слой держится на чужой разметке;
 *    если узел переименуют, шаг обязан сказать об этом на экране. Молчаливое
 *    «не сработало» на preview неотличимо от «так и задумано».
 * 2. Поведение не переписывается. Переключение раздела кликает настоящую
 *    кнопку вкладки, а не повторяет её onclick: у вкладок есть побочные
 *    действия (renderPhasing, renderSensitivityForm), и вторая их копия
 *    разошлась бы с первой в первый же день.
 */
(function () {
  'use strict';

  var missing = [];
  /* «План и риски» из первоначального разбора не пережил первого взгляда
     владельца: очередность — это устройство проекта, а не риск. Разделы
     названы тем, что внутри: очередность и календарь — сроки, чувствительность
     — анализ результата, и живёт рядом с отчётом. */
  /* Разделы — это шаги, и человека ведут по ним (решение владельца):
     вперёд — кнопкой «Далее», назад — свободно, перескочить нельзя.
     Деление: слева вводишь, справа смотришь. ВРИ и кривая ключевой ставки —
     вводные, поэтому в «Экономике»; вкладка финансирования — таблицы БРИДЖа,
     ПФ и LLCR, то есть результат. «Пересчитать модель» и «Открыть пример»
     открывают отчёт и потому разблокируют путь целиком. */
  /* Структура владельца: три раздела, шаги внутри. «Проект» — что строим:
     участок, ТЭП, очередность. «Экономика» — на каких условиях: вводные по
     стройке, продажам и сделке, ВРИ, процентная ставка. «Результат» — что
     вышло. Кнопка «Далее» ведёт по шагам как проводник, но ничего не заперто:
     «просто посмотреть» можно всё и сразу — замечание владельца. */
  var SECTIONS = [
    { id: 'project', label: 'Проект', tabs: ['iaSite', 'tep', 'phasing'] },
    { id: 'economics', label: 'Экономика', tabs: ['inputs', 'vri', 'rates'] },
    { id: 'result', label: 'Результат', tabs: ['report', 'sensitivity'] }
  ];
  /* Финансирование и календарь отдельными вкладками были дублями: в отчёте
     оба живут разделами с оглавлением (rsFinance, rsCalendar) — «зачем блок
     финансирование там? он такой же в отчёте». Панели остаются в разметке и
     наполняются расчётом, но навигация ведёт в отчёт. Чувствительность — не
     дубль, а инструмент: там задают параметр и запускают анализ. */
  var RETIRED_TABS = ['finance', 'calendar'];
  var PATH = [];
  SECTIONS.forEach(function (section) { section.tabs.forEach(function (t) { PATH.push(t); }); });
  // Путь ведёт к ответу и на ответе заканчивается: «Далее» после отчёта
  // предлагал чувствительность как следующий шаг, хотя это инструмент по
  // желанию, а не стадия (замечание владельца).
  PATH = PATH.slice(0, PATH.indexOf('report') + 1);
  var SUB_LABEL = {
    iaSite: 'Участок', tep: 'ТЭП', vri: 'ВРИ', inputs: 'Вводные',
    rates: 'Ключевая ставка', finance: 'Финансирование',
    phasing: 'Очередность', calendar: 'Календарь', sensitivity: 'Чувствительность',
    report: 'Отчёт'
  };
  var TARGET_LLCR = 1.2;

  function need(selector, what) {
    var el = document.querySelector(selector);
    if (!el) missing.push(what + ' — ' + selector);
    return el;
  }

  function step(name, fn) {
    try {
      fn();
    } catch (error) {
      missing.push(name + ' — ' + (error && error.message ? error.message : error));
    }
  }

  /* Замена текста объявляет, что именно она рассчитывала найти: строка в
     разметке может уехать, и тогда на экране останется прежняя формулировка,
     а понять это со стороны нельзя. */
  function retext(selector, from, to) {
    var el = document.querySelector(selector);
    if (!el) { missing.push('текст «' + from + '» — ' + selector); return; }
    if (el.textContent.trim().indexOf(from) !== 0) {
      missing.push('текст «' + from + '» изменился — ' + selector + ': «' + el.textContent.trim().slice(0, 60) + '»');
      return;
    }
    el.textContent = to;
  }

  /* Данные страницы объявлены через let/const: свойствами window они не
     становятся и видны только по имени. Через window.lastResult слой читал бы
     undefined — и карточка решения вечно показывала бы «расчёт не выполнен».
     Форматтеры money/mult/pct — тоже const, поэтому берутся так же. */
  function pageResult() { return typeof lastResult === 'undefined' ? null : lastResult; }
  function pageGlavapu() { return typeof glavapuImport === 'undefined' ? null : glavapuImport; }
  function pendingGlavapu() {
    var box = document.getElementById('glavapuPreview');
    return !!(box && box.style.display !== 'none' && typeof window.applyGlavapu === 'function');
  }
  function pageInputs() { return typeof inputs === 'undefined' ? {} : inputs; }
  function pageTep() { return typeof tep === 'undefined' ? {} : tep; }
  function pageRates() { return typeof rates === 'undefined' ? [] : rates; }
  function pagePhasing() { return typeof phasing === 'undefined' ? {} : phasing; }

  var fmtMoney = function (v) { return typeof money === 'function' ? money(v) : String(v); };
  var fmtMult = function (v) { return typeof mult === 'function' ? mult(v) : String(v); };
  var fmtPct = function (v) { return typeof pct === 'function' ? pct(v) : String(v); };

  /* Цены в подборе приходят в млн ₽ — так их держит и вводная
     purchase_price_mln. Слой их не переводит: перевод единиц — это уже вторая
     реализация экономики, а разница цен приезжает из движка полем change_abs. */
  function mlnLabel(value) {
    if (value == null || isNaN(value)) return '—';
    return Number(value).toLocaleString('ru-RU', { maximumFractionDigits: 1 }) + ' млн ₽';
  }

  /* ------------------------------------------------------------------ */
  /* Шапка                                                               */
  /* ------------------------------------------------------------------ */

  function rebuildHeader() {
    var sub = need('.title p', 'подзаголовок шапки');
    if (sub) {
      var version = (sub.textContent.match(/v[\d.]+/) || [''])[0];
      sub.innerHTML = '';
      sub.appendChild(document.createTextNode(
        'Оценка экономики девелоперского проекта по адресу или кадастровому номеру'));
      if (version) {
        var badge = document.createElement('span');
        badge.className = 'ia-ver';
        badge.textContent = version;
        sub.appendChild(badge);
      }
    }

    var actions = need('.actions', 'кнопки шапки');
    if (!actions) return;

    // Состояние расчёта занимает левый край шапки: инструкция «после ручного
    // изменения нажмите Пересчитать» жила в постоянном абзаце, хотя это
    // состояние, а не правило.
    var state = document.createElement('div');
    state.className = 'ia-state';
    state.id = 'iaState';
    state.innerHTML = '<span class="ia-dot-state"></span><span id="iaStateText">Расчёт актуален</span>';
    actions.parentNode.insertBefore(state, actions);

    // Платон — плавающей кнопкой. Он объясняет результат, а не вводит данные,
    // и в ряду с «Сохранить» и «Сбросить» читался как равный им по важности.
    var ai = document.querySelector('.ai-open-btn');
    if (!ai) missing.push('кнопка Платона — .ai-open-btn');
    else {
      ai.classList.add('ia-fab');
      ai.classList.remove('btn');
      document.body.appendChild(ai);
      // «Платон Сергеевич» в углу читался как подпись автора, а не как
      // помощник, — никто не понимал, что там спрятан AI. Подпись говорит,
      // что это и зачем, и не прячется на телефоне.
      var label = ai.querySelector('.ai-label');
      if (!label) missing.push('подпись кнопки Платона — .ai-open-btn .ai-label');
      else label.textContent = 'Платон · AI-помощник';
      var bubble = document.createElement('div');
      bubble.className = 'ia-fab-hint';
      bubble.id = 'iaFabHint';
      bubble.innerHTML = 'Это AI-помощник по модели: разложит LLCR, найдёт потолок цены, '
        + 'проверит аномалии. Числа считает движок, а не языковая модель.'
        + '<button type="button" aria-label="Понятно">×</button>';
      document.body.appendChild(bubble);
      var hide = function () { bubble.remove(); };
      bubble.querySelector('button').onclick = hide;
      ai.addEventListener('click', hide);
    }

    // Класс и сценарий уезжают в «Экономику»: их спрашивали раньше, чем
    // человек ввёл участок.
    var setup = document.createElement('div');
    setup.className = 'ia-setup';
    document.querySelectorAll('.actions .scenario').forEach(function (node) { setup.appendChild(node); });

    var note = document.querySelector('.header-note');
    if (!note) missing.push('абзац о классе и сценарии — .header-note');
    else {
      var box = document.createElement('details');
      box.className = 'ia-method';
      box.innerHTML = '<summary>Как считаются класс и сценарий</summary>';
      note.parentNode.removeChild(note);
      box.appendChild(note);
      // Цифры классов — из PROJECT_CLASS_PRESETS страницы, не копией:
      // пояснение без конкретных чисел не объясняло ничего (замечание
      // владельца), а вторая копия чисел разъехалась бы с первой.
      if (typeof PROJECT_CLASS_PRESETS !== 'undefined') {
        var fmtN = function (v) { return Number(v).toLocaleString('ru-RU'); };
        var rows = Object.keys(PROJECT_CLASS_PRESETS).map(function (key) {
          var c = PROJECT_CLASS_PRESETS[key];
          return '<tr><td>' + c.label + '</td><td>' + fmtN(c.apartment_price_th) + ' / '
            + fmtN(c.commercial_price_th) + '</td><td>' + fmtN(c.parking_price_th) + '</td><td>'
            + fmtN(c.main_above_th_per_sqm) + ' / ' + fmtN(c.main_under_th_per_sqm) + '</td></tr>';
        }).join('');
        var table = document.createElement('div');
        table.innerHTML = '<table class="ia-class-table"><thead><tr><th>Класс</th>'
          + '<th>Квартиры / коммерция, тыс ₽/м²</th><th>Машино-место, тыс ₽</th>'
          + '<th>Себестоимость назем. / подзем., тыс ₽/м²</th></tr></thead><tbody>' + rows + '</tbody></table>'
          + '<div style="font-size:11px;color:#777;margin:6px 0 10px">Сценарий применяется поверх: '
          + 'Базовый — цены 100%, затраты 100% · Консервативный — цены −10%, затраты +10% · '
          + 'Оптимистичный — цены +10%, затраты −10%.</div>';
        box.appendChild(table);
      } else {
        missing.push('таблица классов — PROJECT_CLASS_PRESETS не найдены');
      }
      setup.appendChild(box);
    }

    var host = document.querySelector('#inputs .card');
    if (!host) missing.push('карточка вводных — #inputs .card');
    else {
      var card = document.createElement('div');
      card.className = 'card';
      card.innerHTML = '<div class="section-title">Класс проекта и сценарий</div>';
      card.appendChild(setup);
      host.parentNode.insertBefore(card, host);
    }

    // «Сбросить» остаётся открытой кнопкой: защита от случайного клика — это
    // подтверждение, а меню «⋯» из одного пункта было глупостью — клик
    // отнимало, а защиты не добавляло (замечание владельца).
    var reset = Array.prototype.filter.call(actions.querySelectorAll('button'), function (b) {
      return b.textContent.trim() === 'Сбросить';
    })[0];
    if (!reset) missing.push('кнопка «Сбросить» в шапке');
    else {
      reset.textContent = 'Сбросить проект';
      reset.setAttribute('data-ia-confirm', '1');
    }
  }

  /* Сброс подтверждается: он стирает весь проект, а стоял кнопкой рядом с
     «Сохранить». Обёртка ставится на onclick, чтобы не переписывать resetAll. */
  function guardReset() {
    var reset = document.querySelector('[data-ia-confirm]');
    if (!reset) return;
    var original = reset.onclick;
    reset.onclick = function (event) {
      if (!window.confirm('Сбросить проект? Введённые вводные, ТЭП и импорт будут потеряны.')) return;
      if (original) return original.call(this, event);
    };
  }

  /* ------------------------------------------------------------------ */
  /* Первый экран: участок отдельной панелью                             */
  /* ------------------------------------------------------------------ */

  function splitSite() {
    var inputs = need('#inputs', 'панель вводных');
    var card = need('#inputs .import-card', 'карточка автозагрузки');
    if (!inputs || !card) return;

    var panel = document.createElement('div');
    panel.id = 'iaSite';
    panel.className = 'panel';
    inputs.parentNode.insertBefore(panel, inputs);
    panel.appendChild(card);

    // openTab ищет кнопку по data-tab: без неё разметка активной вкладки
    // выпадет ровно на новой панели.
    var tabs = document.querySelector('.tabs');
    if (!tabs) { missing.push('строка вкладок — .tabs'); return; }
    var button = document.createElement('button');
    button.className = 'tab';
    button.setAttribute('data-tab', 'iaSite');
    button.textContent = 'Участок';
    button.onclick = function () { window.openTab('iaSite', button); };
    tabs.insertBefore(button, tabs.firstChild);

    retext('#iaSite .import-head h2', 'Кадастровый номер или адрес',
      'Введите адрес или кадастровый номер');
    var lead = document.querySelector('#iaSite .import-head p');
    if (!lead) missing.push('пояснение автозагрузки — #iaSite .import-head p');
    else {
      lead.textContent = 'DevelopAid сам получит сведения ЕГРН и рассчитает нормативные ТЭП: '
        + 'для Москвы — по методике ГлавАПУ, для Московской области — по РНГП. '
        + 'Перед применением значения показываются для проверки.';
    }
    var recognized = document.querySelector('#glavapuPreview .scroll');
    if (!recognized) missing.push('таблица распознанного — #glavapuPreview .scroll');
    else {
      var provenance = document.createElement('details');
      provenance.innerHTML = '<summary style="font-size:13px;padding:8px 0">'
        + 'Что распознано — построчно, с происхождением каждого числа</summary>';
      recognized.parentNode.insertBefore(provenance, recognized);
      provenance.appendChild(recognized);
    }

    retext('#iaSite .import-fallback summary',
      'Свой файл: шаблон ТЭП DevelopAid, выгрузка ГлавАПУ или пресет проекта',
      'Другие способы ввода: свой файл — шаблон ТЭП DevelopAid, выгрузка ГлавАПУ или пресет проекта');

    addExampleButton();

    // Человеку без кадастра и адреса некуда было идти — путь «собрать ТЭП
    // вручную» существовал, но о нём знали только по подсказке на другой
    // вкладке. Теперь он назван кнопкой там, где человек упёрся.
    var actions = document.querySelector('#iaSite .import-actions');
    if (actions) {
      var manual = document.createElement('button');
      manual.className = 'btn';
      manual.type = 'button';
      manual.textContent = 'Нет кадастра — собрать ТЭП вручную';
      manual.onclick = function () {
        var button = tabButton('tep');
        if (button) button.click();
      };
      actions.appendChild(manual);
    }

  }

  /* Холодному пользователю нужен один клик, а не выбор из четырёх способов
     загрузки. Пресеты на сервере уже есть — не было кнопки. */
  function addExampleButton() {
    var actions = document.querySelector('#iaSite .import-actions');
    if (!actions) { missing.push('кнопки автозагрузки — #iaSite .import-actions'); return; }
    var button = document.createElement('button');
    button.className = 'btn ia-example';
    button.type = 'button';
    button.textContent = 'Открыть пример';
    button.onclick = function () {
      var status = document.getElementById('cadastralStatus');
      var input = document.getElementById('presetFile');
      if (!input || typeof window.uploadPreset !== 'function') {
        if (status) status.textContent = 'Импорт пресета на странице не найден.';
        return;
      }
      if (status) status.textContent = 'Открываю пример проекта…';
      // Файл кладётся в тот же ввод, которым пользуется человек, и дальше
      // работает штатный uploadPreset: свой путь импорта разошёлся бы с
      // общим в первый же день, а экран проверки перед применением — не
      // вежливость, а место, где видно, что именно меняется.
      fetch('/ia/example.json').then(function (response) {
        if (!response.ok) throw new Error('пример не отдан, код ' + response.status);
        return response.text();
      }).then(function (text) {
        var transfer = new DataTransfer();
        transfer.items.add(new File([text], 'Пример.json', { type: 'application/json' }));
        input.files = transfer.files;
        if (status) status.textContent = '';
        return window.uploadPreset();
      }).catch(function (error) {
        if (status) status.textContent = 'Пример не открылся: ' + (error && error.message ? error.message : error);
      });
    };
    actions.appendChild(button);
  }

  /* ------------------------------------------------------------------ */
  /* Пять разделов вместо девяти вкладок                                  */
  /* ------------------------------------------------------------------ */

  var navButtons = {};
  var currentSection = null;

  function sectionOf(tabId) {
    for (var i = 0; i < SECTIONS.length; i++) {
      if (SECTIONS[i].tabs.indexOf(tabId) >= 0) return SECTIONS[i];
    }
    return null;
  }

  function tabButton(tabId) {
    return document.querySelector('.tabs [data-tab="' + tabId + '"]');
  }

  function buildNav() {
    var tabs = need('.tabs', 'строка вкладок');
    if (!tabs) return;
    document.body.classList.add('ia-on');

    SECTIONS.forEach(function (section) {
      section.tabs.forEach(function (tabId) {
        if (!tabButton(tabId)) missing.push('вкладка «' + (SUB_LABEL[tabId] || tabId) + '» — [data-tab="' + tabId + '"]');
      });
    });

    var nav = document.createElement('div');
    nav.className = 'ia-nav';
    var sub = document.createElement('div');
    sub.className = 'ia-sub';
    sub.id = 'iaSub';

    SECTIONS.forEach(function (section) {
      var button = document.createElement('button');
      button.type = 'button';
      button.textContent = section.label;
      button.onclick = function () { openSection(section.id); };
      navButtons[section.id] = button;
      nav.appendChild(button);
    });

    tabs.parentNode.insertBefore(nav, tabs);
    tabs.parentNode.insertBefore(sub, tabs.nextSibling);
  }

  function openSection(id, keepTab) {
    var section = SECTIONS.filter(function (s) { return s.id === id; })[0];
    if (!section) return;
    var target = keepTab && section.tabs.indexOf(keepTab) >= 0 ? keepTab : section.tabs[0];
    var button = tabButton(target);
    if (button) button.click();
    syncNav(target);
  }

  function syncNav(activeTab) {
    var section = sectionOf(activeTab);
    if (!section) return;
    currentSection = section.id;
    Object.keys(navButtons).forEach(function (key) {
      navButtons[key].classList.toggle('active', key === section.id);
    });
    var sub = document.getElementById('iaSub');
    if (!sub) return;
    sub.innerHTML = '';
    if (section.tabs.length > 1) {
      section.tabs.forEach(function (tabId) {
        var button = document.createElement('button');
        button.type = 'button';
        button.textContent = SUB_LABEL[tabId] || tabId;
        var info = STEP_INFO[tabId] && STEP_INFO[tabId]();
        if (info && info.mark) {
          var mark = document.createElement('span');
          mark.className = 'ia-mark ' + info.mark;
          mark.textContent = { ok: '✓', warn: '!', need: 'обязательно', opt: 'по желанию' }[info.mark] || '';
          button.appendChild(mark);
        }
        button.className = tabId === activeTab ? 'active' : '';
        button.onclick = function () {
          var original = tabButton(tabId);
          if (original) original.click();
        };
        sub.appendChild(button);
      });
    }
    var pos = PATH.indexOf(activeTab);
    var nextTab = pos >= 0 ? PATH[pos + 1] : null;
    if (nextTab) {
      var forward = document.createElement('button');
      forward.type = 'button';
      forward.className = 'ia-next';
      forward.textContent = 'Далее: ' + (SUB_LABEL[nextTab] || nextTab) + ' →';
      forward.onclick = function () {
        var go = function () { var b = tabButton(nextTab); if (b) b.click(); };
        // Уход с «Участка» вперёд — это принятие данных: загруженный файл
        // применяется сам, отдельное «Применить» не требуется (замечание
        // владельца). Кнопка «Применить» остаётся для тех, кто хочет
        // применить и остаться на месте.
        if (activeTab === 'iaSite' && pendingGlavapu()) {
          forward.disabled = true;
          Promise.resolve(window.applyGlavapu()).then(go, go);
        } else go();
      };
      sub.appendChild(forward);
    }
    var hintInfo = STEP_INFO[activeTab] && STEP_INFO[activeTab]();
    var hintBox = document.getElementById('iaStepHint');
    if (!hintBox) {
      hintBox = document.createElement('div');
      hintBox.id = 'iaStepHint';
      hintBox.className = 'ia-step-hint';
      sub.parentNode.insertBefore(hintBox, sub.nextSibling);
    }
    hintBox.textContent = hintInfo ? hintInfo.hint : '';
    hintBox.style.display = hintInfo ? '' : 'none';
  }

  /* ------------------------------------------------------------------ */
  /* Обязательность шагов                                                 */
  /* ------------------------------------------------------------------ */

  /* «Обязательно» — это не список, а состояние: движок считает с
     умолчаниями почти всё, поэтому обязательно ровно то, что при пропуске
     даёт достоверную неправду. Участок/ТЭП — иначе считаются умолчания
     80 000 м² чужого проекта; цена входа — иначе LLCR посчитан для
     бесплатного участка. Остальное честно помечено «по желанию». */
  function tepTotalGns() {
    var t = pageTep(), sum = 0;
    Object.keys(t || {}).forEach(function (key) { sum += Number((t[key] || {}).gns || 0); });
    return sum;
  }

  var STEP_INFO = {
    iaSite: function () {
      if (pageGlavapu() || (pageInputs() || {})._mo_calc) {
        return { mark: 'ok', hint: 'Участок получен, ТЭП рассчитан. Дальше — проверить его на следующем шаге.' };
      }
      return { mark: 'need', hint: 'Введите кадастровый номер или адрес — ТЭП посчитается сам. Нет кадастра — соберите ТЭП вручную на следующем шаге.' };
    },
    tep: function () {
      if (tepTotalGns() > 0) {
        return { mark: 'ok', hint: 'ТЭП заполнен — проверьте цифры, вручную здесь меняют только фактические значения по проекту.' };
      }
      return { mark: 'need', hint: 'ТЭП пока не рассчитан: укажите площадь и плотность ниже — или вернитесь в «Участок».' };
    },
    phasing: function () {
      var ph = pagePhasing();
      if (ph && ph.enabled && Number(ph.phase_count || 1) > 1) {
        return { mark: 'ok', hint: 'Проект разбит на очереди — сроки, инфляция и цены считаются по каждой.' };
      }
      return { mark: 'opt', hint: 'По желанию: нужен, только если проект строится очередями. Пропустите — посчитается одной очередью.' };
    },
    inputs: function () {
      if (Number((pageInputs() || {}).purchase_price_mln || 0) > 0) {
        return { mark: 'ok', hint: 'Цена входа задана. Проверьте класс, цены продаж и себестоимость — умолчания здесь заданы классом проекта.' };
      }
      return { mark: 'warn', hint: 'Обязательное поле не заполнено: цена входа (стоимость покупки) — 0. Без неё LLCR и решение считаются как для бесплатного участка.' };
    },
    vri: function () {
      var i = pageInputs() || {};
      if (!i.vri_required || !Number(i.land_rights_cost_mln || 0)) {
        return { mark: 'opt', hint: 'По желанию: нужен, только если участку требуется смена ВРИ. Плата 0 — шаг можно пропустить.' };
      }
      return { mark: 'ok', hint: 'Смена ВРИ включена: плата посчитана, проверьте сумму, график и источники оплаты.' };
    },
    rates: function () {
      return { mark: 'opt', hint: 'По желанию: прогноз ключевой ставки уже задан умолчанием. Меняйте, если ваш взгляд на ставку другой — кривая пересчитает проценты БРИДЖа и ПФ.' };
    },
    report: function () {
      return { mark: null, hint: 'Итог: карточка решения сверху, детали — по оглавлению ниже. Любое поле можно вернуться и поменять — расчёт обновится.' };
    },
    sensitivity: function () {
      return { mark: 'opt', hint: 'По желанию: покажет, какие параметры сильнее всего двигают результат, и посчитает ваш сценарий.' };
    }
  };

  /* openTab зовут и мимо навигации — calculateAndOpen('report') после каждого
     пересчёта. Без обёртки раздел в шапке остался бы на прежнем. */
  function wrapOpenTab() {
    var original = window.openTab;
    if (typeof original !== 'function') { missing.push('функция openTab не найдена'); return; }
    window.openTab = function (id, btn) {
      var out = original.apply(this, arguments);
      try {
        syncNav(id);
        if (id === 'tep') annotateTep();
        if (id === 'report') ensureGoalSeek();
      } catch (error) { /* навигация не должна ронять расчёт */ }
      return out;
    };
  }

  /* ------------------------------------------------------------------ */
  /* Состояние расчёта                                                    */
  /* ------------------------------------------------------------------ */

  var dirty = 0;
  var running = 0;

  /* Страница пересчитывает модель сама, как только поле подтверждено
     (onchange у каждого поля вызывает calculate). Инструкция в шапке —
     «после ручного изменения нажмите Пересчитать модель» — этому противоречила
     прямо. Поэтому здесь не правило, а состояние: правится → считается →
     актуально. */
  /* Плашка расчёта по центру экрана: статус в шапке мелкий и вне поля
     зрения — человек не видел, что модель считает и что уже посчитала
     (замечание владельца). */
  var toastTimer = null;

  function showToast(message, sticky) {
    var toast = document.getElementById('iaToast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'iaToast';
      toast.className = 'ia-toast';
      document.body.appendChild(toast);
    }
    if (toastTimer) { clearTimeout(toastTimer); toastTimer = null; }
    toast.textContent = message;
    toast.classList.add('show');
    if (!sticky) toastTimer = setTimeout(function () { toast.classList.remove('show'); }, 1600);
  }

  function hideToast() {
    var toast = document.getElementById('iaToast');
    if (toast) toast.classList.remove('show');
  }

  function renderState() {
    var box = document.getElementById('iaState');
    var text = document.getElementById('iaStateText');
    if (!box || !text) return;
    // Кнопка «Пересчитать модель» — главное действие только когда есть
    // изменения; при актуальном расчёте она спорила со статусом рядом.
    var recalc = document.querySelector('.actions .btn.dark');
    if (recalc) recalc.style.display = (dirty > 0 && !running) ? '' : 'none';
    box.classList.toggle('dirty', dirty > 0 && !running);
    if (running) text.textContent = 'Считаю…';
    else if (dirty > 0) {
      text.textContent = 'Есть ' + dirty + ' ' + plural(dirty, ['изменение', 'изменения', 'изменений'])
        + ' вне расчёта — пересчитать';
    } else text.textContent = 'Расчёт актуален';
  }

  function plural(n, forms) {
    var mod100 = n % 100, mod10 = n % 10;
    if (mod100 > 4 && mod100 < 21) return forms[2];
    if (mod10 === 1) return forms[0];
    if (mod10 > 1 && mod10 < 5) return forms[1];
    return forms[2];
  }

  function watchChanges() {
    document.addEventListener('input', onEdit, true);
    document.addEventListener('change', onEdit, true);
    var original = window.calculate;
    if (typeof original !== 'function') { missing.push('функция calculate не найдена'); return; }
    window.calculate = function () {
      running += 1;
      renderState();
      showToast('Пересчитываю модель…', true);
      var out = original.apply(this, arguments);
      if (out && typeof out.then === 'function') {
        out.then(function () { dirty = 0; }, function () { }).then(function () {
          running -= 1;
          renderState();
          if (!running) showToast('✓ Расчёт обновлён');
        });
      } else { running -= 1; renderState(); hideToast(); }
      return out;
    };
  }

  function onEdit(event) {
    var target = event.target;
    if (!target || !target.closest) return;
    if (!target.closest('.content')) return;
    if (target.closest('.ai-drawer')) return;
    dirty += 1;
    renderState();
    goalSeekStale = true;
  }

  /* ------------------------------------------------------------------ */
  /* Карточка инвестиционного решения                                     */
  /* ------------------------------------------------------------------ */

  var goalSeek = null;
  var goalSeekStale = true;
  var goalSeekBusy = false;
  var goalSeekAbort = null;

  function buildVerdict() {
    var report = need('#report', 'панель отчёта');
    var hero = need('#report .report-hero', 'шапка отчёта');
    if (!report || !hero) return;
    var card = document.createElement('div');
    card.className = 'ia-verdict';
    card.id = 'iaVerdict';
    card.innerHTML = '<div class="section-title">Инвестиционное решение</div>'
      + '<h2 id="iaVerdictTitle">Расчёт не выполнен</h2>'
      + '<p class="ia-verdict-lead" id="iaVerdictLead">Нажмите «Пересчитать модель».</p>'
      + '<div class="ia-verdict-grid" id="iaVerdictGrid"></div>'
      + '<div class="ia-stamp" id="iaVerdictStamp"></div>'
      + '<button type="button" class="btn ia-ask" id="iaAskPlaton">Спросить Платона: почему такой вердикт?</button>';
    report.insertBefore(card, hero);
    var ask = card.querySelector('#iaAskPlaton');
    ask.onclick = function () {
      var hint = document.getElementById('iaFabHint');
      if (hint) hint.remove();
      var input = document.getElementById('aiInput');
      if (input && !input.value) {
        input.value = 'Объясни текущее инвестиционное решение: что двигает LLCR, '
          + 'какие два-три параметра важнее всего и что бы ты проверил в первую очередь?';
      }
      if (typeof window.toggleAgent === 'function') window.toggleAgent(true);
    };
  }

  function renderVerdict() {
    var card = document.getElementById('iaVerdict');
    var result = pageResult();
    if (!card || !result || !result.summary) return;

    var llcr = result.summary.llcr;
    var title = document.getElementById('iaVerdictTitle');
    card.classList.remove('pass', 'edge', 'fail');
    if (llcr == null) {
      title.textContent = 'LLCR не рассчитан';
    } else if (llcr >= TARGET_LLCR) {
      card.classList.add('pass'); title.textContent = 'Экономика проходит';
    } else if (llcr >= 1.05) {
      card.classList.add('edge'); title.textContent = 'Экономика на границе';
    } else {
      card.classList.add('fail'); title.textContent = 'Экономика не проходит';
    }

    document.getElementById('iaVerdictLead').textContent =
      'Чистая прибыль ' + fmtMoney(result.summary.net_profit)
      + ' · маржинальность ' + fmtPct(result.summary.margin)
      + ' · IRR ' + (result.summary.irr_equity == null ? 'N/A' : fmtPct(result.summary.irr_equity))
      + ' · порог банка LLCR ' + TARGET_LLCR.toFixed(2).replace('.', ',') + 'x.';

    var found = goalSeek && goalSeek.available && goalSeek.solution ? goalSeek.solution : null;
    var price = found ? goalSeek.current.variable : Number(pageInputs().purchase_price_mln || 0);
    var solution = found ? found.variable : null;
    var cells = [
      { label: 'LLCR (расчётный)', value: fmtMult(llcr), note: 'Ориентир банка — 1,20x.' },
      price > 0
        ? { label: 'Цена входа', value: mlnLabel(price), note: 'Текущая цена приобретения.' }
        : { label: 'Цена входа', value: 'не задана', note: 'Заполните «Стоимость покупки» в Экономике — сейчас всё посчитано как для бесплатного участка.', wait: true },
      found
        ? { label: 'Максимум цены входа', value: mlnLabel(solution), note: 'При LLCR не ниже 1,20x' + (goalSeek.scope_label ? ' · ' + goalSeek.scope_label : '') + '.' }
        : { label: 'Максимум цены входа', value: ceilingText(), note: ceilingNote(), wait: true },
      found
        ? { label: 'Запас к цене', value: mlnLabel(found.change_abs), note: found.change_abs >= 0 ? 'Цена ниже потолка.' : 'Цена выше потолка — покупка не проходит по LLCR.' }
        : { label: 'Запас к цене', value: '—', note: refused() ? 'Порог не достигается ни при какой цене — дело не в цене входа.' : 'Считается после подбора максимума.', wait: true }
    ];

    document.getElementById('iaVerdictGrid').innerHTML = cells.map(function (cell) {
      return '<div class="ia-verdict-cell' + (cell.wait ? ' wait' : '') + '"><span>' + cell.label + '</span><b>'
        + cell.value + '</b><small>' + cell.note + '</small></div>';
    }).join('');

    var stamp = document.getElementById('iaVerdictStamp');
    if (goalSeek && goalSeek.available === false) {
      stamp.textContent = 'Подбор выполнен движком DevelopAid ' + (goalSeek.engine_version || '')
        + ': ' + (goalSeek.reason || 'причина не указана');
    } else if (goalSeek && goalSeek.engine_version) {
      stamp.textContent = 'Подбор выполнен полным пересчётом модели DevelopAid ' + goalSeek.engine_version
        + ' · ' + goalSeek.computed_at + ' UTC. Текущая модель не изменена.'
        + (goalSeek.threshold_beyond_bound ? ' Порог упёрся в границу поиска — предел может лежать дальше.' : '');
    } else {
      stamp.textContent = '';
    }
  }

  /* Отказ подбора — это ответ, а не пустая клетка: цена, «допустимая» у
     проекта, который порог не проходит ни при каких вводных, выглядела бы на
     экране ровно так же, как посчитанная. */
  function refused() { return !!(goalSeek && goalSeek.available === false); }
  function ceilingText() {
    if (goalSeekBusy) return 'считается…';
    if (refused()) return 'не достигается';
    return 'откройте раздел';
  }
  function ceilingNote() {
    if (refused()) return 'LLCR 1,20x не достигается даже при нулевой цене входа.';
    return 'Подбор параметра движком при LLCR 1,20x.';
  }

  /* Подбор — это многократный полный пересчёт модели, поэтому он не идёт
     вместе с расчётом: карточка показывается сразу, максимум приезжает
     отдельным запросом и только там, где на него смотрят. */
  function ensureGoalSeek() {
    if (!pageResult() || goalSeekBusy) return;
    if (goalSeek && !goalSeekStale) return;
    if (goalSeekAbort) goalSeekAbort.abort();
    goalSeekAbort = new AbortController();
    goalSeekBusy = true;
    renderVerdict();
    fetch('/ia/goal-seek', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: goalSeekAbort.signal,
      body: JSON.stringify({
        inputs: pageInputs(), tep: pageTep(),
        rates: pageRates(), phasing: pagePhasing(),
        variable: 'purchase_price_mln', target_llcr: TARGET_LLCR
      })
    }).then(function (response) { return response.json(); })
      .then(function (data) { goalSeek = data; goalSeekStale = false; })
      .catch(function (error) {
        if (error && error.name === 'AbortError') return;
        goalSeek = { available: false, reason: String(error && error.message || error) };
      })
      .then(function () { goalSeekBusy = false; renderVerdict(); });
  }

  function wrapRenderResult() {
    var original = window.renderResult;
    if (typeof original !== 'function') { missing.push('функция renderResult не найдена'); return; }
    window.renderResult = function () {
      var out = original.apply(this, arguments);
      try {
        goalSeekStale = true;
        renderVerdict();
        relabelBridge();
        if (currentSection) {
          var active = document.querySelector('.tabs .tab.active');
          if (active) syncNav(active.getAttribute('data-tab'));
        }
        if (currentSection === 'result') ensureGoalSeek();
      } catch (error) { /* отчёт важнее карточки */ }
      return out;
    };
  }

  /* ------------------------------------------------------------------ */
  /* Подсказки на вкладке ТЭП                                            */
  /* ------------------------------------------------------------------ */

  /* Кнопки «Рассчитать ТЭП от площади и плотности» и «Обновить производные
     ТЭП» висели без объяснения, когда ими пользоваться, — замечание владельца.
     Подсказка знает состояние: загружен ГлавАПУ, посчитано Подмосковье или
     участка нет вовсе — и говорит про текущий случай, а не про все сразу. */
  var tepAnnotated = false;

  function annotateTep() {
    var card = document.querySelector('#tep .card');
    if (!card) {
      if (!tepAnnotated) { tepAnnotated = true; missing.push('карточка ТЭП — #tep .card'); report(); }
      return;
    }
    var intro = document.getElementById('iaTepIntro');
    if (!intro) {
      intro = document.createElement('div');
      intro.id = 'iaTepIntro';
      intro.className = 'note';
      intro.style.margin = '0 0 14px';
      card.insertBefore(intro, card.children[1] || null);
    }
    var mo = (pageInputs() || {})._mo_calc;
    if (pageGlavapu()) {
      intro.textContent = 'ТЭП загружен из ГлавАПУ по участку с шага 1 — числа можно править прямо в '
        + 'таблице ниже. Подземный паркинг производный: постоянные + гостевые места × 35 м².';
    } else if (mo) {
      var district = mo.territory && mo.territory.district ? ' (' + mo.territory.district + ')' : '';
      var density = Number(mo.density_sqm_per_ha || 30000).toLocaleString('ru-RU');
      intro.textContent = 'Участок в Московской области' + district + ': ТЭП посчитан по нормативам РНГП, '
        + 'посадка ' + density + ' м² на га. Поменять плотность или площадь можно в «Параметрах расчёта '
        + 'по Московской области» ниже — затем нажмите «Рассчитать ТЭП от площади и плотности».';
    } else {
      intro.textContent = 'ТЭП пока не рассчитан. Укажите площадь и плотность — или вернитесь в «Участок» '
        + 'и загрузите участок по адресу или кадастровому номеру.';
    }

    // Пояснение стоит у самого блока Подмосковья, а не в начале карточки:
    // блок внизу, и подсказка сверху его не объясняла — замечание владельца.
    var moscowLoaded = !!pageGlavapu();
    var moBox = document.getElementById('moParamsBox');
    if (moBox) {
      var moNote = document.getElementById('iaMoNote');
      if (!moNote) {
        moNote = document.createElement('div');
        moNote.id = 'iaMoNote';
        moNote.className = 'note';
        moNote.style.margin = '10px 0 6px';
        moBox.parentNode.insertBefore(moNote, moBox);
      }
      // Московскому участку параметры Подмосковья не нужны вовсе — блок
      // скрывается, а не подписывается: подпись «не нужен» сбивает так же
      // (замечание владельца).
      moBox.style.display = moscowLoaded ? 'none' : '';
      moNote.style.display = moscowLoaded ? 'none' : '';
      if (moscowLoaded) {
        moNote.textContent = '';
      } else if (mo) {
        var moDistrict = mo.territory && mo.territory.district ? mo.territory.district : 'округ не определён';
        moNote.textContent = 'Ваш участок — Московская область (' + moDistrict + '). Плотность и цены взяты '
          + 'из справочников, посадка по умолчанию — 30 000 м² на га. Откройте блок, если хотите поменять '
          + 'вручную: правка сразу пересчитает ТЭП участка.';
      } else {
        moNote.textContent = 'Этот блок нужен в двух случаях: участок в Московской области (плотность и цены '
          + 'подставятся из справочников) или ручной расчёт без участка — тогда площадь и плотность вводятся здесь.';
      }
    } else if (!tepAnnotated) {
      tepAnnotated = true;
      missing.push('блок параметров МО — #moParamsBox');
      report();
    }

    // Той же логикой — подпись у кнопки расчёта от площади и плотности.
    var calcButton = document.querySelector('#tep [onclick="applyDensityToTep()"]');
    var calcBar = calcButton ? calcButton.closest('.toolbar') : null;
    if (!calcBar) {
      if (!tepAnnotated) { tepAnnotated = true; missing.push('кнопка расчёта от плотности — #tep [onclick="applyDensityToTep()"]'); report(); }
    } else {
      var manualWrap = document.getElementById('iaManualCalc');
      if (!manualWrap) {
        manualWrap = document.createElement('details');
        manualWrap.id = 'iaManualCalc';
        manualWrap.innerHTML = '<summary style="font-size:13px;padding:8px 0"></summary>';
        calcBar.parentNode.insertBefore(manualWrap, calcBar);
        manualWrap.appendChild(calcBar);
        manualWrap.open = !moscowLoaded;
      }
      // Для московского участка это сценарный инструмент, а не ошибка:
      // «что, если посадка другая» — пересчитать ТЭП от своей плотности.
      // Подпись говорит это прямо, вместе с ценой (замена данных ГлавАПУ)
      // и путём назад (повторно «Получить ТЭП» на шаге «Участок»).
      // Базовая посадка — из поля страницы, не копией: цифра, разъехавшаяся
      // с полем, хуже отсутствующей.
      var densityField = document.getElementById('moDensity');
      var baseDensity = Number((densityField && densityField.getAttribute('value')) || 30000)
        .toLocaleString('ru-RU');
      manualWrap.querySelector('summary').textContent = moscowLoaded
        ? 'Что если посадка другая? Пересчитать ТЭП от своей плотности'
        : (mo
          ? 'Пересчитать ТЭП — по нормативам РНГП МО, посадка по умолчанию ' + baseDensity + ' м² на га'
          : 'Рассчитать ТЭП вручную — площадь × плотность (по умолчанию ' + baseDensity + ' м² на га)');
    }

    var hint = document.getElementById('siteApplyHint');
    if (hint) {
      if (pageGlavapu()) {
        hint.textContent = 'Сценарий «а что, если»: задайте свою плотность и пересчитайте ТЭП. Данные '
          + 'ГлавАПУ будут заменены; вернуть их — повторно «Получить ТЭП» на шаге «Участок».';
      } else if (mo) {
        hint.textContent = 'Нажмите после правки плотности или площади — ТЭП пересчитается по нормативам '
          + 'РНГП: квартиры = площадь × плотность, социалка и паркинг — от населения.';
      } else {
        var densityInput = document.getElementById('moDensity');
        var densityBase = Number((densityInput && densityInput.getAttribute('value')) || 30000)
          .toLocaleString('ru-RU');
        hint.textContent = 'Введите площадь и плотность выше и нажмите: квартиры = площадь × плотность '
          + '(по умолчанию ' + densityBase + ' м² на га — норматив РНГП), социалка и паркинг — от населения. '
          + 'Работает в любом регионе.';
      }
    }

    var sync = document.querySelector('#tep [onclick="syncTep()"]');
    if (sync && !document.getElementById('iaSyncNote')) {
      var note = document.createElement('div');
      note.id = 'iaSyncNote';
      note.className = 'note';
      note.style.margin = '12px 0 6px';
      note.textContent = 'Офисы, ТЦ, паркинги и соцобъекты в таблице — производные от вводных шага 3 '
        + '«Экономика»: площади, места, галочки «объект включён». Поменяли что-то там — нажмите кнопку '
        + 'ниже, и эти строки пересчитаются. Квартиры и коммерцию первого этажа кнопка не трогает.';
      sync.closest('.toolbar').parentNode.insertBefore(note, sync.closest('.toolbar'));
    } else if (!sync && !tepAnnotated) {
      tepAnnotated = true;
      missing.push('кнопка производных ТЭП — #tep [onclick="syncTep()"]');
      report();
    }
  }

  /* ------------------------------------------------------------------ */
  /* Тексты                                                              */
  /* ------------------------------------------------------------------ */

  /* Потребность и лимит — две разные величины с одним именем «БРИДЖ». Плата за
     ВРИ в потребность входит, а в расчётный лимит банка нет, и на странице это
     читалось как противоречие. Разница между ними — то, что банк не
     финансирует; сейчас движок выдаёт БРИДЖем всю потребность. */
  var bridgeChecked = false;

  function relabelBridge() {
    var done = 0;
    document.querySelectorAll('#reportKpi .kpi span').forEach(function (node) {
      if (node.textContent.trim() === 'Пиковый БРИДЖ') {
        node.textContent = 'Потребность в БРИДЖе (пик)'; done += 1;
      }
    });
    // Подписи таблицы приходят из row() ячейками td, а не заголовками: на th
    // переименование молча не срабатывало, и на экране оставался прежний
    // «Расчётный лимит» — ровно та потеря, ради которой заведена плашка.
    document.querySelectorAll('#bridgeTable td').forEach(function (node) {
      var text = node.textContent.trim();
      if (text === 'Пиковый остаток') { node.textContent = 'Пиковая потребность в БРИДЖе'; done += 1; }
      if (text === 'Расчётный лимит') { node.textContent = 'Расчётный лимит банка'; done += 1; }
    });
    if (!bridgeChecked && pageResult() && done < 3) {
      bridgeChecked = true;
      missing.push('термины БРИДЖа переименованы частично (' + done + ' из 3) — проверьте #reportKpi и #bridgeTable');
      report();
    }
    if (done >= 3) bridgeChecked = true;
    explainBridge();
  }

  /* Потребность и лимит — две величины, которые страница называла одинаково.
     Плата за ВРИ входит в первую и не входит во вторую, и на экране это
     читалось как противоречие. Пояснение — текст, не расчёт. */
  function explainBridge() {
    var table = document.getElementById('bridgeTable');
    if (!table || document.getElementById('iaBridgeNote')) return;
    var note = document.createElement('div');
    note.id = 'iaBridgeNote';
    note.className = 'note';
    note.style.margin = '10px 0 0';
    note.style.fontSize = '11px';
    note.textContent = 'Потребность — сколько денег нужно до открытия ПФ; плата за смену ВРИ в неё входит. '
      + 'Расчётный лимит — то, что банк считает своим бюджетом БРИДЖа: цена входа, П, РД и денежная '
      + 'соцкомпенсация. Разницу между ними банк не финансирует.';
    table.parentNode.appendChild(note);
  }

  /* Инструкция «после ручного изменения нажмите Пересчитать» описывала не то,
     что страница делает: каждое подтверждённое поле пересчитывает модель само.
     Правило, которого нет, дороже отсутствующего: человек ждёт кнопки. */
  var STALE_RULE = 'После ручного изменения вводных нажмите <b>«Пересчитать модель»</b>.';

  function dropStaleRule() {
    var note = document.querySelector('.header-note');
    if (!note) { missing.push('абзац о классе и сценарии — .header-note'); return; }
    if (note.innerHTML.indexOf(STALE_RULE) < 0) {
      missing.push('инструкция о ручном пересчёте изменилась — .header-note');
      return;
    }
    note.innerHTML = note.innerHTML.replace(STALE_RULE, '');
  }

  function trimTexts() {
    dropStaleRule();
    retext('#rates .card h2', 'Автоматическая кривая нормализации', 'Прогноз ключевой ставки');
    retext('#sensitivity .report-title h2', 'Что решает судьбу проекта', 'Чувствительность');
    retext('#phasing .card h2', 'Разбиение мастер-проекта на очереди', 'Очередность проекта');
    retext('#report #vriCard h2', 'Обязательство, график погашения и источники оплаты',
      'ВРИ: сумма и график платежей');

    var moNote = document.querySelector('#moParamsBox p b');
    if (!moNote) missing.push('оговорка о пересчёте МО — #moParamsBox p b');
    else if (moNote.textContent.indexOf('Правка любого параметра') !== 0) {
      missing.push('оговорка о пересчёте МО изменилась: «' + moNote.textContent.slice(0, 50) + '»');
    } else {
      // Здесь пересчитывается ТЭП участка, а не экономика. Одно слово
      // «результат» на две разные величины читалось как противоречие с
      // «после ручного изменения нажмите Пересчитать модель».
      moNote.textContent = 'Правка любого параметра сразу пересчитывает ТЭП участка';
    }

    // Предупреждение о расчётном LLCR стояло трижды. Остаётся одно — рядом с
    // самим числом; повторённое трижды, оно не читается нигде.
    var kept = document.querySelector('#finance .llcr-label');
    if (!kept) missing.push('оговорка рядом с LLCR — #finance .llcr-label');
    var dropped = 0;
    document.querySelectorAll('#finance .note.warning, #report > .note.warning').forEach(function (node) {
      if (node.textContent.indexOf('LLCR') >= 0) { node.style.display = 'none'; dropped += 1; }
    });
    if (dropped < 2) missing.push('дублей предупреждения о LLCR найдено ' + dropped + ', ожидалось 2');
  }

  /* ------------------------------------------------------------------ */

  function ribbon() {
    var shell = document.querySelector('.shell');
    if (!shell) { missing.push('корень страницы — .shell'); return; }
    var bar = document.createElement('div');
    bar.className = 'ia-ribbon';
    bar.innerHTML = '<span>Тестовый адрес · новая архитектура</span>'
      + '<span class="ia-ribbon-note">Тот же движок и те же вводные. Рабочая страница — <a href="/">/</a></span>';
    shell.insertBefore(bar, shell.firstChild);
  }

  function report() {
    if (!missing.length) return;
    var shell = document.querySelector('.shell') || document.body;
    var box = document.createElement('div');
    box.className = 'ia-missing';
    box.innerHTML = '<b>Слой перестройки не нашёл ' + missing.length + ' узл'
      + plural(missing.length, ['а', 'а', 'ов']) + ' страницы — эти изменения не применились:</b><ul>'
      + missing.map(function (item) { return '<li>' + item + '</li>'; }).join('') + '</ul>';
    var header = shell.querySelector('.header');
    if (header && header.nextSibling) shell.insertBefore(box, header.nextSibling);
    else shell.appendChild(box);
  }

  /* Все группы вводных открыты сразу: свёрнутая группа читается как
     «здесь ничего нет», и человек не видел данных раздела, пока не дошёл
     до него руками (решение владельца). Отчёт не трогается. */
  function openAllGroups() {
    var groups = document.querySelectorAll('#inputGroups details');
    if (!groups.length) { missing.push('группы вводных — #inputGroups details'); return; }
    groups.forEach(function (group) { group.open = true; });
  }

  function boot() {
    step('лента preview', ribbon);
    step('шапка', rebuildHeader);
    step('подтверждение сброса', guardReset);
    step('панель участка', splitSite);
    step('навигация', buildNav);
    step('перехват openTab', wrapOpenTab);
    step('карточка решения', buildVerdict);
    step('перехват renderResult', wrapRenderResult);
    step('состояние расчёта', watchChanges);
    step('группы вводных', openAllGroups);
    step('тексты', trimTexts);
    step('подсказки ТЭП', annotateTep);
    step('термины БРИДЖа', relabelBridge);
    openSection('project', 'iaSite');
    renderState();
    renderVerdict();
    report();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();

/* Сторож загрузки слоя. Встраивается в <head> строкой, а не файлом.
 *
 * Страница весит полтора мегабайта. Прежняя шапка (класс, сценарий, вкладки)
 * лежит в первых процентах документа, главный скрипт — следом, а слой
 * подключён в самом конце. Пока документ идёт по медленной мобильной сети,
 * человек видит прежний интерфейс без «Личного кабинета», с кнопками, которые
 * ещё ничего не делают, — и принимает его за готовую страницу (телефон
 * владельца, 25.10.2026). Поэтому до запуска слоя прежний вид закрыт экраном
 * загрузки, а всё, что может пойти не так, называется на экране:
 *
 * - документ грузится дольше обычного — экран говорит, что связь медленная,
 *   и даёт кнопку «Обновить страницу»;
 * - файл слоя не загрузился или слой не запустился — экран снимается,
 *   показан прежний вид и плашка с причиной.
 *
 * Синтаксис — ES5: этот код обязан выполниться в любом браузере, иначе он
 * сам стал бы причиной «пустой» страницы.
 */
(function () {
  var root = document.documentElement;
  var SLOW_MS = 12000;
  var START_MS = 6000;
  var settled = false;

  root.className += (root.className ? ' ' : '') + 'ia-loading';
  root.setAttribute('data-ia-loading', 'Загружаем страницу…');

  function ready() { return /(^|\s)ia-ready(\s|$)/.test(root.className); }

  function unveil() {
    root.className = root.className.replace(/(^|\s)ia-loading(?=\s|$)/g, ' ').replace(/^\s+|\s+$/g, '');
  }

  function fail(reason) {
    if (settled || ready()) return;
    if (!document.body) {
      document.addEventListener('DOMContentLoaded', function () { fail(reason); });
      return;
    }
    settled = true;
    unveil();
    var box = document.createElement('div');
    box.className = 'ia-boot-fail';
    box.id = 'iaBootFail';
    box.innerHTML = '<b>Новый интерфейс не включился.</b> '
      + '<span></span> Сейчас открыт прежний вид страницы. '
      + 'Обновите страницу; если плашка останется, пришлите её текст.'
      + ' <button type="button">Обновить страницу</button>';
    box.querySelector('span').textContent = reason;
    box.querySelector('button').onclick = function () { location.reload(); };
    var shell = document.querySelector('.shell');
    if (shell) shell.insertBefore(box, shell.firstChild);
    else document.body.insertBefore(box, document.body.firstChild);
  }

  window.__iaBootFail = fail;

  setTimeout(function () {
    if (document.readyState === 'loading' && !ready()) {
      root.setAttribute('data-ia-loading',
        'Страница ещё загружается: связь медленная, а страница большая. '
        + 'Подождите немного или обновите страницу.');
      var again = document.createElement('button');
      again.type = 'button';
      again.className = 'ia-boot-reload';
      again.textContent = 'Обновить страницу';
      again.onclick = function () { location.reload(); };
      (document.body || root).appendChild(again);
    }
  }, SLOW_MS);

  window.addEventListener('load', function () {
    setTimeout(function () {
      fail('Страница загрузилась, но слой нового интерфейса не запустился за '
        + Math.round(START_MS / 1000) + ' секунд.');
    }, START_MS);
  });
})();

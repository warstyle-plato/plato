"""Кусок страницы PAGE: Разметка страницы (<body>: шапка, вкладки, панели, окна) и
маленький первый <script> до основного.

Страница — один шаблон с плейсхолдерами `__DEVELOPAID_*__`, разложенный по
кускам `engine/page_*.py` в порядке строк `_engine_part("page_*")` в
`main_legacy.py`; каждый кусок дописывает свой текст к `PAGE` как есть,
и их склейка — прежняя страница байт в байт. Плейсхолдеры подставляет
engine/page_build.py. Стенды на node берут куски скрипта из собранной
`core.PAGE` через tests/page_blocks.py, тексты — через tests/engine_source.py.

Не самостоятельный модуль. `main_legacy.py` выполняет этот файл в своём
пространстве имён (`_engine_part("page_markup")`), поэтому здесь видны все имена
движка. Отдельно не импортировать: второй импорт поднял бы вторую копию движка.
"""
# ruff: noqa

PAGE += r"""</head>
<body>
<div class="shell">
  <div class="brandbar"><img src="data:image/webp;base64,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"><div class="brandline"></div></div>
  <div class="header">
    <div class="title"><h1>Девелоперская инвестиционная модель</h1><p>v__DEVELOPAID_VERSION__ · ТЭП · экономика · БРИДЖ · проектное финансирование · эскроу · LLCR</p></div>
    <div class="actions">
      <!-- Что строим. Нежилой проект — офисы, торговля, ФОК и наземный
           паркинг: ни жилья, ни соцнагрузки, ни платы за смену ВРИ. Место
           рядом с классом, а НЕ у поля кадастра: кадастр отвечает на «где», а
           тип — на «что строим», и проект приезжает ещё файлом, ссылкой и
           мостом КРТ, минуя это поле вовсе. Варианты рисует движок: два
           написанных здесь руками были бы копией, которую негде обновлять. -->
      <div class="scenario">Проект&nbsp;
        <select id="projectKindSelect" onchange="applyProjectKind(this.value)" style="min-width:135px"></select>
        <div id="projectKindNoteTop" style="font-size:10px;color:#777;margin-top:4px;text-align:right"></div>
      </div>
      <!-- Класс гостиницы — звёздность, а не класс жилья: пресет жилья у
           гостиницы ничего не считает. Поле одно — `hotel_stars` блока
           «Гостиница»; шапка его показывает и правит. -->
      <div class="scenario" id="hotelClassBox" style="display:none">Класс&nbsp;
        <select id="hotelClassSelect" onchange="setHotelClass(this.value)" style="min-width:135px"></select>
        <div id="hotelClassNote" style="font-size:10px;color:#777;margin-top:4px;text-align:right">звёздность гостиницы</div>
      </div>
      <div class="scenario" id="projectClassBox">Класс&nbsp;
        <select id="projectClassSelect" onchange="applyProjectClassPreset(this.value)" style="min-width:135px">
          <option value="comfort">Комфорт</option>
          <option value="business">Бизнес</option>
          <option value="elite">Элитный</option>
          <option value="custom">Пользовательский</option>
        </select>
        <div id="projectClassPreview" style="font-size:10px;color:#777;margin-top:4px;text-align:right"></div>
        <div style="text-align:right;margin-top:2px"><a href="#" onclick="openClassDialog();return false" style="font-size:10px;color:#3b6db4">Настройки классов</a></div>
      </div>
      <div class="scenario">Сценарий&nbsp;
        <select id="scenarioSelect" onchange="applyScenario(this.value)">
          <option value="conservative">Консервативный</option><option value="base" selected>Базовый</option><option value="optimistic">Оптимистичный</option>
        </select>
        <div id="scenarioNote" style="font-size:10px;color:#777;margin-top:4px;text-align:right">
          Доходы без корректировки · расходы без корректировки
        </div>
      </div>
      <button class="btn ai-open-btn" onclick="toggleAgent(true)"><span id="aiStatusDot" class="ai-dot"></span><span class="ai-label">Платон Сергеевич</span></button>
      <!-- Кнопки хранилища появляются только там, где оно настроено и есть чем
           опознать владельца: иначе это кнопка, которая всегда отказывает. -->
      <button class="btn" id="projectsButton" style="display:none" onclick="openProjects()">Личный кабинет</button>
      <!-- Вход жил внутри личного кабинета и показывался только тем, у кого нет
           ни сессии, ни ключа: человек с непринятым ключом до него не доходил
           вовсе (замечание владельца, 18.08.2026). Кнопка стоит в шапке, пока
           никто не вошёл, и прячется после входа. -->
      <button class="btn dark" id="loginButton" style="display:none" onclick="openLogin()">Войти через Telegram</button>
      <button class="btn" id="tariffsButton" onclick="openTariffs()">Тарифы</button>
      <button class="btn" onclick="resetProject()">Сбросить</button>
      <a class="btn" href="/guide">Руководство</a>
      <button class="btn dark" onclick="calculateAndOpen('report')">Пересчитать модель</button>
    </div>
  </div>
  <div class="header-note">
    <b>Класс проекта и сценарий.</b>
    Класс — Комфорт, Бизнес или Элитный — задаёт стартовые цены квартир и коммерции,
    цену машино-места и стоимость строительства наземной и подземной частей.
    Сценарий меняет эти числа <b>поверх выбранного класса</b>: в базовом цены и затраты
    остаются как есть, в консервативном цены ниже на 10%, а затраты выше на 10%,
    в оптимистичном — наоборот. Так видно, что будет с проектом при худших или лучших
    условиях. Это не отдельные классы жилья.
    Класс и сценарий применяются сразу, а модель пересчитывается сама после каждого изменённого поля.
  </div>
  <div class="tabs">
    <button class="tab active" data-tab="inputs" onclick="openTab('inputs',this)">Вводные</button>
    <button class="tab" data-tab="tep" onclick="openTab('tep',this)">ТЭП</button>
    <button class="tab" data-tab="vri" onclick="openTab('vri',this)">ВРИ</button>
    <button class="tab" data-tab="phasing" onclick="openTab('phasing',this);renderPhasing()">Очередность</button>
    <button class="tab" data-tab="rates" onclick="openTab('rates',this)">Ключевая ставка</button>
    <button class="tab" data-tab="finance" onclick="openTab('finance',this)">Финансирование</button>
    <button class="tab" data-tab="calendar" onclick="openTab('calendar',this)">Календарь</button>
    <button class="tab" data-tab="sensitivity" onclick="openTab('sensitivity',this);renderSensitivityForm()">Чувствительность</button>
    <button class="tab" data-tab="report" onclick="openTab('report',this)">Отчёт</button>
  </div>

  <div class="content">
    <div id="inputs" class="panel active">
      <div class="card import-card">
        <div class="import-head">
          <div>
            <div class="section-title">Автозагрузка исходных данных</div>
            <h2>Введите адрес или кадастровый номер</h2>
            <p>Мы возьмём данные об участке из госреестра недвижимости и посчитаем ТЭП. Для Москвы и Московской области — по их нормам. Для участка в другом регионе норм у нас нет: возьмём площадь из госреестра, ТЭП посчитаем по плотности, а остальное поставим нашими умолчаниями — всё это вы сможете поправить. Прежде чем подставить числа в модель, покажем их вам.</p>
          </div>
          <div style="font-size:11px;color:#777;text-align:right">Источники<br><b style="color:#111">ЕГРН, ГлавАПУ, нормы Московской области</b></div>
        </div>
        <div class="cadastral-box">
          <h3>Участок</h3>
          <p>Подойдёт кадастровый номер, адрес или координаты «широта, долгота». Несколько номеров перечислите через запятую или с новой строки — за один раз можно до 30 участков.</p>
          <div class="cadastral-entry">
            <textarea id="cadastralNumbers" oninput="typeCadastralField(this.value);dropStaleLandPreview()" placeholder="77:02:0016009:1934, 77:02:0016009:1935&#10;или: 50:12:0100131:497&#10;или: Московская область, г. Мытищи, ул. Мира, 1"></textarea>
            <button id="cadastralAnalyzeButton" class="btn dark" onclick="obtainTep()">Получить ТЭП</button>
          </div>
          <div class="import-actions" style="margin-top:8px">
            <button class="btn" onclick="lookupLand()">Только данные об участке</button>
            <span style="font-size:11px;color:#777">Покажем адрес, площадь, категорию земли, разрешённое использование и кадастровую стоимость — без расчёта ТЭП.</span>
          </div>
          <div id="cadastralStatus" class="import-status">Наружу мы отправляем только адрес или кадастровый номер. Ваши цифры и расчёт никуда не уходят.</div>
          <div id="landPreview" class="cadastral-preview" style="display:none">
            <div id="landSummary" class="import-summary"></div>
            <div id="landScreening" class="land-screening" style="display:none"></div>
            <div id="landCards" class="land-results"></div>
            <div id="landWarnings" class="note warning"></div>
            <div class="import-actions">
              <span style="font-size:11px;color:#777">Данные об участке сохранены в проекте. Цифры расчёта от этого не изменились.</span>
            </div>
          </div>
          <div id="cadastralPreview" class="cadastral-preview" style="display:none">
            <div id="cadastralSummary" class="import-summary"></div>
            <div id="cadastralParcels" class="cadastral-parcels"></div>
            <div id="cadastralWarnings" class="note warning"></div>
            <div class="import-actions">
              <span style="font-size:11px;color:#777">Участок сохранён в проекте. ТЭП появится ниже, как только закончится расчёт.</span>
            </div>
          </div>
          <iframe id="genplanAutomationFrame" class="genplan-automation-frame" title="Автоматический расчёт ТЭП ГлавАПУ" aria-hidden="true"></iframe>
        </div>
        <!-- Результат расчёта идёт сразу за сведениями ЕГРН. Прежде между
             ними стояли параметры Подмосковья и загрузка готового файла, и
             посчитанный ТЭП оказывался в самом низу карточки: человек нажимал
             кнопку и не находил ответа там, где его ищут. -->
        <div id="moStatus" class="import-status" style="display:none"></div>
        <div id="moPreview" class="cadastral-preview" style="display:none">
            <div id="moSummary" class="import-summary"></div>
            <div class="import-actions">
              <button class="btn dark" onclick="applyMo()">Подставить в проект</button>
              <span style="font-size:11px;color:#777">В проект встанут новый ТЭП, места в детсадах и школах и плата за смену разрешённого использования земли.</span>
            </div>
            <div id="moTables"></div>
            <div id="moWarnings" class="note warning"></div>
        </div>
        <div id="glavapuStatus" class="import-status">Введите кадастровый номер выше, и ТЭП посчитается сам. Готовые примеры лежат в «Личном кабинете», а свой файл можно загрузить ниже.</div>
        <div id="glavapuPreview" class="import-preview" style="display:none">
          <div id="glavapuSummary" class="import-summary"></div>
          <div class="import-actions">
            <button class="btn dark" onclick="applyGlavapu()">Подставить в проект</button>
            <span style="font-size:11px;color:#777">Площади квартир и коммерции в проекте заменятся числами из этого расчёта.</span>
          </div>
          <div class="scroll" style="max-height:360px"><table>
            <thead><tr><th>Показатель</th><th>Распознано</th><th>Ед.</th><th>Куда попадёт</th></tr></thead>
            <tbody id="glavapuRows"></tbody>
          </table></div>
          <!-- Предупреждения показываются, только когда есть о чём. Справка о
               том, как читается файл, уехала в «как это читается» ниже. -->
          <div id="glavapuWarnings" class="note warning" style="display:none"></div>
          <details id="glavapuNotesBox" style="display:none"><summary style="font-size:13px;padding:8px 0">Как читается файл</summary>
            <div id="glavapuNotes" class="note"></div>
          </details>
        </div>
        <!-- Загрузка готового файла — запасной путь для тех, у кого он уже на
             руках, а не первый шаг. Свёрнута, чтобы не разрывать «ввёл участок
             — получил ТЭП». -->
        <details class="import-fallback">
          <summary>Загрузить свой файл: заполненный шаблон ТЭП, расчёт с сайта ГлавАПУ или сохранённый проект</summary>
          <!-- Готовые примеры уехали в «Личный кабинет»: и они, и сохранённые
               проекты — это «взять готовое и посмотреть», а здесь разбирают
               принесённый файл. Решение владельца (15.08.2026). -->
          <div id="presetsMovedHint" style="font-size:11px;color:#888;margin:10px 0 8px">
            Готовые примеры — Мишина, Мытищи, Румянцево — переехали в «Личный кабинет» наверху страницы.
          </div>
          <div style="font-size:11px;color:#888;margin:7px 0 8px">Заполненный шаблон ТЭП или файл, скачанный с калькулятора ГлавАПУ:</div>
          <!-- Шаблон скачивается отсюда же, где загружается. Отказ разбора
               обещал кнопку «ниже», а её на странице не было вовсе: шаблон
               выдавал только бот командой /template, и человек с сайта узнать
               об этом ниоткуда не мог. -->
          <div class="upload-line">
            <input type="file" id="glavapuFile" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet">
            <button class="btn dark" onclick="uploadGlavapu()">Разобрать файл</button>
            <a class="btn" href="/templates/tep" download style="text-decoration:none">Скачать шаблон ТЭП</a>
          </div>
          <!-- Пресет проекта — это уже собранные ГПЗУ, ППТ, соглашения ВРИ и
               МПТ и справки по техприсоединению. Он заполняет проект целиком,
               поэтому и стоит отдельной строкой от разбора одной книги. -->
          <div style="font-size:11px;color:#888;margin:12px 0 8px">Или сохранённый проект (файл .json) — он заполнит всё сразу: ТЭП, смену разрешённого использования, рабочие места и подключение к сетям.</div>
          <div class="upload-line" style="margin-top:8px">
            <input type="file" id="presetFile" accept=".json,application/json">
            <button class="btn dark" onclick="uploadPreset()">Загрузить проект</button>
          </div>
        </details>
      </div>
      <div class="card">
        <div class="section-title">Вводные данные</div>
        <div id="inputGroups"></div>
      </div>
    </div>

    <div id="tep" class="panel">
      <!-- Порядок блоков вкладки — решение владельца (17.10.2026): участок и
           плотность одной компактной карточкой, сразу под ней таблица ТЭП,
           ниже — свёрнутые «Паркинг и нормативы» и параметры Подмосковья,
           затем сверка с ГлавАПУ. Каждая кнопка стоит у полей, которые она
           читает (владелец, 18.10.2026): заполнение по плотности — в карточке
           участка, пересчёт соцобъектов и парковки и подтягивание строк из
           «Экономики» — под таблицей. -->
      <div class="card site-card">
        <div class="section-title">Участок и плотность</div>
        <div id="otherRegionNote" class="note warning" style="display:none"></div>
        <div id="siteAreaWarning" class="note warning" style="display:none"></div>
        <div class="fields site-fields">
          <div class="field">
            <label>Площадь участка <span class="unit">га</span></label>
            <input type="number" step="0.0001" id="siteAreaHa" onchange="setSiteArea(this.value)">
            <span id="siteAreaSource" class="site-source"></span>
          </div>
          <div class="field">
            <label>Плотность застройки <span class="unit" id="siteDensityUnit">м² поэтажной площади / га</span></label>
            <input type="number" step="100" id="siteDensity" onchange="setSiteDensity(this.value)">
            <span id="siteDensitySource" class="site-source"></span>
          </div>
          <div class="field">
            <label><span id="sitePotentialLabel">Потенциал поэтажной площади</span> <span class="unit">м²</span></label>
            <b id="sitePotential" class="site-value">—</b>
          </div>
          <div class="field">
            <label><span id="siteUsageLabel">Использовано наземными зданиями</span> <span class="unit">от потенциала</span></label>
            <b id="siteUsage" class="site-value">—</b>
          </div>
        </div>
        <div class="tep-action">
          <button class="btn" onclick="formTepByDensity()">Сформировать ТЭП по новым параметрам</button>
          <span class="tep-action-hint" id="siteApplyHint">Поменяли площадь или плотность — нажмите, и таблица ниже заполнится заново: квартиры, магазины на первом этаже, детсады, школы и парковка; перед заменой покажем, что изменится.</span>
        </div>
        <div id="siteApplyStatus" class="import-status" style="display:none"></div>
        <!-- Эквивалент плотности по другой методике — справка, а не параметр:
             раскрывается по желанию, чтобы не занимать экран телефона. -->
        <details class="site-help">
          <summary>Как считается плотность</summary>
          <span id="siteDensityEquiv"></span>
        </details>
        <div id="siteDensityWarn" class="note warning" style="display:none"></div>
      </div>
      <div class="card">
        <div id="tepRatioNote" style="color:#777;font-size:11px;margin:2px 0 8px"></div>
        <div id="tepDerivedNote" class="import-status" style="display:none"></div>
        <div class="scroll"><table class="teptable"><thead><tr><th>Продукт</th><th>ГНС, м²</th><th>Общая площадь, м²</th><th>Полезная площадь, м²</th><th>Продаваемая площадь, м²</th><th>Передаваемая площадь, м²</th><th>Количество, шт.</th></tr></thead><tbody id="tepBody"></tbody><tfoot><tr><th>Итого</th><th id="tg"></th><th id="ta"></th><th id="tu"></th><th id="ts"></th><th id="tt"></th><th id="tn"></th></tr></tfoot></table></div><div id="tepUndergroundNote" class="hint" style="margin-top:6px"></div>
        <div class="tep-action" id="tepNormsAction">
          <button class="btn" onclick="recalcFromTep()">Пересчитать по нормативам</button>
          <span class="tep-action-hint" id="tepNormsHint"></span>
        </div>
        <!-- Синхронизация строк с «Экономикой» — решение владельца (18.10.2026):
             кнопку оставить, хотя правка полей обновляет строки сама: нужна,
             когда число в таблице разошлось с полем (давно сохранённый проект). -->
        <div class="tep-action tep-action-secondary">
          <button class="btn" onclick="syncTep()">Подтянуть значения из «Экономики» (МФЦ, ТЦ, паркинг и др.)</button>
          <span class="tep-action-hint">Нужна редко: при правке полей в «Экономике» эти строки обновляются сами. Нажмите, если число в таблице не совпадает с полем — например, в давно сохранённом проекте. Квартиры и коммерцию 1 этажа не меняет.</span>
        </div>
      </div>
      <div class="card" id="tepSettingsCard">
        <!-- Коэффициенты парковки называет город по ЭТОМУ участку, поэтому они
             здесь, а не во «Вводных». Поля рисует renderSiteParkingFields по
             объявлению FIELD_GROUPS — подписей второй копией нет. -->
        <!-- Свёрнут по умолчанию: поля нужны редко, а в заголовке видно, что
             принял расчёт (К1, К2, район) и есть ли противоречие с кадастром.
             Узел статичный — перерисовка меняет только поля, и раскрытое
             человеком остаётся раскрытым. -->
        <details class="site-parking-box" id="siteParkingBox">
          <summary id="siteParkingSummary">Паркинг и нормативы</summary>
          <div class="fields" id="siteParkingFields" style="grid-template-columns:repeat(auto-fit,minmax(170px,1fr))"></div>
        </details>
        <!-- Параметры Подмосковья стоят здесь, а не на «Вводных»: два поля из
             шести — та же плотность и та же площадь участка, что в карточке
             участка, и рядом видно, что правится одно и то же. На «Вводных» они
             разрывали путь «ввёл участок — получил ТЭП». -->
        <details class="cadastral-box mo-box" id="moParamsBox">
          <summary>Параметры расчёта по Московской области</summary>
          <p>Плотность, площадь участка и средняя площадь квартиры дают ТЭП: сколько метров квартир можно построить, сколько нужно мест в детских садах и школах и сколько машино-мест. Плата за смену разрешённого использования участка (ВРИ) в Подмосковье считается так: средняя цена метра жилья в округе (Кср) × площадь квартир × коэффициент доходности (Кд). Числа подставляются из справочников сами. Меняйте их, только если знаете точные значения по своему проекту: введённое вами важнее справочного. <b>Правка любого параметра сразу пересчитывает ТЭП участка.</b></p>
          <div class="mo-params">
            <div class="field"><label>Плотность <span class="unit">м² квартир на гектар. Это то же поле, что в карточке «Участок и плотность»</span></label><input type="number" id="moDensity" value="30000" step="500"></div>
            <div class="field"><label>Площадь участка вручную <span class="unit">га. Заполните, если участка нет в ЕГРН. Это то же поле, что в карточке «Участок и плотность»</span></label><input type="number" id="moArea" value="" step="0.0001" placeholder="из ЕГРН"></div>
            <div class="field"><label>Городской округ <span class="unit">по нему берутся цена метра жилья и кадастровая стоимость</span></label><select id="moDistrict"><option value="">определить по участку</option></select></div>
            <div class="field"><label>Средняя цена м², Кср <span class="unit" id="moPriceUnit">₽/м². Берётся из справочника</span></label><input type="number" id="moPrice" value="" step="1000" readonly><label class="mo-manual"><input type="checkbox" id="moPriceManual" onchange="toggleMoPrice()"> задать вручную</label></div>
            <div class="field"><label>Коэффициент доходности Кд <span class="unit" id="moKdUnit">доля. Берётся из справочника</span></label><input type="number" id="moKd" value="" step="0.01" readonly><label class="mo-manual"><input type="checkbox" id="moKdManual" onchange="toggleMoKd()"> задать вручную</label></div>
            <div class="field"><label>Средняя площадь квартиры <span class="unit">м²</span></label><input type="number" id="moFlat" value="" step="0.25"><span class="hint" id="moFlatBasis"></span></div>
          </div>
          <div class="mo-price-line"><span id="moPriceState">Справочники загружаются…</span></div>
        </details>
      </div>
      <!-- Сверка сценария: калькулятору ГлавАПУ выставляются НАШИ параметры
           (доля жилья и коммерции, СПП, площадь, нежильё по ВРИ, соцобъекты,
           вид права), и его ответ стоит рядом с нашим по видам. Карточка —
           последняя на вкладке: сначала наши числа и настройки, ниже их
           проверка. ГлавАПУ — проверка: наши значения он не заменяет. -->
      <div class="card" id="glavapuScenarioBox">
        <div class="section-title">Сверка с калькулятором ГлавАПУ</div>
        <div class="toolbar">
          <button class="btn" id="glavapuScenarioButton" onclick="glavapuScenarioCheck()">Сверить сценарий</button>
          <span style="color:#777;font-size:12px">Калькулятору уходят ТЭП, площадь и соцобъекты этого проекта; считает в фоне 1–3 минуты. ГлавАПУ — проверка, наши значения не меняются.</span>
        </div>
        <div id="glavapuScenarioStatus" class="import-status" style="display:none"></div>
        <!-- Итог — здесь, полная таблица — окном по кнопке (решение владельца,
             06.10.2026): расчёт идёт минуты, и окно, всплывшее само, перебило
             бы работу с ТЭП. -->
        <div id="glavapuScenarioSummary" style="display:none"></div>
      </div>
    </div>

    <div id="vri" class="panel">
      <div class="card">
        <div class="report-title">
          <div>
            <div class="section-title">Плата за изменение ВРИ</div>
            <h2>Обязательство, льгота, график погашения и источники оплаты</h2>
          </div>
          <small>Влияет на размер БРИДЖа, потребность в ПФ и стоимость денег</small>
        </div>
        <div class="note"><b>Дата обязательства по умолчанию — экспертно за месяц до РнС.</b> На этапе инвестиционного анализа точная дата соглашения обычно неизвестна; после появления утверждённых документов и графика её необходимо заменить на фактическую. Платежи до открытия ПФ несёт БРИДЖ или собственный капитал, после — ПФ, и только если ВРИ включена в банковский бюджет. Проценты по рассрочке считаются отдельно от процентов по кредитам.</div>
        <div id="vriInputGroups"></div>
      </div>
      <!-- Льготы по плате за ВРИ, посчитанные по проекту: за создание МПТ
           (1874-ПП, по каждому нежилому объекту) и за передачу квартир городу.
           Считаются всегда, когда есть нежильё или передача, — в расчёт идут
           только кнопкой (владелец, 06.10.2026). Числа считает сервер
           (`vri_benefits`), страница их только рисует. -->
      <div class="card" id="vriBenefitsCard" style="display:none">
        <div class="section-title">Льготы по плате за ВРИ и рабочие места</div>
        <div id="vriBenefitsBody"></div>
      </div>
      <div class="card" id="vriTabCard" style="display:none">
        <div class="section-title">Результат</div>
        <div class="report-2col">
          <table class="metric-table metric-compact" id="vriTabTotals"></table>
          <div class="scroll" style="max-height:420px">
            <table class="metric-table metric-compact">
              <thead><tr><th>Дата</th><th>Основной долг</th><th>Проценты</th><th>Платёж</th><th>Остаток</th><th>Источник</th></tr></thead>
              <tbody id="vriTabSchedule"></tbody>
            </table>
          </div>
        </div>
        <div id="vriTabWarnings" class="note" style="display:none"></div>
      </div>
      <div class="card" id="vriTabEmpty">
        <div class="note" id="vriTabEmptyNote">Изменение ВРИ не требуется или сумма обязательства равна нулю — график не строится.</div>
      </div>
    </div>

    <div id="phasing" class="panel">
      <div class="card">
        <div class="report-title">
          <div><div class="section-title">Очередность реализации</div><h2>Разбиение мастер-проекта на очереди</h2></div>
          <div class="phase-switch">
            <label><input id="phasingEnabled" type="checkbox" onchange="togglePhasing(this.checked)"> Включить очередность</label>
            <button class="btn" onclick="autoSuggestPhasing()">Автопредложение</button>
          </div>
        </div>
        <div class="note">Текущий одноочередный расчёт не меняется. В многоочередном режиме каждая очередь считается отдельно тем же движком, после чего строится единый свод без двойного счёта.</div>
        <div id="phaseFinanceHint" class="note phase-config-only">Очереди включены. Проверьте, как финансируются очереди, в разделе «Экономика → Финансирование». <button type="button" class="btn" style="margin-top:8px" onclick="openPhaseFinancing()">Перейти к финансированию очередей</button></div>
        <div class="phase-grid phase-config-only">
          <div class="field"><label>Количество очередей</label><select id="phaseCount" onchange="setPhaseCount(Number(this.value))"><option selected>1</option><option>2</option><option>3</option><option>4</option><option>5</option></select></div>
          <div class="field"><label>Целевой размер очереди, продаваемых м²</label><input id="phaseTargetSize" type="number" step="5000" value="70000" onchange="phasing.target_size_sqm=Number(this.value);renderPhasing()"></div>
          <div class="field"><label>Сдвиг старта, мес.</label><input id="phaseGap" type="number" value="12" min="3" max="36" onchange="phasing.phase_gap_months=Number(this.value);autoPhaseDates()"></div>
          <div class="field"><label>Инфляция себестоимости, % год</label><input id="phaseCostInflation" type="number" value="8" min="0" max="30" step="0.5" onchange="phasing.cost_inflation_pct=Number(this.value);renderPhasing();calculate()"></div>
          <div class="field"><label>Инфляция цены продажи, % год</label><input id="phaseSalesPriceInflation" type="number" value="8" min="-20" max="50" step="0.5" onchange="phasing.sales_price_inflation_pct=Number(this.value);renderPhasing();calculate()"></div>
          <div class="field"><label>Рекомендация</label><div id="phaseRecommendation" style="padding:10px 0;font-weight:700">—</div></div>
        </div>
        <div id="phaseCards" class="phase-grid phase-config-only"></div>
      </div>

      <div class="card phase-config-only">
        <div class="section-title">Распределение массовых продуктов</div>
        <div class="scroll"><table class="phase-table"><thead id="phaseProductHead"></thead><tbody id="phaseProductBody"></tbody></table></div>
        <div id="phaseProductStatus" class="phase-status"></div>
      </div>

      <div class="card phase-config-only">
        <div class="report-title">
          <div><div class="section-title">Реальные ТЭП очередей</div><h2>Продукты и обязательные объекты после распределения долей</h2></div>
          <small>Пустое поле — расчёт по долям; введённое значение становится авторитетным</small>
        </div>
        <div class="note">ГНС, продаваемая площадь и количество хранятся внутри конкретной очереди. Для школ, ДОО и прочих обязательных объектов продаваемая площадь должна быть равна нулю.</div>
        <div id="phaseTepWarning" class="phase-total-bad" style="min-height:18px;margin:8px 0" aria-live="polite"></div>
        <div class="scroll" style="max-height:none"><table class="phase-table"><thead id="phaseTepHead"></thead><tbody id="phaseTepBody"></tbody></table></div>
      </div>

      <!-- Стратегия финансирования очередей живёт в «Экономика → Финансирование»
           последним блоком группы: её туда ставит renderInputs из этого шаблона
           (одна разметка), и только при очередности на 2+ очереди. Выбор хранится
           в `phasing`, а не в узлах, поэтому скрытый блок значений не теряет. -->
      <template id="phaseFinancingTemplate">
        <section class="field-card" id="phaseFinancingBlock">
          <div class="field-section">Стратегия финансирования очередей</div>
          <div class="hint" style="color:#666;font-size:12px">Каждая очередь финансируется отдельно или деньги проекта общие для всех очередей.</div>
          <div style="display:grid;gap:8px;margin:10px 0">
            <label><input id="phaseFinancingIndependent" name="phaseFinancingStrategy" type="radio" value="independent" onchange="setPhaseFinancingStrategy(this.value)"> Независимое финансирование очередей <small>— по умолчанию</small></label>
            <label><input id="phaseFinancingUnified" name="phaseFinancingStrategy" type="radio" value="unified_project_cash" onchange="setPhaseFinancingStrategy(this.value)"> Единый денежный поток проекта</label>
          </div>
          <div class="note">В едином потоке деньги, которые предыдущие очереди уже заработали и которые остались у них после выплат по кредитам, идут на расходы следующей очереди до разрешения на строительство (РнС). Деньги покупателей на счетах эскроу, будущая прибыль, ещё не взятые кредиты — бридж (кредит на старт проекта до проектного финансирования) и проектное финансирование (ПФ, банковский кредит на стройку) — и кредит другой очереди на это не тратятся.</div>
          <div style="display:grid;gap:8px;margin:12px 0 4px">
            <label><input id="phaseCarryDebt" type="checkbox" onchange="setPhaseCarryDebt(this.checked)"> Если очередь не успела вернуть кредит, остаток долга переходит в проектное финансирование следующей очереди</label>
            <label title="Очередь передала долг, но продолжает продавать квартиры. Банк забирает долю её выручки сразу в погашение долга, а остальное остаётся в запасе проекта."><input id="phaseSweepCash" type="checkbox" onchange="setPhaseSweepCash(this.checked)"> Банк забирает долю выручки очереди, которая передала свой долг следующей</label>
            <label style="margin-left:18px">Сколько выручки забирает банк, %: <input id="phaseSweepPct" type="number" min="0" max="100" step="5" style="width:64px" onchange="setPhaseSweepPct(this.value)"></label>
          </div>
          <div class="note">Долг переходит в тот день, когда банк по общему договору открывает проектное финансирование следующей очереди. Лимит кредита этой очереди он не расходует, но проценты на него начисляются как на обычный долг. Из-за него деньги покупателей на эскроу покрывают меньшую часть кредита, и он учитывается в коэффициенте покрытия долга очереди, которая его приняла (LLCR — во сколько раз деньги, которые проект ещё получит, перекрывают долг). Перенос разрешён, только если этот коэффициент по всему проекту не ниже 1,00. Иначе банк не спасает проект, а только откладывает дефолт, и расчёт откажет в переносе, назвав причину. Excel-файл перенос долга пока не учитывает: если его включить, финансирование в файле разойдётся с отчётом.</div>
          <div id="phaseFinancingSummary" class="phase-status" style="margin:10px 0">Расчёт очередей ещё не выполнен.</div>
          <div class="scroll"><table class="phase-table">
            <thead><tr><th>Очередь</th><th>Расходы до разрешения на строительство</th><th>Оплачено свободными деньгами проекта</th><th>Собственные средства</th><th>Новый бридж</th><th>Проектное финансирование после разрешения на строительство</th></tr></thead>
            <tbody id="phaseFinancingBody"></tbody>
          </table></div>
        </section>
      </template>

      <div class="card phase-config-only">
        <div class="section-title">Общепроектные расходы — фактический Cash Flow</div>
        <div style="font-size:11px;color:#777;margin-bottom:10px">О1 по умолчанию несёт покупку, ВРИ и повышенную долю ИРД. Проектирование, подготовка и наружные сети идут по объёму очереди — цена метра у каждой равна вводной; заданная руками доля показывает рядом фактическую цену метра.</div>
        <div class="scroll"><table class="phase-table"><thead id="phaseCashHead"></thead><tbody id="phaseCashBody"></tbody></table></div>
      </div>

      <div class="card phase-config-only">
        <div class="section-title">Экономическая аллокация общих расходов</div>
        <div style="font-size:11px;color:#777;margin-bottom:10px">Только аналитика очередей. Сводный денежный поток не меняется.</div>
        <div class="scroll"><table class="phase-table"><thead id="phaseAllocHead"></thead><tbody id="phaseAllocBody"></tbody></table></div>
      </div>

      <div class="card phase-config-only">
        <div class="report-title"><div><div class="section-title">Социальные объекты</div><h2>Реестр и очередь строительства</h2></div></div>
        <div class="object-actions">
          <button class="btn" onclick="autoSocialObjects()">Авторазбивка соцобъектов</button>
          <button class="btn" onclick="addSocialObject('kindergarten')">+ ДОО</button>
          <button class="btn" onclick="addSocialObject('school')">+ СОШ</button>
          <button class="btn" onclick="addSocialObject('clinic')">+ Поликлиника</button>
        </div>
        <div class="scroll"><table class="phase-table">
          <thead><tr><th>Объект</th><th>Тип</th><th>Мощность</th><th>Очередь</th><th>Начало (опц.)</th><th></th></tr></thead>
          <tbody id="socialObjectsBody"></tbody>
        </table></div>
        <div id="socialObjectsStatus" class="phase-status"></div>
      </div>

      <div class="card phase-config-only">
        <div class="section-title">Отдельные коммерческие объекты</div>
        <div class="phase-grid" id="assignObjects">
          <!-- Поля рисует renderPhasing по реестру объектов: разметкой стояли
               четыре, и пятый объект остался бы без очереди молча. -->
        </div>
        <div class="note">Коммерция первых этажей, подземный паркинг и кладовые делятся по очередям процентами. ОСЗ, офисы и отдельный наземный паркинг относятся целиком к выбранной очереди.</div>
      </div>
    </div>

    <div id="rates" class="panel">
      <div class="card">
        <div class="report-title">
          <div>
            <div class="section-title">Прогноз ключевой ставки</div>
            <h2>Автоматическая кривая нормализации</h2>
          </div>
          <button class="btn" onclick="refreshCurrentKeyRate(true)">Обновить из ЦБ</button>
        </div>

        <div class="fields" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">
          <div class="field">
            <label>Текущая ставка ЦБ <span class="unit">%</span></label>
            <input id="rateStartPct" type="number" step="0.01" readonly>
            <div id="cbrRateStatus" style="font-size:10px;color:#777;margin-top:4px">—</div>
          </div>
          <div class="field">
            <label>Горизонт нормализации <span class="unit">мес.</span></label>
            <input id="rateNormalizationMonths" type="number" min="6" max="60" step="1" onchange="syncRateModel(true)">
          </div>
          <div class="field">
            <label>Консервативная цель <span class="unit">%</span></label>
            <input id="rateTargetHigh" type="number" step="0.25" onchange="syncRateModel(true)">
          </div>
          <div class="field">
            <label>Базовая цель <span class="unit">%</span></label>
            <input id="rateTargetBase" type="number" step="0.25" onchange="syncRateModel(true)">
          </div>
          <div class="field">
            <label>Оптимистичная цель <span class="unit">%</span></label>
            <input id="rateTargetLow" type="number" step="0.25" onchange="syncRateModel(true)">
          </div>
        </div>

        <div class="toolbar" style="margin-top:8px">
          <div>
            <span style="font-size:12px;color:#555">Сценарий ставки:&nbsp;</span>
            <select id="rateScenario" onchange="inputs.rate_scenario=this.value;calculate()" style="width:auto;min-width:180px">
              <option value="high">Консервативный</option>
              <option value="base">Базовый</option>
              <option value="low">Оптимистичный</option>
            </select>
          </div>
          <span style="font-size:11px;color:#777">Кривая: плавное ускоренное снижение в начале и замедление по мере приближения к цели; после горизонта ставка фиксируется на целевом уровне.</span>
        </div>

        <div id="rateCurveChart" class="chart" style="height:300px;margin-top:18px"></div>
      </div>

      <div class="card">
        <div class="section-title">Автоматически рассчитанная помесячная кривая</div>
        <div class="scroll">
          <table>
            <thead><tr><th>Дата</th><th>Консервативная, %</th><th>Базовая, %</th><th>Оптимистичная, %</th></tr></thead>
            <tbody id="rateBody"></tbody>
          </table>
        </div>
      </div>
    </div>

    <div id="finance" class="panel">
      <div class="card" data-nonres-finance-card hidden>
        <div class="section-title">Финансирование объекта — кредит вне ДДУ</div>
        <div class="nonres-finance-box"></div>
      </div>
      <div class="card" data-equity-card hidden>
        <div class="section-title">Собственное участие</div>
        <div class="equity-box"></div>
      </div>
      <div class="card" data-needs="project_finance">
        <div class="llcr-hero">
          <div><div class="section-title">LLCR — расчётный</div><div id="llcrValue" class="llcr-value">—</div></div>
          <div class="llcr-label">Показатель рассчитан текущим веб-движком. Пока кредитный CF не сверён помесячно с актуальным Excel, LLCR нельзя считать контрольным значением модели.</div>
        </div>
      </div>
      <div class="kpis" id="financeKpi" data-needs="project_finance"></div>
      <div class="note" style="margin-top:16px" data-needs="project_finance">Низкая «эффективная ставка ПФ» может возникать из-за льготной ставки при покрытии долга средствами на эскроу. Поэтому она показана отдельно от базовой ставки ПФ до эскроу.</div>

      <div class="finance-grid" style="margin-top:18px" data-needs="project_finance">
        <div class="card"><div class="section-title">БРИДЖ</div><table class="metric-table" id="bridgeTable"></table></div>
        <div class="card"><div class="section-title">Проектное финансирование</div><table class="metric-table" id="pfTable"></table></div>
        <div class="card"><div class="section-title">Проценты и комиссии</div><table class="metric-table" id="interestTable"></table></div>
      </div>

      <div class="card" data-needs="project_finance">
        <div class="section-title">Эскроу против обязательств по ПФ</div>
        <div id="financeChart" class="chart"></div>
        __DEVELOPAID_ESCROW_LEGEND__
        <div id="escrowCoverNote" class="note"></div>
        <div id="financeEscrowPhases"></div>
      </div>

      <div class="card" data-needs="project_finance">
        <div class="section-title">Расчёт LLCR</div>
        <table class="metric-table" id="llcrTable"></table>
      </div>

      <div class="card">
        <div class="section-title">Налог на прибыль</div>
        <table class="metric-table" id="taxTable"></table>
        <div class="note" data-layout="housing">Маржа объектов КРТ признаётся по реализованным м² или машино-местам. Маржа дома признаётся при его вводе (РВЭ), проценты и комиссии — в месяце начисления; убыток прошлых лет гасит не больше половины прибыли года. Налог уходит авансами по итогам квартала и доплатой года в марте.</div>
      </div>

      <div class="card" data-needs="project_finance">
        <div class="section-title">Помесячное финансирование</div>
        <div class="scroll"><table class="monthly"><thead><tr><th>Месяц</th><th>Ключевая</th><th>БРИДЖ</th><th>Ставка БРИДЖ</th><th>% БРИДЖ</th><th>ПФ</th><th>Начислено к уплате</th><th>Эскроу</th><th>Покрытие</th><th>Ставка ПФ</th><th>% ПФ</th><th>Комиссия лимита</th><th>Погашение ПФ</th><th>Налог на прибыль</th></tr></thead><tbody id="monthlyFinance"></tbody></table></div>
      </div>
      <div class="note warning" data-needs="project_finance">LLCR остаётся расчётным показателем веб-движка до завершения помесячной сверки кредитного CF с актуальной Excel-моделью.</div>
    </div>

    <div id="calendar" class="panel">
      <div class="card">
        <div class="report-title"><div><div class="section-title">Календарный график проекта</div><h2>Этапы, финансирование, продажи и ключевые вехи</h2></div><small id="calendarRange">—</small></div>
        <div class="dates" id="calendarDateBoxes" style="margin-bottom:18px"></div>
        <div style="font-size:11px;color:#777;margin:-4px 0 12px">Шкала разбита по годам и кварталам. Каждый квартал имеет фиксированную минимальную ширину, поэтому короткие фазы проекта не сливаются.</div>
        <div id="calendarGantt" class="gantt-wrap"></div>
        <div id="calendarTypeLegend" class="gantt-legend"><span>Проект / строительство</span><span>Финансирование</span><span>Продажи</span></div>
        <div id="calendarPhaseLegend" class="gantt-phase-legend"></div>
      </div>
    </div>

    <div id="sensitivity" class="panel">
      <div class="card">
        <div class="report-title"><div><div class="section-title">Анализ чувствительности</div><h2>Что решает судьбу проекта</h2></div></div>
        <p style="font-size:12px;color:#555;margin:0 0 14px">Меняется <b>один параметр за расчёт</b>, остальные держатся на месте. Сценарии «консервативный / базовый / оптимистичный» этого не заменяют: там цены и затраты двигаются одновременно, и по ним не видно, какой именно параметр решает судьбу проекта. Считает движок модели — те же формулы, что и основной расчёт.</p>
        <div class="grid" id="sensitivityControls"></div>
        <div style="margin:14px 0 4px"><button class="btn dark no-print" id="sensitivityRun" onclick="runSensitivity()">Рассчитать чувствительность</button>
          <span id="sensitivityStatus" style="font-size:12px;color:#777;margin-left:10px"></span></div>
        <details id="sensitivityPicker" style="margin-top:12px"><summary style="cursor:pointer;font-size:12px;color:#555">Какие параметры анализировать</summary>
          <div id="sensitivityParams" style="margin-top:10px"></div></details>
      </div>
      <div class="card" id="sensitivityResult" style="display:none">
        <div class="report-title"><div><div class="section-title" id="sensitivityScope"></div><h2 id="sensitivityTitle"></h2></div></div>
        <div id="sensitivityChart" class="tornado-wrap"></div>
        <div id="sensitivityTable"></div>
        <div id="sensitivityVerdict" class="note" style="margin-top:14px"></div>
        <div id="sensitivityWarnings" style="font-size:11px;color:#a35d00;margin-top:10px"></div>
      </div>
    </div>

    <div id="report" class="panel">
      <!-- Экономика за входом: плашка стоит первой в отчёте, чтобы человек
           видел причину там, где ждал числа (решение владельца, 18.08.2026). -->
      <div id="calcLocked" class="calc-locked" style="display:none"></div>
      <div class="card report-hero">
        <div class="report-title">
          <div><div class="section-title">Управленческий отчёт</div><h2>Экономика и ключевые показатели проекта</h2></div>
          <div class="report-actions">
            <small>Агрегированный отчёт · значения пересчитываются из текущих вводных</small>
            <button class="btn dark no-print" onclick="exportReportPdf()">Экспорт PDF</button>
            <button class="btn no-print" onclick="exportTeaserPdf()" title="Одна страница A4: шесть KPI, ТЭП, продажи, риски и происхождение расчёта — из той же модели, что дашборд книги">Скачать тизер</button>
            <button id="exportModelButton" class="btn no-print" onclick="exportModelArchive()">Скачать модель (Excel)</button>
          </div>
        </div>
        <div class="pdf-report-meta">
          <b>DevelopAid · Инвестиционная модель девелоперского проекта</b>
          <span id="pdfReportMeta">—</span>
        </div>
        <div class="kpis report-kpis" id="reportKpi"></div>
        <div id="pfRveWarning" class="note warning" style="display:none;margin-top:14px"></div>
      </div>

      <div class="report-toc no-print" id="reportToc"></div>

      <div class="report-section" id="rsSite" data-layout="housing">
        <div class="report-section-title">Участок и продукт</div>
      <div class="card">
        <div class="section-title">ТЭП</div>
        <div class="scroll" style="max-height:none"><table id="reportTep"></table></div>
        <div id="reportTepNote" style="font-size:11px;color:#777;margin-top:6px"></div>
      </div>
      <div class="card" id="vriCard" style="display:none">
        <div class="report-title">
          <div>
            <div class="section-title">Плата за изменение ВРИ</div>
            <h2>Обязательство, график погашения и источники оплаты</h2>
          </div>
          <small id="vriMode"></small>
        </div>
        <div class="report-2col">
          <table class="metric-table metric-compact" id="vriTotalsTable"></table>
          <div class="scroll" style="max-height:340px">
            <table class="metric-table metric-compact">
              <thead><tr><th>Дата</th><th>Основной долг</th><th>Проценты</th><th>Платёж</th><th>Остаток</th><th>Источник</th></tr></thead>
              <tbody id="vriScheduleTable"></tbody>
            </table>
          </div>
        </div>
        <div id="vriWarnings" class="note" style="display:none"></div>
      </div>
      <div class="card" data-needs="housing">
        <div class="section-title">Социальная нагрузка</div>
        <table class="metric-table metric-compact" id="socialTable"></table>
      </div>
      </div>

      <div class="report-section" id="rsSummary" data-layout="housing">
        <div class="report-section-title">Итог</div>
      <div class="report-2col">
        <div class="card">
          <div class="section-title">Экономика проекта</div>
          <table class="metric-table metric-compact" id="economicsTable"></table>
        </div>
        <div class="card">
          <div class="section-title">Ключевые параметры</div>
          <table class="metric-table metric-compact" id="projectParamsTable"></table>
        </div>
      </div>
      <div class="card">
        <div class="section-title">Удельная экономика</div>
        <div style="font-size:11px;color:#777;margin:-5px 0 10px">
          Каждая строка — на свою базу: расходы на м² __DEVELOPAID_TERM_total_area_genitive__ (наземная и подземная), выручка и прибыль на м² продаваемой. Расходы — ещё и на 1 м² продаваемой, для сравнения с ценой.
        </div>
        <div class="scroll" style="max-height:none">
          <table class="unit-table">
            <thead><tr><th>Показатель</th><th>Всего</th><th>тыс. ₽/м² своей базы</th><th>База</th><th>тыс. ₽/м² прод.</th></tr></thead>
            <tbody id="unitEconomicsTable"></tbody>
          </table>
        </div>
      </div>
      </div>

      <div class="report-section" id="rsPhases" data-layout="housing">
        <div class="report-section-title">Очереди проекта</div>
      <div id="phaseReportControls" class="phase-report-nav no-print" style="display:none"></div>
      <div id="phaseComparisonCard" class="card phase-comparison-card">
        <div class="section-title">Сравнение очередей</div>
        <div class="scroll" style="max-height:none"><table class="metric-table">
          <thead id="phaseComparisonHead"></thead>
          <tbody id="phaseComparisonBody"></tbody>
        </table></div>
        <div class="note">Аналитическая прибыль после аллокации перераспределяет общепроектные расходы только для сравнения очередей. Сводный CF не меняется.</div>
        <div id="phaseDebtCarryNote" class="note" style="display:none"></div>
      </div>
      </div>

      <div class="report-section" id="rsExpenses" data-layout="housing">
        <div class="report-section-title">Расходы</div>
      <div class="card">
        <div class="report-title">
          <div>
            <div class="section-title">Структура расходов</div>
            <h2>Из чего складываются полные расходы проекта</h2>
          </div>
          <small>Сумма и доля каждой категории от 100% расходов</small>
        </div>
        <div class="report-2col">
          <div id="expenseStructureChart" class="expense-bars"></div>
          <div class="scroll" style="max-height:none">
            <table class="metric-table metric-compact">
              <thead><tr><th>Категория</th><th>Сумма</th><th>Доля</th><th id="expenseBaseHead">тыс ₽/м² __DEVELOPAID_TERM_total_area_genitive__</th><th>тыс ₽/м² прод.</th></tr></thead>
              <tbody id="expenseStructureTable"></tbody>
              <tfoot><tr><th>Итого расходов</th><th id="expenseTotal"></th><th>100%</th><th id="expenseTotalGns"></th><th id="expenseTotalSaleable"></th></tr></tfoot>
            </table>
          </div>
        </div>
      </div>
      <div class="card">
        <div class="section-title">Структура затрат по статьям</div>
        <div class="scroll" style="max-height:none"><table><thead><tr><th>Статья</th><th>Сумма</th><th>тыс ₽/м² своей базы</th><th>База</th><th>тыс ₽/м² прод.</th></tr></thead>
        <tbody id="capexTable"></tbody></table></div>
      </div>
      </div>

      <div class="report-section" id="rsIncome" data-layout="housing">
        <div class="report-section-title">Доходы</div>
      <div class="card">
        <div class="section-title">Структура выручки</div>
        <table><thead><tr><th>Продукт</th><th>Выручка</th><th>Доля</th><th>тыс ₽/м² продаваемой площади</th></tr></thead>
        <tbody id="revenueTable"></tbody></table>
      </div>
      <div class="card" id="nonresStrategyCard" hidden>
        <div class="section-title">Нежильё — стратегия реализации</div>
        <div id="nonresStrategyTables"></div>
      </div>
      <div class="card" id="hotelReportCard" hidden>
        <div class="section-title">Гостиница — эксплуатация (USALI)</div>
        <div id="hotelReportBody"></div>
      </div>
      <div class="card">
        <div class="section-title">Темпы и цены продаж</div>
        <div class="scroll" style="max-height:none">
          <table>
            <thead id="salesReportHead"><tr><th>Продукт</th><th>Объём</th><th>Темп до РВЭ</th><th>Продажи до РВЭ</th><th>Стартовая цена</th><th>Средняя цена</th><th>Выручка</th><th>Старт продаж</th><th>Финиш продаж</th></tr></thead>
            <tbody id="salesReportTable"></tbody>
          </table>
        </div>
        <div class="hint" id="salesCostBasis"></div>
        <!-- Квартиры продаются штуками: план отдела продаж и рыночная проверка
             живут в них, а таблица выше говорит только метрами. -->
        <table class="metric-table metric-compact" id="apartmentPaceTable"></table>
        <!-- Тот же темп помесячно. График был только в PDF: человек смотрел
             отчёт на экране, печатал его и видел незнакомый раздел. Средний
             темп прячет и разгон, и сезонный провал, и обрыв после РВЭ. -->
        <div id="apartmentPaceChart" class="chart" style="height:auto"></div>
      </div>
      <div class="card">
        <div class="section-title">Налоговая база по реализованным продуктам</div>
        <table class="metric-table metric-compact" id="reportTaxTable"></table>
      </div>
      </div>

      <div class="report-section" id="rsFinance" data-layout="housing">
        <div class="report-section-title">Финансирование</div>
      <div class="card" data-nonres-finance-card hidden>
        <div class="section-title">Финансирование объекта — кредит вне ДДУ</div>
        <div class="nonres-finance-box"></div>
      </div>
      <div class="card" data-equity-card hidden>
        <div class="section-title">Собственное участие</div>
        <div class="equity-box"></div>
      </div>
      <div class="report-2col" data-needs="project_finance">
        <div class="card">
          <div class="section-title">Финансирование</div>
          <table class="metric-table metric-compact" id="reportFinanceTable"></table>
        </div>
        <div class="card">
          <div class="section-title">Ставки финансирования</div>
          <table class="metric-table metric-compact" id="ratesDebtTable"></table>
        </div>
      </div>
      <div class="card" data-needs="project_finance">
        <div class="section-title">Эскроу против обязательств по ПФ</div>
        <div id="reportEscrowChart" class="chart"></div>
        __DEVELOPAID_ESCROW_LEGEND__
        <div id="reportEscrowNote" class="note"></div>
        <div id="reportEscrowPhases"></div>
      </div>

      <div class="card" data-needs="project_finance">
        <div class="section-title" id="bridgePurposeTitle">Структура расчётного БРИДЖа</div>
        <table class="metric-table metric-compact bridge-purpose-table" id="bridgePurposeTable"></table>
        <div class="bridge-purpose-note" id="bridgePurposeNote">В лимит входит только то, что платится ДО РнС: при рассрочке покупки часть, приходящаяся на период после РнС, финансируется уже ПФ. Смена ВРИ / земельные права, проценты и комиссии в расчётный лимит БРИДЖа не входят.</div>
        <!-- Расчётный лимит расшифрован по целям методики, а фактический пик не
             был расшифрован ничем — и разница между ними, то самое «остальное
             вашими», разбиралась перепиской. -->
        <div class="section-title" style="margin-top:20px">Структура фактического БРИДЖа<span id="bridgeActualMonth"></span></div>
        <table class="metric-table metric-compact bridge-purpose-table" id="bridgeActualTable"></table>
        <div class="bridge-purpose-note" id="bridgeActualNote"></div>
      </div>
      </div>

      <!-- Отчёт проекта без жилья — свои разделы (`report.object_report`
           движка): решение → объект → стратегия → доходы → затраты →
           финансирование → экономика собственника. Чувствительность и
           календарь — общие разделы ниже, с заголовками из `report.layout`. -->
      <div id="objectReport" data-layout="object" hidden></div>

      <div class="report-section" id="rsSensitivity">
        <div class="report-section-title">Чувствительность</div>
      <div class="card">
        <div id="reportSensitivity"></div>
      </div>
      </div>

      <div class="report-section" id="rsCalendar">
        <div class="report-section-title">Календарный план</div>
      <div class="card">
        <div class="dates" id="reportCalendarDates"></div>
        <div id="reportCalendarGantt" class="gantt-wrap"></div>
      </div>
      </div>

      <div class="note warning" data-layout="housing">LLCR, NPV и IRR в веб-модели являются расчётными показателями текущего движка. До полного отказа от Excel кредитный CF и доходность должны быть окончательно сверены помесячно с эталонной моделью.</div>
    </div>
  </div>
</div>

<!-- Сверка с калькулятором ГлавАПУ: полная таблица «наше / ГлавАПУ» окном.
     Открывается кнопкой из карточки на вкладке «ТЭП», само не всплывает. -->
<div id="glavapuScenarioDialog" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);
     z-index:80;align-items:center;justify-content:center;padding:20px" onclick="if(event.target===this)closeGlavapuScenario()">
  <div style="background:#fff;max-width:1200px;width:100%;max-height:88vh;overflow:auto;padding:22px 24px">
    <div style="display:flex;align-items:center;gap:14px;margin-bottom:6px">
      <h2 style="margin:0;font-size:17px">Сверка с калькулятором ГлавАПУ</h2>
      <button class="btn" style="margin-left:auto" onclick="closeGlavapuScenario()">Закрыть</button>
    </div>
    <div id="glavapuScenarioResult"></div>
  </div>
</div>

<!-- Импорт пресета: сначала показать, что произойдёт, и только потом менять
     проект. Экран проверки — не вежливость, а единственное место, где видно
     разницу между «пришло из документа» и «посчитано коэффициентом». -->
<div id="presetDialog" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);
     z-index:80;align-items:center;justify-content:center;padding:20px" onclick="if(event.target===this)closePreset()">
  <div style="background:#fff;max-width:1000px;width:100%;max-height:86vh;overflow:auto;padding:22px 24px">
    <div style="display:flex;align-items:center;gap:14px;margin-bottom:6px">
      <h2 style="margin:0;font-size:17px" id="presetTitle">Импорт пресета</h2>
      <button class="btn dark" id="presetApplyButton" onclick="applyPreset()">Применить</button>
      <button class="btn" style="margin-left:auto" onclick="closePreset()">Отмена</button>
    </div>
    <div id="presetSummary" style="font-size:12px;color:#666;margin-bottom:12px"></div>
    <div id="presetErrors" class="note warning" style="display:none"></div>
    <div id="presetBody"></div>
  </div>
</div>

<!-- Хранилище проектов: список того, что сохранили явно. -->
<div id="projectsDialog" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);
     z-index:80;align-items:center;justify-content:center;padding:20px" onclick="if(event.target===this)closeProjects()">
  <div style="background:#fff;max-width:900px;width:100%;max-height:80vh;overflow:auto;padding:22px 24px">
    <div style="display:flex;align-items:center;gap:14px;margin-bottom:12px">
      <h2 style="margin:0;font-size:17px">Личный кабинет</h2>
      <!-- Кнопки хранилища — только там, где оно есть: примеры открываются и
           без него, а «Сохранить», которое всегда откажет, хуже отсутствия.
           Смена ключа без консоли браузера: ключ меняют, когда он засветился,
           и требовать для этого localStorage.removeItem — значит не менять. -->
      <span id="projectsStorageActions" style="display:none;gap:14px;align-items:center">
        <!-- Два намерения — две кнопки. Прежде обе жили в одном «Сохранить
             текущий», и выбор между ними человек делал в окне подтверждения:
             ОК — поверх, Отмена — как новый. Кнопка с двумя смыслами не
             видна заранее, а «Отмена» читается как «ничего не делать». -->
        <button class="btn dark" id="projectsSaveOver" style="display:none"
                onclick="saveOpenedProject()">Сохранить</button>
        <button class="btn" onclick="saveProjectAsNew()">Сохранить как…</button>
        <span id="projectsOpenedName" class="muted" style="font-size:12px"></span>
        <button class="btn" onclick="changeProjectsKey()">Сменить ключ</button>
      </span>
      <button class="btn" style="margin-left:auto" onclick="closeProjects()">Закрыть</button>
    </div>
    <!-- Готовые примеры стоят рядом с сохранёнными: и то и другое — «открыть
         готовое», и искать их во «Вводных» среди разбора файлов было незачем.
         Ключа они не требуют: это витрина, а не чужие данные. -->
    <div id="projectsExamples" style="border:1px solid var(--line);padding:14px;margin-bottom:14px">
      <div class="section-title" style="margin-bottom:8px">Готовые примеры</div>
      <div class="upload-line" style="align-items:center">
        <select id="serverPresetSelect" style="min-width:240px">
          <option value="">Предустановка ТЭП…</option>
        </select>
        <button class="btn dark" onclick="loadServerPreset()">Открыть</button>
        <a id="serverPresetDownload" class="btn" href="#" style="display:none;text-decoration:none">Скачать Excel</a>
      </div>
      <div style="font-size:11px;color:#888;margin:9px 0 8px">или пресет проекта целиком — ТЭП, ВРИ, МПТ и техприсоединение разом</div>
      <div class="upload-line" style="align-items:center">
        <select id="projectPresetSelect" style="min-width:240px">
          <option value="">Пресет проекта…</option>
        </select>
        <button class="btn dark" onclick="loadServerProjectPreset()">Открыть</button>
      </div>
    </div>
    <!-- Кто вошёл и чем выйти. Прежде выход был только через консоль браузера:
         сессия лежит в localStorage, а кнопки не было (замечание владельца,
         18.08.2026). -->
    <div id="accountBox" style="display:none;border:1px solid var(--line);padding:12px 14px;margin-bottom:14px"></div>
    <!-- Тарифы, мои участки и подписка: условия и права приходят с сервера. -->
    <div id="tariffsBox" style="display:none;border:1px solid var(--line);padding:12px 14px;margin-bottom:14px"></div>
    <!-- Администрирование доступа — только администраторам (решает сервер). -->
    <div id="accessAdminBox" style="display:none;border:1px solid var(--line);padding:12px 14px;margin-bottom:14px">
      <div class="section-title" style="margin-bottom:8px">Администрирование доступа</div>
      <!-- Подписи стоят над полями, а не подсказкой внутри: подсказка исчезала
           после ввода, и по заполненной форме нельзя было понять, кому и что
           выдаётся (замечание владельца, 22.10.2026). -->
      <div class="grant-form" style="display:grid;gap:8px;max-width:640px;margin-bottom:8px">
        <label>Кому выдать доступ
          <select id="grantChat" style="width:100%"><option value="">Загружаю пользователей…</option></select>
          <small class="muted">В списке — все, кто писал боту или входил на сайт. Нет нужного человека — попросите его сначала написать боту DevelopAid.</small>
        </label>
        <label>Что выдать
          <select id="grantKind" onchange="grantKindChanged()" style="width:100%">
            <option value="plot">Доступ к участку</option>
            <option value="subscription">Подписку — все участки</option>
          </select>
        </label>
        <label id="grantCadastralRow">Кадастровые номера участка
          <input id="grantCadastral" placeholder="например, 77:09:0004001:5578, 77:09:0004001:5579" style="width:100%">
          <small class="muted">Если в расчёте несколько участков, впишите все номера через запятую: это один участок-набор, доступ откроется ко всему набору и к любой его части.</small>
        </label>
        <label>Срок доступа, дней
          <input id="grantDays" type="number" min="1" value="30" style="width:120px">
        </label>
        <label>Комментарий для журнала (необязательно)
          <input id="grantNote" placeholder="например, пилот для компании" style="width:100%">
        </label>
        <div><button class="btn dark" onclick="accessAdminGrant()">Выдать доступ</button></div>
      </div>
      <div id="accessAdminStatus" style="font-size:12px;margin-bottom:8px"></div>
      <div id="accessAdminList"></div>
      <div class="section-title" style="margin:14px 0 6px">Демо-доступ по ссылке</div>
      <div style="font-size:12px;color:#777;margin-bottom:6px">Ссылку можно отправить кому угодно: клиенту, партнёру, проверяющему ЮKassa. Она открывает кабинет без Telegram на 14 дней. По ней человек, как новый клиент, может посчитать один участок, а оплата не списывает деньги. Если отозвать ссылку, вход по ней закроется сразу.</div>
      <div class="upload-line" style="align-items:center;margin-bottom:6px">
        <input id="demoInviteNote" placeholder="Для кого, например «ЮKassa» или «ООО Ромашка»" style="min-width:220px">
        <button class="btn dark" onclick="accessDemoCreate()">Создать демо-ссылку</button>
      </div>
      <div id="demoInviteStatus" style="font-size:12px;margin-bottom:6px"></div>
      <div id="demoInviteList"></div>
    </div>
    <div id="projectsStored">
      <div class="section-title" style="margin-bottom:8px">Мои проекты</div>
      <div style="font-size:11px;color:#777;margin-bottom:10px">
        Хранится на ядре в России. Сохраняется только то, что вы сохранили сами.
      </div>
      <!-- Ссылка живёт на нашем сервере и требует, чтобы он отвечал. Файл
           настроек не требует ничего: его пересылают почтой, кладут в папку
           проекта, открывают через год. Это разные способы передачи, и один
           другого не заменяет. -->
      <!-- Скачать и загрузить — две половины одного действия, и стоять они
           обязаны рядом. Скачивание жило в шапке диалога, за экран выше
           списка, а загрузка здесь: владелец искал кнопку и не нашёл
           (23.08.2026). Подпись при этом ссылалась на кнопку «Файл», которой
           на странице давно нет. -->
      <div class="upload-line" style="align-items:center;margin-bottom:10px">
        <button class="btn" onclick="downloadCurrentSettings()">Скачать настройки текущего</button>
        <button class="btn" onclick="importSettingsFile()">Загрузить файл настроек</button>
        <input type="file" id="settingsFileInput" accept=".json,application/json" style="display:none"
               onchange="applySettingsFile(this)">
        <span style="font-size:11px;color:#888">файл .json с вводными и ТЭП — свой или присланный</span>
      </div>
      <div class="scroll"><table>
        <thead><tr><th>Проект</th><th>Выручка</th><th>Чистая прибыль</th><th>LLCR</th><th></th></tr></thead>
        <tbody id="projectsBody"></tbody>
      </table></div>
    </div>
  </div>
</div>

<div id="aiOverlay" class="ai-overlay" onclick="toggleAgent(false)"></div>
<aside id="aiDrawer" class="ai-drawer" aria-label="Платон Сергеевич Федоскин — AI-консультант DevelopAid">
  <div class="ai-head">
    <div><h2>Платон Сергеевич Федоскин</h2><p>AI-консультант DevelopAid по инвестиционной модели и проектному финансированию. Использует расчётные инструменты DevelopAid: трассировку показателей, Goal Seek, сценарные пересчёты и контроль аномалий. Режим только чтение.</p></div>
    <button class="ai-close" onclick="toggleAgent(false)" aria-label="Закрыть">×</button>
  </div>
  <div class="ai-quick">
    <button class="ai-chip" onclick="askAgentQuick('Разложи структуру расходов проекта: CAPEX, коммерческие расходы, проценты, налог и полную себестоимость. Что формирует основные затраты?','expense_structure')">Структура расходов</button>
    <button class="ai-chip" data-needs="project_finance" onclick="askAgentQuick('Почему текущий LLCR именно такой? Разложи числитель и знаменатель и назови основные причины.','llcr_breakdown')">Почему такой LLCR?</button>
    <button class="ai-chip" data-needs="project_finance" onclick="askAgentQuick('За сколько максимум можно купить проект, чтобы LLCR оставался не ниже 1,20x? Сделай подбор параметра. Если проект многоочередный — контролируй слабейшую очередь.','max_purchase_price')">Макс. цена покупки при LLCR 1,20</button>
    <button class="ai-chip" data-needs="project_finance" onclick="askAgentQuick('Какая максимальная ставка основного строительства допустима, чтобы LLCR был не ниже 1,20x? Сделай подбор параметра; для многоочередного проекта проверь слабейшую очередь.','max_construction_cost')">Себестоимость для LLCR 1,20</button>
    <button class="ai-chip" onclick="askAgentQuick('Проверь текущую модель на очевидные аномалии: ТЭП, выручка, CAPEX, маржа, очереди и финансирование. Назови только существенные отклонения.','anomalies')">Проверить аномалии</button>
    <button class="ai-chip" data-needs="project_finance" onclick="askAgentQuick('Найди слабейшую очередь. Объясни причинно, почему её LLCR ниже целевого, и сам пересчитай реальные варианты оздоровления: перенос допустимых затрат, социалки, увеличение ТЭП. Дай ранжированную рекомендацию до LLCR не ниже 1,20.','phase_recovery')">Оздоровить слабую очередь</button>
    <button class="ai-chip" data-needs="project_finance" onclick="askAgentQuick('Оцени текущую цену покупки как инвестиционное решение: какой максимальный потолок цены при LLCR 1,20, насколько текущая цена от него отличается и что делать, если продавец не снижает цену.','purchase_evaluation')">Оценить цену покупки</button>
  </div>
  <div id="aiMessages" class="ai-messages"><div id="aiHero" class="ai-hero"><img src="/assets/platon-hero.webp" alt="" width="260" height="298" loading="lazy"><div class="ai-hero-say"><b>Привет! Я Платон.</b><span>Помогу настроить отчёт и отвечу на вопросы.</span></div></div><div class="ai-msg system">Платон Сергеевич анализирует проект через расчётные инструменты DevelopAid. Цифры и подбор параметров считает движок модели, а не языковая модель.</div></div>
  <div class="ai-compose">
    <textarea id="aiInput" placeholder="Например: за сколько максимум можно купить проект, чтобы LLCR слабейшей очереди был не ниже 1,20?"></textarea>
    <div class="ai-compose-row"><small><span data-needs="project_finance">Ориентир диагностики: LLCR 1,20x. </span>Методика конкретного банка может отличаться.</small><input type="file" id="aiFile" accept=".pdf,application/pdf" style="display:none" onchange="sendAgentDocument(this.files&&this.files[0])"><button id="aiFileBtn" class="btn" onclick="document.getElementById('aiFile').click()" title="Тизер, справка по участку, решение ГЗК — Платон прочитает и покажет, что можно взять в модель">Приложить документ</button><button id="aiSendBtn" class="btn dark" onclick="sendAgentMessage()">Отправить</button></div>
  </div>
</aside>

<footer style="max-width:1540px;margin:0 auto;padding:14px 34px;font-size:11px;color:#888;display:flex;gap:18px;flex-wrap:wrap">
  <span>© ИП Ситников В.Ю.</span>
  <a href="/consent" style="color:#888">Согласие на обработку персональных данных</a>
  <a href="/privacy" style="color:#888">Политика конфиденциальности</a>
  <a href="/ads-consent" style="color:#888">Согласие на рекламные материалы</a>
  <a href="/guide" style="color:#888">Руководство</a>
  <a href="/tariffs" style="color:#888">Тарифы</a>
  <a href="/contacts" style="color:#888">Контакты</a>
  <a href="/offer" style="color:#888">Лицензионный договор</a>
  <a href="/refund" style="color:#888">Условия возврата</a>
  <span>__DEVELOPAID_PRODUCT_REGISTRATION__</span>
  <!-- Перечень нормативной базы: какая редакция учтена, на какое число она
       влияет и в каком модуле применяется. Страница была, а дойти до неё с
       калькулятора было нельзя — только из руководства или по ссылке в
       сообщении бота об изменениях. Маршрут, до которого не дойти, — это
       маршрут, которого нет; подвал общий на все поверхности, поэтому ссылка
       появляется сразу везде. -->
  <a href="/normatives" style="color:#888">Нормативная база</a>
  <!-- Анкета всплывает сама один раз; ссылка нужна тем, кто отложил её или
       захотел дописать позже — иначе второго шанса у человека нет. -->
  <a href="#" style="color:#888" onclick="openFeedback('footer');return false">Оценить DevelopAid</a>
</footer>

<!-- Анкета обратной связи. Всплывает один раз, когда человек и посчитал, и
     почитал: раньше оценивать нечего, а «при выходе» на телефоне срабатывает
     через раз и ловит уже уходящего. -->
<!-- Знакомство. Личность подтверждает Telegram, а имя, компанию и источник
     подтвердить нечем — они со слов человека, и делать вид, что проверены,
     нельзя. Спрашиваем один раз после входа (решение владельца, 18.08.2026). -->
<div id="classDialog" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);
     z-index:90;align-items:center;justify-content:center;padding:20px" onclick="if(event.target===this)closeClassDialog()">
  <div style="background:#fff;max-width:780px;width:100%;max-height:86vh;overflow:auto;padding:22px 24px;border-radius:10px">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:10px"><h2 style="margin:0;font-size:17px">Настройки классов</h2><button onclick="closeClassDialog()" style="margin-left:auto;border:1px solid #ddd;background:#fff;border-radius:6px;padding:3px 10px;cursor:pointer">✕</button></div>
    <div id="classDialogBody" style="container-type:inline-size"></div>
    <div id="classDialogNote" style="font-size:12px;margin-top:10px;color:#444"></div>
    <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap"><button onclick="applyProjectClassPreset(document.getElementById('projectClassSelect').value);renderClassDialog()" style="border:1px solid #3b6db4;background:#fff;color:#3b6db4;border-radius:6px;padding:6px 12px;cursor:pointer;font-size:12px">Вернуть базу выбранного класса</button><button onclick="fillClassesFromStats()" title="Подставляет свод модуля «Статистика» во все классы как ваши значения — по каждой статье, где свод есть" style="border:1px solid #3b6db4;background:#fff;color:#3b6db4;border-radius:6px;padding:6px 12px;cursor:pointer;font-size:12px">Вставить данные из статистики</button><button id="clearClassOwnButton" onclick="clearClassOverrides()" title="Убирает ВАШИ значения всех классов — таблица возвращается к общим базам DevelopAid" style="border:1px solid #c98a1b;background:#fff;color:#8a5a00;border-radius:6px;padding:6px 12px;cursor:pointer;font-size:12px">Убрать мои значения</button></div>
    <div id="classSourcesBody" style="margin-top:16px"></div>
  </div>
</div>
<!-- Что случилось при смене типа проекта. Переключение — разовое действие с
     большими последствиями: обнуляется жильё, соцнагрузка и плата за ВРИ, а
     метры объектов задаются уже в другом месте. Ответ на «что теперь» стоял
     плашкой ниже по странице — её надо было заметить (владелец, 21.09.2026:
     «самое разумное при выборе нежилого всплывающее окно, что такие-то
     параметры отключены, можете выбрать ТЭП в разделе экономика»). Текст
     живёт ЗДЕСЬ и только здесь: плашка под селектором зовёт это же окно,
     иначе одно и то же сказано дважды подряд и его перестают читать. -->
<!-- Подтверждение «Сформировать ТЭП по новым параметрам»: действие перезаписывает
     строки таблицы, и перед заменой человек видит, что именно изменится
     (строка, было → будет) и чем. Список составляет densityTepPlan. -->
<div id="tepConfirmDialog" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);
     z-index:91;align-items:center;justify-content:center;padding:20px" onclick="if(event.target===this)closeTepConfirm()">
  <div style="background:#fff;max-width:560px;width:100%;max-height:86vh;overflow:auto;padding:22px 24px;border-radius:10px">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:10px">
      <h2 id="tepConfirmTitle" style="margin:0;font-size:17px">Сформировать ТЭП по новым параметрам</h2>
      <button onclick="closeTepConfirm()" style="margin-left:auto;border:1px solid #ddd;background:#fff;border-radius:6px;padding:3px 10px;cursor:pointer">✕</button>
    </div>
    <div id="tepConfirmBody" style="font-size:13px;line-height:1.55"></div>
    <div style="margin-top:14px;display:flex;gap:8px;flex-wrap:wrap">
      <button class="btn dark" type="button" id="tepConfirmOk" onclick="confirmTepAction()">Сформировать</button>
      <button class="btn" type="button" onclick="closeTepConfirm()">Отмена</button>
    </div>
  </div>
</div>
<div id="projectKindDialog" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);
     z-index:91;align-items:center;justify-content:center;padding:20px" onclick="if(event.target===this)closeProjectKindDialog()">
  <div style="background:#fff;max-width:660px;width:100%;max-height:86vh;overflow:auto;padding:22px 24px;border-radius:10px">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:10px">
      <h2 id="projectKindDialogTitle" style="margin:0;font-size:17px">Нежилой проект</h2>
      <button onclick="closeProjectKindDialog()" style="margin-left:auto;border:1px solid #ddd;background:#fff;border-radius:6px;padding:3px 10px;cursor:pointer">✕</button>
    </div>
    <div id="projectKindDialogBody" style="font-size:13px;line-height:1.55"></div>
    <div style="margin-top:14px;display:flex;gap:8px;flex-wrap:wrap">
      <button class="btn" type="button" onclick="closeProjectKindDialog()">Понятно</button>
      <button type="button" onclick="cancelNonResidential()" style="border:1px solid #c98a1b;background:#fff;color:#8a5a00;border-radius:6px;padding:6px 12px;cursor:pointer;font-size:12px">Вернуть жильё</button>
    </div>
  </div>
</div>
<!-- Карта, которую крутят. Миниатюра остаётся на месте и остаётся тем, что
     уходит в бота и в печать: развёрнутая карта живёт только на экране, и
     подменять ею печатную картинку нельзя — иначе про один участок будет два
     достоверных на вид изображения. -->
<div id="landMapDialog" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);
     z-index:96;align-items:center;justify-content:center;padding:16px" onclick="if(event.target===this)closeLandMap()">
  <div style="background:#fff;max-width:1100px;width:100%;border-radius:10px;padding:14px 16px 12px">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
      <h2 id="landMapTitle" style="margin:0;font-size:16px">Участок и окружение</h2>
      <span id="landMapLayers" style="display:inline-flex;gap:4px;margin-left:12px" aria-label="Вид карты"></span>
      <button id="landMapRuler" onclick="landMapMeasureToggle()" style="margin-left:auto;border:1px solid #3b6db4;background:#fff;color:#3b6db4;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:12px">Линейка</button>
      <button onclick="landMapZoomBy(-1)" style="border:1px solid #ddd;background:#fff;border-radius:6px;padding:4px 11px;cursor:pointer">−</button>
      <button onclick="landMapZoomBy(1)" style="border:1px solid #ddd;background:#fff;border-radius:6px;padding:4px 11px;cursor:pointer">+</button>
      <button onclick="closeLandMap()" style="border:1px solid #ddd;background:#fff;border-radius:6px;padding:4px 10px;cursor:pointer">✕</button>
    </div>
    <div id="landMapStage" style="position:relative;width:100%;height:min(64vh,560px);overflow:hidden;border:1px solid #e3e3e0;border-radius:6px;background:#eeeee9;touch-action:none;cursor:grab"
         onpointerdown="landMapDown(event)" onpointermove="landMapMove(event)" onpointerup="landMapUp()" onpointercancel="landMapUp()"
         onclick="landMapClick(event)" onwheel="landMapWheel(event)"></div>
    <div id="landMapNote" style="font-size:12px;color:#555;margin-top:8px"></div>
  </div>
</div>
<div id="profileDialog" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);
     z-index:95;align-items:center;justify-content:center;padding:20px">
  <div style="background:#fff;max-width:560px;width:100%;max-height:86vh;overflow:auto;padding:22px 24px">
    <h2 style="margin:0 0 6px;font-size:17px">Знакомство</h2>
    <div style="font-size:12px;color:#666;margin-bottom:16px">
      Вход подтверждён через Telegram. Осталось назвать себя — иначе мы видим
      только номер аккаунта. Минута, и больше не спросим.
    </div>
    <label class="prof-l">Имя и фамилия<input id="profName" class="prof-i" maxlength="200" placeholder="Как к вам обращаться"></label>
    <label class="prof-l">Компания<input id="profCompany" class="prof-i" maxlength="200" placeholder="Где работаете"></label>
    <label class="prof-l">Роль <span style="color:#999">— не обязательно</span><input id="profRole" class="prof-i" maxlength="200" placeholder="Например: директор по развитию"></label>
    <label class="prof-l">Откуда узнали о нас<select id="profSource" class="prof-i"></select></label>
    <label class="prof-l">Телефон или почта <span style="color:#999">— не обязательно</span><input id="profContact" class="prof-i" maxlength="200" placeholder="Чтобы связаться, если понадобится"></label>
    <label style="display:flex;gap:8px;align-items:flex-start;font-size:12px;color:#555;margin-top:12px">
      <input type="checkbox" id="profConsent" style="margin-top:2px">
      <span>Согласен(на) на обработку персональных данных —
        <a href="/consent" target="_blank">согласие</a> и
        <a href="/privacy" target="_blank">политика</a>.</span>
    </label>
    <div id="profileStatus" style="font-size:12px;color:#777;margin-top:12px"></div>
    <div style="display:flex;gap:10px;margin-top:16px">
      <button class="btn dark" onclick="saveProfile()">Сохранить</button>
      <button class="btn" onclick="closeProfile()">Позже</button>
    </div>
  </div>
</div>

<div id="feedbackDialog" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);
     z-index:90;align-items:center;justify-content:center;padding:20px"
     onclick="if(event.target===this)closeFeedback('backdrop')">
  <div style="background:#fff;max-width:760px;width:100%;max-height:86vh;overflow:auto;padding:22px 24px">
    <h2 style="margin:0 0 6px;font-size:17px">Что скажете?</h2>
    <div style="font-size:12px;color:#666;margin-bottom:16px">
      Это рабочая версия. Нам важнее всего то, что в ней не сходится с вашей
      практикой. Одна минута, ничего обязательного.
    </div>
    <div id="feedbackBody"></div>
    <div id="feedbackStatus" style="font-size:12px;color:#777;margin-top:12px"></div>
    <div style="display:flex;gap:10px;margin-top:16px">
      <button class="btn dark" onclick="sendFeedback()">Отправить</button>
      <button class="btn" onclick="closeFeedback('later')">Позже</button>
    </div>
  </div>
</div>

<!-- Ловушка ставится ОТДЕЛЬНЫМ скриптом и ДО основного. Обработчик, объявленный
     внутри скрипта, который сам не смог разобраться, не сработает никогда: до
     него исполнение не доходит. Прежняя версия ловушки лежала в конце большого
     блока и молчала ровно в том случае, ради которого писалась (телефон
     владельца, 23.08.2026: страница мертва, причины нет). -->
<script>
function pageFailureBox(){
 var box=document.getElementById('pageFailure');
 if(!box){
  box=document.createElement('div');
  box.id='pageFailure';
  box.style.cssText='margin:12px;padding:12px 14px;border:1px solid #a33;'
   +'background:#fdeeee;color:#7a1f1f;font-size:13px;line-height:1.5;'
   +'white-space:pre-wrap;word-break:break-word';
  var host=document.body||document.documentElement;
  host.insertBefore(box, host.firstChild);
 }
 return box;
}
window.addEventListener('error', function(event){
 try{
  // Отказ РЕСУРСА — не смерть страницы. У такого события нет ни сообщения, ни
  // строки, и прежняя ловушка печатала «ошибка без описания · страница:0:0»:
  // не загрузилась картинка карты — а на экране стояло «страница не
  // доработала до конца» (владелец, 04.09.2026). Ложная тревога такого рода
  // хуже молчания: человек ищет поломку там, где всё работает.
  var target=event.target;
  var tag=(target&&target!==window&&target.tagName)?String(target.tagName).toLowerCase():'';
  if(tag){
   // У картинки карты и у тайлов есть свой onerror: страница о них позаботилась
   // и показывает это сама. Кричим только о тех, о ком не позаботился никто.
   if(typeof target.onerror==='function')return;
   var src=target.currentSrc||target.src||target.href||'';
   pageFailureBox().textContent='Не загрузился ресурс страницы: '+tag
    +(src?'\n'+src:'')+'\nСама страница работает — сломано только это.\n'
    +'Пришлите этот текст.';
   return;
  }
  var message=event.message||(event.error&&event.error.message)||'ошибка без описания';
  var where=(event.filename||'страница')+':'+(event.lineno||0)+':'+(event.colno||0);
  // «Script error.» без файла и строки — ошибка из скрипта ДРУГОГО источника:
  // браузер её содержимое не раскрывает. Наших внешних скриптов на странице
  // нет ни одного (это держит отдельная проверка), значит пришла она от
  // расширения браузера или обвязки просмотрщика — на iPhone/Safari это
  // обычное дело. Прежняя плашка звала это «страница не доработала до конца»
  // и печатала «страница:0:0»: человек искал поломку в нашем коде по адресу,
  // которого не существует (экран владельца, 21.09.2026). Сказать, что
  // страница цела, мы при этом не вправе — но ответить, докуда она дошла,
  // можем, и это измерение, а не догадка.
  if(!event.filename&&!event.lineno&&/^script error/i.test(String(message))){
   pageFailureBox().textContent='Сообщение об ошибке пришло из скрипта другого источника.\n'
    +message+'\n'
    +'Браузер не раскрывает ни файла, ни строки, а внешних скриптов на этой странице нет ни одного '
    +'— значит это расширение браузера или встроенный просмотрщик.\n'
    +(window.__developaidBooted
      ? 'Наша страница к этому моменту загрузилась целиком.'
      : 'Наша страница в этот момент ещё загружалась.')+'\n'
    +'Если что-то не работает — напишите, что именно не нажимается.';
   return;
  }
  pageFailureBox().textContent='Страница не доработала до конца.\n'
   +message+'\n'+where+'\n'
   +'Пришлите этот текст — по нему видно точное место.';
 }catch(e){}
}, true);
// Оборванная асинхронная работа не поднимала ловушку вовсе: у промиса нет
// события error, и отказ, который никто не поймал, оставался тишиной на
// экране — «страница просто стоит». Теперь он называет себя.
window.addEventListener('unhandledrejection', function(event){
 try{
  var reason=event&&event.reason;
  var message=(reason&&(reason.message||reason.detail))||String(reason||'').trim()
   ||'отказ без описания';
  pageFailureBox().textContent='Незавершённая работа страницы.\n'+message+'\n'
   +'Пришлите этот текст — по нему видно точное место.';
 }catch(e){}
});
</script>

"""

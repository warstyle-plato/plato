"""Вопрос Платону укладывается в бюджет — один раз на все поверхности.

Предел у Платона 4000 знаков, и превышение — это отказ «вопрос слишком
длинный» ровно там, где данных больше всего. Свод продаж это уже проходил:
обязательная шапка и хвост стояли вне счёта, и с одиннадцатью выводами вопрос
перевалил предел ещё до первого раздела.

В торгах то же самое повторилось своим путём: списки там обрезаны по двенадцать
строк, а общего бюджета нет вовсе — и один выбранный лот, у которого в
названии весь перечень ЗОУИТ, выносит вопрос за предел (экран владельца,
30.08.2026). Это второе место, где считают одно и то же, поэтому счёт объявлен
здесь и подставляется обеим страницам, как контур и подвал.

Правила счёта выведены на своде продаж и переносятся целиком:

- **бюджет считается на всё сообщение**, а не на его середину: преамбула и
  вопрос человека вычитаются до укладки;
- **место под строку «не поместилось» держится с начала** — приписанная сверх
  бюджета, она обрезается первой, то есть пропадает ровно то предупреждение,
  ради которого написана;
- **раздел входит построчно**, а не всё-или-ничего: иначе раздел из шести
  строк выпадает целиком, а стоящий ниже из пяти проходит;
- **длинная строка обрезается по знакам**, а не выбрасывает раздел: у лота
  торгов в названии бывает пятьсот знаков перечня ограничений;
- **всякая обрезка называет себя**: молча укороченный свод читается как полный.

Рядом живёт разговор. «Платон должен везде уметь вести диалог, а не один
ответ» (владелец, 30.08.2026): кабинет рынка, свод продаж и торги спрашивали
его с чистого листа каждый раз — уточнить сказанное было нельзя, потому что
сказанного он не помнил. История несёт РАЗГОВОР, а не данные: числа едут
свежими в самом вопросе, потому что источник мог смениться между репликами, а
движок каждую реплику истории обрезает по длине — свод, уехавший в неё
целиком, вернулся бы обрубком и выглядел бы полным.
"""

from __future__ import annotations

PLACEHOLDER = "__DEVELOPAID_PLATO_PACK__"
# Оболочка разговора. Ящик справа живёт в `PAGE` — там его вид и там его
# правят; кабинет, торги и монитор берут оттуда же, а не рисуют свой.
DRAWER_CSS_PLACEHOLDER = "__DEVELOPAID_PLATO_DRAWER_CSS__"
DRAWER_PLACEHOLDER = "__DEVELOPAID_PLATO_DRAWER__"
# Имена элементов ящика объявлены здесь же, где решается, кто их читает:
# второго списка «какой id у какого поля» не бывает.
DRAWER_IDS = {"drawer": "platoDrawer", "overlay": "platoOverlay",
              "hint": "platoHint", "chips": "platoChips", "out": "platoOut",
              "field": "platoField", "button": "platoSend"}

# Границы куска стилей в `PAGE`. Кусок берётся по СВОИМ границам, а не по
# соседней строке: сосед переписывается вместе с чужой правкой, и проверка
# тогда падает, ничего не сказав о том, что сломалось.
_CSS_START = "\n.ai-open-btn{"
_CSS_END = "@media(max-width:700px){.ai-drawer"


class MissingPiece(RuntimeError):
    """Куска оболочки в `PAGE` нет. Это поломка, а не повод нарисовать свой."""


def drawer_css(core) -> str:
    """Стили ящика — из `PAGE`, где они и живут.

    Копии нет по той же причине, по которой нет копии `VERSION`: копию негде
    обновлять, а разошедшиеся стили дали бы на трёх поверхностях три разных
    Платона, и каждый выглядел бы правильным.
    """
    page = getattr(core, "PAGE", "") or ""
    start = page.find(_CSS_START)
    at = page.find(_CSS_END)
    if start < 0 or at < 0 or at < start:
        raise MissingPiece("в PAGE не нашлись стили ящика Платона (.ai-*)")
    end = page.find("\n", at)
    return page[start:end if end > 0 else len(page)].strip()


def drawer_markup(ids: dict[str, str]) -> str:
    """Оболочка разговора: один ящик на страницу, груз — от блока.

    Общее у поверхностей — вид и поведение, а не содержимое: спрашивают о том
    отчёте, который перед глазами. Поэтому подпись и подсказки ставит блок, из
    которого ящик открыли (`platoOpen`), а не разметка: в кабинете блоков два,
    и второй ящик рядом с первым означал бы два разных Платона на одном экране.
    """
    import html as _html

    def esc(value: str) -> str:
        return _html.escape(str(value or ""), quote=True)

    return f"""<div id="{esc(ids['overlay'])}" class="ai-overlay" onclick="platoDrawer(false)"></div>
<aside id="{esc(ids['drawer'])}" class="ai-drawer" aria-label="Платон Сергеевич Федоскин — AI-консультант DevelopAid">
  <div class="ai-head">
    <div><h2>Платон Сергеевич Федоскин</h2><p id="{esc(ids['hint'])}"></p></div>
    <button class="ai-close" onclick="platoDrawer(false)" aria-label="Закрыть">×</button>
  </div>
  <div id="{esc(ids['chips'])}" class="ai-quick"></div>
  <div id="{esc(ids['out'])}" class="ai-messages"></div>
  <div class="ai-compose">
    <textarea id="{esc(ids['field'])}" placeholder="Спросите о том, что на экране"></textarea>
    <div class="ai-compose-row"><small>Числа считает движок — модель ничего не пересчитывает.</small><button id="{esc(ids['button'])}" class="btn dark" onclick="platoSend()">Спросить</button></div>
  </div>
</aside>"""


# Кнопка, которая не уезжает вверх вместе с блоком. Её стилей в `PAGE` нет и
# быть не может: на расчёте Платон стоит в шапке страницы и виден всегда, а в
# кабинете шапка одна на несколько блоков. Поэтому кнопка объявлена здесь —
# один раз на все поверхности, как и сам ящик.
LAUNCHER_PLACEHOLDER = "__DEVELOPAID_PLATO_LAUNCHER__"

LAUNCHER_CSS = """
.ai-fab{position:fixed;right:18px;bottom:18px;z-index:998;display:inline-flex;
 align-items:center;gap:8px;padding:11px 16px;border:1px solid #111;border-radius:999px;
 background:#111;color:#fff;font:inherit;font-size:13px;font-weight:600;cursor:pointer;
 box-shadow:0 10px 26px rgba(0,0,0,.22)}
.ai-fab:hover{background:#000}
.ai-fab .ai-dot{background:#7fd39a}
/* `hidden` слабее `display:inline-flex`, и без этой строки спрятанная кнопка
   остаётся на экране — в том числе поверх открытого ящика. */
.ai-fab[hidden]{display:none}
@media(max-width:700px){.ai-fab{right:12px;bottom:12px;padding:11px 13px}
 .ai-fab .ai-fab-label{display:none}}
@media print{.ai-fab{display:none !important}}
"""


def launcher_css() -> str:
    """Стили всплывающей кнопки. Ставятся рядом со стилями ящика."""
    return LAUNCHER_CSS.strip()


def floating_launcher() -> str:
    """Всплывающая кнопка: одна на страницу, груз — от блока перед глазами.

    Карточка внизу блока отвечала на «где спросить» только тому, кто дочитал до
    низа: у свода продаж это десять экранов (владелец, 06.09.2026 — «надо во
    всех блоках кабинета, чтобы Платон был не внизу, а всплывал видимо, как на
    основном расчёте модели»). Кнопка на экране ОДНА: вторая рядом означала бы
    два разных Платона, и человек не знал бы, который его слушает. О каком
    блоке спросит — написано на ней самой: молча сменившийся груз читается как
    ответ не о том.
    """
    return ('<button type="button" id="platoFab" class="ai-fab" hidden '
            'onclick="platoOpenVisible()">'
            '<span class="ai-dot ready"></span>'
            '<span class="ai-fab-label" id="platoFabLabel">Спросить Платона</span>'
            "</button>")

SCRIPT = r"""
// Разговор с Платоном — один на все поверхности. Копия этого правила была бы
// третьим местом, где решают, что помнить и сколько.
function platoThread(){
 const turns=[];
 return {
  turns: turns,
  // Движок берёт последние шесть реплик — больше слать незачем.
  history: function(){ return turns.slice(-6) },
  said: function(question, answer){
   turns.push({role:'user', content:String(question||'')});
   turns.push({role:'assistant', content:String(answer||'')});
   // Двенадцать реплик — шесть обменов: движок дальше не смотрит, а
   // растущий без конца список висит в памяти вкладки.
   while(turns.length>12) turns.shift();
  },
  // Источник сменился — разговор о прежних числах продолжать нельзя: Платон
  // помнил бы то, чего в своде уже нет.
  reset: function(){ turns.length=0 },
  rounds: function(){ return Math.floor(turns.length/2) }
 };
}

// Путь к Платону — один на все поверхности. Копий было три: кабинет, торги и
// расчёт, — и они разошлись ровно там, где это заметно человеку: кабинет
// показывает стадию и секунды, торги молчали «Платон Сергеевич думает…» до
// самого ответа. Ожидание без признака работы читается как внезапность, и
// правило это записано давно — просто жило в одной копии из трёх.
//
// Числа сюда не приходят: что положить в вопрос, решает поверхность. Общее —
// как спросить, как дождаться и как показать разговор.
async function platoAsk(message, history, onStage){
 const r=await fetch('/cabinet/ask',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({message, history: history||[]})});
 // Ответ бывает не JSON — например HTML страницы шлюза. Разбирать его вслепую
 // значит показать поломку разбора вместо причины отказа.
 const raw=await r.text();
 let d;
 try{ d=JSON.parse(raw) }
 catch(_){ throw new Error(`Платон ответил не по-русски и не по-JSON (код ${r.status}): `+raw.slice(0,200)) }
 if(!r.ok){
  // Код ответа едет вместе с ошибкой: закрытый кабинет — это «войдите», а не
  // «Платон не ответил», и назвать его своим именем может только поверхность.
  const refusal=new Error(d.detail||d.error||'Платон не ответил');
  refusal.status=r.status;
  throw refusal;
 }
 return platoAwait(d, onStage);
}

// Ожидание ответа — общее для всех, кто спрашивает из браузера. «Работа
// принята» и «пустой ответ» с виду одинаковы: и там и там текста нет, — и
// поверхность, которая ждать не умеет, показывает принятую работу как отказ
// («Платон вернул пустой ответ» в карточке КРТ, владелец 06.09.2026).
//
// Где забирать готовое, решает поверхность: кабинет ходит по номеру запуска в
// движок, карточка КРТ — в свой маршрут, потому что там ответ ещё и
// сохраняется в отчёт площадки. Ждут при этом одинаково.
async function platoAwait(d, onStage, poll){
 const ready=poll||(async id=>{
  const p=await fetch('/agent/result/'+encodeURIComponent(id));
  return p.ok?p.json():null;
 });
 // Быстрый ответ приходит тем же запросом; за долгим ходим по номеру запуска:
 // цепочка ядро → Render → OpenAI одним соединением не держится.
 let text=d.reply||d.answer||d.text||'';
 const began=Date.now();
 let stage='', label='';
 for(let i=0;!text&&d.trace_id&&i<120;i++){
  await new Promise(done=>setTimeout(done,2500));
  try{
   const s=await fetch('/agent/trace/'+encodeURIComponent(d.trace_id));
   if(s.ok){ const sd=await s.json();
    stage=sd.stage||stage; label=sd.label||label;
    if(onStage) onStage(`${label||stage||'работа принята'} · ${Math.round((Date.now()-began)/1000)} с`);
   }
  }catch(_){}
  const pd=await ready(d.trace_id);
  if(!pd) continue;
  if(pd.status==='error'){ throw new Error(pd.detail||pd.error||'Платон не справился') }
  text=pd.reply||pd.answer||pd.text||'';
 }
 if(!text){
  // «Ответ пустой» — неверный диагноз: работа могла идти и не кончиться.
  // Различить это можно только стадией, и она называется вслух.
  const waited=Math.round((Date.now()-began)/1000);
  throw new Error(d.error||(stage
   ? `Платон не ответил за ${waited} с. Последняя стадия: ${label||stage}.`
   : `Платон не ответил за ${waited} с, и работа не начиналась: стадии нет. `
     +`Маршрут модели виден в /agent/status.`));
 }
 return text;
}

// Разговор на экране: новая реплика выше прежней. Это отрисовка, и она одна —
// три копии рисовали одно и то же тремя классами.
// Экранирование пакета названо своим именем. `esc` есть почти на каждой
// поверхности, и объявить второй в общем коде значит затенить чужой — а
// разбирающему файл по объявлениям показать конец не той функции.
// Кавычка внутри /[...]/ ломает не эту строку, а всякого, кто разбирает файл
// по кавычкам, поэтому её тут нет: текстовому узлу она не опасна.
function platoEsc(value){
 return String(value==null?'':value)
  .split('&').join('&amp;').split('<').join('&lt;').split('>').join('&gt;');
}

function platoTalkHtml(talk, pending){
 const rows=[];
 for(let i=talk.turns.length-2;i>=0;i-=2){
  rows.push('<div class="ai-msg plato-answer"'
   +(i<talk.turns.length-2?' style="opacity:.75"':'')+'>'
   +'<div class="ai-said">'+platoEsc(talk.turns[i].content)+'</div>'
   +platoEsc(talk.turns[i+1].content).replace(/\n/g,'<br>')+'</div>');
 }
 return (pending?'<div class="ai-thinking">'+platoEsc(pending)+'</div>':'')+rows.join('');
}

// Какой блок сейчас спрашивает. Ящик на странице один: два ящика рядом — это
// два разных Платона на одном экране, и человек не знает, который его слушает.
let PLATO_SURFACE=null;
const PLATO_IDS={drawer:'platoDrawer', overlay:'platoOverlay', hint:'platoHint',
 chips:'platoChips', out:'platoOut', field:'platoField', button:'platoSend'};

function platoRender(pending){
 const out=document.getElementById(PLATO_IDS.out);
 if(out&&PLATO_SURFACE) out.innerHTML=platoTalkHtml(PLATO_SURFACE.talk, pending);
}

// Блок объявляет: чей разговор, что кладём в вопрос, что написано в шапке и
// какие подсказки. Числа собирает он же — пакет не считает ничего.
function platoOpen(surface){
 if(surface) PLATO_SURFACE=surface;
 if(!PLATO_SURFACE) return;
 const hint=document.getElementById(PLATO_IDS.hint);
 if(hint) hint.textContent=PLATO_SURFACE.hint||'';
 const chips=document.getElementById(PLATO_IDS.chips);
 if(chips){
  chips.innerHTML='';
  (PLATO_SURFACE.chips||[]).forEach(pair=>{
   const button=document.createElement('button');
   button.type='button'; button.className='ai-chip'; button.textContent=pair[0];
   button.onclick=()=>{
    const field=document.getElementById(PLATO_IDS.field);
    if(field) field.value=pair[1];
    platoSend();
   };
   chips.appendChild(button);
  });
 }
 platoDrawer(true);
 platoRender('');
}

async function platoSend(){
 const surface=PLATO_SURFACE;
 if(!surface) return;
 const field=document.getElementById(PLATO_IDS.field);
 const button=document.getElementById(PLATO_IDS.button);
 const out=document.getElementById(PLATO_IDS.out);
 const question=String((field&&field.value)||'').trim();
 if(!question){ if(out) out.innerHTML='<div class="ai-msg system">Напишите вопрос.</div>'; return }
 // Груз блок собирает сам и вправе отказать: «сначала соберите отчёт» — это
 // ответ, а не поломка.
 let message;
 try{ message=surface.message(question) }
 catch(e){ if(out) out.innerHTML='<div class="ai-msg system">'+String(e.message||e)+'</div>'; return }
 if(!message){ if(out) out.innerHTML='<div class="ai-msg system">Пока нечего показать Платону.</div>'; return }
 if(button) button.disabled=true;
 platoRender('Платон Сергеевич думает…');
 try{
  // История несёт РАЗГОВОР, а не данные: числа едут свежими в самом вопросе —
  // источник мог смениться между репликами.
  const text=await platoAsk(message, surface.talk.history(),
    note=>platoRender('Платон Сергеевич: '+note));
  surface.talk.said(question, text);
  if(field) field.value='';
  platoRender('');
 }catch(e){
  platoRender('');
  // Свою причину поверхность называет сама: 401 в торгах значит «войдите»,
  // а не «Платон не ответил».
  const said=surface.error?surface.error(e):((e&&e.message)||e);
  if(out) out.insertAdjacentHTML('afterbegin',
   '<div class="ai-msg system">'+String(said).replace(/[<>&]/g,'')+'</div>');
 }
 finally{ if(button) button.disabled=false }
}

// Ящик открывают и закрывают одинаково везде. Escape закрывает — иначе на
// телефоне из него не выйти, кроме как попасть в крестик.
function platoDrawer(open){
 if(typeof document==='undefined') return;
 const box=document.querySelector('.ai-drawer'), veil=document.querySelector('.ai-overlay');
 if(!box) return;
 box.classList.toggle('open',!!open);
 if(veil) veil.classList.toggle('open',!!open);
 if(open){ const field=box.querySelector('textarea'); if(field) setTimeout(()=>field.focus(),80) }
 // Кнопка прячется под открытым ящиком: висеть поверх завесы ей незачем.
 platoFabSync();
}

// Блоки, о которых есть что спросить. Карточка «Спросить Платона» стояла ВНИЗУ
// блока и находилась только тем, кто дочитал до низа; в своде продаж это десять
// экранов (владелец, 06.09.2026). Кнопка теперь висит над экраном, а блок она
// выбирает тот, что перед глазами.
const PLATO_BLOCKS=[];

// Блок объявляет себя один раз: где он на странице, чей груз и как назвать его
// на кнопке. Узел ищется КАЖДЫЙ раз по селектору, а не запоминается ссылкой:
// отчёт перерисовывается целиком, и запомненный узел остался бы от прошлого.
function platoBlock(selector, surface, title){
 if(!selector||!surface) return;
 const at=String(selector);
 const known=PLATO_BLOCKS.find(block=>block.at===at);
 if(known){ known.surface=surface; known.title=String(title||known.title||'') }
 else PLATO_BLOCKS.push({at:at, surface:surface, title:String(title||'')});
 platoFabSync();
}

// Какой блок сейчас перед глазами. Видимость меряется `getBoundingClientRect`,
// а не `offsetParent`: у всего внутри `position:fixed` он равен null, и первая
// версия такой проверки честно соврала «блоков нет». Нулевая высота — это
// «блок ещё не построен»: пустой `div` шириной во всю страницу выглядел бы
// видимым.
function platoBlockInView(){
 if(typeof document==='undefined'||!document.querySelector) return null;
 const height=(typeof window!=='undefined'&&window.innerHeight)||0;
 const middle=height/2;
 let best=null, closest=Infinity;
 PLATO_BLOCKS.forEach(block=>{
  let node=null;
  try{ node=document.querySelector(block.at) }catch(_){ node=null }
  if(!node||!node.getBoundingClientRect) return;
  const box=node.getBoundingClientRect();
  if(!(box.height>0)) return;
  const away=box.top>middle?box.top-middle:(box.bottom<middle?middle-box.bottom:0);
  if(away<closest){ closest=away; best=block }
 });
 return best;
}

// Спрашивают о том, что на экране. Груз берётся у блока в этот миг, а не у
// того, из которого спрашивали в прошлый раз.
function platoOpenVisible(){
 const block=platoBlockInView();
 if(block) platoOpen(block.surface);
}

function platoFabSync(){
 if(typeof document==='undefined'||!document.getElementById) return;
 const fab=document.getElementById('platoFab');
 if(!fab) return;
 const block=platoBlockInView();
 const open=!!(document.querySelector&&document.querySelector('.ai-drawer.open'));
 fab.hidden=!block||open;
 if(!block) return;
 const label=document.getElementById('platoFabLabel');
 // Имя блока на кнопке — часть ответа: «Спросить Платона» без него не говорит,
 // о чём будет разговор, а блоков на странице несколько.
 if(label) label.textContent='Спросить Платона'+(block.title?' '+block.title:'');
 fab.title='Разговор о том, что на экране: '+(block.title||'этот блок');
}
// Спрашивают через `typeof`, а не надеются на окружение: пакет подставляется
// на четыре поверхности и грузится в проверках голым, без DOM. Молча упавший
// на первой строке пакет не определил бы ни одной функции — ровно та поломка,
// которую уже ловили незакрытой кавычкой в `PAGE`.
if(typeof document!=='undefined'&&document.addEventListener){
 document.addEventListener('keydown',e=>{
  if(e.key==='Escape'&&document.querySelector('.ai-drawer.open')) platoDrawer(false);
 });
 // Прокрутка меняет то, что перед глазами, — значит и то, о чём спросят.
 // Считается это не на каждое событие прокрутки, а раз на кадр: иначе кнопка
 // пересчитывает подпись сотни раз в секунду на длинном своде.
 let awaiting=false;
 const soon=()=>{
  if(awaiting) return;
  awaiting=true;
  const run=()=>{ awaiting=false; platoFabSync() };
  if(typeof requestAnimationFrame==='function') requestAnimationFrame(run);
  else setTimeout(run,80);
 };
 // Прокрутка ловится и внутри блоков (`true`): у таблиц кабинета своя.
 document.addEventListener('scroll',soon,true);
 document.addEventListener('DOMContentLoaded',()=>platoFabSync());
 if(typeof window!=='undefined'&&window.addEventListener) window.addEventListener('resize',soon);
}

// Укладка вопроса Платону в бюджет. Объявлена один раз (plato_question.py) и
// подставляется на страницы: два счёта одного и того же однажды разойдутся, и
// одна поверхность будет отвечать «слишком длинный» там, где другая уложилась.
function platoPack(head, groups, options){
 const opt=options||{};
 const cap=Number(opt.limit)||2800;
 const order=opt.order||[];
 const lineCap=Number(opt.lineLimit)||300;
 const NOTE_ROOM=200;
 const cut=s=>{s=String(s==null?'':s); return s.length>lineCap?s.slice(0,lineCap-1)+'…':s};
 const rank=name=>(order.indexOf(name)+1)||99;
 const list=(groups||[]).filter(g=>g&&(g.lines||[]).length).map(
   g=>({name:g.name, lines:g.lines.map(cut)}));
 list.sort((a,b)=>rank(a.name)-rank(b.name));
 const kept=(head||[]).map(cut), dropped=[];
 let size=kept.join('\n').length;
 list.forEach(g=>{
  const room=cap-NOTE_ROOM-size;
  const fit=[];
  let used=0;
  g.lines.forEach(line=>{ if(used+line.length+1<=room){fit.push(line); used+=line.length+1} });
  if(!fit.length){ dropped.push(g.name+' ('+g.lines.length+' строк)'); return }
  if(fit.length<g.lines.length){
   const note='(вошло '+fit.length+' строк из '+g.lines.length+')';
   if(used+note.length+1<=room){ fit.push(note); used+=note.length+1 }
   dropped.push(g.name+' — часть');
  }
  kept.push(fit.join('\n'));
  size+=fit.join('\n').length+1;
 });
 if(dropped.length){
  let note='НЕ ПОМЕСТИЛОСЬ В ВОПРОС (не считай это отсутствием данных): '+dropped.join(', ')+'.';
  if(note.length>NOTE_ROOM-1) note=note.slice(0,NOTE_ROOM-3)+'….';
  kept.push(note);
 }
 let out=kept.join('\n');
 if(out.length>cap) out=out.slice(0, Math.max(0, cap-40))+'\n(свод обрезан по длине вопроса)';
 return out;
}
"""


def script() -> str:
    """JS-помощник для подстановки в страницу."""
    return SCRIPT

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
"""

from __future__ import annotations

PLACEHOLDER = "__DEVELOPAID_PLATO_PACK__"

SCRIPT = r"""
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

from pathlib import Path

p=Path('main.py')
s=p.read_text(encoding='utf-8')

old='''            "web_app": {"url": _telegram_web_app_url(chat_id, numbers, session.get("manual_tep"))},'''
new='''            "web_app": {"url": _telegram_web_app_url(
                chat_id,
                numbers,
                session.get("manual_tep"),
                session.get("calc_overrides"),
            )},'''
if old not in s:
    raise SystemExit('post-result webapp anchor not found')
s=s.replace(old,new,1)

old='''   if(window.Telegram&&window.Telegram.WebApp){
    setTimeout(()=>window.Telegram.WebApp.close(),700);
   }'''
new='''   if(window.Telegram&&window.Telegram.WebApp&&telegramResultSent){
    setTimeout(()=>window.Telegram.WebApp.close(),700);
   }'''
if old not in s:
    raise SystemExit('telegram close anchor not found')
s=s.replace(old,new,1)

p.write_text(s,encoding='utf-8')
print('FOLLOWUP_OK')

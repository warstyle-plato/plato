from pathlib import Path

p=Path('main.py')
s=p.read_text(encoding='utf-8')

init=s.find('async function initializeTelegramLaunch(){')
if init<0:
    raise SystemExit('initializeTelegramLaunch not found')
edit=s.find("if(telegramMode==='edit')",init)
if edit<0:
    raise SystemExit('edit mode branch not found')
cad=s.find('if(telegramCad){',edit)
if cad<0:
    raise SystemExit('cadastral branch not found')
block=s[edit:cad]
if 'setupTelegramEditSubmit();' not in block:
    calc=block.find('await calculate();')
    if calc<0:
        raise SystemExit('edit mode calculate call not found')
    absolute=edit+calc
    line_end=s.find('\n',absolute)
    if line_end<0:
        raise SystemExit('calculate line end not found')
    s=s[:line_end+1]+'   setupTelegramEditSubmit();\n'+s[line_end+1:]

p.write_text(s,encoding='utf-8')
print('EDIT_ROUNDTRIP_FOLLOWUP_OK')

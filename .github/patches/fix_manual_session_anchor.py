from pathlib import Path

path = Path('.github/patches/apply_telegram_tep_template_v2.py')
text = path.read_text(encoding='utf-8')
old = '''    count = text.count(old)
    if count != 1:
'''
new = '''    count = text.count(old)
    if label == "manual session region" and count == 2:
        return text.replace(old, new, 1)
    if count != 1:
'''
if text.count(old) != 1:
    raise RuntimeError('replace_once helper anchor not found exactly once')
path.write_text(text.replace(old, new, 1), encoding='utf-8')
print('Manual session anchor fixed')

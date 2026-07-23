from pathlib import Path

p = Path('main.py')
s = p.read_text(encoding='utf-8')

old = '''        "Выберите класс. После этого можно принять профиль целиком или вручную заменить "
        "четыре значения: цену жилья, коммерции, машино-места и себестоимость строительства.",'''
new = '''        "Выберите базовый профиль цен и себестоимости. После этого значения можно заменить вручную. "
        "Если в составе проекта есть офисный центр, ТЦ или наземный гараж, их цены и себестоимость "
        "DevelopAid запросит отдельным следующим шагом.",'''
if old not in s:
    raise RuntimeError('project class explanatory text not found')
s = s.replace(old, new, 1)

old_func = '''def _telegram_prompt_extra_econ(chat_id: int, dialog: dict[str, Any]) -> None:
    data = dialog.setdefault("data", {})
    specs = _telegram_extra_econ_specs(data)
    idx = int(dialog.get("extra_econ_index") or 0)
    if idx >= len(specs):
        _telegram_finalize_dialog_review(chat_id, dialog)
        return
    key, label, unit = specs[idx]
    dialog["step"] = "await_extra_econ"
    dialog["extra_econ_index"] = idx
    _telegram_dialog_save(chat_id, dialog)
    example = "2,2" if "_mln_" in key else "350"
    _telegram_send_message(
        chat_id,
        f"<b>{idx + 1} из {len(specs)} · {html.escape(label)}</b>\\n\\n"
        f"Введите значение в {unit}, например <code>{example}</code>.",
    )
'''
new_func = '''def _telegram_prompt_extra_econ(chat_id: int, dialog: dict[str, Any]) -> None:
    data = dialog.setdefault("data", {})
    specs = _telegram_extra_econ_specs(data)
    idx = int(dialog.get("extra_econ_index") or 0)
    while idx < len(specs) and data.get(specs[idx][0]) not in (None, ""):
        idx += 1
    dialog["extra_econ_index"] = idx
    if idx >= len(specs):
        _telegram_finalize_dialog_review(chat_id, dialog)
        return
    key, label, unit = specs[idx]
    dialog["step"] = "await_extra_econ"
    _telegram_dialog_save(chat_id, dialog)
    example = "2,2" if "_mln_" in key else "350"
    _telegram_send_message(
        chat_id,
        f"<b>{idx + 1} из {len(specs)} · {html.escape(label)}</b>\\n\\n"
        f"Введите значение в {unit}, например <code>{example}</code>.",
    )
'''
if old_func not in s:
    raise RuntimeError('extra econ prompt function not found')
s = s.replace(old_func, new_func, 1)

p.write_text(s, encoding='utf-8')
print('tidied v0.12.17')

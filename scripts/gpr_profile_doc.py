"""Generate/check the published estimate table from the application catalog."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from developaid_schedule_elements import ELEMENTS, SOURCE, SOURCE_URL, TITLE, ACCEPTED_ON

START, END = '<!-- gpr-profile:start -->', '<!-- gpr-profile:end -->'


def block():
    rows = [START, f'**{TITLE}.** Принят владельцем {ACCEPTED_ON}.',
            f'[{SOURCE}]({SOURCE_URL})', '', '| Элемент | Доля |', '| --- | ---: |']
    rows += [f'| {name} | {weight}% |' for _, name, weight in ELEMENTS]
    return '\n'.join([*rows, f'| **Итого** | **{sum(w for _, _, w in ELEMENTS)}%** |', END])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    path = ROOT/'docs/gpr_readiness_profiles.md'
    source = path.read_text()
    before, rest = source.split(START, 1)
    _, after = rest.split(END, 1)
    expected = before+block()+after
    if args.write:
        path.write_text(expected)
    elif source != expected:
        raise SystemExit('Таблица расходится с кодом: python scripts/gpr_profile_doc.py --write')

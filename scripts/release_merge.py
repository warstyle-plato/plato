#!/usr/bin/env python3
"""Номер выпуска выдаётся слиянием, а не веткой.

Номер отвечает на «что выпущено», а выпуск случается на main — значит номер
принадлежит main. Пока его брали в ветке заранее, брали его ВСЛЕПУЮ: сторож
сверяет с main, а соседняя сессия держит свой номер у себя, и до первого
слияния расхождения не видно ниоткуда. 21.09.2026 так столкнулись #464 и #465
на 0.24.16; второму пришлось поднимать номер трижды, и каждый подъём стоил
круга приёмки, за который main успевал уехать снова.

Здесь номер выдаётся ВНУТРИ слияния: прочитать main, записать номер в ветку,
перечитать main (не ушёл ли), слить. Окно, в которое сосед займёт тот же
номер, сжимается с часов до одного вызова API. Второй такой же прогон в это
окно не пускает `concurrency` в workflow — одной проверкой здесь этого не
добиться, потому что проверка и слияние идут разными вызовами.

Прогон вручную не нужен: это шаг workflow «Слияние с выдачей номера».

Запуск: python3 scripts/release_merge.py --pr 465 [--method squash] [--dry-run]
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "main_legacy.py"
API = "https://api.github.com"
# Сколько раз перечитывать main, если сосед занял номер между чтением и
# слиянием. Три — это не «на всякий случай»: каждый круг стоит одного вызова
# API, а не круга приёмки, и четвёртый круг означал бы, что в репозиторий
# льют быстрее, чем отвечает GitHub.
ATTEMPTS = 3
# Сразу после push номера GitHub ещё не знает, сливается ли новая голова
# (mergeable=null), и PUT merge в эту секунду получает 405. Ждём, пока он
# досчитает: до трёх минут шагами по три секунды. Минуты не хватало: после
# сдвига main GitHub пересчитывает все открытые PR разом, и 27.09 #532 и #538
# упали на входе с null через минуту ожидания.
SETTLE_POLLS = 60
SETTLE_PAUSE = 3


def _guard():
    """Счёт свободного номера живёт в стороже версий, и копии здесь нет."""
    path = ROOT / "scripts" / "check_version_grows.py"
    spec = importlib.util.spec_from_file_location("check_version_grows", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def refuse_reason(pull: dict) -> str:
    """Почему этот PR сливать нельзя. Пусто — можно.

    Причина НАЗЫВАЕТСЯ целиком: «не сливается» без имени состояния — это отказ,
    по которому идут смотреть руками, то есть тот же разбор, только позже.
    """
    if pull.get("state") != "open":
        return f"PR не открыт: state={pull.get('state')!r}."
    if pull.get("draft"):
        return "PR — черновик; черновик не сливают."
    if pull.get("merged"):
        return "PR уже слит."
    state = pull.get("mergeable_state")
    if pull.get("mergeable") is False or state == "dirty":
        return ("Конфликт с базой: влейте базовую ветку и разрешите конфликт. "
                "Номер здесь ни при чём — его выдаёт этот же прогон после.")
    if pull.get("mergeable") is None or state == "unknown":
        return ("GitHub ещё считает слияемость (mergeable=null). Это не отказ "
                "навсегда — повторите прогон через несколько секунд.")
    if state in ("blocked", "behind"):
        return (f"База не пускает слияние: mergeable_state={state!r}. "
                "Красная или недостающая проверка, либо ветка отстала.")
    return ""


def _api(method: str, path: str, token: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(f"{API}{path}", data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request) as answer:
        return json.loads(answer.read().decode("utf-8") or "{}")


def _git(*args: str, capture: bool = True) -> str:
    done = subprocess.run(["git", *args], cwd=ROOT, check=True,
                          capture_output=capture, text=True)
    return (done.stdout or "").strip()


def _write_version(guard, number: str, message: str) -> bool:
    """Поставить номер в строку VERSION и закоммитить. False — он уже стоит."""
    text = ENGINE.read_text(encoding="utf-8")
    replaced, count = guard._VERSION.subn(f'VERSION = "{number}"', text, count=1)
    if count != 1:
        raise SystemExit(f"В {ENGINE.name} не нашлась строка VERSION — номер не выдан.")
    if replaced == text:
        return False
    ENGINE.write_text(replaced, encoding="utf-8")
    _git("add", str(ENGINE.relative_to(ROOT)))
    _git("commit", "-m", message)
    return True


def _set_version(head_ref: str, number: str, base_ref: str = "main") -> str:
    """Записать номер в ветку и вернуть новую голову.

    Правится ОДНА строка объявления — та самая, что объявлена в движке один
    раз. Всё остальное содержимое ветки уже прошло приёмку, и трогать его
    здесь нечем.

    Ветка, отошедшая от прежней базы, держит в VERSION прежний номер, а база
    с тех пор свой подняла. Новый номер поверх такой ветки меняет ту же строку,
    что и база, — и GitHub видит конфликт, которого в содержании нет. Поэтому
    сначала строка ставится на номер базы, затем база вливается в ветку, и
    только потом пишется выданный номер. Конфликт вне VERSION — настоящий, его
    здесь не разрешают.
    """
    guard = _guard()
    _git("fetch", "--no-tags", "origin", head_ref, base_ref)
    _git("checkout", "-B", head_ref, f"origin/{head_ref}")
    found = guard._VERSION.search(guard._show(f"origin/{base_ref}"))
    if not found:
        raise SystemExit(f"В {ENGINE.name} базы не нашлась строка VERSION — номер не выдан.")
    _write_version(guard, found.group(1),
                   "Номер базы перед слиянием\n\nСтрока VERSION выравнивается по "
                   "базе, чтобы влить её без конфликта в номере.")
    merged = subprocess.run(["git", "merge", "--no-edit", f"origin/{base_ref}"],
                            cwd=ROOT, capture_output=True, text=True)
    if merged.returncode != 0:
        subprocess.run(["git", "merge", "--abort"], cwd=ROOT, capture_output=True)
        raise SystemExit(f"Ветка {head_ref} конфликтует с {base_ref} не только номером: "
                         "влейте базу и разрешите конфликт в ветке, затем повторите.")
    if not _write_version(guard, number,
                          f"Выпуск {number}\n\nНомер выдан слиянием: ветка его не "
                          "занимала, поэтому занять его у соседа было нечем."):
        # Номер записал прошлый прогон, которому GitHub отказал в слиянии.
        # Остановка здесь оставила бы PR с номером, но без слияния, и каждый
        # повтор падал бы на этой же строке.
        print(f"Номер {number} уже стоит в ветке — сливается её голова как есть.")
    head = _git("rev-parse", "HEAD")
    if head != _git("rev-parse", f"origin/{head_ref}"):
        _git("push", "origin", f"HEAD:{head_ref}")
    return head


def _conflict_may_be_the_number(pull: dict) -> bool:
    """Конфликт, который снимет вливание базы в `_set_version`.

    Ветка с номером от прошлого прогона конфликтует с базой в строке VERSION.
    Настоящий конфликт вне номера `_set_version` назовёт сам и не сольёт.
    """
    return (pull.get("state") == "open" and not pull.get("draft")
            and not pull.get("merged")
            and (pull.get("mergeable") is False or pull.get("mergeable_state") == "dirty"))


def _settled(pull: dict, sha: str) -> bool:
    """GitHub досчитал слияемость именно этой головы."""
    return (pull.get("head") or {}).get("sha") == sha and pull.get("mergeable") is not None


def _wait_settled(repo: str, number: str, token: str, sha: str) -> dict:
    pull: dict = {}
    for _ in range(SETTLE_POLLS):
        pull = _api("GET", f"/repos/{repo}/pulls/{number}", token)
        if _settled(pull, sha):
            break
        time.sleep(SETTLE_PAUSE)
    return pull


BUILD_WORKFLOW = "build-yandex.yml"


def _dispatch_build(repo: str, token: str, base_ref: str) -> None:
    """Запустить сборку базы после слияния.

    Слияние от GITHUB_TOKEN не рождает push-события для других workflow:
    27.09 так пять выпусков легли в main и не уехали на прод. Отказ запуска
    не отменяет слияния, но называется в логе прогона.
    """
    try:
        _api("POST", f"/repos/{repo}/actions/workflows/{BUILD_WORKFLOW}/dispatches",
             token, {"ref": base_ref})
        print(f"Сборка {BUILD_WORKFLOW} на {base_ref} запущена.")
    except urllib.error.HTTPError as error:
        print(f"Слито, но сборка {BUILD_WORKFLOW} не запустилась ({error.code}): "
              "запустите её вручную, иначе выпуск не уедет на прод.", file=sys.stderr)


def _engine_changed(guard, base_ref: str, head_ref: str) -> bool:
    """Менялся ли production-код. Имя сохранено для совместимости тестов.

    Источник правила один — check_version_grows._release_changed(). Поэтому
    market_search/**, данные и остальные runtime-файлы получают новый номер
    так же, как main_legacy.py; документация/тесты/CI номер не тратят.
    """
    return guard._release_changed(f"origin/{base_ref}", f"origin/{head_ref}")


def main() -> int:
    argv = sys.argv[1:]
    dry = "--dry-run" in argv
    argv = [arg for arg in argv if arg != "--dry-run"]
    options = dict(zip(argv[::2], argv[1::2]))
    number = options.get("--pr") or os.environ.get("PR", "")
    method = options.get("--method") or os.environ.get("METHOD") or "squash"
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
    if not number.isdigit():
        raise SystemExit("Нужен номер PR: --pr 465")
    if not repo or not token:
        raise SystemExit("Нет GITHUB_REPOSITORY или GH_TOKEN — это шаг workflow.")

    pull = _api("GET", f"/repos/{repo}/pulls/{number}", token)
    if pull.get("mergeable") is None:
        # Сдвиг main заставляет GitHub пересчитать все PR, и первый ответ
        # после любого слияния — null. Ждать, а не отказывать.
        pull = _wait_settled(repo, number, token, (pull.get("head") or {}).get("sha", ""))
    reason = refuse_reason(pull)
    if reason and pull.get("mergeable") is None and pull.get("state") == "open" \
            and not pull.get("draft") and not pull.get("merged"):
        # Недосчитанная слияемость на входе — не отказ: дальше база вливается
        # в ветку (настоящий конфликт `_set_version` назовёт сам), и перед
        # слиянием GitHub опрашивается снова уже про итоговую голову.
        print("GitHub не досчитал слияемость на входе — проверим её перед слиянием.")
        reason = ""
    if reason and not _conflict_may_be_the_number(pull):
        print(reason, file=sys.stderr)
        return 1
    head_ref = pull["head"]["ref"]
    base_ref = pull["base"]["ref"]
    guard = _guard()

    for attempt in range(1, ATTEMPTS + 1):
        _git("fetch", "--no-tags", "origin", base_ref, head_ref)
        before = guard._version(guard._show(f"origin/{base_ref}"))
        issuing = _engine_changed(guard, base_ref, head_ref)
        issued = guard._next_version(before) if issuing else ".".join(map(str, before))
        print(f"Попытка {attempt}: база {'.'.join(map(str, before))}, "
              + (f"выдаётся {issued}." if issuing
                 else "production-код не менялся — выпуска нет, номер не выдаётся."))
        if dry:
            return 0
        head_sha = (_set_version(head_ref, issued, base_ref) if issuing
                    else _git("rev-parse", f"origin/{head_ref}"))
        # Перечитать базу ПЕРЕД слиянием: между счётом и слиянием сосед мог
        # слить своё. Слить поверх ушедшей базы — это выпуск под занятым
        # номером, то есть ровно то, от чего написан этот шаг.
        _git("fetch", "--no-tags", "origin", base_ref)
        if guard._version(guard._show(f"origin/{base_ref}")) != before:
            print("База ушла, пока выдавался номер — считаем заново.")
            continue
        settled = _wait_settled(repo, number, token, head_sha)
        if not _settled(settled, head_sha):
            print(f"GitHub за {SETTLE_POLLS * SETTLE_PAUSE} с не досчитал слияемость "
                  f"головы {head_sha[:7]}. Повторите прогон: номер уже в ветке, "
                  "и повтор сольёт её как есть.", file=sys.stderr)
            return 1
        reason = refuse_reason(settled)
        if reason:
            print(reason, file=sys.stderr)
            return 1
        try:
            answer = _api("PUT", f"/repos/{repo}/pulls/{number}/merge", token,
                          {"merge_method": method, "sha": head_sha,
                           "commit_title": f"{pull['title']} (#{number})"})
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            print(f"Слияние отклонено ({error.code}): {detail}", file=sys.stderr)
            return 1
        if not answer.get("merged"):
            print(f"Слияние не состоялось: {answer.get('message')!r}", file=sys.stderr)
            return 1
        print(f"Слито под номером {issued}: {answer.get('sha')}")
        if issuing:
            _dispatch_build(repo, token, base_ref)
        return 0

    print(f"База уходила {ATTEMPTS} раза подряд — номер так и не выдан. "
          "Повторите прогон.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

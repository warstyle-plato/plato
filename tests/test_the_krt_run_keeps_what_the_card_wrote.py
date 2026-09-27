"""Прогон рейтинга КРТ не откатывает то, что за время прогона записала карточка.

Прогон брал снимок всех строк на старте и после каждой площадки писал его
целиком. Для нетронутых строк `computed_at` совпадал, и `merge_row` оставлял
снимок: оценка, которую карточка положила через `remember` пять минут назад,
молча возвращалась к старой. Второй дефект того же узла: `due()` решал
«пора ли недельный прогон» по `updated_at`, а его двигала любая запись —
открытие карточки в воскресенье после трёх часов отменяло прогон недели.
"""

from auction_search.krt_ranking import KrtRanking


def _row(slug: str, at: int) -> dict:
    return {"slug": slug, "name": slug, "available": True,
            "entry_capacity_rub_per_sqm": 100, "computed_at": at}


def _stored(ranking: KrtRanking, slug: str) -> dict:
    return ranking.stored_row(slug)


def test_a_rating_written_during_the_run_survives_it(tmp_path):
    ranking = KrtRanking(tmp_path)
    ranking._persist({"alpha": _row("alpha", 100), "beta": _row("beta", 100)})
    ranking.remember("beta", {"investment_rating": {"score": 40}})

    def screen(project):
        # Пока прогон считает alpha, человек открыл карточку beta.
        ranking.remember("beta", {"investment_rating": {"score": 77}})
        return {"available": False, "reason": "рынок не ответил"}

    ranking._run([{"slug": "alpha", "name": "alpha"}], screen)

    assert _stored(ranking, "beta")["investment_rating"] == {"score": 77}, (
        "прогон откатил оценку, записанную карточкой")


def test_the_counted_site_keeps_a_rating_written_while_it_was_counted(tmp_path):
    ranking = KrtRanking(tmp_path)
    ranking._persist({"alpha": _row("alpha", 100)})
    ranking.remember("alpha", {"investment_rating": {"score": 40}})

    def screen(project):
        ranking.remember("alpha", {"investment_rating": {"score": 77}})
        return {"available": False, "reason": "рынок не ответил"}

    ranking._run([{"slug": "alpha", "name": "alpha"}], screen)

    assert _stored(ranking, "alpha")["investment_rating"] == {"score": 77}


def test_only_the_scheduled_run_moves_the_week(tmp_path):
    ranking = KrtRanking(tmp_path)
    assert ranking.due() is True

    ranking._persist({"alpha": _row("alpha", 100)})
    ranking.remember("alpha", {"investment_rating": {"score": 40}})
    ranking.upsert_row(_row("beta", 200))
    assert ranking.due() is True, "запись карточки или пачки фона отменила недельный прогон"

    ranking._run([], lambda project: {}, catalogue_run=False)
    assert ranking.due() is True, "пачка фона сдвинула срок недельного прогона"

    ranking._run([], lambda project: {}, catalogue_run=True)
    assert ranking.due() is False

    ranking.remember("alpha", {"investment_rating": {"score": 41}})
    assert ranking.due() is False, "отметка полного прогона потерялась при записи карточки"


def test_the_scheduled_start_is_the_catalogue_run(tmp_path, monkeypatch):
    seen = []
    for scheduled in (True, False):
        ranking = KrtRanking(tmp_path)

        def fake_run(projects, screen, *, catalogue_run=False, ranking=ranking):
            seen.append(catalogue_run)
            ranking.release()

        monkeypatch.setattr(ranking, "_run", fake_run)
        assert ranking.start([], lambda project: {}, scheduled=scheduled)
        ranking._thread.join(5)
    assert seen == [True, False]


def test_a_slug_cannot_leave_the_reports_folder(tmp_path):
    import pytest

    ranking = KrtRanking(tmp_path)
    for slug in ("../../etc/passwd", "a/../../b", "decision:77-01"):
        path = ranking.report_path(slug)
        assert str(path).startswith(str(ranking.reports_dir.resolve()))
    with pytest.raises(ValueError):
        ranking.report_path("..")
    assert ranking.report("../../etc/passwd") is None

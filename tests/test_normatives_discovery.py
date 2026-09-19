from normatives_registry import find_repeal_signals


def test_amendment_marker_in_title_and_base_act_in_snippet_is_detected():
    entry = {"watch_terms": ["713/30", "774-ПП"]}
    docs = [{
        "title": "Постановление Правительства МО от 01.09.2026 N 1080-ПП "
                 "О внесении изменений в нормативы градостроительного проектирования Московской области",
        "snippet": "Изменения вносятся в нормативы, утвержденные постановлением "
                   "Правительства Московской области от 17.08.2015 N 713/30.",
        "url": "https://example.test/1080",
    }]

    signals = find_repeal_signals(entry, docs)

    assert len(signals) == 1
    assert signals[0]["kind"] == "amended"
    assert signals[0]["url"] == "https://example.test/1080"


def test_title_marker_without_base_act_anchor_is_ignored():
    entry = {"watch_terms": ["713/30"]}
    docs = [{
        "title": "О внесении изменений в другую государственную программу",
        "snippet": "Никакой ссылки на базовый градостроительный акт здесь нет.",
        "url": "https://example.test/unrelated",
    }]

    assert find_repeal_signals(entry, docs) == []


def test_same_sentence_detection_still_works():
    entry = {"watch_terms": ["713/30"]}
    docs = [{
        "title": "Обзор законодательства",
        "snippet": "В постановление N 713/30 внесены изменения новым правовым актом.",
        "url": "https://example.test/review",
    }]

    signals = find_repeal_signals(entry, docs)

    assert len(signals) == 1
    assert signals[0]["kind"] == "amended"


def test_the_snippet_form_of_an_amendment_is_detected_too():
    """«Изменения вносятся» в описании — та же поправка, что и в заголовке.

    Заголовок карточки и её описание называют одно действие разными формами:
    «О внесении изменений в…» и «Изменения вносятся в…». Прежний список знал
    только личные формы («внесены изменения»), и обе официальные проходили
    мимо. Соседний тест держит заголовочную форму; эта держит ту, что стоит
    в тексте, — иначе добавленный маркер остаётся утверждением без проверки.
    """
    entry = {"watch_terms": ["713/30"]}
    docs = [{
        "title": "Обзор законодательства Московской области",
        "snippet": "Изменения вносятся в постановление N 713/30 новым правовым актом.",
        "url": "https://example.test/snippet-form",
    }]

    signals = find_repeal_signals(entry, docs)

    assert len(signals) == 1
    assert signals[0]["kind"] == "amended"

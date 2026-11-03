from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_tep_decorator_disconnects_observer_while_mutating_dom():
    source = (ROOT / "frontend_v2" / "tep_sync.js").read_text(encoding="utf-8")

    callback = source[source.index("const observer = new MutationObserver"):]
    assert "requestAnimationFrame" in callback
    assert "observer.disconnect();" in callback
    assert "decorateTepEditor();" in callback
    assert "observer.observe(document.body" in callback
    assert callback.index("observer.disconnect();") < callback.index("decorateTepEditor();")
    assert callback.index("decorateTepEditor();") < callback.index("observer.observe(document.body")

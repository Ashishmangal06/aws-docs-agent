from backend.app.session import SessionStore


def test_add_and_retrieve():
    SessionStore.add_turn("s1", "What is S3?", "S3 is object storage.")
    history = SessionStore.get_history("s1")
    assert len(history) == 2
    assert history[0].content == "What is S3?"
    assert history[1].content == "S3 is object storage."


def test_clear():
    SessionStore.add_turn("s2", "Hello", "Hi there")
    SessionStore.clear("s2")
    assert SessionStore.get_history("s2") == []


def test_trim_history():
    for i in range(15):  # 15 turns = 30 messages, should trim to 20
        SessionStore.add_turn("s3", f"q{i}", f"a{i}")
    history = SessionStore.get_history("s3")
    assert len(history) == 20  # MAX_HISTORY_TURNS * 2
from second_brain_service.store import mail_repository


class DummyCursor:
    def __init__(self) -> None:
        self.query = ""
        self.params = ()

    def execute(self, query, params) -> None:
        self.query = query
        self.params = params

    def fetchall(self):
        return []


def test_unsuppressed_chunk_predicate():
    assert (
        mail_repository._unsuppressed_chunk_predicate("mc")
        == "COALESCE(mc.metadata->>'suppressed', 'false') <> 'true'"
    )


def test_lexical_chunk_search_filters_suppressed_chunks():
    cur = DummyCursor()

    mail_repository.lexical_chunk_search.__wrapped__(cur, "unsubscribe", 5, None)

    assert mail_repository._unsuppressed_chunk_predicate("mc") in cur.query


def test_semantic_search_filters_suppressed_chunks():
    cur = DummyCursor()

    mail_repository.semantic_search.__wrapped__(cur, [0.0], 5, None)

    assert mail_repository._unsuppressed_chunk_predicate("mc") in cur.query

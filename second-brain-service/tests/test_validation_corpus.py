from second_brain_service.search.chunking import build_chunks, prepare_message_sections
from second_brain_service.search.chunking_evaluation import evaluate_chunking_corpus
from second_brain_service.search.validation_corpus import VALIDATION_CORPUS


def test_validation_corpus_covers_required_categories():
    categories = {case.category for case in VALIDATION_CORPUS}
    assert categories == {
        "short mail",
        "long multi-topic mail",
        "reply chains",
        "forwarded threads",
        "newsletters and promotions",
    }


def test_validation_corpus_section_expectations():
    for case in VALIDATION_CORPUS:
        sections = prepare_message_sections(case.subject, case.body_text)
        assert tuple(section.section_type for section in sections) == case.expected_section_types


def test_validation_queries_match_unsuppressed_chunks():
    for case in VALIDATION_CORPUS:
        chunks = build_chunks(case.subject, case.body_text)
        visible_chunk_text = "\n".join(
            chunk.text for chunk in chunks if not chunk.metadata.get("suppressed")
        ).lower()
        for query in case.queries:
            assert query.expected_excerpt.lower() in visible_chunk_text


def test_chunking_evaluation_improves_focus_without_losing_hits():
    results = evaluate_chunking_corpus()

    assert results["section_aware"]["top1_hits"] >= results["legacy"]["top1_hits"]
    assert results["section_aware"]["avg_top_hit_tokens"] < results["legacy"]["avg_top_hit_tokens"]

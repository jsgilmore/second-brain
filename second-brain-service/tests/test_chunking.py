"""Tests for the section-aware email chunking pipeline."""

from second_brain_service.search.chunking import (
    Chunk,
    Section,
    build_chunks,
    estimate_tokens,
    prepare_message_sections,
    _build_section_chunks,
    _normalize_preserve_structure,
    _split_oversized,
)


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_single_word(self):
        result = estimate_tokens("hello")
        assert result >= 1

    def test_sentence(self):
        result = estimate_tokens("This is a short sentence.")
        assert 4 <= result <= 10

    def test_proportionality(self):
        short = estimate_tokens("one two three")
        long = estimate_tokens("one two three four five six seven eight nine ten")
        assert long > short


# ---------------------------------------------------------------------------
# Structure-preserving normalization
# ---------------------------------------------------------------------------

class TestNormalization:
    def test_preserves_paragraph_breaks(self):
        text = "First paragraph.\n\nSecond paragraph."
        result = _normalize_preserve_structure(text)
        assert "\n\n" in result
        assert "First paragraph." in result
        assert "Second paragraph." in result

    def test_preserves_blank_lines(self):
        text = "Line 1\n\nLine 2\n\nLine 3"
        result = _normalize_preserve_structure(text)
        assert result.count("\n\n") == 2

    def test_normalizes_nbsp(self):
        text = "hello\u00a0world"
        result = _normalize_preserve_structure(text)
        assert "\u00a0" not in result
        assert "hello world" in result

    def test_strips_zero_width(self):
        text = "hello\u200bworld"
        result = _normalize_preserve_structure(text)
        assert "\u200b" not in result

    def test_collapses_internal_spaces(self):
        text = "hello    world"
        result = _normalize_preserve_structure(text)
        assert "hello world" in result

    def test_empty_input(self):
        assert _normalize_preserve_structure("") == ""


# ---------------------------------------------------------------------------
# Section detection
# ---------------------------------------------------------------------------

class TestSectionDetection:
    def test_simple_body(self):
        text = "Hello, this is a simple email body."
        sections = prepare_message_sections(None, text)
        assert len(sections) == 1
        assert sections[0].section_type == "body"
        assert sections[0].source_role == "current_author"

    def test_reply_chain(self):
        text = (
            "Thanks for the update.\n\n"
            "On Mon, Jan 1, 2024, John Doe wrote:\n"
            "> Previous message content here.\n"
            "> More quoted text."
        )
        sections = prepare_message_sections(None, text)
        types = [s.section_type for s in sections]
        assert "body" in types
        assert "quote" in types

    def test_reply_with_gt_prefix(self):
        text = (
            "My reply here.\n\n"
            "> Quoted text line 1.\n"
            "> Quoted text line 2."
        )
        sections = prepare_message_sections(None, text)
        assert any(s.section_type == "quote" for s in sections)

    def test_forwarded_message(self):
        text = (
            "FYI see below.\n\n"
            "---------- Forwarded message ----------\n"
            "From: someone@example.com\n"
            "Date: Mon, Jan 1, 2024\n"
            "Subject: Test\n\n"
            "Original message content."
        )
        sections = prepare_message_sections(None, text)
        assert [section.section_type for section in sections] == ["body", "forward"]
        assert sections[1].source_role == "quoted_author"
        assert "Original message content." in sections[1].text

    def test_outlook_original_message(self):
        text = (
            "My response.\n\n"
            "-----Original Message-----\n"
            "From: sender@example.com\n"
            "Sent: Monday, January 1, 2024\n"
            "Subject: Test\n\n"
            "Original content."
        )
        sections = prepare_message_sections(None, text)
        types = [s.section_type for s in sections]
        assert "quote" in types

    def test_signature_detection(self):
        text = (
            "Thanks for the info.\n\n"
            "--\n"
            "John Doe\n"
            "Senior Engineer"
        )
        sections = prepare_message_sections(None, text)
        types = [s.section_type for s in sections]
        assert "signature" in types

    def test_footer_detection(self):
        text = (
            "Here is the article content.\n\n"
            "To unsubscribe from this mailing list, click here."
        )
        sections = prepare_message_sections(None, text)
        types = [s.section_type for s in sections]
        assert "footer" in types

    def test_empty_body(self):
        sections = prepare_message_sections(None, "")
        assert sections == []

    def test_whitespace_only(self):
        sections = prepare_message_sections(None, "   \n\n   ")
        assert len(sections) <= 1

    def test_unknown_fallback(self):
        """When the entire body is just whitespace-normalized text with no
        clear structure markers, it should produce at least one section."""
        text = "Just a plain line."
        sections = prepare_message_sections(None, text)
        assert len(sections) >= 1

    def test_section_indices_sequential(self):
        text = (
            "Body content.\n\n"
            "On Mon, Jan 1, 2024, Someone wrote:\n"
            "> Quote.\n\n"
            "--\n"
            "Sig"
        )
        sections = prepare_message_sections(None, text)
        indices = [s.section_index for s in sections]
        assert indices == list(range(len(sections)))

    def test_source_role_body_vs_quote(self):
        text = (
            "My text.\n\n"
            "> Their text."
        )
        sections = prepare_message_sections(None, text)
        body = [s for s in sections if s.section_type == "body"]
        quote = [s for s in sections if s.section_type == "quote"]
        if body:
            assert body[0].source_role == "current_author"
        if quote:
            assert quote[0].source_role == "quoted_author"


# ---------------------------------------------------------------------------
# Chunk building
# ---------------------------------------------------------------------------

class TestBuildChunks:
    def test_short_message_single_chunk(self):
        chunks = build_chunks("Test Subject", "Short body.")
        assert len(chunks) >= 1
        assert chunks[0].text.startswith("Subject: Test Subject")
        assert "Short body." in chunks[0].text

    def test_subject_only_on_first_chunk(self):
        long_body = "Paragraph one. " * 200 + "\n\n" + "Paragraph two. " * 200
        chunks = build_chunks("My Subject", long_body)
        assert chunks[0].text.startswith("Subject: My Subject")
        for chunk in chunks[1:]:
            assert not chunk.text.startswith("Subject:")

    def test_no_subject(self):
        chunks = build_chunks(None, "Body text here.")
        assert len(chunks) >= 1
        assert not chunks[0].text.startswith("Subject:")

    def test_deterministic(self):
        text = "Hello there.\n\nSecond paragraph.\n\n> Quoted reply."
        chunks_a = build_chunks("Sub", text)
        chunks_b = build_chunks("Sub", text)
        assert len(chunks_a) == len(chunks_b)
        for a, b in zip(chunks_a, chunks_b):
            assert a.text == b.text
            assert a.metadata == b.metadata

    def test_chunk_indices_sequential(self):
        text = "Para 1.\n\n> Quote.\n\n--\nSig"
        chunks = build_chunks(None, text)
        indices = [c.chunk_index for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_prev_next_linkage(self):
        text = "First.\n\n> Second.\n\n--\nThird"
        chunks = build_chunks(None, text)
        if len(chunks) >= 2:
            assert chunks[0].metadata["prev_chunk_index"] is None
            assert chunks[0].metadata["next_chunk_index"] == 1
            assert chunks[-1].metadata["next_chunk_index"] is None
            assert chunks[-1].metadata["prev_chunk_index"] == len(chunks) - 2

    def test_suppressed_sections(self):
        text = (
            "Main content here.\n\n"
            "--\n"
            "John Doe\n"
            "Acme Corp"
        )
        chunks = build_chunks(None, text)
        sig_chunks = [c for c in chunks if c.metadata.get("section_type") == "signature"]
        body_chunks = [c for c in chunks if c.metadata.get("section_type") == "body"]
        if sig_chunks:
            assert sig_chunks[0].metadata["suppressed"] is True
        if body_chunks:
            assert body_chunks[0].metadata["suppressed"] is False

    def test_quote_flag(self):
        text = "Reply.\n\n> Quoted content."
        chunks = build_chunks(None, text)
        quote_chunks = [c for c in chunks if c.metadata.get("is_quote")]
        body_chunks = [c for c in chunks if not c.metadata.get("is_quote")]
        assert len(quote_chunks) >= 1
        assert len(body_chunks) >= 1

    def test_forwarded_content_stays_forward(self):
        text = (
            "FYI see below.\n\n"
            "---------- Forwarded message ----------\n"
            "From: someone@example.com\n"
            "Date: Mon, Jan 1, 2024\n"
            "Subject: Test\n\n"
            "Original message content."
        )
        chunks = build_chunks(None, text)
        assert [chunk.metadata["section_type"] for chunk in chunks] == ["body", "forward"]
        assert chunks[1].metadata["is_quote"] is True
        assert "Original message content." in chunks[1].text

    def test_metadata_keys_present(self):
        chunks = build_chunks("Sub", "Body text.")
        required_keys = {
            "section_type", "section_index", "position_start", "position_end",
            "source_role", "is_quote", "suppressed", "prev_chunk_index",
            "next_chunk_index",
        }
        for chunk in chunks:
            assert required_keys.issubset(chunk.metadata.keys()), (
                f"Missing keys: {required_keys - chunk.metadata.keys()}"
            )

    def test_empty_body(self):
        chunks = build_chunks("Sub", "")
        assert chunks == []


# ---------------------------------------------------------------------------
# Token-aware splitting
# ---------------------------------------------------------------------------

class TestTokenAwareSplitting:
    def test_within_limit(self):
        text = "Short text."
        result = _split_oversized(text, max_tokens=100)
        assert result == [text]

    def test_splits_long_text(self):
        # Build a text that exceeds 50 tokens
        text = "This is a sentence. " * 50
        result = _split_oversized(text, max_tokens=50)
        assert len(result) > 1
        for piece in result:
            assert estimate_tokens(piece) <= 50

    def test_section_chunks_respect_max(self):
        long_text = "A moderately long sentence with several words in it. " * 100
        section = Section(
            section_index=0,
            section_type="body",
            text=long_text,
            source_role="current_author",
        )
        chunk_texts = _build_section_chunks(
            section, target_tokens=64, max_tokens=128, overlap_tokens=0,
        )
        for ct in chunk_texts:
            assert estimate_tokens(ct) <= 128, (
                f"Chunk exceeds max_tokens: {estimate_tokens(ct)} tokens"
            )


# ---------------------------------------------------------------------------
# Multi-topic and newsletter-style emails
# ---------------------------------------------------------------------------

class TestMultiTopicEmails:
    def test_multiple_paragraphs_create_multiple_chunks(self):
        paragraphs = []
        for i in range(5):
            paragraphs.append(f"Topic {i}: " + "This is detailed content. " * 30)
        body = "\n\n".join(paragraphs)
        chunks = build_chunks("Newsletter", body, target_tokens=64, max_tokens=128)
        assert len(chunks) > 1

    def test_reply_chain_separated(self):
        text = (
            "Thanks for the detailed analysis.\n\n"
            "I agree with your points about the budget.\n\n"
            "On Tue, Mar 5, 2024, Alice wrote:\n"
            "> Here is my analysis of the Q1 budget.\n"
            "> We are 15% over target in marketing.\n"
            "> Engineering is on track.\n\n"
            "> On Mon, Mar 4, 2024, Bob wrote:\n"
            ">> What's the status of Q1?\n"
            ">> Can you send a summary?"
        )
        chunks = build_chunks(None, text)
        section_types = {c.metadata["section_type"] for c in chunks}
        assert "body" in section_types
        assert "quote" in section_types

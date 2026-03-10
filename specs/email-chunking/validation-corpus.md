# Email Chunking Validation Corpus

This validation corpus is synthetic and safe to commit. It exists to exercise the chunking pipeline on the main message shapes called out in the requirements and design.

Source of truth:

- `second-brain-service/src/second_brain_service/search/validation_corpus.py`

Corpus coverage:

1. `short-personal-email`
   - Category: short mail
   - Query focus: concrete scheduling detail in a single authored message
2. `long-multi-topic-work-email`
   - Category: long multi-topic mail
   - Query focus: one topic should match without dragging unrelated planning sections into the same chunk
3. `reply-chain`
   - Category: reply chains
   - Query focus: current authored content should stay separate from quoted history
4. `forwarded-thread`
   - Category: forwarded threads
   - Query focus: forwarded content should remain classified as forwarded/quoted context
5. `newsletter-promotion`
   - Category: newsletters and promotions
   - Query focus: substantive article content should be retrievable while signature/footer content is suppressed

The corpus is used by:

- automated tests in `second-brain-service/tests/test_validation_corpus.py`
- the evaluation command `make evaluate-chunking`

Success criteria for this corpus:

- every case maps to the expected section sequence
- every representative query has a matching unsuppressed section-aware chunk
- the evaluation report can compare legacy chunking against the new section-aware chunker on a stable input set

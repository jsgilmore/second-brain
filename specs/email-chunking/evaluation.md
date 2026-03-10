# Email Chunking Evaluation

Generated from:

- `PYTHONPATH=./second-brain-service/src ./.venv/bin/python -m second_brain_service.cli evaluate-chunking`
- Generated at: `2026-03-10T22:01:26.289346+00:00`

Corpus:

- 5 synthetic messages
- 7 representative queries

## Summary

| metric | legacy chunking | section-aware chunking |
| --- | ---: | ---: |
| top-1 query hits | 7 | 7 |
| top-1 hit rate | 1.00 | 1.00 |
| avg chunks per message | 1.00 | 1.80 |
| avg top-hit chunk tokens | 60.29 | 48.14 |
| suppressed chunks in section-aware corpus | n/a | 2 |

## Query Results

| case | query | legacy hit | section-aware hit | legacy tokens | section-aware tokens |
| --- | --- | ---: | ---: | ---: | ---: |
| short-personal-email | Green Market cafe travel forms | yes | yes | 32 | 32 |
| long-multi-topic-work-email | vendor contracts runway model | yes | yes | 65 | 65 |
| long-multi-topic-work-email | onboarding checklist April cohort | yes | yes | 65 | 65 |
| reply-chain | rollback window Friday support one hour before deploy | yes | yes | 68 | 28 |
| forwarded-thread | Okta audience mismatch staging tenant | yes | yes | 70 | 57 |
| newsletter-promotion | rate limit 500 requests verified workspaces | yes | yes | 61 | 45 |
| newsletter-promotion | webhook retries migration guide | yes | yes | 61 | 45 |

## Interpretation

- The synthetic corpus covers short mail, long multi-topic mail, reply chains, forwarded threads, and newsletter-style mail.
- Both chunkers still find the relevant evidence on these representative queries, but the section-aware chunker returns smaller and more focused chunks.
- On this corpus, the section-aware chunker preserves top-1 query hit rate while reducing average top-hit chunk size by about 20%.
- The section-aware pipeline also suppresses signature/footer chunks, reducing retrieval pressure from low-value content.

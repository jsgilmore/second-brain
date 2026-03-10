from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationQuery:
    query: str
    expected_excerpt: str


@dataclass(frozen=True)
class ValidationCase:
    case_id: str
    category: str
    subject: str | None
    body_text: str
    expected_section_types: tuple[str, ...]
    queries: tuple[ValidationQuery, ...]


VALIDATION_CORPUS: tuple[ValidationCase, ...] = (
    ValidationCase(
        case_id="short-personal-email",
        category="short mail",
        subject="Lunch tomorrow",
        body_text=(
            "Hey Sam,\n\n"
            "Can we meet at the Green Market cafe at 12:30 tomorrow to go over the travel forms?\n\n"
            "Thanks,\n"
            "Alex"
        ),
        expected_section_types=("body",),
        queries=(
            ValidationQuery(
                query="Green Market cafe travel forms",
                expected_excerpt="Green Market cafe at 12:30 tomorrow",
            ),
        ),
    ),
    ValidationCase(
        case_id="long-multi-topic-work-email",
        category="long multi-topic mail",
        subject="Q2 planning notes",
        body_text=(
            "Budget update:\n"
            "We are freezing vendor contracts until finance signs off on the revised runway model.\n\n"
            "Customer onboarding:\n"
            "The support team needs a refreshed onboarding checklist before the April cohort starts.\n\n"
            "Hiring:\n"
            "We should pause the staff engineer interview loop until after the planning offsite."
        ),
        expected_section_types=("body",),
        queries=(
            ValidationQuery(
                query="vendor contracts runway model",
                expected_excerpt="freezing vendor contracts until finance signs off",
            ),
            ValidationQuery(
                query="onboarding checklist April cohort",
                expected_excerpt="refreshed onboarding checklist before the April cohort starts",
            ),
        ),
    ),
    ValidationCase(
        case_id="reply-chain",
        category="reply chains",
        subject="Release rollback plan",
        body_text=(
            "Let's keep the rollback window on Friday at 16:00 and notify support one hour before the deploy.\n\n"
            "On Tue, Mar 5, 2024, Priya wrote:\n"
            "> I think Thursday is safer because support coverage is thinner on Friday.\n"
            "> We should also confirm the customer status page copy."
        ),
        expected_section_types=("body", "quote"),
        queries=(
            ValidationQuery(
                query="rollback window Friday support one hour before deploy",
                expected_excerpt="rollback window on Friday at 16:00",
            ),
        ),
    ),
    ValidationCase(
        case_id="forwarded-thread",
        category="forwarded threads",
        subject="Fwd: Identity launch blocker",
        body_text=(
            "Forwarding the note from infrastructure.\n\n"
            "---------- Forwarded message ----------\n"
            "From: Infra Ops <infra@example.com>\n"
            "Date: Tue, Mar 5, 2024\n"
            "Subject: Identity launch blocker\n\n"
            "The SSO launch is blocked by an Okta audience mismatch in the staging tenant.\n"
            "We can clear it by rotating the service provider metadata before Thursday."
        ),
        expected_section_types=("body", "forward"),
        queries=(
            ValidationQuery(
                query="Okta audience mismatch staging tenant",
                expected_excerpt="SSO launch is blocked by an Okta audience mismatch",
            ),
        ),
    ),
    ValidationCase(
        case_id="newsletter-promotion",
        category="newsletters and promotions",
        subject="Platform weekly digest",
        body_text=(
            "API changes:\n"
            "The public API rate limit is increasing to 500 requests per minute for verified workspaces.\n\n"
            "Docs update:\n"
            "The migration guide now includes a complete example for webhook retries.\n\n"
            "--\n"
            "Platform Weekly\n\n"
            "To unsubscribe from these updates, manage your preferences here."
        ),
        expected_section_types=("body", "signature", "footer"),
        queries=(
            ValidationQuery(
                query="rate limit 500 requests verified workspaces",
                expected_excerpt="rate limit is increasing to 500 requests per minute",
            ),
            ValidationQuery(
                query="webhook retries migration guide",
                expected_excerpt="migration guide now includes a complete example",
            ),
        ),
    ),
)

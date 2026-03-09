# Security Policy

## Supported Scope

This project handles private Gmail data, OAuth credentials, and remote access surfaces. Treat security issues as high priority.

## Reporting

Please do not open a public issue for vulnerabilities that could expose mailbox data, credentials, or unauthorized remote access.

Instead, report security issues privately to the project maintainer through a private channel you already trust for this project.

## What To Include

- A clear description of the issue
- Affected files, commands, or endpoints
- Reproduction steps if safe to share
- Impact assessment
- Suggested mitigations if available

## Secrets And Sensitive Data

Do not include:

- OAuth client files
- OAuth tokens
- `.env` contents
- Authorization headers
- Raw private email content unless strictly necessary

Redact sensitive values before sharing logs or screenshots.

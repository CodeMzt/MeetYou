# Security Policy

## Supported Versions

MeetYou is under active V4 development. Security fixes target the `main` branch unless a maintainer explicitly publishes a release branch.

## Reporting A Vulnerability

Do not open a public issue with vulnerability details, tokens, cookies, credentials, private chat IDs, internal hostnames, or exploit steps.

Preferred path:

1. Use GitHub private vulnerability reporting if it is enabled for the repository.
2. If private reporting is not available, open a minimal public issue asking for a security contact without including sensitive details.

Please include:

- Affected component or boundary.
- Impact and expected attacker capability.
- Minimal reproduction steps with placeholders instead of secrets.
- Whether credentials, local files, chat channels, or endpoint providers are involved.

## Secret Handling

- Real secrets belong in `.env` or ignored `user/*.json` files.
- Public examples must use placeholders.
- Danxi email, password, WebVPN cookies, provider tokens, and bot credentials must not appear in logs, errors, snapshots, tests, screenshots, or documentation examples.
- If a secret is accidentally committed, rotate it immediately and remove it from Git history before publishing a public repository.

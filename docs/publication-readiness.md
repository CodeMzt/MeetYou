# Publication Readiness Checklist

This checklist records the public-repository hygiene expected before publishing MeetYou.

## Repository Metadata

- License: MIT, tracked in `LICENSE`.
- Primary README: English `README.md`.
- Chinese README: `README.zh-CN.md`.
- Community files: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `SUPPORT.md`, issue templates, and PR template.
- Frontend package metadata: `license=MIT`, `author=MeetYou Contributors`, and `private=true` to prevent accidental npm publishing.

## Privacy And Secret Hygiene

Expected public state:

- No real `.env`, `.env.*`, `user/*.json`, logs, local databases, packaged binaries, or build outputs tracked by Git.
- No committed private keys, cloud access keys, OpenAI-style API keys, GitHub tokens, Google API keys, JWT-like bearer tokens, or database URLs with real passwords.
- Public examples use placeholders.
- Test database URLs may use local-only dummy credentials such as `postgres:postgres@127.0.0.1`.
- Public docs should not include personal local usernames, personal filesystem roots, private hostnames, real chat IDs, or human screenshots.

Useful local checks:

```powershell
git -c core.quotepath=false ls-files | Select-String -Pattern '(^|/)(\.env|logs|release|dist|build|\.venv|__pycache__|node_modules|user/.*(?<!\.example)\.json$|.*\.db$|.*\.sqlite|.*\.pem|.*\.key)$'

git -c core.quotepath=false grep -n -E "AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{32,}|gh[pousr]_[A-Za-z0-9_]{30,}|AIza[0-9A-Za-z_-]{30,}|-----BEGIN (RSA |OPENSSH |EC |DSA |PRIVATE )?PRIVATE KEY-----" -- .

git -c core.quotepath=false grep -n -E "C:\\Users\\|<repo-root>|private-host.example|oc_[A-Za-z0-9]+" -- .
```

Review any match manually. A pattern match is not automatically a leak; examples and tests may intentionally contain placeholders.

## Community Norms

- Use issues for reproducible bugs and feature proposals.
- Use private vulnerability reporting where available; do not publish exploit details or credentials.
- Keep PRs scoped and include verification.
- Preserve V4 architecture boundaries from `AGENTS.md`.
- Update docs when protocol, startup, configuration, or validation behavior changes.

## Publish Gate

Before publishing a public release:

- Run backend tests relevant to the changed surface.
- Run frontend typecheck, tests, and `npm run build:ui` when frontend files change.
- Run the Windows desktop installer build (`npm run build`) before publishing desktop release assets.
- Run a real browser or Electron visual check for UI behavior changes.
- Confirm `git status --short` has no local-only runtime files.
- Confirm GitHub CI passes on `main`.
- Confirm deployment only runs after successful CI or explicit manual dispatch.

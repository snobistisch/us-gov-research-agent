# Security Policy

## API-key safety

- Put keys only in a local `.env` file or your deployment platform's secret store.
- Never paste real keys into source, tests, notebooks, issue reports, command output, or screenshots.
- Do not commit `.env`; it is ignored from the repository's first commit.
- Use a separate, least-privilege key for this project and rotate it periodically.
- Install the repository's Gitleaks pre-commit hook before contributing.

If a key is exposed, revoke or rotate it at the provider immediately. Removing it in a later commit is not sufficient because it remains in git history. Rewrite the affected history, force-push the cleaned refs, and ask every collaborator to discard old clones.

## Reporting a vulnerability or leaked key

Do not open a public issue containing a credential or exploitable detail. Use GitHub's private vulnerability-reporting feature for this repository. If that feature is unavailable, contact the repository owner privately through their GitHub profile.

Include the affected component, impact, reproduction steps, and whether a credential has already been revoked. Never include the credential itself.

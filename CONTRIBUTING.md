# Contributing to OpenOcto

**Welcome aboard, sailor!**

Captain Octo and his crew are building a free voice assistant — independent from corporate clouds and big tech surveillance. Every contribution, whether it's a bug fix, a new feature, or a docs improvement, makes the ship stronger. Grab a cutlass and join the fight for privacy and freedom!

## Maintainer

**Dmitry Kudryavtsev** Rman ([@Dmitry-rman](https://github.com/Dmitry-rman)) — creator and lead maintainer

All PRs are reviewed by the maintainer. Response time: usually within a few days.

## How to Contribute

**Bug fixes and small improvements** — open a PR directly.

**New features or architectural changes** — please open a GitHub Issue or Discussion first. This saves everyone's time by aligning on the approach before you write code.

**What we're NOT looking for right now:**
- Refactor-only PRs (unless discussed and agreed upon)
- Dependency bumps without a clear reason

## Before Your PR

1. **Fork** the repo and create a feature branch from `main`
2. **Test locally**: `source .venv/bin/activate && pytest`
3. Keep PRs focused — one feature or fix per PR
4. Describe **what** you changed and **why** in the PR description
5. Follow existing code style (PEP 8, type hints, async where possible)

## AI-Assisted Contributions

PRs written with AI tools (Claude, Copilot, ChatGPT, etc.) are welcome! Just:
- Mark them as AI-assisted in the PR description
- Make sure you understand and can explain every change
- Test thoroughly — AI can generate plausible but broken code

## Current Focus

Areas where contributions are most valuable right now:

- **Persona system** — new personas (Hestia, Metis, Nestor, Sofia, Argus) with unique voices and prompts
- **Skill system** — skill SDK and first built-in skills (timers, weather, notes)
- **Wake word** — training and improving custom wake word models
- **Localization** — Russian language support, multilingual TTS voices
- **Testing** — expanding test coverage, especially integration tests

## Contributor License Agreement

By submitting a pull request, you agree that:

1. Your contribution is your original work
2. You grant the OpenOcto project the right to use, modify, and distribute your contribution under the project's BSL 1.1 license and any future license chosen by the project maintainer
3. You grant the project maintainer the right to relicense your contribution (including for commercial licensing)
4. This grant is irrevocable

This is a standard CLA used by many open-source projects to ensure consistent licensing.

## Security

Found a vulnerability? Please **do not** open a public issue. Email info@openocto.dev with:
- Description and severity
- Steps to reproduce
- Suggested fix (if you have one)

## Questions?

- GitHub Issues: [openocto-dev/openocto](https://github.com/openocto-dev/openocto/issues)
- Email: info@openocto.dev
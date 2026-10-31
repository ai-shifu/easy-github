# Contributing

[English](CONTRIBUTING.md) | [简体中文](CONTRIBUTING.zh-CN.md)

Start with an issue describing the problem or proposed improvement. Work on a separate branch, complete the relevant verification, and open a ready, non-draft PR. Do not push directly to `main` or proactively merge into it.

## Language conventions

Use your preferred language when asking questions, discussing changes, or working with an AI tool. English is the default for PR titles, PR descriptions, and documentation so that contributors across languages can review the work.

English documentation is the maintenance baseline. Simplified Chinese translations are provided in `README.zh-CN.md`, `CONTRIBUTING.zh-CN.md`, `docs/zh-CN/`, and `skills/easy-github/references/zh-CN/`. Keep the language-switch links and relative links working. When changing behavior or instructions, update both languages and preserve the same limits, verification requirements, and factual distinctions in each version.

Additional translations are welcome. Follow the existing locale naming and directory layout, link each translation to its English source, and add translated Skill references to the explicit file list in `scripts/package_skill.py`. Keep a single top-level `SKILL.md` entrypoint so installing another translation does not create a competing Skill. Commands, IDs, JSON fields, and status values keep their original spelling; explain their meaning in the reader's language.

## Source changes and verification

Runtime sources live in `prototype/`. The Skill's `scripts/` directory contains generated copies. After changing runtime sources or Skill contents, rebuild the package instead of maintaining two implementations:

```bash
python3 scripts/package_skill.py
python3 -m unittest discover -s tests -v
```

Tests use temporary Git repositories and simulated transports; they do not require GitHub credentials or model services. For integration checks with real tools or GitHub, explicitly select a test repository and retain the exact versions and evidence of actual execution. Do not describe simulations as human reviews or real execution by an external AI tool.

Keep `LICENSE` and the Skill's bundled license identical. Do not commit credentials, personal runtime logs, or work-state directories. New capabilities should have checks of actual behavior, especially exact-version binding, rejection of stale candidates, and preservation of original workspaces.

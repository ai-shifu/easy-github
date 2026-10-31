# Repository instructions

Never proactively merge code into main. Use a task branch and a ready, non-draft pull request.

Runtime sources are maintained in prototype/. The scripts under skills/easy-github/scripts/ are generated copies: run python3 scripts/package_skill.py after source or Skill changes. Keep the root LICENSE and bundled Skill LICENSE identical.

Keep business code generation in external coding tools. Do not weaken the GitHub adapter's current test-repository or exact-version checks while preparing docs or packaging. Do not commit credentials, runtime state, or personal run evidence.

English is the maintained source for default documentation, Skill instructions, and UI metadata. Keep Simplified Chinese translations and language-switch links in sync when changing user-facing behavior. The Skill should converse in the user's language and preserve machine identifiers and user content. Bundle translated Skill references as well as English ones.

Run relevant tests with python3 -m unittest discover -s tests -v. Local fixture operations are simulations; do not describe them as real multi-user approval or real external AI execution.

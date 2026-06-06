# External Patterns

Use these patterns as packaging and workflow guidance only. They are not runtime dependencies.

- Keep `SKILL.md` short and procedural; put detailed protocols in `references/`.
- Put repeatable fragile operations in deterministic scripts.
- Put generated output examples and boilerplate in `assets/templates/`.
- Keep the first version file-first and inspectable before adding optional integrations.
- Make provenance and update logs visible so future agents can recover context from files, not chat history.

For this skill, external services, embeddings, vector search, crawlers, and domain adapters are future optional contracts. They must not become hidden assumptions in the core workflow.

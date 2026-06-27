# tasktool-timeline

Standalone visual work-history timeline generator + live server for tasktool/superstar projects.

## Planning & implementation discipline

This project uses the superstar skill set. Follow these skills for non-trivial work:

- **brainstorming** — before any creative/feature work, to explore intent and requirements.
- **writing-plans** — turn a spec into a step-by-step implementation plan under `docs/plans/`.
- **subagent-driven-development** / **executing-plans** — execute plans with review checkpoints.
- **external-review** — gate specs, plans, and completed slices/phases through the third-party reviewer.
- **tasklist-discipline** — all work items live in `docs/tasklist.json`; mutate it only via the `tasktool` CLI from the authoritative `master` checkout.

Project docs layout: `docs/specs/`, `docs/plans/`, `docs/handoffs/`, `docs/reviewer/` (review chains), `docs/archived-tasks/`.

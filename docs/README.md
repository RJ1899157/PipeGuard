# Documentation

PipeGuard documentation describes product scope, proposed architecture, local development, and delivery criteria. Proposed behavior is explicitly distinguished from implemented functionality.

## Start here

| Document | Purpose |
| --- | --- |
| [Project overview](../README.md) | Product problem, planned capabilities, technology plan, and current status |
| [Architecture overview](architecture/overview.md) | Service boundaries, data ownership, metadata flow, and deployment scope |
| [Domain model](architecture/domain-model.md) | Entity identity, relationships, event handling, and persistence invariants |
| [Development setup](development/setup.md) | Repository access, Python environment, dependencies, and verification status |
| [Delivery roadmap](roadmap.md) | Thirteen delivery stages with outputs and acceptance criteria |
| [Project guidance](../AGENTS.md) | Working conventions and required GitHub identity |

## Documentation conventions

- Label design proposals and planned functionality clearly.
- Update setup instructions when commands, dependencies, or service requirements change.
- Record significant architecture decisions and tradeoffs alongside their affected design.
- Add API contracts, migration instructions, operating procedures, and incident runbooks when those systems exist.
- Keep examples synthetic and secret-free. Avoid credentials, private payloads, and machine-specific data in shared examples.
- Keep personal lessons, exercises, course recommendations, and individual progress outside the repository.

## Implemented contracts

- [Execution events v1](contracts/execution-events.md): validation, replay, reconciliation and local command.
- [Execution JSON Schema](contracts/execution-event-v1.schema.json): machine-readable field contract.

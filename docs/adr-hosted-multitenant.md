# ADR: Hosted organisation based multi tenant tier

**Status:** accepted for exploration; this ADR records the approved direction, not deployment approval.  
**Scope:** plan 27 stage 2 foundation. The current application remains local, single user, loopback only.  
**Decision date:** 2026-10-20

## Context

The local application stores projects as folders and keeps durable jobs and the generation library in SQLite. A future hosted tier needs shared workspaces, identity, tenant isolation, spend controls and durable background work. A hosted product would change the security boundary and requires separate operational and security work. This slice adds pure policy models, a request context, a store interface seam and tenant scoped secret references; it adds no accounts, listener, billing, cloud deployment or network access.

## Decision

### Tenant and identity model

Use **Organisation → Workspace → Project**. An organisation is the security and billing tenant. Workspaces group members and projects. Projects remain the portable unit and initially correspond to today's project folders. Each durable row carries `tenant_id`; the request context also carries an actor id and role. Local mode uses tenant `local` and actor `local` by default.

Hosted sign in will use an identity provider, with OIDC as the initial integration and SAML as an organisation option. SCIM provisioning is a later option. Organisation roles are owner, admin, billing and member. Workspace roles are editor, reviewer and viewer. Agents may prepare and propose work but cannot approve spending. The local role and policy helpers are groundwork only; they do not authenticate callers or enforce a hosted session.

### Data and isolation

Use PostgreSQL for hosted durable rows, with **Row Level Security (RLS)** policies keyed by tenant context. Application queries must also filter by tenant as defense in depth. Workers must establish tenant and actor context for each job and must not reuse a context across jobs. SQLite remains the local default.

Store project media in S3 compatible object storage under tenant scoped prefixes. Issue short lived signed URLs only after authorization. Encrypt provider credentials separately per organisation using KMS envelope encryption. Secrets must not be shared across tenants. Add tenant aware audit records for membership, key, project, approval, policy and data lifecycle changes.

### Spending and billing

An organisation owns a spend policy: approval threshold, monthly cap and whether autopilot is permitted. The policy evaluator can allow, require an administrator, or deny based on the remaining monthly capacity. Agents are propose only. Plan 10's project and workspace limits remain additional limits; organisation caps are an aggregate ceiling. Every spend decision and use of an approval grant must be attributable to an actor in the hosted tier.

Support two billing modes, selected by each organisation:

1. **Bring your own provider keys:** organisation managed keys and usage reporting.
2. **Platform keys:** metered usage and invoicing, requiring a billing and metering service.

This ADR does not select a payment processor or authorize charging customers.

### Persistence, jobs and migration

Keep durable access behind the `aistudio.store` execute/query/transaction contract. SQLite remains the implemented backend. A Postgres backend is a documented stub until a later plan chooses its driver and migration strategy. Hosted jobs use a durable queue, with a Postgres backed queue as the initial candidate. Job payloads include tenant and actor identity, and workers restore that context before handling work.

Migrate by importing each existing project using the project zip format into an organisation and workspace. Preserve the project folder format as the portable export/import boundary. Map existing local rows to tenant `local`; hosted migration must not silently merge projects or provider keys across organisations.

## Consequences

- Local installs remain supported and default to `local` / `local` without identity setup.
- The code has basic role and spend policy vocabulary, but hosted authorization is not active.
- Tenant ids and actor ids are groundwork; they are not a substitute for RLS or a security boundary.
- Hosted launch needs a network architecture, identity integration, Postgres and object storage implementations, operational audit controls, and a reviewed data migration path.

## Open decisions

1. OIDC provider support and the conditions for SAML; session and account recovery design.
2. Whether roles are inherited from the organisation, workspace, or both, and the exact permission matrix.
3. Hosting target: managed cloud versus self hosted Docker or Helm; region and data residency needs.
4. Postgres driver, migration tool, connection pooling, RLS policy design, and tenant context propagation to pooled connections.
5. Queue implementation and worker isolation model; Postgres backed jobs remain the first candidate.
6. S3 compatible object store, retention and backup policy, signed URL limits, and tenant deletion retention window.
7. KMS provider, key rotation, recovery, and per organisation envelope key lifecycle.
8. Definition of monthly cap accounting (reservation vs actual cost, refunds, currency, reset time, and concurrency).
9. Platform key metering, invoicing provider, tax handling, and billing dispute process.
10. Audit event schema, retention, export, and tamper resistance.
11. Hosted availability targets, incident response, threat model and independent security review scope.

## Release gate

No outside organisation may be onboarded until plans 09–12 and the required hosted foundations are complete, a deployment and operations design is approved, tenant isolation and migration are tested, and an external security review signs off. Stage 2 foundation work alone does not satisfy this gate.

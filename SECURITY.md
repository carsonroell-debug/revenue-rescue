# Security Policy

Revenue Rescue is a public-site auditing and monitoring service. Security
reports are taken seriously.

## Supported versions

Before the first public release, only the latest deployed production version is
considered supported.

## Reporting a vulnerability

Do not open a public GitHub issue for a vulnerability that could expose data,
credentials, internal services, or enable abuse.

Before public launch, publish a monitored security contact in this file and on
the product website.

A useful report should include:

- affected endpoint/component;
- reproduction steps;
- impact;
- whether credentials or private-network access are involved;
- minimal evidence needed to reproduce.

Do not include secrets, personal data, or unrelated customer data.

## Scope / safety

Please do not:

- intentionally overload the service or third-party websites;
- probe private/internal network ranges;
- attempt destructive actions;
- access data that is not yours;
- publish exploit details before a fix is available.

## Current controls

Revenue Rescue currently includes:

- public HTTP(S)-only target validation;
- private/loopback/link-local hostname/IP blocking;
- redirect-hop SSRF checks;
- bounded crawl size and concurrency;
- bearer authentication support;
- a separate cron secret;
- REST rate limiting;
- structured request IDs/logging;
- private Postgres/Supabase-ready persistence;
- non-root container execution;
- container and platform health checks;
- precision-first finding rules that treat uncertain network failures as
  inconclusive.

## Known security assumptions

Application-level SSRF validation is defense in depth, not a complete network
sandbox. Production deployments should also restrict egress where practical.

In-memory rate limiting is instance-local. Multi-instance deployments should
move rate limits to shared infrastructure such as Redis/Valkey or an upstream
gateway.

Secrets must be configured through the deployment platform and never committed
to the repository.

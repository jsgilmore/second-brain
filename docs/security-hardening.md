# Security Hardening

## First hardening pass applied

The current stack now does two important things by default:

1. All published ports bind to `127.0.0.1` only.
2. The always-on `mcp` and `mcp_remote` containers do not mount `./config`.

That means:

- your router does not expose these services unless you explicitly add a tunnel or reverse proxy
- the public-facing MCP process cannot read your Gmail OAuth client JSON or token JSON from disk

## Why removing secret mounts matters

`./config` is where the Gmail OAuth desktop client file and Gmail token file live. Those files grant mailbox access.

If an always-on container has that directory mounted, then any remote compromise of that container can potentially expose those credentials. Removing the mount reduces the blast radius:

- remote MCP can read Postgres only
- Gmail OAuth material stays on the host
- a future Gmail sync process can be isolated separately if needed

## Current posture

- safer than before: yes
- internet-hardened enough for public exposure: not yet

You still need:

- HTTPS exposure through a tunnel or reverse proxy
- authentication on the remote MCP endpoint
- logging and rate limiting at the edge
- ideally a dedicated non-root runtime user and narrower network segmentation if you keep expanding this stack

## Remote MCP auth

The remote MCP server now supports Google OAuth authentication with an explicit allowlist:

- transport-level OAuth via FastMCP GoogleProvider
- tool-level email allowlist enforcement via `REMOTE_ALLOWED_EMAILS` and `REMOTE_ALLOWED_DOMAINS`

This is a good first hardening step because:

- unauthenticated requests are rejected at the MCP transport
- authenticated but unapproved Google accounts are denied tool access
- you can keep access scoped to one specific email address

Recommended single-user setting:

```dotenv
REMOTE_ALLOWED_EMAILS=you@gmail.com
```

## Embedding privacy

The stack now defaults to remote embeddings through OpenAI with `text-embedding-3-large`.

That means:

- email content used for embedding is sent to OpenAI
- the local deployment still stores the normalized mail archive and vectors in Postgres
- Postgres stores the resulting vectors for semantic search

# ChatGPT MCP Setup

## Important constraint

The MCP service in this repo runs locally on your machine, but ChatGPT needs a remote MCP endpoint. That means `http://localhost:8000/sse` is only the local service address, not the final ChatGPT connection URL.

You need to expose the service through HTTPS on a public URL that you control.

The stack now binds all published ports to `127.0.0.1`, so nothing is reachable from your LAN or the public internet until you deliberately put a tunnel or reverse proxy in front of it.

The remote MCP service now expects Google OAuth plus an explicit allowlist. That means the final public URL must also be configured as the OAuth base URL for the remote MCP server.

## Exposure options

You need a stable public HTTPS URL for ChatGPT to reach your MCP server.

Common options:

- `Tailscale Funnel`: quickest path for a personal self-hosted setup if you already use Tailscale
- `Cloudflare Tunnel`: managed public exposure without opening router ports
- `Caddy` or `Nginx` on your own domain: best when you want full control over DNS and TLS

Choose one approach and keep the same final HTTPS base URL for:

- `PUBLIC_BASE_URL`
- the Google OAuth web client settings
- the MCP URL you add in ChatGPT

## Minimal path

1. Run the local stack:

```bash
make up
```

The `mcp_remote` service is in the Docker `remote` profile, so start it explicitly when you are ready:

```bash
docker compose --profile remote up -d mcp_remote
```

2. Expose the MCP service on port `8000` through an HTTPS tunnel or reverse proxy.

Typical options:

- Cloudflare Tunnel
- Tailscale Funnel
- Caddy or Nginx on a public domain

3. Use the final HTTPS URL ending in `/sse` when connecting the MCP server inside ChatGPT.

Example target shape:

`https://mail-mcp.example.com/sse`

## Tailscale Funnel path

`Tailscale Funnel` is a good option for a personal setup, but it has a few requirements:

- Tailscale must be installed and logged in on the machine running this repo
- `MagicDNS` must be enabled on your tailnet
- Funnel must be allowed in your tailnet policy
- Funnel only works on specific public HTTPS ports, not arbitrary public ports

Suggested flow:

1. Start the local services:

```bash
make up
docker compose --profile remote up -d mcp_remote
```

2. Verify the local remote MCP endpoint responds:

```bash
curl http://localhost:8000/healthz
```

3. Create a Funnel to the local remote MCP service:

```bash
tailscale funnel 8000
```

Tailscale will print a public HTTPS URL in your `*.ts.net` domain.

4. Set `PUBLIC_BASE_URL` in `.env` to that HTTPS origin, without `/sse`.

Example:

```dotenv
PUBLIC_BASE_URL=https://your-machine-name.your-tailnet.ts.net
```

5. Create a Google OAuth `Web application` client for the same public origin and set:

- Authorized JavaScript origin: `https://your-machine-name.your-tailnet.ts.net`
- Authorized redirect URI: `https://your-machine-name.your-tailnet.ts.net/auth/callback`

6. Set the remote auth values in `.env`:

```dotenv
REMOTE_MCP_AUTH_REQUIRED=true
REMOTE_MCP_GOOGLE_CLIENT_ID=your-web-oauth-client-id.apps.googleusercontent.com
REMOTE_MCP_GOOGLE_CLIENT_SECRET=your-web-oauth-client-secret
REMOTE_ALLOWED_EMAILS=you@example.com
```

7. Restart the remote MCP service so it picks up the new environment:

```bash
docker compose --profile remote up -d mcp_remote
```

8. Add the server in ChatGPT using:

```text
https://your-machine-name.your-tailnet.ts.net/sse
```

Notes:

- The first Funnel enablement may require approval in the Tailscale admin flow.
- Public DNS for the Funnel hostname can take a few minutes to propagate.
- Keep the local API on `8080`, Postgres on `5432`, and n8n on `5678` private. Only expose the MCP endpoint.

## Required auth settings

Set these in `.env` before starting the remote MCP service:

```dotenv
PUBLIC_BASE_URL=https://mail-mcp.example.com
REMOTE_MCP_AUTH_REQUIRED=true
REMOTE_MCP_GOOGLE_CLIENT_ID=your-web-oauth-client-id.apps.googleusercontent.com
REMOTE_MCP_GOOGLE_CLIENT_SECRET=your-web-oauth-client-secret
REMOTE_ALLOWED_EMAILS=you@gmail.com
```

Use a Google OAuth `Web application` client and configure:

- Authorized JavaScript origin: `https://mail-mcp.example.com`
- Authorized redirect URI: `https://mail-mcp.example.com/auth/callback`

The remote MCP server will reject requests from Google accounts that are not explicitly allowlisted.

## What the server exposes

The remote MCP server provides these tools:

- `search`
- `search_chunks`
- `fetch`
- `fetch_thread`
- `status`
- `recent_mail`
- `contacts`
- `contact_messages`
- `investigate`

The intended ChatGPT flow is:

1. `search("emails about Acme renewal")`
2. ChatGPT selects message IDs from the result set
3. `fetch(message_id)` to retrieve full mail content

For structured exploration while the mailbox is still loading:

1. `status()` to inspect message counts and sync checkpoint state
2. `recent_mail(participant_email="someone@example.com")` to browse recent mail involving a person
3. `contacts(query="acme")` to find active people or aliases
4. `contact_messages(contact_email="someone@example.com")` to list message IDs before calling `fetch`

For deeper question-driven discovery:

1. `investigate("What have I been discussing with vendors about pricing pressure?")`
2. Review `themes`, `connections`, and `evidence`
3. Use `fetch` or `fetch_thread` only for the most relevant supporting messages

If you want chunk-level semantic evidence before opening whole emails:

1. `search_chunks("contract risk and delayed payment")`
2. Review the returned snippets and message IDs
3. Fetch only the messages or threads that matter

## Security baseline

- Do not expose the local API on `8080` publicly.
- Do not expose Postgres on `5432` publicly.
- Do not expose n8n on `5678` publicly.
- Put auth and TLS in front of the remote MCP endpoint.
- Assume mail content and embeddings are sensitive.
- Gmail OAuth files stay on the host in `./config` and are not mounted into the always-on containers.
- If you temporarily disable remote auth for local testing with `REMOTE_MCP_AUTH_REQUIRED=false`, do not expose that endpoint publicly.

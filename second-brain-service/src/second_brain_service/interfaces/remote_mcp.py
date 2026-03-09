from html import escape

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from second_brain_service.common.config import (
    DEFAULT_MAIL_SOURCE,
    MCP_REMOTE_PORT,
    PUBLIC_BASE_URL,
    REMOTE_MCP_AUTH_REQUIRED,
    REMOTE_MCP_GOOGLE_CLIENT_ID,
    REMOTE_MCP_GOOGLE_CLIENT_SECRET,
)
from second_brain_service.interfaces.remote_auth import build_google_auth_provider, require_allowed_user
from second_brain_service.search.embeddings import EmbeddingClient
from second_brain_service.search.retrieval import (
    contact_activity,
    get_thread,
    hybrid_search,
    investigate_mailbox,
    mailbox_status,
    messages_with_contact,
    recent_messages,
    search_chunks as search_chunks_query,
)
from second_brain_service.store.mail_repository import export_message_document


def _oauth_ready() -> bool:
    return bool(PUBLIC_BASE_URL and REMOTE_MCP_GOOGLE_CLIENT_ID and REMOTE_MCP_GOOGLE_CLIENT_SECRET)


def _render_page(title: str, body_html: str) -> HTMLResponse:
    html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{escape(title)}</title>
    <style>
      :root {{
        color-scheme: light;
        --bg: #f4efe6;
        --panel: rgba(255, 255, 255, 0.78);
        --ink: #173042;
        --muted: #4f6472;
        --line: rgba(23, 48, 66, 0.12);
        --teal: #0f766e;
        --gold: #c98016;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        min-height: 100vh;
        font-family: ui-serif, Georgia, Cambria, "Times New Roman", Times, serif;
        background:
          radial-gradient(circle at top right, rgba(201, 128, 22, 0.16), transparent 22rem),
          radial-gradient(circle at bottom left, rgba(15, 118, 110, 0.14), transparent 26rem),
          var(--bg);
        color: var(--ink);
      }}
      main {{
        max-width: 860px;
        margin: 0 auto;
        padding: 48px 24px 72px;
      }}
      .card {{
        background: var(--panel);
        border: 1px solid var(--line);
        backdrop-filter: blur(10px);
        border-radius: 28px;
        padding: 32px;
        box-shadow: 0 24px 60px rgba(23, 48, 66, 0.08);
      }}
      h1, h2 {{ margin: 0 0 16px; line-height: 1.05; }}
      h1 {{ font-size: clamp(2.3rem, 6vw, 4.8rem); max-width: 10ch; }}
      h2 {{ font-size: 1.35rem; margin-top: 28px; }}
      p, li {{ color: var(--muted); font-size: 1.05rem; line-height: 1.7; }}
      .eyebrow {{
        display: inline-block;
        margin-bottom: 14px;
        letter-spacing: 0.14em;
        text-transform: uppercase;
        color: var(--teal);
        font: 600 0.76rem/1.2 ui-monospace, SFMono-Regular, Menlo, monospace;
      }}
      .grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 16px;
        margin-top: 24px;
      }}
      .panel {{
        border: 1px solid var(--line);
        border-radius: 18px;
        padding: 18px;
        background: rgba(255,255,255,0.56);
      }}
      .status {{
        margin-top: 24px;
        padding: 14px 16px;
        border-left: 4px solid var(--gold);
        background: rgba(201, 128, 22, 0.08);
        color: var(--ink);
      }}
      a {{ color: var(--teal); }}
      footer {{
        margin-top: 28px;
        display: flex;
        gap: 14px;
        flex-wrap: wrap;
        font: 500 0.95rem/1.4 ui-monospace, SFMono-Regular, Menlo, monospace;
      }}
      code {{
        font: 500 0.94em/1.3 ui-monospace, SFMono-Regular, Menlo, monospace;
        color: var(--ink);
      }}
      ul {{ padding-left: 20px; }}
    </style>
  </head>
  <body>
    <main>
      <section class="card">
        {body_html}
        <footer>
          <a href="/">Home</a>
          <a href="/privacy">Privacy</a>
          <a href="/terms">Terms</a>
        </footer>
      </section>
    </main>
  </body>
</html>"""
    return HTMLResponse(html)


def create_mcp_server() -> FastMCP:
    if REMOTE_MCP_AUTH_REQUIRED and _oauth_ready():
        mcp = FastMCP("gmail-second-brain", auth=build_google_auth_provider())
    else:
        mcp = FastMCP("gmail-second-brain")
    embedding_client = EmbeddingClient()
    readonly_annotations = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    @mcp.custom_route("/", methods=["GET"], include_in_schema=False)
    async def homepage(_: Request) -> Response:
        oauth_status = "configured" if _oauth_ready() else "pending setup"
        body = f"""
        <span class="eyebrow">Second Brain Mail</span>
        <h1>A private mail memory, served from your infrastructure.</h1>
        <p>
          This application exposes a read-only mailbox knowledge service over Model Context Protocol
          so ChatGPT can search and retrieve mail already synced into a local Postgres archive.
        </p>
        <div class="grid">
          <div class="panel">
            <h2>What it does</h2>
            <p>Indexes Gmail into a self-hosted database and exposes search, thread fetch, contact activity, and mailbox status tools.</p>
          </div>
          <div class="panel">
            <h2>How it is hosted</h2>
            <p>The service runs on self-hosted infrastructure and is published at <code>{escape(PUBLIC_BASE_URL or "")}</code>.</p>
          </div>
        </div>
        <div class="status">
          OAuth status: <strong>{escape(oauth_status)}</strong>. Public legal pages are live. MCP sign-in activates after the Google OAuth client is configured.
        </div>
        """
        return _render_page("Second Brain Mail", body)

    @mcp.custom_route("/privacy", methods=["GET"], include_in_schema=False)
    async def privacy(_: Request) -> Response:
        body = """
        <span class="eyebrow">Privacy Policy</span>
        <h1>Mail content stays under the user&apos;s control.</h1>
        <p>
          This application is a self-hosted email knowledge service operated by the deployment owner. It connects to a Gmail account,
          stores message metadata and content in a privately managed Postgres database, and exposes read-only retrieval tools for authorized use.
        </p>
        <h2>Data Collected</h2>
        <ul>
          <li>Email message content, metadata, participants, thread structure, and derived search indexes from the connected Gmail account.</li>
          <li>Basic Google identity information used for sign-in to the remote MCP endpoint, including email address and verification status.</li>
          <li>Operational logs needed to diagnose sync and access issues.</li>
        </ul>
        <h2>How Data Is Used</h2>
        <ul>
          <li>To search, retrieve, and summarize the mailbox inside personal AI workflows.</li>
          <li>To authenticate access and restrict usage to explicitly allowlisted accounts.</li>
          <li>To maintain sync integrity, uptime, and troubleshooting information.</li>
        </ul>
        <h2>Data Sharing</h2>
        <p>
          Mailbox data is not sold. Data may be processed by infrastructure and AI providers required to operate the service,
          including Google for account authentication and Gmail access, Tailscale for secure remote exposure, and embedding providers
          when semantic search is enabled.
        </p>
        <h2>Retention and Security</h2>
        <p>
          Data is retained in the self-hosted database until the operator deletes it. Access is limited through Google sign-in,
          explicit allowlists, and private infrastructure running on the operator&apos;s hardware.
        </p>
        <h2>Contact</h2>
        <p>Questions about this service should be directed to the deployment owner or maintainer.</p>
        """
        return _render_page("Privacy Policy | Second Brain Mail", body)

    @mcp.custom_route("/terms", methods=["GET"], include_in_schema=False)
    async def terms(_: Request) -> Response:
        body = """
        <span class="eyebrow">Terms of Service</span>
        <h1>This service is for authorized use only.</h1>
        <p>
          Second Brain Mail is a self-hosted application for querying and retrieving mailbox data controlled by the deployment owner.
          Access is limited to approved accounts.
        </p>
        <h2>Permitted Use</h2>
        <ul>
          <li>You may use the service only if you are the operator or an explicitly authorized user.</li>
          <li>You may use the service only for lawful access to mailbox data you are permitted to view.</li>
        </ul>
        <h2>Restrictions</h2>
        <ul>
          <li>You may not attempt to bypass authentication, authorization, or infrastructure controls.</li>
          <li>You may not use the service to access data belonging to accounts that have not been approved.</li>
          <li>You may not interfere with the availability or integrity of the service.</li>
        </ul>
        <h2>No Warranty</h2>
        <p>
          The service is provided on an &quot;as is&quot; basis, without warranties of availability, fitness for a particular purpose,
          or error-free operation.
        </p>
        <h2>Termination</h2>
        <p>
          Access may be revoked at any time by the operator. The operator may suspend or discontinue the service without notice.
        </p>
        """
        return _render_page("Terms of Service | Second Brain Mail", body)

    @mcp.custom_route("/healthz", methods=["GET"], include_in_schema=False)
    async def remote_health(_: Request) -> Response:
        return JSONResponse(
            {
                "status": "ok",
                "oauth_ready": _oauth_ready(),
                "auth_required": REMOTE_MCP_AUTH_REQUIRED,
                "public_base_url": PUBLIC_BASE_URL,
            }
        )

    @mcp.tool(annotations=readonly_annotations)
    def search(query: str, limit: int = 8) -> dict:
        require_allowed_user()
        query_embedding = embedding_client.embed_query(query) if embedding_client.enabled else None
        return hybrid_search(query=query, limit=limit, source=DEFAULT_MAIL_SOURCE, query_embedding=query_embedding)

    @mcp.tool(annotations=readonly_annotations)
    def search_chunks(query: str, limit: int = 8) -> dict:
        require_allowed_user()
        query_embedding = embedding_client.embed_query(query) if embedding_client.enabled else None
        return search_chunks_query(query=query, limit=limit, source=DEFAULT_MAIL_SOURCE, query_embedding=query_embedding)

    @mcp.tool(annotations=readonly_annotations)
    def fetch(message_id: str) -> dict:
        require_allowed_user()
        document = export_message_document(message_id)
        if not document:
            raise ValueError(f"message not found: {message_id}")
        return document

    @mcp.tool(annotations=readonly_annotations)
    def fetch_thread(conversation_id: str, limit: int = 200) -> dict:
        require_allowed_user()
        return get_thread(conversation_id, limit)

    @mcp.tool(annotations=readonly_annotations)
    def status() -> dict:
        require_allowed_user()
        return mailbox_status()

    @mcp.tool(annotations=readonly_annotations)
    def recent_mail(
        limit: int = 20,
        subject_query: str | None = None,
        sender_email: str | None = None,
        participant_email: str | None = None,
    ) -> dict:
        require_allowed_user()
        return recent_messages(
            limit=limit,
            subject_query=subject_query,
            sender_email=sender_email,
            participant_email=participant_email,
        )

    @mcp.tool(annotations=readonly_annotations)
    def contacts(limit: int = 20, query: str | None = None) -> dict:
        require_allowed_user()
        return contact_activity(limit=limit, query=query)

    @mcp.tool(annotations=readonly_annotations)
    def contact_messages(contact_email: str, limit: int = 20) -> dict:
        require_allowed_user()
        return messages_with_contact(contact_email=contact_email, limit=limit)

    @mcp.tool(annotations=readonly_annotations)
    def investigate(question: str, limit: int = 12) -> dict:
        require_allowed_user()
        query_embedding = embedding_client.embed_query(question) if embedding_client.enabled else None
        return investigate_mailbox(
            question=question,
            limit=limit,
            source=DEFAULT_MAIL_SOURCE,
            query_embedding=query_embedding,
        )

    return mcp


def serve_remote_mcp() -> None:
    mcp = create_mcp_server()
    mcp.run(transport="sse", host="0.0.0.0", port=MCP_REMOTE_PORT)

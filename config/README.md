# Config

This directory is for local machine configuration and OAuth material used by host-side commands.

Expected local files:

- `gmail-oauth-client.json`
- `gmail-token.json`

Notes:

- these files are local secrets and should not be committed
- `gmail-oauth-client.json` is the downloaded Google desktop OAuth client
- `gmail-token.json` is generated after completing the OAuth flow on the host machine

If you need to rotate credentials, replace the client file and delete the token file before re-authenticating.

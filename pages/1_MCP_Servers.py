"""MCP Servers page — add, edit, enable/disable, delete, and (re)authenticate."""

import json
import logging

import streamlit as st

import db
from ui_common import init_app, render_nav, get_client_and_tools
from oauth_store import OAuthHandler

logger = logging.getLogger("mcpchat.mcp_servers")

st.set_page_config(page_title="MCP Servers", page_icon="🔌", layout="wide")
init_app()
render_nav()

st.title("🔌 MCP Servers")
st.caption("Configure the MCP servers the chat connects to. Stored in SQLite.")

# Reconnect = authenticate any OAuth server that lacks a valid token (opens a
# browser when needed), then re-discover tools for all enabled servers.
if st.button("🔄 Reconnect MCP servers", key="resync_servers"):
    # Surfaced sign-in link — the browser may not open automatically (e.g. when
    # running in Docker), so always show a clickable link to complete OAuth.
    link_box = st.empty()
    with st.spinner("Reconnecting… click the sign-in link if a browser doesn't open."):
        for s in db.list_servers(enabled_only=True):
            if s["auth_type"] == "oauth":
                handler = OAuthHandler(s["name"], s["url"], s.get("oauth"))
                if not handler.token_noninteractive():
                    try:
                        handler.authorize(on_auth_url=lambda url, n=s["name"]: link_box.markdown(
                            f"🔐 **{n}** needs sign-in — [click here to authenticate]({url})"))
                    except Exception as e:  # noqa: BLE001
                        logger.exception("Reconnect: OAuth failed for %s", s["name"])
                        st.toast(f"{s['name']}: authentication failed: {e}", icon="⚠️")
    get_client_and_tools.clear()
    st.rerun()

# --- existing servers --------------------------------------------------------
servers = db.list_servers()
if not servers:
    st.info("No servers yet. Add one below.")

for s in servers:
    with st.expander(f"{'🟢' if s['enabled'] else '⚪'} {s['name']}  —  {s['url']}",
                     expanded=False):
        with st.form(f"edit_{s['id']}"):
            url = st.text_input("URL", value=s["url"])
            auth_type = st.selectbox(
                "Auth type", ["none", "token", "oauth"],
                index=["none", "token", "oauth"].index(s["auth_type"])
                if s["auth_type"] in ("none", "token", "oauth") else 1,
            )
            token = ""
            if auth_type == "token":
                token = st.text_input(
                    "Bearer token", value=(s.get("oauth") or {}).get("token", ""),
                    type="password",
                )
            oauth_json = ""
            if auth_type == "oauth":
                oauth_json = st.text_area(
                    "OAuth config (optional JSON: scopes, client_id, …)",
                    value=json.dumps(s.get("oauth"), indent=2) if s.get("oauth") else "",
                    height=120,
                )
            enabled = st.checkbox("Enabled", value=s["enabled"])

            c1, c2 = st.columns(2)
            if c1.form_submit_button("💾 Save", width='stretch'):
                oauth = None
                if auth_type == "token" and token:
                    oauth = {"token": token}
                elif auth_type == "oauth" and oauth_json.strip():
                    try:
                        oauth = json.loads(oauth_json)
                    except json.JSONDecodeError as e:
                        logger.warning("Invalid OAuth JSON for server %s: %s", s["name"], e)
                        st.error(f"Invalid OAuth JSON: {e}")
                        st.stop()
                db.update_server(s["id"], url=url, auth_type=auth_type,
                                 enabled=enabled, oauth=oauth)
                st.toast("Saved.", icon="✅")
                st.rerun()
            if c2.form_submit_button("🗑 Delete", width='stretch'):
                db.remove_server(s["id"])
                st.rerun()

        # OAuth status + re-auth (outside the form so the button works immediately)
        if s["auth_type"] == "oauth":
            tok = db.get_oauth_token(s["name"])
            if tok and tok.get("access_token"):
                st.caption(f"Token stored (expires: {tok.get('expires_at', 'n/a')})")
            else:
                st.caption("No token stored yet.")
            if st.button("🔐 Re-authenticate", key=f"auth_{s['id']}"):
                link_box = st.empty()
                with st.spinner("Completing OAuth — click the sign-in link if a "
                                "browser doesn't open…"):
                    try:
                        handler = OAuthHandler(s["name"], s["url"], s.get("oauth"))
                        token = handler.authorize(
                            on_auth_url=lambda url: link_box.markdown(
                                f"🔐 [Click here to sign in]({url})"))
                        if token:
                            st.toast("Authenticated.", icon="✅")
                        else:
                            logger.error("Re-authenticate failed or timed out for %s", s["name"])
                            st.toast("Authentication failed or timed out.", icon="❌")
                    except Exception as e:  # noqa: BLE001
                        logger.exception("Re-authenticate error for %s", s["name"])
                        st.toast(f"OAuth error: {e}", icon="❌")
                st.rerun()

# --- add new server ----------------------------------------------------------
st.divider()
st.subheader("Add a server")
with st.form("add_server", clear_on_submit=True):
    name = st.text_input("Name", placeholder="e.g. Salesforce")
    new_url = st.text_input("URL", placeholder="https://....mcp.workato.com/")
    new_auth = st.selectbox("Auth type", ["none", "token", "oauth"], index=2)
    new_token = st.text_input("Bearer token (if token auth)", type="password")
    if st.form_submit_button("➕ Add server"):
        if not name or not new_url:
            logger.warning("Add server rejected: name and URL are required")
            st.error("Name and URL are required.")
        else:
            oauth = {"token": new_token} if (new_auth == "token" and new_token) else None
            db.add_server(name=name, url=new_url, auth_type=new_auth,
                          enabled=True, oauth=oauth)
            st.toast(f"Added {name}.", icon="✅")
            st.rerun()

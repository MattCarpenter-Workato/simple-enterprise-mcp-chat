"""System Prompts page — create, edit, and delete reusable system prompts."""

import streamlit as st

import db
from ui_common import init_app

st.set_page_config(page_title="System Prompts", page_icon="📝", layout="wide")
init_app()

st.title("📝 System Prompts")
st.caption("Saved prompts can be selected in the chat sidebar to steer responses.")

# --- existing prompts --------------------------------------------------------
for p in db.list_prompts():
    with st.expander(p["name"]):
        with st.form(f"edit_prompt_{p['id']}"):
            name = st.text_input("Name", value=p["name"])
            content = st.text_area("Prompt", value=p["content"], height=160)
            c1, c2 = st.columns(2)
            if c1.form_submit_button("💾 Save", width='stretch'):
                if name and content:
                    db.save_prompt(name, content, prompt_id=p["id"])
                    st.success("Saved.")
                    st.rerun()
                else:
                    st.error("Name and prompt are required.")
            if c2.form_submit_button("🗑 Delete", width='stretch'):
                db.delete_prompt(p["id"])
                st.rerun()

# --- new prompt --------------------------------------------------------------
st.divider()
st.subheader("New prompt")
with st.form("new_prompt", clear_on_submit=True):
    name = st.text_input("Name", placeholder="e.g. Concise assistant")
    content = st.text_area("Prompt", height=160,
                           placeholder="You are a concise assistant that…")
    if st.form_submit_button("➕ Create"):
        if not name or not content:
            st.error("Name and prompt are required.")
        else:
            try:
                db.save_prompt(name, content)
                st.success(f"Created '{name}'.")
                st.rerun()
            except Exception as e:  # noqa: BLE001 (likely a duplicate name)
                st.error(f"Could not save: {e}")

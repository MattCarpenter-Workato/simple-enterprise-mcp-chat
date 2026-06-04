"""System Prompts page — create, edit, and delete reusable system prompts.

Prompts are authored in Markdown with a live rendered preview. The content is
stored and sent to the model as raw text (Markdown flows through unchanged).
"""

import logging

import streamlit as st

import db
from ui_common import init_app, render_nav

logger = logging.getLogger("mcpchat.system_prompts")

st.set_page_config(page_title="System Prompts", page_icon="📝", layout="wide")
init_app()
render_nav()

st.title("📝 System Prompts")
st.caption("Saved prompts can be selected in the chat sidebar to steer responses. "
           "Markdown is supported — use the preview to see how it renders.")

# --- existing prompts --------------------------------------------------------
for p in db.list_prompts():
    with st.expander(p["name"]):
        edit_col, prev_col = st.columns(2)
        with edit_col:
            name = st.text_input("Name", value=p["name"], key=f"name_{p['id']}")
            content = st.text_area("Prompt (Markdown)", value=p["content"],
                                   height=260, key=f"content_{p['id']}")
            b1, b2 = st.columns(2)
            save = b1.button("💾 Save", key=f"save_{p['id']}", width='stretch')
            delete = b2.button("🗑 Delete", key=f"del_{p['id']}", width='stretch')
        with prev_col:
            st.caption("Preview")
            st.markdown(content or "_(empty)_")

        if save:
            if name and content:
                db.save_prompt(name, content, prompt_id=p["id"])
                st.toast("Saved.", icon="✅")
                st.rerun()
            else:
                logger.warning("Save prompt rejected (id=%s): name and content required", p["id"])
                st.error("Name and prompt are required.")
        if delete:
            db.delete_prompt(p["id"])
            st.rerun()

# --- new prompt --------------------------------------------------------------
st.divider()
st.subheader("New prompt")
edit_col, prev_col = st.columns(2)
with edit_col:
    new_name = st.text_input("Name", placeholder="e.g. Concise assistant",
                             key="new_prompt_name")
    new_content = st.text_area("Prompt (Markdown)", height=260,
                               placeholder="You are a concise assistant that…\n\n"
                                           "## Style\n- Use bullet points\n- Be brief",
                               key="new_prompt_content")
    save_new = st.button("💾 Save", key="save_prompt")
with prev_col:
    st.caption("Preview")
    st.markdown(new_content or "_(nothing to preview)_")

if save_new:
    if not new_name or not new_content:
        logger.warning("Create prompt rejected: name and content required")
        st.error("Name and prompt are required.")
    else:
        try:
            db.save_prompt(new_name, new_content)
            # Reset the input fields on success so it's ready for the next prompt.
            for k in ("new_prompt_name", "new_prompt_content"):
                st.session_state.pop(k, None)
            st.toast(f"Saved '{new_name}'.", icon="✅")
            st.rerun()
        except Exception as e:  # noqa: BLE001 (likely a duplicate name)
            logger.exception("Could not save prompt '%s'", new_name)
            st.error(f"Could not save: {e}")

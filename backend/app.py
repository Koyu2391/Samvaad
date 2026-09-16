import streamlit as st
 
from core.query_engine import build_query_engine
from ui.sidebar import render_sidebar
from ui.chat import render_chat
 
# PAGE CONFIG
st.set_page_config(page_title="RAG LangChain", layout="wide")
 

# SIDEBAR  -  model selection + indexing
selected_model, persist_dir = render_sidebar()
 
# QUERY ENGINE -  built from persisted index
query_engine = build_query_engine(persist_dir, selected_model)
 
# CHAT UI
render_chat(query_engine, persist_dir, selected_model)
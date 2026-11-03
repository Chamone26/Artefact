"""Interface web do agente, independente da CLI.

Uso, a partir da raiz do projeto: streamlit run streamlit_app.py
"""

import uuid

import streamlit as st

from agent.api_client import ApiUnavailableError
from agent.config import ConfigError, Settings
from agent.graph import create_agent


st.set_page_config(page_title="Empório da Música")
st.title("Empório da Música")
st.caption("Assistente de atendimento")

if "agent" not in st.session_state:
    try:
        settings = Settings.from_env()
        st.session_state.agent = create_agent(settings)
    except (ApiUnavailableError, ConfigError) as error:
        st.error(str(error))
        st.stop()

if "conversation_id" not in st.session_state:
    st.session_state.conversation_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []

if st.sidebar.button("Nova conversa"):
    st.session_state.conversation_id = str(uuid.uuid4())
    st.session_state.messages = []
    st.rerun()

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Como posso ajudar?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Consultando..."):
            reply = st.session_state.agent.respond(st.session_state.conversation_id, prompt)
        st.markdown(reply.text)
    st.session_state.messages.append({"role": "assistant", "content": reply.text})

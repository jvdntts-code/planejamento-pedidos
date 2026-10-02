import hmac

import streamlit as st


def _secret(name, default=""):
    try:
        return st.secrets[name] if name in st.secrets else default
    except Exception:
        return default


def _load_users():
    users = {}

    # Formato recomendado para vários usuários:
    # [auth.users.jvn]
    # name = "JVN"
    # password = "senha"
    try:
        auth = st.secrets["auth"] if "auth" in st.secrets else {}
        users_cfg = auth.get("users", {}) if hasattr(auth, "get") else {}

        for username, data in users_cfg.items():
            if not hasattr(data, "get"):
                continue
            password = str(data.get("password", ""))
            if not password:
                continue
            users[str(username).strip()] = {
                "password": password,
                "name": str(data.get("name", username)).strip() or str(username),
            }
    except Exception:
        pass

    # Formato simples, útil para começar com apenas um usuário.
    if not users:
        username = str(_secret("NEXO_LOGIN_USER", "")).strip()
        password = str(_secret("NEXO_LOGIN_PASSWORD", ""))
        display_name = str(_secret("NEXO_LOGIN_NAME", username)).strip()

        if username and password:
            users[username] = {
                "password": password,
                "name": display_name or username,
            }

    return users


def _valid_login(username, password, users):
    username = str(username or "").strip()
    password = str(password or "")

    if username not in users:
        return False

    saved = str(users[username].get("password", ""))
    return hmac.compare_digest(password, saved)


def require_login():
    users = _load_users()

    # Não bloqueia o app antes da configuração dos Secrets.
    if not users:
        st.sidebar.warning("🔓 Login ainda não configurado.")
        return {
            "authenticated": False,
            "configured": False,
            "username": "",
            "name": "",
        }

    if "nexo_authenticated" not in st.session_state:
        st.session_state["nexo_authenticated"] = False
    if "nexo_username" not in st.session_state:
        st.session_state["nexo_username"] = ""
    if "nexo_user_name" not in st.session_state:
        st.session_state["nexo_user_name"] = ""

    if not st.session_state["nexo_authenticated"]:
        st.markdown(
            """
            <style>
            section[data-testid="stSidebar"] {display: none;}
            .nexo-login-title {
                text-align:center;
                font-size:2.4rem;
                font-weight:800;
                letter-spacing:.10em;
                margin-top:6rem;
            }
            .nexo-login-subtitle {
                text-align:center;
                opacity:.68;
                margin-bottom:1.5rem;
            }
            </style>
            <div class="nexo-login-title">NEXO</div>
            <div class="nexo-login-subtitle">Gestão • Planejamento • Inteligência</div>
            """,
            unsafe_allow_html=True,
        )

        left, center, right = st.columns([1.3, 1, 1.3])
        with center:
            with st.container(border=True):
                st.markdown("### 🔐 Entrar")
                with st.form("nexo_login_form", clear_on_submit=False):
                    username = st.text_input(
                        "Usuário",
                        autocomplete="username",
                    )
                    password = st.text_input(
                        "Senha",
                        type="password",
                        autocomplete="current-password",
                    )
                    submitted = st.form_submit_button(
                        "Entrar",
                        type="primary",
                        use_container_width=True,
                    )

                if submitted:
                    if _valid_login(username, password, users):
                        st.session_state["nexo_authenticated"] = True
                        st.session_state["nexo_username"] = username.strip()
                        st.session_state["nexo_user_name"] = users[
                            username.strip()
                        ]["name"]
                        st.rerun()
                    else:
                        st.error("Usuário ou senha incorretos.")

        st.stop()

    username = st.session_state.get("nexo_username", "")
    name = st.session_state.get("nexo_user_name", username)

    st.sidebar.caption(f"👤 {name}")
    if st.sidebar.button("Sair", key="nexo_logout", use_container_width=True):
        st.session_state["nexo_authenticated"] = False
        st.session_state["nexo_username"] = ""
        st.session_state["nexo_user_name"] = ""
        st.rerun()

    return {
        "authenticated": True,
        "configured": True,
        "username": username,
        "name": name,
    }

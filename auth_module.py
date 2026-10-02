import base64
import hashlib
import hmac
import json
import re
import secrets
import string
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

import streamlit as st


AUTH_USERS_FILE = "auth/users.json"
DEFAULT_DATA_BRANCH = "main"
PBKDF2_ITERATIONS = 240_000


def _secret(name, default=""):
    try:
        return st.secrets[name] if name in st.secrets else default
    except Exception:
        return default


def current_username():
    return str(st.session_state.get("nexo_username", "")).strip()


def _safe_user_slug(value):
    text = str(value or "").strip().lower()
    text = "".join(
        char
        for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )
    text = re.sub(r"[^a-z0-9._-]+", "-", text).strip("-._")
    return text or "usuario"


def user_storage_prefix(username=None):
    user = username if username is not None else current_username()
    return f"users/{_safe_user_slug(user)}"


def _data_settings():
    repo = str(_secret("GITHUB_DATA_REPO", "")).strip()
    branch = str(
        _secret(
            "GITHUB_DATA_BRANCH",
            _secret("GITHUB_BRANCH", DEFAULT_DATA_BRANCH),
        )
    ).strip()
    token = str(_secret("GITHUB_TOKEN", "")).strip()
    return repo, branch or DEFAULT_DATA_BRANCH, token


def _github_headers(token=""):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "nexo-auth",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _read_registry():
    repo, branch, token = _data_settings()
    if not repo or not token:
        return {}, None, (
            "Configure GITHUB_DATA_REPO e GITHUB_TOKEN nos Secrets "
            "para habilitar contas dinâmicas."
        )

    encoded_path = urllib.parse.quote(AUTH_USERS_FILE, safe="/")
    encoded_branch = urllib.parse.quote(branch, safe="")
    url = (
        f"https://api.github.com/repos/{repo}/contents/{encoded_path}"
        f"?ref={encoded_branch}"
    )
    request = urllib.request.Request(url, headers=_github_headers(token), method="GET")

    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
        raw = base64.b64decode(payload.get("content", "")).decode("utf-8")
        saved = json.loads(raw)
        users = saved.get("users", {}) if isinstance(saved, dict) else {}
        return (users if isinstance(users, dict) else {}), payload.get("sha"), None
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {}, None, None
        return {}, None, f"Não foi possível carregar as contas (HTTP {exc.code})."
    except Exception as exc:
        return {}, None, f"Não foi possível carregar as contas: {exc}"


def _write_registry(users, sha=None):
    repo, branch, token = _data_settings()
    if not repo or not token:
        return False, (
            "Configure GITHUB_DATA_REPO e GITHUB_TOKEN nos Secrets "
            "para salvar contas."
        )

    encoded_path = urllib.parse.quote(AUTH_USERS_FILE, safe="/")
    url = f"https://api.github.com/repos/{repo}/contents/{encoded_path}"

    if sha is None:
        _, current_sha, read_error = _read_registry()
        if read_error:
            return False, read_error
        sha = current_sha

    payload_data = {
        "version": 1,
        "users": users,
    }
    raw = json.dumps(
        payload_data,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8")

    payload = {
        "message": "Atualiza contas do NEXO",
        "content": base64.b64encode(raw).decode("ascii"),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            **_github_headers(token),
            "Content-Type": "application/json",
        },
        method="PUT",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            response.read()
        return True, None
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("message", "")
        except Exception:
            detail = ""
        suffix = f" — {detail}" if detail else ""
        return False, f"Não foi possível salvar as contas (HTTP {exc.code}){suffix}."
    except Exception as exc:
        return False, f"Não foi possível salvar as contas: {exc}"


def _load_legacy_users():
    users = {}

    try:
        auth = st.secrets["auth"] if "auth" in st.secrets else {}
        users_cfg = auth.get("users", {}) if hasattr(auth, "get") else {}

        for username, data in users_cfg.items():
            if not hasattr(data, "get"):
                continue
            password = str(data.get("password", ""))
            if not password:
                continue
            key = str(username).strip()
            users[key] = {
                "password": password,
                "name": str(data.get("name", username)).strip() or key,
                "source": "legacy",
            }
    except Exception:
        pass

    username = str(_secret("NEXO_LOGIN_USER", "")).strip()
    password = str(_secret("NEXO_LOGIN_PASSWORD", ""))
    display_name = str(_secret("NEXO_LOGIN_NAME", username)).strip()

    if username and password and username not in users:
        users[username] = {
            "password": password,
            "name": display_name or username,
            "source": "legacy",
        }

    return users


def _password_hash(password, salt=None):
    salt_bytes = bytes.fromhex(salt) if salt else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        str(password).encode("utf-8"),
        salt_bytes,
        PBKDF2_ITERATIONS,
    )
    return salt_bytes.hex(), digest.hex()


def _verify_hash(value, salt, expected):
    if not salt or not expected:
        return False
    _, calculated = _password_hash(value, salt=salt)
    return hmac.compare_digest(calculated, str(expected))


def _new_recovery_code():
    alphabet = string.ascii_uppercase + string.digits
    raw = "".join(secrets.choice(alphabet) for _ in range(16))
    return "-".join(raw[i:i + 4] for i in range(0, 16, 4))


def _normalize_recovery_code(value):
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())


def _username_key(value):
    return str(value or "").strip().casefold()


def _find_registry_user(users, username):
    target = _username_key(username)
    for key, data in users.items():
        if _username_key(key) == target:
            return key, data
    return None, None


def _find_legacy_user(users, username):
    target = _username_key(username)
    for key, data in users.items():
        if _username_key(key) == target:
            return key, data
    return None, None


def _load_users():
    registry, _, registry_error = _read_registry()
    users = {}

    for username, data in registry.items():
        if not isinstance(data, dict):
            continue
        users[username] = {
            **data,
            "name": str(data.get("name", username)).strip() or username,
            "source": "registry",
        }

    for username, data in _load_legacy_users().items():
        if _find_registry_user(registry, username)[0] is None:
            users[username] = data

    return users, registry_error


def _valid_login(username, password, users):
    key, user = _find_registry_user(users, username)
    if user is None:
        return False, None, None

    if user.get("source") == "registry":
        ok = _verify_hash(
            str(password or ""),
            str(user.get("password_salt", "")),
            str(user.get("password_hash", "")),
        )
    else:
        ok = hmac.compare_digest(
            str(password or ""),
            str(user.get("password", "")),
        )

    return ok, key, user


def _validate_new_account(name, username, password, confirm):
    errors = []
    name = str(name or "").strip()
    username = str(username or "").strip()

    if len(name) < 2:
        errors.append("Informe seu nome.")
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,40}", username):
        errors.append(
            "O usuário deve ter de 3 a 40 caracteres e usar apenas letras, "
            "números, ponto, hífen ou sublinhado."
        )
    if len(str(password or "")) < 8:
        errors.append("A senha deve ter pelo menos 8 caracteres.")
    if str(password or "") != str(confirm or ""):
        errors.append("As senhas não conferem.")
    return errors


def _create_registry_user(name, username, password):
    registry, sha, error = _read_registry()
    if error:
        return False, error, None, None

    legacy = _load_legacy_users()
    if (
        _find_registry_user(registry, username)[0] is not None
        or _find_legacy_user(legacy, username)[0] is not None
    ):
        return False, "Este usuário já existe.", None, None

    recovery_code = _new_recovery_code()
    password_salt, password_hash = _password_hash(password)
    recovery_salt, recovery_hash = _password_hash(
        _normalize_recovery_code(recovery_code)
    )

    canonical = str(username).strip()
    registry[canonical] = {
        "name": str(name).strip(),
        "password_salt": password_salt,
        "password_hash": password_hash,
        "recovery_salt": recovery_salt,
        "recovery_hash": recovery_hash,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "password_changed_at": datetime.now().isoformat(timespec="seconds"),
    }

    ok, save_error = _write_registry(registry, sha=sha)
    if not ok:
        return False, save_error, None, None

    return True, None, canonical, recovery_code


def _migrate_legacy_user(username, user, password):
    registry, sha, error = _read_registry()
    if error:
        return None, error

    existing_key, _ = _find_registry_user(registry, username)
    if existing_key is not None:
        return None, None

    recovery_code = _new_recovery_code()
    password_salt, password_hash = _password_hash(password)
    recovery_salt, recovery_hash = _password_hash(
        _normalize_recovery_code(recovery_code)
    )

    registry[str(username).strip()] = {
        "name": str(user.get("name", username)).strip() or str(username).strip(),
        "password_salt": password_salt,
        "password_hash": password_hash,
        "recovery_salt": recovery_salt,
        "recovery_hash": recovery_hash,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "password_changed_at": datetime.now().isoformat(timespec="seconds"),
        "migrated_from_secrets": True,
    }

    ok, save_error = _write_registry(registry, sha=sha)
    if not ok:
        return None, save_error

    return recovery_code, None


def _reset_password(username, recovery_code, new_password):
    registry, sha, error = _read_registry()
    if error:
        return False, error

    key, user = _find_registry_user(registry, username)

    supplied = str(recovery_code or "").strip()

    if user is None:
        legacy_key, legacy_user = _find_legacy_user(_load_legacy_users(), username)
        if legacy_user is None:
            return False, (
                "Conta não encontrada ou ainda não migrada. "
                "Entre uma vez com a senha atual ou procure o administrador."
            )
        return False, (
            "Essa conta ainda usa o login antigo. "
            "Entre uma vez com a senha atual para concluir a migração."
        )

        recovery_new = _new_recovery_code()
        password_salt, password_hash = _password_hash(new_password)
        recovery_salt, recovery_hash = _password_hash(
            _normalize_recovery_code(recovery_new)
        )
        registry[legacy_key] = {
            "name": str(legacy_user.get("name", legacy_key)),
            "password_salt": password_salt,
            "password_hash": password_hash,
            "recovery_salt": recovery_salt,
            "recovery_hash": recovery_hash,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "password_changed_at": datetime.now().isoformat(timespec="seconds"),
            "migrated_from_secrets": True,
        }
        ok, save_error = _write_registry(registry, sha=sha)
        if not ok:
            return False, save_error
        st.session_state["nexo_reset_recovery_code"] = recovery_new
        return True, None

    recovery_ok = _verify_hash(
        _normalize_recovery_code(supplied),
        str(user.get("recovery_salt", "")),
        str(user.get("recovery_hash", "")),
    )

    release_until_raw = str(user.get("admin_reset_until", "") or "").strip()
    admin_release_ok = False
    if release_until_raw:
        try:
            release_until = datetime.fromisoformat(release_until_raw)
            admin_release_ok = datetime.now() <= release_until
        except Exception:
            admin_release_ok = False

    if not recovery_ok and not admin_release_ok:
        return False, (
            "Código de recuperação inválido. "
            "Se você perdeu o código, peça ao administrador para liberar a redefinição."
        )

    password_salt, password_hash = _password_hash(new_password)
    recovery_new = _new_recovery_code()
    recovery_salt, recovery_hash = _password_hash(
        _normalize_recovery_code(recovery_new)
    )

    user["password_salt"] = password_salt
    user["password_hash"] = password_hash
    user["recovery_salt"] = recovery_salt
    user["recovery_hash"] = recovery_hash
    user["password_changed_at"] = datetime.now().isoformat(timespec="seconds")
    user.pop("admin_reset_until", None)
    user.pop("admin_reset_authorized_at", None)
    user.pop("admin_reset_authorized_by", None)
    registry[key] = user

    ok, save_error = _write_registry(registry, sha=sha)
    if not ok:
        return False, save_error

    st.session_state["nexo_reset_recovery_code"] = recovery_new
    return True, None


def _admin_reset_status(user):
    raw = str(user.get("admin_reset_until", "") or "").strip()
    if not raw:
        return False, None
    try:
        until = datetime.fromisoformat(raw)
    except Exception:
        return False, None
    return datetime.now() <= until, until


def _set_admin_reset(username, enabled):
    registry, sha, error = _read_registry()
    if error:
        return False, error

    key, user = _find_registry_user(registry, username)
    if user is None:
        return False, (
            "Esse usuário ainda não está no cadastro novo. "
            "Ele precisa entrar uma vez com a senha atual para concluir a migração."
        )

    if enabled:
        now = datetime.now()
        user["admin_reset_authorized_at"] = now.isoformat(timespec="seconds")
        user["admin_reset_until"] = (
            now + timedelta(hours=24)
        ).isoformat(timespec="seconds")
        user["admin_reset_authorized_by"] = current_username()
    else:
        user.pop("admin_reset_authorized_at", None)
        user.pop("admin_reset_until", None)
        user.pop("admin_reset_authorized_by", None)

    registry[key] = user
    ok, save_error = _write_registry(registry, sha=sha)
    if not ok:
        return False, save_error
    return True, None




def is_legacy_owner(username=None):
    user = str(username if username is not None else current_username()).strip()
    if not user:
        return False

    explicit = str(_secret("NEXO_LEGACY_OWNER", "")).strip()
    if explicit:
        return hmac.compare_digest(user, explicit)

    simple_user = str(_secret("NEXO_LOGIN_USER", "")).strip()
    if simple_user:
        return hmac.compare_digest(user, simple_user)

    users, _ = _load_users()
    if len(users) == 1:
        only_user = next(iter(users))
        return hmac.compare_digest(user, only_user)

    return False


def render_user_admin():
    if not is_legacy_owner():
        st.error("Acesso restrito ao administrador.")
        return

    st.title("Usuários")
    st.caption(
        "Gerencie contas e libere redefinições de senha. "
        "A liberação administrativa expira em 24 horas e é consumida após a troca."
    )

    registry, _, error = _read_registry()
    if error:
        st.error(error)
        return

    legacy_users = _load_legacy_users()
    rows = []
    all_names = sorted(
        set(registry.keys()) | set(legacy_users.keys()),
        key=lambda value: value.casefold(),
    )

    for username in all_names:
        if username in registry:
            data = registry[username]
            active, until = _admin_reset_status(data)
            created = str(data.get("created_at", "") or "")
            created_label = created[:10] if created else "—"
            status = (
                f"Liberada até {until.strftime('%d/%m/%Y %H:%M')}"
                if active and until is not None
                else "Normal"
            )
            account_type = "Conta ativa"
            name = str(data.get("name", username))
        else:
            data = legacy_users[username]
            created_label = "—"
            status = "Aguardando primeiro acesso"
            account_type = "Conta antiga"
            name = str(data.get("name", username))

        rows.append(
            {
                "Nome": name,
                "Usuário": username,
                "Conta": account_type,
                "Criada em": created_label,
                "Redefinição": status,
            }
        )

    if not rows:
        st.info("Nenhuma conta cadastrada.")
        return

    st.dataframe(
        rows,
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("### Redefinição de senha")
    st.caption(
        "Use esta opção somente quando o usuário também perdeu o código de recuperação."
    )

    selected = st.selectbox(
        "Usuário",
        options=all_names,
        format_func=lambda username: (
            f"{registry.get(username, legacy_users.get(username, {})).get('name', username)}"
            f" — {username}"
        ),
        key="admin_user_selected",
    )

    selected_registry = registry.get(selected)
    if selected_registry is None:
        st.warning(
            "Essa conta ainda usa o login antigo. "
            "Ela precisa entrar uma vez com a senha atual antes de receber liberação administrativa."
        )
        return

    active, until = _admin_reset_status(selected_registry)
    if active and until is not None:
        st.info(
            "Redefinição liberada até "
            + until.strftime("%d/%m/%Y às %H:%M")
            + "."
        )

    left, right = st.columns(2)
    with left:
        if st.button(
            "Liberar redefinição por 24 horas",
            type="primary",
            use_container_width=True,
            disabled=active,
            key="admin_release_reset",
        ):
            ok, save_error = _set_admin_reset(selected, True)
            if ok:
                st.success(
                    "Liberação concluída. O usuário já pode definir uma nova senha "
                    "sem informar o código antigo."
                )
                st.rerun()
            else:
                st.error(save_error)

    with right:
        if st.button(
            "Cancelar liberação",
            use_container_width=True,
            disabled=not active,
            key="admin_cancel_reset",
        ):
            ok, save_error = _set_admin_reset(selected, False)
            if ok:
                st.success("Liberação cancelada.")
                st.rerun()
            else:
                st.error(save_error)


def _render_admin_sidebar():
    if not is_legacy_owner():
        return

    registry, _, error = _read_registry()
    if error:
        return

    legacy_users = _load_legacy_users()
    usernames = sorted(
        set(registry.keys()) | set(legacy_users.keys()),
        key=lambda value: value.casefold(),
    )
    if not usernames:
        return

    st.sidebar.markdown("---")
    with st.sidebar.expander("Gerenciar usuários", expanded=False):
        selected = st.selectbox(
            "Conta",
            options=usernames,
            format_func=lambda username: (
                f"{registry.get(username, legacy_users.get(username, {})).get('name', username)}"
                f" — {username}"
            ),
            key="sidebar_admin_user",
        )

        if selected not in registry:
            st.caption(
                "Conta antiga: precisa entrar uma vez com a senha atual antes "
                "da liberação administrativa."
            )
            return

        active, until = _admin_reset_status(registry[selected])
        if active and until is not None:
            st.caption(
                "Redefinição liberada até "
                + until.strftime("%d/%m/%Y às %H:%M")
            )

        if st.button(
            "Liberar redefinição",
            type="primary",
            use_container_width=True,
            disabled=active,
            key="sidebar_admin_release",
        ):
            ok, save_error = _set_admin_reset(selected, True)
            if ok:
                st.success("Redefinição liberada por 24 horas.")
                st.rerun()
            else:
                st.error(save_error)

        if st.button(
            "Cancelar liberação",
            use_container_width=True,
            disabled=not active,
            key="sidebar_admin_cancel",
        ):
            ok, save_error = _set_admin_reset(selected, False)
            if ok:
                st.success("Liberação cancelada.")
                st.rerun()
            else:
                st.error(save_error)


def _clear_session():
    for key in list(st.session_state.keys()):
        st.session_state.pop(key, None)


def _render_recovery_notice():
    recovery_code = st.session_state.get("nexo_new_recovery_code")
    if recovery_code:
        st.sidebar.markdown("---")
        st.sidebar.caption("Código de recuperação")
        st.sidebar.code(recovery_code)
        st.sidebar.caption(
            "Guarde este código em local seguro. Ele será necessário se você esquecer a senha."
        )
        if st.sidebar.button(
            "Já guardei",
            key="nexo_recovery_saved",
            use_container_width=True,
        ):
            st.session_state.pop("nexo_new_recovery_code", None)
            st.rerun()


def require_login():
    users, registry_error = _load_users()

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
                margin-top:4.5rem;
            }
            .nexo-login-subtitle {
                text-align:center;
                opacity:.62;
                margin-bottom:1.7rem;
            }
            div[data-testid="stTabs"] button {
                font-size:.92rem;
            }
            </style>
            <div class="nexo-login-title">NEXO</div>
            <div class="nexo-login-subtitle">Gestão • Planejamento • Inteligência</div>
            """,
            unsafe_allow_html=True,
        )

        left, center, right = st.columns([1.15, 1.35, 1.15])
        with center:
            with st.container(border=True):
                tab_login, tab_signup, tab_reset = st.tabs(
                    ["Entrar", "Criar conta", "Redefinir senha"]
                )

                with tab_login:
                    with st.form("nexo_login_form", clear_on_submit=False):
                        username = st.text_input(
                            "Usuário",
                            autocomplete="username",
                            key="login_username",
                        )
                        password = st.text_input(
                            "Senha",
                            type="password",
                            autocomplete="current-password",
                            key="login_password",
                        )
                        submitted = st.form_submit_button(
                            "Entrar",
                            type="primary",
                            use_container_width=True,
                        )

                    if submitted:
                        refreshed_users, _ = _load_users()
                        valid, selected_user, user = _valid_login(
                            username,
                            password,
                            refreshed_users,
                        )
                        if valid:
                            recovery_code = None
                            if user.get("source") == "legacy":
                                recovery_code, migration_error = _migrate_legacy_user(
                                    selected_user,
                                    user,
                                    password,
                                )
                                if migration_error:
                                    st.error(migration_error)
                                    st.stop()

                            selected_name = str(
                                user.get("name", selected_user)
                            ).strip() or selected_user
                            _clear_session()
                            st.session_state["nexo_authenticated"] = True
                            st.session_state["nexo_username"] = selected_user
                            st.session_state["nexo_user_name"] = selected_name
                            if recovery_code:
                                st.session_state[
                                    "nexo_new_recovery_code"
                                ] = recovery_code
                            st.rerun()
                        else:
                            st.error("Usuário ou senha incorretos.")

                with tab_signup:
                    st.caption(
                        "Cada conta possui seus próprios dados, pedidos, tarefas e preferências."
                    )
                    signup_code_required = str(
                        _secret("NEXO_SIGNUP_CODE", "")
                    ).strip()

                    with st.form("nexo_signup_form", clear_on_submit=False):
                        new_name = st.text_input(
                            "Nome",
                            key="signup_name",
                        )
                        new_username = st.text_input(
                            "Novo usuário",
                            key="signup_username",
                        )
                        new_password = st.text_input(
                            "Nova senha",
                            type="password",
                            key="signup_password",
                        )
                        new_confirm = st.text_input(
                            "Confirmar senha",
                            type="password",
                            key="signup_confirm",
                        )
                        access_code = ""
                        if signup_code_required:
                            access_code = st.text_input(
                                "Código de acesso",
                                type="password",
                                key="signup_access_code",
                            )

                        create = st.form_submit_button(
                            "Criar conta",
                            type="primary",
                            use_container_width=True,
                        )

                    if create:
                        errors = _validate_new_account(
                            new_name,
                            new_username,
                            new_password,
                            new_confirm,
                        )
                        if (
                            signup_code_required
                            and not hmac.compare_digest(
                                str(access_code),
                                signup_code_required,
                            )
                        ):
                            errors.append("Código de acesso inválido.")

                        if errors:
                            for error in errors:
                                st.error(error)
                        else:
                            ok, error, created_user, recovery_code = (
                                _create_registry_user(
                                    new_name,
                                    new_username,
                                    new_password,
                                )
                            )
                            if not ok:
                                st.error(error)
                            else:
                                _clear_session()
                                st.session_state["nexo_authenticated"] = True
                                st.session_state["nexo_username"] = created_user
                                st.session_state["nexo_user_name"] = (
                                    str(new_name).strip()
                                )
                                st.session_state[
                                    "nexo_new_recovery_code"
                                ] = recovery_code
                                st.rerun()

                with tab_reset:
                    st.caption(
                        "Use seu código de recuperação. Se você perdeu esse código, "
                        "o administrador pode liberar uma redefinição temporária."
                    )
                    reset_generated_code = st.session_state.get(
                        "nexo_reset_recovery_code"
                    )
                    if reset_generated_code:
                        st.success("Senha redefinida.")
                        st.caption("Novo código de recuperação")
                        st.code(reset_generated_code)
                        st.caption(
                            "Guarde este código. O código anterior foi invalidado."
                        )

                    with st.form("nexo_reset_form", clear_on_submit=False):
                        reset_username = st.text_input(
                            "Usuário",
                            key="reset_username",
                        )
                        recovery_code = st.text_input(
                            "Código de recuperação (opcional se o administrador liberou)",
                            type="password",
                            key="reset_recovery",
                        )
                        reset_password = st.text_input(
                            "Nova senha",
                            type="password",
                            key="reset_password",
                        )
                        reset_confirm = st.text_input(
                            "Confirmar nova senha",
                            type="password",
                            key="reset_confirm",
                        )
                        reset = st.form_submit_button(
                            "Redefinir senha",
                            type="primary",
                            use_container_width=True,
                        )

                    if reset:
                        reset_errors = []
                        if len(str(reset_password or "")) < 8:
                            reset_errors.append(
                                "A nova senha deve ter pelo menos 8 caracteres."
                            )
                        if str(reset_password or "") != str(reset_confirm or ""):
                            reset_errors.append("As senhas não conferem.")
                        if not str(reset_username or "").strip():
                            reset_errors.append("Informe o usuário.")
                        if reset_errors:
                            for error in reset_errors:
                                st.error(error)
                        else:
                            ok, error = _reset_password(
                                reset_username,
                                recovery_code,
                                reset_password,
                            )
                            if ok:
                                st.success(
                                    "Senha redefinida. Você já pode entrar com a nova senha."
                                )
                            else:
                                st.error(error)

                if registry_error:
                    st.caption(registry_error)

        st.stop()

    username = st.session_state.get("nexo_username", "")
    name = st.session_state.get("nexo_user_name", username)

    return {
        "authenticated": True,
        "configured": True,
        "username": username,
        "name": name,
    }


def render_sidebar_account_controls():
    if not st.session_state.get("nexo_authenticated"):
        return

    username = st.session_state.get("nexo_username", "")
    name = st.session_state.get("nexo_user_name", username)

    st.sidebar.markdown(
        '<div class="nexo-sidebar-spacer"></div>',
        unsafe_allow_html=True,
    )
    _render_recovery_notice()

    st.sidebar.markdown(
        f'<div class="nexo-sidebar-account">{name}</div>',
        unsafe_allow_html=True,
    )
    _render_admin_sidebar()

    if st.sidebar.button(
        "Sair",
        key="nexo_logout",
        use_container_width=True,
    ):
        _clear_session()
        st.rerun()

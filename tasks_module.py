import base64
import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import date, datetime

import pandas as pd
import streamlit as st


TASKS_FILE = "personal_tasks.json"
DEFAULT_GITHUB_REPO = "jvdntts-code/planejamento-pedidos"
DEFAULT_GITHUB_BRANCH = "main"

PRIORITIES = ["Alta", "Média", "Baixa"]
CATEGORIES = ["Compras", "Análise", "Fornecedor", "Pessoal", "Outro"]
STATUSES = ["Pendente", "Em andamento", "Concluída"]


def _secret(name, default=""):
    try:
        return st.secrets[name] if name in st.secrets else default
    except Exception:
        return default


def _settings():
    repo = str(_secret("GITHUB_REPO", DEFAULT_GITHUB_REPO))
    branch = str(_secret("GITHUB_BRANCH", DEFAULT_GITHUB_BRANCH))
    token = str(_secret("GITHUB_TOKEN", ""))
    return repo, branch, token


def _headers(token=""):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "planejamento-pedidos-streamlit",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _read_tasks():
    repo, branch, token = _settings()
    path = urllib.parse.quote(TASKS_FILE, safe="/")
    url = (
        f"https://api.github.com/repos/{repo}/contents/{path}"
        f"?ref={urllib.parse.quote(branch, safe='')}"
    )
    request = urllib.request.Request(url, headers=_headers(token), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = base64.b64decode(payload["content"]).decode("utf-8")
        data = json.loads(content)
        return data if isinstance(data, list) else [], None
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return [], None
        return [], f"Não foi possível carregar as tarefas (HTTP {exc.code})."
    except Exception as exc:
        return [], f"Não foi possível carregar as tarefas: {exc}"


def _save_tasks(tasks):
    repo, branch, token = _settings()
    if not token:
        return False, "Sem GITHUB_TOKEN: as tarefas ficam apenas nesta sessão."

    path = urllib.parse.quote(TASKS_FILE, safe="/")
    url = f"https://api.github.com/repos/{repo}/contents/{path}"

    sha = None
    get_url = f"{url}?ref={urllib.parse.quote(branch, safe='')}"
    request = urllib.request.Request(get_url, headers=_headers(token), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            existing = json.loads(response.read().decode("utf-8"))
            sha = existing.get("sha")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            return False, f"Não foi possível localizar o arquivo de tarefas (HTTP {exc.code})."
    except Exception as exc:
        return False, f"Não foi possível localizar o arquivo de tarefas: {exc}"

    content = json.dumps(tasks, ensure_ascii=False, indent=2)
    payload = {
        "message": "Atualiza minhas tarefas",
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    put = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={**_headers(token), "Content-Type": "application/json"},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(put, timeout=15) as response:
            response.read()
        return True, "Tarefas salvas."
    except urllib.error.HTTPError as exc:
        return False, f"Não foi possível salvar as tarefas (HTTP {exc.code})."
    except Exception as exc:
        return False, f"Não foi possível salvar as tarefas: {exc}"


def _load_state():
    if "personal_tasks_loaded" not in st.session_state:
        tasks, error = _read_tasks()
        st.session_state["personal_tasks"] = tasks
        st.session_state["personal_tasks_loaded"] = True
        if error:
            st.session_state["tasks_feedback"] = error
    return st.session_state.get("personal_tasks", [])


def _persist(tasks, success_text="Tarefas atualizadas."):
    st.session_state["personal_tasks"] = tasks
    ok, message = _save_tasks(tasks)
    if ok:
        st.session_state["tasks_feedback"] = success_text
    else:
        st.session_state["tasks_feedback"] = message
    return ok


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return None


def _priority_rank(priority):
    return {"Alta": 0, "Média": 1, "Baixa": 2}.get(priority, 9)


def _build_checklist(text, existing=None):
    lines = [
        line.strip()
        for line in str(text or "").splitlines()
        if line.strip()
    ]

    existing = existing or []
    existing_by_text = {}
    for item in existing:
        if isinstance(item, dict):
            key = str(item.get("text", "")).strip().casefold()
            if key:
                existing_by_text.setdefault(key, []).append(item)

    checklist = []
    for line in lines:
        key = line.casefold()
        preserved = None
        if existing_by_text.get(key):
            preserved = existing_by_text[key].pop(0)

        checklist.append(
            {
                "id": (
                    preserved.get("id")
                    if preserved and preserved.get("id")
                    else uuid.uuid4().hex
                ),
                "text": line,
                "done": bool(preserved.get("done", False)) if preserved else False,
            }
        )
    return checklist


def _checklist_text(task):
    return "\n".join(
        str(item.get("text", "")).strip()
        for item in task.get("checklist", [])
        if isinstance(item, dict) and str(item.get("text", "")).strip()
    )


def _task_status_label(task):
    due = _parse_date(task.get("due_date"))
    today = date.today()
    if task.get("status") == "Concluída":
        return "Concluída"
    if due and due < today:
        return "Atrasada"
    if due == today:
        return "Hoje"
    return task.get("status", "Pendente")


def render_tasks():
    tasks = _load_state()
    today = date.today()

    st.title("✅ Minhas Tarefas")
    st.caption("Sua lista pessoal de pendências, prazos e acompanhamentos.")

    _, _, token = _settings()
    if token:
        st.success("☁️ Salvamento permanente habilitado.")
    else:
        st.warning(
            "As tarefas estão funcionando, mas sem GITHUB_TOKEN elas não ficam salvas após reiniciar o app."
        )

    feedback = st.session_state.get("tasks_feedback", "")
    if feedback:
        if "salv" in feedback.lower() or "atualiz" in feedback.lower() or "conclu" in feedback.lower():
            st.success(feedback)
        else:
            st.info(feedback)

    pending_count = sum(1 for t in tasks if t.get("status") != "Concluída")
    today_count = sum(
        1 for t in tasks
        if t.get("status") != "Concluída" and _parse_date(t.get("due_date")) == today
    )
    overdue_count = sum(
        1 for t in tasks
        if t.get("status") != "Concluída"
        and _parse_date(t.get("due_date"))
        and _parse_date(t.get("due_date")) < today
    )
    done_count = sum(1 for t in tasks if t.get("status") == "Concluída")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pendentes", pending_count)
    c2.metric("Hoje", today_count)
    c3.metric("Atrasadas", overdue_count)
    c4.metric("Concluídas", done_count)

    with st.expander("➕ Nova tarefa", expanded=not tasks):
        with st.form("new_task_form", clear_on_submit=True):
            title = st.text_input("Título da tarefa")
            description = st.text_area(
                "Descrição / observação",
                placeholder="Ex.: conferir pendências antes de fechar o pedido.",
            )
            checklist_text = st.text_area(
                "Checklist (opcional)",
                placeholder=(
                    "Digite um item por linha.\n"
                    "Ex.:\n"
                    "Conferir pendências\n"
                    "Gerar pedido\n"
                    "Enviar ao fornecedor"
                ),
                help="Cada linha vira um item marcável dentro da tarefa.",
            )
            f1, f2, f3 = st.columns(3)
            due_date = f1.date_input("Prazo", value=today)
            priority = f2.selectbox("Prioridade", PRIORITIES)
            category = f3.selectbox("Categoria", CATEGORIES)
            status = st.selectbox("Status", STATUSES, index=0)
            submitted = st.form_submit_button("Adicionar tarefa", type="primary")

        if submitted:
            if not title.strip():
                st.error("Informe o título da tarefa.")
            else:
                now = datetime.now().isoformat(timespec="seconds")
                new_task = {
                    "id": uuid.uuid4().hex,
                    "title": title.strip(),
                    "description": description.strip(),
                    "due_date": due_date.isoformat() if due_date else "",
                    "priority": priority,
                    "category": category,
                    "status": status,
                    "checklist": _build_checklist(checklist_text),
                    "created_at": now,
                    "completed_at": now if status == "Concluída" else "",
                }
                tasks = [new_task] + tasks
                _persist(tasks, "Tarefa adicionada e salva.")
                st.rerun()

    st.markdown("### Lista de tarefas")

    f1, f2, f3 = st.columns([1.2, 1.1, 1])
    view = f1.radio(
        "Visualizar",
        ["Pendentes", "Hoje", "Esta semana", "Atrasadas", "Concluídas", "Todas"],
        horizontal=False,
    )
    category_filter = f2.multiselect(
        "Categoria",
        CATEGORIES,
        default=[],
        placeholder="Todas",
    )
    priority_filter = f3.multiselect(
        "Prioridade",
        PRIORITIES,
        default=[],
        placeholder="Todas",
    )

    filtered = []
    for task in tasks:
        due = _parse_date(task.get("due_date"))
        status = task.get("status", "Pendente")

        include = True
        if view == "Pendentes":
            include = status != "Concluída"
        elif view == "Hoje":
            include = status != "Concluída" and due == today
        elif view == "Esta semana":
            include = (
                status != "Concluída"
                and due is not None
                and 0 <= (due - today).days <= 7
            )
        elif view == "Atrasadas":
            include = status != "Concluída" and due is not None and due < today
        elif view == "Concluídas":
            include = status == "Concluída"

        if category_filter:
            include = include and task.get("category") in category_filter
        if priority_filter:
            include = include and task.get("priority") in priority_filter

        if include:
            filtered.append(task)

    filtered.sort(
        key=lambda t: (
            t.get("status") == "Concluída",
            _parse_date(t.get("due_date")) or date.max,
            _priority_rank(t.get("priority")),
            t.get("title", "").lower(),
        )
    )

    if not filtered:
        st.info("Nenhuma tarefa encontrada neste filtro.")
    else:
        for task in filtered:
            due = _parse_date(task.get("due_date"))
            status_label = _task_status_label(task)

            if status_label == "Atrasada":
                icon = "🔴"
            elif status_label == "Hoje":
                icon = "🟠"
            elif task.get("status") == "Concluída":
                icon = "✅"
            elif task.get("priority") == "Alta":
                icon = "🔺"
            else:
                icon = "⬜"

            title_text = task.get("title", "Sem título")
            with st.container(border=True):
                top1, top2 = st.columns([4, 1])
                top1.markdown(f"#### {icon} {title_text}")
                top2.markdown(f"**{status_label}**")

                meta = []
                if due:
                    meta.append(f"📅 {due.strftime('%d/%m/%Y')}")
                meta.append(f"⚡ {task.get('priority', 'Média')}")
                meta.append(f"🏷️ {task.get('category', 'Outro')}")
                meta.append(f"📌 {task.get('status', 'Pendente')}")
                st.caption("  •  ".join(meta))

                if task.get("description"):
                    st.write(task["description"])

                checklist = [
                    item
                    for item in task.get("checklist", [])
                    if isinstance(item, dict) and item.get("text")
                ]
                if checklist:
                    completed_checklist = sum(
                        1 for item in checklist if item.get("done")
                    )
                    st.markdown(
                        f"**☑️ Checklist {completed_checklist}/{len(checklist)}**"
                    )
                    progress_value = (
                        completed_checklist / len(checklist)
                        if checklist
                        else 0
                    )
                    st.progress(progress_value)

                    checklist_changed = False
                    for checklist_item in checklist:
                        checklist_id = checklist_item.get("id") or uuid.uuid4().hex
                        checklist_item["id"] = checklist_id
                        checked = st.checkbox(
                            checklist_item.get("text", ""),
                            value=bool(checklist_item.get("done", False)),
                            key=f"check_{task['id']}_{checklist_id}",
                        )
                        if checked != bool(checklist_item.get("done", False)):
                            checklist_item["done"] = checked
                            checklist_changed = True

                    if checklist_changed:
                        for item in tasks:
                            if item["id"] == task["id"]:
                                item["checklist"] = checklist
                                break
                        _persist(tasks, "Checklist atualizado e salvo.")
                        st.rerun()

                a1, a2, a3, a4 = st.columns([1, 1, 1, 1])
                task_id = task["id"]

                if task.get("status") != "Concluída":
                    if a1.button("✅ Concluir", key=f"done_{task_id}", use_container_width=True):
                        for item in tasks:
                            if item["id"] == task_id:
                                item["status"] = "Concluída"
                                item["completed_at"] = datetime.now().isoformat(timespec="seconds")
                        _persist(tasks, "Tarefa concluída e salva.")
                        st.rerun()

                    if a2.button("▶️ Em andamento", key=f"progress_{task_id}", use_container_width=True):
                        for item in tasks:
                            if item["id"] == task_id:
                                item["status"] = "Em andamento"
                                item["completed_at"] = ""
                        _persist(tasks, "Status atualizado e salvo.")
                        st.rerun()
                else:
                    if a1.button("↩️ Reabrir", key=f"reopen_{task_id}", use_container_width=True):
                        for item in tasks:
                            if item["id"] == task_id:
                                item["status"] = "Pendente"
                                item["completed_at"] = ""
                        _persist(tasks, "Tarefa reaberta e salva.")
                        st.rerun()

                edit_key = f"edit_open_{task_id}"
                if a3.button("✏️ Editar", key=f"edit_{task_id}", use_container_width=True):
                    st.session_state[edit_key] = not st.session_state.get(edit_key, False)

                if a4.button("🗑️ Excluir", key=f"delete_{task_id}", use_container_width=True):
                    st.session_state[f"confirm_delete_{task_id}"] = True

                if st.session_state.get(f"confirm_delete_{task_id}", False):
                    st.warning("Excluir esta tarefa definitivamente?")
                    d1, d2 = st.columns(2)
                    if d1.button("Sim, excluir", key=f"delete_yes_{task_id}", type="primary"):
                        tasks = [t for t in tasks if t["id"] != task_id]
                        _persist(tasks, "Tarefa excluída e alteração salva.")
                        st.session_state.pop(f"confirm_delete_{task_id}", None)
                        st.rerun()
                    if d2.button("Cancelar", key=f"delete_no_{task_id}"):
                        st.session_state.pop(f"confirm_delete_{task_id}", None)
                        st.rerun()

                if st.session_state.get(edit_key, False):
                    with st.form(f"edit_form_{task_id}"):
                        new_title = st.text_input("Título", value=task.get("title", ""))
                        new_desc = st.text_area(
                            "Observação",
                            value=task.get("description", ""),
                        )
                        new_checklist_text = st.text_area(
                            "Checklist (um item por linha)",
                            value=_checklist_text(task),
                            help=(
                                "Adicione, remova ou altere os itens. "
                                "Itens já marcados mantêm o status quando o texto permanece igual."
                            ),
                        )
                        e1, e2, e3 = st.columns(3)
                        new_due = e1.date_input(
                            "Prazo",
                            value=due or today,
                            key=f"edit_due_{task_id}",
                        )
                        current_priority = task.get("priority", "Média")
                        new_priority = e2.selectbox(
                            "Prioridade",
                            PRIORITIES,
                            index=PRIORITIES.index(current_priority)
                            if current_priority in PRIORITIES else 1,
                        )
                        current_category = task.get("category", "Outro")
                        new_category = e3.selectbox(
                            "Categoria",
                            CATEGORIES,
                            index=CATEGORIES.index(current_category)
                            if current_category in CATEGORIES else len(CATEGORIES) - 1,
                        )
                        current_status = task.get("status", "Pendente")
                        new_status = st.selectbox(
                            "Status",
                            STATUSES,
                            index=STATUSES.index(current_status)
                            if current_status in STATUSES else 0,
                        )
                        save_edit = st.form_submit_button("Salvar alterações", type="primary")

                    if save_edit:
                        for item in tasks:
                            if item["id"] == task_id:
                                item["title"] = new_title.strip() or item["title"]
                                item["description"] = new_desc.strip()
                                item["due_date"] = new_due.isoformat() if new_due else ""
                                item["priority"] = new_priority
                                item["category"] = new_category
                                item["status"] = new_status
                                item["checklist"] = _build_checklist(
                                    new_checklist_text,
                                    existing=item.get("checklist", []),
                                )
                                item["completed_at"] = (
                                    datetime.now().isoformat(timespec="seconds")
                                    if new_status == "Concluída"
                                    else ""
                                )
                        _persist(tasks, "Tarefa editada e salva.")
                        st.session_state[edit_key] = False
                        st.rerun()

    if tasks:
        export_rows = []
        for task in tasks:
            export_rows.append(
                {
                    "Tarefa": task.get("title", ""),
                    "Descrição": task.get("description", ""),
                    "Prazo": task.get("due_date", ""),
                    "Prioridade": task.get("priority", ""),
                    "Categoria": task.get("category", ""),
                    "Status": task.get("status", ""),
                    "Checklist": " | ".join(
                        (
                            ("[x] " if item.get("done") else "[ ] ")
                            + str(item.get("text", ""))
                        )
                        for item in task.get("checklist", [])
                        if isinstance(item, dict) and item.get("text")
                    ),
                    "Situação": _task_status_label(task),
                    "Criada em": task.get("created_at", ""),
                    "Concluída em": task.get("completed_at", ""),
                }
            )
        df = pd.DataFrame(export_rows)
        csv = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "⬇️ Exportar tarefas (.csv)",
            csv,
            file_name="minhas_tarefas.csv",
            mime="text/csv",
        )

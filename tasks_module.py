import base64
import copy
import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from auth_module import current_username, is_legacy_owner, user_storage_prefix


LEGACY_TASKS_FILE = "legacy/personal_tasks.json"
DEFAULT_GITHUB_REPO = "jvdntts-code/planejamento-pedidos"
DEFAULT_GITHUB_BRANCH = "main"


def _tasks_file():
    return f"{user_storage_prefix()}/tasks/personal_tasks.json"

PRIORITIES = ["Alta", "Média", "Baixa"]
AREAS = ["Trabalho", "Faculdade", "Pessoal"]
CATEGORIES = [
    "Compras", "Análise", "Fornecedor", "Reunião", "Prazo",
    "Faculdade", "Pessoal", "Outro",
]
STATUSES = ["Pendente", "Em andamento", "Concluída"]
REMINDER_OPTIONS = {
    "No horário": 0,
    "1 hora antes": 60,
    "3 horas antes": 180,
    "1 dia antes": 1440,
    "3 dias antes": 4320,
    "7 dias antes": 10080,
}
APP_TIMEZONE = ZoneInfo("America/Sao_Paulo")


def _secret(name, default=""):
    try:
        return st.secrets[name] if name in st.secrets else default
    except Exception:
        return default


def _settings():
    repo = str(
        _secret(
            "GITHUB_DATA_REPO",
            _secret("GITHUB_REPO", DEFAULT_GITHUB_REPO),
        )
    )
    branch = str(
        _secret(
            "GITHUB_DATA_BRANCH",
            _secret("GITHUB_BRANCH", DEFAULT_GITHUB_BRANCH),
        )
    )
    token = str(_secret("GITHUB_TOKEN", ""))
    return repo, branch, token


def _legacy_settings():
    repo = str(
        _secret(
            "GITHUB_DATA_REPO",
            _secret("GITHUB_REPO", DEFAULT_GITHUB_REPO),
        )
    )
    branch = str(
        _secret(
            "GITHUB_DATA_BRANCH",
            _secret("GITHUB_BRANCH", DEFAULT_GITHUB_BRANCH),
        )
    )
    token = str(_secret("GITHUB_TOKEN", ""))
    return repo, branch, token


def _read_tasks_from(repo, branch, token, file_path):
    path = urllib.parse.quote(file_path, safe="/")
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
        return (data if isinstance(data, list) else []), None, True
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return [], None, False
        return [], ("Token do GitHub inválido, revogado ou sem acesso ao repositório. Atualize GITHUB_TOKEN nos Secrets do Streamlit (HTTP 401)." if exc.code == 401 else f"Não foi possível carregar as tarefas (HTTP {exc.code})."), False
    except Exception as exc:
        return [], f"Não foi possível carregar as tarefas: {exc}", False


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
    tasks, error, found = _read_tasks_from(
        repo,
        branch,
        token,
        _tasks_file(),
    )
    if error or found:
        return tasks, error

    # Migração transparente dos dados antigos para o primeiro/atual proprietário.
    if is_legacy_owner():
        legacy_repo, legacy_branch, legacy_token = _legacy_settings()
        legacy_tasks, legacy_error, legacy_found = _read_tasks_from(
            legacy_repo,
            legacy_branch,
            legacy_token,
            LEGACY_TASKS_FILE,
        )
        if legacy_error:
            return [], legacy_error
        if legacy_found:
            ok, message = _save_tasks(legacy_tasks)
            if ok:
                return legacy_tasks, None
            return legacy_tasks, (
                "Tarefas antigas carregadas, mas ainda não foi possível migrá-las: "
                + message
            )

    return [], None


def _save_tasks(tasks):
    repo, branch, token = _settings()
    if not token:
        return False, "Sem GITHUB_TOKEN: as tarefas ficam apenas nesta sessão."

    path = urllib.parse.quote(_tasks_file(), safe="/")
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
            return False, ("Token do GitHub inválido, revogado ou sem acesso ao repositório. Atualize GITHUB_TOKEN nos Secrets do Streamlit (HTTP 401)." if exc.code == 401 else f"Não foi possível localizar o arquivo de tarefas (HTTP {exc.code}).")
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
        return False, ("Token do GitHub inválido, revogado ou sem permissão para gravar no repositório. Atualize GITHUB_TOKEN nos Secrets do Streamlit (HTTP 401)." if exc.code == 401 else f"Não foi possível salvar as tarefas (HTTP {exc.code}).")
    except Exception as exc:
        return False, f"Não foi possível salvar as tarefas: {exc}"


def _load_state():
    if "personal_tasks_loaded" not in st.session_state:
        tasks, error = _read_tasks()
        st.session_state["personal_tasks"] = tasks
        st.session_state["personal_tasks_loaded"] = not bool(error)
        st.session_state["tasks_load_error"] = error or ""
        if error:
            st.session_state["tasks_feedback"] = error
    return st.session_state.get("personal_tasks", [])


def _persist(tasks, success_text="Tarefas atualizadas."):
    ok, message = _save_tasks(tasks)
    if ok:
        st.session_state["personal_tasks"] = copy.deepcopy(tasks)
    st.session_state["tasks_save_failed"] = not ok
    if ok:
        st.session_state["tasks_feedback"] = success_text
    else:
        st.session_state["tasks_feedback"] = message
    return ok


def _now():
    return datetime.now(APP_TIMEZONE).replace(tzinfo=None)


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except Exception:
        return None


def _parse_time(value):
    if not value:
        return time(23, 59)
    try:
        return time.fromisoformat(str(value))
    except Exception:
        return time(23, 59)


def _task_due_datetime(task):
    due_date = _parse_date(task.get("due_date"))
    if due_date is None:
        return None
    return datetime.combine(due_date, _parse_time(task.get("due_time")))


def _priority_rank(priority):
    return {"Alta": 0, "Média": 1, "Baixa": 2}.get(priority, 9)


def _task_area(task):
    area = str(task.get("area", "") or "").strip()
    if area in AREAS:
        return area
    category = str(task.get("category", "") or "")
    if category == "Pessoal":
        return "Pessoal"
    if category == "Faculdade":
        return "Faculdade"
    return "Trabalho"


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


def _reminder_minutes(task):
    values = task.get("reminder_minutes", [])
    if isinstance(values, (int, float, str)):
        values = [values]
    cleaned = []
    for value in values or []:
        try:
            cleaned.append(int(value))
        except Exception:
            continue
    return sorted(set(cleaned), reverse=True)


def _reminder_labels(task):
    reverse = {minutes: label for label, minutes in REMINDER_OPTIONS.items()}
    return [reverse[m] for m in _reminder_minutes(task) if m in reverse]


def _task_status_label(task, now=None):
    now = now or _now()
    due = _task_due_datetime(task)
    if task.get("status") == "Concluída":
        return "Concluída"
    if due and due < now:
        return "Atrasada"
    if due and due.date() == now.date():
        return "Hoje"
    if due and now < due <= now + timedelta(hours=24):
        return "Próximas 24h"
    return task.get("status", "Pendente")


def _reminder_is_active(task, now=None):
    now = now or _now()
    if task.get("status") == "Concluída":
        return False

    due = _task_due_datetime(task)
    if due is None:
        return False

    snooze_raw = str(task.get("snooze_until", "") or "").strip()
    if snooze_raw:
        try:
            snooze_until = datetime.fromisoformat(snooze_raw)
            if now < snooze_until:
                return False
        except Exception:
            pass

    if due < now:
        return True

    reminders = _reminder_minutes(task)
    if not reminders:
        return False

    return any(now >= due - timedelta(minutes=minutes) for minutes in reminders)


def _format_due(task):
    due = _task_due_datetime(task)
    if due is None:
        return "Sem prazo"
    return due.strftime("%d/%m/%Y às %H:%M")


def _set_task_status(tasks, task_id, status):
    for item in tasks:
        if item.get("id") == task_id:
            item["status"] = status
            item["completed_at"] = (
                _now().isoformat(timespec="seconds")
                if status == "Concluída"
                else ""
            )
            if status == "Concluída":
                item["snooze_until"] = ""
            break


def _render_active_reminders(tasks, now):
    active = [
        task for task in tasks
        if _reminder_is_active(task, now)
    ]
    active.sort(
        key=lambda task: (
            _task_due_datetime(task) or datetime.max,
            _priority_rank(task.get("priority")),
        )
    )

    if not active:
        return

    st.markdown("### Lembretes")
    st.caption(
        "Prazos que já chegaram ao momento configurado para aviso."
    )

    for task in active[:8]:
        due = _task_due_datetime(task)
        overdue = bool(due and due < now)
        area = _task_area(task)
        message = (
            f"{task.get('title', 'Sem título')} — {_format_due(task)} — {area}"
        )
        if overdue:
            st.error("ATRASADA: " + message)
        else:
            st.warning(message)

        b1, b2 = st.columns([1, 1])
        task_id = task.get("id")
        if b1.button(
            "Concluir",
            key=f"reminder_done_{task_id}",
            use_container_width=True,
        ):
            _set_task_status(tasks, task_id, "Concluída")
            _persist(tasks, "Tarefa concluída e salva.")
            st.rerun()

        if b2.button(
            "Adiar lembrete por 1 hora",
            key=f"reminder_snooze_{task_id}",
            use_container_width=True,
        ):
            for item in tasks:
                if item.get("id") == task_id:
                    item["snooze_until"] = (
                        now + timedelta(hours=1)
                    ).isoformat(timespec="minutes")
                    break
            _persist(tasks, "Lembrete adiado por 1 hora.")
            st.rerun()


def render_tasks():
    if not is_legacy_owner():
        st.error("Esta área é privada e está disponível apenas no seu login.")
        return

    tasks = copy.deepcopy(_load_state())
    now = _now()
    today = now.date()

    heading, refresh = st.columns([4, 1])
    heading.title("Minhas Tarefas")
    if refresh.button("Atualizar tarefas", use_container_width=True):
        st.session_state.pop("personal_tasks_loaded", None)
        st.rerun()
    if st.session_state.get("tasks_load_error"):
        st.error(st.session_state["tasks_load_error"])
        st.caption("Corrija a conexão e clique em Atualizar tarefas para carregar sua agenda.")
        return
    st.caption(
        "Organize trabalho, faculdade e vida pessoal com prazos, Checklist e lembretes."
    )

    _, _, token = _settings()
    if not token:
        st.warning(
            "Sem GITHUB_TOKEN, as tarefas não ficam salvas após reiniciar o app."
        )

    feedback = st.session_state.pop("tasks_feedback", "")
    if feedback:
        if st.session_state.get("tasks_save_failed"):
            st.error(feedback)
        elif any(word in feedback.lower() for word in ("salv", "atualiz", "conclu", "adicion")):
            st.success(feedback)
        else:
            st.info(feedback)

    pending_tasks = [
        task for task in tasks if task.get("status") != "Concluída"
    ]
    overdue_count = sum(
        1 for task in pending_tasks
        if (_task_due_datetime(task) is not None and _task_due_datetime(task) < now)
    )
    today_count = sum(
        1 for task in pending_tasks
        if (_task_due_datetime(task) is not None and _task_due_datetime(task).date() == today)
    )
    next_24h_count = sum(
        1 for task in pending_tasks
        if (
            _task_due_datetime(task) is not None
            and now < _task_due_datetime(task) <= now + timedelta(hours=24)
        )
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pendentes", len(pending_tasks))
    c2.metric("Hoje", today_count)
    c3.metric("Próximas 24h", next_24h_count)
    c4.metric("Atrasadas", overdue_count)

    day_tasks = [t for t in tasks if _parse_date(t.get("due_date")) == today]
    day_done = sum(t.get("status") == "Concluída" for t in day_tasks)
    if day_tasks:
        st.progress(day_done / len(day_tasks), text=f"Hoje: {day_done} de {len(day_tasks)} tarefas concluídas")
    in_progress = [t for t in pending_tasks if t.get("status") == "Em andamento"]
    if in_progress:
        st.info("Em foco: " + " • ".join(t.get("title", "") for t in in_progress[:3]))
    active_count = sum(_reminder_is_active(t, now) for t in tasks)
    if active_count:
        with st.expander(f"Lembretes e atrasos ({active_count})", expanded=False):
            _render_active_reminders(tasks, now)

    with st.expander("Adicionar tarefa rápida", expanded=False):
        with st.form("quick_task", clear_on_submit=True):
            quick_title = st.text_input("O que precisa fazer?", key="quick_title")
            q1, q2, q3 = st.columns(3)
            quick_date = q1.date_input("Dia", value=today, key="quick_date")
            quick_time = q2.time_input("Até que horas?", value=time(18), key="quick_time")
            quick_priority = q3.selectbox("Prioridade", PRIORITIES, index=1, key="quick_priority")
            quick_submit = st.form_submit_button("Adicionar", use_container_width=True)
        if quick_submit:
            if not quick_title.strip():
                st.error("Informe o título da tarefa.")
            else:
                tasks.insert(0, {
                    "id": uuid.uuid4().hex, "title": quick_title.strip(),
                    "description": "", "area": "Trabalho", "category": "Outro",
                    "due_date": quick_date.isoformat(), "due_time": quick_time.strftime("%H:%M"),
                    "priority": quick_priority, "status": "Pendente", "checklist": [],
                    "reminder_minutes": [], "snooze_until": "",
                    "created_at": now.isoformat(timespec="seconds"), "completed_at": "",
                })
                _persist(tasks, "Tarefa adicionada e salva.")
                st.rerun()

    with st.expander("Nova tarefa com detalhes e checklist", expanded=False):
        with st.form("new_task_form", clear_on_submit=True):
            title = st.text_input(
                "Título da tarefa",
                placeholder="Ex.: Entregar atividade da faculdade",
            )
            n1, n2 = st.columns([1, 2])
            area = n1.selectbox("Área", AREAS)
            category = n2.selectbox("Categoria", CATEGORIES)

            description = st.text_area(
                "Descrição / observação",
                placeholder="Inclua instruções, links, observações ou detalhes importantes.",
            )
            checklist_text = st.text_area(
                "Checklist (opcional)",
                placeholder=(
                    "Um item por linha.\n"
                    "Ex.:\n"
                    "Revisar conteúdo\n"
                    "Finalizar arquivo\n"
                    "Enviar atividade"
                ),
            )

            d1, d2, d3 = st.columns(3)
            due_date = d1.date_input("Data do prazo", value=today)
            due_time = d2.time_input(
                "Hora do prazo",
                value=time(23, 59),
                step=900,
            )
            priority = d3.selectbox("Prioridade", PRIORITIES)

            reminder_labels = st.multiselect(
                "Lembretes",
                list(REMINDER_OPTIONS.keys()),
                default=["1 dia antes", "1 hora antes"],
                help=(
                    "Os avisos aparecem dentro do NEXO quando você entrar. "
                    "Você pode escolher mais de um momento de aviso."
                ),
            )
            status = st.selectbox("Situação", STATUSES, index=0)
            submitted = st.form_submit_button(
                "Adicionar tarefa",
                type="primary",
                use_container_width=True,
            )

        if submitted:
            if not title.strip():
                st.error("Informe o título da tarefa.")
            else:
                created_at = now.isoformat(timespec="seconds")
                new_task = {
                    "id": uuid.uuid4().hex,
                    "title": title.strip(),
                    "description": description.strip(),
                    "area": area,
                    "category": category,
                    "due_date": due_date.isoformat() if due_date else "",
                    "due_time": due_time.strftime("%H:%M") if due_time else "23:59",
                    "priority": priority,
                    "status": status,
                    "reminder_minutes": [
                        REMINDER_OPTIONS[label]
                        for label in reminder_labels
                        if label in REMINDER_OPTIONS
                    ],
                    "snooze_until": "",
                    "checklist": _build_checklist(checklist_text),
                    "created_at": created_at,
                    "completed_at": (
                        created_at if status == "Concluída" else ""
                    ),
                }
                tasks = [new_task] + tasks
                _persist(tasks, "Tarefa adicionada e salva.")
                st.rerun()

    st.markdown("### Minhas tarefas")

    f1, f2, f3 = st.columns([1.4, 1, 1])
    view = f1.selectbox(
        "Visualizar",
        [
            "Hoje",
            "Pendentes",
            "Em andamento",
            "Data específica",
            "Próximas 24h",
            "Próximos 7 dias",
            "Atrasadas",
            "Concluídas",
            "Todas",
        ],
    )
    area_filter = f2.multiselect(
        "Área",
        AREAS,
        placeholder="Todas",
    )
    priority_filter = f3.multiselect(
        "Prioridade",
        PRIORITIES,
        placeholder="Todas",
    )

    search = st.text_input("Buscar tarefa", placeholder="Título, observação ou item do checklist", key="tasks_search")
    selected_day = st.date_input("Dia da agenda", value=today, key="tasks_selected_day") if view == "Data específica" else today
    sort_order = st.selectbox("Ordenar por", ["Horário / prazo", "Prioridade", "Situação"], key="tasks_sort")

    filtered = []
    for task in tasks:
        due = _task_due_datetime(task)
        status = task.get("status", "Pendente")
        include = True

        if view == "Em andamento":
            include = status == "Em andamento"
        elif view == "Data específica":
            include = due is not None and due.date() == selected_day
        elif view == "Pendentes":
            include = status != "Concluída"
        elif view == "Hoje":
            include = (
                status != "Concluída"
                and due is not None
                and due.date() == today
            )
        elif view == "Próximas 24h":
            include = (
                status != "Concluída"
                and due is not None
                and now <= due <= now + timedelta(hours=24)
            )
        elif view == "Próximos 7 dias":
            include = (
                status != "Concluída"
                and due is not None
                and now <= due <= now + timedelta(days=7)
            )
        elif view == "Atrasadas":
            include = (
                status != "Concluída"
                and due is not None
                and due < now
            )
        elif view == "Concluídas":
            include = status == "Concluída"

        if area_filter:
            include = include and _task_area(task) in area_filter
        if priority_filter:
            include = include and task.get("priority") in priority_filter

        if search.strip():
            haystack = " ".join([str(task.get("title", "")), str(task.get("description", "")), _checklist_text(task)]).casefold()
            include = include and search.strip().casefold() in haystack
        if include:
            filtered.append(task)

    filtered.sort(
        key=lambda task: (
            task.get("status") == "Concluída",
            _task_due_datetime(task) or datetime.max,
            _priority_rank(task.get("priority")),
            str(task.get("title", "")).casefold(),
        )
    )

    if sort_order == "Prioridade":
        filtered.sort(key=lambda t: (t.get("status") == "Concluída", _priority_rank(t.get("priority")), _task_due_datetime(t) or datetime.max))
    elif sort_order == "Situação":
        filtered.sort(key=lambda t: (STATUSES.index(t.get("status")) if t.get("status") in STATUSES else 0, _task_due_datetime(t) or datetime.max))
    st.caption(f"{len(filtered)} tarefa(s) nesta visualização • Use Atualizar tarefas para buscar alterações salvas fora desta sessão.")

    if not filtered:
        st.info("Nenhuma tarefa encontrada neste filtro.")
    else:
        for task in filtered:
            task_id = task.get("id")
            status_label = _task_status_label(task, now)
            area = _task_area(task)

            with st.container(border=True):
                top1, top2 = st.columns([4, 1])
                top1.markdown(f"#### {task.get('title', 'Sem título')}")
                top2.markdown(f"**{status_label}**")

                meta = [
                    f"Área: {area}",
                    f"Prazo: {_format_due(task)}",
                    f"Prioridade: {task.get('priority', 'Média')}",
                    f"Categoria: {task.get('category', 'Outro')}",
                    f"Situação: {task.get('status', 'Pendente')}",
                ]
                reminders = _reminder_labels(task)
                if reminders:
                    meta.append("Lembretes: " + ", ".join(reminders))
                st.caption("  •  ".join(meta))

                if task.get("description"):
                    with st.expander("Observações / programação", expanded=False):
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
                        f"**Checklist {completed_checklist}/{len(checklist)}**"
                    )
                    st.progress(
                        completed_checklist / len(checklist)
                        if checklist else 0
                    )

                    checklist_changed = False
                    for checklist_item in checklist:
                        checklist_id = checklist_item.get("id") or uuid.uuid4().hex
                        checklist_item["id"] = checklist_id
                        checked = st.checkbox(
                            checklist_item.get("text", ""),
                            value=bool(checklist_item.get("done", False)),
                            key=f"check_{task_id}_{checklist_id}",
                        )
                        if checked != bool(checklist_item.get("done", False)):
                            checklist_item["done"] = checked
                            checklist_changed = True

                    if checklist_changed:
                        for item in tasks:
                            if item.get("id") == task_id:
                                item["checklist"] = checklist
                                break
                        _persist(tasks, "Checklist atualizado e salvo.")
                        st.rerun()

                a1, a2, a3, a4 = st.columns(4)

                if task.get("status") != "Concluída":
                    if a1.button(
                        "Concluir",
                        key=f"done_{task_id}",
                        use_container_width=True,
                    ):
                        _set_task_status(tasks, task_id, "Concluída")
                        _persist(tasks, "Tarefa concluída e salva.")
                        st.rerun()

                    if a2.button(
                        "Em andamento",
                        key=f"progress_{task_id}",
                        use_container_width=True,
                    ):
                        _set_task_status(tasks, task_id, "Em andamento")
                        _persist(tasks, "Situação atualizada e salva.")
                        st.rerun()
                else:
                    if a1.button(
                        "Reabrir",
                        key=f"reopen_{task_id}",
                        use_container_width=True,
                    ):
                        _set_task_status(tasks, task_id, "Pendente")
                        _persist(tasks, "Tarefa reaberta e salva.")
                        st.rerun()

                if task.get("status") != "Concluída":
                    with st.expander("Reprogramar", expanded=False):
                        with st.form(f"reschedule_{task_id}"):
                            r1, r2 = st.columns(2)
                            original_due = _task_due_datetime(task)
                            target_day = r1.date_input("Novo dia", value=original_due.date() if original_due else today)
                            target_time = r2.time_input("Novo horário", value=original_due.time() if original_due else time(18))
                            move = st.form_submit_button("Salvar novo prazo")
                        if move:
                            task["due_date"] = target_day.isoformat()
                            task["due_time"] = target_time.strftime("%H:%M")
                            task["snooze_until"] = ""
                            _persist(tasks, "Prazo atualizado e salvo.")
                            st.rerun()

                edit_key = f"edit_open_{task_id}"
                if a3.button(
                    "Editar",
                    key=f"edit_{task_id}",
                    use_container_width=True,
                ):
                    st.session_state[edit_key] = not st.session_state.get(
                        edit_key, False
                    )

                if a4.button(
                    "Excluir",
                    key=f"delete_{task_id}",
                    use_container_width=True,
                ):
                    st.session_state[f"confirm_delete_{task_id}"] = True

                if st.session_state.get(f"confirm_delete_{task_id}", False):
                    st.warning("Excluir esta tarefa definitivamente?")
                    d1, d2 = st.columns(2)
                    if d1.button(
                        "Sim, excluir",
                        key=f"delete_yes_{task_id}",
                        type="primary",
                    ):
                        tasks = [
                            item for item in tasks
                            if item.get("id") != task_id
                        ]
                        _persist(tasks, "Tarefa excluída e alteração salva.")
                        st.session_state.pop(
                            f"confirm_delete_{task_id}", None
                        )
                        st.rerun()
                    if d2.button(
                        "Cancelar",
                        key=f"delete_no_{task_id}",
                    ):
                        st.session_state.pop(
                            f"confirm_delete_{task_id}", None
                        )
                        st.rerun()

                if st.session_state.get(edit_key, False):
                    due = _task_due_datetime(task)
                    with st.form(f"edit_form_{task_id}"):
                        new_title = st.text_input(
                            "Título",
                            value=task.get("title", ""),
                        )
                        e1, e2 = st.columns([1, 2])
                        current_area = _task_area(task)
                        new_area = e1.selectbox(
                            "Área",
                            AREAS,
                            index=AREAS.index(current_area),
                        )
                        current_category = task.get("category", "Outro")
                        new_category = e2.selectbox(
                            "Categoria",
                            CATEGORIES,
                            index=(
                                CATEGORIES.index(current_category)
                                if current_category in CATEGORIES
                                else len(CATEGORIES) - 1
                            ),
                        )

                        new_desc = st.text_area(
                            "Observação",
                            value=task.get("description", ""),
                        )
                        new_checklist_text = st.text_area(
                            "Checklist (um item por linha)",
                            value=_checklist_text(task),
                        )

                        e3, e4, e5 = st.columns(3)
                        new_due = e3.date_input(
                            "Data do prazo",
                            value=due.date() if due else today,
                            key=f"edit_due_{task_id}",
                        )
                        new_time = e4.time_input(
                            "Hora do prazo",
                            value=due.time() if due else time(23, 59),
                            step=900,
                            key=f"edit_time_{task_id}",
                        )
                        current_priority = task.get("priority", "Média")
                        new_priority = e5.selectbox(
                            "Prioridade",
                            PRIORITIES,
                            index=(
                                PRIORITIES.index(current_priority)
                                if current_priority in PRIORITIES
                                else 1
                            ),
                        )

                        current_reminders = _reminder_labels(task)
                        new_reminders = st.multiselect(
                            "Lembretes",
                            list(REMINDER_OPTIONS.keys()),
                            default=current_reminders,
                        )

                        current_status = task.get("status", "Pendente")
                        new_status = st.selectbox(
                            "Situação",
                            STATUSES,
                            index=(
                                STATUSES.index(current_status)
                                if current_status in STATUSES
                                else 0
                            ),
                        )
                        save_edit = st.form_submit_button(
                            "Salvar alterações",
                            type="primary",
                            use_container_width=True,
                        )

                    if save_edit:
                        for item in tasks:
                            if item.get("id") == task_id:
                                item["title"] = (
                                    new_title.strip() or item.get("title", "")
                                )
                                item["description"] = new_desc.strip()
                                item["area"] = new_area
                                item["category"] = new_category
                                item["due_date"] = (
                                    new_due.isoformat() if new_due else ""
                                )
                                item["due_time"] = (
                                    new_time.strftime("%H:%M")
                                    if new_time else "23:59"
                                )
                                item["priority"] = new_priority
                                item["status"] = new_status
                                item["reminder_minutes"] = [
                                    REMINDER_OPTIONS[label]
                                    for label in new_reminders
                                    if label in REMINDER_OPTIONS
                                ]
                                item["snooze_until"] = ""
                                item["checklist"] = _build_checklist(
                                    new_checklist_text,
                                    existing=item.get("checklist", []),
                                )
                                item["completed_at"] = (
                                    _now().isoformat(timespec="seconds")
                                    if new_status == "Concluída"
                                    else ""
                                )
                                break
                        _persist(tasks, "Tarefa editada e salva.")
                        st.session_state[edit_key] = False
                        st.rerun()

    if tasks:
        export_rows = []
        for task in tasks:
            export_rows.append(
                {
                    "Tarefa": task.get("title", ""),
                    "Área": _task_area(task),
                    "Descrição": task.get("description", ""),
                    "Data do Prazo": task.get("due_date", ""),
                    "Hora do Prazo": task.get("due_time", ""),
                    "Prioridade": task.get("priority", ""),
                    "Categoria": task.get("category", ""),
                    "Situação": task.get("status", ""),
                    "Lembretes": ", ".join(_reminder_labels(task)),
                    "Checklist": " | ".join(
                        (
                            ("[x] " if item.get("done") else "[ ] ")
                            + str(item.get("text", ""))
                        )
                        for item in task.get("checklist", [])
                        if isinstance(item, dict) and item.get("text")
                    ),
                    "Prazo": _task_status_label(task, now),
                    "Criada em": task.get("created_at", ""),
                    "Concluída em": task.get("completed_at", ""),
                }
            )
        df = pd.DataFrame(export_rows)
        csv = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "Exportar tarefas (.csv)",
            csv,
            file_name="minhas_tarefas.csv",
            mime="text/csv",
        )

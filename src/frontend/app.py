import json
import os
from collections.abc import Iterator

import httpx
import streamlit as st

API_URL = os.environ.get("API_URL", "http://localhost:8000")

st.set_page_config(
    page_title="RAG Agent Chat",
    page_icon="🔍",
    layout="wide",
)


# ─── État de session ──────────────────────────────────────────────────────────

def _init_session() -> None:
    defaults = {
        "phase": "search",          # search | select | answer
        "question": "",
        "thread_id": None,
        "groups": [],               # SourceGroup[]
        "selected_ids": set(),      # element_ids cochés
        "answer": "",
        "citations": [],
        "images": [],
        "chat_history": [],
        "search_count": 0,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


_init_session()


# ─── Helpers API ──────────────────────────────────────────────────────────────

def _api_post(path: str, payload: dict) -> dict:
    resp = httpx.post(f"{API_URL}{path}", json=payload, timeout=120.0)
    resp.raise_for_status()
    return resp.json()


def _stream_post(path: str, payload: dict) -> Iterator[dict]:
    """POST en SSE : yield chaque événement `data: {...}` décodé."""
    timeout = httpx.Timeout(10.0, read=None)  # la génération peut être longue
    with httpx.stream("POST", f"{API_URL}{path}", json=payload, timeout=timeout) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if line.startswith("data:"):
                yield json.loads(line[len("data:"):].strip())


def _clear_selection_state() -> None:
    """Purge les états des checkboxes de la question précédente."""
    for key in list(st.session_state.keys()):
        if key.startswith(("chunk_", "doc_")):
            del st.session_state[key]


def _toggle_doc(element_ids: list[str], doc_key: str) -> None:
    """Callback 'Tout sélectionner' : (dé)coche tous les chunks du document."""
    checked = st.session_state[doc_key]
    for eid in element_ids:
        st.session_state[f"chunk_{eid}"] = checked


# ─── UI principale ────────────────────────────────────────────────────────────

st.title("🔍 RAG Agent Chat")
st.caption(f"Connecté à {API_URL}")

# ── Barre latérale : historique ───────────────────────────────────────────────
with st.sidebar:
    st.header("Historique")
    for msg in st.session_state.chat_history:
        role_icon = "👤" if msg["role"] == "user" else "🤖"
        st.markdown(f"**{role_icon}** {msg['content'][:80]}…")

    if st.session_state.chat_history and st.button("Effacer l'historique"):
        st.session_state.chat_history = []
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 1 & 2 : Saisie de la question + affichage des sources
# ═══════════════════════════════════════════════════════════════════════════════

if st.session_state.phase == "search":
    with st.form("question_form"):
        question = st.text_area(
            "Votre question",
            placeholder="Que voulez-vous savoir sur vos documents ?",
            height=80,
        )
        submitted = st.form_submit_button("🔍 Rechercher", use_container_width=True)

    if submitted and question.strip():
        st.session_state.question = question.strip()
        with st.spinner("Recherche et classement des sources…"):
            try:
                data = _api_post(
                    "/chat/start",
                    {
                        "question": question.strip(),
                        "top_k": 20,
                        # Multi-turn : les questions suivantes bénéficient du contexte
                        "chat_history": st.session_state.chat_history,
                    },
                )
                st.session_state.thread_id = data["thread_id"]
                st.session_state.groups = data["groups"]
                _clear_selection_state()
                st.session_state.selected_ids = {
                    chunk["element_id"]
                    for group in data["groups"]
                    for chunk in group["chunks"]
                }
                st.session_state.phase = "select"
                st.rerun()
            except httpx.HTTPError as exc:
                st.error(f"Erreur API : {exc}")


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2 : Sélection des sources
# ═══════════════════════════════════════════════════════════════════════════════

elif st.session_state.phase == "select":
    st.subheader(f"📋 Sources trouvées pour : *{st.session_state.question}*")

    if not st.session_state.groups:
        st.warning("Aucune source trouvée. Essayez une autre question.")
        if st.button("← Nouvelle question"):
            st.session_state.phase = "search"
            st.rerun()
    else:
        selected: set[str] = set()

        for group in st.session_state.groups:
            filename = group["filename"]
            collection = group.get("collection") or ""
            # Identité réelle du document : deux ouvrages peuvent contenir un
            # chapitre du même nom.
            doc_id = group.get("source_path") or filename
            title = f"{collection} › {filename}" if collection else filename
            # Pertinence dans [0, 1] : le score brut est un logit de
            # cross-encoder, non borné, illisible tel quel.
            relevance = group.get("best_relevance") or 0.0
            chunks = group["chunks"]
            chunk_ids = [c["element_id"] for c in chunks]

            # Initialiser l'état des checkboxes au premier rendu (tout coché)
            for eid in chunk_ids:
                st.session_state.setdefault(
                    f"chunk_{eid}", eid in st.session_state.selected_ids
                )

            score_color = "green" if relevance > 0.5 else "orange" if relevance > 0.2 else "red"  # noqa: PLR2004
            score_badge = f":{score_color}[pertinence : {relevance:.0%}]"

            with st.expander(f"📄 **{title}** — {score_badge}", expanded=relevance > 0.2):  # noqa: PLR2004
                # Checkbox document entier : reflète l'état réel des chunks,
                # le callback propage le clic à tous les chunks du document.
                doc_key = f"doc_{doc_id}"
                st.session_state[doc_key] = all(
                    st.session_state[f"chunk_{eid}"] for eid in chunk_ids
                )
                st.checkbox(
                    f"Tout sélectionner ({filename})",
                    key=doc_key,
                    on_change=_toggle_doc,
                    args=(chunk_ids, doc_key),
                )

                st.divider()
                for chunk in chunks:
                    eid = chunk["element_id"]
                    chunk_relevance = chunk.get("relevance") or 0.0
                    label = chunk.get("label", "")
                    page = chunk.get("page_no", 0)
                    section = chunk.get("section_title") or ""
                    text_preview = chunk["document"][:200]

                    # Le titre de section situe le passage : « p.42 [paragraph] »
                    # seul ne dit rien de ce qu'on s'apprête à cocher.
                    where = f"p.{page}" if page else label
                    if section:
                        where += f" — § {section[:60]}"

                    checked = st.checkbox(
                        f"{where} · {chunk_relevance:.0%}",
                        key=f"chunk_{eid}",
                        help=text_preview,
                    )
                    if checked:
                        selected.add(eid)

        st.session_state.selected_ids = selected
        st.info(f"**{len(selected)}** chunk(s) sélectionné(s)")

        col1, col2 = st.columns([3, 1])
        with col1:
            if st.button(
                "✅ Générer la réponse",
                use_container_width=True,
                disabled=len(selected) == 0,
            ):
                if not selected:
                    st.error("Sélectionnez au moins une source.")
                else:
                    st.session_state.phase = "answer"
                    st.rerun()
        with col2:
            if st.button("← Retour", use_container_width=True):
                st.session_state.phase = "search"
                st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 3-5 : Génération de la réponse
# ═══════════════════════════════════════════════════════════════════════════════

elif st.session_state.phase == "answer":
    st.subheader(f"💬 {st.session_state.question}")

    answer_placeholder = st.empty()

    if not st.session_state.answer:
        try:
            answer_placeholder.markdown("⏳ _Reconstruction du contexte…_")
            acc = ""
            for event in _stream_post(
                "/chat/resume",
                {
                    "thread_id": st.session_state.thread_id,
                    "question": st.session_state.question,
                    "selected_element_ids": list(st.session_state.selected_ids),
                    "stream": True,
                },
            ):
                if event.get("reset"):
                    # Nouvelle génération (boucle agentique) : on repart de zéro
                    acc = ""
                    answer_placeholder.markdown("🔄 _Recherche supplémentaire…_")
                elif "token" in event:
                    acc += event["token"]
                    answer_placeholder.markdown(acc + " ▌")
                elif event.get("done"):
                    st.session_state.answer = event.get("answer", acc)
                    st.session_state.citations = event.get("citations", [])
                    st.session_state.images = event.get("images", [])
                    st.session_state.search_count = event.get("search_count", 1)

            # Ajouter à l'historique
            st.session_state.chat_history.append(
                {"role": "user", "content": st.session_state.question}
            )
            st.session_state.chat_history.append(
                {"role": "assistant", "content": st.session_state.answer}
            )

        except httpx.HTTPError as exc:
            st.error(f"Erreur lors de la génération : {exc}")
            if st.button("← Retour à la sélection"):
                st.session_state.phase = "select"
                st.rerun()
            st.stop()

    answer_placeholder.markdown(st.session_state.answer)

    # ── Images ────────────────────────────────────────────────────────────────
    if st.session_state.images:
        st.subheader("🖼️ Images référencées")
        cols = st.columns(min(len(st.session_state.images), 3))
        for i, img in enumerate(st.session_state.images):
            with cols[i % 3]:
                url = img["minio_url"]
                caption = f"[img:{img['element_id']}]"
                try:
                    if url.startswith("/"):
                        # Chemin proxy /media : on télécharge via l'API
                        # (le navigateur ne voit pas le réseau Docker interne)
                        resp = httpx.get(f"{API_URL}{url}", timeout=30.0)
                        resp.raise_for_status()
                        st.image(resp.content, caption=caption)
                    else:
                        st.image(url, caption=caption)
                except httpx.HTTPError:
                    st.caption(f"⚠️ Image indisponible : {caption}")

    # ── Citations ─────────────────────────────────────────────────────────────
    if st.session_state.citations:
        with st.expander(f"📚 Sources utilisées ({len(st.session_state.citations)})"):
            for citation in st.session_state.citations:
                book = citation.get("collection") or ""
                name = f"{book} › {citation['filename']}" if book else citation["filename"]
                where = [f"p.{citation['page_no']}"] if citation.get("page_no") else []
                if citation.get("section_title"):
                    where.append(f"§ {citation['section_title']}")
                suffix = ", ".join(where)
                st.markdown(
                    f"- **{name or 'document inconnu'}**"
                    + (f" — {suffix}" if suffix else "")
                    + f"  `[src:{citation['element_id']}]`  \n"
                    f"  _{citation['text_excerpt']}_"
                )

    if st.session_state.search_count > 1:
        st.caption(f"🔄 {st.session_state.search_count} recherche(s) effectuée(s)")

    st.divider()
    col1, col2 = st.columns([2, 1])
    with col1:
        if st.button("🔄 Nouvelle question", use_container_width=True):
            # Réinitialiser pour une nouvelle question
            st.session_state.phase = "search"
            st.session_state.answer = ""
            st.session_state.citations = []
            st.session_state.images = []
            st.session_state.groups = []
            st.session_state.selected_ids = set()
            st.rerun()
    with col2:
        if st.button("← Modifier les sources", use_container_width=True):
            st.session_state.phase = "select"
            st.session_state.answer = ""
            st.rerun()

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


# ─── UI principale ────────────────────────────────────────────────────────────

st.title("🔍 RAG Agent Chat")
st.caption(f"Connecté à {API_URL}")

# ── Barre latérale : historique ───────────────────────────────────────────────
with st.sidebar:
    st.header("Historique")
    for msg in st.session_state.chat_history:
        role_icon = "👤" if msg["role"] == "user" else "🤖"
        st.markdown(f"**{role_icon}** {msg['content'][:80]}…")

    if st.session_state.chat_history:
        if st.button("Effacer l'historique"):
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
                data = _api_post("/chat/start", {"question": question.strip(), "top_k": 20})
                st.session_state.thread_id = data["thread_id"]
                st.session_state.groups = data["groups"]
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
        selected: set[str] = st.session_state.selected_ids.copy()

        for group in st.session_state.groups:
            filename = group["filename"]
            best_score = group["best_score"]
            chunks = group["chunks"]

            score_color = "green" if best_score > 0.5 else "orange" if best_score > 0.2 else "red"  # noqa: PLR2004
            score_badge = f":{score_color}[score: {best_score:.3f}]"

            with st.expander(f"📄 **{filename}** — {score_badge}", expanded=best_score > 0.2):  # noqa: PLR2004
                # Checkbox document entier
                doc_checked = st.checkbox(
                    f"Tout sélectionner ({filename})",
                    value=all(c["element_id"] in selected for c in chunks),
                    key=f"doc_{filename}",
                )
                if doc_checked:
                    for c in chunks:
                        selected.add(c["element_id"])
                else:
                    # Ne désélectionner que si c'était coché avant
                    pass

                st.divider()
                for chunk in chunks:
                    eid = chunk["element_id"]
                    rerank_score = chunk.get("rerank_score") or 0.0
                    label = chunk.get("label", "")
                    page = chunk.get("page_no", 0)
                    text_preview = chunk["document"][:200]

                    checked = st.checkbox(
                        f"p.{page} [{label}] — score: {rerank_score:.3f}",
                        value=eid in selected,
                        key=f"chunk_{eid}",
                        help=text_preview,
                    )
                    if checked:
                        selected.add(eid)
                    else:
                        selected.discard(eid)

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
                st.markdown(
                    f"- **{citation['filename']}**, p.{citation['page_no']} "
                    f"`[src:{citation['element_id']}]`  \n"
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

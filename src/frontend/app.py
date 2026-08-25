import json
import os
import re
from collections.abc import Iterator
from typing import Any

import httpx
import streamlit as st

API_URL = os.environ.get("API_URL", "http://localhost:8000")

# Doit suivre MAX_HISTORY_MESSAGES de src/api/schemas.py, que ce module ne peut
# pas importer : l'image du frontend ne contient que src/frontend. L'API n'a
# jamais lu que les derniers messages ; envoyer le fil entier grossissait la
# charge utile pour rien, et depuis que la liste est bornee cote schema, une
# conversation assez longue se ferait rejeter en 422.
MAX_HISTORY_MESSAGES = 6

st.set_page_config(
    page_title="RAG Agent Chat",
    page_icon="🔍",
    layout="wide",
)


# ─── État de session ──────────────────────────────────────────────────────────

def _init_session() -> None:
    defaults: dict[str, Any] = {
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

def _api_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    resp = httpx.post(f"{API_URL}{path}", json=payload, timeout=120.0)
    resp.raise_for_status()
    payload_recu: dict[str, Any] = resp.json()
    return payload_recu


def _stream_post(path: str, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
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
        # Les clés de session_state sont typées `str | int` : seules les nôtres
        # nous intéressent, et elles sont des chaînes.
        if isinstance(key, str) and key.startswith(("chunk_", "doc_")):
            del st.session_state[key]


def couleur_pertinence(relevance: float, meilleure: float) -> str:
    """Couleur du badge de pertinence, RELATIVE au meilleur score de la question.

    Les scores d'un cross-encoder ne sont comparables ni d'un modèle à l'autre
    ni d'une question à l'autre : le reranker multilingue rend des valeurs bien
    plus basses que ms-marco, et les seuils absolus hérités affichaient tout en
    rouge — y compris la meilleure source. Ce qui aide à trancher n'est pas la
    valeur absolue mais le rang relatif : « ces sources-là sont les bonnes pour
    cette question ».
    """
    if meilleure <= 0:
        return "red"
    part = relevance / meilleure
    if part >= 0.6:  # noqa: PLR2004
        return "green"
    return "orange" if part >= 0.25 else "red"  # noqa: PLR2004


def situer_passage(chunk: dict[str, Any]) -> str:
    """Libellé qui situe un passage : langue, page, section.

    « p.42 [paragraph] » ne disait rien de ce qu'on s'apprête à cocher. La
    langue compte sur un corpus mixte : une question française ramène
    légitimement des sources anglaises, autant l'annoncer.
    """
    page = chunk.get("page_no") or 0
    ou = f"p.{page}" if page else (chunk.get("label") or "")
    section = chunk.get("section_title") or ""
    if section:
        ou += f" — § {section[:60]}"
    langue = chunk.get("language") or ""
    return f"[{langue}] {ou}" if langue else ou


def numeroter_citations(reponse: str, citations: list[dict[str, Any]]) -> str:
    """Remplace les marqueurs `[src:HASH]` par des renvois numérotés `[1]`.

    Le hash sert au post-processing, pas à la lecture : « le CD est un élément
    central de MLOps [src:203a2f3181] » demande à l'œil de sauter dix caractères
    sans signification. Un renvoi numéroté pointe vers la liste des sources, où
    figurent ouvrage, document, page et section.

    Les identifiants non résolus — inventés par le modèle, ou absents des
    contextes — sont retirés plutôt que laissés bruts : ils ne renvoient à rien.

    Un crochet peut en contenir plusieurs : le modèle écrit volontiers
    « [src:54a896937a, src:822a883a43] ». Chacun reçoit son renvoi.
    """
    numeros = {c["element_id"]: index for index, c in enumerate(citations, start=1)}

    def remplacer(correspondance: re.Match[str]) -> str:
        # Le modèle groupe souvent plusieurs sources dans un même crochet :
        # « [src:54a896937a, src:822a883a43] ». On les rend toutes.
        trouves = [
            numeros[eid]
            for eid in re.findall(r"[a-f0-9]{10}", correspondance.group(0))
            if eid in numeros
        ]
        vus = list(dict.fromkeys(trouves))
        return "".join(f"[{n}]" for n in vus)

    return re.sub(r"\[\s*src:[^\]]*\]", remplacer, reponse, flags=re.I)


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
                        # Multi-turn : les questions suivantes bénéficient du contexte
                        "chat_history": st.session_state.chat_history[
                            -MAX_HISTORY_MESSAGES:
                        ],
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

        # Les scores d'un cross-encoder ne sont pas comparables d'un modèle à
        # l'autre ni d'une question à l'autre : le multilingue rend des valeurs
        # bien plus basses que ms-marco, et des seuils absolus affichaient tout
        # en rouge. Ce qui aide à trancher, c'est le rang RELATIF — « ces
        # sources-là sont les bonnes pour cette question ».
        meilleure = max(
            (g.get("best_relevance") or 0.0 for g in st.session_state.groups), default=0.0
        )

        for rang, group in enumerate(st.session_state.groups):
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

            score_badge = (
                f":{couleur_pertinence(relevance, meilleure)}[pertinence : {relevance:.0%}]"
            )

            # Le meilleur document est toujours déplié : replier l'ensemble
            # oblige l'utilisateur à cliquer avant de voir quoi que ce soit.
            with st.expander(f"📄 **{title}** — {score_badge}", expanded=rang == 0):
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
                    text_preview = chunk["document"][:200]

                    checked = st.checkbox(
                        f"{situer_passage(chunk)} · {chunk_relevance:.0%}",
                        key=f"chunk_{eid}",
                        help=text_preview,
                    )
                    if checked:
                        selected.add(eid)

        st.session_state.selected_ids = selected
        st.info(f"**{len(selected)}** passage(s) sélectionné(s)")

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

    answer_placeholder.markdown(
        numeroter_citations(st.session_state.answer, st.session_state.citations)
    )

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
        # Dépliée : c'est le livrable, pas une annexe.
        with st.expander(
            f"📚 Sources utilisées ({len(st.session_state.citations)})", expanded=True
        ):
            for numero, citation in enumerate(st.session_state.citations, start=1):
                book = citation.get("collection") or ""
                name = f"{book} › {citation['filename']}" if book else citation["filename"]
                where = [f"p.{citation['page_no']}"] if citation.get("page_no") else []
                if citation.get("section_title"):
                    where.append(f"§ {citation['section_title']}")
                suffix = ", ".join(where)
                st.markdown(
                    f"**[{numero}]** **{name or 'document inconnu'}**"
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

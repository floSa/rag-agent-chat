"""Budget de contexte : ce qui ne tient pas dans la fenêtre du modèle doit être
écarté ici, explicitement — sinon Ollama tronque en silence, et par le DÉBUT du
prompt, donc en jetant le message système (les règles de citation et
d'abstention) puis les sources les mieux classées.

Le budget se calcule sur ce qui est RÉELLEMENT dans le prompt. Il ne comptait
que les sources : l'historique de conversation n'entrait dans aucun calcul, et
six messages suffisaient à faire dépasser num_ctx — 31 380 caractères mesurés
pour une fenêtre utile de 14 336."""

import json
import logging
import re

import pytest

from src.agent import llm
from src.agent.llm import (
    _TRUNCATION_MARKER,
    _build_context_message,
    _build_messages,
    _load_system_prompt,
    context_budget_chars,
    estimate_prompt_tokens,
    fit_contexts,
    fit_history,
    fit_prompt,
    history_budget_chars,
    log_prompt_measure,
    prompt_window_chars,
    prompt_window_tokens,
    source_framing_chars,
)
from src.agent.settings import settings
from src.api.schemas import MAX_MESSAGE_CHARS, BreadcrumbEntry, Message, SectionContext


def _context(element_id: str, taille: int) -> SectionContext:
    return SectionContext(
        element_id=element_id,
        section_id=element_id,
        breadcrumbs=[],
        elements=[],
        markdown="x" * taille,
    )


QUESTION = "Quelle est la difference entre un pipeline de features et un feature store ?"


def _source(rang: int, taille: int, niveaux: int = 2) -> SectionContext:
    """Un contexte tel que la production en produit : `breadcrumbs` peuplé.

    C'est le résultat de la remontée `PARENT_OF` — un contexte sans fil des
    titres est un artefact de fixture, et c'est sur lui qu'un encadrement
    forfaitaire paraissait généreux.
    """
    return SectionContext(
        element_id=f"abcdef01{rang:02d}",
        section_id=f"abcdef01{rang:02d}",
        breadcrumbs=[
            BreadcrumbEntry(node_id=f"n{i}", label="SectionHeader", text="T" * 44)
            for i in range(niveaux)
        ],
        elements=[],
        markdown="x" * taille,
    )


def _historique(nb: int, taille: int) -> list[Message]:
    return [
        Message(role="user" if i % 2 == 0 else "assistant", content="m" * taille)
        for i in range(nb)
    ]


# ─── Le budget compte ce qui est réellement dans le prompt ────────────────────

def test_budget_deduit_la_generation_de_la_fenetre() -> None:
    """num_ctx est partagé : ce qui est réservé à num_predict n'est pas du contexte."""
    assert context_budget_chars("question", []) > 0
    assert prompt_window_chars() < settings.llm_num_ctx * 3.5


def test_un_historique_long_reduit_le_budget_des_sources() -> None:
    """Le trou d'ALG-2 : l'historique n'entrait dans aucun calcul.

    Un forfait de 512 tokens était censé le couvrir. Six messages sont acceptés
    et chaque réponse assistante peut atteindre LLM_MAX_TOKENS : le forfait
    était dépassé d'un ordre de grandeur.
    """
    sans = context_budget_chars("question", [])
    avec = context_budget_chars("question", _historique(4, 800))

    assert avec < sans
    # Ce que l'historique occupe est retiré caractère pour caractère.
    assert sans - avec >= 4 * 800


def test_le_prompt_systeme_est_compte_dans_le_budget(monkeypatch) -> None:
    """Le message système est le premier que tronque Ollama : il doit être compté.

    L'assertion porte sur le TERME, pas sur une inégalité : `budget <= fenêtre −
    len(système)` était satisfaite par l'ancien forfait, qui ne comptait pas du
    tout le prompt système — vert des deux côtés du correctif, donc muet.
    """
    reel = _load_system_prompt()
    avec = context_budget_chars("question", [])
    monkeypatch.setattr(llm, "_load_system_prompt", lambda: "")
    sans = context_budget_chars("question", [])

    assert sans - avec == len(reel) > 0


def test_le_gabarit_rendu_est_compte_dans_le_budget() -> None:
    """Le gabarit est mesuré, pas forfaitisé : une retouche s'y répercute."""
    question_courte = context_budget_chars("q", [])
    question_longue = context_budget_chars("q" * 2000, [])

    assert question_longue < question_courte
    assert question_courte - question_longue >= 1999  # noqa: PLR2004


def test_l_encadrement_est_mesure_source_par_source() -> None:
    """34 caractères sans fil des titres, 275 avec cinq niveaux : un forfait
    unique est faux dans les deux sens selon le document.

    L'encadrement était un forfait de 200, documenté sous un tableau intitulé
    « Mesuré ». Sur les fixtures sans breadcrumbs il paraissait six fois trop
    haut ; en production `breadcrumbs` est toujours peuplé et le gabarit imprime
    « Chemin : » en clair.
    """
    base = len(_build_context_message(QUESTION, []))

    for niveaux in (0, 1, 3, 5):
        source = _source(0, 1000, niveaux)
        attendu = len(_build_context_message(QUESTION, [source])) - base - 1000
        assert source_framing_chars(QUESTION, [source]) == [attendu]

    profondeurs = [source_framing_chars(QUESTION, [_source(0, 100, n)])[0] for n in (0, 2, 5)]
    assert profondeurs[0] < profondeurs[1] < profondeurs[2]


def test_l_encadrement_ne_porte_que_sur_les_sources_retenues() -> None:
    """Sept candidates en gardaient sept, dix n'en gardaient plus que six : la
    provision réservait la place de sources jamais rendues."""
    sept = len(fit_prompt(QUESTION, [_source(i, 1500) for i in range(7)], []).contexts)

    for candidates in (8, 10, 12):
        retenues = len(
            fit_prompt(QUESTION, [_source(i, 1500) for i in range(candidates)], []).contexts
        )
        assert retenues >= sept, (
            f"7 candidates -> {sept} retenues, {candidates} candidates -> {retenues}"
        )


def test_aucune_source_ecartee_n_aurait_tenu() -> None:
    """Le budget doit être serré autant qu'honnête : la place laissée libre dans
    la fenêtre doit être plus petite que le coût de la moins chère des écartées.

    C'est la seule vérification qui attrape une sur-provision. Mesuré avant
    correctif : 3 125 caractères libres pour une source écartée qui en coûtait
    1 634.
    """
    candidates = [_source(i, 1500) for i in range(10)]
    fit = fit_prompt(QUESTION, candidates, [])
    ecartees = [c for c in candidates if c not in fit.contexts]
    assert ecartees, "le cas de test ne provoque aucune mise à l'écart"

    rendu = len(_load_system_prompt()) + len(_build_context_message(QUESTION, fit.contexts))
    libre = prompt_window_chars() - rendu
    base = len(_build_context_message(QUESTION, []))
    cout_minimal = min(len(_build_context_message(QUESTION, [c])) - base for c in ecartees)

    assert libre < cout_minimal, (
        f"{libre} caracteres libres alors qu'une source ecartee en coute {cout_minimal}"
    )


def test_le_prompt_rendu_ne_depasse_jamais_la_fenetre() -> None:
    """L'encadrement mesuré doit l'être exactement : le message rendu est la
    seule vérité, et il doit tenir quelle que soit la profondeur du fil des
    titres."""
    for niveaux in (0, 2, 4, 6):
        candidates = [_source(i, 1500, niveaux) for i in range(10)]
        fit = fit_prompt(QUESTION, candidates, [])
        rendu = len(_load_system_prompt()) + len(_build_context_message(QUESTION, fit.contexts))

        assert rendu <= prompt_window_chars(), f"{niveaux} niveaux : {rendu} caracteres"


def test_la_declaration_d_outil_est_comptee(monkeypatch) -> None:
    """`tools` n'est pas un canal séparé : Ollama le rend dans le prompt.

    417 caractères que rien ne comptait — le même trou que le forfait retiré,
    à plus petite échelle.
    """
    from src.agent import llm

    avec = context_budget_chars("q", [])
    cout = llm.tools_overhead_chars()
    monkeypatch.setattr(llm.settings, "native_tool_calling", False)
    sans = context_budget_chars("q", [])

    assert llm.tools_overhead_chars() == 0
    assert sans - avec == cout > 0


def test_le_budget_ne_devient_jamais_negatif() -> None:
    """Un historique qui dépasse la fenêtre donne 0, pas un budget négatif.

    Le pire cas que l'API accepte : six messages à la borne de Message.content.
    """
    pire_cas = _historique(6, MAX_MESSAGE_CHARS)

    assert context_budget_chars("q", pire_cas) == 0


# ─── Le prompt construit tient dans la fenêtre ────────────────────────────────

def test_le_prompt_construit_tient_dans_la_fenetre() -> None:
    """Le mode de panne d'ALG-2, de bout en bout.

    Avant correctif : 31 380 caractères de prompt pour une fenêtre utile de
    14 336 — Ollama tronquait par le DÉBUT, donc jetait le message système.
    """
    msgs, _ = _build_messages(
        "Quelle est la question ?",
        [_context("a", 12_000), _context("b", 12_000)],
        _historique(6, 3000),
    )
    total = sum(len(str(m["content"])) for m in msgs)

    assert total <= prompt_window_chars()


def test_le_prompt_garde_toujours_le_message_systeme() -> None:
    """Même sous un historique démesuré, c'est le système qui reste."""
    msgs, _ = _build_messages("q", [_context("a", 50_000)], _historique(6, MAX_MESSAGE_CHARS))

    assert msgs[0]["role"] == "system"
    assert estimate_prompt_tokens(msgs) <= settings.llm_num_ctx


# ─── Historique : les tours les plus récents survivent ────────────────────────

def _conversation(nb_tours: int, taille: int) -> list[Message]:
    """Une conversation réelle : question utilisateur, puis réponse assistante."""
    messages: list[Message] = []
    for i in range(nb_tours):
        messages.append(Message(role="user", content=f"question {i} " + "q" * taille))
        messages.append(Message(role="assistant", content=f"reponse {i} " + "r" * taille))
    return messages


def test_une_reponse_ne_part_jamais_sans_sa_question() -> None:
    """La coupe porte sur des TOURS, pas sur des messages.

    Couper par message produisait ce que le docstring prétendait éviter : avec
    six messages de 2 000 caractères, seul le dernier survivait — l'assistant,
    sans la question à laquelle il répondait.
    """
    for taille in (500, 1000, 2000, 3000):
        kept, _ = fit_history(_conversation(3, taille))
        if kept:
            assert kept[0].role == "user", (
                f"taille {taille} : historique retenu {[m.role for m in kept]}"
            )


def test_le_prompt_alterne_les_roles() -> None:
    """Un gabarit de chat strict sur l'alternance recevait un tour « model »
    directement après le système."""
    msgs, _ = _build_messages("Et pour les femmes ?", [], _conversation(3, 2000))
    roles = [m["role"] for m in msgs]

    assert roles == ["system", *["user", "assistant"] * ((len(roles) - 2) // 2), "user"], roles


def test_un_tour_trop_gros_est_ecarte_entier() -> None:
    """Pas de demi-échange : ni la question sans sa réponse, ni l'inverse."""
    kept, dropped = fit_history(_conversation(1, MAX_MESSAGE_CHARS // 2))

    assert kept == []
    assert dropped == 2  # noqa: PLR2004


def test_un_assistant_orphelin_ne_part_jamais_seul() -> None:
    """Un historique qui commence par une réponse — client mal élevé, ou tour
    coupé en amont — ne doit pas produire un « model » juste après le système."""
    kept, dropped = fit_history([Message(role="assistant", content="reponse orpheline")])

    assert kept == []
    assert dropped == 1


def test_la_part_de_fenetre_de_l_historique_est_reglable(monkeypatch) -> None:
    """Forfait assumé, mais exposé : HISTORY_WINDOW_SHARE le rend arbitrable
    sans toucher au code."""
    monkeypatch.setattr(llm.settings, "history_window_share", 0.5)
    large = history_budget_chars()
    monkeypatch.setattr(llm.settings, "history_window_share", 0.1)
    etroit = history_budget_chars()

    assert etroit < large
    assert large == int(prompt_window_chars() * 0.5)


def test_les_balises_de_tour_valent_le_gabarit_qu_elles_citent() -> None:
    """Le forfait valait 24 pour un gabarit qui en fait 34 — 30 % de moins, et
    dans le sens dangereux : sous-estimer le prompt une fois par message."""
    gemma = len("<start_of_turn>user\n") + len("<end_of_turn>\n")

    assert llm._MESSAGE_FRAMING_CHARS == gemma == 34  # noqa: PLR2004, SLF001



def test_l_historique_garde_les_messages_les_plus_recents() -> None:
    """Sens inverse des sources : c'est le dernier échange qui situe la question."""
    historique = [Message(role="user", content=f"{i}" * 2000) for i in range(6)]
    kept, dropped = fit_history(historique)

    assert kept == historique[-len(kept) :]
    assert dropped == 6 - len(kept)


def test_l_historique_est_borne_a_une_part_de_la_fenetre() -> None:
    kept, _ = fit_history(_historique(6, 4000))

    assert sum(len(m.content) for m in kept) <= history_budget_chars()
    assert history_budget_chars() < prompt_window_chars()


def test_un_historique_court_passe_entier() -> None:
    historique = _historique(4, 100)

    assert fit_history(historique) == (historique, 0)


def test_un_message_trop_gros_est_ecarte_pas_tronque() -> None:
    """Un demi-tour de conversation n'apporte rien ; node_rewrite a déjà rendu
    la question autonome, donc l'historique est du confort, pas un prérequis."""
    kept, dropped = fit_history([Message(role="user", content="m" * MAX_MESSAGE_CHARS)])

    assert kept == []
    assert dropped == 1


# ─── Sources : ordre, remplissage au mieux, troncature ────────────────────────

def test_toutes_les_sources_passent_si_le_budget_suffit() -> None:
    contexts = [_context("a", 100), _context("b", 100)]
    kept, dropped = fit_contexts(contexts, budget_chars=1000)

    assert len(kept) == 2  # noqa: PLR2004
    assert dropped == 0


def test_la_queue_saute_a_taille_egale() -> None:
    """Les sources sont ordonnées par pertinence : on garde les premières."""
    contexts = [_context("a", 400), _context("b", 400), _context("c", 400)]
    kept, dropped = fit_contexts(contexts, budget_chars=900)

    assert [c.element_id for c in kept] == ["a", "b"]
    assert dropped == 1


def test_le_remplissage_est_au_mieux_pas_une_coupe_de_la_queue() -> None:
    """`continue` et non `break` : une petite source après une grosse écartée
    est conservée.

    Le comportement est raisonnable, mais le docstring annonçait « c'est la
    queue de la liste qui saute » — ce que le code n'a jamais fait. À tailles
    égales les deux comportements sont indistinguables : il faut une grosse
    source au milieu pour les séparer, ce que le test précédent ne faisait pas.
    """
    contexts = [_context("a", 300), _context("b", 900), _context("c", 300)]
    kept, dropped = fit_contexts(contexts, budget_chars=700)

    assert [c.element_id for c in kept] == ["a", "c"]  # « queue qui saute » dirait ["a"]
    assert dropped == 1


def test_la_source_unique_trop_grosse_est_tronquee() -> None:
    """IMP-6 : elle était transmise entière, et Ollama coupait — par le DÉBUT."""
    kept, dropped = fit_contexts([_context("a", 10_000)], budget_chars=1000)

    assert [c.element_id for c in kept] == ["a"]
    assert len(kept[0].markdown) <= 1000  # noqa: PLR2004
    assert dropped == 0


def test_la_troncature_conserve_le_debut_et_se_signale() -> None:
    """Coupée par la fin, et marquée : le modèle doit voir qu'il manque du texte."""
    source = _context("a", 10_000)
    kept, _ = fit_contexts([source], budget_chars=1000)

    assert kept[0].markdown.endswith(_TRUNCATION_MARKER)
    assert source.markdown.startswith(kept[0].markdown[: -len(_TRUNCATION_MARKER)])


def _source_avec_marqueurs(nb_elements: int) -> SectionContext:
    """Un markdown tel que `_render_element` le produit : un [src:ID] par élément."""
    parties = [
        f"Paragraphe numero {i} de la section, avec un peu de texte. [src:{i:010d}]"
        for i in range(nb_elements)
    ]
    return SectionContext(
        element_id="abcdef0123",
        section_id="abcdef0123",
        breadcrumbs=[],
        elements=[],
        markdown="\n\n".join(parties),
    )


def test_la_troncature_n_ampute_jamais_un_marqueur() -> None:
    """Un identifiant coupé en deux n'est pas résolu par le post-processing — ou,
    pire, correspond à un AUTRE élément.

    C'était le mode de panne d'IMP-6, déplacé d'Ollama vers `_truncate` : la
    coupe se faisait à un index de caractère brut. Balayé sur une plage de
    budgets, parce qu'un seul cas tombe rarement au milieu d'un marqueur.
    """
    source = _source_avec_marqueurs(20)
    vrais_ids = {f"{i:010d}" for i in range(20)}
    marqueur = re.compile(r"\[src:([^\]]*)\]")
    tronquees = 0

    for budget in range(150, 1400):
        kept, _ = fit_contexts([source], budget_chars=budget)
        if not kept:
            continue
        markdown = kept[0].markdown
        corps = (
            markdown[: -len(_TRUNCATION_MARKER)]
            if markdown.endswith(_TRUNCATION_MARKER)
            else markdown
        )
        tronquees += 1

        assert corps.count("[src:") == len(marqueur.findall(corps)), (
            f"budget {budget} : marqueur ouvert non refermé — {corps[-40:]!r}"
        )
        assert set(marqueur.findall(corps)) <= vrais_ids, (
            f"budget {budget} : identifiant inconnu — {corps[-40:]!r}"
        )
        assert len(markdown) <= budget, f"budget {budget} : {len(markdown)} caractères rendus"

    assert tronquees > 1000, "la plage balayée ne tronque presque rien"


def test_la_coupe_tombe_sur_une_frontiere_d_element() -> None:
    """Le texte conservé porte toujours son identifiant : un fragment sans
    marqueur ne serait pas attribuable, et le prompt système exige de citer."""
    kept, _ = fit_contexts([_source_avec_marqueurs(20)], budget_chars=400)
    corps = kept[0].markdown[: -len(_TRUNCATION_MARKER)]

    assert corps.endswith("]")


def test_une_fenetre_trop_etroite_pour_la_marque_ecarte_la_source() -> None:
    """Seule la marque de troncature entrerait : cela n'apprend rien au modèle."""
    kept, dropped = fit_contexts(
        [_source_avec_marqueurs(5)], budget_chars=len(_TRUNCATION_MARKER)
    )

    assert kept == []
    assert dropped == 1


def test_un_budget_epuise_ecarte_tout() -> None:
    """Budget nul : mieux vaut une abstention qu'un prompt amputé de son système."""
    kept, dropped = fit_contexts([_context("a", 100), _context("b", 100)], budget_chars=0)

    assert kept == []
    assert dropped == 2  # noqa: PLR2004


def test_sans_source() -> None:
    assert fit_contexts([], budget_chars=1000) == ([], 0)


# ─── Point d'entrée unique ────────────────────────────────────────────────────

def test_fit_prompt_borne_historique_et_sources_ensemble() -> None:
    """/answer et _build_messages doivent compter la même chose."""
    fit = fit_prompt("q", [_context("a", 20_000)], _historique(6, 4000))

    assert fit.dropped_history > 0
    assert sum(len(c.markdown) for c in fit.contexts) <= fit.budget_chars
    assert fit.budget_chars == context_budget_chars("q", fit.history)


def test_fit_prompt_sans_historique() -> None:
    fit = fit_prompt("q", [_context("a", 100)], None)

    assert fit.history == []
    assert fit.dropped_history == 0
    assert fit.dropped_contexts == 0


# ─── L'estimation confrontée à la mesure ──────────────────────────────────────

def test_estimate_prompt_tokens_compte_les_balises_de_tour() -> None:
    """Le gabarit de chat encadre chaque message : trois messages, trois tours.

    Même texte total, découpé autrement : c'est l'encadrement qui fait l'écart.
    """
    groupe = estimate_prompt_tokens([{"role": "system", "content": "abc" * 3}])
    eclate = estimate_prompt_tokens([{"role": "system", "content": "abc"}] * 3)

    assert eclate > groupe


def test_l_ecart_entre_estimation_et_reel_est_journalise(caplog) -> None:
    """`prompt_eval_count` était rendu par Ollama et lu par personne : le ratio
    caractères/token restait une devinette qu'aucune mesure ne corrigeait."""
    with caplog.at_level(logging.INFO, logger="src.agent.llm"):
        log_prompt_measure(1000, 1200)

    assert "estimé 1000" in caplog.text
    assert "réel 1200" in caplog.text
    assert "-16.7 %" in caplog.text


def _avertissements(caplog):
    return [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_un_prompt_qui_affleure_num_ctx_signale_une_troncature(caplog) -> None:
    """Ollama tronque AVANT d'évaluer : `prompt_eval_count` est majoré par
    num_ctx par construction.

    La première version avertissait sur `> num_ctx`, condition inatteignable —
    le détecteur du mode de panne ne pouvait pas voir le mode de panne. Un
    décompte qui affleure la fenêtre est la seule trace observable.
    """
    with caplog.at_level(logging.INFO, logger="src.agent.llm"):
        log_prompt_measure(settings.llm_num_ctx + 500, settings.llm_num_ctx)

    assert len(_avertissements(caplog)) == 1
    assert "PAR LE DÉBUT" in _avertissements(caplog)[0].getMessage()


def test_un_prompt_qui_rogne_la_generation_est_signale(caplog) -> None:
    """Entre la fenêtre de prompt et num_ctx, `num_predict` ne peut plus être
    honoré : la génération est rognée, en silence."""
    depasse = prompt_window_tokens() + 800
    with caplog.at_level(logging.INFO, logger="src.agent.llm"):
        log_prompt_measure(depasse, depasse)

    assert len(_avertissements(caplog)) == 1
    assert "rognée" in _avertissements(caplog)[0].getMessage()


def test_un_prompt_dans_la_fenetre_ne_leve_pas_d_avertissement(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="src.agent.llm"):
        log_prompt_measure(prompt_window_tokens() - 100, prompt_window_tokens() - 100)

    assert _avertissements(caplog) == []


def test_une_mesure_reduite_par_le_cache_kv_ne_calibre_rien(caplog) -> None:
    """Ollama ne réévalue que le préfixe absent de son cache KV. Au deuxième tour
    d'une conversation, `prompt_eval_count` ne mesure plus le prompt — calibrer
    `_CHARS_PER_TOKEN` là-dessus le ferait fondre à chaque tour."""
    with caplog.at_level(logging.INFO, logger="src.agent.llm"):
        log_prompt_measure(4000, 200)

    assert not any("ratio mesuré" in r.getMessage() for r in caplog.records)
    assert any("cache KV" in r.getMessage() for r in caplog.records)


def test_sans_prompt_eval_count_rien_n_est_journalise(caplog) -> None:
    """Une version d'Ollama qui ne rend pas le champ ne doit pas faire de bruit."""
    with caplog.at_level(logging.INFO, logger="src.agent.llm"):
        log_prompt_measure(1000, None)

    assert caplog.records == []


def _flux_ollama(lignes: list[dict]):
    class Resp:
        def raise_for_status(self) -> None: ...

        async def aiter_lines(self):
            for ligne in lignes:
                yield json.dumps(ligne)

    class Stream:
        async def __aenter__(self):
            return Resp()

        async def __aexit__(self, *_):
            return False

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        def stream(self, *_args, **_kwargs):
            return Stream()

    return lambda **_kwargs: Client()


@pytest.mark.asyncio
async def test_le_prompt_eval_count_est_lu_dans_l_evenement_final(monkeypatch, caplog) -> None:
    """Il n'arrive que sur l'événement `done: true` — celui dont la boucle
    sortait sans le lire."""
    monkeypatch.setattr(
        llm.httpx,
        "AsyncClient",
        _flux_ollama(
            [
                {"message": {"content": "Réponse."}},
                {"message": {"content": ""}, "done": True, "prompt_eval_count": 4321},
            ]
        ),
    )

    with caplog.at_level(logging.INFO, logger="src.agent.llm"):
        tokens = [t async for t in llm.generate_stream("q", [_context("a", 100)])]

    assert tokens == ["Réponse."]
    assert "réel 4321" in caplog.text

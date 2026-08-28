"""Une citation ne doit pas résoudre vers un texte jamais soumis.

`resolve_citations` résolvait un `[src:ID]` depuis deux tables — les sections
CANDIDATES et TOUS les chunks reranqués — dont aucune n'était restreinte à ce que
le budget de fenêtre avait réellement envoyé au modèle. Un identifiant écarté
ressortait donc résolu, avec un extrait, une page et une section que le modèle
n'avait pas lus : une citation d'apparence parfaite vers un passage jamais vu.

Trois choses ont dicté la forme de ces tests.

- **Les deux voies comptent séparément.** Passer `submitted_contexts` au lieu des
  candidates ferme `elements_map` et laisse `chunks_map` grand ouvert ; filtrer
  `chunks_map` sans changer l'argument ferme l'inverse. Un test qui ne couvre
  qu'une voie est vert avec la moitié du correctif, donc il ne garde rien.
- **Le chemin réel est l'HISTORIQUE.** L'objection évidente — « le modèle ne peut
  pas citer un identifiant qu'il n'a jamais vu » — tombe sur le multi-tour :
  `fit_history` resoumet les réponses passées marqueurs compris, et le gabarit
  ordonne de les reprendre tels quels. Le test qui suit ce chemin prouve chaque
  maillon au lieu de le supposer, sans quoi le lot ressemble à un durcissement
  théorique.
- **Le grain est l'élément, pas la section.** Le cas tranchant — une section
  RETENUE mais tronquée, dont un élément a perdu son marqueur à la coupe — vit
  dans `test_precision_contexte.py`, à côté de la machinerie de troncature qui le
  produit : `test_le_post_processing_refuse_un_identifiant_que_le_prompt_ne_
  portait_pas`.
"""

import logging

from src.agent.graph import node_postprocess, resolve_citations
from src.api.schemas import ChunkResult, Message, SectionContext, SectionElement

# ─── Outillage ────────────────────────────────────────────────────────────────

MINIO_URL = "http://minio:9000/documents/images/livre/1111111111_picture.png"


def _element(node_id: str, **kwargs) -> SectionElement:
    base = {
        "node_id": node_id,
        "label": "paragraph",
        "text": f"Le passage {node_id}, assez long pour peser dans le budget de fenêtre.",
        "sequence": 0,
    }
    return SectionElement(**{**base, **kwargs})


def _section(section_id: str, elements: list[SectionElement], **kwargs) -> SectionContext:
    """Section reconstruite dont le markdown PORTE les marqueurs de ses éléments.

    C'est la forme que produit `_render_element` : « texte [src:ID] ». Le markdown
    est ce que la résolution lit désormais — une section au markdown vide ne cite
    plus rien, et un faux au markdown vide ne prouverait rien.
    """
    base = {
        "element_id": elements[0].node_id,
        "section_id": section_id,
        "breadcrumbs": [],
        "elements": elements,
        "markdown": " ".join(f"{e.text} [src:{e.node_id}]" for e in elements),
        "filename": "3. Statistical Toolbox",
        "section_title": "Dispersion",
        "collection": "The Statistics Workshop",
    }
    return SectionContext(**{**base, **kwargs})


def _chunk(element_id: str, **kwargs) -> ChunkResult:
    base = {
        "chunk_id": element_id,
        "element_id": element_id,
        "graph_node_id": element_id,
        "document": "Le texte du chunk, celui que le classement porte.",
        "filename": "3. Statistical Toolbox",
        "collection": "The Statistics Workshop",
        "section_title": "Dispersion",
        "page_no": 88,
        "label": "paragraph",
        "distance": 0.2,
    }
    return ChunkResult(**{**base, **kwargs})


# ─── (a) et (e) : les deux voies, comptées séparément ─────────────────────────

def test_la_voie_des_chunks_refuse_une_section_ecartee_par_le_budget(caplog) -> None:
    """LE cas du lot, et la voie qui laissait passer.

    La section a été ÉCARTÉE : elle n'est pas dans `submitted_contexts`. Mais son
    élément d'ancrage est dans le classement — c'est par là qu'il est arrivé — et
    `chunks_map` n'était filtré sur rien. Le modèle recevait donc une citation
    complète, avec l'extrait du chunk, vers un passage absent de son prompt.

    Ce test reste rouge si l'on ne fait que passer `submitted_contexts` sans
    filtrer `chunks_map` : c'est la moitié du correctif qui ne suffit pas.
    """
    ecartee = _section("ssssssssbb", [_element("bbbbbbbbbb")])
    state = {
        "response": "Une affirmation appuyée sur rien [src:bbbbbbbbbb].",
        "reranked_chunks": [_chunk("bbbbbbbbbb")],
        # Reconstruite, donc candidate — et écartée par le budget, donc absente
        # des sections soumises. C'est exactement l'état que `node_generate`
        # publie quand la fenêtre déborde.
        "enriched_contexts": [ecartee],
        "submitted_contexts": [],
    }

    with caplog.at_level(logging.WARNING, logger="src.agent.graph"):
        resultat = node_postprocess(state)

    assert resultat["citations"] == []
    # Le refus doit se voir : c'est le seul moyen d'apprendre si le cas se
    # produit en production, et un identifiant qui tombe en silence ne
    # l'apprendrait à personne.
    assert any("bbbbbbbbbb" in message for message in caplog.messages)
    assert any("Citations refusées" in message for message in caplog.messages)


def test_la_voie_des_elements_refuse_une_section_ecartee_par_le_budget() -> None:
    """La seconde voie, qui ne se ferme QUE par le choix de l'argument.

    Ici l'élément n'est dans aucun chunk : il n'est connu que par la section
    reconstruite. Filtrer `chunks_map` ne change donc rien, et ce test reste rouge
    tant que `node_postprocess` passe `enriched_contexts`. Les deux tests
    ensemble comptent les deux espèces séparément.
    """
    ecartee = _section("ssssssssbb", [_element("bbbbbbbbbb"), _element("cccccccccc")])
    state = {
        "response": "Une affirmation appuyée sur rien [src:cccccccccc].",
        "reranked_chunks": [],
        "enriched_contexts": [ecartee],
        "submitted_contexts": [],
    }

    assert node_postprocess(state)["citations"] == []


def test_un_identifiant_invente_reste_ignore_sans_bruit(caplog) -> None:
    """Le cas connu, et le troisième cas ne doit pas l'avaler.

    Inventé par le modèle : ni les sections ni le classement ne le connaissent, il
    est ignoré comme avant, et il ne déclenche PAS l'avertissement du refus — sans
    quoi le journal deviendrait bavard sur un cas ordinaire et le vrai signal,
    lui, se noierait.
    """
    soumise = _section("ssssssssaa", [_element("aaaaaaaaaa")])
    state = {
        "response": "Une affirmation [src:deadbeef99].",
        "reranked_chunks": [],
        "enriched_contexts": [soumise],
        "submitted_contexts": [soumise],
    }

    with caplog.at_level(logging.WARNING, logger="src.agent.graph"):
        assert node_postprocess(state)["citations"] == []

    assert not any("Citations refusées" in message for message in caplog.messages)


# ─── (d) La non-régression qui compte ─────────────────────────────────────────

def test_une_citation_legitime_garde_son_document_sa_page_et_sa_section() -> None:
    """Un correctif qui casse les citations normales serait pire que le défaut.

    L'élément est soumis, son marqueur est dans le texte parti : la citation sort
    complète. Les métadonnées viennent du chunk quand il y en a un — c'est la
    raison d'être de cette voie, et le filtre ne doit pas l'avoir déplacée.
    """
    soumise = _section("ssssssssaa", [_element("aaaaaaaaaa")])
    state = {
        "response": "La dispersion se mesure [src:aaaaaaaaaa].",
        "reranked_chunks": [_chunk("aaaaaaaaaa")],
        "enriched_contexts": [soumise],
        "submitted_contexts": [soumise],
    }

    citation = node_postprocess(state)["citations"][0]

    assert citation.element_id == "aaaaaaaaaa"
    assert citation.filename == "3. Statistical Toolbox"
    assert citation.collection == "The Statistics Workshop"
    assert citation.section_title == "Dispersion"
    assert citation.page_no == 88
    assert citation.text_excerpt == "Le texte du chunk, celui que le classement porte."


def test_une_citation_legitime_sans_chunk_garde_son_extrait_de_section() -> None:
    """L'autre voie, sur un élément soumis : le cas le plus courant en production.

    Le LLM cite un enfant de section, qui ne figure dans aucun chunk reranqué.
    Fermer la voie des chunks ne doit pas fermer celle-là.
    """
    soumise = _section("ssssssssaa", [_element("aaaaaaaaaa", page_no=42)])
    state = {
        "response": "La dispersion se mesure [src:aaaaaaaaaa].",
        "reranked_chunks": [],
        "enriched_contexts": [soumise],
        "submitted_contexts": [soumise],
    }

    citation = node_postprocess(state)["citations"][0]

    assert citation.page_no == 42
    assert citation.text_excerpt.startswith("Le passage aaaaaaaaaa")
    assert citation.collection == "The Statistics Workshop"


# ─── (3) Les images ───────────────────────────────────────────────────────────

def test_une_illustration_d_une_section_ecartee_n_est_plus_affichee() -> None:
    """Restreindre les sections restreint les images, et c'est voulu.

    Une figure qui disparaît d'une réponse se voit à l'écran, autant qu'une
    citation. Mais elle appartenait à une section que le modèle n'a jamais reçue :
    la montrer laissait croire que la réponse s'appuie dessus.

    Les deux voies des images sont exercées ici : le marqueur explicite du modèle
    ET l'illustration attachée à une section citée.
    """
    ecartee = _section(
        "ssssssssbb",
        [
            _element("bbbbbbbbbb"),
            _element("1111111111", label="picture", minio_url=MINIO_URL),
        ],
    )
    state = {
        "response": "Voir la figure [img:1111111111], et le passage [src:bbbbbbbbbb].",
        "reranked_chunks": [_chunk("bbbbbbbbbb")],
        "enriched_contexts": [ecartee],
        "submitted_contexts": [],
    }

    resultat = node_postprocess(state)

    assert resultat["citations"] == []
    assert resultat["images"] == []


def test_une_illustration_dont_le_marqueur_est_coupe_reste_affichee() -> None:
    """Le grain des images de la VOIE 2 est la section, pas l'élément — décision.

    La section est soumise et citée ; le marqueur de sa figure n'est pas dans le
    texte parti. La citation d'un élément coupé serait refusée — elle rendrait un
    extrait non lu — mais la figure, elle, n'a pas de texte : le modèle n'en voit
    jamais qu'un marqueur, et elle appartient réellement à la section citée. La
    retirer ne corrigerait aucun mensonge, et retirerait au lecteur une figure du
    document.

    La voie 1 reste au grain de l'élément : un `[img:ID]` que le modèle émet est
    une affirmation sur ce qu'il a vu, et elle est vérifiée comme telle.
    """
    figure = _element("1111111111", label="picture", minio_url=MINIO_URL)
    citee = _section("ssssssssaa", [_element("aaaaaaaaaa"), figure])
    # Le markdown soumis s'arrête après le premier élément : le marqueur de la
    # figure est parti à la coupe.
    tronquee = citee.model_copy(
        update={"markdown": f"{citee.elements[0].text} [src:aaaaaaaaaa]"}
    )
    state = {
        "response": "La dispersion se mesure [src:aaaaaaaaaa].",
        "reranked_chunks": [],
        "enriched_contexts": [citee],
        "submitted_contexts": [tronquee],
    }

    resultat = node_postprocess(state)

    assert [c.element_id for c in resultat["citations"]] == ["aaaaaaaaaa"]
    assert [i.element_id for i in resultat["images"]] == ["1111111111"]


def test_un_marqueur_image_emis_par_le_modele_sur_un_element_coupe_est_refuse() -> None:
    """La voie 1, au grain de l'élément : la contrepartie du test précédent.

    Le modèle ÉCRIT `[img:ID]` alors que ce marqueur n'était pas dans son prompt.
    Ce n'est plus une illustration attachée par le système, c'est une affirmation
    du modèle sur ce qu'il a vu — et elle est fausse. La section n'étant pas citée
    ici, la voie 2 ne la rattrape pas.
    """
    figure = _element("1111111111", label="picture", minio_url=MINIO_URL)
    soumise = _section("ssssssssaa", [_element("aaaaaaaaaa"), figure])
    tronquee = soumise.model_copy(
        update={"markdown": f"{soumise.elements[0].text} [src:aaaaaaaaaa]"}
    )
    state = {
        "response": "Voir la figure [img:1111111111].",
        "reranked_chunks": [],
        "enriched_contexts": [soumise],
        "submitted_contexts": [tronquee],
    }

    assert node_postprocess(state)["images"] == []


def test_la_borne_des_illustrations_reste_appliquee(monkeypatch) -> None:
    """MAX_IMAGES borne toujours, et la restriction ne change pas son sens.

    Vérifié parce que la restriction réduit le vivier : si elle avait déplacé la
    borne, on l'aurait su ici et non en production.
    """
    from src.agent import graph as graph_module

    monkeypatch.setattr(graph_module.settings, "max_images", 2)
    figures = [
        _element(f"{i}" * 10, label="picture", minio_url=MINIO_URL) for i in range(1, 6)
    ]
    soumise = _section("ssssssssaa", [_element("aaaaaaaaaa"), *figures])
    state = {
        "response": "La dispersion se mesure [src:aaaaaaaaaa].",
        "reranked_chunks": [],
        "enriched_contexts": [soumise],
        "submitted_contexts": [soumise],
    }

    assert len(node_postprocess(state)["images"]) == 2


# ─── (b) Le chemin réel : l'historique ────────────────────────────────────────

def test_le_modele_qui_recite_un_marqueur_du_tour_precedent_est_refuse(caplog) -> None:
    """Le chemin par lequel le défaut est atteignable en production.

    Chaque maillon est PROUVÉ ici, pas supposé — un test qui choisit son cas doit
    montrer qu'il l'a atteint :

    1. le budget réel écarte la section (`dropped == 1`, et elle n'est pas dans
       les retenues) ;
    2. le marqueur de son élément est bel et bien dans le prompt du tour courant,
       parce que `fit_history` y resoumet la réponse du tour précédent ;
    3. le modèle le recite — ce que le gabarit lui ordonne de faire — et la
       citation est refusée.

    Sans le point 2, le lot n'aurait corrigé qu'un défaut inatteignable.
    """
    from src.agent.llm import _build_messages, context_budget_chars, fit_history

    question = "Et pour une distribution asymétrique ?"
    historique = [
        Message(role="user", content="Comment mesure-t-on la dispersion ?"),
        Message(role="assistant", content="Par l'écart-type [src:bbbbbbbbbb]."),
    ]

    # Les tailles sont CALCULÉES depuis le budget réel, pas posées : une
    # constante choisie à la main tomberait un jour du mauvais côté de la
    # frontière, et le test surveillerait alors un cas qu'il n'atteint plus.
    # 85 % pour la première — elle passe entière — et 85 % pour la seconde : la
    # marge restante (~15 %) est en dessous du plancher de troncature (un tiers
    # de la source), donc la seconde est ÉCARTÉE et non tronquée.
    budget = context_budget_chars(question, fit_history(historique)[0])
    cible = int(budget * 0.85)
    premiere = _section("ssssssssaa", [_element("aaaaaaaaaa", text="Un paragraphe. " * 40)])
    premiere = premiere.model_copy(update={"markdown": "A" * cible})
    seconde = _section("ssssssssbb", [_element("bbbbbbbbbb")])
    seconde = seconde.model_copy(
        update={"markdown": "B" * cible + " [src:bbbbbbbbbb]"}
    )

    messages, fit = _build_messages(question, [premiere, seconde], historique)

    # Maillon 1 : la section de l'identifiant a été écartée, pour de vrai.
    assert fit.dropped_contexts == 1
    assert [c.section_id for c in fit.contexts] == ["ssssssssaa"]
    # Maillon 2 : et son marqueur est pourtant dans le prompt, par l'historique.
    prompt = "\n".join(m["content"] for m in messages)
    assert "[src:bbbbbbbbbb]" in prompt
    assert any("[src:bbbbbbbbbb]" in m.content for m in fit.history)

    # Maillon 3 : le modèle reprend l'identifiant tel quel, comme on le lui
    # demande. L'état est celui que `node_generate` publie.
    state = {
        "response": "Comme dit plus haut, par l'écart-type [src:bbbbbbbbbb].",
        "reranked_chunks": [_chunk("bbbbbbbbbb")],
        "enriched_contexts": [premiere, seconde],
        "submitted_contexts": fit.contexts,
    }

    with caplog.at_level(logging.WARNING, logger="src.agent.graph"):
        resultat = node_postprocess(state)

    assert resultat["citations"] == [], (
        "la citation désigne un passage absent du prompt de CE tour : la réponse "
        "peut rester vraie, la citation n'est plus vérifiable"
    )
    assert any("bbbbbbbbbb" in message for message in caplog.messages)


# ─── Ce que le nœud dit quand la chaîne est cassée ────────────────────────────

def test_un_etat_sans_section_soumise_le_dit(caplog) -> None:
    """Aucune citation sur des candidates existantes est un symptôme, pas un état.

    Sans cet avertissement, une chaîne `on_fit` → `submitted_contexts` défaite
    rendrait des réponses sans aucune citation, ce qui ressemble à un modèle qui
    n'en a émis aucune. C'est le même repli muet que celui que ce lot corrige,
    une strate plus haut.
    """
    candidate = _section("ssssssssaa", [_element("aaaaaaaaaa")])
    state = {
        "response": "Une affirmation [src:aaaaaaaaaa].",
        "reranked_chunks": [],
        "enriched_contexts": [candidate],
    }

    with caplog.at_level(logging.WARNING, logger="src.agent.graph"):
        assert node_postprocess(state)["citations"] == []

    assert any("on_fit" in message for message in caplog.messages)


def test_la_resolution_directe_sans_section_ne_cite_rien() -> None:
    """`/chat/simple` appelle la résolution sans passer par l'état du graphe.

    Le contrat est le même : ce qui n'a pas été soumis ne se cite pas. Ici, aucune
    section soumise du tout — le cas où le rappel `on_fit` n'a rien rendu.
    """
    citations, images = resolve_citations("Un fait [src:aaaaaaaaaa].", [], [_chunk("aaaaaaaaaa")])

    assert citations == []
    assert images == []


# ─── La route de génération directe, qui ne passe pas par l'état du graphe ────

def _client_generation_directe(monkeypatch, sections: list[SectionContext]):
    """Un client pour `/chat/simple`, avec le VRAI budget de fenêtre.

    Le faux `generate_stream` appelle `on_fit` comme le vrai le fait avant sa
    requête HTTP, et il le fait avec le vrai `fit_prompt` : c'est l'appel de la
    route qui est testé, pas une reformulation du budget.
    """
    from fastapi.testclient import TestClient

    from src.agent import llm as llm_module
    from src.agent import usage as usage_module
    from src.api import main

    monkeypatch.setattr(main.settings, "api_key", "")
    # La capture n'a rien à voir avec ce test, et son fichier n'existe pas hors
    # conteneur : la laisser active journalise un échec par requête.
    monkeypatch.setattr(usage_module.settings, "usage_capture", False)
    par_id = {ctx.element_id: ctx for ctx in sections}
    monkeypatch.setattr(main, "reconstruct_section", lambda eid: par_id[eid])

    reponse = "Comme dit plus haut [src:bbbbbbbbbb], et voici mieux [src:aaaaaaaaaa]."

    async def faux_stream(*args, **kwargs):
        on_fit = kwargs.get("on_fit")
        if on_fit is not None:
            question = kwargs.get("question", args[0] if args else "")
            contexts = kwargs.get("contexts", args[1] if len(args) > 1 else [])
            historique = kwargs.get("chat_history", args[2] if len(args) > 2 else None)
            on_fit(llm_module.fit_prompt(question, contexts or [], historique))
        yield reponse

    # Le VRAI `generate` tourne sur le chemin non diffusé : c'est lui qui doit
    # relayer `on_fit`, et le remplacer par un faux rendrait le test vert alors
    # que le relais aurait disparu. Seul `generate_stream`, qui fait la requête
    # HTTP, est neutralisé — des deux côtés, la route l'appelant directement en
    # flux et à travers `generate` hors flux.
    monkeypatch.setattr(main, "generate_stream", faux_stream)
    monkeypatch.setattr(llm_module, "generate_stream", faux_stream)
    return TestClient(main.app)


def _deux_sections_dont_une_ecartee() -> list[SectionContext]:
    """La première tient dans la fenêtre, la seconde est écartée.

    Tailles CALCULÉES depuis le budget réel : 85 % chacune, donc la marge
    restante passe sous le plancher de troncature et la seconde est écartée
    entière au lieu d'être tronquée.
    """
    from src.agent.llm import context_budget_chars

    cible = int(context_budget_chars("q", []) * 0.85)
    premiere = _section("ssssssssaa", [_element("aaaaaaaaaa")])
    seconde = _section("ssssssssbb", [_element("bbbbbbbbbb")])
    return [
        premiere.model_copy(update={"markdown": "A" * cible + " [src:aaaaaaaaaa]"}),
        seconde.model_copy(update={"markdown": "B" * cible + " [src:bbbbbbbbbb]"}),
    ]


def test_generation_directe_en_flux_ne_cite_que_ce_qu_elle_a_soumis(monkeypatch) -> None:
    """`/chat/simple` n'a pas d'état de graphe : le rappel est posé au point d'appel.

    Les deux espèces sont comptées : la section retenue reste citée, l'écartée ne
    l'est plus. Un test qui n'assérait que l'absence serait vert sur une route qui
    ne cite plus rien du tout.
    """
    import json

    sections = _deux_sections_dont_une_ecartee()
    client = _client_generation_directe(monkeypatch, sections)

    with client.stream(
        "POST",
        "/chat/simple",
        json={
            "question": "q",
            "selected_element_ids": ["aaaaaaaaaa", "bbbbbbbbbb"],
            "stream": True,
        },
    ) as flux:
        evenements = [
            json.loads(ligne[len("data:") :].strip())
            for ligne in flux.iter_lines()
            if ligne.startswith("data:")
        ]

    final = [e for e in evenements if e.get("done")][-1]
    assert [c["element_id"] for c in final["citations"]] == ["aaaaaaaaaa"]


def test_generation_directe_hors_flux_ne_cite_que_ce_qu_elle_a_soumis(monkeypatch) -> None:
    """Le même contrat sur la réponse non diffusée, qui passe par `generate`.

    C'est ce chemin qui a exigé de relayer `on_fit` à travers `generate` : sans
    cela, l'appelant non-streaming ne pouvait pas savoir ce que le budget avait
    retenu, et il restait le seul à citer des sections écartées.
    """
    sections = _deux_sections_dont_une_ecartee()
    client = _client_generation_directe(monkeypatch, sections)

    corps = client.post(
        "/chat/simple",
        json={
            "question": "q",
            "selected_element_ids": ["aaaaaaaaaa", "bbbbbbbbbb"],
            "stream": False,
        },
    ).json()

    assert [c["element_id"] for c in corps["citations"]] == ["aaaaaaaaaa"]

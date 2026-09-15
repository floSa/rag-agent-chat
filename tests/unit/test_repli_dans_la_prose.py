"""Le second rideau : reconnaître un appel d'outil ÉCRIT DANS LA PROSE.

Quand le modèle ne fait pas d'appel natif — parce qu'il n'en sait pas faire,
parce que la déclaration n'est pas partie, ou parce qu'il a simplement décidé
d'écrire l'appel à la place — `node_generate` a un second rideau : repérer
l'appel dans le texte. Ce rideau porte DEUX charges, et elles tombent
séparément :

1. **la recherche supplémentaire part** — sans quoi la boucle agentique
   s'arrête sur une réponse que le modèle a lui-même déclarée incomplète ;
2. **la syntaxe d'appel ne part PAS à l'écran** — sans quoi l'utilisateur lit
   `search_vectors(query="…")` au milieu d'une phrase.

Un rideau qui ne fait que la première laisse l'appel s'afficher ; un rideau qui
ne fait que la seconde efface la demande sans jamais la servir. Chaque forme est
donc éprouvée sur les deux.

CE QUE CES SCÈNES ÉPROUVENT, ET D'OÙ ELLES PARTENT
--------------------------------------------------

Elles partent d'un **message utilisateur** et traversent `node_generate` en
entier. Elles n'appellent pas le reconnaisseur à la main : un test qui attaque
le validateur est vert sous un `node_generate` qui ne l'appelle jamais, et c'est
exactement ce qui avait caché ce défaut.

Et elles posent `NATIVE_TOOL_CALLING` sur sa valeur **de production** (`True`).
Le repli n'est pas commandé par cet interrupteur — il est armé dans les deux
positions — mais l'éprouver en position éteinte mesurerait une configuration que
personne ne sert. Ce qui amène le repli ici, c'est un flux **sans appel natif**
dont le texte porte l'appel : la scène réelle du défaut.

D'OÙ VIENNENT LES FORMES
------------------------

Elles ne sont pas imaginées : chacune a été relevée sur un des deux moteurs du
poste, en lecture, une requête à la fois. Voir la table du rapport du lot 19.
Les formes non mesurées ne sont pas ajoutées « au cas où » — un motif plus large
que les formes réelles déclenche des recherches fantômes sur du texte ordinaire,
et `test_les_mentions_en_prose_ne_declenchent_rien` en tient les bords.
"""

import json

import pytest

from src.agent import graph as graph_module
from src.agent import llm
from src.api.schemas import BreadcrumbEntry, SectionContext

QUESTION = "Quelle est la durée du congé parental d'éducation ?"


def _flux_sans_appel_natif(texte: str):
    """Un serveur qui rend `texte` en un seul jeton et AUCUN `tool_calls`.

    C'est la scène du défaut : le canal natif est muet, donc `tool_queries`
    reste vide, donc le second rideau est le seul signal disponible.
    """

    class Resp:
        def raise_for_status(self) -> None: ...

        async def aiter_lines(self):
            yield json.dumps({"message": {"content": texte}})
            yield json.dumps({"message": {"content": ""}, "done": True})

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


def _section() -> SectionContext:
    return SectionContext(
        element_id="abcdef0123",
        section_id="sssssssss1",
        breadcrumbs=[BreadcrumbEntry(node_id="doc0000001", label="Document", text="Manuel RH")],
        elements=[],
        markdown="Le congé de paternité est de 25 jours calendaires. [src:abcdef0123]",
    )


async def _servir(monkeypatch, texte: str) -> dict:
    """Joue un tour complet de `node_generate` sur un modèle qui rend `texte`.

    `NATIVE_TOOL_CALLING` est posé à `True` : la valeur SERVIE en production.
    """
    monkeypatch.setattr(llm.settings, "native_tool_calling", True)
    monkeypatch.setattr(llm.httpx, "AsyncClient", _flux_sans_appel_natif(texte))
    return await graph_module.node_generate(
        {
            "question": QUESTION,
            "enriched_contexts": [_section()],
            "search_count": 0,
            "_metadata": {},
        }
    )


# ─── Les formes MESURÉES sur les deux moteurs ────────────────────────────────

# (étiquette, texte tel que le moteur l'a écrit, sous-question attendue)
FORMES_MESUREES = [
    pytest.param(
        "positionnelle",
        'search_vectors("contrat cadre")',
        "contrat cadre",
        id="positionnelle-ollama",
    ),
    pytest.param(
        "nommee-query",
        "Je vais lancer une recherche complémentaire sur la durée du congé parental "
        "d'éducation.\n\n<execute_tool>\n"
        'search_vectors(query="durée du congé parental d\'éducation")\n'
        "</execute_tool>",
        "durée du congé parental d'éducation",
        id="nommee-query-vllm",
    ),
    pytest.param(
        "nommee-underscore",
        "Je vais lancer une recherche complémentaire pour trouver le nombre de jours de "
        "télétravail autorisés.\n\n"
        'search_vectors(sous_question="nombre de jours de télétravail autorisés")',
        "nombre de jours de télétravail autorisés",
        id="nommee-sous_question-vllm",
    ),
    pytest.param(
        "nommee-tiret",
        "Je n'ai trouvé d'information sur ce sujet dans les documents fournis.\n\n"
        'search_vectors(sous-question="durée du congé parental d\'éducation")',
        "durée du congé parental d'éducation",
        id="nommee-sous-question-ollama",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("etiquette,texte,attendue", FORMES_MESUREES)
async def test_la_recherche_supplementaire_part(monkeypatch, etiquette, texte, attendue) -> None:
    """Effet 1 : la sous-question est extraite et la boucle repart.

    Sans ce rideau, `needs_more_info` reste faux et l'agent rend une réponse
    dont le modèle vient lui-même de dire qu'elle ne suffit pas.
    """
    resultat = await _servir(monkeypatch, texte)

    assert resultat["next_query"] == attendue, f"forme {etiquette} non reconnue"
    assert resultat["needs_more_info"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("etiquette,texte,attendue", FORMES_MESUREES)
async def test_la_syntaxe_d_appel_ne_part_pas_a_l_ecran(
    monkeypatch, etiquette, texte, attendue
) -> None:
    """Effet 2 : ce que l'utilisateur lit ne porte plus l'appel.

    C'est une charge DISTINCTE de la première : un rideau qui reconnaît la forme
    sans la retirer sert la recherche ET affiche la syntaxe.
    """
    resultat = await _servir(monkeypatch, texte)

    assert "search_vectors" not in resultat["response"], f"forme {etiquette} affichée"
    # La sous-question ENTRE GUILLEMETS est la marque de la syntaxe. Exiger
    # qu'elle disparaisse tout court serait faux : le modèle a le droit
    # d'annoncer en français ce qu'il va chercher, et la forme `query=` mesurée
    # sur vLLM fait précisément les deux.
    assert f'"{attendue}"' not in resultat["response"]


@pytest.mark.asyncio
async def test_l_enrobage_du_moteur_ne_reste_pas_orphelin(monkeypatch) -> None:
    """La balise qui ENTOURE l'appel part avec lui, et pas sans lui.

    vLLM enrobe l'appel de `<execute_tool>…</execute_tool>` (mesuré). Retirer
    l'appel seul laisserait à l'écran une balise ouvrante et une fermante vides,
    ce qui est la même fuite en plus discret.
    """
    resultat = await _servir(
        monkeypatch,
        "Je vais chercher.\n\n<execute_tool>\n"
        'search_vectors(query="le contrat cadre")\n'
        "</execute_tool>",
    )

    assert resultat["next_query"] == "le contrat cadre"
    assert "execute_tool" not in resultat["response"]
    assert resultat["response"] == "Je vais chercher."


# ─── L'AUTRE BORD : ce qui ne doit RIEN déclencher ───────────────────────────

# Chacun de ces textes est soit relevé sur un moteur, soit la phrase ordinaire
# la plus proche de la forme reconnue. Un motif trop large les attrape, et
# l'agent lance alors une recherche que personne n'a demandée.
PROSE_ORDINAIRE = [
    pytest.param(
        "Je n'ai pas trouvé d'information sur ce sujet dans les documents fournis "
        "concernant le compte épargne temps. Je vais lancer une recherche complémentaire "
        "avec l'outil `search_vectors`.\n\n"
        "Sous-question : Quelles sont les modalités et la durée du compte épargne temps ?",
        id="mention-en-prose-sans-parentheses-ollama",
    ),
    pytest.param(
        "La fonction search_vectors(query) prend une sous-question et rend des passages.",
        id="signature-citee-sans-guillemets",
    ),
    pytest.param(
        'Le manuel parle de "congé parental" à la page 12, sans donner de durée.',
        id="guillemets-sans-appel",
    ),
    pytest.param(
        "Il faudrait appeler search_vectors avec une sous-question précise.",
        id="nom-de-l-outil-dans-une-phrase",
    ),
    pytest.param(
        "Je vais lancer une recherche complémentaire avec l'outil `search_vectors`.\n\n"
        'Sous-question : "Quelles sont les modalités et la durée du compte épargne temps ?"',
        id="mention-puis-citation-entre-guillemets",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("texte", PROSE_ORDINAIRE)
async def test_les_mentions_en_prose_ne_declenchent_rien(monkeypatch, texte) -> None:
    """Le bord haut : aucune recherche fantôme, et le texte rendu intact.

    Le premier cas n'est pas inventé : Ollama l'a écrit, deux essais sur deux.
    Un rideau qui cherche `search_vectors` sans exiger la parenthèse ET la
    chaîne entre guillemets part en recherche sur cette phrase-là.

    Le dernier est COMPOSÉ, et il faut le dire : ses deux moitiés sont mesurées
    séparément — Ollama écrit « avec l'outil `search_vectors`. » sans jamais
    l'appeler (deux essais sur deux), et les deux moteurs citent les sources
    entre guillemets (quatre cellules sur quatre). Aucune requête ne les a
    produites ENSEMBLE : le prompt système interdit d'écrire l'appel, et les
    modèles lui obéissent. Ce cas n'affirme donc pas qu'un moteur écrit ce
    texte ; il tient le bord haut du motif, que rien ne tenait avant lui — une
    mutation retirant les parenthèses du motif a survécu à tout le reste de ce
    fichier.
    """
    resultat = await _servir(monkeypatch, texte)

    assert resultat["next_query"] is None
    assert resultat["needs_more_info"] is False
    assert resultat["response"] == texte.strip()

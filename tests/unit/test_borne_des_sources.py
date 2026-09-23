"""La borne déclarée par l'API est celle que la chaîne sert réellement.

`AnswerRequest.max_sources` a porté `le=20` pendant que `rerank` n'en rendait
que `RERANK_TOP_K` = 10. L'API acceptait donc 11 à 20, servait 10, et ne le
disait nulle part : ni erreur, ni avertissement, ni champ de réponse. Un défaut
qui échoue se voit ; celui-là RÉPONDAIT.

CE QUE CES SCÈNES TIENNENT, ET POURQUOI ELLES NE LISENT PAS `RERANK_TOP_K`.
Un garde qui confronterait `settings.rerank_top_k` à lui-même serait vrai par
construction et ne pourrait rien attraper. Ces scènes mesurent donc ce que la
chaîne **SERT** — la longueur que `rerank` rend vraiment, sur un vivier plus
grand que toute borne — et le confrontent à ce que le schéma **DÉCLARE**. Les
deux sites peuvent alors diverger, et c'est cette divergence qui rougit :

  — mutation du reranker (la troncature de `rerank`) → il sert moins que la
    borne déclarée → rouge ;
  — mutation du schéma (une borne écrite en dur) → il déclare plus que la
    chaîne ne sert → rouge.

Aucune scène n'écrit `10`, ni aucun autre instantané du réglage : le jour où
`RERANK_TOP_K` bouge, elles suivent sans être touchées.
"""

from typing import Any

import numpy
import pytest
from pydantic import BaseModel

from src.agent import retriever
from src.api import schemas
from src.api.schemas import AnswerRequest, ChunkResult

# Vivier soumis au reranker. Il n'a qu'une exigence, et elle est VÉRIFIÉE par
# `_servies_par_la_chaine` plutôt que supposée : être strictement plus grand que
# la borne, sans quoi la troncature ne s'exercerait pas et la scène mesurerait
# une liste rendue entière — verte, et aveugle.
TAILLE_DU_VIVIER = 64


class _CrossEncoderDouble:
    """Rend un score par paire, décroissant, sans charger le moindre modèle.

    Les scores sont distincts : deux ex æquo laisseraient l'ordre du tri décider
    silencieusement, et la scène mesurerait alors un hasard de tri plutôt que la
    troncature.
    """

    def predict(self, pairs: list[Any]) -> Any:
        # `rerank` appelle `.tolist()` sur ce retour : le vrai cross-encoder rend
        # un tableau numpy. Le double doit en rendre un aussi, sinon la scène
        # mourrait dans le double au lieu de mesurer le code.
        return numpy.array([1.0 - i / len(pairs) for i in range(len(pairs))])


def _vivier(taille: int) -> list[ChunkResult]:
    """Des chunks à `element_id` tous distincts.

    `rerank` dédoublonne par élément AVANT de tronquer : un vivier qui porterait
    des doublons serait réduit par le dédoublonnage, et une troncature absente
    passerait pour présente.
    """
    return [
        ChunkResult(
            chunk_id=f"chunk-{i}",
            element_id=f"{i:010x}",
            graph_node_id=f"noeud-{i}",
            document=f"passage numéro {i}",
            filename="document.pdf",
            page_no=1,
            label="paragraph",
            distance=0.1,
        )
        for i in range(taille)
    ]


@pytest.fixture
def servies(monkeypatch: pytest.MonkeyPatch) -> int:
    """Combien de sources la chaîne SERT, mesuré en faisant tourner `rerank`.

    C'est le producteur de la contrainte : `node_reconstruct_context` découpe
    `ranking[:max_sources]` sur cette liste-là, donc rien en aval ne peut en
    rendre plus. Seul le cross-encoder est doublé ; le dédoublonnage, le tri et
    la troncature sont le vrai code.
    """
    retriever._get_rerank_model.cache_clear()
    monkeypatch.setattr(retriever, "_get_rerank_model", lambda: _CrossEncoderDouble())

    vivier = _vivier(TAILLE_DU_VIVIER)
    rendu = len(retriever.rerank("une question", vivier))

    # CONTRÔLE POSITIF DE LA MESURE ELLE-MÊME. Si `rerank` rendait tout le
    # vivier, aucune troncature ne se serait exercée et le chiffre ci-dessus ne
    # décrirait aucune borne. La scène doit mourir ici, pas passer.
    assert rendu < TAILLE_DU_VIVIER, (
        f"`rerank` a rendu les {rendu} éléments du vivier sans en tronquer aucun : "
        "cette mesure ne décrit alors AUCUNE borne, et tout ce qui la confronte "
        "au schéma est vert par accident. Agrandir le vivier, ou chercher "
        "pourquoi la troncature de `rerank` ne s'exerce plus"
    )
    return rendu


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Any:
    """`/answer` avec son graphe doublé : seule la porte de validation est mesurée.

    La scène qui s'en sert ne lit que le code de statut. Doubler le graphe est
    donc ce qui fait qu'un 422 y signifie « le schéma a refusé » et rien
    d'autre : sans ce double, une pile absente rendrait 500 ou 503, et un
    `!= 422` passerait en ayant mesuré une panne.
    """
    from fastapi.testclient import TestClient

    from src.api import main

    async def graphe_muet(_state: Any, _config: Any = None) -> dict[str, Any]:
        return {
            "reranked_chunks": [],
            "enriched_contexts": [],
            "submitted_contexts": [],
            "response": "",
            "citations": [],
            "images": [],
            "_metadata": {},
        }

    monkeypatch.setattr(main.answer_graph, "ainvoke", graphe_muet)
    return TestClient(main.app)


def _borne_declaree(modele: type[BaseModel], champ: str) -> int | None:
    """La borne supérieure que le schéma publie pour ce champ.

    Lue dans les métadonnées pydantic, donc dans ce qui gouverne réellement la
    validation et ce qu'OpenAPI publie — pas dans le texte du fichier, qu'un
    refactor déplacerait sans rien changer au contrat.
    """
    for contrainte in modele.model_fields[champ].metadata:
        borne = getattr(contrainte, "le", None)
        if borne is not None:
            return int(borne)
    return None


def test_la_borne_declaree_est_celle_que_la_chaine_sert(servies: int) -> None:
    """L'invariant, à l'état nu : ce qui est promis == ce qui est servi."""
    declaree = _borne_declaree(AnswerRequest, "max_sources")

    assert declaree is not None, (
        "`AnswerRequest.max_sources` ne déclare plus AUCUNE borne supérieure. "
        "Le champ accepte alors n'importe quel entier et la chaîne en sert "
        f"{servies} : la promesse est redevenue fausse, en plus grand"
    )
    assert declaree == servies, (
        f"L'API déclare accepter jusqu'à {declaree} sources et la chaîne en sert "
        f"{servies}. Une demande entre les deux est rabotée SANS QUE RIEN NE LE "
        "DISE — c'est le défaut que ce fichier garde. Les deux sites sont "
        "`MAX_SOURCES_SERVIES` dans `src/api/schemas.py` et la troncature de "
        "`rerank` dans `src/agent/retriever.py` : l'un des deux a bougé seul"
    )


def test_l_api_refuse_ce_que_la_chaine_ne_sert_pas(client, servies: int) -> None:
    """La borne n'est pas seulement écrite, elle est APPLIQUÉE par HTTP.

    Le contrat se juge à la porte : la dernière valeur servable passe, la
    première qui ne l'est pas est refusée. Un schéma dont la borne serait juste
    mais inerte — contrainte non lue par pydantic, champ renommé — resterait
    vert sur la scène précédente et tomberait ici.
    """
    hors_borne = client.post(
        "/answer", json={"question": "borne haute", "max_sources": servies + 1}
    )
    assert hors_borne.status_code == 422, (  # noqa: PLR2004
        f"demander {servies + 1} sources est accepté ({hors_borne.status_code}) "
        f"alors que la chaîne en sert {servies}. L'appelant recevra moins que ce "
        "qu'il a demandé sans qu'aucun champ ne l'en informe"
    )

    # CONTRÔLE POSITIF : sans lui, un schéma qui refuserait TOUT — borne à 0,
    # champ devenu incompatible — rendrait la scène ci-dessus verte en ayant
    # cessé de décrire une borne.
    dans_la_borne = client.post(
        "/answer", json={"question": "borne exacte", "max_sources": servies}
    )
    assert dans_la_borne.status_code != 422, (  # noqa: PLR2004
        f"demander {servies} sources est refusé alors que la chaîne les sert. "
        "La borne déclarée est plus basse que ce que la chaîne sait faire : "
        "l'API refuse un service qu'elle rend"
    )


def test_aucun_champ_d_api_ne_borne_les_sources_de_son_cote(servies: int) -> None:
    """LE FLUX INTERACTIF, ET TOUT CE QUI VIENDRAIT APRÈS LUI.

    `/chat/start` ne déclare aujourd'hui aucune borne de sources : son nombre de
    contextes est la SÉLECTION que le client poste, que `node_reconstruct_context`
    n'écrête pas — il n'y a donc pas de promesse à y rendre honnête. Cette scène
    tient ce qui arriverait SI on en ajoutait une : tout champ d'API qui borne un
    nombre de sources doit porter la borne de la chaîne, jamais la sienne.

    Elle balaie les schémas plutôt que d'énumérer les endpoints connus, parce
    qu'un garde ancré sur une liste écrite à la main ne voit pas le champ ajouté
    le mois suivant.
    """
    trouves: list[tuple[str, str, int | None]] = []
    for nom, objet in vars(schemas).items():
        if not (isinstance(objet, type) and issubclass(objet, BaseModel)):
            continue
        for champ in objet.model_fields:
            if "max_source" in champ:
                trouves.append((nom, champ, _borne_declaree(objet, champ)))

    # CONTRÔLE POSITIF : un balayage qui ne trouve RIEN passerait en silence, et
    # ce fichier ne garderait plus que son propre parcours de `vars()`.
    assert trouves, (
        "aucun champ de borne de sources trouvé dans `src.api.schemas` : le "
        "balayage ne mesure plus rien. Le champ a-t-il été renommé ?"
    )

    ecarts = [(m, c, b) for m, c, b in trouves if b != servies]
    assert not ecarts, (
        f"des champs d'API bornent les sources autrement que la chaîne "
        f"(qui en sert {servies}) : {ecarts}. Chacun promet un nombre de sources "
        "que la chaîne ne tiendra pas — dériver la borne de `MAX_SOURCES_SERVIES` "
        "plutôt que l'écrire"
    )

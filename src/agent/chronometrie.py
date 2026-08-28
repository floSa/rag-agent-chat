"""Partition du temps d'une réponse par étage.

`AnswerResponse` ne portait que `retrieval_ms` et `generation_ms` : deux
chiffres pour huit étages, dont celui qui n'avait jamais été chronométré — la
reconstruction par le graphe, c'est-à-dire le pari central du projet. On ne peut
pas arbitrer la suppression d'une étape dont on ignore le prix.

**Ce module tient une partition, pas une collection de compteurs.** La
distinction n'est pas cosmétique : si un étage est mesuré à l'intérieur d'un
autre, la somme des étages dépasse le total et le tableau devient faux sans que
rien ne le signale. Deux garde-fous l'empêchent :

- `Chrono.mesurer` refuse un nom d'étage absent d'`ETAGES`. Un refactor qui
  invente un étage verse sinon son temps au résidu, en silence.
- `decomposer` publie le RÉSIDU — le temps qu'aucun étage n'a réclamé — et le
  laisse devenir négatif quand la partition se recoupe. Un résidu négatif est la
  seule trace observable d'un double comptage ; le borner à zéro effacerait
  précisément ce qu'on cherche à voir.

Un résidu large est en soi un résultat : c'est du temps que personne ne sait
expliquer.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

# Étages d'une réponse, dans l'ordre où ils s'exécutent. La liste FAIT la
# partition : `decomposer` n'attribue du temps à rien d'autre, et tout ce qui
# n'y figure pas tombe au résidu.
#
# `rewrite_ms` et `translation_ms` sont deux appels LLM distincts et se
# mesurent séparément : la traduction est un coût de la recherche translingue,
# la réécriture un coût des questions de suivi, et les deux s'arbitrent
# indépendamment.
#
# `dense_ms`, `lexical_ms` et `fusion_ms` découpent ce que `retrieve` fait :
# les recherches (jusqu'à quatre classements, question et traduction) puis leur
# fusion RRF. Le temps du nœud qui n'est ni l'un ni l'autre — construction des
# requêtes, journalisation — n'est réclamé par aucun étage et va au résidu.
ETAGES: tuple[str, ...] = (
    "rewrite_ms",
    "translation_ms",
    "dense_ms",
    "lexical_ms",
    "fusion_ms",
    "rerank_ms",
    "reconstruction_ms",
    "generation_ms",
)

# Clés de chronométrage qui AGRÈGENT des étages, et ne sont donc pas des étages.
# `retrieval_ms` est le temps mural du nœud de recherche : il CONTIENT
# `dense_ms`, `lexical_ms` et `fusion_ms`. Il survit parce que la capture
# d'usage a une colonne de ce nom, et parce qu'`AnswerResponse` le publie depuis
# l'origine — mais l'ajouter à `ETAGES` doublerait le comptage de tout l'étage
# de recherche. C'est le piège que ce module existe pour fermer, donc il est
# nommé ici plutôt que laissé à la sagacité du prochain lecteur.
AGREGATS: tuple[str, ...] = ("retrieval_ms",)


class Chrono:
    """Accumulateur de durées par étage, sur toute la traversée du graphe.

    Cumulatif à dessein : la boucle agentique repasse par la recherche et par la
    génération, et ce qui compte pour arbitrer un étage est ce qu'il coûte à la
    réponse entière, pas à son dernier passage.
    """

    def __init__(self) -> None:
        self.etages: dict[str, int] = {}

    @contextmanager
    def mesurer(self, etage: str) -> Iterator[None]:
        """Chronomètre un étage de la partition.

        Lève `KeyError` sur un nom inconnu. C'est délibérément brutal : un étage
        mal nommé n'échoue pas, il DISPARAÎT — son temps se retrouve au résidu,
        et la table de latence continue de s'afficher comme si elle était
        complète.
        """
        if etage not in ETAGES:
            raise KeyError(
                f"« {etage} » n'est pas un étage de la partition : {', '.join(ETAGES)}. "
                "Un étage inconnu verserait son temps au résidu sans le dire."
            )
        depuis = time.monotonic()
        try:
            yield
        finally:
            ecoule = int((time.monotonic() - depuis) * 1000)
            self.etages[etage] = self.etages.get(etage, 0) + ecoule


def cumuler(chronometrage: Mapping[str, Any] | None, etages: Mapping[str, int]) -> dict[str, Any]:
    """Ajoute des durées d'étage à un chronométrage existant, sans en écraser.

    L'état LangGraph est remplacé nœud par nœud : écraser au lieu d'ajouter
    ferait perdre le temps du premier passage dès que la boucle agentique en
    fait un second.
    """
    fusion: dict[str, Any] = dict(chronometrage or {})
    for cle, valeur in etages.items():
        fusion[cle] = int(fusion.get(cle) or 0) + valeur
    return fusion


def decomposer(chronometrage: Mapping[str, Any] | None, total_ms: int) -> dict[str, int]:
    """Rend la partition complète : un champ par étage, plus le résidu.

    `total_ms` est le temps mural mesuré autour de la traversée entière — le
    seul chiffre qui ne dépend d'aucune instrumentation interne, et donc le seul
    contre lequel la partition peut être confrontée.

    Le résidu vaut `total_ms` moins la somme des étages. Il porte tout ce
    qu'aucun étage ne réclame : l'ordonnancement de LangGraph, le
    post-traitement des citations, l'assemblage de la réponse HTTP. Il n'est
    **pas** borné à zéro — voir le module.
    """
    etages = {cle: int((chronometrage or {}).get(cle) or 0) for cle in ETAGES}
    residu = total_ms - sum(etages.values())
    if residu < 0:
        logger.warning(
            "Résidu de chronométrage négatif (%d ms) : la somme des étages (%d ms) dépasse "
            "le temps mural (%d ms). Deux étages se recoupent, ou l'un d'eux mesure un "
            "agrégat (%s) — la table de latence est fausse tant que ce n'est pas tranché.",
            residu,
            sum(etages.values()),
            total_ms,
            ", ".join(AGREGATS),
        )
    return {**etages, "residual_ms": residu, "total_ms": total_ms}

"""La fenêtre qu'une scène POSE quand son sujet est une mise à l'écart.

CE QUE CE MODULE REFERME, ET C'EST UN GESTE DU PILOTE QUI L'A OUVERT. Le
22 septembre 2026, `LLM_NUM_CTX` est passé de 8192 à 32768 dans le `.env` du
poste. Onze scènes sont devenues rouges le jour même — six ici, une dans
`test_answer_endpoint.py`, deux dans `test_precision_contexte.py`, une dans
`test_capture_branchement.py`, une dans `test_champs_du_dialecte.py` — et
personne ne l'a vu pendant deux jours, parce que les arbres de travail n'ont pas
de `.env` et que la porte y restait verte à bon droit.

**La fenêtre élargie ne les faisait pas échouer : elle les privait de leur
sujet.** Une scène qui construit six sources de 4 000 caractères pour observer
ce que le budget écarte n'observe plus rien quand le budget quadruple ; elle ne
mesure pas un code faux, elle ne mesure plus rien, et elle le dit — « le cas de
test ne provoque aucune mise à l'écart ». C'est le motif déjà consigné au
registre : *un test qui hérite d'un défaut change de sujet le jour où le défaut
change.*

POURQUOI UNE FONCTION PLUTÔT QU'UNE FIXTURE AUTOMATIQUE, et c'est délibéré.
Une fixture `autouse` poserait la fenêtre de tout le fichier, y compris des
scènes qui ne la mesurent pas : le réglage redeviendrait ambiant, seulement
ambiant ailleurs. Surtout, `monkeypatch.undo()` annule AUSSI ce qu'une fixture a
posé — ce dépôt s'y est brûlé une fois, vingt-quatre scènes d'un coup. Un appel
écrit DANS la scène est visible à la lecture, ne dépend d'aucun ordre de
fixtures, et survit à un `undo()` puisque la scène peut le refaire. `mesuré` le
22 septembre 2026 : `git grep -n 'monkeypatch.undo()' tests/` ne rend aucune
ligne, donc aucune scène de ce dépôt ne déclenche ce piège aujourd'hui — la
forme est choisie pour qu'il reste sans effet le jour où l'une le fera.

AUCUNE DES TROIS VALEURS N'EST UN DÉFAUT DU CODE, et c'est la seconde moitié du
geste. Poser 8192 aurait redonné aux scènes leur sujet tout en les laissant
vertes sous une mutation qui écrirait `8192` en dur à la place de
`settings.llm_num_ctx` : « mesuré sous le défaut », le motif que
`test_champs_du_dialecte.py` documente sous NB-4 et qu'une mutation survivante
avait déjà trouvé ici. `test_fenetre_heritee.py` refuse que l'une de ces valeurs
redevienne un défaut déclaré.

LE BUDGET EST UNE FONCTION DE TROIS RÉGLAGES, pas d'un seul, et les trois sont
lisibles dans l'environnement : `llm.prompt_window_chars` lit `LLM_NUM_CTX` ET
`LLM_MAX_TOKENS`, `llm.history_budget_chars` lit en plus `HISTORY_WINDOW_SHARE`.
Poser le seul `LLM_NUM_CTX` laisserait la même porte ouverte aux deux autres, et
la refermer une variable à la fois est ce qui a produit ce lot. Ils sont donc
posés ENSEMBLE, ou pas du tout.

Ce que ce module NE fait PAS : il ne touche ni au `.env`, qui vit dans le clone
principal et nulle part ailleurs, ni à `src/`. Le code de production est juste —
c'est un réglage qui a changé, et ce sont les scènes qui le lisaient mal.
"""

from __future__ import annotations

import pytest

# ─── LA FENÊTRE POSÉE, ET LE POURQUOI DE CHAQUE CHIFFRE ──────────────────────
#
# Elle est ÉTROITE — les scènes gardées ici ont pour sujet ce que le budget
# écarte, et un budget qui n'écarte rien n'a pas de sujet — et elle est PROCHE
# de l'ancien plafond hérité (8192 − 4096, soit 14 336 caractères de prompt
# utile) : les comptes que ces scènes avaient réglés sous lui restent ceux
# qu'elles observent. `mesuré` le 22 septembre 2026 : 14 000 caractères ici,
# soit 2,3 % sous la fenêtre héritée.
#
# Aucune n'est le défaut déclaré du champ correspondant (8192, 4096, 0.25), et
# c'est exigé plutôt que remarqué — voir le garde nommé plus haut.
FENETRE_QUI_ECARTE = 8000
GENERATION_RESERVEE = 4000
PART_DE_L_HISTORIQUE = 0.2

# Les trois réglages posés, et le nom que `Settings` leur donne. Cette table est
# le seul endroit à modifier si le budget se met à dépendre d'un quatrième :
# `poser_la_fenetre` et le garde anti-défaut la lisent tous les deux, de sorte
# qu'un réglage ajouté ici est posé ET gardé sans qu'on ait à y penser deux fois.
REGLAGES_POSES: dict[str, int | float] = {
    "llm_num_ctx": FENETRE_QUI_ECARTE,
    "llm_max_tokens": GENERATION_RESERVEE,
    "history_window_share": PART_DE_L_HISTORIQUE,
}


def poser_la_fenetre(monkeypatch: pytest.MonkeyPatch) -> dict[str, int | float]:
    """Pose sur `settings` la fenêtre que la scène appelante mesure.

    À appeler AVANT le premier calcul de budget de la scène — donc avant
    `fit_prompt`, avant `context_budget_chars`, et avant toute requête HTTP qui
    les atteindrait à travers `node_generate`.

    Rend la table posée, pour qu'une scène puisse asserter contre elle sans la
    recopier : un chiffre recopié est un second site, et ce dépôt en a déjà payé
    le prix.
    """
    from src.agent.settings import settings

    for champ, valeur in REGLAGES_POSES.items():
        monkeypatch.setattr(settings, champ, valeur)
    return dict(REGLAGES_POSES)

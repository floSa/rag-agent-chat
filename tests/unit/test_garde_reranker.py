"""Le garde du reranker, et les deux décisions qui lui donnent sa forme.

**LA PANNE QUE CES TESTS EXISTENT POUR RENDRE BRUYANTE.** `rerank_model` avait
TROIS usages dans le dépôt et AUCUN contrôle — le seul des deux modèles à n'en
avoir aucun. Son mal est silencieux : `mesuré` par l'audit du 8 septembre 2026,
un reranker ANGLAIS sur les **41 questions translingues sur 138** du jeu de
référence — **30 %** — coûte **−2,5 points de rappel@10** (97,6 % → 95,1 %).
Aucune exception, aucune ligne de journal, aucun test.

**PREMIÈRE DÉCISION — CONTRE QUOI CONFRONTER, PUISQU'IL N'Y A PAS D'ESTAMPILLE.**
Le lot 3 n'est pas copiable ici. Le modèle d'embedding laisse une trace : le
pipeline inscrit `embedding_model` dans les métadonnées de la collection, et le
garde confronte le réglage à cette estampille — une égalité de noms, exacte. Le
reranker ne produit **rien de persistant** : aucune estampille n'existe, et il
n'y a aucun fait extérieur auquel le confronter. On confronte donc le modèle à
**une propriété de lui-même** — la taille de son vocabulaire — doublée d'un
registre des modèles réellement mesurés sur ce corpus.

**ET LA MESURE QUI INTERDIT D'EN FAIRE UN CLASSIFIEUR.** `mesuré` le
8 septembre 2026 par lecture des seuls `config.json` (60 Ko, aucun poids) :
mBERT, **multilingue**, porte **119 547** entrées de vocabulaire, quand
DeBERTa-v3, **anglais**, en porte **128 100**. Les deux classes SE CHEVAUCHENT :
aucun seuil ne les sépare en général. Le plancher retenu discrimine les familles
en jeu pour un *reranker* — les cross-encoders anglais usuels plafonnent vers
30 000 — et rien de plus. C'est un indice, pas un verdict, et les tests ci-
dessous éprouvent aussi ce que l'indice laisse passer.

**SECONDE DÉCISION — SIGNALER, PAS REFUSER, et le chevauchement ci-dessus en est
la moitié du motif.** Le lot 3 refuse en 503 : un embedding qui ne correspond
pas rend des passages plausibles et FAUX, l'index est inexploitable, et ne rien
servir vaut mieux que servir faux. Un reranker anglais ne rend pas des passages
faux — il en rend MOINS DE BONS, à −2,5 points. Refuser porterait la
disponibilité de 100 % à 0 % pour épargner 2,5 points de rappel, ce qui est pire
sur tous les axes. Et le refus du lot 3 s'appuie sur un fait exact, quand celui-
ci s'appuierait sur un indice dont le chevauchement prouve qu'il se trompe dans
les deux sens : un 503 sur un indice est un garde qu'on arrache au premier faux
positif.

**LE NOM DU MODÈLE ÉCARTÉ N'EST PAS ÉCRIT ICI, ET C'EST UNE CONTRAINTE DU DÉPÔT.**
Il est PUBLIC, et on n'y écrit aucune affectation copiable d'un modèle non
conforme. Les cas monolingues sont donc éprouvés sous un nom FICTIF, avec la
taille de vocabulaire réellement mesurée : c'est le mécanisme qui est testé, et
un nom fictif l'éprouve aussi bien qu'un vrai sans rien apprendre à personne.
"""

import logging

from src.agent import retriever

# Un nom FICTIF, et le vocabulaire réellement mesuré d'un cross-encoder anglais
# usuel (30 522 entrées). Le mécanisme ne lit pas le nom autrement que pour le
# chercher au registre, donc un nom fictif éprouve exactement le même chemin.
_RERANKER_FICTIF_MONOLINGUE = "cross-encoder/exemple-monolingue-L6-v2"
_VOCABULAIRE_ANGLAIS_MESURE = 30_522
# mBERT : le plus PETIT vocabulaire multilingue relevé, et celui qui borne le
# plancher par le bas.
_VOCABULAIRE_MULTILINGUE_LE_PLUS_PETIT = 119_547
# DeBERTa-v3 : anglais, et AU-DESSUS du plancher. C'est le faux vert assumé.
_VOCABULAIRE_ANGLAIS_A_GROS_VOCABULAIRE = 128_100


# ─── Le registre : ce qui a été mesuré ne se signale pas ──────────────────────


def test_le_modele_en_service_ne_declenche_rien() -> None:
    """Le réglage en vigueur doit être MUET, sinon le garde s'auto-discrédite.

    Un garde qui parle sur le réglage en service apprend à l'exploitant à
    ignorer son journal, et c'est ainsi qu'un garde devient décoratif. La valeur
    est LUE dans `settings.py` et non recopiée : un changement de modèle en
    service doit emporter ce test avec lui plutôt que le laisser viser un nom
    que plus rien ne lit.
    """
    from src.agent.settings import Settings

    en_service = str(Settings.model_fields["rerank_model"].default)
    assert en_service in retriever._RERANKERS_MESURES, (
        f"le modèle en service '{en_service}' n'est pas au registre des modèles "
        "mesurés : le garde va signaler le réglage NORMAL à chaque démarrage"
    )
    # Le vocabulaire n'est même pas consulté pour un modèle du registre : il a
    # été mesuré, ce qui est plus fort qu'un indice. On le prouve en passant une
    # valeur qui déclencherait le pire des cas si elle était lue.
    assert (
        retriever.verdict_langue_du_reranker(en_service, _VOCABULAIRE_ANGLAIS_MESURE)
        is None
    ), "le registre ne prime pas sur l'indice : un modèle mesuré est signalé quand même"


# ─── Le défaut lui-même : un reranker monolingue ──────────────────────────────


def test_un_reranker_monolingue_est_signale_avec_son_cout_mesure() -> None:
    """LE CŒUR DU LOT. Le défaut passait en silence ; il parle désormais.

    Le message est éprouvé sur son CONTENU et pas seulement sur son existence :
    un avertissement qui ne dit ni le coût ni la réparation envoie chercher au
    hasard, et c'est la famille de défaut que ce chantier paie le plus cher.
    """
    verdict = retriever.verdict_langue_du_reranker(
        _RERANKER_FICTIF_MONOLINGUE, _VOCABULAIRE_ANGLAIS_MESURE
    )

    assert verdict is not None, (
        "un reranker au vocabulaire de 30 522 entrées ne déclenche RIEN : c'est "
        "exactement l'état d'avant ce lot, où le défaut coûtait 2,5 points en silence"
    )
    niveau, message = verdict
    assert niveau == "warning", niveau
    assert "2,5 points" in message, message
    assert "RERANK_MODEL" in message, (
        f"le message ne nomme pas le réglage à corriger : {message!r}"
    )
    assert str(_VOCABULAIRE_ANGLAIS_MESURE) in message, (
        f"le message ne publie pas la valeur mesurée : {message!r}"
    )


def test_un_vocabulaire_illisible_est_un_avertissement_et_non_un_silence() -> None:
    """« JE NE SAIS PAS » NE SE REPLIE PAS SUR « C'EST BON ».

    C'est la même discipline que `etat_index_lexical`, et elle compte davantage
    ici : `CrossEncoder.config` est un attribut de bibliothèque, pas un contrat.
    Une montée de version qui le déplacerait doit rendre ce garde BAVARD, jamais
    muet — se tromper dans ce sens coûte une ligne de journal, se tromper dans
    l'autre coûte le garde.
    """
    verdict = retriever.verdict_langue_du_reranker(_RERANKER_FICTIF_MONOLINGUE, None)

    assert verdict is not None, (
        "un vocabulaire illisible est traité comme un modèle sain : le garde "
        "devient muet exactement quand il ne sait pas, ce qui est le seul cas interdit"
    )
    niveau, message = verdict
    assert niveau == "warning", niveau
    assert "impossible" in message.lower(), message


# ─── L'absence de mesure n'est pas un défaut ──────────────────────────────────


def test_un_modele_hors_registre_au_vocabulaire_ample_est_un_info_et_pas_un_defaut() -> None:
    """DEUX FAITS DIFFÉRENTS, DEUX NIVEAUX, et le mélange serait un défaut.

    « ce modèle est probablement monolingue » et « personne n'a mesuré ce
    modèle » ne se soignent pas pareil, et annoncer le second comme un
    avertissement apprendrait à ignorer les avertissements. Le niveau est donc
    `info` — le fait est publié, il n'est pas dramatisé.
    """
    verdict = retriever.verdict_langue_du_reranker(
        "cross-encoder/exemple-multilingue-inconnu", _VOCABULAIRE_MULTILINGUE_LE_PLUS_PETIT
    )

    assert verdict is not None, "une absence de mesure doit être DITE, pas passée sous silence"
    niveau, message = verdict
    assert niveau == "info", (
        f"un modèle simplement non mesuré est annoncé en '{niveau}' : le garde "
        "dramatise une absence de mesure et s'use lui-même"
    )
    assert "mesuré" in message, message


def test_le_plancher_laisse_passer_le_plus_petit_vocabulaire_multilingue() -> None:
    """LA BORNE PAR LE BAS, ET ELLE EST MESURÉE.

    mBERT (119 547) est le plus petit vocabulaire multilingue relevé. Un
    plancher posé au-dessus de lui ferait rougir un modèle légitime — le faux
    rouge que la seconde décision refuse. Ce test fixe cette marge : le
    déplacer, c'est décider de perdre mBERT.
    """
    assert retriever._VOCABULAIRE_MULTILINGUE_PLANCHER < _VOCABULAIRE_MULTILINGUE_LE_PLUS_PETIT, (
        f"le plancher {retriever._VOCABULAIRE_MULTILINGUE_PLANCHER} atteint ou "
        f"dépasse mBERT ({_VOCABULAIRE_MULTILINGUE_LE_PLUS_PETIT}) : un reranker "
        "multilingue légitime serait désormais signalé comme monolingue"
    )
    niveau, _ = retriever.verdict_langue_du_reranker(
        "cross-encoder/exemple-mbert", _VOCABULAIRE_MULTILINGUE_LE_PLUS_PETIT
    )
    assert niveau == "info", niveau


def test_le_faux_vert_assume_est_garde_pour_qu_il_reste_ecrit() -> None:
    """CE QUE LE GARDE NE VOIT PAS, ÉPROUVÉ PLUTÔT QU'ÉCRIT.

    DeBERTa-v3 est ANGLAIS et porte 128 100 entrées, donc au-dessus du plancher.
    Il passe, et c'est assumé : un faux vert laisse l'état d'avant ce lot, quand
    un faux rouge sur un modèle légitime apprendrait à ignorer le journal.

    Ce test n'existe pas pour célébrer le trou : il existe pour qu'on ne
    puisse pas croire le garde plus fort qu'il n'est. Le jour où quelqu'un
    resserre le plancher, ce test rougira et l'obligera à relire le
    chevauchement mesuré avant de décider.
    """
    niveau, _ = retriever.verdict_langue_du_reranker(
        "cross-encoder/exemple-anglais-a-gros-vocabulaire",
        _VOCABULAIRE_ANGLAIS_A_GROS_VOCABULAIRE,
    )
    assert niveau == "info", (
        f"le verdict est '{niveau}' : le plancher a été resserré et attrape "
        "désormais un vocabulaire de 128 100. Relire le chevauchement mesuré au "
        "site avant de garder ce changement — mBERT est à 119 547"
    )


# ─── L'extraction de la propriété, et le chemin du chargement ─────────────────


class _FauxCrossEncoder:
    """Le strict minimum que `_vocabulaire_du_reranker` lit du modèle chargé."""

    def __init__(self, config: object) -> None:
        self.config = config


class _Config:
    def __init__(self, vocab_size: object) -> None:
        self.vocab_size = vocab_size


def test_la_taille_du_vocabulaire_est_lue_sur_le_modele_charge() -> None:
    """Aucune seconde lecture : la propriété est prise sur l'objet en mémoire."""
    assert (
        retriever._vocabulaire_du_reranker(_FauxCrossEncoder(_Config(250_002))) == 250_002
    )


def test_une_propriete_absente_ou_illisible_rend_none_sans_lever() -> None:
    """Trois façons pour la bibliothèque de changer sous nous, et aucune ne lève.

    Une exception ici casserait le CHARGEMENT du reranker, donc la recherche —
    un garde qui provoque la panne qu'il surveille. C'est le cas que
    `_vocabulaire_du_reranker` absorbe, et l'absorption est bornée à
    `TypeError`/`ValueError` : elle ne masque pas une panne d'une autre nature.
    """
    assert retriever._vocabulaire_du_reranker(object()) is None
    assert retriever._vocabulaire_du_reranker(_FauxCrossEncoder(object())) is None
    assert retriever._vocabulaire_du_reranker(_FauxCrossEncoder(_Config("ni un entier"))) is None


def test_le_chargement_du_reranker_journalise_le_verdict(monkeypatch, caplog) -> None:
    """LE BRANCHEMENT, ET IL EST TESTÉ DEPUIS LE CÔTÉ QUI PRODUIT L'EFFET.

    Les tests ci-dessus éprouvent une fonction pure ; celui-ci prouve qu'elle
    est réellement APPELÉE au chargement. Sans lui, le garde pourrait être
    parfait et jamais branché — c'est la panne « le code est juste, le garde
    manque » retournée contre elle-même, et ce chantier l'a payée huit fois.

    Le `lru_cache` de `_get_rerank_model` est vidé : sans cela, un chargement
    survenu dans un autre test rendrait celui-ci vert sans rien exécuter.
    """
    charges: list[str] = []

    def _faux_constructeur(nom: str) -> _FauxCrossEncoder:
        charges.append(nom)
        return _FauxCrossEncoder(_Config(_VOCABULAIRE_ANGLAIS_MESURE))

    monkeypatch.setattr(retriever, "CrossEncoder", _faux_constructeur)
    monkeypatch.setattr(
        retriever.settings, "rerank_model", _RERANKER_FICTIF_MONOLINGUE, raising=False
    )
    retriever._get_rerank_model.cache_clear()
    try:
        with caplog.at_level(logging.INFO, logger=retriever.logger.name):
            retriever._get_rerank_model()
    finally:
        retriever._get_rerank_model.cache_clear()

    assert charges == [_RERANKER_FICTIF_MONOLINGUE], (
        f"le modèle n'a pas été chargé par le chemin testé ({charges}) : ce test "
        "ne prouve rien sur le branchement du garde"
    )
    avertissements = [e for e in caplog.records if e.levelno == logging.WARNING]
    assert avertissements, (
        "le chargement d'un reranker monolingue n'a produit AUCUN avertissement : "
        f"le garde n'est pas branché. Journal vu : {[e.message for e in caplog.records]}"
    )
    assert "2,5 points" in avertissements[0].getMessage(), avertissements[0].getMessage()


# ─── La saturation de sigmoïde, et l'inférence fausse qu'elle a produite ──────

# Les logits que l'audit relève pour un cross-encoder anglais sur une question
# française. Site canonique du motif corrigé : `src/agent/settings.py`, au
# champ `rerank_model`.
_LOGITS_RELEVES = (-6.8, -7.5, -8.2, -9.0, -9.9, -10.6, -11.35)


def test_une_etendue_quasi_nulle_preserve_strictement_l_ordre() -> None:
    """L'INFÉRENCE FAUSSE QUE CE TEST EMPÊCHE DE REVENIR.

    Le site de `rerank_model` a porté, et le pilote du chantier a repris sans
    le mesurer, que « étendue 0,0 % … **soit un classement au hasard** ». La
    conclusion ne suit pas : `_sigmoid` SATURE sur les logits très négatifs, et
    une étendue quasi nulle est un artefact d'échelle, pas une perte d'ordre.

    Ce test tient les deux moitiés de la correction — l'étendue EST minuscule,
    et l'ordre EST strictement préservé. Tant qu'il est vert, personne ne peut
    relire une étendue plate comme un classement au hasard sans le faire rougir.

    Aucun modèle n'est chargé : la propriété est celle du MÉCANISME, et se
    mesure sur la seule fonction. C'est ce qui la rend gardable.
    """
    pertinences = [retriever._sigmoid(logit) for logit in _LOGITS_RELEVES]

    etendue = max(pertinences) - min(pertinences)
    assert etendue < 0.002, (
        f"l'étendue vaut {etendue:.6f} : la saturation qui explique le « 0,0 % » "
        "du site n'est plus reproduite, et le motif écrit là-bas ne tient plus"
    )
    # `strict=False` EXPLICITE, et non par omission : un appariement deux-à-deux
    # compare n-1 couples pour n valeurs, donc les deux arguments ont des
    # longueurs volontairement différentes. `strict=True` y lève — c'est le
    # premier réflexe, et il est faux ici.
    voisins = zip(pertinences, pertinences[1:], strict=False)
    assert all(a > b for a, b in voisins), (
        f"l'ordre n'est PAS strictement préservé : {pertinences}. C'est la moitié "
        "décisive de la correction du motif — sans elle, « étendue nulle donc "
        "classement au hasard » redeviendrait une inférence défendable"
    )
    # Et la monotonie n'est pas une propriété de ces sept points seulement.
    croissants = [retriever._sigmoid(x) for x in (-40.0, -11.35, -6.8, 0.0, 3.0, 40.0)]
    assert croissants == sorted(croissants), croissants

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

import asyncio
import json
import logging
import pathlib
import subprocess
import sys

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


def test_les_mesures_du_registre_sont_dites_a_l_exploitant() -> None:
    """LES VALEURS DU REGISTRE SONT LUES, ET CE TEST EST CE QUI LES MAINTIENT.

    `mesuré` le 9 septembre 2026 : le registre était un `dict[str, str]` dont
    **les valeurs étaient mortes** — les trois usages ne parcouraient que les
    clés, et les vider toutes laissait 643 tests verts. De la documentation
    déguisée en donnée.

    Le message `info` est celui qui rend la chose visible : il dit à l'exploitant
    « ce modèle n'a PAS été mesuré » sans jamais lui dire ce qui A été mesuré sur
    celui du registre, alors que la réponse est écrite deux lignes plus haut dans
    le même fichier. Ce test asserte que chaque mesure du registre atteint le
    journal ; vider une valeur le fait rougir.
    """
    verdict = retriever.verdict_langue_du_reranker(
        _RERANKER_FICTIF_MONOLINGUE, _VOCABULAIRE_MULTILINGUE_LE_PLUS_PETIT
    )
    assert verdict is not None
    niveau, message = verdict
    assert niveau == "info", niveau

    assert retriever._RERANKERS_MESURES, "le registre est vide : ce test ne mesure rien"
    for nom, mesure in retriever._RERANKERS_MESURES.items():
        assert mesure.strip(), (
            f"le registre porte {nom!r} sans aucune mesure : une entrée sans sa "
            "mesure est un nom qu'on croit validé sans savoir par quoi"
        )
        assert nom in message and mesure in message, (
            "le message d'absence de mesure ne dit pas ce qui A été mesuré sur "
            f"{nom!r} — la valeur du registre est redevenue morte, et le garde "
            f"retient l'information dont il constate l'absence. Message : {message}"
        )


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
    `_vocabulaire_du_reranker` absorbe.

    **LA PHRASE QUI SUIVAIT ÉTAIT FAUSSE ET A ÉTÉ RETIRÉE LE 9 SEPTEMBRE 2026** :
    elle disait l'absorption « bornée à `TypeError`/`ValueError`, elle ne masque
    pas une panne d'une autre nature » — et ces trois scènes-là ne sont
    justement PAS celles qui levaient. Les deux `object()` ci-dessous rendent
    `None` par le `default` de `getattr`, jamais par l'`except`. La borne
    étroite laissait donc propager tout ce qui LÈVE en lisant la propriété, et
    c'est mesuré : voir
    `TestLaLectureDefensiveDuVocabulaireNeCassePasLaRecherche` juste dessous, où
    les deux directions sont désormais gardées.
    """
    assert retriever._vocabulaire_du_reranker(object()) is None
    assert retriever._vocabulaire_du_reranker(_FauxCrossEncoder(object())) is None
    assert retriever._vocabulaire_du_reranker(_FauxCrossEncoder(_Config("ni un entier"))) is None


class TestLaLectureDefensiveDuVocabulaireNeCassePasLaRecherche:
    """LA SURFACE D'EXCEPTION DE LA LECTURE DÉFENSIVE, QUE RIEN NE GARDAIT.

    **LE DÉFAUT, `mesuré` le 9 septembre 2026.** `_vocabulaire_du_reranker`
    écrivait que son échec rend `None`, traité en `warning`, et qu'« une montée
    de version rendrait ce garde bavard, pas muet ». L'`except` ne retenait que
    `TypeError` et `ValueError`. Une sonde de dix lignes, sans charger de
    modèle, a montré que la phrase ne tenait que pour l'attribut ABSENT : un
    `config` qui est une `property` levant `RuntimeError`, `OSError`, `KeyError`
    ou `ImportError` **propageait**.

    **ET LA PROPAGATION N'ÉTAIT PAS BAVARDE, ELLE ÉTAIT MORTELLE.**
    `_get_rerank_model()` est appelé par `rerank()`, que `node_rerank` appelle
    sans aucun `try` : l'exception traversait tout et cassait la recherche. *Un
    garde qui provoque la panne qu'il surveille* — ce que le docstring du test
    voisin nomme lui-même sans l'avoir gardé.

    **CE N'EST PAS THÉORIQUE.** En sentence-transformers 5.6.1 — la version
    épinglée, `vérifié` le 9 septembre 2026 — `CrossEncoder.config` **est** une
    `property`, chaînée sur une seconde (`transformers_model`) qui parcourt la
    hiérarchie de modules du modèle. La version installée est sûre ; ce garde
    existe pour celle qui vient.

    **LES DEUX DIRECTIONS, et la seconde est celle qui rend l'élargissement
    tenable** : ce qui doit être absorbé l'est, et ce qui doit traverser
    traverse — `KeyboardInterrupt` et `SystemExit` en tête. Un `except` qui
    avale tout est aussi inutile qu'un `except` qui n'avale rien.
    """

    class _ConfigQuiLeve:
        """Un `config` qui est une `property` levant — la forme réelle de 5.6.1."""

        def __init__(self, nature: type[BaseException]) -> None:
            self._nature = nature

        @property
        def config(self) -> object:
            raise self._nature("la bibliothèque a changé sous nous")

    # LES SIX NATURES PLAUSIBLES, et la liste est raisonnée plutôt que
    # inventée. `AttributeError` : l'attribut déplacé, le cas nominal d'une
    # montée de version. `RuntimeError` : un modèle mal initialisé, ce que lève
    # `transformers` quand un module attendu manque. `OSError` : une lecture de
    # `config.json` faite paresseusement par la property. `KeyError` : une clé
    # absente d'un dictionnaire de configuration. `ImportError` : un backend
    # optionnel (`optimum-onnx`, `optimum-intel`) que la chaîne de property
    # touche. `NotImplementedError` : une property qui refuse le cas.
    #
    # **CETTE PHRASE ÉTAIT FAUSSE, ET C'EST LA CORRECTION DU 9 SEPTEMBRE 2026.**
    # Elle affirmait : « les quatre du milieu PROPAGEAIENT ; les deux autres
    # étaient déjà absorbées, l'une par le `default` de `getattr`, l'autre par
    # l'`except` étroit ». La seconde moitié est démentie par la mesure.
    #
    # `NotImplementedError` **est une sous-classe de `RuntimeError`** —
    # `mesuré` le 9 septembre 2026, `NotImplementedError.__mro__` rend
    # `(NotImplementedError, RuntimeError, Exception, BaseException, object)` —
    # donc `except (TypeError, ValueError)` ne l'attrapait PAS. Elle propageait
    # comme les quatre autres.
    #
    # Sonde rejouée le même jour, `except` étroit reconstruit à l'identique,
    # sur ces six natures :
    #
    #     ABSORBÉES   : AttributeError                                    -> **1**
    #     PROPAGEANTES: RuntimeError, OSError, KeyError, ImportError,
    #                   NotImplementedError                               -> **5**
    #
    # Cinq des six propageaient, et une seule était absorbée — par le `default`
    # de `getattr`, jamais par l'`except`. *Une sous-classe lue comme une classe
    # sœur : le compte était juste sur quatre noms et faux sur le sixième.*
    #
    # ── « SIX » EST DÉFINI ICI, ET CE N'EST PAS LE « SEPT » DU SITE ──
    #
    # `retriever.py` écrit « quatre natures sur les sept sondées ». Ce fichier
    # énumère six natures ici, et **neuf** en tout avec celles qui doivent
    # traverser. Les trois comptes sont exacts sous trois définitions, et leur
    # silence sur celles-ci était le défaut. Les définitions sont désormais
    # écrites aux deux sites. Celle-ci :
    #
    #     **SIX = les natures dont l'ABSORPTION est sondée par ce fichier**,
    #     choisies pour être plausibles sous une montée de version de
    #     `sentence-transformers`, et non pour reproduire la sonde d'origine.
    #     Les natures qui doivent TRAVERSER sont comptées à part —
    #     `test_l_interruption_l_annulation_et_la_sortie_traversent_toujours`
    #     en tient **trois**.
    #
    # Celle de `retriever.py` : les sept natures que la sonde du 9 septembre
    # 2026 a soumises à l'`except` étroit, `TypeError` et `ValueError`
    # comprises — deux natures que ce fichier ne sonde pas, parce qu'un
    # `except Exception` les couvre sans qu'on ait à les nommer.
    _NATURES = (
        AttributeError,
        RuntimeError,
        OSError,
        KeyError,
        ImportError,
        NotImplementedError,
    )

    def test_la_liste_des_six_natures_ne_retrecit_pas_en_silence(self) -> None:
        """LE TROU QUE MA PROPRE MUTATION M-j A TROUVÉ, ET IL EST DANS CE TEST.

        `mesuré` le 9 septembre 2026 : retirer `NotImplementedError` de
        `_NATURES` laissait les **16** tests de ce fichier VERTS. Une liste de
        sondes qui rétrécit ne fait rougir personne — le test voisin sonde
        simplement une nature de moins, et sa couverture se perd en silence.

        **UN COMPTE EST LÉGITIME ICI, ET LA DISTINCTION IMPORTE.** Ce fichier et
        `test_coherence_depot.py` refusent d'asserter des comptes, et ils ont
        raison : un inventaire d'occurrences GRANDIT à chaque test ajouté, et un
        garde qui rougit sur l'événement normal enseigne le geste « monter le
        chiffre » — la leçon du §4.35. `_NATURES` n'est pas un inventaire : c'est
        une liste FERMÉE et raisonnée, dont la seule évolution normale est de
        s'allonger. Un plancher la garde donc sans jamais rougir à tort.

        **ET IL TIENT LE FAIT QUI AVAIT ÉTÉ ÉCRIT FAUX.**
        `NotImplementedError` est une sous-classe de `RuntimeError`, donc
        l'`except (TypeError, ValueError)` d'avant le 9 septembre 2026 ne
        l'attrapait pas : elle propageait, contrairement à ce que le commentaire
        de `_NATURES` affirmait. Si la hiérarchie de la bibliothèque standard
        changeait, ce commentaire redeviendrait faux, et c'est cette assertion
        qui le dirait.
        """
        assert len(self._NATURES) >= 6, (
            f"la liste des natures sondées est tombée à {len(self._NATURES)} : "
            f"{[n.__name__ for n in self._NATURES]}. Une sonde retirée ne fait "
            "rougir personne, et sa couverture se perd en silence. Allonger cette "
            "liste est normal ; la raccourcir demande une mesure écrite"
        )
        assert len(set(self._NATURES)) == len(self._NATURES), (
            f"une nature est répétée : {[n.__name__ for n in self._NATURES]}. Le "
            "plancher ci-dessus serait alors tenu par un doublon"
        )
        assert NotImplementedError in self._NATURES, (
            "`NotImplementedError` a quitté la liste. C'est la nature dont le "
            "commentaire de `_NATURES` a écrit le comportement FAUX — elle "
            "propageait, n'étant pas couverte par l'`except` étroit — et c'est "
            "elle qui rend la correction du 9 septembre 2026 relisible"
        )
        assert issubclass(NotImplementedError, RuntimeError), (
            "`NotImplementedError` ne dérive plus de `RuntimeError` : le "
            "commentaire de `_NATURES` explique la correction du 9 septembre 2026 "
            "par cette hiérarchie, et il vient de redevenir faux. Remesure "
            "`NotImplementedError.__mro__` et réécris-le"
        )
        for nature in self._NATURES:
            assert not issubclass(nature, (KeyboardInterrupt, SystemExit)), (
                f"{nature.__name__} est une nature qui doit TRAVERSER, et elle est "
                "dans la liste de celles qui doivent être absorbées : les deux "
                "sens de ce garde viennent de se contredire"
            )

    def test_aucune_des_six_natures_ne_traverse_la_lecture(self) -> None:
        """LA PREUVE D'ATTEINTE EST DANS LE MESSAGE : chaque nature est nommée.

        Un test qui se contenterait d'un `is None` global ne dirait pas
        LAQUELLE des six est retombée à travers. Chacune est donc sondée
        séparément, et l'échec la nomme.
        """
        for nature in self._NATURES:
            modele = self._ConfigQuiLeve(nature)
            # Preuve que la sonde ATTEINT son cas : la property lève bien.
            leve = False
            try:
                _ = modele.config
            except nature:
                leve = True
            assert leve, (
                f"la sonde n'atteint pas son cas pour {nature.__name__} : la "
                "property ne lève pas, donc ce tour de boucle ne mesure rien"
            )

            assert retriever._vocabulaire_du_reranker(modele) is None, (
                f"{nature.__name__} traverse la lecture défensive du vocabulaire. "
                "`_get_rerank_model()` est appelé par `rerank()` sans aucun `try` : "
                "cette exception ne rend pas le garde bavard, elle casse la "
                "recherche — un garde qui provoque la panne qu'il surveille"
            )

    def test_une_property_qui_leve_sur_vocab_size_est_absorbee_aussi(self) -> None:
        """Le SECOND maillon de la chaîne, et il n'était pas gardé non plus.

        `config` peut être lisible et `vocab_size` lever : c'est exactement la
        forme de 5.6.1, où `config` délègue à un `PretrainedConfig` dont les
        attributs sont eux-mêmes calculés.
        """

        class _VocabQuiLeve:
            @property
            def vocab_size(self) -> int:
                raise RuntimeError("attribut calculé, et le calcul a échoué")

        modele = _FauxCrossEncoder(_VocabQuiLeve())
        leve = False
        try:
            _ = modele.config.vocab_size
        except RuntimeError:
            leve = True
        assert leve, "la sonde n'atteint pas son cas : `vocab_size` ne lève pas"

        assert retriever._vocabulaire_du_reranker(modele) is None

    def test_l_interruption_l_annulation_et_la_sortie_traversent_toujours(
        self,
    ) -> None:
        """LE SENS DANGEREUX DE L'ÉLARGISSEMENT, ET C'EST SA BORNE.

        `except Exception` et non `except BaseException` : un
        `KeyboardInterrupt` ou un `SystemExit` doit traverser cette lecture
        comme il traverse le reste du programme. Un `except` qui avale tout
        rendrait ce garde impossible à interrompre — et il serait alors aussi
        inutile que l'`except` étroit qu'il remplace, dans l'autre sens.

        **`asyncio.CancelledError` REJOINT CETTE LISTE LE 9 SEPTEMBRE 2026, ET
        ELLE Y MANQUAIT.** Elle traversait déjà — `vérifié` ce jour-là,
        `asyncio.CancelledError.__mro__` rend `(CancelledError, BaseException,
        object)` sous Python 3.12.13, et `issubclass(…, Exception)` rend
        `False` — et c'est le bon comportement : *une annulation doit propager.*
        Mais elle ne le devait à rien qui fût écrit ou éprouvé : elle le devait
        à une propriété de la bibliothèque standard que personne n'avait
        relevée. *On cherchait un trou et on a trouvé un choix juste ; un choix
        juste que rien ne garde est un choix qu'un lot suivant défait.*

        Le cas est réel sur ce dépôt : `pyproject.toml` porte
        `asyncio_mode = "strict"` et le graphe est piloté par `ainvoke` et
        `astream`. `node_rerank` est aujourd'hui un nœud **synchrone**, donc
        l'annulation arrive d'abord sur la coroutine qui attend — raison de plus
        pour garder la propriété maintenant : le jour où ce nœud devient
        `async`, un `except BaseException` rendrait la requête inannulable, et
        rien ne le dirait.
        """
        for nature in (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
            # PREUVE D'ATTEINTE : la nature sondée est bien HORS de `Exception`.
            # Sans elle, ajouter par erreur une nature ordinaire à cette liste
            # ferait rougir le test pour la bonne raison mais sur le mauvais
            # fait — et une nature ordinaire DOIT être absorbée.
            assert not issubclass(nature, Exception), (
                f"{nature.__name__} dérive de `Exception` : elle doit être "
                "ABSORBÉE, pas traverser. C'est le test voisin qui la sonde"
            )
            modele = self._ConfigQuiLeve(nature)
            try:
                retriever._vocabulaire_du_reranker(modele)
            except nature:
                continue
            raise AssertionError(
                f"{nature.__name__} est désormais AVALÉ par la lecture défensive : "
                "l'`except Exception` est devenu un `except BaseException`, et ce "
                "garde n'est plus interruptible"
            )

    def test_le_verdict_reste_un_avertissement_et_non_un_silence(self) -> None:
        """L'ABSORPTION NE DOIT PAS DEVENIR UN SILENCE, et c'est le point.

        Élargir l'`except` sans cette assertion échangerait une panne bruyante
        contre un garde muet — le troc que `verdict_langue_du_reranker` refuse
        explicitement. Le `None` rendu par l'absorption doit produire un
        `warning`, pas un `None` de verdict.
        """
        modele = self._ConfigQuiLeve(RuntimeError)
        vocabulaire = retriever._vocabulaire_du_reranker(modele)
        assert vocabulaire is None

        verdict = retriever.verdict_langue_du_reranker("un/modele-hors-registre", vocabulaire)
        assert verdict is not None, (
            "une propriété illisible ne dit plus rien : l'absorption est devenue "
            "un silence, ce qui est le seul choix interdit ici"
        )
        niveau, message = verdict
        assert niveau == "warning", f"niveau attendu 'warning', obtenu {niveau!r}"
        assert "vocabulaire" in message


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
    message = avertissements[0].getMessage()
    # LES TROIS ASSERTIONS SUIVANTES SONT LA RÉPARATION DE B-1, ET LEUR ORDRE
    # EST CELUI DES TROIS QUESTIONS AUXQUELLES « il y a un avertissement » NE
    # RÉPOND PAS. La version d'origine se contentait de `"2,5 points"`, que les
    # DEUX messages `warning` portent : elle éprouvait que quelque chose
    # avertit, jamais QUOI.
    assert _RERANKER_FICTIF_MONOLINGUE in message, (
        "l'avertissement ne NOMME pas le réglage du reranker. Le garde a donc lu "
        "un AUTRE réglage que `rerank_model` — et il avertit alors sur un modèle "
        "qui n'est pas celui qu'il croit surveiller, ce qui est pire que se "
        f"taire. Message vu : {message}"
    )
    assert str(_VOCABULAIRE_ANGLAIS_MESURE) in message, (
        "l'avertissement ne rapporte pas le vocabulaire LU sur le modèle chargé "
        f"({_VOCABULAIRE_ANGLAIS_MESURE}). C'est donc la branche « vocabulaire "
        "illisible » qui a parlé : le câblage n'a jamais lu la propriété du "
        f"modèle, et son verdict ne décrit rien de lui. Message vu : {message}"
    )
    assert "2,5 points" in message, message


# ─── Le modèle EN SERVICE, par le vrai chemin, dans un processus à part ───────

# Le vocabulaire du reranker en service. **CITÉ, non mesuré ici** : il vient de
# l'audit du 9 septembre 2026 (`documentation/axes_amelioration.md` §4.33), par
# lecture du seul `config.json`. Le test ne DÉPEND pas de sa justesse — le
# silence attendu vient du registre, qui court-circuite avant tout seuil —, mais
# il monte la scène réelle plutôt qu'une scène plausible, et un chiffre inventé
# ferait croire à une mesure qui n'a pas eu lieu.
_VOCABULAIRE_DU_MODELE_EN_SERVICE = 250_002

_RACINE = pathlib.Path(__file__).resolve().parents[2]

# La scène tourne dans un processus NEUF, et c'est structurel, pas décoratif :
# `_get_rerank_model` porte un `lru_cache`, et une seconde scène dans ce
# processus-ci serait servie par la première sans rien exécuter — elle rendrait
# vert quoi qu'on lui fasse. Le sous-processus rend aussi l'état des modules
# vierge : aucun `monkeypatch` d'un autre test ne peut l'avoir touché.
_SCENE_DU_MODELE_EN_SERVICE = """
import json
import logging

from src.agent import retriever
from src.agent.settings import settings

charges = []
lectures = []


class _ConfigInstrumentee:
    # Une `property`, comme dans sentence-transformers : chaque lecture se
    # compte, et c'est ce compteur qui prouve que le cablage lit REELLEMENT le
    # vocabulaire du modele charge, au lieu de le supposer.
    @property
    def vocab_size(self):
        lectures.append("vocab_size")
        return {vocabulaire}


class _ModeleBouche:
    def __init__(self):
        self.config = _ConfigInstrumentee()


def _faux_constructeur(nom):
    charges.append(nom)
    return _ModeleBouche()


class _Collecteur(logging.Handler):
    def __init__(self):
        super().__init__()
        self.vus = []

    def emit(self, record):
        self.vus.append([record.levelname, record.getMessage()])


retriever.CrossEncoder = _faux_constructeur
collecteur = _Collecteur()
retriever.logger.addHandler(collecteur)
retriever.logger.setLevel(logging.DEBUG)
retriever.logger.propagate = False

retriever._get_rerank_model.cache_clear()
retriever._get_rerank_model()

print(json.dumps({{
    "reglage": settings.rerank_model,
    "charges": charges,
    "lectures": len(lectures),
    "journal": collecteur.vus,
}}))
"""


def test_le_modele_en_service_ne_dit_rien_par_le_chemin_reel() -> None:
    """LA SECONDE MOITIÉ DU CÂBLAGE, ET C'EST ELLE QUE LE LOT AVAIT MANQUÉE.

    `test_le_modele_en_service_ne_declenche_rien` éprouve le silence sur le
    réglage en service — mais il appelle la fonction PURE, et ne voit rien du
    câblage. `mesuré` le 9 septembre 2026 : faire lire au site d'appel
    `embedding_model_name` au lieu de `rerank_model`, et ne jamais lire le
    vocabulaire, laissait **643 tests verts** ; sous cette mutation le réglage
    NORMAL se mettait à avertir en nommant le mauvais modèle. *Le bon test, du
    mauvais côté de la frontière.*

    Ce test remonte la même exigence du côté qui produit l'effet, et il asserte
    TROIS faits que « rien n'a été journalisé » ne donne pas à lui seul :

    - le modèle a bien été chargé, et sous le réglage réel — sans quoi un
      sous-processus qui échouerait tôt rendrait un silence trivial. C'est la
      preuve d'atteinte, et elle est assertée, pas supposée ;
    - le vocabulaire du modèle chargé a bien été LU. La `property` compte ses
      lectures : un câblage qui passerait `None` en dur laisserait ce compteur à
      zéro, alors même que le verdict resterait silencieux — le registre
      court-circuite avant tout seuil, donc le silence seul ne prouve rien ;
    - le journal ne porte QUE la ligne de chargement. Pas de verdict, d'aucun
      niveau : le réglage en service est muet par le vrai chemin, et un garde
      qui parle sur le réglage en service apprend à ignorer son journal.
    """
    acheve = subprocess.run(
        [
            sys.executable,
            "-c",
            _SCENE_DU_MODELE_EN_SERVICE.format(
                vocabulaire=_VOCABULAIRE_DU_MODELE_EN_SERVICE
            ),
        ],
        capture_output=True,
        text=True,
        cwd=str(_RACINE),
        check=False,
        timeout=300,
    )
    assert acheve.returncode == 0, (
        f"la scène n'a pas abouti (rc={acheve.returncode}) — le silence qu'elle "
        f"mesurerait serait celui d'un processus mort.\n{acheve.stderr[-3000:]}"
    )
    releve = json.loads(acheve.stdout.strip().splitlines()[-1])

    assert releve["charges"] == [releve["reglage"]], (
        "le modèle n'a pas été chargé sous le réglage du reranker "
        f"({releve['charges']} contre {releve['reglage']!r}) : cette scène "
        "n'atteint pas le chemin qu'elle prétend éprouver"
    )
    assert releve["lectures"] >= 1, (
        "le vocabulaire du modèle chargé n'a JAMAIS été lu. Le câblage ne "
        "transmet donc pas la propriété du modèle au verdict, et son silence "
        "ici ne décrit rien du modèle en service"
    )
    verdicts = [
        (niveau, texte)
        for niveau, texte in releve["journal"]
        if "Chargement du modèle de reranking" not in texte
    ]
    assert verdicts == [], (
        "le réglage EN SERVICE a produit un verdict par le chemin réel. Un garde "
        "qui parle sur le réglage en vigueur s'auto-discrédite, et c'est "
        "exactement ce que produit un câblage qui lit le mauvais réglage. "
        f"Verdicts vus : {verdicts}"
    )


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

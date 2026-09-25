"""Le plafond de RÉCUPÉRATION du jeu dispersé, et les cinq façons de le mal lire.

Le §4.76 a mesuré que **67 ancrages sur 120** n'atteignent pas le top-10 du
reranker, et il a nommé la suite : *ce jeu borne d'abord la récupération, et
personne ne sait pourquoi*. `scripts/mesurer_recuperation.py` répond par un
**tableau de causes**, et un tableau de causes se casse de cinq façons dont
aucune ne lève d'erreur :

1. **UNE CAUSE QUI NE PEUT PAS ÊTRE VUE.** Une ligne comptée à `0` par un
   détecteur incapable de la reconnaître se lit comme une absence de défaut.
   Chaque cause a donc ici son **témoin**, qui est un contrôle positif : le
   classeur DOIT la rendre sur une observation faite pour elle.
2. **UN ARBRE QUI N'EST PAS EXCLUSIF.** Les causes sont définies par l'ordre où
   elles sont essayées ; une observation qui satisferait deux marches et dont la
   seconde gagnerait ferait fuir un compte vers sa voisine sans rien casser.
3. **UNE TABLE QUI NE SOMME PAS.** Sans la ligne « non expliqué », le dernier
   `return` ramasse tout ce que l'arbre n'a pas su nommer, et la table se boucle
   en accusant la dernière cause essayée.
4. **UNE BASE QUI N'EST PAS CELLE DU §4.76.** Le contrôle positif compare trois
   comptes ; comparé à une AUTRE profondeur, il compare deux grandeurs qui
   portent le même nom. Il doit refuser la profondeur avant de comparer.
5. **DEUX ÉTATS DES STORES DANS UN MÊME TABLEAU.** Le pipeline voisin va purger
   puis réingérer. Un banc qui ne refuse pas rend un tableau dont chaque ligne
   est juste et dont le total ne décrit rien.

Les témoins portent LEUR COMPTE — la leçon de `test_mesure_de_la_selection.py` :
sans compte écrit, un banc cassé rend « une liste » et le test la trouve
plausible.
"""

import importlib.util
import json
import pathlib
import sys

import pytest

_RACINE = pathlib.Path(__file__).resolve().parents[2]
_BANC = _RACINE / "scripts" / "mesurer_recuperation.py"
_BILAN_PROD = _RACINE / "runs" / "2026-09-24-recuperation-p50.json"
_BILAN_CAUSES = _RACINE / "runs" / "2026-09-24-recuperation-causes.json"

# LES TROIS CHIFFRES DU §4.76, recopiés ici pour que le garde soit lisible au
# site où il s'exerce. Ce sont des comptes d'ancrages ABSENTS, à profondeur de
# production, sur les stores du 24 septembre 2026.
_ABSENTS_4_76 = {"dense": 56, "fusion": 46, "rerank": 67}
_ANCRAGES = 120


def _charger(chemin: pathlib.Path):
    spec = importlib.util.spec_from_file_location(chemin.stem, chemin)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[chemin.stem] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def banc():
    return _charger(_BANC)


def _observation(**ecarts):
    """Une observation NEUTRE, sur laquelle chaque témoin ne change QUE son motif.

    Neutre veut dire : rien n'est trouvé nulle part, le texte est indexé, et
    l'oracle a été joué sans rien ramener — c'est-à-dire la cause `texte_indexe`.
    Un témoin qui partirait d'une observation déjà classée ailleurs pourrait
    mourir par un autre chemin que celui qu'il vise.
    """
    base = {
        "rang_dense_prod": None,
        "rang_lexical_prod": None,
        "rang_fusion_prod": None,
        "rang_rerank_prod": None,
        "rang_fusion_profond": None,
        "rang_rerank_profond": None,
        "indexe": True,
        "oracle_rerank": None,
    }
    base.update(ecarts)
    return base


# LE TÉMOIN DE CHAQUE CAUSE, ET C'EST LE CONTRÔLE POSITIF DE LA TABLE. Une cause
# comptée à 0 dans le bilan doit l'être par un détecteur qui sait la voir ; la
# preuve qu'il sait la voir est ici, et elle est exigée pour les HUIT.
_TEMOINS = {
    "arrive": _observation(rang_rerank_prod=4, rang_fusion_prod=9),
    "hors_chromadb": _observation(indexe=False),
    "ecarte_par_le_reranker": _observation(rang_fusion_prod=37),
    "profondeur_recupere": _observation(rang_fusion_profond=310, rang_rerank_profond=6),
    "profondeur_insuffisante": _observation(rang_fusion_profond=310),
    "requete_unique": _observation(oracle_rerank=2),
    "texte_indexe": _observation(),
    "non_explique": {k: v for k, v in _observation().items() if k != "oracle_rerank"},
}


@pytest.mark.parametrize("attendue", sorted(_TEMOINS))
def test_chaque_cause_a_un_temoin_que_le_classeur_sait_voir(banc, attendue):
    """CONTRÔLE POSITIF, cause par cause : un 0 dans la table est alors un 0 mesuré.

    Sans ce test, une cause pourrait valoir 0 parce qu'aucune observation ne
    l'atteint — une branche morte de l'arbre — et le rapport lirait « cette
    hypothèse est écartée » là où elle n'a jamais été regardée.
    """
    assert banc.classer_la_cause(_TEMOINS[attendue]) == attendue


def test_les_temoins_couvrent_les_huit_causes_declarees(banc):
    """Le registre des causes et les témoins disent la MÊME liste, dans les deux sens.

    Ajouter une cause au classeur sans lui donner de témoin la rendrait
    invisible ; retirer une cause en laissant son témoin ferait passer un test
    sur une branche morte.
    """
    assert set(_TEMOINS) == set(banc.CAUSES)
    assert len(banc.CAUSES) == len(set(banc.CAUSES)) == 8


def test_une_table_batie_sur_les_temoins_somme_au_nombre_d_observations(banc):
    """LA TABLE SOMME, et le témoin porte son compte : 8 observations, 8 causes.

    Un classeur qui rendrait deux fois la même cause, ou une cause hors du
    registre, ferait une table dont la somme resterait juste et dont les lignes
    seraient fausses — d'où le contrôle sur les DEUX.
    """
    observations = list(_TEMOINS.values())
    comptes = {
        cause: sum(1 for o in observations if banc.classer_la_cause(o) == cause)
        for cause in banc.CAUSES
    }
    assert sum(comptes.values()) == len(observations) == 8
    assert comptes == dict.fromkeys(banc.CAUSES, 1)


def test_arrive_l_emporte_sur_tout_le_reste(banc):
    """L'ORDRE EST LA DÉFINITION : un ancrage arrivé n'a rien à expliquer.

    Une observation qui satisfait AUSSI une marche plus basse — ici un texte
    absent de ChromaDB, ce qui est impossible en pratique et volontaire en
    témoin — doit rester `arrive`. Si elle fuyait vers `hors_chromadb`, la
    première ligne de la table perdrait des ancrages au profit de la seconde
    sans qu'aucune somme ne bouge.
    """
    assert banc.classer_la_cause(_observation(rang_rerank_prod=1, indexe=False)) == "arrive"


def test_l_ecart_du_reranker_l_emporte_sur_la_profondeur(banc):
    """Un ancrage que la fusion de PRODUCTION portait est H4, jamais H2.

    Il est aussi présent en profondeur — forcément, élargir n'enlève rien. Le
    classer `profondeur_recupere` ferait croire qu'il faut élargir alors que le
    passage était déjà dans les mains du quatrième étage.
    """
    observation = _observation(rang_fusion_prod=12, rang_fusion_profond=12, rang_rerank_profond=3)
    assert banc.classer_la_cause(observation) == "ecarte_par_le_reranker"


def test_la_profondeur_qui_ne_suffit_pas_n_est_pas_celle_qui_recupere(banc):
    """Retrouvé plus profond n'est pas récupéré : les deux marches sont distinctes.

    Les fondre compterait comme « la profondeur le perdait » un ancrage que le
    reranker refuse de remonter même quand on le lui donne — et la question
    ouverte qui en sort ne serait pas la même.
    """
    recupere = _observation(rang_fusion_profond=88, rang_rerank_profond=7)
    insuffisant = _observation(rang_fusion_profond=88)
    assert banc.classer_la_cause(recupere) == "profondeur_recupere"
    assert banc.classer_la_cause(insuffisant) == "profondeur_insuffisante"
    assert banc.classer_la_cause(recupere) != banc.classer_la_cause(insuffisant)


def test_un_rang_profond_rendu_par_la_liste_n_est_pas_un_rang_dans_le_haut(banc):
    """LA FAUTE QUE CE TEST EXISTE POUR ATTRAPER, ET ELLE A ÉTÉ COMMISE ICI.

    À profondeur de production `RERANK_TOP_K` vaut 10, donc « rendu par `rerank` »
    et « dans le top-10 » coïncident, et un classeur qui teste `is not None`
    passe. À profondeur 1000 ils divergent : un ancrage rendu au rang **812** se
    lirait « la profondeur l'a récupéré », et la table dirait qu'élargir suffit
    là où le reranker ne le remonte jamais. Le seuil doit donc être le MÊME aux
    trois profondeurs, et il est explicite.
    """
    loin = _observation(rang_fusion_profond=310, rang_rerank_profond=812)
    assert banc.classer_la_cause(loin) == "profondeur_insuffisante"
    proche = _observation(rang_fusion_profond=310, rang_rerank_profond=10)
    assert banc.classer_la_cause(proche) == "profondeur_recupere"
    # La borne est INCLUSIVE, et le contrôle est de part et d'autre : un seuil
    # exclusif perdrait le dixième ancrage de chaque question sans rien casser.
    assert banc.dans_le_haut(10) is True
    assert banc.dans_le_haut(11) is False
    assert banc.dans_le_haut(None) is False


def test_l_oracle_muet_au_dela_du_top_dix_n_est_pas_une_requete_qui_recupere(banc):
    """L'oracle aussi est jugé sur le HAUT du classement, pas sur sa présence.

    Sans quoi H1 ramasserait des ancrages que l'oracle retrouve au rang 40 —
    c'est-à-dire des passages qu'aucune décomposition n'amènerait au prompt.
    """
    assert banc.classer_la_cause(_observation(oracle_rerank=11)) == "texte_indexe"
    assert banc.classer_la_cause(_observation(oracle_rerank=10)) == "requete_unique"


def test_l_oracle_non_joue_ne_vaut_pas_un_oracle_muet(banc):
    """`non_explique` EXISTE, et il attrape l'oracle qu'on n'a pas joué.

    Sans cette marche, un ancrage jamais interrogé par l'oracle tomberait dans
    `texte_indexe` — c'est-à-dire qu'un travail non fait se lirait comme une
    cause mesurée. C'est la faute que la ligne « non expliqué » existe pour
    rendre visible.
    """
    sans_oracle = {k: v for k, v in _observation().items() if k != "oracle_rerank"}
    assert banc.classer_la_cause(sans_oracle) == "non_explique"
    assert banc.classer_la_cause(_observation(oracle_rerank=None)) == "texte_indexe"


# ─── La couverture de la preuve ───────────────────────────────────────────────


def test_une_preuve_sans_jeton_mesurable_rend_none_et_non_zero(banc):
    """`None` n'est pas `0.0` : rien n'a pu être comparé, ce n'est pas un échec.

    Une part de 0,0 se lirait « le texte indexé ne porte rien de la preuve » et
    classerait l'ancrage en H3, alors que la mesure est impossible. Le §4.76 a
    déjà payé cette confusion sur les ancrages sans texte.
    """
    assert banc.couverture("", "n'importe quel texte") is None
    assert banc.couverture("à la de", "n'importe quel texte") is None
    assert banc.couverture("rien", "") == 0.0


def test_les_jetons_courts_ne_rendent_pas_la_couverture_toujours_vraie(banc):
    """Un mot de deux lettres se retrouve dans n'importe quoi.

    Les compter ferait monter toutes les parts vers 1 et déclarerait « la preuve
    est portée » sur des chunks qui n'en portent aucun mot distinctif.
    """
    # « of » et « la » font moins de trois caractères : ils sont écartés des
    # deux côtés, et seul « challenger » compte. Le porteur ne l'a pas.
    assert banc.couverture("of la challenger", "of la") == 0.0
    # Et le contrôle dans l'autre sens : un jeton court partagé ne suffit pas à
    # faire monter la part, sans quoi ce test passerait sur un détecteur cassé.
    assert banc.couverture("of la", "of la challenger") is None


def test_une_preuve_entierement_recopiee_rend_une_couverture_de_un(banc):
    """CONTRÔLE POSITIF de la couverture : sans lui, un 0,0 partout passerait.

    Un détecteur qui rendrait toujours 0 ferait tomber les 120 ancrages dans
    H3, et le test précédent — qui attend 0,0 — le trouverait juste.
    """
    preuve = "the challenger is evaluated alongside the champion"
    assert banc.couverture(preuve, f"Texte du chunk : {preuve}, et la suite.") == 1.0


# ─── La requête oracle ────────────────────────────────────────────────────────


def test_la_requete_oracle_est_la_preuve_et_rien_d_autre(banc):
    """Le titre de section ne vient PAS du chunk, donc il n'entre pas dans la requête.

    L'y mettre mêlerait le graphe et l'index vectoriel dans une mesure qui doit
    dire ce que le CHUNK rend, et un ancrage remonté par son titre se lirait
    comme un passage atteignable.
    """
    ancrage = {
        "preuve": "  the challenger is evaluated alongside the champion  ",
        "section_title": "Challenger Versus Champion",
        "element_id": "6e460fc900",
    }
    requete = banc.requete_oracle_preuve(ancrage)
    assert requete == "the challenger is evaluated alongside the champion"
    assert "Challenger Versus Champion" not in requete


def test_un_ancrage_sans_preuve_rend_une_requete_vide_et_non_un_titre(banc):
    """Le repli est le vide, jamais une autre source : l'appelant doit le voir."""
    assert banc.requete_oracle_preuve({"section_title": "Un titre"}) == ""


# ─── L'affectation des sous-questions ─────────────────────────────────────────


def test_l_affectation_retient_celle_qui_ramene_le_plus_d_ancrages(banc):
    """La permutation croisée gagne quand elle trouve plus, et le banc la prend.

    Le modèle écrit deux sous-questions sans voir les passages : rien ne dit
    laquelle vise lequel. Prendre l'identité par défaut sous-compterait l'oracle
    une fois sur deux, et le chiffre publié dirait « la décomposition ne sert à
    rien ».
    """
    # La sous-question 0 trouve l'ancrage 1 ; la 1 trouve l'ancrage 0.
    matrice = [[None, 3], [5, None]]
    permutation, rangs = banc.affectation_au_mieux(matrice)
    assert permutation == [1, 0]
    assert rangs == [3, 5]


def test_a_egalite_l_affectation_retient_la_somme_des_rangs_la_plus_basse(banc):
    """Deux affectations qui trouvent AUTANT ne sont pas équivalentes.

    Sans ce second critère, l'oracle publierait des rangs qui dépendent de
    l'ordre des permutations — donc du hasard de l'implémentation.
    """
    matrice = [[9, 1], [2, 8]]
    permutation, rangs = banc.affectation_au_mieux(matrice)
    assert permutation == [1, 0]
    assert rangs == [1, 2]


def test_l_affectation_identite_est_retenue_quand_elle_est_la_meilleure(banc):
    """CONTRÔLE POSITIF dans l'autre sens : le banc ne croise pas systématiquement.

    Un banc qui rendrait toujours la permutation croisée passerait les deux
    tests précédents et se tromperait sur toutes les autres questions.
    """
    matrice = [[1, None], [None, 2]]
    permutation, rangs = banc.affectation_au_mieux(matrice)
    assert permutation == [0, 1]
    assert rangs == [1, 2]


# ─── L'état des stores ────────────────────────────────────────────────────────


def _releve(chunks=4367, status="ok", services=None):
    return {
        "heure_utc": "2026-09-24T20:00:00+00:00",
        "health": {"status": status, "services": services or {"chromadb": True}},
        "chunks": chunks,
    }


def test_deux_comptes_de_chunks_differents_sont_un_refus(banc):
    """Le pipeline voisin purge et réingère : deux états, un seul tableau, refus.

    Le compte est la seule grandeur qui distingue « les services répondent » de
    « c'est le même corpus » — `/health` reste vert pendant une réingestion.
    """
    stable, phrase = banc.stores_stables(_releve(4367), _releve(4211))
    assert stable is False
    assert "4367" in phrase and "4211" in phrase


def test_un_service_rouge_est_un_refus_et_il_est_nomme(banc):
    """Nommé, parce qu'un refus qui ne dit pas QUEL service se rejoue à l'aveugle."""
    stable, phrase = banc.stores_stables(
        _releve(services={"chromadb": True, "nebulagraph": False}), _releve()
    )
    assert stable is False
    assert "nebulagraph" in phrase


def test_un_health_injoignable_est_un_refus_et_non_un_silence(banc):
    """Une sonde qui ne répond pas n'est pas une sonde verte.

    L'absorption large du relevé rend un dictionnaire `{"panne": …}` plutôt que
    de lever : sans ce garde, la campagne le traverserait sans un mot.
    """
    casse = _releve()
    casse["health"] = {"panne": "ConnectError: refused"}
    stable, phrase = banc.stores_stables(casse, _releve())
    assert stable is False
    assert "injoignable" in phrase


def test_deux_releves_identiques_passent_et_le_verdict_porte_le_compte(banc):
    """CONTRÔLE POSITIF : sans lui, un garde qui refuse TOUT passerait les trois.

    Et le verdict porte le chiffre : un verdict qui dirait seulement « stable »
    laisserait le rapport affirmer un compte que personne n'a lu.
    """
    stable, phrase = banc.stores_stables(_releve(), _releve())
    assert stable is True
    assert "4367" in phrase


# ─── Le contrôle positif contre le §4.76 ──────────────────────────────────────


def _bilan_prod(absents, profondeurs=None):
    """Un bilan minimal dont on CHOISIT le nombre d'ancrages absents par étage."""
    lignes = []
    for index in range(_ANCRAGES // 2):
        rangs = {}
        for moitie in (0, 1):
            position = index * 2 + moitie
            rangs[f"{position:010x}"] = {
                etage: (None if position < absents.get(etage, 0) else 1)
                for etage in ("dense", "lexical", "fusion", "rerank")
            }
        lignes.append({"id": f"D-{index:03d}", "gold": list(rangs), "rangs": rangs})
    return {
        "profondeurs": profondeurs or {"fetch_k": 50, "retrieval_top_k": 50, "rerank_top_k": 10},
        "lignes": lignes,
    }


def test_le_controle_positif_accorde_sur_les_trois_chiffres_du_4_76(banc):
    """CONTRÔLE POSITIF DU CONTRÔLE : un garde qui refuse tout ne prouve rien."""
    resultat = banc.controle_positif(_bilan_prod(_ABSENTS_4_76))
    assert resultat["accord"] is True
    assert resultat["mesure"] == _ABSENTS_4_76
    assert resultat["ancrages"] == _ANCRAGES


def test_un_seul_ancrage_d_ecart_fait_tomber_le_controle(banc):
    """« À l'unité près » est la condition, et elle mord à UNE unité.

    Un contrôle qui tolérerait un écart laisserait passer un banc qui mesure
    presque la même chose — c'est-à-dire autre chose.
    """
    resultat = banc.controle_positif(_bilan_prod({**_ABSENTS_4_76, "rerank": 66}))
    assert resultat["accord"] is False
    assert resultat["mesure"]["rerank"] == 66


def test_le_controle_refuse_une_autre_profondeur_avant_de_comparer(banc):
    """Comparés à `RERANK_TOP_K=50`, les trois comptes portent le même nom et un autre sens.

    Le contrôle doit donc refuser la PROFONDEUR, et pas seulement les comptes :
    un bilan élargi qui retrouverait 56/46/67 par hasard se dirait conforme.
    """
    large = {"fetch_k": 200, "retrieval_top_k": 200, "rerank_top_k": 200}
    resultat = banc.controle_positif(_bilan_prod(_ABSENTS_4_76, profondeurs=large))
    assert resultat["accord"] is False
    assert set(resultat["ecart_de_profondeur"]) == {"fetch_k", "retrieval_top_k", "rerank_top_k"}


# ─── Ce que les bilans VERSIONNÉS disent, et qui doit rester vrai ─────────────
#
# AUCUN `skipif` ICI, ET C'EST DÉLIBÉRÉ. Un garde qui s'efface quand son fichier
# manque ne garde rien : le jour où une campagne oublie de versionner son bilan,
# la suite resterait verte et le rapport serait le seul endroit où le chiffre
# existe. Le fichier absent DOIT rougir.


def test_le_bilan_versionne_retrouve_les_trois_chiffres_du_4_76(banc):
    """Le fichier de `runs/` porte la mesure, et le garde la relit sans les stores.

    Sans ce test, le rapport serait le seul endroit où le chiffre existe, et un
    fichier remplacé par une campagne d'un autre jour passerait inaperçu.
    """
    bilan = json.loads(_BILAN_PROD.read_text(encoding="utf-8"))
    resultat = banc.controle_positif(bilan)
    assert resultat["accord"] is True, resultat
    assert resultat["mesure"] == _ABSENTS_4_76
    assert bilan["stores"]["stable"] is True


def test_la_table_des_causes_versionnee_somme_a_cent_vingt(banc):
    """La somme est la propriété que la table existe pour porter.

    Une table dont la somme dériverait aurait perdu des ancrages en route, et
    chacune de ses lignes resterait plausible.
    """
    bilan = json.loads(_BILAN_CAUSES.read_text(encoding="utf-8"))
    assert bilan["somme"] == bilan["ancrages"] == _ANCRAGES
    assert set(bilan["causes"]) == set(banc.CAUSES)
    assert bilan["controle_positif"]["accord"] is True

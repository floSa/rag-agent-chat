"""Le sens de lecture d'une métrique, et la flèche qui l'affirme.

`comparer` posait « ▲ » sur tout delta positif. Une génération qui passe de 9 s
à 6 s — une amélioration nette — portait donc le même « ▼ » qu'un rappel qui
s'effondre, et cela sur **la moitié du résumé** : vingt-six clés se lisent « plus
bas est mieux », dont `reconstruction_ms`, précisément celle que l'ablation du
graphe viendra lire.

La règle du lot vaut pour les flèches comme pour les métriques : une flèche qui
ne peut pas se tromper n'est pas gardée. Chaque test ci-dessous nomme ce que
vaudrait « faux » et l'exige rouge.
"""

import importlib.util
import pathlib

_RACINE = pathlib.Path(__file__).resolve().parents[2]
_SCRIPT = _RACINE / "scripts" / "evaluate.py"


def _evaluate():
    """Charge scripts/evaluate.py sans faire de `scripts/` un paquet."""
    spec = importlib.util.spec_from_file_location("evaluate", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _resume_complet(evaluate) -> dict:
    """Un résumé portant TOUTES les clés, pour balayer la classification.

    Les champs de `generation` sont renseignés : sans eux, les clés qui en
    dérivent existent quand même — c'est `resumer` qui les pose — mais autant
    balayer un résumé qui ressemble à celui d'une campagne réelle.
    """
    ligne = evaluate.evaluer(
        {"id": "G-001", "gold_element_ids": ["aaaaaaaaa1"], "language": "fr"},
        {
            "contexts": [
                {
                    "section_id": "s1",
                    "element_id": "aaaaaaaaa1",
                    "element_ids": ["aaaaaaaaa1"],
                    "retained": True,
                    "text": "x" * 900,
                }
            ],
            "citations": [],
            "answer": "une réponse",
            "timings": {"dense_ms": 90, "generation_ms": 4400, "total_ms": 4600},
            "generation": {
                "eval_count": 640,
                "num_predict": 4096,
                "prompt_eval_count": 3400,
                "prompt_tokens_estimated": 3600,
                "prompt_tokens_reliable": True,
            },
        },
    )
    return evaluate.resumer([ligne])


# ─── La flèche, dans les deux familles ───────────────────────────────────────

def test_une_latence_qui_baisse_s_affiche_comme_une_amelioration() -> None:
    """**Le test qui attrape le défaut.**

    `reconstruction_ms` est la clé que l'ablation du graphe viendra lire. Avec la
    flèche d'origine — « ▲ si delta > 0 » — une reconstruction qui passe de 400 ms
    à 150 ms s'affichait « ▼ », c'est-à-dire comme une régression.
    """
    fleche_de = _evaluate().fleche_de

    assert fleche_de("reconstruction_ms_p50", -250) == "▲"
    assert fleche_de("reconstruction_ms_p50", +250) == "▼"


def test_un_rappel_qui_baisse_s_affiche_comme_une_regression() -> None:
    """L'autre famille, et le pendant indispensable : inverser TOUTES les
    flèches corrigerait la moitié du résumé en cassant l'autre."""
    fleche_de = _evaluate().fleche_de

    assert fleche_de("rappel_recherche", -0.05) == "▼"
    assert fleche_de("rappel_recherche", +0.05) == "▲"


def test_le_meme_delta_porte_des_fleches_opposees_selon_la_metrique() -> None:
    """La formulation la plus dure du défaut : un unique signe d'écart, deux
    lectures. Un affichage qui ne regarde que le signe ne peut pas les
    distinguer, quelle que soit la flèche qu'il choisit."""
    fleche_de = _evaluate().fleche_de

    assert fleche_de("total_ms_p95", -1) != fleche_de("mrr", -1)
    assert fleche_de("contextes_ecartes_total", -3) == "▲"
    assert fleche_de("part_utile_caracteres", -0.3) == "▼"


def test_un_ecart_nul_ne_porte_aucun_jugement() -> None:
    fleche_de = _evaluate().fleche_de

    assert fleche_de("mrr", 0) == "→"
    assert fleche_de("total_ms_p50", 0) == "→"
    assert fleche_de("eval_count_p95", 0) == "→"


def test_une_grandeur_sans_sens_de_lecture_ne_recoit_pas_de_fleche() -> None:
    """« ± » n'est pas un aveu d'ignorance : c'est le refus d'affirmer une
    direction que la grandeur ne porte pas.

    `reponse_caracteres_p95` qui monte n'est ni meilleur ni pire — c'est
    exactement le chiffre dont on a besoin pour régler `LLM_MAX_TOKENS`, et un
    « ▲ » y dirait qu'une réponse longue vaut mieux qu'une courte. Une flèche qui
    ne peut pas se tromper ne mesure rien.
    """
    fleche_de = _evaluate().fleche_de

    assert fleche_de("reponse_caracteres_p95", +2000) == "±"
    assert fleche_de("reponse_caracteres_p95", -2000) == "±"
    # Le cas le plus subtil : il tranche `LLM_MAX_TOKENS`, mais dans les deux
    # sens selon ce qu'on décide. Une flèche y trancherait à la place du lecteur.
    assert fleche_de("generations_au_plafond", +5) == "±"
    # Et un effectif de population n'est pas une qualité.
    assert fleche_de("precision_contexte_sur", -40) == "±"


# ─── La classification elle-même ─────────────────────────────────────────────

def test_le_centile_ne_change_pas_le_sens_de_la_grandeur() -> None:
    """`dense_ms_p50` et `dense_ms_p95` se lisent pareil. Sans le retrait du
    suffixe, chaque étage demanderait deux entrées — et le jour où un étage
    s'ajoute à la partition, il en manquerait deux."""
    evaluate = _evaluate()

    assert evaluate.racine_metrique("dense_ms_p95") == "dense_ms"
    assert evaluate.racine_metrique("reponse_caracteres_max") == "reponse_caracteres"
    assert evaluate.racine_metrique("mrr") == "mrr"
    assert evaluate.sens_de_lecture("dense_ms_p50") == evaluate.sens_de_lecture("dense_ms_p95")


def test_tous_les_etages_de_la_partition_se_lisent_plus_bas_est_mieux() -> None:
    """Le suffixe `_ms` couvre d'avance tout étage ajouté à la partition : c'est
    ce qui évite d'avoir à penser à la flèche en même temps qu'au chronomètre."""
    evaluate = _evaluate()

    for etage in evaluate.ETAGES:
        assert evaluate.sens_de_lecture(f"{etage}_p50") == -1, etage
        assert evaluate.sens_de_lecture(f"{etage}_p95") == -1, etage
    assert evaluate.sens_de_lecture("retrieval_ms_p95") == -1


def test_toutes_les_cles_du_resume_sont_classees() -> None:
    """**Le garde-fou du repli.**

    `sens_de_lecture` rend +1 sur une clé qu'aucune liste ne connaît — la lecture
    historique, pour ne pas casser une campagne sur un nom inattendu. Le prix de
    cette indulgence est qu'une métrique ajoutée demain hériterait d'un « ▲ » que
    personne n'aurait décidé, et rien ne tomberait.

    Ce test est ce qui l'empêche : chaque clé du résumé doit appartenir à l'une
    des trois listes, ou être reconnue à son suffixe `_ms`. Il rougit sur toute
    métrique ajoutée sans qu'on ait tranché son sens de lecture.
    """
    evaluate = _evaluate()
    resume = _resume_complet(evaluate)
    connues = evaluate.HAUT_EST_MIEUX | evaluate.PLUS_BAS_EST_MIEUX | evaluate.SANS_DIRECTION

    non_classees = [
        cle
        for cle in resume
        if not evaluate.racine_metrique(cle).endswith("_ms")
        and evaluate.racine_metrique(cle) not in connues
    ]

    assert not non_classees, f"sens de lecture non tranché : {non_classees}"


def test_les_trois_listes_ne_se_recoupent_pas() -> None:
    """Une racine dans deux listes rendrait le sens dépendant de l'ordre des
    tests dans `sens_de_lecture`, donc d'un détail d'écriture."""
    evaluate = _evaluate()
    haut, bas, sans = (
        evaluate.HAUT_EST_MIEUX,
        evaluate.PLUS_BAS_EST_MIEUX,
        evaluate.SANS_DIRECTION,
    )

    assert not haut & bas
    assert not haut & sans
    assert not bas & sans
    # Et aucune racine `_ms` ne figure dans une liste : elles sont reconnues au
    # suffixe, et l'y ajouter donnerait deux sources de vérité pour le même sens.
    assert not {r for r in haut | bas | sans if r.endswith("_ms")}


# ─── Le sens suit jusque dans l'appariement ──────────────────────────────────

def _lignes(ids, **valeurs):
    return [{"id": i, **valeurs} for i in ids]


def test_un_contexte_qui_maigrit_est_apparie_comme_une_amelioration() -> None:
    """Le prix entre dans l'appariement, donc son sens doit y entrer aussi.

    Sans cela, chaque économie de contexte serait rangée parmi les dégradations —
    et le test des signes conclurait à une régression significative sur la
    métrique même que l'ablation du graphe cherche à faire baisser.
    """
    evaluate = _evaluate()
    ids = [f"G-{i:03d}" for i in range(1, 7)]
    avant = _lignes(ids, caracteres_retenus=9000, contextes_retenus=6)
    apres = _lignes(ids, caracteres_retenus=4500, contextes_retenus=3)

    apparie = evaluate.apparier(apres, avant, "caracteres_retenus")

    assert apparie["sens"] == -1
    assert len(apparie["ameliorees"]) == 6
    assert apparie["degradees"] == []
    # L'écart, lui, garde son signe BRUT : c'est la différence mesurée, et
    # l'intervalle de confiance porte sur elle.
    assert apparie["delta_moyen"] == -4500
    assert apparie["ic95"][1] < 0


def test_le_sens_ne_change_pas_la_p_value() -> None:
    """Garde-fou sur ce que la correction ne doit PAS toucher.

    Le test des signes est symétrique en (améliorées, dégradées) : inverser les
    étiquettes ne peut pas changer sa conclusion. Si un jour elle bougeait, c'est
    que l'inversion aurait débordé du côté du calcul — celui que l'audit a
    vérifié correct.
    """
    evaluate = _evaluate()
    ids = [f"G-{i:03d}" for i in range(1, 7)]
    prix = evaluate.apparier(
        _lignes(ids, caracteres_retenus=4500), _lignes(ids, caracteres_retenus=9000),
        "caracteres_retenus",
    )
    apport = evaluate.apparier(
        _lignes(ids, rang_reciproque=1.0), _lignes(ids, rang_reciproque=0.5), "rang_reciproque"
    )

    assert prix["p_signe"] == apport["p_signe"]
    assert evaluate.test_de_signe(6, 0) == evaluate.test_de_signe(0, 6)


def test_le_prix_est_apparie_au_meme_titre_que_l_apport() -> None:
    """L'apport avait son test des signes et son intervalle de confiance, le prix
    tombait dans le diff des résumés. Pour un arbitrage prix/apport, c'était la
    moitié de l'instrument."""
    appariees = set(_evaluate().METRIQUES_APPARIEES)

    assert {"caracteres_retenus", "contextes_retenus"} <= appariees


def test_toute_metrique_appariee_a_un_sens_de_lecture() -> None:
    """**Le garde-fou que l'exclusion des latences ne donnait pas.**

    La raison écrite pour tenir les latences hors de l'appariement est le bruit
    machine, pas le signe. Le sens n'était donc protégé par rien : une métrique
    sans direction ajoutée au tuple recevrait des colonnes ▲ / ▼ qui ne veulent
    rien dire, et un test des signes qui leur donnerait une p-value.
    """
    evaluate = _evaluate()

    for metrique in evaluate.METRIQUES_APPARIEES:
        assert evaluate.sens_de_lecture(metrique) != 0, metrique


def test_aucune_latence_n_entre_dans_l_appariement() -> None:
    """Et la raison, écrite : ce n'est PAS le signe.

    Deux campagnes ne partagent pas leur machine. Un écart apparié de latence
    mesurerait la charge du moment, question par question, et le test des signes
    lui donnerait une p-value — donc un air de résultat là où il n'y a que du
    bruit d'ordonnancement. Les latences se lisent sur les centiles du résumé, où
    l'agrégation dilue ce bruit au lieu de le tester.
    """
    evaluate = _evaluate()
    appariees = set(evaluate.METRIQUES_APPARIEES)

    assert not {m for m in appariees if evaluate.racine_metrique(m).endswith("_ms")}

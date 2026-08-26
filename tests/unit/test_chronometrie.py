"""La partition du temps, et ce qui la fait mentir.

Sept étages pour deux chiffres : `AnswerResponse` ne portait que `retrieval_ms`
et `generation_ms`, et la reconstruction par le graphe — le pari central du
projet — n'avait jamais été chronométrée.

Ces tests ne vérifient pas qu'un chiffre se calcule : un tel test est vert des
deux côtés du défaut. Ils vérifient que la partition **se casse visiblement**
quand elle est fausse — un étage qui en contient un autre, un étage inventé, une
somme qui dépasse le temps mural.
"""

import logging
import time

import pytest

from src.agent.chronometrie import AGREGATS, ETAGES, Chrono, cumuler, decomposer

# ─── La partition, et sa borne ────────────────────────────────────────────────

def test_la_somme_des_etages_plus_le_residu_vaut_le_total() -> None:
    """L'invariant. Sans lui, la partition dérive au premier refactor."""
    chronometrage = {"rewrite_ms": 40, "dense_ms": 120, "rerank_ms": 300, "generation_ms": 4400}

    partition = decomposer(chronometrage, total_ms=5000)

    assert sum(partition[cle] for cle in ETAGES) + partition["residual_ms"] == 5000
    assert partition["total_ms"] == 5000
    assert partition["residual_ms"] == 140


def test_un_etage_non_mesure_vaut_zero_pas_l_absence() -> None:
    """Un étage absent du chronométrage est un étage à zéro, pas un étage
    manquant : la table de latence doit avoir la même forme à chaque campagne,
    sinon une colonne qui disparaît se lit « rien à voir ici »."""
    partition = decomposer({}, total_ms=100)

    assert set(ETAGES) <= set(partition)
    assert all(partition[cle] == 0 for cle in ETAGES)
    assert partition["residual_ms"] == 100


def test_sans_chronometrage_tout_le_temps_est_du_residu() -> None:
    """Le cas de l'instrumentation débranchée : le résidu vaut le total. Un
    résidu qui égale le total est un instrument muet, et cela doit se voir."""
    assert decomposer(None, total_ms=777)["residual_ms"] == 777


# ─── Ce qui fait mentir la partition, et qui doit se voir ─────────────────────

def test_un_agregat_ajoute_aux_etages_rend_le_residu_negatif(caplog) -> None:
    """**Le test qui fait régresser la mesure.**

    `retrieval_ms` est le temps mural du nœud de recherche : il CONTIENT
    `dense_ms`, `lexical_ms` et `fusion_ms`. Le compter comme un étage double le
    comptage de toute la recherche — c'est exactement le défaut que ce module
    existe pour fermer.

    Le montage simule ce double comptage en versant l'agrégat dans un étage, et
    exige deux choses : que le résidu devienne NÉGATIF, et que le journal le
    dise. Borner le résidu à zéro rendrait ce test vert sur un tableau faux.
    """
    recherche = {"dense_ms": 300, "lexical_ms": 150, "fusion_ms": 50}
    total_recherche = sum(recherche.values())
    # L'agrégat versé dans un étage : c'est la forme que prend le double comptage.
    double = {**recherche, "generation_ms": total_recherche}

    with caplog.at_level(logging.WARNING, logger="src.agent.chronometrie"):
        partition = decomposer(double, total_ms=total_recherche)

    assert partition["residual_ms"] == -total_recherche
    assert "négatif" in caplog.text
    # Et l'invariant tient encore : c'est lui qui rend le mensonge lisible.
    assert sum(partition[cle] for cle in ETAGES) + partition["residual_ms"] == total_recherche


def test_l_agregat_de_recherche_n_est_pas_un_etage() -> None:
    """Épinglage de la décision, pas de son effet.

    `retrieval_ms` survit — la capture d'usage a une colonne de ce nom et
    `AnswerResponse` le publie depuis l'origine. Le jour où quelqu'un l'ajoute à
    `ETAGES` pour « compléter le tableau », ce test tombe avant la campagne.
    """
    assert "retrieval_ms" in AGREGATS
    assert not set(AGREGATS) & set(ETAGES)


def test_un_agregat_present_dans_le_chronometrage_ne_fausse_rien() -> None:
    """Le pendant du précédent : `retrieval_ms` a le droit d'être là.

    Il est écrit par `node_retrieve` et lu par la capture d'usage. Tant qu'il
    n'est pas un étage, `decomposer` doit l'ignorer — pas s'en émouvoir.
    """
    partition = decomposer(
        {"dense_ms": 300, "lexical_ms": 150, "fusion_ms": 50, "retrieval_ms": 510},
        total_ms=600,
    )

    assert partition["residual_ms"] == 100
    assert "retrieval_ms" not in partition


def test_un_etage_inconnu_est_refuse_au_lieu_de_disparaitre() -> None:
    """Un nom d'étage hors partition ne cause pas d'erreur visible : son temps
    tombe au résidu, et la table continue de s'afficher comme si elle était
    complète. `Chrono.mesurer` refuse donc le nom."""
    chrono = Chrono()

    with pytest.raises(KeyError, match="rerankms"), chrono.mesurer("rerankms"):
        pass

    assert chrono.etages == {}


# ─── Le cumul, parce que la boucle agentique repasse ─────────────────────────

def test_deux_passages_dans_un_etage_s_additionnent() -> None:
    """La boucle agentique repasse par la recherche et par la génération. Ce qui
    compte pour arbitrer un étage est ce qu'il coûte à la RÉPONSE, pas à son
    dernier passage."""
    chrono = Chrono()
    for _ in range(2):
        with chrono.mesurer("dense_ms"):
            time.sleep(0.01)

    assert chrono.etages["dense_ms"] >= 20


def test_cumuler_ajoute_au_lieu_d_ecraser() -> None:
    """L'état LangGraph est remplacé nœud par nœud : écraser ferait perdre le
    temps du premier passage dès que la boucle en fait un second."""
    fusion = cumuler({"dense_ms": 100, "retrieval_ms": 150}, {"dense_ms": 40, "fusion_ms": 10})

    assert fusion == {"dense_ms": 140, "retrieval_ms": 150, "fusion_ms": 10}


def test_cumuler_part_de_zero_sur_un_chronometrage_absent() -> None:
    assert cumuler(None, {"rerank_ms": 12}) == {"rerank_ms": 12}


def test_une_exception_dans_l_etage_compte_quand_meme_son_temps() -> None:
    """Une reconstruction qui échoue a coûté du temps. Ne pas le compter le
    verserait au résidu, et un étage en panne s'afficherait gratuit."""
    chrono = Chrono()

    with pytest.raises(RuntimeError), chrono.mesurer("reconstruction_ms"):
        time.sleep(0.01)
        raise RuntimeError("section illisible")

    assert chrono.etages["reconstruction_ms"] >= 10

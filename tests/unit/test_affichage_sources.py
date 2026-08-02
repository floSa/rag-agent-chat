"""Affichage des sources dans l'interface de sélection.

C'est l'écran où l'utilisateur arbitre : si le signal qu'il y lit est faux, la
sélection humaine ne sert plus à rien. Deux versions s'y sont déjà trompées —
d'abord des logits bruts affichés comme des probabilités, puis des seuils
absolus hérités d'un autre modèle qui peignaient tout en rouge.
"""

from src.frontend.app import couleur_pertinence, numeroter_citations, situer_passage

# ─── Couleur du badge ─────────────────────────────────────────────────────────

def test_la_meilleure_source_est_toujours_verte() -> None:
    """Quelle que soit sa valeur absolue : c'est la meilleure de cette question."""
    assert couleur_pertinence(0.14, meilleure=0.14) == "green"
    assert couleur_pertinence(0.97, meilleure=0.97) == "green"


def test_source_proche_de_la_meilleure_reste_verte() -> None:
    assert couleur_pertinence(0.09, meilleure=0.14) == "green"


def test_source_moyenne_en_orange() -> None:
    assert couleur_pertinence(0.05, meilleure=0.14) == "orange"


def test_source_lointaine_en_rouge() -> None:
    assert couleur_pertinence(0.01, meilleure=0.14) == "red"


def test_un_reranker_aux_scores_bas_n_est_pas_penalise() -> None:
    """Le défaut corrigé : des seuils absolus affichaient toute la liste en rouge.

    Le cross-encoder multilingue rend des valeurs bien plus basses que
    ms-marco ; seul le rapport au meilleur score est comparable.
    """
    scores = [0.14, 0.08, 0.02, 0.02, 0.01]
    couleurs = [couleur_pertinence(s, meilleure=max(scores)) for s in scores]

    assert couleurs[0] == "green"
    assert "red" in couleurs  # les mauvaises restent signalées
    assert couleurs.count("red") < len(scores)  # mais pas toutes


def test_aucune_source_pertinente() -> None:
    assert couleur_pertinence(0.0, meilleure=0.0) == "red"


# ─── Libellé d'un passage ─────────────────────────────────────────────────────

def test_passage_situe_par_langue_page_et_section() -> None:
    libelle = situer_passage(
        {"language": "en", "page_no": 42, "section_title": "Dispersion", "label": "paragraph"}
    )

    assert libelle == "[en] p.42 — § Dispersion"


def test_section_tronquee_si_trop_longue() -> None:
    libelle = situer_passage({"language": "fr", "page_no": 1, "section_title": "T" * 100})

    assert len(libelle) < 90  # noqa: PLR2004


def test_sans_page_le_label_prend_le_relais() -> None:
    """Les formats non paginés n'ont pas de numéro de page."""
    assert situer_passage({"language": "fr", "page_no": 0, "label": "paragraph"}) == (
        "[fr] paragraph"
    )


def test_sans_langue_le_prefixe_disparait() -> None:
    """Documents ingérés avant que la métadonnée existe."""
    assert situer_passage({"page_no": 7, "section_title": "Intro"}) == "p.7 — § Intro"


def test_metadonnees_absentes_ne_font_pas_planter() -> None:
    assert situer_passage({}) == ""


# ─── Renvois de citation ──────────────────────────────────────────────────────

def test_hash_remplace_par_un_renvoi_numerote() -> None:
    """Le hash sert au post-processing, pas à la lecture."""
    citations = [{"element_id": "203a2f3181"}, {"element_id": "629eadaccb"}]
    reponse = "Le CD est central [src:203a2f3181] et automatisable [src:629eadaccb]."

    assert numeroter_citations(reponse, citations) == "Le CD est central [1] et automatisable [2]."


def test_meme_source_citee_deux_fois_garde_son_numero() -> None:
    citations = [{"element_id": "aaaaaaaaaa"}]
    reponse = "Un fait [src:aaaaaaaaaa]. Le même [src:aaaaaaaaaa]."

    assert numeroter_citations(reponse, citations) == "Un fait [1]. Le même [1]."


def test_identifiant_non_resolu_est_retire() -> None:
    """Un hash inventé par le modèle ne renvoie à rien : le laisser serait pire."""
    reponse = "Une affirmation [src:deadbeef99]."

    assert numeroter_citations(reponse, [{"element_id": "aaaaaaaaaa"}]) == "Une affirmation ."


def test_reponse_sans_citation_inchangee() -> None:
    assert numeroter_citations("Je n'ai pas trouvé.", []) == "Je n'ai pas trouvé."


def test_numerotation_suit_l_ordre_de_la_liste_des_sources() -> None:
    """L'utilisateur lit [3] et cherche la troisième ligne : elle doit correspondre."""
    citations = [{"element_id": f"{i}" * 10} for i in range(1, 4)]
    reponse = "[src:3333333333] puis [src:1111111111]"

    assert numeroter_citations(reponse, citations) == "[3] puis [1]"

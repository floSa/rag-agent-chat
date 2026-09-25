"""LA DÉCOMPOSITION AVEC TRADUCTION, et les huit façons de la mal mesurer.

Le §4.78 a mesuré la décomposition réelle et a écrit TROIS réserves à son
propre site : la comparaison avec la production est boiteuse parce que la
production traduit et que les variantes ne traduisent pas ; les trois questions
perdues ne sont pas diagnostiquées ; et les neuf questions d'écart à la borne
de l'oracle ne sont pas réparties entre la fusion et le reranking, faute de
versionner le rang de fusion des variantes.
`scripts/mesurer_decomposition_traduite.py` répond aux trois, et une telle
mesure se casse de huit façons dont aucune ne lève d'erreur :

1. **UNE TRADUCTION QUI N'EST PAS CELLE DE LA PRODUCTION.** `translate_question`
   JETTE une traduction vide, une traduction trois fois plus longue que la
   question, une traduction égale à la question — et `retrieve` reçoit alors
   `translation=None`. Un banc qui oublierait un de ces refus donnerait au
   moteur des requêtes que le service n'émet jamais, et attribuerait à la
   traduction un gain qui n'existe pas en production. Le témoin fait passer les
   MÊMES corps par les DEUX chemins et exige le MÊME résultat.
2. **UN REPLI QUI CHANGE DE BASE.** Les variantes du §4.78 retombent sur la
   requête unique SANS traduction ; les variantes traduites doivent retomber sur
   la production EXACTE. Recopier la mauvaise base ferait porter aux 69
   questions à besoin unique du jeu de réglage une perte que l'implémentation
   n'aurait pas.
3. **UNE PONDÉRATION ÉGALE LÀ OÙ LA PRODUCTION PONDÈRE.** La production donne
   MOINS de confiance à la traduction. Fondre les deux familles à poids égaux
   mesurerait un réglage que ce lot ne mesure pas, et le témoin oppose les deux
   ordres obtenus.
4. **UN ÉTAGE DE PERTE QUI N'EST PAS EXCLUSIF.** Les quatre étages sont
   éprouvés un par un, et leur ORDRE l'est aussi : un ancrage que la fusion a
   gardé et que le reranker écarte n'est pas « jamais récupéré ».
5. **UNE QUESTION CLASSÉE PAR SON ANCRAGE LE PLUS AVAL.** Réparer le reranking
   ne rendrait pas complète une question dont l'AUTRE ancrage n'est jamais
   récupéré. Le témoin oppose les deux lectures.
6. **UN ÉCART À LA BORNE PRIS COMME UNE SOUSTRACTION DE COMPTES.** 86 − 72 = 14
   ne dit pas LESQUELS : une variante peut en placer autant que la borne sans en
   placer un seul des mêmes. Le témoin fait ACCORDER les comptes et DIVERGER les
   ensembles.
7. **UN CONTRÔLE POSITIF QUI NE TIENT QU'UN DE SES TROIS TERMES.** Les douze
   couples du §4.78, les rangs de ses QUATRE variantes un à un, et les 120 rangs
   du §4.77. Chacun des trois est muté séparément, et le contrôle du contrôle
   existe : un garde qui refuserait TOUT serait vert sur les trois refus.
8. **UNE RÉPARTITION QUI NE SOMME PAS.** Une table d'étages dont le total ne
   vaut pas le nombre d'ancrages du jeu décrit autre chose que le jeu.

Les témoins portent LEUR COMPTE, et le seuil du haut est éprouvé DANS LES DEUX
SENS : un garde qui n'accepte jamais est vert pour rien.
"""

import importlib.util
import json
import pathlib
import sys

import pytest

_RACINE = pathlib.Path(__file__).resolve().parents[2]
_BANC = _RACINE / "scripts" / "mesurer_decomposition_traduite.py"

# LES DOUZE COUPLES DU §4.78, recopiés ici pour que le garde soit lisible au
# site où il s'exerce — et pour qu'un banc qui les changerait en silence ait
# DEUX sites à changer, non un.
_COUPLES_DISPERSE_4_78 = {
    "unique_avec_traduction": (53, 7),
    "unique_sans_traduction": (57, 6),
    "fusion_rerank_entiere": (60, 8),
    "fusion_rerank_sous_questions": (72, 19),
}


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


def _chunk(chunk_id: str, element_id: str, texte: str = "corps"):
    """Un candidat minimal, et il est un VRAI `ChunkResult`.

    Même raison qu'au §4.78 : `fuse` et `dedupe_by_element` lisent `chunk_id`,
    `element_id` et `document_key`, et un double qui porterait seulement ces
    trois-là mesurerait l'accord de mes attributs avec eux-mêmes plutôt que la
    fusion de production.
    """
    from src.api.schemas import ChunkResult

    return ChunkResult(
        chunk_id=chunk_id,
        element_id=element_id,
        graph_node_id=f"n-{element_id}",
        document=texte,
        filename="f.md",
        source_path=f"livre/{element_id}.md",
        page_no=1,
        label="paragraph",
        distance=1.0,
    )


# ─── 1. LA TRADUCTION EST CELLE DE LA PRODUCTION, ET ON LE PROUVE ───────────

# LES CINQ FORMES QUE LE MODÈLE REND, et chacune est un comportement de
# `translate_question` — pas une invention du garde. Le corps est celui de
# `vllm-central`, `choices[0].message.content`, mesuré au §4.55.
_CORPS = [
    # Le cas nominal, et il est le contrôle positif de toute la table : sans lui
    # un post-traitement qui rendrait TOUJOURS `None` serait vert sur les autres.
    ("Quelle stratégie limite le rayon d'impact ?", "Which strategy limits blast radius?"),
    # LA PREMIÈRE LIGNE SEULE. Le modèle ajoute parfois une explication.
    ("Which strategy limits blast radius?\nNote: technical terms kept.", "Which…?"),
    # LES GUILLEMETS ENCADRANTS, que le gabarit interdit et que le modèle met.
    ('"Which strategy limits blast radius?"', "Quelle…?"),
    # LA TRADUCTION VIDE — refus de la production, recherche MONOLINGUE.
    ("", "Which strategy limits blast radius?"),
    ("   \n  ", "Which strategy limits blast radius?"),
    # LA TRADUCTION IDENTIQUE À LA QUESTION, à la casse près — refus.
    ("WHICH STRATEGY LIMITS BLAST RADIUS?", "Which strategy limits blast radius?"),
    # LA TRADUCTION TROP LONGUE — plus de trois fois la question : refus.
    ("x" * 100, "court ?"),
]


@pytest.mark.parametrize(("contenu", "question"), _CORPS)
def test_le_post_traitement_est_celui_de_la_production_corps_par_corps(
    banc, contenu, question, monkeypatch
):
    """LE MÊME CORPS PAR LES DEUX CHEMINS, ET LE MÊME RÉSULTAT EXIGÉ.

    Ce garde ne relit pas le code de `translate_question` : il le FAIT TOURNER,
    sur le même corps que le banc, et compare les deux sorties. Un banc qui
    oublierait un des trois refus — vide, trop longue, identique — donnerait à
    `retrieve` une requête que le service n'émet jamais, et le gain attribué à
    la recherche translingue porterait en partie sur des requêtes fantômes.

    C'est la seule façon de prouver « reproduit à l'identique » : comparer deux
    listes de règles écrites à la main prouverait qu'elles se ressemblent.
    """
    import asyncio

    import src.agent.llm as llm

    corps = {"choices": [{"message": {"content": contenu}, "finish_reason": "stop"}]}

    class _Reponse:
        status_code = 200

        def json(self):
            return corps

        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return _Reponse()

    monkeypatch.setattr(llm.httpx, "AsyncClient", _Client)
    de_la_production = asyncio.run(llm.translate_question(question))
    du_banc = banc.post_traitement_de_la_production(question, llm._contenu_message(corps))
    assert du_banc == de_la_production, (
        f"le banc rend {du_banc!r} là où la production rend {de_la_production!r}"
    )


def test_le_gabarit_de_traduction_est_celui_de_la_production_et_non_une_copie(banc, monkeypatch):
    """LE PROMPT N'EST PAS RECOPIÉ, IL EST RENDU PAR L'ENVIRONNEMENT DE `src/`.

    Un prompt recopié dans le banc divergerait du jour où la production
    changerait le sien, et le banc mesurerait une traduction que le service
    n'émet plus — sans qu'aucune ligne ne soit fausse.
    """
    from src.agent.llm import _get_jinja_env

    envoyes: list[dict] = []

    class _Reponse:
        def json(self):
            return {"choices": [{"message": {"content": "traduit"}, "finish_reason": "stop"}]}

        def raise_for_status(self):
            return None

    def _post(url, timeout=None, **charges):
        # `httpx.post` reçoit la charge par le mot-clé `json`, qui est aussi le
        # nom du module importé plus haut : le prendre par `**charges` évite
        # l'ombre sans changer l'appel que le banc écrit.
        envoyes.append(charges["json"])
        return _Reponse()

    monkeypatch.setattr(banc.httpx, "post", _post)
    banc.traduire_comme_la_production("La question ?", "http://h:8100", "m", 10.0)
    attendu = _get_jinja_env().get_template("translate_query.j2").render(question="La question ?")
    (charge,) = envoyes
    assert charge["messages"][0]["content"] == attendu
    # LES QUATRE RÉGLAGES DE `translate_question`, et ils ne sont pas décoratifs :
    # une température non nulle rendrait deux traductions différentes pour la
    # même sous-question selon la campagne.
    assert charge["temperature"] == 0.0
    assert charge["max_tokens"] == 150
    assert charge["stream"] is False


def test_une_sous_question_sans_traduction_part_en_recherche_monolingue(banc, monkeypatch):
    """LE REFUS DE LA PRODUCTION SE PROPAGE JUSQU'À `retrieve`, ET C'EST VOULU.

    Quand `translate_question` rend `None`, la production cherche dans une seule
    langue POUR CETTE QUESTION. Le banc doit faire de même : donner à `retrieve`
    une traduction que la production aurait jetée ferait mesurer une chaîne qui
    n'existe pas.
    """
    vus: list[object] = []
    un = _chunk("c-1", "1111111111")

    import src.agent.retriever as retriever

    def _retrieve_double(question, translation=None, **_):
        vus.append(translation)
        return [un]

    monkeypatch.setattr(retriever, "retrieve", _retrieve_double)
    monkeypatch.setattr(retriever, "rerank", lambda q, chunks: list(chunks))

    banc.jouer_les_variantes(
        "q entière ?",
        "whole question?",
        ["1111111111"],
        ["sous-question A ?", "sous-question B ?"],
        utilisable=True,
        traductions_des_sous={"sous-question A ?": "sub-question A?", "sous-question B ?": None},
        sous_questions_traduites=[],
        traduite_utilisable=False,
    )
    assert "sub-question A?" in vus, "la sous-question traduite doit porter sa traduction"
    assert vus.count(None) >= 1, "celle que la production aurait refusée part SANS traduction"


# ─── 2. LE REPLI DES VARIANTES TRADUITES EST LA PRODUCTION, ET PAS LA BASE ──


def test_le_repli_des_variantes_traduites_recopie_la_production_et_pas_la_requete_nue(
    banc, monkeypatch
):
    """DEUX REPLIS DANS UN MÊME BANC, ET ILS NE SONT PAS INTERCHANGEABLES.

    Les variantes du §4.78 ne traduisent pas : quand il n'y a rien à décomposer,
    elles retombent sur la requête unique SANS traduction, et c'est ce qui les
    rend comparables à leur base appariée. Les variantes traduites, elles,
    traduisent : une question qu'elles renoncent à décomposer garde sa recherche
    translingue, donc leur repli est LA PRODUCTION EXACTE.

    Confondre les deux ne lèverait rien et fausserait la non-régression dans le
    sens qui arrange : sur le jeu de réglage, 69 questions sur 130 sont en repli,
    et leur faire perdre la traduction ferait porter aux variantes traduites une
    perte que l'implémentation n'aurait pas.

    Les deux doubles rendent des classements DIFFÉRENTS selon qu'une traduction
    est passée, sans quoi la confusion serait invisible.
    """
    avec, sans = _chunk("c-avec", "aaaaaaaaaa"), _chunk("c-sans", "ssssssssss")

    import src.agent.retriever as retriever

    monkeypatch.setattr(
        retriever,
        "retrieve",
        lambda question, translation=None, **_: [avec] if translation else [sans],
    )
    monkeypatch.setattr(retriever, "rerank", lambda question, chunks: list(chunks))

    mesure = banc.jouer_les_variantes(
        "Which deployment strategy limits blast radius?",
        "Quelle stratégie de déploiement limite le rayon d'impact ?",
        ["aaaaaaaaaa", "ssssssssss"],
        ["Which deployment strategy limits blast radius?"],
        utilisable=False,
        traductions_des_sous={},
        sous_questions_traduites=[],
        traduite_utilisable=False,
    )
    variantes = mesure["variantes"]
    rangs = {nom: {eid: r["rerank"] for eid, r in v.items()} for nom, v in variantes.items()}
    assert rangs["unique_avec_traduction"] == {"aaaaaaaaaa": 1, "ssssssssss": None}
    assert rangs["unique_sans_traduction"] == {"aaaaaaaaaa": None, "ssssssssss": 1}
    # LES DEUX REPLIS, ET ILS DIVERGENT — c'est tout l'objet de ce garde.
    assert rangs["fusion_rerank_entiere"] == rangs["unique_sans_traduction"]
    assert rangs["fusion_rerank_sous_questions"] == rangs["unique_sans_traduction"]
    assert rangs["fusion_traduite_rerank_entiere"] == rangs["unique_avec_traduction"]
    assert rangs["fusion_traduite_rerank_sous_questions"] == rangs["unique_avec_traduction"]
    assert rangs["fusion_question_traduite_decomposee"] == rangs["unique_avec_traduction"]
    # ET LE REPLI NE FACTURE RIEN DE PLUS. Un repli qui recopierait les rangs en
    # relançant la chaîne ferait paraître la décomposition plus chère qu'elle
    # n'est sur les questions simples, qui sont les plus nombreuses.
    paires = mesure["paires_rerankees"]
    assert paires["fusion_traduite_rerank_entiere"] == paires["unique_avec_traduction"] == 1
    assert paires["fusion_traduite_rerank_sous_questions"] == 1
    assert paires["fusion_question_traduite_decomposee"] == 1


# ─── 3. LA PONDÉRATION EST CELLE DU RÉGLAGE, ET ELLE N'EST PAS ÉCRITE EN DUR ─


def test_la_fusion_ponderee_lit_le_reglage_et_ne_code_aucun_poids_en_dur(banc, monkeypatch):
    """LE POIDS VIENT DE `settings`, ET LE TÉMOIN LE DÉPLACE POUR LE PROUVER.

    Sur ce poste `TRANSLATION_WEIGHT` vaut **1,0**, c'est-à-dire l'égalité : un
    banc qui écrirait 1,0 en dur rendrait aujourd'hui exactement les mêmes
    chiffres qu'un banc qui lit le réglage, et le jour où le service passerait à
    0,5 il mesurerait encore l'ancien. Le témoin déplace donc le réglage à 0,3 et
    exige que l'ORDRE change — ce qu'un poids en dur ne ferait pas.

    Le calcul est celui du RRF de `src/` : à `rrf_k=60`, un candidat au rang 2
    d'un classement de poids 1,0 marque 1/62 = 0,0161, et un candidat au rang 1
    d'un classement de poids 0,3 marque 0,3/61 = 0,0049. À poids égaux le second
    passe devant ; à 0,3 il passe derrière.
    """
    import src.agent.settings as reglages

    premier = _chunk("c-1", "1111111111")
    deuxieme = _chunk("c-2", "2222222222")
    traduit = _chunk("c-3", "3333333333")
    origine = [premier, deuxieme]
    traduction = [traduit]

    monkeypatch.setattr(reglages.settings, "translation_weight", 1.0)
    egaux = banc.fuse_pondere(
        [origine, traduction], 10, [1.0, reglages.settings.translation_weight]
    )
    assert [c.element_id for c in egaux][:2] == ["1111111111", "3333333333"], (
        "à poids égaux, le rang 1 de la traduction passe devant le rang 2 de l'origine"
    )

    monkeypatch.setattr(reglages.settings, "translation_weight", 0.3)
    moindre = banc.fuse_pondere(
        [origine, traduction], 10, [1.0, reglages.settings.translation_weight]
    )
    assert [c.element_id for c in moindre][:2] == ["1111111111", "2222222222"], (
        "à poids moindre, la traduction cède la deuxième place"
    )


def test_la_variante_du_second_ordre_pondere_la_famille_traduite_et_pas_l_autre(banc, monkeypatch):
    """LES DEUX FAMILLES N'ENTRENT PAS AU MÊME POIDS, et le témoin les sépare.

    Un banc qui donnerait le poids de la traduction aux DEUX familles — ou à
    aucune — rendrait une fusion que la production ne sait pas faire. Le double
    relève les poids réellement passés à `fuse`.
    """
    import src.agent.retriever as retriever
    import src.agent.settings as reglages

    vus: dict[str, object] = {}

    def _fuse_espion(classements, top_k, poids=None):
        vus["poids"] = list(poids or [])
        return list(classements[0])

    monkeypatch.setattr(reglages.settings, "translation_weight", 0.3)
    monkeypatch.setattr(
        retriever, "retrieve", lambda question, translation=None, **_: [_chunk("c", "aaaaaaaaaa")]
    )
    monkeypatch.setattr(retriever, "rerank", lambda question, chunks: list(chunks))
    import src.agent.lexical as lexical

    monkeypatch.setattr(lexical, "fuse", _fuse_espion)

    banc.jouer_les_variantes(
        "q ?",
        "q translated?",
        ["aaaaaaaaaa"],
        ["sous A ?", "sous B ?"],
        utilisable=True,
        traductions_des_sous={"sous A ?": None, "sous B ?": None},
        sous_questions_traduites=["sub A?", "sub B?", "sub C?"],
        traduite_utilisable=True,
    )
    assert vus["poids"] == [1.0, 1.0, 0.3, 0.3, 0.3], (
        "deux sous-questions d'origine au poids plein, trois traduites au poids de la traduction"
    )


# ─── 4. LES QUATRE ÉTAGES, ET LEUR ORDRE LES REND EXCLUSIFS ─────────────────


def _r(par_requete, fusion, rerank):
    return {"par_requete": list(par_requete), "fusion": fusion, "rerank": rerank}


@pytest.mark.parametrize(
    ("rangs", "attendu"),
    [
        # `arrive` — et il est le contrôle positif des trois autres : un
        # classeur qui ne dirait JAMAIS `arrive` serait vert sur eux.
        (_r([3], 3, 1), "arrive"),
        (_r([3], 3, 10), "arrive"),
        # LE SEUIL DANS L'AUTRE SENS : onze n'est pas dans le haut, et c'est
        # alors le RERANKING qui perd l'ancrage, pas la fusion.
        (_r([3], 3, 11), "perdu_au_reranking"),
        # `perdu_au_reranking` — la fusion l'avait, le reranker ne le rend pas.
        (_r([2, 40], 7, None), "perdu_au_reranking"),
        # `perdu_a_la_fusion` — une sous-requête l'avait, la coupe l'a perdu.
        (_r([49, None], None, None), "perdu_a_la_fusion"),
        (_r([None, 50], None, None), "perdu_a_la_fusion"),
        # `jamais_recupere` — aucune sous-requête ne l'a ramené.
        (_r([None, None], None, None), "jamais_recupere"),
        (_r([], None, None), "jamais_recupere"),
    ],
)
def test_l_etage_de_perte_nomme_le_premier_qui_reconnait_l_ancrage(banc, rangs, attendu):
    """L'ORDRE DES QUATRE ÉTAGES EST CE QUI LES REND EXCLUSIFS.

    C'est la construction de la table des causes du §4.77, et elle est reprise
    parce qu'elle a une propriété que rien d'autre ne donne : les comptes
    SOMMENT. Un ancrage que la fusion a gardé et que le reranker écarte doit
    tomber dans `perdu_au_reranking` et nulle part ailleurs — le déclarer
    « jamais récupéré » ferait croire qu'aucun élargissement de la recherche ne
    le ramènerait, alors qu'il était déjà là.
    """
    assert banc.etage_de_perte(rangs) == attendu


def test_une_question_est_classee_par_son_ancrage_le_plus_amont(banc):
    """RÉPARER L'AVAL NE RENDRAIT PAS COMPLÈTE UNE QUESTION PERDUE EN AMONT.

    Une question porte deux ancrages : l'un est écarté par le reranker, l'autre
    n'est jamais récupéré. La classer « perdue au reranking » ferait lire qu'un
    meilleur reranking la sauverait — il ne la sauverait pas, l'autre ancrage
    n'étant dans aucune liste. Le témoin oppose les deux lectures sur la MÊME
    question, et une seule peut être verte.
    """
    assert banc.etage_de_la_question(["perdu_au_reranking", "jamais_recupere"]) == "jamais_recupere"
    assert banc.etage_de_la_question(["arrive", "perdu_a_la_fusion"]) == "perdu_a_la_fusion"
    assert banc.etage_de_la_question(["perdu_au_reranking", "arrive"]) == "perdu_au_reranking"
    # ET UNE QUESTION DONT TOUS LES ANCRAGES ARRIVENT EST COMPLÈTE, sans quoi le
    # classeur ne dirait jamais `arrive` et les trois assertions ci-dessus
    # seraient vertes pour rien.
    assert banc.etage_de_la_question(["arrive", "arrive"]) == "arrive"


def _ligne(identifiant, gold, rangs_par_variante):
    """Une ligne de bilan, avec les SEPT variantes renseignées.

    Les variantes non nommées par l'appelant reçoivent les rangs de la première :
    un dictionnaire incomplet ferait lever `KeyError` au dépouillement, et le
    garde mesurerait alors sa propre fixture.
    """
    defaut = next(iter(rangs_par_variante.values()))
    return {
        "id": identifiant,
        "gold": list(gold),
        "variantes": {v: rangs_par_variante.get(v, defaut) for v in _VARIANTES},
    }


_VARIANTES = (
    "unique_avec_traduction",
    "unique_sans_traduction",
    "fusion_rerank_entiere",
    "fusion_rerank_sous_questions",
    "fusion_traduite_rerank_entiere",
    "fusion_traduite_rerank_sous_questions",
    "fusion_question_traduite_decomposee",
)


def test_les_sept_variantes_du_banc_sont_bien_celles_que_les_gardes_eprouvent(banc):
    """Une variante ajoutée au banc sans être éprouvée ici doit ROUGIR.

    Sans ce garde, une huitième variante entrerait dans les tableaux publiés
    sans qu'aucune scène ne l'ait vue, et les fixtures ci-dessus la
    renseigneraient en silence par recopie de la première.
    """
    assert banc.VARIANTES == _VARIANTES
    assert _VARIANTES[:4] == banc.VARIANTES_DU_LOT_38
    assert set(banc.VARIANTES_NEUVES) == set(_VARIANTES[4:])


def test_la_repartition_par_etage_somme_au_jeu_qu_elle_decrit(banc):
    """UNE TABLE QUI NE SOMME PAS DÉCRIT AUTRE CHOSE QUE LE JEU.

    C'est la propriété que la table des causes du §4.77 portait, et la seule qui
    attrape un classeur qui oublierait un ancrage : deux questions, trois
    ancrages, et les quatre étages doivent en compter trois — pas deux, pas
    quatre.
    """
    lignes = [
        _ligne(
            "Q-1",
            ["a", "b"],
            {"unique_avec_traduction": {"a": _r([1], 1, 1), "b": _r([9], 9, None)}},
        ),
        _ligne("Q-2", ["c"], {"unique_avec_traduction": {"c": _r([None], None, None)}}),
    ]
    table = banc.repartir_par_etage(lignes)["unique_avec_traduction"]
    assert table["ancrages"] == {
        "arrive": 1,
        "perdu_au_reranking": 1,
        "perdu_a_la_fusion": 0,
        "jamais_recupere": 1,
    }
    assert table["somme_ancrages"] == 3
    assert table["questions"] == {
        "arrive": 0,
        "perdu_au_reranking": 1,
        "perdu_a_la_fusion": 0,
        "jamais_recupere": 1,
    }
    assert table["somme_questions"] == 2
    assert table["somme_juste"] is True


# ─── 6. L'ÉCART À LA BORNE EST UNE DIFFÉRENCE D'ENSEMBLES ───────────────────


def _oracle(tmp_path, rangs):
    chemin = tmp_path / "oracle.json"
    chemin.write_text(
        json.dumps(
            {
                "lignes": [
                    {"id": qid, "oracle_decomposition_rerank": dict(ancrages)}
                    for qid, ancrages in rangs.items()
                ]
            }
        ),
        encoding="utf-8",
    )
    return chemin


def test_l_ecart_a_la_borne_est_une_intersection_et_non_une_soustraction(banc, tmp_path):
    """LES COMPTES ACCORDENT ET LES ENSEMBLES DIVERGENT — et c'est tout le témoin.

    La borne place deux ancrages : `a` de Q-1 et `c` de Q-2. La variante en place
    deux aussi : `b` de Q-1 et `c` de Q-2. Une lecture par soustraction rendrait
    « 2 − 2 = 0, l'écart est refermé » ; la vérité est qu'un ancrage de la borne
    est manqué et qu'un ancrage hors borne est gagné. C'est la leçon du §4.77,
    portée cette fois sur l'écart plutôt que sur le contrôle positif.
    """
    oracle = _oracle(tmp_path, {"Q-1": {"a": 1, "b": 40}, "Q-2": {"c": 2}})
    lignes = [
        _ligne(
            "Q-1",
            ["a", "b"],
            {"unique_avec_traduction": {"a": _r([20], 20, None), "b": _r([1], 1, 1)}},
        ),
        _ligne("Q-2", ["c"], {"unique_avec_traduction": {"c": _r([1], 1, 1)}}),
    ]
    ecart = banc.ecart_a_la_borne(lignes, oracle)
    table = ecart["variantes"]["unique_avec_traduction"]
    assert ecart["borne_ancrages"] == 2
    assert table["ancrages_atteints"] == 2, "les comptes ACCORDENT"
    assert table["ancrages_de_la_borne_manques"] == 1, "et pourtant un ancrage de la borne manque"
    assert table["ancrages_hors_borne_gagnes"] == 1, "et un ancrage hors borne est gagné"
    # L'ÉTAGE OÙ IL SE PERD, et c'est la réponse à la question ouverte B du §4.78.
    assert table["ancrages_manques_par_etage"]["perdu_au_reranking"] == 1
    assert table["somme_juste"] is True


def test_l_ecart_a_la_borne_repartit_les_questions_manquees_par_etage(banc, tmp_path):
    """LA RÉPARTITION EN QUESTIONS, ET ELLE EST NOMMÉE.

    L'oracle rend Q-1 complète ; la variante ne la rend pas, parce que son second
    ancrage n'est jamais récupéré. Le banc doit NOMMER Q-1 et dire l'étage — un
    compte seul ferait recompter à la main ce que le fichier sait déjà.
    """
    oracle = _oracle(tmp_path, {"Q-1": {"a": 1, "b": 2}})
    lignes = [
        _ligne(
            "Q-1",
            ["a", "b"],
            {"unique_avec_traduction": {"a": _r([1], 1, 1), "b": _r([None], None, None)}},
        )
    ]
    table = banc.ecart_a_la_borne(lignes, oracle)["variantes"]["unique_avec_traduction"]
    assert table["questions_de_la_borne_manquees"] == ["Q-1"]
    assert table["questions_manquees_par_etage"]["jamais_recupere"] == 1
    assert table["somme_juste"] is True


def test_une_question_sans_ancrage_mesurable_n_est_pas_declaree_complete(banc):
    """`all()` SUR UN DICTIONNAIRE VIDE EST VRAI, et c'est le piège du §4.78.

    Une question dont aucun ancrage n'est mesurable passerait pour un succès à
    TOUTES les variantes, et gonflerait les sept colonnes d'un coup.
    """
    lignes = [_ligne("Q-VIDE", [], {"unique_avec_traduction": {}})]
    depouille = banc.depouiller(lignes)
    assert depouille["unique_avec_traduction"]["questions_completes"] == 0
    assert depouille["unique_avec_traduction"]["questions_completes_ids"] == []


def test_la_non_regression_nomme_les_gagnees_et_les_perdues_et_pas_qu_un_solde(banc):
    """UN SOLDE NET CACHE UN ÉCHANGE, et le jeu de contrôle du §4.78 l'a montré.

    Son total est resté à **14** en perdant `q18` et en gagnant `q05` : seules
    les listes nommées le disent. Le témoin reproduit exactement cette forme —
    solde nul, deux mouvements.
    """
    lignes = [
        _ligne(
            "GARDEE",
            ["a"],
            {"unique_avec_traduction": {"a": _r([1], 1, 1)}},
        ),
        _ligne(
            "PERDUE",
            ["a"],
            {
                "unique_avec_traduction": {"a": _r([1], 1, 1)},
                "fusion_traduite_rerank_sous_questions": {"a": _r([1], 1, None)},
            },
        ),
        _ligne(
            "GAGNEE",
            ["a"],
            {
                "unique_avec_traduction": {"a": _r([1], 1, None)},
                "fusion_traduite_rerank_sous_questions": {"a": _r([1], 1, 1)},
            },
        ),
    ]
    tableau = banc.non_regression(banc.depouiller(lignes), "unique_avec_traduction")
    bilan = tableau["fusion_traduite_rerank_sous_questions"]
    assert bilan["solde"] == 0, "le solde est nul, et il ment"
    assert bilan["perdues"] == ["PERDUE"]
    assert bilan["gagnees"] == ["GAGNEE"]
    # ET LA BASE NE SE COMPARE PAS À ELLE-MÊME : une colonne « 0 perdue » qui
    # serait celle de la référence ferait lire une non-régression parfaite.
    assert "unique_avec_traduction" not in tableau


# ─── 7. LE CONTRÔLE POSITIF, ET SES TROIS TERMES SONT MUTÉS SÉPARÉMENT ──────


def _bilan_lot38(tmp_path, rangs_par_variante):
    """Un bilan du §4.78 au format versionné : `variantes[v][ancrage] = rang`."""
    chemin = tmp_path / "lot38.json"
    identifiants = sorted({q for v in rangs_par_variante.values() for q in v})
    chemin.write_text(
        json.dumps(
            {
                "lignes": [
                    {
                        "id": qid,
                        "variantes": {
                            variante: dict(par_question[qid])
                            for variante, par_question in rangs_par_variante.items()
                        },
                    }
                    for qid in identifiants
                ]
            }
        ),
        encoding="utf-8",
    )
    return chemin


def _reference_4_77(tmp_path, rangs):
    chemin = tmp_path / "p50.json"
    chemin.write_text(
        json.dumps(
            {
                "lignes": [
                    {"id": qid, "rangs": {eid: {"rerank": r} for eid, r in ancrages.items()}}
                    for qid, ancrages in rangs.items()
                ]
            }
        ),
        encoding="utf-8",
    )
    return chemin


_RANGS_ACCORDES = {"Q-1": {"a": 1, "b": 3}, "Q-2": {"a": None}}


def _lignes_accordees():
    return [
        _ligne(
            qid,
            sorted(ancrages),
            {v: {eid: _r([r], r, r) for eid, r in ancrages.items()} for v in _VARIANTES},
        )
        for qid, ancrages in _RANGS_ACCORDES.items()
    ]


def _lot38_accorde(tmp_path):
    return _bilan_lot38(
        tmp_path,
        {v: {qid: dict(anc) for qid, anc in _RANGS_ACCORDES.items()} for v in _VARIANTES[:4]},
    )


def _couples_accordes(banc, monkeypatch, jeu="jeu.yaml"):
    monkeypatch.setitem(banc.CONTROLE_4_78, jeu, dict.fromkeys(_VARIANTES[:4], (2, 1)))


def test_le_controle_positif_accorde_quand_les_trois_termes_coincident(banc, tmp_path, monkeypatch):
    """LE CONTRÔLE POSITIF DU CONTRÔLE POSITIF.

    Sans lui, un contrôle qui refuserait TOUT serait vert sur chacun des témoins
    de refus qui suivent, et le banc ne publierait jamais rien — ce qui se lit
    exactement comme un banc prudent.
    """
    _couples_accordes(banc, monkeypatch)
    lignes = _lignes_accordees()
    verdict = banc.controle_positif(
        lignes,
        banc.depouiller(lignes),
        pathlib.Path("jeu.yaml"),
        _lot38_accorde(tmp_path),
        _reference_4_77(tmp_path, _RANGS_ACCORDES),
    )
    assert verdict["termes_applicables"] == 3
    assert verdict["couples_4_78"]["accord"] is True
    assert verdict["rangs_du_lot_38"]["accord"] is True
    assert verdict["rangs_du_4_77"]["accord"] is True
    assert verdict["rangs_du_4_77"]["rangs_identiques"] == 3
    assert verdict["accord"] is True


def test_le_controle_positif_refuse_un_couple_du_4_78_qui_ne_tombe_pas_juste(
    banc, tmp_path, monkeypatch
):
    """TERME 1 MUTÉ : les rangs coïncident tous, et un compte ne tombe pas.

    C'est la confrontation au DOCUMENT, celle qui attrape un banc qui aurait
    dérivé de concert avec ses propres fichiers de `runs/`.
    """
    monkeypatch.setitem(banc.CONTROLE_4_78, "jeu.yaml", dict.fromkeys(_VARIANTES[:4], (99, 1)))
    lignes = _lignes_accordees()
    verdict = banc.controle_positif(
        lignes,
        banc.depouiller(lignes),
        pathlib.Path("jeu.yaml"),
        _lot38_accorde(tmp_path),
        _reference_4_77(tmp_path, _RANGS_ACCORDES),
    )
    assert verdict["rangs_du_lot_38"]["accord"] is True, "les rangs, eux, coïncident"
    assert verdict["couples_4_78"]["accord"] is False
    assert len(verdict["couples_4_78"]["desaccords"]) == 4
    assert verdict["accord"] is False


def test_le_controle_positif_refuse_un_rang_de_variante_qui_diverge_a_comptes_egaux(
    banc, tmp_path, monkeypatch
):
    """TERME 2 MUTÉ, ET C'EST LE TÉMOIN QUI COMPTE LE PLUS.

    Le désaccord porte sur une variante de fusion — PAS sur la production — et
    les comptes sont IDENTIQUES des deux côtés : deux ancrages dans le haut, une
    question complète, et pourtant un ancrage sort au rang 3 là où le §4.78 le
    met au rang 2. Un contrôle qui ne confronterait que la production, ou que
    des comptes, serait vert ici.
    """
    _couples_accordes(banc, monkeypatch)
    lignes = _lignes_accordees()
    diverge = {v: {qid: dict(anc) for qid, anc in _RANGS_ACCORDES.items()} for v in _VARIANTES[:4]}
    diverge["fusion_rerank_sous_questions"]["Q-1"]["b"] = 2
    verdict = banc.controle_positif(
        lignes,
        banc.depouiller(lignes),
        pathlib.Path("jeu.yaml"),
        _bilan_lot38(tmp_path, diverge),
        _reference_4_77(tmp_path, _RANGS_ACCORDES),
    )
    assert verdict["couples_4_78"]["accord"] is True, "les comptes ACCORDENT"
    par_variante = verdict["rangs_du_lot_38"]["par_variante"]
    assert par_variante["unique_avec_traduction"]["accord"] is True, "la production accorde"
    assert par_variante["fusion_rerank_sous_questions"]["n_desaccords"] == 1
    assert verdict["accord"] is False


def test_le_controle_positif_refuse_un_jeu_qui_n_a_pas_les_memes_cles(banc, tmp_path, monkeypatch):
    """TERME 2 MUTÉ AUTREMENT : zéro désaccord sur zéro clé commune.

    Sans cette exigence, un banc mesurant un autre jeu passerait le contrôle en
    ne partageant aucune clé — et c'est exactement la forme d'un banc qui aurait
    lu le mauvais cache de décompositions.
    """
    _couples_accordes(banc, monkeypatch)
    lignes = _lignes_accordees()
    autres = {v: {"Q-AUTRE": {"z": 1}} for v in _VARIANTES[:4]}
    verdict = banc.controle_positif(
        lignes,
        banc.depouiller(lignes),
        pathlib.Path("jeu.yaml"),
        _bilan_lot38(tmp_path, autres),
        _reference_4_77(tmp_path, _RANGS_ACCORDES),
    )
    terme = verdict["rangs_du_lot_38"]["par_variante"]["unique_avec_traduction"]
    assert terme["cles_communes"] == 0
    assert terme["n_desaccords"] == 0, "zéro désaccord, et il ne prouve RIEN"
    assert terme["accord"] is False
    assert verdict["accord"] is False


def test_le_controle_positif_refuse_un_rang_qui_diverge_du_4_77(banc, tmp_path, monkeypatch):
    """TERME 3 MUTÉ : la chaîne de bout en bout, mesurée la veille par un autre
    instrument, et un seul rang qui bouge suffit à refuser."""
    _couples_accordes(banc, monkeypatch)
    lignes = _lignes_accordees()
    decale = {"Q-1": {"a": 1, "b": 2}, "Q-2": {"a": None}}
    verdict = banc.controle_positif(
        lignes,
        banc.depouiller(lignes),
        pathlib.Path("jeu.yaml"),
        _lot38_accorde(tmp_path),
        _reference_4_77(tmp_path, decale),
    )
    assert verdict["rangs_du_lot_38"]["accord"] is True
    assert verdict["rangs_du_4_77"]["n_desaccords"] == 1
    assert verdict["accord"] is False


def test_un_controle_sans_aucun_terme_applicable_n_accorde_pas(banc, tmp_path):
    """AUCUN TERME APPLICABLE N'EST PAS UN ACCORD.

    Un banc lancé sans référence et sans bilan du lot 38, sur un jeu inconnu de
    la table, ne prouve rien du tout — et `all([])` vaut `True`. Le banc
    publierait alors ses sept variantes sans qu'une seule ait été confrontée.
    """
    lignes = _lignes_accordees()
    verdict = banc.controle_positif(
        lignes, banc.depouiller(lignes), pathlib.Path("inconnu.yaml"), None, None
    )
    assert verdict["termes_applicables"] == 0
    assert verdict["accord"] is False


# ─── 8. LES CACHES SONT EXIGÉS, ET LE BANC N'EN FABRIQUE AUCUN ──────────────


def test_les_decompositions_du_lot_38_sont_exigees_et_jamais_refabriquees(banc, tmp_path):
    """LE CACHE VERSIONNÉ DU §4.78 EST UN ANTÉCÉDENT, PAS UNE COMMODITÉ.

    Refabriquer les sous-questions ferait varier la décomposition EN MÊME TEMPS
    que la traduction — le modèle n'est pas déterministe à température 0,2 — et
    l'écart entre `fusion_rerank_*` et `fusion_traduite_rerank_*` ne serait
    imputable à rien. Son absence doit être un REFUS, pas un cache vide.
    """
    with pytest.raises(SystemExit) as absent:
        banc._decompositions(tmp_path / "jeu_qui_n_existe_pas.yaml", [])
    assert "ABSENT" in str(absent.value)


def test_une_question_sans_decomposition_en_cache_est_un_refus_nomme(banc, tmp_path, monkeypatch):
    """UN CACHE PARTIEL EST PIRE QU'UN CACHE ABSENT.

    Il rendrait un bilan sur un sous-ensemble du jeu sans que le dénominateur
    bouge, et les sept colonnes se liraient comme si le jeu entier avait été
    mesuré. Le refus NOMME les questions manquantes, sans quoi il faudrait les
    chercher à la main.
    """
    chemin = tmp_path / "runs" / ".decomposition-jeu.json"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps({"Q-1": ["a ?", "b ?"]}), encoding="utf-8")
    monkeypatch.setattr(banc, "cache_de_decomposition", lambda jeu: chemin)
    with pytest.raises(SystemExit) as refus:
        banc._decompositions(
            tmp_path / "jeu.yaml", [{"id": "Q-1", "question": "q"}, {"id": "Q-2", "question": "q"}]
        )
    assert "REFUS" in str(refus.value)
    assert "Q-2" in str(refus.value)


def test_chaque_cache_neuf_porte_le_nom_de_son_jeu(banc):
    """UN CACHE UNIQUE POUR TROIS JEUX LIRAIT LES SOUS-QUESTIONS D'UN AUTRE.

    Les identifiants sont locaux à leur fichier, et les sous-questions le sont
    aussi. Le §4.78 a posé la règle pour son cache de décompositions ; les deux
    caches neufs de ce lot la portent également.
    """
    disperse = pathlib.Path("tests/fixtures/jeu_ancrages_disperses.yaml")
    reglage = pathlib.Path("tests/fixtures/golden_qa_generated.yaml")
    for fabrique in (
        banc.cache_de_traduction_des_sous_questions,
        banc.cache_de_decomposition_traduite,
    ):
        assert fabrique(disperse) != fabrique(reglage)
        assert "jeu_ancrages_disperses" in fabrique(disperse).name
        assert "golden_qa_generated" in fabrique(reglage).name


# ─── 9. LE DIAGNOSTIC NOMME CE QU'IL DIAGNOSTIQUE ───────────────────────────


def test_le_diagnostic_rend_l_etage_de_chaque_ancrage_de_chaque_variante(banc):
    """UN DIAGNOSTIC QUI NE RENDRAIT QUE LE RANG FINAL NE DIAGNOSTIQUERAIT RIEN.

    C'est le reproche du §4.78 à lui-même : `G-110`, `q18` et `D-003` y sont
    trois lignes d'un tableau, et personne ne sait à quel étage elles se
    perdent. Le diagnostic doit rendre, pour chaque variante, le rang à CHAQUE
    étage ET le nom de l'étage — et il ne doit rendre QUE les questions nommées.
    """
    lignes = [
        {
            "id": "PERDUE",
            "question": "q ?",
            "traduction": "q?",
            "gold": ["a"],
            "nature": "decomposee",
            "repli": False,
            "sous_questions": ["s1 ?", "s2 ?"],
            "traductions_des_sous_questions": {"s1 ?": "s1?", "s2 ?": None},
            "sous_questions_traduites": ["t1?"],
            "sondes_amont": {"a": {"dense_question": 12}},
            "variantes": {v: {"a": _r([3, None], 14, None)} for v in _VARIANTES},
        },
        {
            "id": "MUETTE",
            "question": "q2 ?",
            "traduction": None,
            "gold": ["b"],
            "nature": "une_seule",
            "repli": True,
            "sous_questions": ["q2 ?"],
            "traductions_des_sous_questions": {},
            "sous_questions_traduites": [],
            "sondes_amont": {},
            "variantes": {v: {"b": _r([1], 1, 1)} for v in _VARIANTES},
        },
    ]
    diagnostic = banc.diagnostiquer(lignes, {"PERDUE"})
    assert [d["id"] for d in diagnostic] == ["PERDUE"], "seules les questions nommées sont rendues"
    (cas,) = diagnostic
    assert cas["sous_questions"] == ["s1 ?", "s2 ?"]
    assert cas["traductions_des_sous_questions"]["s2 ?"] is None
    assert cas["sous_questions_de_la_question_traduite"] == ["t1?"]
    assert cas["sondes_amont"] == {"a": {"dense_question": 12}}
    for variante in _VARIANTES:
        etage = cas["etages"][variante]["a"]
        assert etage["fusion"] == 14, "le rang de FUSION est versionné pour CHAQUE variante"
        assert etage["par_requete"] == [3, None]
        assert etage["etage"] == "perdu_au_reranking"


# ─── 10. AUCUN GARDE NE S'EFFACE ────────────────────────────────────────────


def test_aucun_garde_de_ce_fichier_ne_s_efface_ni_ne_se_relache():
    """UN GARDE QUI S'EFFACE QUAND SON FICHIER MANQUE NE GARDE RIEN.

    Même règle qu'aux §4.77 et §4.78, et elle est délibérée : ce fichier ne
    porte aucune marque d'effacement — ni saut, ni saut conditionnel, ni échec
    attendu — et aucune règle de linter n'y est relâchée en bloc.

    LES MOTIFS NE SONT ÉCRITS NULLE PART EN CLAIR DANS CE FICHIER, PAS MÊME
    ICI : la sonde lit sa propre source, et une phrase qui les nommerait la
    rendrait rouge sans qu'aucune marque n'existe.
    """
    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    # LES MOTIFS SONT ASSEMBLÉS, ET CE N'EST PAS UNE COQUETTERIE : écrits en
    # clair, ils se trouveraient EUX-MÊMES dans ce fichier, et le garde serait
    # rouge sans qu'aucun `skip` n'existe. Une sonde qui s'attrape elle-même ne
    # mesure que sa propre citation.
    interdits = [
        "pytest.mark." + "skip",
        "pytest.mark." + "xfail",
        "skip" + "if",
        "ruff: " + "noqa",
    ]
    for interdit in interdits:
        assert interdit not in source, f"{interdit} dans un fichier de gardes"
    # LE CONTRÔLE POSITIF DE LA SONDE : elle DOIT voir le motif quand il est là.
    assert interdits[0] in f"@{interdits[0]}\ndef test_x(): ..."

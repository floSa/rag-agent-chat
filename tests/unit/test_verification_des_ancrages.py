"""La sonde qui prouve qu'un jeu de questions désigne quelque chose.

`scripts/verifier_les_ancrages.py` est l'antécédent de toute campagne : un
rappel mesuré après son rouge ne veut rien dire. Ce fichier garde ce que la
sonde décide, sans ouvrir de connexion — `verifier()` est pure, et c'est
délibéré : la logique de verdict se teste en mémoire, la vérité des stores se
mesure en la lançant.

**PROUVE QUE TA MESURE ATTEINT SON CAS.** Une sonde qui rend 0 et rend 0 aussi
sur le code défectueux ne prouve rien. Le rouge de cette sonde a donc été
mesuré, pas seulement relu : `mesuré` le 8 septembre 2026 contre les stores en
service, sur le jeu de 138 questions du 3 août 2026 — `rc=1`, **0 / 129** dans
le graphe et **0 / 129** dans ChromaDB ; sur les deux jeux de ce lot — `rc=0`,
**130 / 130** et **44 / 44** dans les deux stores.
"""

import ast
import importlib.util
import json
import pathlib
import re

import pytest

_RACINE = pathlib.Path(__file__).resolve().parents[2]
_SCRIPT = _RACINE / "scripts" / "verifier_les_ancrages.py"


def _sonde():
    """Charge le script sans faire de `scripts/` un paquet."""
    spec = importlib.util.spec_from_file_location("verifier_les_ancrages", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _question(identifiant: str, **champs):
    return {"id": identifiant, "gold_element_ids": [], **champs}


# ─── Ce qui fait de cette sonde une sonde en lecture seule ───────────────────


class TestLaSondeEstEnLectureSeule:
    """Une campagne LIT. Le dire dans un docstring n'est pas le garantir.

    Ce dépôt travaille contre des stores qui sont l'antécédent de la campagne de
    référence du pipeline : une écriture accidentelle depuis un outil de mesure
    détruirait un état qu'aucune conversation ne peut reconstruire sans
    réingérer — et réingérer est interdit.

    LA FORME EST UNE LECTURE DE L'ARBRE SYNTAXIQUE, ET LA PREMIÈRE FORME ÉTAIT
    FAUSSE. Une recherche de la sous-chaîne `.add(` dans le texte du fichier
    rougissait sur `trouves.add(...)` — un ensemble Python, appel parfaitement
    légitime. Un garde qui rougit sur du code sain est retiré par le suivant,
    donc désarmé : c'est un faux garde, pas un garde strict. L'arbre syntaxique
    relève le NOM de chaque méthode appelée, ce qui distingue `collection.add(`
    de `parser.add_argument(` sans lister les cas.

    Ce qu'elle n'attrape pas, et il faut le dire : une écriture obtenue par
    réflexion (`getattr(coll, "ad" + "d")`). Elle attrape la façon dont une
    écriture arrive vraiment — quelqu'un ajoute un `.upsert(` pour « corriger
    une métadonnée en passant ».
    """

    # Les verbes d'écriture de l'API ChromaDB. `count`, `get` et
    # `get_collection` sont les lectures, et elles restent permises.
    _ECRITURES_CHROMA = frozenset({"add", "upsert", "modify", "delete", "update"})
    # Les verbes d'écriture nGQL, suivis d'une espace : c'est ainsi qu'ils
    # s'écrivent dans une requête.
    _ECRITURES_NGQL = ("INSERT ", "UPDATE ", "UPSERT ", "DELETE ", "DROP ", "CREATE ")

    @staticmethod
    def _methodes_appelees(source: str) -> set[str]:
        """Le nom de chaque méthode appelée dans le module."""
        return {
            noeud.func.attr
            for noeud in ast.walk(ast.parse(source))
            if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Attribute)
        }

    def test_le_script_n_appelle_aucun_verbe_d_ecriture(self) -> None:
        source = _SCRIPT.read_text(encoding="utf-8")
        interdits = sorted(self._methodes_appelees(source) & self._ECRITURES_CHROMA)
        assert not interdits, (
            f"{_SCRIPT.name} appelle {interdits} : une sonde de mesure ne doit "
            "jamais écrire dans ChromaDB — l'index en service est l'antécédent de "
            "la campagne de référence du pipeline."
        )

    def test_le_script_ne_porte_aucune_requete_d_ecriture_ngql(self) -> None:
        texte = _SCRIPT.read_text(encoding="utf-8")
        # Les verbes apparaissent légitimement dans les COMMENTAIRES qui
        # expliquent le garde ; on ne lit donc que le code.
        code = "\n".join(
            ligne for ligne in texte.splitlines() if not ligne.lstrip().startswith("#")
        )
        trouves = [motif for motif in self._ECRITURES_NGQL if motif in code]
        assert not trouves, f"{_SCRIPT.name} porte une requête nGQL d'écriture : {trouves}"

    def test_le_garde_attrape_bien_une_ecriture(self) -> None:
        """Le garde ci-dessus est-il CAPABLE de rougir ?

        Une inspection qui ne trouve jamais rien ne se distingue pas d'une
        inspection cassée. On lui donne les deux cas : celui qu'il doit
        attraper, et celui qu'il ne doit PAS attraper — c'est ce second cas qui
        avait fait tomber la première forme de ce garde.
        """
        faute = "collection.upsert(ids=['x'], metadatas=[{}])"
        assert self._methodes_appelees(faute) & self._ECRITURES_CHROMA == {"upsert"}

        sain = "trouves = set()\ntrouves.add(x)\nparser.add_argument('--jeu')"
        assert self._methodes_appelees(sain) & self._ECRITURES_CHROMA == {"add"}
        # `set.add` EST dans la liste : c'est pourquoi la sonde n'en appelle
        # aucun, et pourquoi son code le dit à l'endroit où il l'évite.
        assert ".add(" not in "".join(
            ligne
            for ligne in _SCRIPT.read_text(encoding="utf-8").splitlines()
            if not ligne.lstrip().startswith("#")
        )

    def test_les_seules_lectures_de_store_sont_nommees(self) -> None:
        """Et les lectures qu'elle fait sont celles que son docstring annonce."""
        texte = _SCRIPT.read_text(encoding="utf-8")
        assert "get_collection(" in texte
        assert ".count()" in texte
        assert "FETCH PROP ON *" in texte


# ─── Un schéma inconnu n'est pas un jeu conforme ─────────────────────────────


def test_un_jeu_sous_la_mauvaise_cle_est_refuse_et_non_declare_vert() -> None:
    """LE PIÈGE QUE CE TEST FERME, et il est le plus dangereux de la sonde.

    Le pipeline nomme ses ancrages `element_ids`, ce dépôt `gold_element_ids`.
    Une sonde qui lirait la seule clé de ce dépôt sur un jeu du pipeline
    rendrait « 0 ancrage déclaré », donc **aucun désaccord**, donc VERT — sans
    avoir vérifié un seul identifiant. C'est la forme exacte du défaut que le
    lot 5 répare : un instrument qui ne mesure pas et ne le dit pas.

    La sonde lit les deux clés, et LÈVE sur une question qui n'en porte
    aucune : « je ne sais pas lire » ne doit jamais devenir « c'est bon ».
    """
    sonde = _sonde()
    cle, ancrages = sonde.ancrages_de({"id": "q01", "element_ids": ["05f988efec"]})
    assert (cle, ancrages) == ("element_ids", ["05f988efec"])
    cle, ancrages = sonde.ancrages_de({"id": "G-001", "gold_element_ids": ["7b29190883"]})
    assert (cle, ancrages) == ("gold_element_ids", ["7b29190883"])

    with pytest.raises(sonde.StoreInjoignableError, match="schéma inconnu"):
        sonde.ancrages_de({"id": "X-001", "ancres": ["7b29190883"]})


def test_les_deux_vocabulaires_d_abstention_sont_reconnus() -> None:
    """`unanswerable: true` ici, `strate: sans_reponse` chez le pipeline.

    Confondre les deux compterait les quatre questions d'abstention du jeu de 30
    comme des échecs de rappel, au lieu de les mesurer sur l'abstention.
    """
    sonde = _sonde()
    assert sonde.sans_reponse({"unanswerable": True})
    assert sonde.sans_reponse({"strate": "sans_reponse"})
    assert not sonde.sans_reponse({"unanswerable": False, "strate": "simple"})


# ─── Les quatre désaccords que la sonde cherche ──────────────────────────────


class TestLesQuatreDesaccords:
    """Chacun ferme une façon de mesurer zéro sans le savoir."""

    def test_un_ancrage_absent_du_graphe_est_un_desaccord(self) -> None:
        sonde = _sonde()
        bilan = sonde.verifier(
            [_question("G-001", gold_element_ids=["aaaaaaaaaa"])],
            {"aaaaaaaaaa": "htms/Livre/1.html"},
            set(),
        )
        assert bilan["absents_du_graphe"] == [("G-001", "aaaaaaaaaa")]
        assert sonde.desaccords(bilan) == 1

    def test_un_ancrage_absent_de_chromadb_est_un_desaccord(self) -> None:
        """C'est CELUI qui décide du rappel, et le plus traître des deux.

        `retrieved_element_ids` sort des métadonnées de l'index vectoriel : un
        ancrage présent au graphe et absent de l'index a l'air bon et ne peut
        JAMAIS être trouvé. Les deux stores ne portent pas les mêmes
        populations — `mesuré` le 8 septembre 2026 : 15 196 sommets au graphe,
        **3 750** `element_id` distincts dans ChromaDB.
        """
        sonde = _sonde()
        bilan = sonde.verifier(
            [_question("G-001", gold_element_ids=["aaaaaaaaaa"])], {}, {"aaaaaaaaaa"}
        )
        assert bilan["absents_de_chromadb"] == [("G-001", "aaaaaaaaaa")]
        assert bilan["absents_du_graphe"] == []
        assert sonde.desaccords(bilan) == 1

    def test_un_document_discordant_est_un_desaccord(self) -> None:
        """L'ancrage existe, mais pas dans le document que le jeu lui prête.

        `rappel_documents` mesurerait alors autre chose que ce qu'il annonce.
        """
        sonde = _sonde()
        bilan = sonde.verifier(
            [
                _question(
                    "G-001",
                    gold_element_ids=["aaaaaaaaaa"],
                    _origine={"source_path": "htms/Livre/1.html"},
                )
            ],
            {"aaaaaaaaaa": "htms/Autre livre/9.html"},
            {"aaaaaaaaaa"},
        )
        assert bilan["documents_discordants"] == [
            ("G-001", "aaaaaaaaaa", "htms/Livre/1.html", "htms/Autre livre/9.html")
        ]

    def test_une_question_a_reponse_sans_ancrage_est_un_desaccord(self) -> None:
        sonde = _sonde()
        bilan = sonde.verifier([_question("G-001")], {}, set())
        assert len(bilan["strates_incoherentes"]) == 1
        assert "ne mesure rien" in bilan["strates_incoherentes"][0]

    def test_une_abstention_qui_porte_un_ancrage_est_un_desaccord(self) -> None:
        sonde = _sonde()
        bilan = sonde.verifier(
            [_question("N-001", unanswerable=True, gold_element_ids=["aaaaaaaaaa"])],
            {"aaaaaaaaaa": "htms/Livre/1.html"},
            {"aaaaaaaaaa"},
        )
        assert len(bilan["strates_incoherentes"]) == 1
        assert "abstention attendue" in bilan["strates_incoherentes"][0]

    def test_un_jeu_sain_ne_rend_aucun_desaccord(self) -> None:
        """Et le vert existe : sans lui, le rouge ne prouverait rien non plus."""
        sonde = _sonde()
        bilan = sonde.verifier(
            [
                _question(
                    "G-001",
                    gold_element_ids=["aaaaaaaaaa"],
                    _origine={"source_path": "htms/Livre/1.html"},
                ),
                _question("N-001", unanswerable=True),
            ],
            {"aaaaaaaaaa": "htms/Livre/1.html"},
            {"aaaaaaaaaa"},
        )
        assert sonde.desaccords(bilan) == 0
        assert bilan["dans_le_graphe"] == bilan["dans_chromadb"] == 1
        assert bilan["ancrages_distincts"] == 1


# ─── Le bilan versionné du 8 septembre 2026 ──────────────────────────────────


def test_le_bilan_versionne_atteste_que_les_deux_jeux_designent_le_corpus() -> None:
    """La mesure qui autorise la campagne laisse un artefact, et il est relu ici.

    Un rapport qui affirme « les ancrages existent » sans fichier laisse la
    conversation suivante devant deux choix : *recroire*, ou *tout refaire*.
    Ce test relit l'artefact et refuse qu'il soit remplacé par un bilan en
    désaccord.
    """
    bilan = json.loads(
        (_RACINE / "runs" / "2026-09-08-ancrages.json").read_text(encoding="utf-8")
    )
    assert bilan["desaccords"] == 0
    assert bilan["chromadb"]["estampille_embedding"] == (
        "paraphrase-multilingual-MiniLM-L12-v2"
    )
    jeux = bilan["jeux"]
    assert len(jeux) == 2
    for nom, resultat in jeux.items():
        distincts = resultat["ancrages_distincts"]
        assert distincts > 0, f"{nom} ne déclare aucun ancrage"
        assert resultat["dans_le_graphe"] == distincts, nom
        assert resultat["dans_chromadb"] == distincts, nom


def test_la_sonde_nomme_les_deux_invocations_qui_atteignent_les_stores() -> None:
    """`graphd` et `chromadb` n'exposent aucun port sur l'hôte.

    Un mode d'emploi qui donne une adresse IP de conteneur périme à la première
    reconstruction de la pile. Le docstring donne les DEUX invocations qui
    tiennent : celle qui découvre les adresses par `docker inspect`, et celle
    qui passe par un conteneur déjà branché au réseau.
    """
    docstring = _sonde().__doc__ or ""
    assert "docker inspect" in docstring
    assert "docker exec -i rag-agent-api python -" in docstring
    assert not re.search(r"\b172\.\d+\.\d+\.\d+\b", docstring), (
        "une adresse IP de conteneur est figée dans le docstring : elle périmera"
    )

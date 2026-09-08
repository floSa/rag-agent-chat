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
import sys

import nebula3.gclient.net.SessionPool as SessionPoolModule
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
        # ET C'EST LE POINT : `set.add` EST dans la liste, donc l'arbre
        # syntaxique NE SAIT PAS distinguer `trouves.add` de `collection.add`.
        # C'est pourquoi la sonde n'appelle aucun `add` du tout et le dit à
        # l'endroit où elle l'évite. Il ne sait en revanche distinguer
        # `parser.add_argument`, ce que la sous-chaîne `.add(` ne savait pas.
        #
        # UNE TROISIÈME ASSERTION A VÉCU ICI, ET ELLE EST RETIRÉE LE 8 SEPTEMBRE
        # 2026 : une recherche de la sous-chaîne `.add(` dans le code de la
        # sonde — c'est-à-dire exactement la forme que le docstring de cette
        # classe déclare fausse, revenue trois lignes plus bas. Elle était
        # STRICTEMENT REDONDANTE : `mesuré` en plantant un `trouves.add(...)`
        # légitime dans la sonde, `test_le_script_n_appelle_aucun_verbe_d_ecriture`
        # rougit déjà sur `['add']`. Elle ne détectait donc rien de plus, et
        # coûtait un second rouge inexplicable sur le même code sain —
        # précisément ce qui pousse un successeur à affaiblir un garde.

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


# ─── Le contrat des codes de sortie, et il n'était gardé nulle part ──────────


class TestUnStoreInjoignableSortEnDeux:
    """« 2 = store injoignable » est écrit à QUATRE sites, et RIEN ne le testait.

    Les quatre : le docstring de `scripts/verifier_les_ancrages.py`, la cible
    `verifier-les-ancrages` du `Makefile`, le compte rendu de campagne du
    8 septembre 2026, et `documentation/tests.md`. `grep` rendait **zéro** test
    sur ce chemin, et le contrat était faux d'un côté sur deux.

    LE DÉFAUT, ET IL TIENT À UN LIEN D'HÉRITAGE. `StoreInjoignableError` hérite
    de `RuntimeError`. `SessionPool.init()` de `nebula3` ne rend PAS `False`
    quand le serveur ne répond pas : il **lève** un `RuntimeError` nu. Un
    `except StoreInjoignableError` n'attrape pas le PARENT de ce qu'il nomme,
    l'exception traversait donc les deux absorptions de `main()`, et Python
    sortait en **1** — le code qui veut dire « ce jeu de questions est périmé »
    — avec une trace, sur un jeu parfaitement sain derrière un graphe éteint.

    `mesuré` le 8 septembre 2026, ChromaDB joignable (`172.20.0.8`) et Nebula
    sur `192.0.2.1` (TEST-NET-1, non routable) :

        RuntimeError: The services status exception:
            [services: ('192.0.2.1', 9669), status: BAD]
        rc=1

    **ET LA PREUVE D'ATTEINTE EST LA MOITIÉ DU TRAVAIL.** Une première sonde
    rendait `rc=2` — le chiffre attendu — pour la mauvaise raison : sans `.env`,
    `--chroma-host` vaut `chromadb`, qui ne résout pas, et le script échouait
    sur ChromaDB **avant** d'atteindre NebulaGraph. Un `rc` juste n'est pas une
    preuve d'atteinte. Les tests ci-dessous portent donc chacun un TÉMOIN
    D'ATTEINTE : `lire_chroma` bouchonné inscrit son passage, et le test refuse
    de conclure si ce passage n'a pas eu lieu.
    """

    # Le message que `nebula3` 3.8.3 lève VRAIMENT, recopié de la sonde
    # ci-dessus. Un message inventé rendrait ce bouchon décoratif : c'est la
    # FORME de l'échec — un `RuntimeError` nu, pas un `False` — qui est le
    # défaut, et le message est ce qui atteste qu'on l'a bien observée.
    _MESSAGE_REEL = "The services status exception: [services: ('192.0.2.1', 9669), status: BAD]"

    @staticmethod
    def _jeu_sain(dossier: pathlib.Path) -> pathlib.Path:
        """Un jeu minimal et SAIN : le seul défaut possible est le store."""
        chemin = dossier / "jeu.yaml"
        chemin.write_text(
            "questions:\n  - id: G-001\n    gold_element_ids: ['aaaaaaaaaa']\n",
            encoding="utf-8",
        )
        return chemin

    def test_l_heritage_de_runtimeerror_est_bien_le_piege(self) -> None:
        """La prémisse du défaut, mesurée plutôt que crue.

        Si un jour `StoreInjoignableError` cessait d'hériter de `RuntimeError`,
        ce test rougirait et dirait au suivant que l'absorption large de
        `lire_nebula` a perdu son motif.
        """
        sonde = _sonde()
        assert issubclass(sonde.StoreInjoignableError, RuntimeError)
        attrape = False
        try:
            raise RuntimeError(self._MESSAGE_REEL)
        except sonde.StoreInjoignableError:
            attrape = True
        except RuntimeError:
            attrape = False
        assert not attrape, (
            "`except StoreInjoignableError` attraperait un RuntimeError nu : "
            "le motif de l'absorption large de `lire_nebula` n'est plus le bon"
        )

    def test_un_nebula_qui_leve_devient_un_store_injoignable(self, monkeypatch) -> None:
        """`lire_nebula` traduit la levée de la bibliothèque, elle ne la laisse pas passer."""

        message = self._MESSAGE_REEL

        class _PoolQuiLeve:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def init(self, *_args, **_kwargs):
                raise RuntimeError(message)

        monkeypatch.setattr(SessionPoolModule, "SessionPool", _PoolQuiLeve)
        sonde = _sonde()
        with pytest.raises(sonde.StoreInjoignableError, match="services status exception"):
            sonde.lire_nebula("192.0.2.1", 9669, "root", "x", "rag_space", ["aaaaaaaaaa"])

    def test_un_pool_qui_rend_false_reste_un_store_injoignable(self, monkeypatch) -> None:
        """L'autre branche n'est pas morte : `init()` rend `False` sur config invalide.

        La correction ÉLARGIT l'absorption, elle ne remplace pas ce test-là.
        """

        class _PoolQuiRefuse:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def init(self, *_args, **_kwargs) -> bool:
                return False

        monkeypatch.setattr(SessionPoolModule, "SessionPool", _PoolQuiRefuse)
        sonde = _sonde()
        with pytest.raises(sonde.StoreInjoignableError, match="connexion refusée"):
            sonde.lire_nebula("192.0.2.1", 9669, "root", "x", "rag_space", ["aaaaaaaaaa"])

    def test_main_sort_en_2_et_non_en_1_sur_un_nebula_injoignable(
        self, monkeypatch, tmp_path
    ) -> None:
        """LE CONTRAT LUI-MÊME, avec son témoin d'atteinte.

        `lire_chroma` bouchonné RÉUSSIT et inscrit son passage : c'est ce qui
        distingue ce test de la fausse sonde qui rendait 2 en échouant sur
        ChromaDB. Sans le témoin, un 2 obtenu avant NebulaGraph serait
        indiscernable d'un 2 obtenu à cause de lui.
        """

        message = self._MESSAGE_REEL

        class _PoolQuiLeve:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def init(self, *_args, **_kwargs):
                raise RuntimeError(message)

        monkeypatch.setattr(SessionPoolModule, "SessionPool", _PoolQuiLeve)
        sonde = _sonde()

        atteint: list[str] = []

        def _chroma_joignable(host, port, nom):
            atteint.append(f"{host}:{port}/{nom}")
            return {"aaaaaaaaaa": ""}, {"embedding_model": "x"}, 1

        monkeypatch.setattr(sonde, "lire_chroma", _chroma_joignable)
        jeu = self._jeu_sain(tmp_path)
        monkeypatch.setattr(sys, "argv", ["verifier_les_ancrages.py", str(jeu)])

        code = sonde.main()

        assert atteint, (
            "ChromaDB n'a pas été atteint : ce test ne prouve RIEN sur le chemin "
            "NebulaGraph — c'est exactement la fausse sonde du 8 septembre 2026"
        )
        assert code == 2, (
            f"un graphe injoignable a rendu {code} : le contrat des quatre sites "
            "promet 2, et 1 voudrait dire « ce jeu de questions est périmé »"
        )

    def test_un_graphe_qui_meurt_pendant_la_lecture_sort_aussi_en_2(self, monkeypatch) -> None:
        """Le graphe répond à `init()` puis disparaît : c'est le MÊME défaut.

        Découvert par mutation M3 : élargir la seule absorption de la connexion
        laissait `pool.execute` lever à travers `main()`, donc `rc=1` sur un jeu
        sain. `NoValidSessionException` dérive d'`Exception`, pas de
        `RuntimeError` — un `except RuntimeError` ne l'aurait pas vue non plus.
        """
        from nebula3.Exception import NoValidSessionException

        atteint: list[str] = []

        class _PoolQuiMeurtEnRoute:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def init(self, *_args, **_kwargs) -> bool:
                atteint.append("init")
                return True

            def execute(self, *_args, **_kwargs):
                atteint.append("execute")
                raise NoValidSessionException("graphd est parti")

        monkeypatch.setattr(SessionPoolModule, "SessionPool", _PoolQuiMeurtEnRoute)
        sonde = _sonde()
        with pytest.raises(sonde.StoreInjoignableError, match="graphd est parti"):
            sonde.lire_nebula("192.0.2.1", 9669, "root", "x", "rag_space", ["aaaaaaaaaa"])
        assert atteint == ["init", "execute"], (
            f"la lecture n'a pas été atteinte ({atteint}) : ce test ne prouve rien "
            "sur le chemin `execute`"
        )

    def test_un_chromadb_injoignable_sort_aussi_en_2(self, monkeypatch, tmp_path) -> None:
        """L'AUTRE MOITIÉ DU CONTRAT, et elle n'était pas gardée non plus.

        Découverte par une mutation qui a manqué sa cible : narrower
        l'absorption de `lire_chroma` — `except StoreInjoignableError` au lieu
        d'`except Exception` — laissait les **19** tests de ce fichier verts.
        Le contrat des quatre sites dit « les stores », au pluriel ; les deux
        côtés le méritent donc.

        `mesuré` le 8 septembre 2026 : hôte `chromadb` non résolu, `rc=2`,
        « RIEN N'EST PROUVÉ — ChromaDB chromadb:8000 / rag_documents ». Ce test
        est la version hors-réseau de cette mesure.
        """
        sonde = _sonde()

        atteint: list[str] = []

        class _ClientMuet:
            def __init__(self, *_args, **_kwargs) -> None:
                atteint.append("HttpClient")

            def get_collection(self, *_args, **_kwargs):
                raise ValueError("Could not connect to a Chroma server.")

        import chromadb

        monkeypatch.setattr(chromadb, "HttpClient", _ClientMuet)
        # Le graphe ne doit JAMAIS être atteint : `lire_chroma` vient avant.
        monkeypatch.setattr(
            sonde,
            "lire_nebula",
            lambda *_a, **_k: (_ for _ in ()).throw(
                AssertionError("le graphe a été atteint alors que ChromaDB avait déjà échoué")
            ),
        )
        jeu = self._jeu_sain(tmp_path)
        monkeypatch.setattr(sys, "argv", ["verifier_les_ancrages.py", str(jeu)])

        code = sonde.main()

        assert atteint == ["HttpClient"], (
            "le client ChromaDB n'a pas été construit : ce test ne prouve rien"
        )
        assert code == 2, f"un ChromaDB injoignable a rendu {code} au lieu de 2"

    def test_un_vrai_desaccord_sort_toujours_en_1(self, monkeypatch, tmp_path) -> None:
        """L'ÉLARGISSEMENT NE DOIT PAS AVALER LE 1, et c'est l'autre direction.

        Une absorption trop large rendrait 2 partout, ce qui ferait passer un
        jeu périmé pour un store éteint — le défaut symétrique, et le plus
        coûteux des deux : il autorise la campagne à ne rien mesurer.
        """

        class _PoolVide:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def init(self, *_args, **_kwargs) -> bool:
                return True

            def execute(self, *_args, **_kwargs):
                raise AssertionError("aucun identifiant ne devrait être demandé")

        monkeypatch.setattr(SessionPoolModule, "SessionPool", _PoolVide)
        sonde = _sonde()

        atteint: list[str] = []

        def _chroma_joignable(host, port, nom):
            atteint.append(f"{host}:{port}/{nom}")
            return {}, {}, 0

        monkeypatch.setattr(sonde, "lire_chroma", _chroma_joignable)
        # Un jeu qui déclare un ancrage que NI l'un NI l'autre store ne porte.
        jeu = self._jeu_sain(tmp_path)
        monkeypatch.setattr(
            sonde, "lire_nebula", lambda *_args, **_kwargs: set()
        )
        monkeypatch.setattr(sys, "argv", ["verifier_les_ancrages.py", str(jeu)])

        code = sonde.main()

        assert atteint, "ChromaDB n'a pas été atteint : le désaccord n'a pas été mesuré"
        assert code == 1, (
            f"un ancrage absent des deux stores a rendu {code} : le désaccord doit "
            "rester un 1, sans quoi un jeu périmé se lit comme un store éteint"
        )

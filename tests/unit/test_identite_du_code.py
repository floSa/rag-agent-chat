"""« QUEL CODE TOURNE ? » — et le gabarit ne peut plus servir une image muette.

CE FICHIER EXISTE PARCE QUE CE CHANTIER A PAYÉ DEUX FOIS SON ABSENCE. Pendant
douze lots, l'agent en service a exécuté du code antérieur et aucun garde livré
ne tournait : personne ne s'en est aperçu, parce que rien ne permettait de poser
la question (§4.42 du registre). Puis le lot 18 a failli rendre l'état servi
anonyme et irrécupérable, une étiquette datée désignant une autre image que son
nom ne le disait.

CE QUI EST GARDÉ ICI EST UNE PROPRIÉTÉ, JAMAIS UN INSTANTANÉ. « L'image porte
l'identité du code qu'elle contient, et `/health` la publie ou déclare qu'elle
ne l'a pas » est une propriété, et c'est ce que ces tests tiennent. « Cette
image-ci porte ce sha-là » est un instantané, et aucun test ici ne l'asserte :
un tel test rougirait à chaque commit et serait désarmé avant la fin du mois.

TROIS FAMILLES, ET AUCUNE NE REMPLACE LES AUTRES :

1. le CONTRAT — une image anonyme ne peut pas se présenter comme identifiée, et
   c'est pydantic qui le refuse, pas la politesse des appelants ;
2. la LECTURE — les trois positions de `identite_du_code()`, y compris les trois
   chemins distincts vers l'anonymat ;
3. le GABARIT — `Dockerfile.agent` et `docker-compose.yml` portent ce qu'il faut
   pour que l'identité arrive jusqu'au conteneur, sinon rien ne la porterait et
   les deux familles précédentes garderaient un mécanisme que personne n'arme.

CES TESTS NE DEMANDENT NI DOCKER, NI RÉSEAU, NI CONTENEUR : ils lisent des
fichiers et appellent une fonction. C'est la condition pour qu'ils tournent dans
la porte, et la porte est le seul endroit où un garde de déploiement sert à
quelque chose.
"""

import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.api.identite_du_code import (
    VAR_ARBRE,
    VAR_CONSTRUITE_LE,
    VAR_SHA,
    identite_du_code,
)
from src.api.schemas import CodeServiHealth, EmbeddingModelHealth

# LE LECTEUR DU COMPOSE EST IMPORTÉ, JAMAIS RECOPIÉ, et le motif est mesuré sur
# ce dépôt. `docker compose` fusionne `docker-compose.override.yml` quand il
# existe, sans qu'aucun `-f` soit écrit : un garde qui ne lit que le fichier de
# base reste VERT sur un override qui défait ce qu'il garde — l'audit du
# 15 septembre 2026 l'a mesuré en posant un override de quatre lignes, et 870
# tests sont restés verts pendant que la docstring promettait de rougir.
#
# `tests/unit/test_health_parallele.py` a appris cette leçon et porte la lecture
# correcte, overrides automatiques ET bases prioritaires (`compose.yaml`, qui
# ferait cesser docker d'ouvrir `docker-compose.yml` du tout). La recopier ici
# en ferait DEUX sites qui divergeraient sans qu'un seul rouge n'apparaisse,
# c'est-à-dire exactement la famille de défaut que ce fichier existe pour
# fermer. Le nom est privé et l'import le sait : c'est un outil de la suite de
# tests, pas une interface publique, et il est importé comme tel.
from tests.unit.test_health_parallele import _compose_tel_que_docker_le_lit

_RACINE = Path(__file__).resolve().parents[2]

# Les trois arguments de construction, tels que `Dockerfile.agent` les déclare.
# Appariés aux variables d'environnement que le module lit : c'est ce
# rapprochement qui empêche l'image et le code de diverger, et il n'existe qu'ici.
_ARGS_ATTENDUS = {
    "CODE_SHA": VAR_SHA,
    "CODE_ARBRE": VAR_ARBRE,
    "CODE_CONSTRUITE_LE": VAR_CONSTRUITE_LE,
}

# Un sha de commit plausible, et il est FABRIQUÉ à dessein : écrire le sha réel
# du dépôt ferait de ces scènes un instantané, périmé au commit suivant.
_UN_SHA = "0" * 39 + "a"


@pytest.fixture
def sans_identite(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un environnement dont les trois variables sont ABSENTES.

    Indispensable, et pas seulement par hygiène : la porte tourne sur un poste
    où rien ne garantit que ces variables ne traînent pas, et un test qui lirait
    l'environnement réel serait vert ou rouge selon la machine.
    """
    for var in (VAR_SHA, VAR_ARBRE, VAR_CONSTRUITE_LE):
        monkeypatch.delenv(var, raising=False)


# ─── 1. Le contrat : l'anonymat ne se négocie pas ─────────────────────────────


class TestUneImageAnonymeNePeutPasPasserPourIdentifiee:
    """LA BORNE DU LOT, et elle est tenue par le modèle lui-même.

    Ce chantier a rencontré trois fois la même forme de défaut sous trois
    visages — une absence rendue en zéro, un catalogue vide mémorisé en « modèle
    absent du serveur », un `usage` vide effaçant une mesure réelle. `None` veut
    dire « on ne me l'a pas dit », JAMAIS « c'est nul » et JAMAIS « c'est à
    jour ». Ces scènes rougissent si une image anonyme se présente comme
    identifiée, et dans les deux sens.

    LE VALIDATEUR EST DANS LE MODÈLE ET NON DANS LA FONCTION DE LECTURE, parce
    que ce modèle valide AUSSI ce qui arrive du dehors : `scripts/evaluate.py`
    et le pipeline d'ingestion lisent le `/health` d'un agent qu'ils n'ont pas
    construit. Un garde posé sur la seule fonction laisserait un corps trafiqué,
    ou un agent à moitié déployé, leur faire croire à une identité.
    """

    def test_un_sha_ne_se_publie_pas_sous_un_etat_anonyme(self) -> None:
        """Le sens qui compte : de l'anonymat qui se déguise en identité."""
        with pytest.raises(ValidationError, match="une image anonyme ne publie pas de sha"):
            CodeServiHealth(etat="anonyme", sha=_UN_SHA, avertissement="peu importe")

    def test_un_etat_identifie_sans_sha_est_refuse(self) -> None:
        """LE SENS INVERSE, et il est le plus insidieux des deux.

        Un `etat: "identifie"` sans sha est la forme que prendrait un mécanisme à
        moitié cassé : le lecteur pressé lit l'état, conclut que l'image est
        identifiée, et ne regarde jamais que le sha manque.
        """
        with pytest.raises(ValidationError, match="Une image sans sha est anonyme"):
            CodeServiHealth(etat="identifie")

    def test_un_etat_arbre_sale_sans_sha_est_refuse(self) -> None:
        """La troisième position obéit au même invariant, et rien ne le forçait.

        `arbre_sale` n'est pas `anonyme` : un sha y est donc exigé, sans quoi
        l'état ne dirait rien du tout tout en ayant l'air de dire quelque chose.
        """
        with pytest.raises(ValidationError, match="Une image sans sha est anonyme"):
            CodeServiHealth(etat="arbre_sale", avertissement="peu importe")

    def test_un_etat_non_identifie_doit_dire_pourquoi(self) -> None:
        """Un code d'état que personne ne sait interpréter est un code que
        personne ne lit : les trois chemins vers l'anonymat ne se soignent pas
        pareil, et seule la phrase les distingue."""
        with pytest.raises(ValidationError, match="doit dire POURQUOI"):
            CodeServiHealth(etat="anonyme")

    def test_une_identite_sure_ne_s_assortit_d_aucune_reserve(self) -> None:
        """L'AUTRE SENS DE LA MÊME CLAUSE, et il n'allait pas de soi.

        Sans lui, `avertissement` pourrait être renseigné sur un `identifie` —
        un état qui affirme la fiabilité tout en portant une réserve, que deux
        lecteurs interpréteraient de deux façons.
        """
        with pytest.raises(ValidationError, match="ne s'assortit d'aucune réserve"):
            CodeServiHealth(etat="identifie", sha=_UN_SHA, avertissement="mais quand même")

    @pytest.mark.parametrize(
        "faux_sha",
        [
            pytest.param("", id="chaine-vide"),
            pytest.param("HEAD", id="reference-non-resolue"),
            pytest.param("unknown", id="le-defaut-qu-on-ecrit-par-reflexe"),
            pytest.param("0" * 7, id="sha-abrege"),
            pytest.param("0" * 39 + "A", id="hexadecimal-majuscule"),
            pytest.param("0" * 41, id="un-caractere-de-trop"),
            pytest.param("$(git rev-parse HEAD)", id="substitution-non-evaluee"),
        ],
    )
    def test_rien_qui_ressemble_a_un_sha_ne_passe_pour_un_sha(self, faux_sha: str) -> None:
        """TROISIÈME PIÈGE DU LOT : ne pas publier une identité non relevée.

        Si le mécanisme d'identité échoue à la construction, ce qu'il rend ne
        doit pas ressembler à un sha. Les sept formes ci-dessus sont celles
        qu'un build cassé produit réellement — une variable vide, une référence
        que `git` n'a pas résolue, un défaut écrit par réflexe, un sha abrégé
        qui peut cesser d'être unique, et une substitution shell qui n'a jamais
        été évaluée.
        """
        with pytest.raises(ValidationError, match="n'est pas un sha de commit"):
            CodeServiHealth(etat="identifie", sha=faux_sha)

    def test_le_contrat_accepte_ce_qu_un_build_correct_produit(self) -> None:
        """LE TÉMOIN INERTE DE CETTE FAMILLE, et il n'est pas décoratif.

        Sans lui, un validateur qui refuserait TOUT serait vert sur les sept
        scènes ci-dessus : elles ne prouveraient alors que sa sévérité, jamais sa
        justesse — et le mécanisme entier serait cassé sans qu'un rouge
        n'apparaisse.
        """
        assert CodeServiHealth(etat="identifie", sha=_UN_SHA).sha == _UN_SHA
        assert CodeServiHealth(etat="anonyme", avertissement="rien de gravé").sha is None


# ─── 2. La lecture : trois positions, et trois chemins vers l'anonymat ────────


class TestCeQueLeBuildAGraveEstCeQuiSePublie:
    """LA SCÈNE DE L'IMAGE ANONYME, et les deux autres positions.

    Chaque scène pose l'environnement qu'une image REELLEMENT construite d'une
    certaine façon porterait, et lit ce que `/health` en dirait.
    """

    def test_une_image_construite_sans_argument_se_declare_anonyme(
        self, sans_identite: None
    ) -> None:
        """LA SCÈNE PRINCIPALE DU LOT.

        `Dockerfile.agent` déclare ses `ARG` SANS valeur par défaut : un
        `docker build` qui ne les passe pas produit trois variables vides dans
        l'image. C'est l'état de toute image construite hors de `make image`, et
        il doit se dire.
        """
        identite = identite_du_code()
        assert identite.etat == "anonyme"
        assert identite.sha is None
        assert identite.avertissement is not None
        assert "construite sans" in identite.avertissement

    def test_une_variable_presente_et_vide_vaut_une_absence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LE CAS RÉEL, ET IL DIFFÈRE DU PRÉCÉDENT.

        `ARG CODE_SHA` non fourni ne produit pas une variable ABSENTE : il
        produit `RAG_AGENT_CODE_SHA=` — présente, et vide. Un `os.environ.get`
        nu rendrait `""`, et une chaîne vide qui se propage jusqu'au contrat est
        le « zéro rendu pour une absence » que ce lot ferme. Le cas ci-dessus
        n'éprouve donc PAS celui-ci, et l'inverse non plus.
        """
        monkeypatch.setenv(VAR_SHA, "")
        monkeypatch.setenv(VAR_ARBRE, "")
        monkeypatch.setenv(VAR_CONSTRUITE_LE, "")
        identite = identite_du_code()
        assert identite.etat == "anonyme"
        # L'ÉTAT SEUL NE SUFFISAIT PAS, ET LA MUTATION L'A DIT. `mesuré` le
        # 16 septembre 2026 : en retirant le `or None` de `_lire`, ce test
        # RESTAIT VERT — la chaîne vide se propageait jusqu'à `_UN_SHA`, qui la
        # refusait, et l'image finissait `anonyme` par un AUTRE chemin. Le test
        # mesurait alors une position que deux codes différents atteignent, donc
        # rien. L'avertissement est ce qui sépare les deux chemins : « rien n'a
        # été gravé » n'est pas « le relevé a échoué », et les deux ne se
        # soignent pas pareil.
        assert identite.avertissement is not None
        assert "construite sans" in identite.avertissement

    def test_des_blancs_ne_font_pas_une_identite(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Un `--build-arg CODE_SHA=" "` est le même non-savoir, autrement écrit."""
        monkeypatch.setenv(VAR_SHA, "   ")
        monkeypatch.setenv(VAR_ARBRE, " propre ")
        identite = identite_du_code()
        assert identite.etat == "anonyme"
        # Même motif que la scène précédente : l'état seul ne distingue pas le
        # code servi d'un code qui aurait cessé de dépouiller ses variables.
        assert identite.avertissement is not None
        assert "construite sans" in identite.avertissement

    def test_un_sha_illisible_laisse_l_image_anonyme_et_le_dit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Un relevé qui a échoué ne se publie pas, ET ne se tait pas non plus.

        Les deux chemins mènent à `anonyme`, mais ils ne se soignent pas de la
        même façon : rien de gravé est un build non instrumenté, un sha illisible
        est un build instrumenté qui s'est cassé. L'avertissement les sépare.
        """
        monkeypatch.setenv(VAR_SHA, "HEAD")
        monkeypatch.setenv(VAR_ARBRE, "propre")
        identite = identite_du_code()
        assert identite.etat == "anonyme"
        assert identite.sha is None
        assert identite.avertissement is not None
        assert "n'est pas un sha de commit" in identite.avertissement

    def test_un_sha_sans_declaration_d_arbre_ne_suffit_pas(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LE TROISIÈME CHEMIN VERS L'ANONYMAT, et c'est le seul qui surprenne.

        Un sha valide, gravé, mais aucun mot sur l'arbre de construction : on ne
        peut pas dire si ce sha décrit le code. Le publier `identifie`
        SUPPOSERAIT la propreté ; le publier `arbre_sale` AFFIRMERAIT la saleté.
        Les deux affirment un fait que le build n'a pas donné, et ce lot existe
        précisément pour cesser de supposer.
        """
        monkeypatch.setenv(VAR_SHA, _UN_SHA)
        monkeypatch.delenv(VAR_ARBRE, raising=False)
        identite = identite_du_code()
        assert identite.etat == "anonyme"
        assert identite.avertissement is not None
        assert "rien ne dit si l'arbre" in identite.avertissement

    def test_un_mot_d_arbre_inconnu_ne_se_devine_pas(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`true`, `clean`, `oui` : trois façons de ne pas dire `propre`.

        Interpréter au plus proche serait un pari, et c'est un pari sur la
        question même que ce lot ferme.
        """
        monkeypatch.setenv(VAR_SHA, _UN_SHA)
        monkeypatch.setenv(VAR_ARBRE, "clean")
        assert identite_du_code().etat == "anonyme"

    def test_un_arbre_sale_publie_son_sha_et_aussi_sa_reserve(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DEUXIÈME PIÈGE DU LOT : un sha relevé dans un arbre sale ne décrit
        pas le code de l'image.

        Il nomme un commit qui NE CONTIENT PAS ce qui tourne. Le taire
        reviendrait à publier une identité fausse ; ne rien publier perdrait le
        seul repère disponible. Il est donc publié AVEC sa réserve, et l'état le
        sépare d'une identité sûre pour tout lecteur qui teste `etat`.
        """
        monkeypatch.setenv(VAR_SHA, _UN_SHA)
        monkeypatch.setenv(VAR_ARBRE, "sale")
        identite = identite_du_code()
        assert identite.etat == "arbre_sale"
        assert identite.sha == _UN_SHA
        assert identite.avertissement is not None
        assert "NE DÉCRIT PAS le code de cette image" in identite.avertissement

    def test_un_build_complet_publie_une_identite_sure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LE TÉMOIN INERTE DE CETTE FAMILLE.

        Sans lui, une lecture qui rendrait TOUJOURS `anonyme` serait verte sur
        les six scènes ci-dessus — le mécanisme serait mort et le banc muet.
        """
        monkeypatch.setenv(VAR_SHA, _UN_SHA)
        monkeypatch.setenv(VAR_ARBRE, "propre")
        monkeypatch.setenv(VAR_CONSTRUITE_LE, "2026-09-16T09:00:00Z")
        identite = identite_du_code()
        assert identite.etat == "identifie"
        assert identite.sha == _UN_SHA
        assert identite.construite_le == "2026-09-16T09:00:00Z"
        assert identite.avertissement is None

    def test_la_date_survit_a_l_anonymat(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Elle est hors de l'invariant, et c'est délibéré : elle est la seule
        chose qu'une image anonyme puisse encore porter honnêtement."""
        monkeypatch.delenv(VAR_SHA, raising=False)
        monkeypatch.setenv(VAR_CONSTRUITE_LE, "2026-09-16T09:00:00Z")
        identite = identite_du_code()
        assert identite.etat == "anonyme"
        assert identite.construite_le == "2026-09-16T09:00:00Z"

    def test_l_identite_est_relue_a_chaque_appel_et_non_figee_a_l_import(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CE QUI REND LES SCÈNES CI-DESSUS POSSIBLES, et rien ne le forçait.

        Une constante de module figerait la valeur à l'import : toutes les
        scènes de ce fichier deviendraient alors des lectures de la même valeur,
        vertes ou rouges ensemble et sans rapport avec ce qu'elles posent. Ce
        test asserte le CHANGEMENT entre deux appels, ce qu'aucune valeur figée
        ne peut produire.
        """
        monkeypatch.delenv(VAR_SHA, raising=False)
        avant = identite_du_code()
        monkeypatch.setenv(VAR_SHA, _UN_SHA)
        monkeypatch.setenv(VAR_ARBRE, "propre")
        apres = identite_du_code()
        assert (avant.etat, apres.etat) == ("anonyme", "identifie")


# ─── 3. `/health` publie l'identité, quelle qu'elle soit ─────────────────────


class TestHealthPublieLIdentiteDuCodeServi:
    """La route doit répondre à « quel code tourne ? » SANS que personne suppose.

    Ces deux scènes passent par le corps HTTP réel plutôt que par la fonction :
    un champ calculé mais jamais publié ne répondrait à personne, et c'est
    exactement l'état dans lequel `/health` était avant ce lot — il publiait
    l'état de tout sauf de lui-même.
    """

    def _corps(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
        """Le corps de `/health`, TOUTES LES SONDES DOUBLÉES ET AUCUNE I/O.

        CE DOUBLAGE N'EST PAS DU CONFORT, ET LA PREMIÈRE ÉCRITURE DE CE FICHIER
        S'EN EST PASSÉE — À TORT. Sans lui, `TestClient` monte l'application
        complète et les sondes partent RÉELLEMENT vers ChromaDB, NebulaGraph et
        le serveur LLM du poste. Trois conséquences, toutes disqualifiantes pour
        un garde qui doit tourner dans la porte : le test parle au réseau, il
        devient vert ou rouge selon ce qui tourne sur la machine, et il fait
        remonter un `PytestUnraisableExceptionWarning` du client Nebula
        (`SessionPool.__del__`) que la suite n'avait pas avant.

        `mesuré` le 16 septembre 2026 : sans ces doublages, cette famille ajoute
        ce warning à la campagne ; avec eux, la suite retrouve son unique
        avertissement d'origine.

        Les six sources d'entrées-sorties de la route sont doublées — les trois
        sondes de `services`, le client HTTP d'Ollama, la concordance du modèle
        d'embedding (qui lit la collection Chroma) et le relevé du moteur. Ce
        qui reste vivant est exactement ce que cette famille mesure : la lecture
        de l'identité du code et sa publication dans le corps.
        """
        from src.api import main
        from tests.unit.test_health_parallele import _ollama_repond_vrai

        monkeypatch.setattr(main.settings, "api_key", "")
        monkeypatch.setattr(main.settings, "torch_device", "cpu")
        monkeypatch.setattr(main, "chroma_ping", lambda: True)
        monkeypatch.setattr(main, "nebula_ping", lambda: True)
        monkeypatch.setattr(main, "lexical_ready", lambda: True)
        monkeypatch.setattr(main.httpx, "AsyncClient", _ollama_repond_vrai())
        monkeypatch.setattr(
            main,
            "etat_modele_embedding",
            lambda: EmbeddingModelHealth(status="ok", expected="peu-importe"),
        )

        async def _pas_de_moteur() -> None:
            return None

        monkeypatch.setattr(main, "_sonder_moteur_llm", _pas_de_moteur)

        with TestClient(main.app) as client:
            reponse = client.get("/health")
        assert reponse.status_code == 200
        corps: dict[str, object] = reponse.json()
        return corps

    def test_le_corps_porte_toujours_la_cle_meme_anonyme(
        self, sans_identite: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LE CHAMP N'EST PAS OPTIONNEL, et c'est le cœur de l'arbitrage.

        Une réponse muette sur l'identité du code se lit comme une réponse
        rassurante : c'est cette lecture qui a laissé douze lots croire qu'ils
        mesuraient les gardes qu'ils venaient de livrer. Le non-savoir a donc un
        nom, et il occupe la place.
        """
        code_servi = self._corps(monkeypatch)["code_servi"]
        assert isinstance(code_servi, dict)
        assert code_servi["etat"] == "anonyme"
        assert code_servi["sha"] is None
        assert code_servi["avertissement"]

    def test_une_image_identifiee_publie_son_sha_dans_le_corps(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LE TÉMOIN INERTE DE CETTE FAMILLE : le champ n'est pas cloué sur
        `anonyme`.

        Sans lui, un `code_servi` écrit en dur à l'anonymat serait vert
        ci-dessus, et la route ne répondrait jamais à la question.
        """
        monkeypatch.setenv(VAR_SHA, _UN_SHA)
        monkeypatch.setenv(VAR_ARBRE, "propre")
        code_servi = self._corps(monkeypatch)["code_servi"]
        assert isinstance(code_servi, dict)
        assert code_servi == {
            "etat": "identifie",
            "sha": _UN_SHA,
            "construite_le": os.environ.get(VAR_CONSTRUITE_LE) or None,
            "avertissement": None,
        }

    def test_une_image_anonyme_ne_degrade_pas_le_service(
        self, sans_identite: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L'ARBITRAGE ÉCRIT AU SITE, ET IL EST GARDÉ DANS CE SENS-CI.

        Une image anonyme est un défaut de PROCÉDURE DE DÉPLOIEMENT, pas une
        panne : elle répond et elle sert. La faire dégrader ferait passer
        `agent-api` `unhealthy` au healthcheck, donc empêcherait `frontend` de
        lever au démarrage à froid — pour une image qui fonctionne. Ce test
        rougirait si quelqu'un branchait `code_servi` sur `status`, et il oblige
        à venir relire le motif avant de le faire.

        `status: "ok"` EST EXIGIBLE ICI, et seulement parce que `_corps` double
        les six sources d'entrées-sorties au vert : sur un poste sans stores, un
        `degraded` viendrait des sondes et ce test mesurerait l'environnement au
        lieu de l'arbitrage. Les deux assertions qui suivent le disent d'ailleurs
        chacune à sa façon — la première que le statut ne bouge pas, la seconde
        que l'anonymat n'a pas non plus été rangé parmi les sondes muettes, où
        `services_unknown` le ferait lire comme une anomalie à réparer côté
        service.
        """
        corps = self._corps(monkeypatch)
        code_servi = corps["code_servi"]
        assert isinstance(code_servi, dict)
        assert code_servi["etat"] == "anonyme"
        assert corps["status"] == "ok"
        services_unknown = corps["services_unknown"]
        assert isinstance(services_unknown, list)
        assert "code_servi" not in services_unknown


# ─── 4. Le gabarit porte ce qu'il faut pour que l'identité arrive ────────────


def _dockerfile() -> str:
    return (_RACINE / "Dockerfile.agent").read_text(encoding="utf-8")


def _args_du_compose(
    texte: str | None = None, texte_override: str | None = None
) -> dict[str, object]:
    """Les `build.args` du service `agent-api`, LUS COMME DOCKER LES LIT.

    `texte` et `texte_override` n'existent que pour les scènes de ce lecteur :
    éprouver qu'un override défait le garde exigerait sinon de muter le vrai
    compose, ce qu'aucun test ne doit faire.
    """
    services = _compose_tel_que_docker_le_lit(texte, texte_override).get("services") or {}
    assert isinstance(services, dict)
    agent = services.get("agent-api")
    assert isinstance(agent, dict), (
        "le service `agent-api` est absent du compose tel que docker le lit : ce "
        "garde lit le service qui SERT, et il ne mesure plus rien"
    )
    build = agent.get("build")
    assert isinstance(build, dict), (
        "`build:` n'est pas une table dans le compose : la forme courte "
        "(`build: .`) ne peut porter aucun argument de construction, donc aucune "
        "identité n'entrerait dans l'image"
    )
    args = build.get("args") or {}
    assert isinstance(args, dict)
    return args


class TestLeGabaritFaitEntrerLIdentiteDansLImage:
    """SANS CES TROIS LIGNES, LE MÉCANISME EXISTE ET PERSONNE NE L'ARME.

    C'est la forme de défaut la plus coûteuse de ce chantier : un garde livré,
    juste, testé — et jamais atteint par ce qui tourne.
    """

    @pytest.mark.parametrize("argument", sorted(_ARGS_ATTENDUS))
    def test_le_compose_passe_les_trois_arguments_au_build(self, argument: str) -> None:
        args = _args_du_compose()
        assert argument in args, (
            f"`{argument}` n'est pas dans les `build.args` du service `agent-api` : "
            "une image construite par `docker compose build` serait ANONYME, et "
            "la question « quel code tourne ? » redeviendrait sans réponse. "
            "Site : documentation/identite_du_code_servi.md"
        )

    @pytest.mark.parametrize("argument,variable", sorted(_ARGS_ATTENDUS.items()))
    def test_chaque_argument_vient_de_l_environnement_et_non_d_une_valeur_ecrite(
        self, argument: str, variable: str
    ) -> None:
        """L'IDENTITÉ VIENT DU BUILD, JAMAIS D'UN FICHIER QU'ON MET À JOUR À LA
        MAIN.

        Une valeur écrite ici serait une constante qui dérive, et ce dépôt en a
        corrigé trois — dont une qui a été écrite FAUSSE par le commit qui
        prétendait la rattraper. Ce test exige une interpolation, donc un relevé
        fait au moment où l'image se construit.
        """
        valeur = args if isinstance(args := _args_du_compose()[argument], str) else ""
        assert valeur.startswith(f"${{{variable}"), (
            f"`{argument}` ne vient pas de `${{{variable}}}` mais de {valeur!r} : "
            "une identité écrite dans le gabarit est un chiffre qui dérive, et "
            "elle nommerait un commit sans rapport avec ce qui tourne"
        )

    @pytest.mark.parametrize("argument", sorted(_ARGS_ATTENDUS))
    def test_le_dockerfile_declare_l_argument_sans_valeur_par_defaut(
        self, argument: str
    ) -> None:
        """LE PIÈGE PRINCIPAL DU LOT, FERMÉ ICI.

        `ARG CODE_SHA=unknown` ferait passer toute image non instrumentée pour
        identifiée — ou, pire, pour porteuse d'un sha. Sans valeur par défaut,
        l'argument non fourni arrive vide, et l'image se déclare anonyme.
        """
        texte = _dockerfile()
        assert re.search(rf"^ARG {argument}$", texte, re.M), (
            f"`ARG {argument}` est absent de Dockerfile.agent, ou il porte une "
            "valeur par défaut. Un défaut ferait passer une image NON "
            "INSTRUMENTÉE pour identifiée, ce qui est le défaut exact que ce "
            "lot ferme."
        )

    @pytest.mark.parametrize("argument,variable", sorted(_ARGS_ATTENDUS.items()))
    def test_le_dockerfile_grave_l_argument_en_variable_d_environnement(
        self, argument: str, variable: str
    ) -> None:
        """C'est le chemin par lequel `/health` l'obtient, sans accès au démon
        Docker."""
        assert re.search(rf"^ENV {variable}=\$\{{{argument}\}}$", _dockerfile(), re.M), (
            f"`ENV {variable}=${{{argument}}}` est absent de Dockerfile.agent : "
            f"l'argument entrerait dans le build sans jamais atteindre le "
            "processus, et `/health` déclarerait l'image anonyme quoi qu'on "
            "passe au build"
        )

    @pytest.mark.parametrize(
        "etiquette,argument",
        [
            ("org.opencontainers.image.revision", "CODE_SHA"),
            ("org.opencontainers.image.created", "CODE_CONSTRUITE_LE"),
            ("rag-agent-chat.code.arbre", "CODE_ARBRE"),
        ],
    )
    def test_le_dockerfile_grave_aussi_l_identite_en_etiquette(
        self, etiquette: str, argument: str
    ) -> None:
        """LE SECOND CHEMIN, ET CE N'EST PAS UNE REDONDANCE.

        `env_file:` charge le `.env` au démarrage, et Docker laisse l'exécution
        l'emporter sur l'`ENV` de l'image : une variable posée dans le `.env`
        ferait publier à `/health` une identité que le build n'a pas gravée. Le
        `LABEL`, lui, est figé à la construction et l'exécution ne peut pas le
        toucher. Croiser les deux nomme exactement ce cas, et c'est ce que fait
        la procédure de retour arrière.
        """
        assert re.search(
            rf"^LABEL {re.escape(etiquette)}=\$\{{{argument}\}}$", _dockerfile(), re.M
        ), (
            f"`LABEL {etiquette}=${{{argument}}}` est absent de Dockerfile.agent : "
            "l'identité ne vivrait plus que dans un `ENV` que l'exécution peut "
            "contredire, et rien ne permettrait de trancher"
        )

    def test_la_cible_qui_construit_releve_le_sha_et_aussi_la_proprete(self) -> None:
        """UN SHA SEUL NE SUFFIT PAS, et c'est le deuxième piège du lot.

        Un sha relevé dans un arbre qui porte des modifications non commitées
        NOMME UN COMMIT QUI NE CONTIENT PAS CE QUI TOURNE. La cible doit donc
        relever les deux — et relever la propreté SUR LA CHAÎNE, jamais sur le
        code de retour : `git status --porcelain` rend 0 qu'il ait de la sortie
        ou non, et un auditeur de ce chantier s'est fait annoncer « arbre
        propre » au-dessus d'un fichier muté.
        """
        recette = (_RACINE / "Makefile").read_text(encoding="utf-8")
        cible = re.search(r"^image:\n((?:\t.*\n)+)", recette, re.M)
        assert cible is not None, (
            "la cible `image` a disparu du Makefile : le seul geste qui "
            "construise une image identifiée n'existe plus, et le redéploiement "
            "produirait une image anonyme sans que personne ait rien décidé"
        )
        corps = cible.group(1)
        assert "rev-parse HEAD" in corps, "la cible `image` ne relève plus le sha du commit"
        assert "status --porcelain" in corps, (
            "la cible `image` ne relève plus la propreté de l'arbre : le sha "
            "qu'elle grave pourrait nommer un commit qui ne contient pas ce qui "
            "tourne, sans que rien ne le dise"
        )
        assert '-z "$$S"' in corps, (
            "la propreté n'est plus lue SUR LA CHAÎNE rendue par `git status` : "
            "tester son code de retour rend « propre » au-dessus de n'importe "
            "quelle modification, puisque `git status` rend 0 dans les deux cas"
        )


class TestCeGardeLitCeQueDockerLit:
    """LE GARDE DU GARDE, et il ferme un défaut MESURÉ sur ce dépôt.

    `docker compose` fusionne `docker-compose.override.yml` quand il existe, sans
    qu'aucun `-f` soit écrit. Un garde qui ne lit que le fichier de base reste
    VERT pendant qu'un override défait ce qu'il garde : l'audit du 15 septembre
    2026 l'a mesuré, 870 tests verts et une docstring qui promettait de rougir.

    Ces deux scènes ne mutent aucun fichier : elles passent les textes au
    lecteur, qui les accepte pour cette seule raison.
    """

    _BASE = (
        "services:\n"
        "  agent-api:\n"
        "    build:\n"
        "      context: .\n"
        "      dockerfile: Dockerfile.agent\n"
        "      args:\n"
        "        CODE_SHA: ${RAG_AGENT_CODE_SHA:-}\n"
        "        CODE_ARBRE: ${RAG_AGENT_CODE_ARBRE:-}\n"
        "        CODE_CONSTRUITE_LE: ${RAG_AGENT_CODE_CONSTRUITE_LE:-}\n"
    )

    def test_un_override_qui_efface_les_arguments_fait_rougir(self) -> None:
        """LE SENS QUI MORD.

        Quatre lignes d'override suffisent à faire construire une image anonyme,
        et le fichier de base continuerait d'avoir l'air juste.
        """
        override = (
            "services:\n"
            "  agent-api:\n"
            "    build:\n"
            "      context: .\n"
            "      dockerfile: Dockerfile.agent\n"
            "      args:\n"
            "        CODE_SHA: deadbeef\n"
        )
        # PREUVE D'ATTEINTE : la base seule porte bien l'interpolation, donc un
        # lecteur qui ignorerait l'override resterait vert sur cette scène.
        assert _args_du_compose(self._BASE)["CODE_SHA"] == "${RAG_AGENT_CODE_SHA:-}"

        args = _args_du_compose(self._BASE, override)
        assert args["CODE_SHA"] == "deadbeef", (
            "l'override n'a pas été fusionné : ce garde ne lit pas ce que docker "
            "lit, et il serait vert sur un déploiement anonyme"
        )

    def test_un_override_qui_ne_touche_pas_au_build_laisse_les_arguments(self) -> None:
        """LE TÉMOIN INERTE DE CETTE FAMILLE.

        Un lecteur qui perdrait les arguments à la moindre fusion rougirait
        partout, et son rouge ne dirait plus rien.
        """
        override = "services:\n  agent-api:\n    restart: always\n"
        args = _args_du_compose(self._BASE, override)
        assert args["CODE_SHA"] == "${RAG_AGENT_CODE_SHA:-}"

    def test_le_compose_reellement_livre_se_lit_sans_texte_injecte(self) -> None:
        """LE TÉMOIN INERTE DU FICHIER : sans lui, les deux scènes ci-dessus
        mesureraient un compose qui n'existe pas."""
        assert set(_args_du_compose()) >= set(_ARGS_ATTENDUS)

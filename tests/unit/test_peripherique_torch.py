"""LE PÉRIPHÉRIQUE DE TORCH : choisi, réglable, observable — et gardé aux DEUX bouts.

LA PANNE QUE CETTE BATTERIE FERME, et elle est une trouvaille du lot 10 : le
code de production construisait ses deux modèles SANS argument `device`.
`SentenceTransformer` et `CrossEncoder` portent tous deux `device: str | None =
None` (`mesuré` le 11 septembre 2026, `inspect.signature` sur
sentence-transformers 5.6.1), et `None` ne veut pas dire « CPU » : il veut dire
« décide pour moi ». Le service prenait donc ce que l'image lui donnait — et
tant que l'image ne portait qu'un `torch` CPU, *rien ne distinguait « le GPU
n'est pas utilisé » de « il n'y a pas de GPU »*.

POURQUOI CETTE BATTERIE EXISTE AVANT QUE L'IMAGE PRENNE LE GPU, et pas après :
une image CUDA sans ce réglage bascule le service sur la carte à la
reconstruction, en silence, AVANT qu'une campagne ait dit si ça vaut le coup. Le
GPU de ce poste n'est pas libre — Ollama y tient 4 904 Mio (`mesuré` le
11 septembre 2026 à 12:23 UTC, `nvidia-smi`) et porte 84 % du temps d'une
réponse — donc basculer sans mesurer, c'est optimiser 11 % du temps en risquant
les 67 % de la génération.

LES DEUX POSITIONS SONT GARDÉES, et c'est la leçon que ce chantier a payée NEUF
fois : un réglage dont une seule position est éprouvée est un garde à moitié
écrit. `cpu` est le défaut, donc la position que la production rencontre ; `cuda`
est celle que personne ne rencontrera avant qu'on l'allume, donc celle où un
défaut dormirait.

CE QUE CETTE BATTERIE NE PROUVE PAS, et il faut le dire ici pour que personne ne
le lise dedans : elle ne prouve RIEN sur la présence d'une carte. Elle prouve que
le réglage arrive aux constructeurs et que l'état est publié. Qu'un GPU soit
réellement atteint se mesure sur la carte, pas dans un test unitaire — c'est
`documentation/gpu_cuda.md` §5, et la mémoire prise sur la L4 pendant une
recherche.
"""

import logging
from typing import Any

import pytest
import torch
from fastapi.testclient import TestClient

from src.agent import retriever
from src.agent.settings import Settings
from src.api.schemas import TorchDeviceHealth

# ─── Outillage : deux doubles qui reproduisent la SIGNATURE réelle ────────────
#
# Ils portent `device` en mot-clé parce que c'est ainsi que le site d'appel le
# passe, et ils l'ENREGISTRENT. Un double qui accepterait `**kwargs` sans rien en
# faire laisserait passer un site d'appel qui ne passe rien : c'est la même
# classe de garde creux que cette batterie existe pour refuser.


class _Config:
    """La `config` d'un cross-encoder, réduite à ce que le garde du lot 6 y lit."""

    vocab_size = 250_002


class _FauxEmbedder:
    def __init__(self, device: str | None) -> None:
        # `device` est ce que le CONSTRUCTEUR a reçu, et non ce que torch aurait
        # posé : le double ne sait pas poser quoi que ce soit. La distinction est
        # assumée, et c'est la raison pour laquelle la mesure sur la carte reste
        # le seul juge de « le GPU est atteint ».
        self.device = device


class _FauxCrossEncoder:
    def __init__(self, device: str | None) -> None:
        self.device = device
        self.config = _Config()


def _brancher_les_deux(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """Branche les deux constructeurs et rend le journal de ce qu'ils ont reçu.

    Les deux `lru_cache` sont vidés AVANT et APRÈS : sans le premier, un
    chargement survenu dans un autre test rendrait la scène verte sans rien
    exécuter — le piège exact que REPAR-7 a trouvé au lot 6 ; sans le second, la
    scène laisserait un faux modèle derrière elle pour le test suivant.
    """
    recu: dict[str, list[Any]] = {"embedding": [], "rerank": []}

    def _faux_st(nom: str, device: str | None = None) -> _FauxEmbedder:
        recu["embedding"].append((nom, device))
        return _FauxEmbedder(device)

    def _faux_ce(nom: str, device: str | None = None) -> _FauxCrossEncoder:
        recu["rerank"].append((nom, device))
        return _FauxCrossEncoder(device)

    monkeypatch.setattr(retriever, "SentenceTransformer", _faux_st)
    monkeypatch.setattr(retriever, "CrossEncoder", _faux_ce)
    retriever._get_embedding_model.cache_clear()
    retriever._get_rerank_model.cache_clear()
    return recu


@pytest.fixture(autouse=True)
def _aucun_modele_ne_survit_a_un_test() -> Any:
    """Les deux singletons sont vidés au démontage, quoi qu'il arrive.

    Un faux modèle laissé dans un `lru_cache` serait servi aux tests suivants —
    y compris à ceux qui asserent qu'AUCUN modèle n'est chargé, qu'il rendrait
    faussement rouges, et à ceux de `test_garde_reranker.py`, qu'il rendrait
    faussement verts.
    """
    yield
    retriever._get_embedding_model.cache_clear()
    retriever._get_rerank_model.cache_clear()


# ─── (1) LE DÉFAUT, ET IL EST UNE DÉCISION ────────────────────────────────────


def test_le_defaut_du_reglage_est_cpu() -> None:
    """LE DÉFAUT PRÉSERVE LE SERVICE MESURÉ, image CUDA ou non.

    Lu sur une instance NEUVE de `Settings`, jamais sur le singleton `settings` :
    celui-ci a été construit à l'import, donc sous le `.env` du poste, et un
    test qui le lirait mesurerait la configuration de la machine plutôt que la
    décision écrite dans le code.

    Ce que ce test refuse : qu'on passe le défaut à `cuda` (ou à un `auto` qui
    reviendrait au même dès que l'image porte CUDA) sans le décider. Le faire
    changerait le comportement de la production par la seule reconstruction de
    l'image, ce que le §P1 du registre appelle trancher sans mesure.
    """
    assert Settings().torch_device == "cpu", (
        "le défaut de TORCH_DEVICE n'est plus `cpu`. Ce défaut n'est pas une "
        "commodité : c'est lui qui fait qu'une image reconstruite avec un build "
        "CUDA et un GPU réservé continue de calculer là où la campagne du "
        "11 septembre 2026 l'a mesurée. Le changer change le service"
    )


def test_le_reglage_porte_bien_l_alias_d_environnement() -> None:
    """Le réglage est réglable SANS reconstruire l'image — sinon ce n'en est pas un.

    C'est la moitié « réglable » de l'exigence, et elle n'est pas acquise : un
    `Field` sans alias se règle par `torch_device` et non par `TORCH_DEVICE`,
    donc pas par le `.env` que `docker-compose.yml` passe au conteneur.
    """
    # `mypy` exclut `tests/` (`pyproject.toml`), donc l'alias passé au
    # constructeur ne demande aucune annotation de complaisance ici.
    assert Settings(TORCH_DEVICE="cuda:3").torch_device == "cuda:3", (
        "`TORCH_DEVICE` ne règle plus le périphérique : l'alias a disparu, et "
        "le réglage ne se change plus que par une reconstruction d'image"
    )


# ─── (2) LES DEUX POSITIONS ATTEIGNENT LES DEUX CONSTRUCTEURS ────────────────


@pytest.mark.parametrize("position", ["cpu", "cuda"], ids=["cpu", "cuda"])
def test_les_deux_modeles_recoivent_le_peripherique_regle(
    monkeypatch: pytest.MonkeyPatch, position: str
) -> None:
    """LE GARDE CENTRAL — et il est paramétré parce qu'un seul cas ne suffit pas.

    `cpu` est la position de la production ; `cuda` est celle que personne ne
    rencontre tant qu'on ne l'allume pas, donc celle où un site d'appel oublié
    dormirait sans rien casser. Les deux modèles sont vérifiés séparément :
    l'embedder et le cross-encoder sont deux constructeurs distincts, et c'est
    exactement le genre d'endroit où l'un est câblé et l'autre non.

    MUTATIONS QUI DOIVENT LE FAIRE ROUGIR, et elles sont au tableau du rapport :
    retirer `device=` de l'un des deux constructeurs ; passer un littéral `"cpu"`
    au lieu du réglage ; câbler l'embedder sur `settings.torch_device` et le
    reranker sur autre chose.
    """
    recu = _brancher_les_deux(monkeypatch)
    monkeypatch.setattr(retriever.settings, "torch_device", position, raising=False)

    retriever._get_embedding_model()
    retriever._get_rerank_model()

    assert [device for _, device in recu["embedding"]] == [position], (
        f"le modèle d'embedding n'a pas reçu le périphérique réglé ({recu['embedding']} "
        f"sous TORCH_DEVICE={position!r}). Sans argument `device`, "
        "sentence-transformers DÉCIDE seul, et le réglage devient décoratif"
    )
    assert [device for _, device in recu["rerank"]] == [position], (
        f"le cross-encoder n'a pas reçu le périphérique réglé ({recu['rerank']} "
        f"sous TORCH_DEVICE={position!r}). C'est l'étage `rerank`, 622 ms sur "
        "6 846 au 11 septembre 2026 : le laisser décider seul est exactement ce "
        "que ce lot est venu fermer"
    )


@pytest.mark.parametrize("position", ["cpu", "cuda"], ids=["cpu", "cuda"])
def test_le_journal_nomme_le_peripherique_aux_deux_chargements(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, position: str
) -> None:
    """L'OBSERVABILITÉ AU JOURNAL, qui est le seul témoin d'un démarrage passé.

    `/health` dit l'état MAINTENANT ; le journal dit sur quoi les modèles ont été
    posés AU CHARGEMENT, ce qu'aucune lecture ultérieure ne retrouve si le
    processus a été redémarré depuis. Les deux lignes existent pour cette
    raison, et le prompt du lot les demande explicitement comme preuve que le
    GPU est atteint.
    """
    recu = _brancher_les_deux(monkeypatch)
    monkeypatch.setattr(retriever.settings, "torch_device", position, raising=False)

    with caplog.at_level(logging.INFO, logger=retriever.logger.name):
        retriever._get_embedding_model()
        retriever._get_rerank_model()

    assert recu["embedding"] and recu["rerank"], (
        "aucun modèle n'a été construit : la scène n'atteint pas le chemin "
        "qu'elle prétend éprouver, et son journal ne dirait rien"
    )
    messages = [enregistrement.getMessage() for enregistrement in caplog.records]
    demandes = [m for m in messages if "périphérique demandé" in m]
    poses = [m for m in messages if "chargé sur le périphérique" in m]
    assert len(demandes) == 2, (
        f"les deux chargements ne disent pas le périphérique DEMANDÉ : {messages}"
    )
    assert len(poses) == 2, (
        f"les deux chargements ne disent pas le périphérique POSÉ : {messages}. "
        "Cette seconde ligne n'est pas un doublon de la première : elles "
        "diffèrent précisément quand le build ne sait pas servir ce qu'on demande"
    )
    for message in demandes:
        assert position in message, (
            f"la ligne de chargement ne nomme pas le périphérique réglé : {message!r}"
        )


# ─── (3) L'ÉTAT PUBLIÉ DISTINGUE « PRÉSENT » DE « ATTEINT » ──────────────────


def test_l_etat_ne_charge_aucun_modele_et_le_dit_en_null() -> None:
    """LA PROPRIÉTÉ QUI REND LA SONDE UTILISABLE PAR UN HEALTHCHECK.

    `/health` est appelé toutes les 20 s (`docker-compose.yml`). Une sonde qui
    lirait le périphérique en CONSTRUISANT le modèle ferait payer au premier
    healthcheck le téléchargement des poids — et au démarrage à froid, c'est le
    healthcheck qui décide si `frontend` lève.

    `null` n'est donc pas « je ne sais pas » : c'est « personne n'a encore eu
    besoin de ce modèle ». Différent de `"cpu"`, et c'est la distinction qui
    fait qu'on ne lit pas un service au repos comme un service sur CPU.
    """
    retriever._get_embedding_model.cache_clear()
    retriever._get_rerank_model.cache_clear()

    etat = retriever.etat_du_peripherique()

    assert etat.embedding is None and etat.rerank is None, (
        f"l'état publie un périphérique ({etat.embedding}, {etat.rerank}) alors "
        "qu'aucun modèle n'est chargé : la sonde a chargé un modèle pour "
        "répondre, ce qui la rend impropre à un healthcheck de 20 s"
    )
    assert retriever._get_embedding_model.cache_info().currsize == 0, (
        "la sonde a peuplé le singleton de l'embedder"
    )
    assert retriever._get_rerank_model.cache_info().currsize == 0, (
        "la sonde a peuplé le singleton du reranker"
    )


@pytest.mark.parametrize("position", ["cpu", "cuda"], ids=["cpu", "cuda"])
def test_l_etat_publie_le_peripherique_des_modeles_charges(
    monkeypatch: pytest.MonkeyPatch, position: str
) -> None:
    """ET QUAND ILS SONT CHARGÉS, IL PUBLIE CE QU'ILS PORTENT.

    C'est le champ qui dit que le GPU SERT, par opposition à `cuda_available`
    qui dit seulement qu'il est là. `cuda_available: true` avec
    `embedding: "cpu"` est un état parfaitement possible — c'est même le défaut
    de ce service — et c'est précisément ce qu'on ne pouvait pas voir avant.
    """
    _brancher_les_deux(monkeypatch)
    monkeypatch.setattr(retriever.settings, "torch_device", position, raising=False)
    retriever._get_embedding_model()
    retriever._get_rerank_model()

    etat = retriever.etat_du_peripherique()

    assert etat.requested == position, f"`requested` ne rend pas le réglage : {etat.requested!r}"
    assert etat.embedding == position, (
        f"l'état publie `embedding={etat.embedding!r}` pour un modèle posé sur "
        f"{position!r} : il ne lit pas le modèle, il répète le réglage — et il "
        "ne saurait donc pas dire que le GPU est présent mais jamais atteint"
    )
    assert etat.rerank == position, (
        f"l'état publie `rerank={etat.rerank!r}` pour un modèle posé sur {position!r}"
    )


def test_l_etat_lit_torch_et_non_une_valeur_recopiee() -> None:
    """LES TROIS FAITS DU BUILD VIENNENT DE TORCH, PAS D'UN LITTÉRAL.

    Un état qui affirmerait `cuda_build` depuis le réglage serait rassurant et
    faux : c'est exactement la panne qu'on répare, un service qui déclare ce
    qu'il croit au lieu de ce qu'il est. Les trois champs sont donc confrontés à
    `torch` lui-même, dans l'environnement qui exécute ce test.

    Ce test est vrai dans les DEUX environnements du chantier — le `.venv` CPU du
    §2.2 et l'image CUDA — parce qu'il n'écrit aucune valeur attendue : il
    compare deux lectures de la même source. Un test qui aurait écrit
    `cuda_build is None` serait rouge dans l'image, et ce lot l'aurait arraché.
    """
    etat = retriever.etat_du_peripherique()

    assert etat.torch_version == torch.__version__, (
        f"`torch_version` ({etat.torch_version!r}) ne vient pas de torch "
        f"({torch.__version__!r})"
    )
    assert etat.cuda_build == torch.version.cuda, (
        f"`cuda_build` ({etat.cuda_build!r}) ne vient pas de torch "
        f"({torch.version.cuda!r}) : c'est le champ qui dit si l'IMAGE porte un "
        "build CUDA, et le recopier d'ailleurs le rendrait faux à la première "
        "reconstruction"
    )
    assert etat.cuda_available == torch.cuda.is_available(), (
        "`cuda_available` ne vient pas de torch : c'est le champ qui tombe à "
        "faux quand la réservation GPU manque au compose, et lui seul distingue "
        "« l'image sait faire du CUDA » de « la carte est visible d'ici »"
    )


def test_le_suffixe_du_build_et_la_version_cuda_disent_la_meme_chose() -> None:
    """LES DEUX FAITS DU BUILD SONT COHÉRENTS — et ce n'est pas une tautologie.

    `torch_version` porte le suffixe (`+cpu`, `+cu130`) et `cuda_build` porte la
    version CUDA compilée. Ils viennent de deux attributs distincts de torch, et
    un jour où ils se contrediraient — un `+cu130` avec `cuda_build: null` —
    l'image serait montée de travers : deux `torch` installés l'un sur l'autre,
    ce que le protocole du §2.2 produit exactement si on inverse ses deux `pip
    install`.

    Le test tient dans les deux environnements sans rien écrire en dur.
    """
    etat = retriever.etat_du_peripherique()
    porte_le_suffixe_cpu = etat.torch_version.endswith("+cpu")

    assert porte_le_suffixe_cpu == (etat.cuda_build is None), (
        f"`torch_version={etat.torch_version!r}` et `cuda_build={etat.cuda_build!r}` "
        "se contredisent : l'un dit un build CPU et l'autre un build CUDA. "
        "L'environnement porte probablement deux installations de torch "
        "superposées"
    )


# ─── (4) LE CÂBLAGE — /health publie réellement le champ ─────────────────────


def test_health_publie_le_peripherique(monkeypatch: pytest.MonkeyPatch) -> None:
    """LA MOITIÉ QUI MANQUE À TOUS LES GARDES CREUX DE CE CHANTIER.

    Les tests ci-dessus éprouvent une fonction ; celui-ci prouve qu'elle est
    réellement APPELÉE par la route, et que son résultat arrive jusqu'au corps
    de la réponse. Sans lui, l'état pourrait être parfait et jamais publié —
    « le code est juste, le garde manque », trouvé neuf fois ici.

    La sonde de concordance du modèle d'embedding est neutralisée : elle
    ouvrirait une connexion ChromaDB, que `tests/unit/conftest.py` interdit.
    """
    from src.api import main

    monkeypatch.setattr(main.settings, "api_key", "")
    # Les quatre sondes sont branchées, et PAS seulement la concordance : sans
    # cela, `nebula_ping` ouvre une vraie connexion NebulaGraph depuis un test
    # unitaire — mesuré à l'écriture de ce test, qui rendait un
    # `PytestUnraisableExceptionWarning` sur le `__del__` d'un `SessionPool`.
    # `tests/unit/conftest.py` ferme cette porte pour ChromaDB seulement ; celle
    # de Nebula se ferme ici, au site qui l'ouvrait.
    monkeypatch.setattr(main, "chroma_ping", lambda: True)
    monkeypatch.setattr(main, "nebula_ping", lambda: True)
    monkeypatch.setattr(main, "lexical_ready", lambda: True)
    monkeypatch.setattr(
        main, "etat_modele_embedding", lambda: main._embedding_inconnu(), raising=True
    )
    monkeypatch.setattr(retriever.settings, "torch_device", "cuda:7", raising=False)

    corps = TestClient(main.app).get("/health").json()

    assert "torch_device" in corps, (
        f"/health ne publie pas `torch_device` : {sorted(corps)}. L'état est "
        "calculé et jeté, et l'exploitant n'a aucun moyen de savoir sur quoi ce "
        "service calcule"
    )
    publie = corps["torch_device"]
    assert publie["requested"] == "cuda:7", (
        f"/health ne publie pas le réglage en vigueur : {publie}. Le champ vient "
        "d'ailleurs que de `etat_du_peripherique`, ou d'une valeur figée"
    )
    for champ in ("torch_version", "cuda_build", "cuda_available", "embedding", "rerank"):
        assert champ in publie, f"`{champ}` manque au champ publié : {publie}"


def test_le_repli_de_la_sonde_n_invente_pas_un_gpu() -> None:
    """LE SENS DU REPLI, ET IL EST ASYMÉTRIQUE EXPRÈS.

    Quand la sonde n'est pas revenue, `_peripherique_inconnu` publie le pire cas
    — pas de build CUDA, pas de carte — en gardant le seul fait qu'on puisse
    encore affirmer : le réglage. L'inverse ferait lire « GPU en service » à un
    exploitant dont la sonde vient de pendre, et c'est la lecture qu'on ne veut
    jamais provoquer : « je n'ai pas pu lire » et « pas de GPU » se soignent par
    le même geste — ouvrir le mode d'emploi et vérifier les trois conditions.
    """
    from src.api import main

    repli = main._peripherique_inconnu()

    assert isinstance(repli, TorchDeviceHealth)
    assert repli.requested == main.settings.torch_device, (
        "le repli n'affirme même plus le réglage, qui est pourtant le seul fait "
        "qui ne dépende pas de la sonde"
    )
    assert repli.cuda_build is None and repli.cuda_available is False, (
        f"le repli annonce un GPU qu'aucune sonde n'a vu : {repli}"
    )
    assert repli.embedding is None and repli.rerank is None, (
        f"le repli annonce un modèle posé quelque part : {repli}"
    )


# ─── (5) LE TÉMOIN INERTE ─────────────────────────────────────────────────────


@pytest.mark.parametrize("position", ["cpu", "cuda"], ids=["cpu", "cuda"])
def test_temoin_inerte_le_peripherique_ne_touche_ni_aux_noms_ni_au_verdict(
    monkeypatch: pytest.MonkeyPatch, position: str
) -> None:
    """LE TÉMOIN. Le périphérique ne change NI le modèle chargé NI le garde du lot 6.

    Ce test doit rester VERT sous toute mutation du périphérique — retirer
    `device=`, l'inverser, le figer — et ne rougir que si le câblage des NOMS ou
    le garde de langue du reranker est cassé. C'est ce qui distingue, au tableau
    des mutations, « le périphérique est mal câblé » de « le module est cassé » :
    une mutation du périphérique qui rougirait ICI n'a pas éprouvé le
    périphérique, elle a cassé autre chose.

    Il est paramétré sur les deux positions : un témoin qui ne serait inerte que
    sur `cpu` ne dirait rien des mutations rencontrées sur `cuda`.
    """
    recu = _brancher_les_deux(monkeypatch)
    monkeypatch.setattr(retriever.settings, "torch_device", position, raising=False)

    retriever._get_embedding_model()
    retriever._get_rerank_model()

    assert [nom for nom, _ in recu["embedding"]] == [
        retriever.settings.embedding_model_name
    ], f"le modèle d'embedding chargé n'est pas celui du réglage : {recu['embedding']}"
    assert [nom for nom, _ in recu["rerank"]] == [retriever.settings.rerank_model], (
        f"le reranker chargé n'est pas celui du réglage : {recu['rerank']}"
    )
    # Le garde de langue du lot 6 lit le vocabulaire du modèle CHARGÉ. Le double
    # en porte un qui est celui du modèle en service (250 002), donc le verdict
    # doit rester silencieux — quel que soit le périphérique.
    assert (
        retriever.verdict_langue_du_reranker(retriever.settings.rerank_model, _Config.vocab_size)
        is None
    ), "le garde de langue du reranker parle sur le réglage en service"

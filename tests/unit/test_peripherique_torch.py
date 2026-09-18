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

import contextlib
import logging
import threading
import time
from typing import Any

import pytest
import torch
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.agent import retriever
from src.agent.settings import Settings
from src.api.schemas import ChunkResult, EmbeddingModelHealth, TorchDeviceHealth

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


def test_le_defaut_du_reglage_est_celui_que_la_campagne_a_tranche() -> None:
    """LE DÉFAUT EST `cuda`, ET IL EST ADOSSÉ À UNE MESURE.

    Lu sur une instance NEUVE de `Settings`, jamais sur le singleton `settings` :
    celui-ci a été construit à l'import, donc sous le `.env` du poste, et un
    test qui le lirait mesurerait la configuration de la machine plutôt que la
    décision écrite dans le code.

    CE QUE CE TEST A GARDÉ D'ABORD, ET POURQUOI IL A CHANGÉ DE SENS. Il exigeait
    `cpu`, le matin du 11 septembre 2026 : tant que la campagne n'avait pas
    tranché, la seule reconstruction de l'image n'avait pas à basculer la
    production sur une carte partagée avec Ollama. La campagne du même jour a
    tranché — `rerank_ms` p50 498 → 58, `total_ms` p50 7 298 → 6 481, et la
    contention sur la génération chiffrée à **+40 ms** —, et le propriétaire a
    décidé. **Le garde n'a pas été relâché : il a changé de valeur gardée**, et
    la valeur qu'il garde porte désormais la mesure qui la justifie.

    Ce que ce test refuse toujours : qu'on change ce défaut sans décision. Le
    motif complet, avec ses chiffres, est au site du réglage.
    """
    assert Settings().torch_device == "cuda", (
        "le défaut de TORCH_DEVICE n'est plus `cuda`. Ce défaut n'est pas une "
        "commodité : il est le résultat de la campagne du 11 septembre 2026 "
        "(−817 ms sur `total_ms` p50, contention mesurée à +40 ms sur la "
        "génération). Le changer change le service, et demande la même chose "
        "qu'il a demandé la première fois : une mesure, pas une intuition"
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
    for champ in ("torch_version", "cuda_build", "cuda_available", "embedding", "rerank"):
        assert champ in publie, f"`{champ}` manque au champ publié : {publie}"

    # L'ASSERTION QUI DISCRIMINE, ET LA PREMIÈRE ÉCRITURE DE CE TEST NE L'AVAIT
    # PAS. Elle se contentait de `requested == "cuda:7"` — or
    # `_peripherique_inconnu()` publie EXACTEMENT le même `requested`, puisqu'il
    # le tient du même réglage. `mesuré` le 11 septembre 2026 : la mutation qui
    # remplace la sonde par son repli dans la route laissait **15 tests verts**.
    # Le garde du câblage ne gardait rien, et c'est la famille de défaut que ce
    # chantier a trouvée neuf fois — un garde vert sous une scène qu'il ne
    # rencontre jamais, retourné cette fois contre le garde lui-même.
    #
    # `torch_version` est le champ qui sépare les deux : la sonde le lit dans
    # torch, le repli le laisse vide faute de pouvoir l'affirmer.
    assert publie["torch_version"] == torch.__version__, (
        f"/health publie `torch_version={publie['torch_version']!r}` là où torch "
        f"dit {torch.__version__!r} : la route ne sert pas la sonde, elle sert "
        "son repli — ou une valeur figée. Le champ serait publié en permanence "
        "comme s'il n'y avait ni build CUDA ni carte"
    )
    assert publie["requested"] == "cuda:7", (
        f"/health ne publie pas le réglage en vigueur : {publie}"
    )


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


# ─── (6) LE STATUT — un périphérique hors d'atteinte doit DÉGRADER ───────────
#
# LA PANNE QUE CETTE SECTION FERME, et elle a été mesurée en grandeur réelle par
# l'audit du 14 septembre 2026 (`documentation/audits/2026-09-14-audit-lot-11.md`
# §1) : sur un service dont CHAQUE recherche rend **500**, `/health` rendait
# **200 `status: ok`**, et le healthcheck `curl -sf` du compose restait vert pour
# toujours — il ne lit que le code HTTP, jamais `status`.
#
# Le mode de panne est NÉ AVEC le lot 11 : `device=None` laissait
# sentence-transformers choisir un périphérique qui existe, et le chargement ne
# pouvait pas lever pour cette raison. `device=settings.torch_device` passe la
# chaîne telle quelle à torch, sans validation — c'est écrit et assumé dans
# `settings.py` (« ce qui remplace la validation est l'OBSERVABILITÉ »). Le lot a
# donc produit l'observabilité et n'a pas branché le statut dessus.
#
# CE QUE CETTE SECTION PEUT ÉPROUVER, ET CE QU'ELLE NE PEUT PAS. La route de
# santé NE CHARGE RIEN, délibérément — un `/health` qui construit deux modèles
# n'est plus une sonde. `status` ne peut donc pas savoir « le chargement va
# lever » avant qu'il ait levé. Ce qui EST connaissable sans rien charger, c'est
# que le périphérique demandé n'existe pas d'ici : torch refuse la chaîne, ou
# torch ne voit aucune carte, ou l'ordinal dépasse le nombre de cartes. Les trois
# scénarios de levée mesurés par l'audit (B, C, D) sont exactement ceux-là.
#
# LES DEUX DIRECTIONS SONT GARDÉES, et c'est la moitié qu'on oublie : un statut
# qui dégraderait toujours aurait remplacé un mensonge par un autre.


def _ollama_vert() -> Any:
    """La sonde Ollama, branchée au vert — et elle est `async` au site réel."""

    async def _sonde() -> bool:
        return True

    return _sonde()


def _corps_de_health(monkeypatch: pytest.MonkeyPatch, peripherique: str) -> dict[str, Any]:
    """Le corps de `/health` avec les QUATRE sondes au vert et le réglage donné.

    LES QUATRE, ET C'EST LE PIÈGE QUE CETTE FONCTION EXISTE POUR FERMER. L'audit
    a écrit sa première sonde sans brancher le moteur : `services["llm"]` était
    faux, le statut dégradait POUR CETTE RAISON-LÀ, et la sonde était verte en
    mesurant une voisine. *Le `rc` juste, la raison fausse — huitième fois dans
    ce chantier.* Tout ce qui peut dégrader pour une autre raison est donc
    neutralisé ici, et le contrôle positif ci-dessous le vérifie AVANT que quoi
    que ce soit d'autre ne soit mesuré.
    """
    from src.api import main

    monkeypatch.setattr(main.settings, "api_key", "")
    monkeypatch.setattr(main, "chroma_ping", lambda: True)
    monkeypatch.setattr(main, "nebula_ping", lambda: True)
    monkeypatch.setattr(main, "lexical_ready", lambda: True)
    monkeypatch.setattr(main, "_sonder_moteur", _ollama_vert)
    # `unknown` ne dégrade pas — c'est la décision écrite au site pour la sonde
    # de concordance. Le témoin ci-dessous éprouve la position qui dégrade.
    monkeypatch.setattr(main, "etat_modele_embedding", lambda: main._embedding_inconnu())
    monkeypatch.setattr(retriever.settings, "torch_device", peripherique, raising=False)
    reponse = TestClient(main.app).get("/health")
    assert reponse.status_code == 200, (
        f"/health ne rend plus 200 mais {reponse.status_code} : le motif écrit au "
        "site est qu'un code d'erreur passerait le conteneur `unhealthy` et "
        "empêcherait le frontend de démarrer à froid"
    )
    return dict(reponse.json())


def test_controle_positif_le_service_sain_reste_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """LE CONTRÔLE POSITIF, et il passe AVANT tout le reste.

    Il asserte que, sur cette scène, `status` vaut `ok` et que les quatre sondes
    sont vertes. Sans lui, un `degraded` mesuré plus bas ne distinguerait pas
    « le périphérique dégrade » de « une voisine dégrade » — la confusion exacte
    qui a rendu la première sonde de l'audit verte pour une mauvaise raison.

    `cpu` est un périphérique que torch sert TOUJOURS, build CUDA ou non
    (scénario **E** de l'audit : charge, `rc=0`). Cette scène est donc celle d'un
    service parfaitement sain.
    """
    corps = _corps_de_health(monkeypatch, "cpu")

    assert corps["services"] == {
        "chromadb": True,
        "nebulagraph": True,
        "index_lexical": True,
        "llm": True,
    }, f"une sonde voisine n'est pas verte, la scène ne mesure pas ce qu'on croit : {corps}"
    assert corps["services_unknown"] == [], (
        f"une sonde n'est pas revenue, la scène est instable : {corps}"
    )
    assert corps["status"] == "ok", (
        f"le contrôle positif est ROUGE : `status` vaut {corps['status']!r} sur un "
        f"service sain. Le garde du périphérique a remplacé un mensonge par un "
        f"autre — corps : {corps}"
    )


def test_preuve_d_atteinte_le_peripherique_demande_leve_vraiment_ici(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LA PREUVE D'ATTEINTE : la scène mesurée plus bas est RÉELLE dans ce venv.

    Un test qui asserterait `degraded` sans celui-ci ne dirait pas si la scène
    qu'il décrit est atteignable. Ici elle l'est, et c'est mesurable sans rien
    charger : `torch.cuda.is_available()` vaut faux dans l'environnement du §2.2
    (torch CPU), donc `SentenceTransformer(nom, device="cuda")` LÈVE — scénario
    **B** de l'audit, `RuntimeError: Found no NVIDIA driver on your system`.

    La levée est éprouvée sur `torch` lui-même et non sur sentence-transformers :
    c'est torch qui lève, au premier `.to(device)`, et le prouver ici n'exige
    aucun téléchargement de modèle. Le double de la section (1) ne saurait pas
    lever — c'est un double.
    """
    assert not torch.cuda.is_available(), (
        "ce venv VOIT une carte : la scène du scénario B n'est pas atteignable ici, "
        "et le test ci-dessous serait vert sans rien avoir éprouvé. Monter "
        "l'environnement par le §2.2 du mandat (torch CPU)"
    )
    with pytest.raises(Exception) as leve:
        torch.zeros(1).to("cuda")
    assert "cuda" in str(leve.value).lower() or "driver" in str(leve.value).lower(), (
        f"la levée obtenue ne parle pas du périphérique : {leve.value}"
    )
    # Et la chaîne refusée par torch — scénario **D**, `banane` — lève au
    # PARSING, donc encore plus tôt, et sans aucune carte en jeu.
    with pytest.raises(RuntimeError):
        torch.device("banane")


@pytest.mark.parametrize(
    ("reglage", "motif"),
    [
        ("cuda", "carte absente"),
        ("cuda:7", "carte absente"),
        ("banane", "chaîne que torch ne connaît pas"),
    ],
)
def test_un_peripherique_hors_d_atteinte_degrade_le_statut(
    monkeypatch: pytest.MonkeyPatch, reglage: str, motif: str
) -> None:
    """LA PROPRIÉTÉ VISÉE — et c'est elle qui était ABSENTE avant ce lot.

    Sur ces trois réglages, le chargement du premier modèle LÈVE (scénarios B, C
    et D de l'audit) : toute recherche rend 500, et `embedding`/`rerank` restent
    `null` pour toujours puisque le `lru_cache` ne se peuple jamais. Un statut
    `ok` y décrirait un service qui ne sert rien — c'est mot pour mot le motif
    écrit trois lignes plus haut au site, pour la concordance d'embedding.

    `cuda:7` est ici indiscernable de `cuda` faute de carte ; sur une machine qui
    en porte une, c'est l'ordinal qui le condamne. Les deux chemins sont écrits,
    un seul est atteignable dans ce venv, et c'est dit plutôt que tu.
    """
    corps = _corps_de_health(monkeypatch, reglage)

    assert corps["status"] == "degraded", (
        f"/health rend `status={corps['status']!r}` alors que le périphérique "
        f"demandé ({reglage!r}) est hors d'atteinte — {motif}. Toute recherche "
        f"lèvera, et le healthcheck `curl -sf` du compose restera vert pour "
        f"toujours puisqu'il ne lit que le code HTTP. Corps publié : {corps}"
    )
    assert corps["torch_device"]["hors_d_atteinte"], (
        "le statut dégrade mais le corps ne dit pas POURQUOI : un exploitant qui "
        f"lit `degraded` doit trouver le motif dans la réponse — {corps['torch_device']}"
    )


def test_le_corps_distingue_le_repos_de_la_panne_totale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L'INDISCERNABILITÉ, qui est la moitié qui rendait la panne invisible.

    `mesuré` par l'audit : `/health` publiait EXACTEMENT le même corps au repos et
    après trois chargements qui avaient levé — `embedding` et `rerank` valant
    `null` dans les deux cas, le cache ne se peuplant jamais. Un exploitant ne
    pouvait donc pas distinguer « pas encore chargé » de « toute recherche échoue
    depuis le démarrage », qui est le cas coûteux.

    Ce test compare les deux corps et exige qu'ils diffèrent. Il ne prescrit pas
    COMMENT : il exige seulement que la différence existe et qu'elle soit lisible.
    """
    sain = _corps_de_health(monkeypatch, "cpu")
    casse = _corps_de_health(monkeypatch, "cuda")

    assert sain["torch_device"] != casse["torch_device"], (
        "le corps publié est IDENTIQUE pour un service au repos et pour un "
        "service dont chaque recherche lève : "
        f"{sain['torch_device']}. L'exploitant ne peut pas les distinguer"
    )
    assert (sain["status"], casse["status"]) == ("ok", "degraded"), (
        f"les deux positions ne sont pas gardées : sain={sain['status']!r}, "
        f"cassé={casse['status']!r}"
    )


def test_temoin_la_concordance_refusee_degrade_toujours(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LE TÉMOIN QUI DONNE SON SENS AUX TROIS PRÉCÉDENTS.

    La dégradation par une sonde EXISTE dans cette route et fonctionnait déjà —
    c'est le geste du lot 3, et le lot 11 ne s'en est pas servi. Sans ce témoin,
    un `degraded` mesuré plus haut ne distinguerait pas « la propriété a été
    ajoutée » de « la route dégrade tout, maintenant ».

    Il est joué sur un périphérique SAIN (`cpu`) : seule la concordance dégrade.
    """
    from src.api import main

    monkeypatch.setattr(main.settings, "api_key", "")
    monkeypatch.setattr(main, "chroma_ping", lambda: True)
    monkeypatch.setattr(main, "nebula_ping", lambda: True)
    monkeypatch.setattr(main, "lexical_ready", lambda: True)
    monkeypatch.setattr(main, "_sonder_moteur", _ollama_vert)
    monkeypatch.setattr(retriever.settings, "torch_device", "cpu", raising=False)
    monkeypatch.setattr(
        main,
        "etat_modele_embedding",
        lambda: EmbeddingModelHealth(
            status="mismatch", expected="attendu", collection="autre-chose"
        ),
    )

    corps = TestClient(main.app).get("/health").json()

    assert corps["status"] == "degraded", (
        f"la dégradation par concordance refusée ne mord plus : {corps}"
    )


def test_une_sonde_qui_n_est_pas_revenue_ne_degrade_pas_le_statut(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """« JE N'AI PAS PU LIRE » N'EST PAS « C'EST CASSÉ », et le repli en est un.

    `_peripherique_inconnu()` publie le PIRE CAS — pas de build CUDA, pas de
    carte — parce que « je n'ai pas pu lire » et « pas de GPU » se soignent par le
    même geste. Mais ce pire cas porte `requested` tel quel, donc `cuda` par
    défaut : une lecture naïve du corps y verrait « cuda demandé, aucune carte »
    et dégraderait un service dont on ne sait RIEN.

    C'est la décision déjà écrite au site pour `unknown` de la concordance :
    *« publier degraded sur une sonde qui n'est pas revenue reviendrait à faire
    dire à l'agent “ça diverge” quand il n'en sait rien »*. Le verdict doit donc
    se lire sur le RÉSULTAT de la sonde, jamais sur le repli.
    """
    from src.api import main

    repli = main._peripherique_inconnu()
    assert repli.requested == main.settings.torch_device
    assert repli.cuda_available is False
    assert repli.hors_d_atteinte is None, (
        "le repli AFFIRME un périphérique hors d'atteinte alors qu'aucune sonde "
        f"n'a rendu : {repli}. Le statut dégraderait sur une ignorance"
    )

    monkeypatch.setattr(main.settings, "api_key", "")
    monkeypatch.setattr(main, "chroma_ping", lambda: True)
    monkeypatch.setattr(main, "nebula_ping", lambda: True)
    monkeypatch.setattr(main, "lexical_ready", lambda: True)
    monkeypatch.setattr(main, "_sonder_moteur", _ollama_vert)
    monkeypatch.setattr(main, "etat_modele_embedding", lambda: main._embedding_inconnu())
    monkeypatch.setattr(retriever.settings, "torch_device", "cuda", raising=False)

    def _sonde_muette() -> Any:
        raise TimeoutError("la sonde n'a pas rendu la main")

    monkeypatch.setattr(main, "etat_du_peripherique", _sonde_muette)

    corps = TestClient(main.app).get("/health").json()

    assert corps["torch_device"]["torch_version"] == "", (
        f"la scène n'est pas atteinte : la route sert la sonde, pas son repli — {corps}"
    )
    assert corps["status"] == "ok", (
        f"une sonde qui n'a pas rendu dégrade le service : {corps}. Le repli porte "
        "`requested=cuda` et `cuda_available=false` parce qu'il ne sait pas, pas "
        "parce qu'il a mesuré"
    )
    # NB-1 de l'audit du 14 septembre 2026, et c'est l'autre moitié de la même
    # décision : ne pas dégrader est juste, mais le corps doit DIRE qu'il ne sait
    # rien. Sans cette ligne, `ok` sur une sonde muette est indiscernable de `ok`
    # sur un service sain — et c'est exactement ce que le geste rendu au pipeline
    # imprime.
    assert "peripherique_torch" in corps["services_unknown"], (
        f"la sonde du périphérique n'est pas revenue et le corps ne le dit nulle "
        f"part : {corps['services_unknown']}. Un exploitant lit alors `ok` sur une "
        "ignorance, exactement comme sur un service sain — alors que les cinq "
        "autres sondes savent le dire, et que `_embedding_inconnu()` le dit par "
        "`status=unknown` à sept lignes d'écart"
    )


def test_temoin_un_peripherique_bien_sonde_ne_figure_pas_dans_les_inconnues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TÉMOIN de la scène précédente : une sonde qui REVIENT ne s'y déclare pas.

    Sans lui, `peripherique_torch in services_unknown` serait satisfait par un
    site qui l'y met toujours — un garde vert sur une propriété que le code ne
    tient pas. La scène est la même à une seule chose près : la sonde répond.
    """
    from src.api import main

    monkeypatch.setattr(main.settings, "api_key", "")
    monkeypatch.setattr(main, "chroma_ping", lambda: True)
    monkeypatch.setattr(main, "nebula_ping", lambda: True)
    monkeypatch.setattr(main, "lexical_ready", lambda: True)
    monkeypatch.setattr(main, "_sonder_moteur", _ollama_vert)
    monkeypatch.setattr(main, "etat_modele_embedding", lambda: main._embedding_inconnu())
    monkeypatch.setattr(main.settings, "torch_device", "cpu")
    monkeypatch.setattr(retriever.settings, "torch_device", "cpu", raising=False)

    corps = TestClient(main.app).get("/health").json()

    assert corps["torch_device"]["torch_version"] != "", (
        f"la scène n'est pas atteinte : la route sert le repli, pas la sonde — {corps}"
    )
    assert "peripherique_torch" not in corps["services_unknown"], (
        f"la sonde du périphérique a RÉPONDU et le corps la déclare inconnue : "
        f"{corps['services_unknown']}. `services_unknown` cesserait de vouloir dire "
        "quelque chose"
    )
    assert corps["status"] == "ok", f"le témoin ne décrit pas un service sain : {corps}"


def test_une_levee_au_chargement_degrade_le_statut(monkeypatch: pytest.MonkeyPatch) -> None:
    """LA MOITIÉ QUE LE CONTRÔLE STATIQUE NE PEUT PAS COUVRIR, et elle est VIVANTE.

    Le verdict statique ci-dessus répond à « le périphérique demandé existe-t-il
    d'ici ». Il ne répond pas à « le chargement va-t-il aboutir » — et il ne le
    peut pas : `/health` ne charge rien. Or `mesuré` le 14 septembre 2026 à
    09:08 UTC, `nvidia-smi --query-compute-apps` croisé avec
    `docker inspect -f '{{.State.Pid}}' rag-agent-api` : **vLLM tient déjà
    14 264 Mio** sur la L4, Ollama **4 584**, l'agent **1 294**, sur **23 034**.
    Il reste **2 892 Mio**. La panne qui vient n'est plus « la carte est absente »
    — `cuda_available` restera `true` et l'ordinal valide — c'est **la mémoire**,
    au chargement.

    D'OÙ LA SECONDE MOITIÉ, ET ELLE EST NOMMÉE PAR L'AUDIT LUI-MÊME : *« ou une
    levée mémorisée au dernier chargement »*. Une levée est un FAIT déjà produit ;
    la relire ne coûte rien et ne charge rien. Elle couvre toute cause — mémoire
    insuffisante, modèle absent du cache, droits refusés — au prix d'arriver
    APRÈS la première recherche, là où le contrôle statique arrive avant.

    Les deux sont donc complémentaires, et aucun ne rend l'autre inutile.
    """
    retriever.oublier_les_levees_au_chargement()

    def _leve(nom: str, **kwargs: Any) -> Any:
        raise RuntimeError("CUDA out of memory. Tried to allocate 1.20 GiB")

    monkeypatch.setattr(retriever, "SentenceTransformer", _leve)
    retriever._get_embedding_model.cache_clear()
    monkeypatch.setattr(retriever.settings, "torch_device", "cpu", raising=False)

    # PREUVE D'ATTEINTE : le chargement lève réellement, et le cache reste vide.
    with pytest.raises(RuntimeError, match="out of memory"):
        retriever._get_embedding_model()
    assert retriever._get_embedding_model.cache_info().currsize == 0, (
        "le modèle a été mis en cache malgré la levée : la scène n'est pas celle "
        "d'un service dont chaque recherche échoue"
    )

    corps = _corps_de_health(monkeypatch, "cpu")
    try:
        assert corps["status"] == "degraded", (
            "un chargement qui LÈVE laisse `/health` en "
            f"{corps['status']!r} : le périphérique demandé existe (`cpu`), donc le "
            "contrôle statique ne voit rien, et toute recherche rend pourtant 500. "
            f"Corps : {corps['torch_device']}"
        )
        assert "out of memory" in (corps["torch_device"]["hors_d_atteinte"] or ""), (
            "le corps ne rend pas la levée qui s'est produite : "
            f"{corps['torch_device']}"
        )
    finally:
        retriever.oublier_les_levees_au_chargement()
        retriever._get_embedding_model.cache_clear()


def test_un_chargement_reussi_efface_la_levee_memorisee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LA SECONDE DIRECTION — sans elle le garde ne se relâcherait JAMAIS.

    Un exploitant qui corrige la cause (il libère la carte, il rend les droits)
    doit voir le service redevenir `ok` sans redémarrage. Une levée mémorisée qui
    survivrait au chargement réussi suivant serait un `degraded` définitif — le
    mensonge symétrique de celui que ce lot ferme.
    """
    recu = _brancher_les_deux(monkeypatch)
    retriever.oublier_les_levees_au_chargement()
    retriever._memoriser_la_levee("embedding", RuntimeError("CUDA out of memory"))
    assert retriever.levees_au_chargement(), "la scène n'est pas montée"

    monkeypatch.setattr(retriever.settings, "torch_device", "cpu", raising=False)
    retriever._get_embedding_model()

    assert recu["embedding"], "le double n'a pas été appelé, rien n'a été rechargé"
    assert not retriever.levees_au_chargement(), (
        "la levée survit à un chargement RÉUSSI : le service resterait `degraded` "
        f"pour toujours — {retriever.levees_au_chargement()}"
    )


# ─── (7) LA BORNE DE CONCURRENCE, ET LE CLIQUET PUBLIÉ ───────────────────────
#
# POURQUOI CETTE SECTION EXISTE, ET ELLE DÉBLOQUE UNE AUTRE ÉQUIPE.
# `--gpu-memory-utilization` est une option de LANCEMENT de vLLM : elle ne se
# change pas à chaud, donc le chiffre de réservation doit être bon AVANT. Or cet
# agent ne pouvait pas en donner un honnête : **aucune borne de concurrence
# n'existait** — `uvicorn` lancé sans `--limit-concurrency`, aucun sémaphore,
# aucun `PYTORCH_CUDA_ALLOC_CONF` — et chaque requête reclasse `FETCH_K=50`
# passages. *Réserver pour quelqu'un d'illimité, ce n'est pas réserver.*
#
# ET L'EMPREINTE EST UN CLIQUET : l'allocateur de torch ne rend rien, donc après
# chaque rafale elle RESTE au sommet atteint. `mesuré` sur le service en
# production, sans qu'aucune charge ne soit ajoutée par ce lot : **1 294 Mio** à
# 09:08 UTC, **1 984 Mio** à 09:28 — même PID (503779), aucun redémarrage entre
# les deux, et 1 984 est exactement le palier « 16 concurrentes » du banc du
# pilote. Le cliquet est donc observé, pas supposé.


def test_la_borne_de_concurrence_est_un_reglage_et_non_une_constante() -> None:
    """Une borne enfouie dans le code ne se règle pas sur le poste qui en a besoin.

    Le voisin de carte dimensionne sa réservation sur CETTE valeur : elle doit
    être lisible, réglable sans reconstruire l'image, et publiée.
    """
    assert Settings().torch_max_concurrency == 4, (
        "le défaut de la borne a changé sans que ce test le dise — le chiffre de "
        "réservation rendu au voisin de carte en dépend"
    )
    assert Settings(TORCH_MAX_CONCURRENCY="7").torch_max_concurrency == 7, (
        "la borne ne se règle pas par l'environnement"
    )
    with pytest.raises(ValidationError):
        Settings(TORCH_MAX_CONCURRENCY="0")


def test_la_borne_laisse_passer_sous_son_plafond(monkeypatch: pytest.MonkeyPatch) -> None:
    """PREMIÈRE DIRECTION : sous la borne, rien ne change.

    Une borne qui sérialiserait tout serait une régression de latence déguisée en
    garde. Trois entrées simultanées sous une borne de quatre doivent être
    RÉELLEMENT simultanées.
    """
    monkeypatch.setattr(retriever.settings, "torch_max_concurrency", 4, raising=False)
    retriever.rearmer_la_borne_des_etages_torch()

    dedans = []
    barriere = threading.Barrier(3, timeout=5)

    def _entrer() -> None:
        with retriever.borne_des_etages_torch():
            dedans.append(1)
            barriere.wait()

    fils = [threading.Thread(target=_entrer) for _ in range(3)]
    for f in fils:
        f.start()
    for f in fils:
        f.join(timeout=5)

    assert len(dedans) == 3, (
        f"trois requêtes sous une borne de quatre ne sont pas entrées ensemble : "
        f"{len(dedans)}. La barrière aurait levé si elles s'étaient attendues"
    )


def test_la_borne_fait_attendre_au_dessus_de_son_plafond(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SECONDE DIRECTION, ET C'EST CELLE QUI PORTE LA PROPRIÉTÉ.

    Au-dessus de la borne, les requêtes s'attendent **au lieu de faire croître la
    carte**. C'est tout ce que ce garde existe pour obtenir : le cliquet ne monte
    que jusqu'au palier de la borne.

    PREUVE D'ATTEINTE INCLUSE : le test vérifie que le quatrième fil est
    RÉELLEMENT bloqué — il ne se contente pas de compter, il constate qu'il
    n'entre qu'une fois une place libérée.
    """
    # LE CHEMIN DU SERVICE EST LA CONSTRUCTION PARESSEUSE, PAS `rearmer`, et
    # c'est une correction : la première écriture de ce test appelait
    # `rearmer_la_borne_des_etages_torch()`, qui construit le sémaphore à part.
    # La mutation M9 — `_semaphore()` construisant un sémaphore illimité — le
    # laissait donc **VERT**, le chemin muté n'étant jamais emprunté. En service,
    # personne n'appelle `rearmer` : le sémaphore naît dans `_semaphore()`, à la
    # première requête. On remet donc le module à l'état où il l'y construira.
    monkeypatch.setattr(retriever.settings, "torch_max_concurrency", 3, raising=False)
    monkeypatch.setattr(retriever, "_borne", None, raising=False)
    monkeypatch.setattr(retriever, "_borne_taille", None, raising=False)

    entres: list[int] = []
    liberer = threading.Event()

    def _occuper(n: int) -> None:
        with retriever.borne_des_etages_torch():
            entres.append(n)
            liberer.wait(timeout=5)

    trois = [threading.Thread(target=_occuper, args=(i,)) for i in range(3)]
    for f in trois:
        f.start()
    for _ in range(200):
        if len(entres) == 3:
            break
        time.sleep(0.01)
    assert len(entres) == 3, f"les trois premières n'ont pas rempli la borne : {entres}"

    quatrieme = threading.Thread(target=_occuper, args=(99,))
    quatrieme.start()
    time.sleep(0.15)
    assert 99 not in entres, (
        "la quatrième requête est entrée alors que la borne de TROIS est pleine : "
        f"{entres}. Rien ne borne la concurrence des étages torch, et l'empreinte "
        "de la carte croît avec elle — le chiffre de réservation rendu au voisin "
        "ne vaut alors rien"
    )

    liberer.set()
    for f in [*trois, quatrieme]:
        f.join(timeout=5)
    assert 99 in entres, f"la quatrième n'est jamais entrée après libération : {entres}"


def test_les_deux_etages_torch_passent_par_la_borne(monkeypatch: pytest.MonkeyPatch) -> None:
    """LE CÂBLAGE, et sans lui la borne serait un objet que personne n'appelle.

    C'est la moitié qui manquait à tous les gardes creux de ce chantier. Les deux
    étages sont éprouvés SÉPARÉMENT et par leur VRAI chemin d'appel : borner
    l'encodage sans le reclassement laisserait passer celui qui traite
    `FETCH_K=50` passages par requête, donc celui dont l'empreinte croît.

    Les doubles n'observent pas un appel au sémaphore — ils observent que le
    permis est **réellement détenu** au moment où torch calcule. Un câblage qui
    prendrait puis rendrait le permis avant d'appeler serait vert à un traceur
    d'appels et faux en service.
    """
    monkeypatch.setattr(retriever.settings, "torch_device", "cpu", raising=False)
    monkeypatch.setattr(retriever.settings, "torch_max_concurrency", 1, raising=False)
    retriever.rearmer_la_borne_des_etages_torch()

    tenu: dict[str, bool] = {}

    def _permis_detenu() -> bool:
        """Vrai si l'unique permis est pris. Rendu immédiatement s'il ne l'était pas."""
        libre = retriever._semaphore().acquire(blocking=False)
        if libre:
            retriever._semaphore().release()
        return not libre

    class _Embedder:
        def __init__(self, nom: str = "", *, device: str | None = None) -> None:
            self.device = device

        def encode(self, question: str) -> Any:
            tenu["embedding"] = _permis_detenu()
            import numpy

            return numpy.zeros(3)

    class _Cross:
        def __init__(self, nom: str = "", *, device: str | None = None) -> None:
            self.device = device
            self.config = _Config()

        def predict(self, pairs: Any) -> Any:
            tenu["rerank"] = _permis_detenu()
            import numpy

            return numpy.zeros(len(pairs))

    monkeypatch.setattr(retriever, "SentenceTransformer", _Embedder)
    monkeypatch.setattr(retriever, "CrossEncoder", _Cross)
    monkeypatch.setattr(retriever, "verifier_modele_embedding", lambda: None)

    class _Collection:
        def query(self, **kwargs: Any) -> dict[str, Any]:
            return {"documents": [[]], "metadatas": [[]], "distances": [[]], "ids": [[]]}

    monkeypatch.setattr(retriever, "_get_chroma_collection", lambda: _Collection())
    retriever._get_embedding_model.cache_clear()
    retriever._get_rerank_model.cache_clear()

    try:
        # Étage 1 — l'encodage de la question, par son vrai chemin.
        retriever._dense_search("question", 5)
        # Étage 2 — le reclassement, celui qui traite les 50 passages.
        retriever.rerank(
            "question",
            [
                ChunkResult(
                    chunk_id=f"c{i}",
                    element_id=f"{i:010x}",
                    graph_node_id=f"n{i}",
                    document="texte",
                    filename="f.pdf",
                    page_no=1,
                    label="text",
                    distance=0.1,
                )
                for i in range(3)
            ],
        )
    finally:
        retriever._get_embedding_model.cache_clear()
        retriever._get_rerank_model.cache_clear()

    assert tenu.get("embedding") is True, (
        "l'ENCODAGE de la question ne tient pas le permis quand torch calcule : "
        f"{tenu}. La borne ne borne pas cet étage"
    )
    assert tenu.get("rerank") is True, (
        "le RECLASSEMENT ne tient pas le permis quand torch calcule : "
        f"{tenu}. C'est l'étage qui traite `FETCH_K=50` passages par requête, "
        "donc celui dont l'empreinte sur la carte croît avec la concurrence"
    )


def test_le_cliquet_est_publie_par_health(monkeypatch: pytest.MonkeyPatch) -> None:
    """LE VOISIN NE DOIT PAS AVOIR À CROIRE CE DÉPÔT SUR PAROLE.

    `/health` publie le plus haut niveau de mémoire GPU jamais RÉSERVÉ par ce
    processus, et la borne qui le plafonne. Les deux ensemble sont ce qui rend le
    chiffre de réservation vérifiable de l'extérieur.

    ET IL FAUT LIRE `pic_memoire_reservee_mio` DEPUIS LE PROCESSUS QUI SERT.
    `mesuré` le 14 septembre 2026 à 09:29 UTC : `docker exec rag-agent-api python
    -c "torch.cuda.max_memory_reserved()"` rend **0,0 Mio** pendant que
    `nvidia-smi` attribue **1 984 Mio** au même conteneur — parce que `docker
    exec` démarre un AUTRE processus, avec un contexte CUDA neuf. *C'est
    précisément pour cela que ce champ doit passer par la route.*
    """
    corps = _corps_de_health(monkeypatch, "cpu")
    publie = corps["torch_device"]

    assert "concurrence_max" in publie, (
        f"la borne n'est pas publiée : {publie}. Le voisin de carte ne peut pas "
        "vérifier le chiffre de réservation qu'on lui a rendu"
    )
    assert publie["concurrence_max"] == retriever.settings.torch_max_concurrency
    assert "pic_memoire_reservee_mio" in publie, (
        f"le cliquet n'est pas publié : {publie}"
    )


def test_le_cliquet_vaut_null_tant_que_rien_n_est_charge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ZÉRO NE VEUT PAS DIRE « CET AGENT NE PREND RIEN ».

    C'est exactement le reproche que la bloquante (1) de ce lot fait à `status`,
    et il serait absurde de le refaire ici. La route ne charge rien ; tant
    qu'aucun modèle n'est en mémoire, le cliquet vaut `null` — *« on ne sait pas
    encore »* — et non `0.0`, qui se lirait *« mesuré, et c'est zéro »*.

    Le danger est concret : un voisin qui dimensionne sa réservation pendant que
    cet agent est au repos verrait 1,3 Go de libre en trop, les prendrait, et
    ferait tomber l'agent plus tard — c'est le §4.50, rendu par le pilote.
    """
    retriever._get_embedding_model.cache_clear()
    retriever._get_rerank_model.cache_clear()
    # CETTE LIGNE EST CE QUI REND LE TEST DISCRIMINANT, et son absence l'a rendu
    # creux. Dans le venv du §2.2 — torch CPU — `torch.cuda.is_available()` est
    # FAUX, donc `_pic_memoire_reservee_mio` rendait `None` par sa seconde
    # condition quoi qu'il arrive : la mutation M10, qui retire le garde « aucun
    # modèle chargé », laissait ce test **VERT**. En feignant une carte, c'est
    # bien le garde visé qui décide.
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(
        torch.cuda, "max_memory_reserved", lambda *a, **k: 1_036 * 2**20, raising=False
    )

    corps = _corps_de_health(monkeypatch, "cpu")

    assert corps["torch_device"]["embedding"] is None, "la scène n'est pas celle du repos"
    assert corps["torch_device"]["pic_memoire_reservee_mio"] is None, (
        "le cliquet publie une valeur alors qu'aucun modèle n'est chargé : "
        f"{corps['torch_device']}. Un `0.0` ici se lit « cet agent ne prend rien », "
        "et c'est la lecture qui fait tomber l'agent plus tard"
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


# ─── (9) LE CHARGEMENT LUI-MÊME, QUI EST LE MOMENT OÙ LA CARTE ALLOUE ────────
#
# CE QUE CES DEUX GARDES FERMENT — B-1 de l'audit du 14 septembre 2026. La borne
# était prise autour du CALCUL et pas autour du CHARGEMENT, et `lru_cache` ne
# sérialise pas les manques concurrents : en CPython son verrou n'est tenu que
# pour la mise à jour du dictionnaire, jamais pendant l'exécution de la fonction
# enveloppée. `K` fils qui manquent le cache ensemble construisaient donc `K`
# modèles EN MÊME TEMPS, chacun plaçant sa copie des poids sur la carte — et
# l'allocateur de torch ne rend rien, ce que `_pic_memoire_reservee_mio` écrit
# lui-même. `mesuré` par l'audit sur le module réel : **8** constructions
# simultanées sous une borne de 4, contre 4 avec le constructeur sous le `with`.
#
# DEUX GARDES ET NON UN, PARCE QUE LES DEUX PROPRIÉTÉS SONT DISTINCTES ET QUE
# NI L'UNE NI L'AUTRE NE SUFFIT :
#   — la SÉRIALISATION rend une seule construction pour K manques simultanés.
#     Sans elle, les placer sous la borne ramènerait le pic de K à la borne — 4
#     copies au lieu de 8 — ce qui est une atténuation, pas une fermeture ;
#   — le PLACEMENT sous la borne fait que le chargement compte dans la grandeur
#     que la borne plafonne. Sans lui, une construction peut se dérouler pendant
#     que `TORCH_MAX_CONCURRENCY` calculs occupent déjà la carte, et le chiffre
#     de réservation rendu au voisin ne majore plus la scène.
#
# LES DEUX SONT ÉPROUVÉS SUR LE MODULE RÉEL, avec des doubles INERTES qui ne
# font que compter : ils ne chargent rien, ne touchent pas la carte, et ne
# savent rien de la borne.

_FILS_A_FROID = 8


def test_un_manque_de_cache_concurrent_ne_construit_qu_un_seul_modele(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LA PROPRIÉTÉ : K manques simultanés → UNE construction. Pas K, pas la borne.

    C'est la moitié qui ferme la mémoire. Le pic de la carte est pris au
    CHARGEMENT, et il n'est jamais rendu ; deux copies des poids construites en
    même temps coûtent deux fois, définitivement.

    LA BARRIÈRE EST DANS LE CONSTRUCTEUR, ET C'EST CE QUI REND LE ROUGE
    DÉTERMINISTE plutôt que dépendant de l'ordonnanceur : sous le défaut les
    `_FILS_A_FROID` constructeurs s'y retrouvent et la franchissent d'un coup,
    donc le pic mesuré est bien `_FILS_A_FROID` et non « ce que le hasard a
    laissé passer ». Sous la correction un seul constructeur y arrive, la
    barrière expire, il passe — le test coûte alors son délai UNE fois.

    On asserte la PROPRIÉTÉ (`<= 1`), pas l'instantané : un jour où la machine
    sérialiserait pour une autre raison, le garde doit rester juste.
    """
    presents = {"courant": 0, "pic": 0, "total": 0}
    compte = threading.Lock()
    # Participants = le nombre de fils : elle ne s'ouvre que si TOUS les
    # constructeurs y sont ensemble, ce qui est exactement le défaut.
    rendez_vous = threading.Barrier(_FILS_A_FROID)

    def _faux_st(nom: str, device: str | None = None) -> _FauxEmbedder:
        with compte:
            presents["courant"] += 1
            presents["total"] += 1
            presents["pic"] = max(presents["pic"], presents["courant"])
        # `suppress` et non un `except: pass` : la barrière CASSE quand un seul
        # constructeur s'y présente, et c'est le cas VERT — celui où la
        # sérialisation a fait son travail. Le garde ne doit pas pendre dessus.
        with contextlib.suppress(threading.BrokenBarrierError):
            rendez_vous.wait(timeout=1.0)
        with compte:
            presents["courant"] -= 1
        return _FauxEmbedder(device)

    monkeypatch.setattr(retriever, "SentenceTransformer", _faux_st)
    retriever._get_embedding_model.cache_clear()

    depart = threading.Barrier(_FILS_A_FROID)
    obtenus: list[Any] = []

    def _un_fil() -> None:
        depart.wait(timeout=5.0)
        obtenus.append(retriever._get_embedding_model())

    fils = [threading.Thread(target=_un_fil) for _ in range(_FILS_A_FROID)]
    for f in fils:
        f.start()
    for f in fils:
        f.join(timeout=15.0)

    assert not [f for f in fils if f.is_alive()], (
        "un fil n'est jamais revenu du chargement : la sérialisation pend au lieu "
        "de sérialiser"
    )
    assert len(obtenus) == _FILS_A_FROID, (
        f"tous les fils n'ont pas obtenu de modèle : {len(obtenus)}"
    )
    assert presents["pic"] <= 1, (
        f"{presents['pic']} constructions du modèle d'embedding étaient en cours EN "
        f"MÊME TEMPS (pour {_FILS_A_FROID} fils à froid). Chacune place sa copie des "
        "poids sur la carte, et l'allocateur de torch ne rend rien : le pic reste "
        "acquis. `lru_cache` ne sérialise pas les manques concurrents — il faut un "
        "verrou de chargement"
    )
    assert presents["total"] == 1, (
        f"{presents['total']} modèles construits pour {_FILS_A_FROID} manques "
        "simultanés. Sérialiser sans dédupliquer ne ferme rien : les copies "
        "surnuméraires sont bien construites l'une après l'autre, et chacune alloue"
    )
    assert len({id(m) for m in obtenus}) == 1, (
        "les fils n'ont pas tous reçu le MÊME modèle : le singleton n'en est plus un"
    )


def test_le_chargement_des_deux_modeles_se_fait_sous_la_borne(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LE PLACEMENT, par le VRAI chemin d'appel des deux étages.

    Le jumeau de `test_les_deux_etages_torch_passent_par_la_borne`, un cran plus
    tôt : celui-là observe le permis pendant `encode`/`predict`, celui-ci pendant
    la CONSTRUCTION. Les deux sont nécessaires — le lot 12 tenait le premier et
    la mutation qui déplaçait le constructeur hors de la borne laissait la suite
    entièrement verte (mutation M-A de l'audit).

    Le permis est observé DEPUIS le constructeur, et non par un traceur d'appels :
    un câblage qui prendrait puis rendrait le permis avant de charger serait vert
    à un traceur et faux en service.
    """
    monkeypatch.setattr(retriever.settings, "torch_device", "cpu", raising=False)
    monkeypatch.setattr(retriever.settings, "torch_max_concurrency", 1, raising=False)
    retriever.rearmer_la_borne_des_etages_torch()

    tenu: dict[str, bool] = {}

    def _permis_detenu() -> bool:
        """Vrai si l'unique permis est pris. Rendu immédiatement s'il ne l'était pas."""
        libre = retriever._semaphore().acquire(blocking=False)
        if libre:
            retriever._semaphore().release()
        return not libre

    class _Embedder:
        def __init__(self, nom: str = "", *, device: str | None = None) -> None:
            tenu["embedding"] = _permis_detenu()
            self.device = device

        def encode(self, question: str) -> Any:
            import numpy

            return numpy.zeros(3)

    class _Cross:
        def __init__(self, nom: str = "", *, device: str | None = None) -> None:
            tenu["rerank"] = _permis_detenu()
            self.device = device
            self.config = _Config()

        def predict(self, pairs: Any) -> Any:
            import numpy

            return numpy.zeros(len(pairs))

    class _Collection:
        def query(self, **kwargs: Any) -> dict[str, Any]:
            return {"documents": [[]], "metadatas": [[]], "distances": [[]], "ids": [[]]}

    monkeypatch.setattr(retriever, "SentenceTransformer", _Embedder)
    monkeypatch.setattr(retriever, "CrossEncoder", _Cross)
    monkeypatch.setattr(retriever, "verifier_modele_embedding", lambda: None)
    monkeypatch.setattr(retriever, "_get_chroma_collection", lambda: _Collection())
    retriever._get_embedding_model.cache_clear()
    retriever._get_rerank_model.cache_clear()

    try:
        retriever._dense_search("question", 5)
        retriever.rerank(
            "question",
            [
                ChunkResult(
                    chunk_id=f"c{i}",
                    element_id=f"{i:010x}",
                    graph_node_id=f"n{i}",
                    document="texte",
                    filename="f.pdf",
                    page_no=1,
                    label="text",
                    distance=0.1,
                )
                for i in range(3)
            ],
        )
    finally:
        retriever._get_embedding_model.cache_clear()
        retriever._get_rerank_model.cache_clear()

    assert tenu.get("embedding") is True, (
        "le CHARGEMENT du modèle d'embedding ne tient pas le permis de la borne : "
        f"{tenu}. C'est le moment où la carte alloue le plus, et il n'est compté "
        "dans aucune borne — le chiffre de réservation rendu au voisin ne majore "
        "alors plus la scène du démarrage à froid"
    )
    assert tenu.get("rerank") is True, (
        "le CHARGEMENT du reranker ne tient pas le permis de la borne : "
        f"{tenu}. Même panne que pour l'embedder, sur le modèle le plus lourd des deux"
    )

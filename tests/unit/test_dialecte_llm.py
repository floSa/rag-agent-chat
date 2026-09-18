"""L'interrupteur du dialecte, et la charge qui ne doit PAS bouger.

CE QUE CE FICHIER MESURE EN PREMIER, ET POURQUOI C'EST L'ESSENTIEL : l'agent en
service parle à Ollama. Une régression dans la charge qui part chez lui est une
panne réelle aujourd'hui, pas un risque futur. Les trois charges d'Ollama sont
donc confrontées à des LITTÉRAUX recopiés du code d'avant le lot 25 — pas à une
reconstruction par les mêmes fonctions, qui ne mesurerait que son propre écho —
et comparées DEUX FOIS : par égalité de dict, et sur le JSON sérialisé dans
l'ordre d'insertion, qui attrape en plus un champ déplacé.

Les formes vLLM assertées ici sont celles qui ont été RELEVÉES sur
`vllm-central` le 16 septembre 2026 entre 14:12 et 14:14 UTC, dix requêtes en
lecture, prompts tous distincts. Les mesures qui commandent chaque décision sont
écrites au site, dans `src/agent/dialecte_llm.py`.
"""

import json

import pytest
from pydantic import ValidationError

from src.agent import llm
from src.agent.dialecte_llm import Dialecte, dialecte_courant
from src.agent.flux_llm import charge_du_corps
from src.agent.settings import Settings, settings

@pytest.fixture(autouse=True)
def _base_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pose EXPLICITEMENT le dialecte d'Ollama comme base de ce fichier.

    Ces scènes héritaient du défaut de `LLM_ENGINE`, qui valait `ollama`. Le
    défaut décrit désormais ce qui est SERVI — vLLM —, et vingt-quatre scènes
    sont devenues rouges d'un coup : elles ne DEMANDAIENT pas le dialecte
    qu'elles mesuraient, elles le SUPPOSAIENT.

    Une scène qui veut le dialecte d'Ollama le demande, comme les scènes vLLM
    posent déjà le leur. Celles-ci surchargent cette fixture après elle, et rien
    ne change pour elles.
    """
    monkeypatch.setattr(settings, "llm_engine", "ollama")


MESSAGES = [{"role": "user", "content": "Quel est le taux de la prime de service ?"}]


@pytest.fixture
def vllm(monkeypatch):
    """Bascule le réglage sur vLLM pour la durée d'une scène, et le rend."""
    monkeypatch.setattr(settings, "llm_engine", "vllm")
    monkeypatch.setattr(settings, "vllm_host", "http://vllm-essai:8000")
    monkeypatch.setattr(settings, "vllm_model", "org/modele-essai")
    return dialecte_courant()


# ─── LE DÉFAUT NE BOUGE PAS ───────────────────────────────────────────────────


def test_le_moteur_par_defaut_est_vllm() -> None:
    """Le défaut du code décrit ce qui est SERVI, pas un état antérieur.

    Un défaut qui ment ne casse rien ICI — les deux hôtes par défaut sont
    injoignables sur ce poste, donc sans `.env` l'application échoue au lieu de
    mesurer faux. Mais le dépôt voisin avait un défaut JOIGNABLE sur l'ancien
    moteur : sa sonde a répondu normalement, sans erreur ni avertissement, et il
    a cru mesurer son produit pendant tout un tour.
    """
    assert Settings(_env_file=None).llm_engine == "vllm"


def test_le_dialecte_courant_est_celui_d_ollama() -> None:
    dialecte = dialecte_courant()
    assert dialecte.nom == "ollama"
    assert dialecte.hote == settings.ollama_host
    assert dialecte.modele == settings.ollama_model
    assert dialecte.url_chat == f"{settings.ollama_host}/api/chat"
    assert dialecte.url_sonde == f"{settings.ollama_host}/api/tags"


def test_la_charge_du_flux_est_celle_d_avant_le_lot(monkeypatch) -> None:
    """Le littéral est recopié de `generate_stream` d'avant le lot 25.

    Reconstruire l'attendu avec `dialecte.charge` ferait passer le test quoi
    qu'il arrive : il ne mesurerait que l'accord de la fonction avec elle-même.
    """
    monkeypatch.setattr(settings, "llm_temperature", 0.1)
    monkeypatch.setattr(settings, "llm_max_tokens", 4096)
    monkeypatch.setattr(settings, "llm_num_ctx", 8192)
    monkeypatch.setattr(settings, "llm_thinking", False)

    attendu = {
        "model": settings.ollama_model,
        "messages": MESSAGES,
        "stream": True,
        "think": False,
        "options": {"temperature": 0.1, "num_predict": 4096, "num_ctx": 8192},
        "tools": [llm.SEARCH_TOOL],
    }
    obtenu = dialecte_courant().charge(
        MESSAGES,
        stream=True,
        temperature=0.1,
        max_tokens=4096,
        thinking=False,
        outils=[llm.SEARCH_TOOL],
    )

    assert obtenu == attendu
    # L'ORDRE D'INSERTION AUSSI : un champ déplacé se lit comme un champ modifié
    # dans un diff, et c'est le chemin qui SERT.
    assert json.dumps(obtenu) == json.dumps(attendu)


def test_la_charge_de_la_reecriture_est_celle_d_avant_le_lot() -> None:
    attendu = {
        "model": settings.ollama_model,
        "messages": MESSAGES,
        "stream": False,
        "think": False,
        "options": {"temperature": 0.0, "num_predict": 120, "num_ctx": settings.llm_num_ctx},
    }
    obtenu = dialecte_courant().charge(
        MESSAGES, stream=False, temperature=0.0, max_tokens=120, thinking=False
    )
    assert obtenu == attendu
    assert json.dumps(obtenu) == json.dumps(attendu)


def test_la_charge_de_la_traduction_est_celle_d_avant_le_lot() -> None:
    attendu = {
        "model": settings.ollama_model,
        "messages": MESSAGES,
        "stream": False,
        "think": False,
        "options": {"temperature": 0.0, "num_predict": 150, "num_ctx": settings.llm_num_ctx},
    }
    obtenu = dialecte_courant().charge(
        MESSAGES, stream=False, temperature=0.0, max_tokens=150, thinking=False
    )
    assert obtenu == attendu
    assert json.dumps(obtenu) == json.dumps(attendu)


def test_sans_outils_la_charge_ollama_n_a_pas_de_cle_tools() -> None:
    """`payload["tools"]` n'était posé que si `native_tool_calling` : même règle."""
    assert "tools" not in dialecte_courant().charge(
        MESSAGES, stream=True, temperature=0.1, max_tokens=4096, thinking=False, outils=None
    )


def test_la_charge_ollama_n_a_aucune_cle_du_dialecte_openai() -> None:
    charge = dialecte_courant().charge(
        MESSAGES, stream=True, temperature=0.1, max_tokens=4096, thinking=True
    )
    for absente in ("max_tokens", "chat_template_kwargs", "stream_options"):
        assert absente not in charge


# ─── CE QUE LE RÉGLAGE COMMANDE VRAIMENT ──────────────────────────────────────


def test_la_bascule_change_le_chemin_le_modele_et_l_hote(vllm) -> None:
    assert vllm.nom == "vllm"
    assert vllm.url_chat == "http://vllm-essai:8000/v1/chat/completions"
    assert vllm.url_sonde == "http://vllm-essai:8000/v1/models"
    assert vllm.modele == "org/modele-essai"


def test_la_charge_vllm_porte_les_grandeurs_a_plat(vllm) -> None:
    charge = vllm.charge(MESSAGES, stream=False, temperature=0.3, max_tokens=250, thinking=False)
    assert charge["temperature"] == 0.3
    assert charge["max_tokens"] == 250
    assert "options" not in charge
    assert "think" not in charge


def test_num_ctx_n_est_pas_envoye_a_vllm_et_reste_envoye_a_ollama(vllm) -> None:
    """Le dialecte OpenAI n'a pas de champ de fenêtre ; l'inventer serait ignoré.

    Le versant Ollama est asserté dans la MÊME scène : sans lui, un mutant qui
    retirerait `num_ctx` des DEUX côtés passerait pour un bon citoyen.
    """
    assert "num_ctx" not in json.dumps(
        vllm.charge(MESSAGES, stream=True, temperature=0.1, max_tokens=4096, thinking=False)
    )
    ollama = Dialecte(nom="ollama", hote="http://o:11434", modele="m")
    assert (
        ollama.charge(MESSAGES, stream=True, temperature=0.1, max_tokens=4096, thinking=False)[
            "options"
        ]["num_ctx"]
        == settings.llm_num_ctx
    )


@pytest.mark.parametrize("raisonne", [True, False])
def test_le_raisonnement_passe_par_le_gabarit_et_par_requete(vllm, raisonne: bool) -> None:
    """Jamais par un drapeau de lancement : `vllm-central` est à une autre équipe.

    Et jamais par `think`, qui est un champ d'Ollama : envoyé à vLLM il est
    accepté puis IGNORÉ en silence (mesuré, voir `dialecte_llm`).
    """
    charge = vllm.charge(
        MESSAGES, stream=False, temperature=0.0, max_tokens=120, thinking=raisonne
    )
    assert charge["chat_template_kwargs"] == {"enable_thinking": raisonne}
    assert "think" not in charge


def test_les_decomptes_sont_demandes_en_flux_et_seulement_en_flux(vllm) -> None:
    """Sans `include_usage`, vLLM n'émet AUCUN `usage` en flux (mesuré : 0 sur 22).

    Hors flux le corps le porte sans qu'on demande, et `stream_options` y est
    refusé par le serveur.
    """
    en_flux = vllm.charge(MESSAGES, stream=True, temperature=0.1, max_tokens=4096, thinking=False)
    assert en_flux["stream_options"] == {"include_usage": True}
    hors_flux = vllm.charge(
        MESSAGES, stream=False, temperature=0.0, max_tokens=120, thinking=False
    )
    assert "stream_options" not in hors_flux


def test_continuous_usage_stats_n_est_pas_demande(vllm) -> None:
    """`flux_llm` sait le traiter ; le demander multiplierait le flux pour rien."""
    charge = vllm.charge(MESSAGES, stream=True, temperature=0.1, max_tokens=4096, thinking=False)
    assert "continuous_usage_stats" not in charge["stream_options"]


def test_un_moteur_inconnu_est_refuse_au_demarrage() -> None:
    """Une faute de frappe ne doit PAS retomber sur Ollama sans le dire.

    C'est la panne muette que tout ce lot existe pour empêcher, à l'endroit où
    elle serait la plus facile à laisser passer.
    """
    with pytest.raises(ValidationError):
        Settings(_env_file=None, LLM_ENGINE="vLLM-0.28")


# ─── LE RETOUR ARRIÈRE EST LE RÉGLAGE LUI-MÊME ────────────────────────────────


def test_la_bascule_revient_et_rien_n_est_memorise(monkeypatch) -> None:
    """Un interrupteur qui ne revient pas n'est pas un interrupteur.

    Ce chantier a déjà payé une mémorisation qui figeait une phrase fausse pour
    la vie du processus. `dialecte_courant()` relit à CHAQUE appel : la scène le
    mesure en basculant DANS le même processus, sans recharger un module.
    """
    avant = dialecte_courant()
    charge_avant = avant.charge(
        MESSAGES, stream=True, temperature=0.1, max_tokens=4096, thinking=False
    )

    monkeypatch.setattr(settings, "llm_engine", "vllm")
    pendant = dialecte_courant()
    assert pendant.nom == "vllm"
    assert pendant.url_chat != avant.url_chat

    monkeypatch.undo()
    apres = dialecte_courant()
    assert apres == avant
    assert (
        apres.charge(MESSAGES, stream=True, temperature=0.1, max_tokens=4096, thinking=False)
        == charge_avant
    )


def test_le_dialecte_est_relu_a_chaque_appel_pas_au_demarrage(monkeypatch) -> None:
    """Deux appels séparés par un changement de réglage rendent deux dialectes."""
    premier = dialecte_courant()
    monkeypatch.setattr(settings, "llm_engine", "vllm")
    assert dialecte_courant().nom != premier.nom


# ─── LES TROIS POSTES CONSOMMENT LE MÊME OBJET ────────────────────────────────


class _ClientEspion:
    """Capture l'URL et la charge du seul POST que le poste émet."""

    vus: list[tuple[str, dict]] = []

    def __init__(self, **_kwargs) -> None: ...

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def post(self, url, json=None, **_kwargs):
        type(self).vus.append((url, json))

        class Resp:
            def raise_for_status(self) -> None: ...

            def json(self) -> dict:
                return {"message": {"content": "réponse"}}

        return Resp()


@pytest.fixture
def espion(monkeypatch):
    _ClientEspion.vus = []
    monkeypatch.setattr(llm.httpx, "AsyncClient", _ClientEspion)
    return _ClientEspion


@pytest.mark.asyncio
async def test_la_reecriture_poste_sur_l_url_du_dialecte(espion, monkeypatch) -> None:
    monkeypatch.setattr(settings, "query_rewrite", True)
    historique = [llm.Message(role="user", content="Et la prime de service ?")]
    await llm.rewrite_question("Et pour les femmes ?", historique)

    url, charge = espion.vus[0]
    assert url == f"{settings.ollama_host}/api/chat"
    assert charge["options"]["num_predict"] == 120
    assert charge["stream"] is False


@pytest.mark.asyncio
async def test_la_traduction_poste_sur_l_url_du_dialecte(espion, monkeypatch) -> None:
    monkeypatch.setattr(settings, "cross_lingual_search", True)
    await llm.translate_question("Quel est le taux de la prime de service ?")

    url, charge = espion.vus[0]
    assert url == f"{settings.ollama_host}/api/chat"
    assert charge["options"]["num_predict"] == 150


@pytest.mark.asyncio
async def test_les_deux_postes_non_flux_basculent_ensemble(espion, monkeypatch) -> None:
    """DEUX postes en `stream: False`, et un lot qui n'en traiterait qu'un les
    laisserait parler Ollama à un serveur vLLM — sans erreur, mesuré."""
    monkeypatch.setattr(settings, "llm_engine", "vllm")
    monkeypatch.setattr(settings, "vllm_host", "http://vllm-essai:8000")
    monkeypatch.setattr(settings, "query_rewrite", True)
    monkeypatch.setattr(settings, "cross_lingual_search", True)

    historique = [llm.Message(role="user", content="Et la prime de service ?")]
    await llm.rewrite_question("Et pour les femmes ?", historique)
    await llm.translate_question("Quel est le taux de la prime de service ?")

    assert [url for url, _ in espion.vus] == [
        "http://vllm-essai:8000/v1/chat/completions"
    ] * 2
    for _, charge in espion.vus:
        assert "options" not in charge
        assert "max_tokens" in charge


# ─── LA LECTURE NON-FLUX CONNAÎT LES DEUX DIALECTES ───────────────────────────


def test_la_reponse_non_flux_de_vllm_est_lue() -> None:
    """Forme relevée sur `vllm-central` le 16 septembre 2026 à 14:12 UTC.

    Sans cette lecture, la réécriture et la traduction seraient tombées sur leur
    repli en HTTP 200 sur une réponse parfaitement valide.
    """
    corps = {
        "choices": [{"index": 0, "message": {"role": "assistant", "content": " Lisbonne "}}],
        "usage": {"prompt_tokens": 32, "completion_tokens": 5},
    }
    assert charge_du_corps(corps)["content"] == " Lisbonne "
    assert llm._contenu_message(corps) == "Lisbonne"


def test_la_reponse_non_flux_d_ollama_est_toujours_lue() -> None:
    """Le contrôle positif de la scène précédente : l'autre forme n'a pas bougé."""
    assert llm._contenu_message({"message": {"content": " Lisbonne "}}) == "Lisbonne"


def test_un_corps_sans_aucune_des_deux_formes_rend_la_chaine_vide() -> None:
    """La règle du dépôt est inchangée : forme nommée, "" rendu, pas d'exception."""
    for corps in ({"message": None}, {"choices": []}, {"choices": [{"delta": {}}]}, {}):
        assert llm._contenu_message(corps) == ""


def test_en_flux_le_fragment_prime_sur_la_reponse_assemblee() -> None:
    """Un corps qui porterait `delta` ET `message` cède le fragment.

    Rendre la réponse entière au milieu d'un flux la ferait s'afficher deux fois.
    """
    corps = {"choices": [{"delta": {"content": "frag"}, "message": {"content": "entier"}}]}
    assert charge_du_corps(corps)["content"] == "frag"


# ─── CE QUI PUBLIE LE MOTEUR NE DOIT PAS MENTIR APRÈS LA BASCULE ──────────────


@pytest.mark.asyncio
async def test_la_sonde_de_sante_suit_le_dialecte(monkeypatch) -> None:
    """Sinon basculer ferait passer `/health` `degraded` pour un service qui sert.

    Les deux sens sont dans la MÊME scène : sans le versant Ollama, un mutant
    qui enverrait TOUT LE MONDE sur `/v1/models` passerait.
    """
    from src.api import main

    vues: list[str] = []

    class Client:
        def __init__(self, **_k) -> None: ...

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, url, **_k):
            vues.append(url)

            class Resp:
                status_code = 200

            return Resp()

    monkeypatch.setattr(main.httpx, "AsyncClient", Client)

    assert await main._sonder_ollama() is True
    monkeypatch.setattr(settings, "llm_engine", "vllm")
    monkeypatch.setattr(settings, "vllm_host", "http://vllm-essai:8000")
    assert await main._sonder_ollama() is True

    assert vues == [
        f"{settings.ollama_host}/api/tags",
        "http://vllm-essai:8000/v1/models",
    ]


def test_l_empreinte_de_configuration_suit_le_moteur(monkeypatch) -> None:
    """Une campagne sous vLLM ne doit pas se regrouper avec celles d'Ollama."""
    from src.agent import usage

    hash_ollama, detail_ollama = usage.configuration()
    assert detail_ollama["ollama_model"] == settings.ollama_model

    monkeypatch.setattr(settings, "llm_engine", "vllm")
    monkeypatch.setattr(settings, "vllm_model", "org/modele-essai")
    hash_vllm, detail_vllm = usage.configuration()

    assert detail_vllm["ollama_model"] == "org/modele-essai"
    assert hash_vllm != hash_ollama
    # Aucune clé nouvelle : l'empreinte d'une campagne sous Ollama est celle
    # qu'elle avait, et les `runs/` déjà enregistrés restent groupés avec elle.
    assert detail_vllm.keys() == detail_ollama.keys()


# ─── LE POSTE DE FLUX, QUI EST LE POSTE PRINCIPAL ─────────────────────────────


def _flux_espion(vus: list[tuple[str, dict]]):
    """Un client qui capture l'URL et la charge du `stream`, et rend un flux vide.

    CETTE SCÈNE EXISTE PARCE QU'UNE MUTATION A SURVÉCU. Remettre
    `f"{settings.ollama_host}/api/chat"` en dur dans `generate_stream` ne
    faisait rougir AUCUN test : les deux postes non-flux étaient exercés sur
    leur URL, le poste de flux ne l'était pas — et c'est celui qui sert chaque
    réponse de l'agent.
    """

    class Resp:
        def raise_for_status(self) -> None: ...

        async def aiter_lines(self):
            yield json.dumps({"message": {"content": "Réponse."}, "done": True})

    class Stream:
        async def __aenter__(self):
            return Resp()

        async def __aexit__(self, *_):
            return False

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        def stream(self, _methode, url, json=None, **_kwargs):
            vus.append((url, json))
            return Stream()

    return lambda **_kwargs: Client()


@pytest.mark.asyncio
async def test_le_poste_de_flux_poste_sur_l_url_du_dialecte(monkeypatch) -> None:
    vus: list[tuple[str, dict]] = []
    monkeypatch.setattr(llm.httpx, "AsyncClient", _flux_espion(vus))

    async for _ in llm.generate_stream("Quel est le taux ?", []):
        pass

    url, charge = vus[0]
    assert url == f"{settings.ollama_host}/api/chat"
    assert charge["stream"] is True
    assert charge["options"]["num_predict"] == settings.llm_max_tokens


@pytest.mark.asyncio
async def test_le_poste_de_flux_bascule_avec_le_reglage(monkeypatch) -> None:
    """Les DEUX sens dans la même campagne : sans celle-ci, une URL figée sur
    Ollama passerait la scène précédente sans être basculable."""
    vus: list[tuple[str, dict]] = []
    monkeypatch.setattr(llm.httpx, "AsyncClient", _flux_espion(vus))
    monkeypatch.setattr(settings, "llm_engine", "vllm")
    monkeypatch.setattr(settings, "vllm_host", "http://vllm-essai:8000")
    monkeypatch.setattr(settings, "vllm_model", "org/modele-essai")

    async for _ in llm.generate_stream("Quel est le taux ?", []):
        pass

    url, charge = vus[0]
    assert url == "http://vllm-essai:8000/v1/chat/completions"
    assert charge["model"] == "org/modele-essai"
    assert charge["max_tokens"] == settings.llm_max_tokens
    assert charge["stream_options"] == {"include_usage": True}
    assert "options" not in charge


@pytest.mark.asyncio
async def test_le_poste_de_flux_transmet_le_reglage_de_raisonnement(monkeypatch) -> None:
    """LE TEXTE QUI SÉPARE LE CODE SERVI D'UN MUTANT ÉQUIVALENT.

    `thinking=settings.llm_thinking` remplacé par `thinking=False` survivait à
    toute la campagne : `LLM_THINKING` vaut `False` par défaut, donc la règle
    était inversée sur un champ CONSTANT dans le domaine mesuré, et la mutation
    ne pouvait pas se voir. Cette scène pose le seul état où les deux diffèrent.

    Les deux dialectes sont assertés, parce que le champ n'a pas le même nom des
    deux côtés et qu'un mutant pourrait n'en casser qu'un.
    """
    vus: list[tuple[str, dict]] = []
    monkeypatch.setattr(llm.httpx, "AsyncClient", _flux_espion(vus))
    monkeypatch.setattr(settings, "llm_thinking", True)

    async for _ in llm.generate_stream("Quel est le taux ?", []):
        pass
    assert vus[0][1]["think"] is True

    monkeypatch.setattr(settings, "llm_engine", "vllm")
    async for _ in llm.generate_stream("Quel est le taux ?", []):
        pass
    assert vus[1][1]["chat_template_kwargs"] == {"enable_thinking": True}


@pytest.mark.asyncio
async def test_health_publie_le_modele_du_moteur_courant(monkeypatch) -> None:
    """LE TEXTE QUI SÉPARE LE CODE SERVI D'UN MUTANT ÉQUIVALENT (seconde fois).

    `ollama_model=dialecte_courant().modele` remplacé par
    `settings.ollama_model` survivait à toute la campagne : sous le défaut, les
    deux valent la même chose. Le seul état où ils diffèrent est la bascule, et
    c'est celui que cette scène pose.

    Le champ garde son nom — il est publié depuis toujours — mais sa valeur doit
    suivre le moteur, sans quoi `/health` annoncerait un modèle que personne n'a
    demandé.
    """
    from src.api import main

    monkeypatch.setattr(main.settings, "api_key", "")
    monkeypatch.setattr(main.settings, "torch_device", "cpu")
    monkeypatch.setattr(main, "chroma_ping", lambda: True)
    monkeypatch.setattr(main, "nebula_ping", lambda: True)
    monkeypatch.setattr(main, "lexical_ready", lambda: True)
    # Aucune sortie réseau : ni la sonde booléenne, ni la sonde du moteur.
    monkeypatch.setattr(main, "_sonder_ollama", lambda: _vrai())
    monkeypatch.setattr(main, "_sonder_moteur_llm", lambda: _rien())

    assert (await main.health()).ollama_model == settings.ollama_model

    monkeypatch.setattr(settings, "llm_engine", "vllm")
    monkeypatch.setattr(settings, "vllm_model", "org/modele-essai")
    assert (await main.health()).ollama_model == "org/modele-essai"


async def _vrai() -> bool:
    return True


async def _rien() -> None:
    return None

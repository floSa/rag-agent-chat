"""Le dialecte sortant : l'adresse, la forme, et ce qu'un mutant ne doit pas figer.

CE QUE CE FICHIER MESURE, ET COMMENT IL S'Y PREND DEPUIS LE LOT 28.

Il mesurait deux dialectes et gardait le premier « à l'octet près » contre des
littéraux recopiés du code d'avant le lot 25. Le lot 28 retire le support de ce
moteur-là : ces littéraux décrivent une charge que le dépôt n'envoie plus, et un
garde qui fige une forme morte ne garde rien.

CE QUI REMPLACE LE « DEUX DIALECTES DANS LA MÊME SCÈNE ». Ce fichier exerçait sa
discrimination en assertant les DEUX versants d'un coup : un mutant qui figeait
une URL sur un moteur rougissait sur l'autre. Il n'y a plus d'autre. Chaque scène
POSE donc un hôte et un modèle d'ESSAI, distincts des défauts du code — un mutant
qui écrirait une route ou un nom de modèle en dur rougit alors, parce que ce
qu'il écrirait ne peut pas être ce que la scène a posé. Une scène qui hérite du
défaut ne mesure plus le site, elle mesure le défaut.

Les formes assertées ici ont été RELEVÉES sur `vllm-central` le 16 septembre 2026
entre 14:12 et 14:14 UTC, dix requêtes en lecture, prompts tous distincts. Les
mesures qui commandent chaque décision sont écrites au site, dans
`src/agent/dialecte_llm.py`.
"""

import json

import pytest

from src.agent import llm
from src.agent.dialecte_llm import Dialecte, dialecte_courant
from src.agent.flux_llm import charge_du_corps
from src.agent.settings import Settings, settings

# L'hôte et le modèle que ce fichier POSE. Ils ne sont ni l'un ni l'autre le
# défaut du code : c'est ce qui rend une valeur écrite en dur détectable.
_HOTE = "http://vllm-essai:8000"
_MODELE = "org/modele-essai"

MESSAGES = [{"role": "user", "content": "Quel est le taux de la prime de service ?"}]


@pytest.fixture(autouse=True)
def _pose_le_moteur(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pose l'hôte et le modèle de ce fichier, qui ne sont pas les défauts.

    AUTOUSE ET NON OPTIONNELLE, et c'est la leçon de la fixture qu'elle remplace :
    vingt-quatre scènes de ce dépôt ont rougi d'un coup le jour où un défaut a
    changé, parce qu'elles ne DEMANDAIENT pas ce qu'elles mesuraient, elles le
    SUPPOSAIENT. Une scène pose ce qu'elle mesure.
    """
    monkeypatch.setattr(settings, "llm_host", _HOTE)
    monkeypatch.setattr(settings, "llm_model", _MODELE)


# ─── LE DÉFAUT DÉCRIT CE QUI EST SERVI ────────────────────────────────────────


def test_les_defauts_decrivent_le_serveur_reellement_servi() -> None:
    """Un défaut qui ment fait mesurer un autre serveur que celui qu'on croit.

    Le dépôt voisin avait un défaut JOIGNABLE sur un serveur qui n'était pas le
    sien : sa sonde a répondu normalement, sans erreur ni avertissement, et il a
    cru mesurer son produit pendant tout un tour. Ces deux défauts-ci décrivent
    le service `vllm-central` du réseau `llm-net` et le modèle qu'il sert.

    `_env_file=None` : sans lui, cette scène lirait le `.env` du poste et
    mesurerait une configuration au lieu du code.
    """
    nu = Settings(_env_file=None)
    assert nu.llm_host == "http://vllm-central:8000"
    assert nu.llm_model == "google/gemma-4-E4B-it-qat-w4a16-ct"


def test_les_reglages_de_l_ancien_moteur_n_existent_plus() -> None:
    """Le support est RETIRÉ, pas seulement le nom — et un champ retiré se mesure.

    `extra="ignore"` fait qu'un `.env` qui porterait encore ces clés démarrerait
    sans un mot. Ce que cette scène tient, c'est que le code ne les lit plus :
    sans elle, une réintroduction silencieuse serait invisible.
    """
    champs = set(Settings.model_fields)
    # LES DEUX NOMS SONT COMPOSÉS, pour la même raison qu'au site du garde de
    # noms (`test_moteur_unique.py`) : une scène qui cherche un nom en l'écrivant
    # en clair le fait entrer dans le dépôt, et le garde le trouverait ici.
    moteurs = ("olla" + "ma", "v" + "llm")
    nommants = {c for c in champs if any(m in c for m in moteurs)}
    assert not nommants, (
        f"un réglage nomme encore un moteur : {sorted(nommants)}"
    )
    assert "llm_engine" not in champs


def test_le_dialecte_lit_les_reglages_et_ecrit_les_routes() -> None:
    """Les deux routes sont ici, et elles sont les SEULES du dépôt."""
    dialecte = dialecte_courant()
    assert dialecte.hote == _HOTE
    assert dialecte.modele == _MODELE
    assert dialecte.url_chat == f"{_HOTE}/v1/chat/completions"
    assert dialecte.url_sonde == f"{_HOTE}/v1/models"


def test_le_dialecte_ne_porte_plus_le_nom_d_un_moteur() -> None:
    """Un champ à une seule valeur possible n'est pas une donnée (lot 28).

    Ce que ce retrait empêche : que `main.py` ou `llm.py` se remettent à lire un
    nom de moteur pour décider quelque chose — la branche que `dialecte_llm`
    existe pour ne pas laisser se répandre.
    """
    assert "nom" not in Dialecte._fields
    assert Dialecte._fields == ("hote", "modele")


# ─── LA FORME DE LA CHARGE ────────────────────────────────────────────────────


def test_la_charge_du_flux_est_celle_qui_a_ete_relevee() -> None:
    """La charge de production, confrontée à un littéral et non à son propre écho.

    Le littéral est reconstruit ici, champ par champ, dans l'ordre d'insertion
    qu'il doit avoir — et comparé DEUX FOIS : par égalité de dict, et sur le JSON
    sérialisé, qui attrape en plus un champ déplacé.
    """
    attendu = {
        "model": _MODELE,
        "messages": MESSAGES,
        "stream": True,
        "temperature": 0.1,
        "max_tokens": 4096,
        "chat_template_kwargs": {"enable_thinking": False},
        "stream_options": {"include_usage": True},
    }
    obtenu = dialecte_courant().charge(
        MESSAGES, stream=True, temperature=0.1, max_tokens=4096, thinking=False
    )
    assert obtenu == attendu
    assert json.dumps(obtenu) == json.dumps(attendu)


def test_les_grandeurs_qui_changent_le_sens_sont_toutes_passees() -> None:
    """Aucune n'est laissée au défaut du serveur, et c'est la décision du site.

    Un champ omis est appliqué par le serveur avec SA valeur, sans un mot : la
    génération se ferait alors à une autre température et à un autre plafond que
    ceux qu'on croit mesurer.
    """
    charge = dialecte_courant().charge(
        MESSAGES, stream=False, temperature=0.3, max_tokens=250, thinking=False
    )
    assert charge["temperature"] == 0.3
    assert charge["max_tokens"] == 250
    assert charge["model"] == _MODELE


def test_aucun_champ_de_l_ancien_dialecte_ne_subsiste() -> None:
    """Ils sont ACCEPTÉS ET IGNORÉS par ce serveur, donc muets (mesuré 16/09).

    C'est la raison d'être du site unique : un champ de l'autre dialecte qui
    reviendrait ne lèverait pas, ne s'afficherait pas dans un journal, et ferait
    générer avec les valeurs par défaut du serveur.
    """
    charge = dialecte_courant().charge(
        MESSAGES, stream=True, temperature=0.1, max_tokens=4096, thinking=True
    )

    def cles(objet: object) -> set[str]:
        """Toutes les clés, à tous les niveaux.

        LES CLÉS ET NON LE JSON SÉRIALISÉ, et c'est un faux résultat que j'ai
        trouvé contre moi-même : cette scène cherchait `"options"` comme
        sous-chaîne, et `stream_options` — un champ LÉGITIME du dialecte servi —
        la contient. Elle rougissait sur le code juste. Un garde qui reconnaît
        par sous-chaîne accuse au hasard.
        """
        trouvees: set[str] = set()
        if isinstance(objet, dict):
            for cle, valeur in objet.items():
                trouvees.add(cle)
                trouvees |= cles(valeur)
        elif isinstance(objet, list):
            for element in objet:
                trouvees |= cles(element)
        return trouvees

    presentes = cles(charge)
    for absent in ("options", "num_predict", "num_ctx", "think", "format"):
        assert absent not in presentes, f"champ de l'ancien dialecte revenu : {absent}"


def test_sans_outils_la_charge_n_a_pas_de_cle_tools() -> None:
    """`payload["tools"]` n'est posé que si `native_tool_calling` : même règle."""
    assert "tools" not in dialecte_courant().charge(
        MESSAGES, stream=True, temperature=0.1, max_tokens=4096, thinking=False, outils=None
    )


def test_num_ctx_n_est_pas_envoye_au_serveur() -> None:
    """Le dialecte OpenAI n'a pas de champ de fenêtre ; l'inventer serait ignoré.

    `LLM_NUM_CTX` reste pleinement utilisé, mais CÔTÉ CLIENT — il borne ce qu'on
    s'autorise à envoyer. La scène pose une valeur qu'on reconnaîtrait si elle
    partait : un mutant qui la glisserait dans la charge, sous n'importe quel
    nom, rougit ici.
    """
    monkeypatched = 4242
    settings.llm_num_ctx, ancien = monkeypatched, settings.llm_num_ctx
    try:
        serialise = json.dumps(
            dialecte_courant().charge(
                MESSAGES, stream=True, temperature=0.1, max_tokens=4096, thinking=False
            )
        )
    finally:
        settings.llm_num_ctx = ancien
    assert str(monkeypatched) not in serialise


@pytest.mark.parametrize("raisonne", [True, False])
def test_le_raisonnement_passe_par_le_gabarit_et_par_requete(raisonne: bool) -> None:
    """Jamais par un drapeau de lancement : `vllm-central` est à une autre équipe.

    Bogue vLLM #39130 : le raisonnement posé côté SERVEUR contourne
    silencieusement la sortie structurée, sur une instance partagée avec deux
    autres équipes.
    """
    charge = dialecte_courant().charge(
        MESSAGES, stream=False, temperature=0.0, max_tokens=120, thinking=raisonne
    )
    assert charge["chat_template_kwargs"] == {"enable_thinking": raisonne}


def test_les_decomptes_sont_demandes_en_flux_et_seulement_en_flux() -> None:
    """Sans `include_usage`, le serveur n'émet AUCUN `usage` en flux (0 sur 22).

    Hors flux le corps le porte sans qu'on demande, et `stream_options` y est
    refusé par le serveur.
    """
    en_flux = dialecte_courant().charge(
        MESSAGES, stream=True, temperature=0.1, max_tokens=4096, thinking=False
    )
    assert en_flux["stream_options"] == {"include_usage": True}
    hors_flux = dialecte_courant().charge(
        MESSAGES, stream=False, temperature=0.0, max_tokens=120, thinking=False
    )
    assert "stream_options" not in hors_flux


def test_continuous_usage_stats_n_est_pas_demande() -> None:
    """`flux_llm` sait le traiter ; le demander multiplierait le flux pour rien."""
    charge = dialecte_courant().charge(
        MESSAGES, stream=True, temperature=0.1, max_tokens=4096, thinking=False
    )
    assert "continuous_usage_stats" not in charge["stream_options"]


def test_la_graine_et_le_format_contraint_sont_absents_quand_ils_ne_sont_pas_demandes() -> None:
    """La charge de production ne bouge pas d'un octet pour deux scripts d'outillage."""
    production = dialecte_courant().charge(
        MESSAGES, stream=True, temperature=0.1, max_tokens=4096, thinking=False
    )
    assert "seed" not in production and "response_format" not in production

    outillage = dialecte_courant().charge(
        MESSAGES,
        stream=False,
        temperature=0.4,
        max_tokens=200,
        thinking=False,
        graine=42,
        format_json=True,
    )
    assert outillage["seed"] == 42
    assert outillage["response_format"] == {"type": "json_object"}


# ─── RIEN N'EST MÉMORISÉ ──────────────────────────────────────────────────────


def test_le_dialecte_est_relu_a_chaque_appel_pas_au_demarrage(monkeypatch) -> None:
    """Deux appels séparés par un changement de réglage rendent deux dialectes.

    CE QUE CETTE SCÈNE TIENT APRÈS LE LOT 28, alors que le réglage ne bascule
    plus de moteur : un dialecte mémorisé au démarrage rendrait les scènes
    incapables de poser un hôte sans recharger le processus, et figerait à vie un
    relevé que ce chantier a déjà payé une fois.
    """
    premier = dialecte_courant()
    monkeypatch.setattr(settings, "llm_host", "http://autre-serveur:9000")
    second = dialecte_courant()
    assert second.hote != premier.hote
    assert second.url_chat == "http://autre-serveur:9000/v1/chat/completions"


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
                return {"choices": [{"message": {"content": "réponse"}}]}

        return Resp()


@pytest.fixture
def espion(monkeypatch):
    _ClientEspion.vus = []
    monkeypatch.setattr(llm.httpx, "AsyncClient", _ClientEspion)
    return _ClientEspion


@pytest.mark.asyncio
async def test_les_deux_postes_non_flux_passent_par_le_dialecte(espion, monkeypatch) -> None:
    """DEUX postes en `stream: False`, et un lot qui n'en traiterait qu'un
    laisserait l'autre parler un dialecte mort — sans erreur, mesuré."""
    monkeypatch.setattr(settings, "query_rewrite", True)
    monkeypatch.setattr(settings, "cross_lingual_search", True)

    historique = [llm.Message(role="user", content="Et la prime de service ?")]
    await llm.rewrite_question("Et pour les femmes ?", historique)
    await llm.translate_question("Quel est le taux de la prime de service ?")

    assert [url for url, _ in espion.vus] == [f"{_HOTE}/v1/chat/completions"] * 2
    plafonds = [charge["max_tokens"] for _, charge in espion.vus]
    assert plafonds == [120, 150], "les deux postes ont leur propre plafond"
    for _, charge in espion.vus:
        assert charge["stream"] is False
        assert charge["model"] == _MODELE


# ─── LA LECTURE NON-FLUX ──────────────────────────────────────────────────────


def test_la_reponse_non_flux_est_lue() -> None:
    """Forme relevée sur `vllm-central` le 16 septembre 2026 à 14:12 UTC.

    Sans cette lecture, la réécriture et la traduction tombaient sur leur repli
    en HTTP 200, sur une réponse parfaitement valide.
    """
    corps = {
        "choices": [{"index": 0, "message": {"role": "assistant", "content": " Lisbonne "}}],
        "usage": {"prompt_tokens": 32, "completion_tokens": 5},
    }
    assert charge_du_corps(corps)["content"] == " Lisbonne "
    assert llm._contenu_message(corps) == "Lisbonne"


def test_un_corps_sans_la_forme_attendue_rend_la_chaine_vide() -> None:
    """La règle du dépôt est inchangée : forme nommée, "" rendu, pas d'exception."""
    for corps in ({"message": None}, {"choices": []}, {"choices": [{"delta": {}}]}, {}):
        assert llm._contenu_message(corps) == ""


def test_la_forme_de_l_ancien_moteur_n_est_plus_lue() -> None:
    """LE CONTRÔLE NÉGATIF DU RETRAIT, et il mesure ce que le lot a fait.

    `{"message": {...}}` à la racine était la forme de l'autre moteur. Sans cette
    scène, sa lecture pourrait revenir sans que rien ne le dise — et un lecteur
    qui accepte deux formes n'est plus le lecteur d'UNE forme.
    """
    assert charge_du_corps({"message": {"content": "Lisbonne"}}) == {}
    assert llm._contenu_message({"message": {"content": "Lisbonne"}}) == ""


def test_en_flux_le_fragment_prime_sur_la_reponse_assemblee() -> None:
    """Un corps qui porterait `delta` ET `message` cède le fragment.

    Rendre la réponse entière au milieu d'un flux la ferait s'afficher deux fois.
    """
    corps = {"choices": [{"delta": {"content": "frag"}, "message": {"content": "entier"}}]}
    assert charge_du_corps(corps)["content"] == "frag"


# ─── CE QUE `/health` ET LES CAMPAGNES PUBLIENT ───────────────────────────────


@pytest.mark.asyncio
async def test_la_sonde_de_sante_suit_le_dialecte(monkeypatch) -> None:
    """Une route écrite en dur ferait passer `/health` `degraded` pour un service
    qui répond et génère. La scène pose un hôte que le code ne peut pas deviner."""
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

    assert await main._sonder_moteur() is True
    assert vues == [f"{_HOTE}/v1/models"]


def test_l_empreinte_de_configuration_suit_le_modele_demande(monkeypatch) -> None:
    """Deux campagnes sur deux modèles ne doivent pas se regrouper.

    C'est la clé qui, dans `config_hash`, sépare un moteur d'un autre : les noms
    de modèle sont ce qui reste pour les distinguer.
    """
    from src.agent import usage

    hash_a, detail_a = usage.configuration()
    assert detail_a["llm_model"] == _MODELE

    monkeypatch.setattr(settings, "llm_model", "org/autre-modele")
    hash_b, detail_b = usage.configuration()

    assert detail_b["llm_model"] == "org/autre-modele"
    assert hash_b != hash_a
    assert detail_b.keys() == detail_a.keys(), "aucune clé nouvelle dans l'empreinte"


def test_l_empreinte_ne_nomme_plus_l_ancien_moteur() -> None:
    """La clé a été renommée avec le réglage qu'elle porte (lot 28).

    Elle entre dans `config_hash` : la renommer dégroupe les campagnes à venir de
    celles déjà enregistrées. Le dégroupement était déjà consommé — `mesuré` le
    18 septembre 2026, aucune des 20 campagnes versionnées de `runs/` n'a été
    produite sous le moteur servi aujourd'hui.
    """
    from src.agent import usage

    _, detail = usage.configuration()
    # LA CLÉ DE L'ANCIEN MOTEUR EST ÉCRITE PAR MORCEAUX, et c'est un faux
    # résultat que j'ai trouvé contre moi-même : un remplacement global de son
    # nom dans les tests a retourné cette assertion — elle affirmait l'absence de
    # la clé NEUVE, donc elle rougissait sur le code juste. L'écrire en deux
    # moitiés la met hors d'atteinte d'un remplacement de chaîne, et le garde de
    # noms de ce dépôt n'a rien à y trouver non plus.
    ancienne = "olla" + "ma_model"
    assert ancienne not in detail
    assert "llm_model" in detail


# ─── LE POSTE DE FLUX, QUI EST LE POSTE PRINCIPAL ─────────────────────────────


def _flux_espion(vus: list[tuple[str, dict]]):
    """Un client qui capture l'URL et la charge du `stream`, et rend un flux vide.

    CETTE SCÈNE EXISTE PARCE QU'UNE MUTATION A SURVÉCU. Remettre une URL en dur
    dans `generate_stream` ne faisait rougir AUCUN test : les deux postes
    non-flux étaient exercés sur leur URL, le poste de flux ne l'était pas — et
    c'est celui qui sert chaque réponse de l'agent.
    """

    class Resp:
        def raise_for_status(self) -> None: ...

        async def aiter_lines(self):
            yield "data: " + json.dumps({"choices": [{"delta": {"content": "Réponse."}}]})
            yield "data: [DONE]"

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
    assert url == f"{_HOTE}/v1/chat/completions"
    assert charge["model"] == _MODELE
    assert charge["stream"] is True
    assert charge["max_tokens"] == settings.llm_max_tokens
    assert charge["stream_options"] == {"include_usage": True}


@pytest.mark.asyncio
async def test_le_poste_de_flux_transmet_le_reglage_de_raisonnement(monkeypatch) -> None:
    """LE TEXTE QUI SÉPARE LE CODE SERVI D'UN MUTANT ÉQUIVALENT.

    `thinking=settings.llm_thinking` remplacé par `thinking=False` survivait à
    toute la campagne : `LLM_THINKING` vaut `False` par défaut, donc la règle
    était inversée sur un champ CONSTANT dans le domaine mesuré, et la mutation
    ne pouvait pas se voir. Cette scène pose le seul état où les deux diffèrent.
    """
    vus: list[tuple[str, dict]] = []
    monkeypatch.setattr(llm.httpx, "AsyncClient", _flux_espion(vus))
    monkeypatch.setattr(settings, "llm_thinking", True)

    async for _ in llm.generate_stream("Quel est le taux ?", []):
        pass
    assert vus[0][1]["chat_template_kwargs"] == {"enable_thinking": True}


@pytest.mark.asyncio
async def test_health_publie_le_modele_du_dialecte_et_non_un_reglage_fige(monkeypatch) -> None:
    """LE TEXTE QUI SÉPARE LE CODE SERVI D'UN MUTANT ÉQUIVALENT (seconde fois).

    Le champ publié doit être celui que le dialecte DEMANDE. La scène pose un
    modèle que ni le défaut ni le `.env` ne portent : un mutant qui publierait
    autre chose rougit.
    """
    from src.api import main

    monkeypatch.setattr(main.settings, "api_key", "")
    monkeypatch.setattr(main.settings, "torch_device", "cpu")
    monkeypatch.setattr(main, "chroma_ping", lambda: True)
    monkeypatch.setattr(main, "nebula_ping", lambda: True)
    monkeypatch.setattr(main, "lexical_ready", lambda: True)
    # Aucune sortie réseau : ni la sonde booléenne, ni la sonde du moteur.
    monkeypatch.setattr(main, "_sonder_moteur", lambda: _vrai())
    monkeypatch.setattr(main, "_sonder_moteur_llm", lambda: _rien())

    assert (await main.health()).llm_model == _MODELE

    monkeypatch.setattr(settings, "llm_model", "org/encore-un-autre")
    assert (await main.health()).llm_model == "org/encore-un-autre"


async def _vrai() -> bool:
    return True


async def _rien() -> None:
    return None

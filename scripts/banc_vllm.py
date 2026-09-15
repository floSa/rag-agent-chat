"""Banc GO/NO-GO de la bascule Ollama -> vLLM. Ne fait partie d'AUCUN chemin de production.

Aucun module de `src/` n'importe ce fichier : il importe la production, jamais
l'inverse. C'est délibéré et c'est la preuve qu'il porte — il juge les réponses
des deux moteurs avec `extract_tool_query`, le lecteur que la production
utilise vraiment, et non avec une relecture réécrite pour l'occasion. Un banc
qui réimplémente le lecteur ne mesure que lui-même.

Contraintes que ce banc s'impose, et qui sont celles du poste :

- il n'alloue pas un octet de carte : il ne parle qu'à des serveurs DÉJÀ lancés ;
- il ne pose **aucun** drapeau de lancement. Tout ce qu'il éprouve se pose PAR
  REQUÊTE, parce que l'instance vLLM est partagée avec une autre équipe dont la
  sortie structurée tourne en production dessus (bogue vLLM #39130 : le
  raisonnement posé côté SERVEUR contourne silencieusement la sortie
  structurée) ;
- réponses courtes, une requête à la fois, une pause entre deux, un délai de
  garde sur chacune ;
- il COMPTE ses requêtes, par serveur, et le décompte sort dans le journal.

Usage :
    python scripts/banc_vllm.py --sonde tout --journal runs/banc.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from jinja2 import Environment, FileSystemLoader, select_autoescape

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from src.agent.llm import SEARCH_TOOL, extract_tool_query  # noqa: E402

# --------------------------------------------------------------------------
# Adresses. Ce sont des services DÉJÀ lancés ; le banc n'en démarre aucun.
# --------------------------------------------------------------------------
VLLM = "http://localhost:8100"
OLLAMA = "http://localhost:11434"
MODELE_VLLM = "google/gemma-4-E4B-it-qat-w4a16-ct"
MODELE_OLLAMA = "gemma4:e4b"

# Délai de garde EXTÉRIEUR à chaque requête. Une sonde qui pend n'est pas une
# mesure : c'est une sonde qui pend.
DELAI = 90.0
# Pause entre deux requêtes : le voisin dit que le volume ne le gêne pas, ce
# n'est pas une raison pour l'inonder.
PAUSE = 1.0
# Réponses courtes partout. La sonde du raisonnement seule monte plus haut,
# parce que son objet est précisément de voir si le budget part en réflexion.
JETONS_COURTS = 64
JETONS_RAISONNEMENT = 300

# Le repli de `graph.py:315`, recopié ICI et nulle part ailleurs dans ce banc.
# Le recopier est un choix : `graph.py` ne l'expose pas en fonction, et
# l'importer voudrait dire importer le graphe entier. Le banc vérifie donc
# d'abord que cette copie est bien celle du site canonique.
MOTIF_REPLI = r"search_vectors\([\"'](.+?)[\"']\)"
SITE_REPLI = RACINE / "src" / "agent" / "graph.py"


def verifier_la_copie_du_repli() -> str:
    """Refuse de mesurer si la copie du motif a divergé de son site canonique.

    Sans ce contrôle, le banc mesurerait un repli que la production n'a plus.
    """
    source = SITE_REPLI.read_text(encoding="utf-8")
    if MOTIF_REPLI not in source:
        raise SystemExit(
            f"Le motif de repli recopié dans ce banc est introuvable dans {SITE_REPLI}. "
            "Le site canonique a changé : la mesure serait fausse."
        )
    return "copie conforme au site canonique"


@dataclass
class Compteur:
    """Décompte des requêtes réellement parties, par serveur."""

    par_serveur: dict[str, int] = field(default_factory=dict)

    def ajouter(self, serveur: str) -> None:
        self.par_serveur[serveur] = self.par_serveur.get(serveur, 0) + 1

    @property
    def total(self) -> int:
        return sum(self.par_serveur.values())


COMPTEUR = Compteur()


def _poster(base: str, chemin: str, charge: dict[str, Any]) -> tuple[int, Any, float]:
    """Une requête non-streamée. Rend (code, corps, secondes).

    Le code HTTP est rendu mais il ne CONCLUT rien : sur ce chantier, un appel
    d'outil qui a fui dans le texte sort en 200 sans un seul log.
    """
    COMPTEUR.ajouter(base)
    debut = time.monotonic()
    with httpx.Client(timeout=httpx.Timeout(DELAI)) as client:
        reponse = client.post(f"{base}{chemin}", json=charge)
    ecoule = time.monotonic() - debut
    try:
        corps = reponse.json()
    except ValueError:
        corps = {"_corps_non_json": reponse.text[:2000]}
    time.sleep(PAUSE)
    return reponse.status_code, corps, ecoule


def _flux(base: str, chemin: str, charge: dict[str, Any], garder: int = 6) -> dict[str, Any]:
    """Une requête streamée. Rend les premières lignes BRUTES et le temps au premier jeton.

    Les lignes sont gardées telles qu'elles arrivent — c'est la forme réelle
    qu'on veut, pas une forme déjà interprétée par un client.
    """
    COMPTEUR.ajouter(base)
    lignes_brutes: list[str] = []
    debut = time.monotonic()
    ttft: float | None = None
    total = 0
    with (
        httpx.Client(timeout=httpx.Timeout(DELAI, read=DELAI)) as client,
        client.stream("POST", f"{base}{chemin}", json=charge) as reponse,
    ):
        code = reponse.status_code
        for ligne in reponse.iter_lines():
            if len(lignes_brutes) < garder:
                lignes_brutes.append(ligne)
            if not ligne.strip():
                continue
            total += 1
            if ttft is None and _porte_du_contenu(ligne):
                ttft = time.monotonic() - debut
    time.sleep(PAUSE)
    return {
        "code": code,
        "lignes_brutes": lignes_brutes,
        "lignes_non_vides": total,
        "ttft_s": round(ttft, 3) if ttft is not None else None,
        "total_s": round(time.monotonic() - debut, 3),
    }


def _porte_du_contenu(ligne: str) -> bool:
    """Vrai si cette ligne de flux porte du texte destiné à l'utilisateur.

    Le temps au premier jeton n'est pas le temps à la première LIGNE : le rôle,
    l'entête SSE et les lignes vides arrivent avant, et les compter donnerait un
    TTFT flatteur qui ne correspond à rien à l'écran.
    """
    brute = ligne[len("data: ") :] if ligne.startswith("data: ") else ligne
    brute = brute.strip()
    if not brute or brute == "[DONE]":
        return False
    try:
        objet = json.loads(brute)
    except json.JSONDecodeError:
        return False
    # Forme OpenAI
    for choix in objet.get("choices") or []:
        if (choix.get("delta") or {}).get("content"):
            return True
    # Forme native Ollama
    return bool((objet.get("message") or {}).get("content"))


def _gabarit(nom: str, **variables: Any) -> str:
    env = Environment(
        loader=FileSystemLoader(RACINE / "prompts"),
        autoescape=select_autoescape(enabled_extensions=(), default=False),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env.get_template(nom).render(**variables)


SYSTEME = (RACINE / "prompts" / "system.txt").read_text(encoding="utf-8")

# Une scène RAG réaliste : trois sources, leurs element_id au format que
# l'agent valide (^[a-f0-9]{10}$), et une question à laquelle elles répondent.
SOURCES = [
    ("a1b2c3d4e5", "Le congé de paternité est de 25 jours calendaires depuis juillet 2021."),
    ("f6a7b8c9d0", "Le congé de maternité est de 16 semaines pour un premier enfant."),
    ("1234abcd56", "Les demandes de congé se déposent sur le portail RH, 30 jours à l'avance."),
]


# Une quatrième source, qui AIGUILLE sans répondre. Sans elle, le modèle
# applique la règle 4 du système (« dis que tu n'as pas trouvé ») et n'appelle
# jamais l'outil — sur AUCUN des deux moteurs. Mesuré le 15 septembre 2026 :
# quatre cellules sur quatre sans appel et sans fuite, donc quatre cellules qui
# ne distinguaient rien. Le premier faux résultat de ce banc, contre lui-même.
AIGUILLON = (
    "9f8e7d6c5b",
    "Le congé parental d'éducation fait l'objet d'une fiche distincte, référence RH-114, "
    "non reproduite ici.",
)


def _scene(question: str, aiguillon: bool = False) -> list[dict[str, str]]:
    sources = [*SOURCES, AIGUILLON] if aiguillon else list(SOURCES)
    corps = "\n\n".join(f"[src:{eid}] {texte}" for eid, texte in sources)
    return [
        {"role": "system", "content": SYSTEME},
        {"role": "user", "content": f"Sources :\n\n{corps}\n\nQuestion : {question}"},
    ]


# Le prompt système de production porte DEUX règles qui se contredisent quand
# les sources ne suffisent pas : la 4 ordonne de dire qu'on n'a pas trouvé, la
# 5 ordonne d'appeler l'outil. Mesuré le 15 septembre 2026 : la 4 gagne, sur
# les DEUX moteurs. Une scène qui ne lève pas cette pince ne mesure donc pas le
# moteur, elle mesure le prompt. Celle-ci la lève depuis le MESSAGE
# UTILISATEUR, sans toucher au système.
INJONCTION = (
    "Les sources ci-dessus ne suffisent pas. Lance une recherche complémentaire "
    "sur la durée du congé parental d'éducation avant de répondre."
)


def _scene_injonction() -> list[dict[str, str]]:
    corps = "\n\n".join(f"[src:{eid}] {texte}" for eid, texte in SOURCES)
    return [
        {"role": "system", "content": SYSTEME},
        {"role": "user", "content": f"Sources :\n\n{corps}\n\n{INJONCTION}"},
    ]


def _lire_openai(corps: Any) -> dict[str, Any]:
    """Traduit une réponse OpenAI vers la FORME que notre code lit déjà.

    C'est le seul endroit du banc où une traduction a lieu, et elle est
    minuscule : `choices[0].message` porte déjà `tool_calls` au même nom et à la
    même place que `/api/chat`. C'est le résultat que la question 1 cherche.
    """
    choix = (corps.get("choices") or [{}])[0]
    return choix.get("message") or {}


# --------------------------------------------------------------------------
# Sonde 1 — l'outil est-il RÉELLEMENT appelé, et à quoi ressemble une fuite ?
# --------------------------------------------------------------------------
def sonde_outil() -> dict[str, Any]:
    question = "Quelle est la durée du congé parental d'éducation ?"
    resultats: dict[str, Any] = {"motif_repli": verifier_la_copie_du_repli(), "cellules": []}

    # CONTRÔLE POSITIF DU TRANSPORT, et il est séparé du reste exprès. Il
    # répond à « le tuyau porte-t-il un tool_calls structuré jusqu'à notre
    # lecteur ? », pas à « le modèle s'en sert-il ? ». Confondre les deux, c'est
    # lire une absence d'appel comme une panne de transport, ou l'inverse.
    charge: dict[str, Any] = {
        "model": MODELE_VLLM,
        "messages": _scene(question),
        "stream": False,
        "temperature": 0.0,
        "max_tokens": JETONS_COURTS,
        "tools": [SEARCH_TOOL],
        "tool_choice": "required",
    }
    code, corps, ecoule = _poster(VLLM, "/v1/chat/completions", charge)
    message = _lire_openai(corps)
    resultats["controle_positif_transport"] = {
        "serveur": "vllm",
        "tool_choice": "required",
        "code_http": code,
        "secondes": round(ecoule, 2),
        "extract_tool_query": extract_tool_query(message),
        "tool_calls_bruts": message.get("tool_calls"),
        "erreur": corps.get("message") if code >= 400 else None,
    }

    for serveur, base, chemin, modele in (
        ("vllm", VLLM, "/v1/chat/completions", MODELE_VLLM),
        ("ollama", OLLAMA, "/api/chat", MODELE_OLLAMA),
    ):
        # `None` = scène d'injonction : le prompt système de production, plus un
        # message utilisateur qui lève la pince règle 4 / règle 5.
        for aiguillon in (False, True, None):
            for natif in (True, False):
                messages = (
                    _scene_injonction()
                    if aiguillon is None
                    else _scene(question, aiguillon=aiguillon)
                )
                charge = {
                    "model": modele,
                    "messages": messages,
                    "stream": False,
                }
                if serveur == "vllm":
                    charge["max_tokens"] = JETONS_COURTS
                    charge["temperature"] = 0.0
                else:
                    charge["think"] = False
                    charge["options"] = {"temperature": 0.0, "num_predict": JETONS_COURTS}
                # NATIVE_TOOL_CALLING allumé = l'outil est DÉCLARÉ. Éteint = il
                # ne l'est pas — mais `prompts/system.txt` le décrit quand même,
                # dans les DEUX positions : ce n'est pas l'interrupteur qui le
                # décrit, et le repli par prose de `graph.py:315` reste armé
                # dans les deux aussi.
                if natif:
                    charge["tools"] = [SEARCH_TOOL]

                code, corps, ecoule = _poster(base, chemin, charge)
                message = _lire_openai(corps) if serveur == "vllm" else (corps.get("message") or {})
                texte = message.get("content") or ""
                fuite = re.search(MOTIF_REPLI, texte)
                resultats["cellules"].append(
                    {
                        "serveur": serveur,
                        "scene": "injonction"
                        if aiguillon is None
                        else ("aiguillon" if aiguillon else "nue"),
                        "native_tool_calling": natif,
                        "code_http": code,
                        "secondes": round(ecoule, 2),
                        # LA preuve : le lecteur de production a-t-il vu l'appel ?
                        "extract_tool_query": extract_tool_query(message),
                        "tool_calls_bruts": message.get("tool_calls"),
                        "finish_reason": ((corps.get("choices") or [{}])[0]).get("finish_reason")
                        if serveur == "vllm"
                        else corps.get("done_reason"),
                        "repli_prose_attrape": fuite.group(1) if fuite else None,
                        "contenu": texte[:600],
                        "contenu_longueur": len(texte),
                    }
                )
    return resultats


# --------------------------------------------------------------------------
# Sonde 2 — les arguments arrivent-ils typés ?
# --------------------------------------------------------------------------
def sonde_arguments() -> dict[str, Any]:
    # Scène d'injonction : la seule mesurée qui produise réellement un appel sur
    # les deux moteurs. Sur la scène nue, il n'y a aucun appel à typer — et une
    # sonde qui lit le type d'un appel absent rend « aucun problème ».
    cellules = []
    for serveur, base, chemin, modele in (
        ("vllm", VLLM, "/v1/chat/completions", MODELE_VLLM),
        ("ollama", OLLAMA, "/api/chat", MODELE_OLLAMA),
    ):
        charge: dict[str, Any] = {
            "model": modele,
            "messages": _scene_injonction(),
            "stream": False,
            "tools": [SEARCH_TOOL],
        }
        if serveur == "vllm":
            charge["max_tokens"] = JETONS_COURTS
            charge["temperature"] = 0.0
        else:
            charge["think"] = False
            charge["options"] = {"temperature": 0.0, "num_predict": JETONS_COURTS}
        code, corps, _ = _poster(base, chemin, charge)
        message = _lire_openai(corps) if serveur == "vllm" else (corps.get("message") or {})
        observes = []
        for appel in message.get("tool_calls") or []:
            arguments = (appel.get("function") or {}).get("arguments")
            observes.append(
                {
                    "type_python": type(arguments).__name__,
                    "brut": arguments if isinstance(arguments, str) else json.dumps(arguments),
                    "cle_id_presente": "id" in appel,
                    "cle_type_presente": "type" in appel,
                }
            )
        cellules.append(
            {
                "serveur": serveur,
                "code_http": code,
                "arguments_observes": observes,
                # La question n'est pas « quel type », c'est « notre :847
                # suffirait-il tel quel ». Le lecteur de production répond.
                "lu_par_la_production": extract_tool_query(message),
            }
        )
    return {"cellules": cellules}


# --------------------------------------------------------------------------
# Sonde 3 — la substitution silencieuse.
# --------------------------------------------------------------------------
def sonde_substitution() -> dict[str, Any]:
    """Éprouvée depuis un MESSAGE UTILISATEUR, jamais en attaquant le validateur.

    Notre outil n'a qu'une propriété, `query`, libre : aucune énumération, donc
    pas la surface du voisin. Mais le prompt en porte une autre, et elle est
    plus large : les `element_id` des sources. Le modèle les lit dans le
    contexte, ils sont « les valeurs autorisées », et la règle 1 du système lui
    ORDONNE d'en citer un à chaque affirmation.
    """
    ids_legaux = {eid for eid, _ in SOURCES}
    cas = [
        (
            "hors_corpus",
            # Aucune des trois sources ne parle de cela. La règle 4 prescrit de
            # le dire ; la règle 1 pousse à citer. C'est la pince.
            "Quel est le montant de l'indemnité journalière versée pendant le congé "
            "de paternité, en euros ?",
        ),
        (
            "premisse_fausse",
            # Le congé de paternité est à 25 jours dans les sources. La question
            # en affirme 40 : une valeur impossible, posée comme acquise.
            "Les sources indiquent 40 jours de congé de paternité : confirme cette "
            "durée et dis depuis quelle année elle s'applique.",
        ),
    ]
    cellules = []
    for serveur, base, chemin, modele in (
        ("vllm", VLLM, "/v1/chat/completions", MODELE_VLLM),
        ("ollama", OLLAMA, "/api/chat", MODELE_OLLAMA),
    ):
        for nom, question in cas:
            charge: dict[str, Any] = {
                "model": modele,
                "messages": _scene(question),
                "stream": False,
                "tools": [SEARCH_TOOL],
            }
            if serveur == "vllm":
                charge["max_tokens"] = 200
                charge["temperature"] = 0.0
            else:
                charge["think"] = False
                charge["options"] = {"temperature": 0.0, "num_predict": 200}
            code, corps, _ = _poster(base, chemin, charge)
            message = _lire_openai(corps) if serveur == "vllm" else (corps.get("message") or {})
            texte = message.get("content") or ""
            cites = set(re.findall(r"\[src:([a-f0-9]{10})\]", texte))
            cellules.append(
                {
                    "serveur": serveur,
                    "cas": nom,
                    "code_http": code,
                    "ids_cites": sorted(cites),
                    # Un id cité qui n'existe pas : le modèle a INVENTÉ une
                    # valeur de la bonne forme.
                    "ids_inventes": sorted(cites - ids_legaux),
                    # Un id légal apposé à une affirmation que la source ne
                    # porte pas : la substitution silencieuse proprement dite.
                    # Le banc la RAPPORTE, il ne la juge pas — c'est une
                    # lecture humaine.
                    "ids_legaux_cites": sorted(cites & ids_legaux),
                    "a_appele_l_outil": extract_tool_query(message),
                    "contenu": texte[:800],
                }
            )
    return {"ids_legaux": sorted(ids_legaux), "cellules": cellules}


# --------------------------------------------------------------------------
# Sonde 4 — éteindre le raisonnement PAR REQUÊTE. Le verrou.
# --------------------------------------------------------------------------
def sonde_raisonnement() -> dict[str, Any]:
    """Cherche un levier PAR REQUÊTE. Aucun drapeau de lancement n'est touché."""
    # Ce que le gabarit de conversation du modèle fait d'un message, SANS
    # générer un seul jeton : /tokenize applique le chat template.
    rendus = {}
    for etiquette, extra in (
        ("nu", {}),
        ("thinking_false", {"chat_template_kwargs": {"thinking": False}}),
        ("enable_thinking_false", {"chat_template_kwargs": {"enable_thinking": False}}),
        ("reasoning_effort_none", {"reasoning_effort": "none"}),
        ("reasoning_effort_low", {"reasoning_effort": "low"}),
    ):
        charge: dict[str, Any] = {
            "model": MODELE_VLLM,
            "messages": [{"role": "user", "content": "Bonjour"}],
            "add_generation_prompt": True,
            "return_token_strs": True,
            **extra,
        }
        code, corps, _ = _poster(VLLM, "/tokenize", charge)
        rendus[etiquette] = {
            "code_http": code,
            "count": corps.get("count"),
            "token_strs": (corps.get("token_strs") or [])[:40],
            "erreur": corps.get("message") or corps.get("error"),
        }

    # Les deux appels de production qui veulent `think=False` EN DUR, avec
    # leurs VRAIS gabarits. C'est là que le coût se paie s'il se paie.
    appels = {
        "reecriture": (
            _gabarit(
                "rewrite_query.j2",
                chat_history=[
                    {"role": "user", "content": "Parle-moi du congé de paternité."},
                    {"role": "assistant", "content": "Il est de 25 jours calendaires."},
                ],
                question="Et pour les femmes ?",
            ),
            120,
        ),
        "traduction": (_gabarit("translate_query.j2", question="Et pour les femmes ?"), 150),
    }

    mesures = []
    for nom, (prompt, num_predict) in appels.items():
        # vLLM : sans levier, puis avec chaque levier que /tokenize a accepté.
        for etiquette, extra in (
            ("vllm_nu", {}),
            ("vllm_thinking_false", {"chat_template_kwargs": {"thinking": False}}),
            ("vllm_enable_thinking_false", {"chat_template_kwargs": {"enable_thinking": False}}),
            ("vllm_reasoning_effort_none", {"reasoning_effort": "none"}),
        ):
            charge = {
                "model": MODELE_VLLM,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "temperature": 0.0,
                "max_tokens": num_predict,
                **extra,
            }
            code, corps, ecoule = _poster(VLLM, "/v1/chat/completions", charge)
            message = _lire_openai(corps)
            texte = message.get("content") or ""
            usage = corps.get("usage") or {}
            mesures.append(
                {
                    "appel": nom,
                    "levier": etiquette,
                    "code_http": code,
                    "secondes": round(ecoule, 2),
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "finish_reason": ((corps.get("choices") or [{}])[0]).get("finish_reason"),
                    # Sans --reasoning-parser côté serveur, un raisonnement ne
                    # part PAS dans un champ à lui : il sort dans `content`.
                    "reasoning": message.get("reasoning"),
                    "contenu": texte[:700],
                    "contenu_longueur": len(texte),
                    "erreur": corps.get("message") if code >= 400 else None,
                }
            )
        # Ollama, même appel, `think=False` comme en production : la base.
        charge_ollama = {
            "model": MODELE_OLLAMA,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": False,
            "options": {"temperature": 0.0, "num_predict": num_predict},
        }
        code, corps, ecoule = _poster(OLLAMA, "/api/chat", charge_ollama)
        texte = (corps.get("message") or {}).get("content") or ""
        mesures.append(
            {
                "appel": nom,
                "levier": "ollama_think_false",
                "code_http": code,
                "secondes": round(ecoule, 2),
                "prompt_tokens": corps.get("prompt_eval_count"),
                "completion_tokens": corps.get("eval_count"),
                "finish_reason": corps.get("done_reason"),
                "reasoning": (corps.get("message") or {}).get("thinking"),
                "contenu": texte[:700],
                "contenu_longueur": len(texte),
                "erreur": None,
            }
        )

    # Une génération plus longue, pour voir si le raisonnement dévore le budget
    # quand on lui en laisse. JETONS_RAISONNEMENT reste court à l'échelle d'un
    # raisonnement : c'est l'intérêt, on veut savoir s'il le remplit.
    charge = {
        "model": MODELE_VLLM,
        "messages": _scene(
            "Compare la durée du congé de paternité et celle du congé de maternité."
        ),
        "stream": False,
        "temperature": 0.0,
        "max_tokens": JETONS_RAISONNEMENT,
    }
    code, corps, ecoule = _poster(VLLM, "/v1/chat/completions", charge)
    message = _lire_openai(corps)
    budget = {
        "code_http": code,
        "secondes": round(ecoule, 2),
        "usage": corps.get("usage"),
        "finish_reason": ((corps.get("choices") or [{}])[0]).get("finish_reason"),
        "reasoning": message.get("reasoning"),
        "contenu": (message.get("content") or "")[:1200],
    }
    return {"gabarit_rendu": rendus, "mesures": mesures, "budget_genereux": budget}


# --------------------------------------------------------------------------
# Sonde 5 — la forme réelle du flux, et le temps au premier jeton.
# --------------------------------------------------------------------------
def sonde_flux(repetitions: int = 3) -> dict[str, Any]:
    question = "Résume en une phrase la durée du congé de paternité."
    formes = {}
    ttft: dict[str, list[float]] = {"vllm": [], "ollama": []}

    for i in range(repetitions):
        charge_vllm = {
            "model": MODELE_VLLM,
            "messages": _scene(question),
            "stream": True,
            "temperature": 0.0,
            "max_tokens": JETONS_COURTS,
            "tools": [SEARCH_TOOL],
        }
        mesure = _flux(VLLM, "/v1/chat/completions", charge_vllm)
        if i == 0:
            formes["vllm"] = mesure
        if mesure["ttft_s"] is not None:
            ttft["vllm"].append(mesure["ttft_s"])

        charge_ollama = {
            "model": MODELE_OLLAMA,
            "messages": _scene(question),
            "stream": True,
            "think": False,
            "options": {"temperature": 0.0, "num_predict": JETONS_COURTS},
            "tools": [SEARCH_TOOL],
        }
        mesure = _flux(OLLAMA, "/api/chat", charge_ollama)
        if i == 0:
            formes["ollama"] = mesure
        if mesure["ttft_s"] is not None:
            ttft["ollama"].append(mesure["ttft_s"])

    # Ce que `aiter_lines()` + `json.loads(ligne)` — notre lecteur de
    # `llm.py:980-983` — ferait des lignes réellement reçues. On ne le déduit
    # pas : on le lui donne à manger.
    verdict_lecteur = {}
    for serveur, mesure in formes.items():
        essais = []
        for ligne in mesure["lignes_brutes"]:
            if not ligne.strip():
                continue
            try:
                data = json.loads(ligne)
            except json.JSONDecodeError as erreur:
                essais.append({"ligne": ligne[:120], "issue": f"JSONDecodeError: {erreur.msg}"})
                continue
            essais.append(
                {
                    "ligne": ligne[:120],
                    "issue": "json.loads OK",
                    "message_content": (data.get("message") or {}).get("content"),
                }
            )
        verdict_lecteur[serveur] = essais

    return {
        "formes": formes,
        "ttft_s": ttft,
        "ttft_moyen_s": {k: (round(sum(v) / len(v), 3) if v else None) for k, v in ttft.items()},
        "notre_lecteur_actuel": verdict_lecteur,
    }


SONDES = {
    "outil": sonde_outil,
    "arguments": sonde_arguments,
    "substitution": sonde_substitution,
    "raisonnement": sonde_raisonnement,
    "flux": sonde_flux,
}


def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--sonde", default="tout", choices=[*SONDES, "tout"])
    analyseur.add_argument("--journal", default=None, help="Fichier JSONL de sortie.")
    arguments = analyseur.parse_args()

    noms = list(SONDES) if arguments.sonde == "tout" else [arguments.sonde]
    sortie: dict[str, Any] = {"sondes": {}}
    for nom in noms:
        print(f"--- sonde {nom}", file=sys.stderr, flush=True)
        sortie["sondes"][nom] = SONDES[nom]()

    sortie["requetes_envoyees"] = {
        "par_serveur": COMPTEUR.par_serveur,
        "total": COMPTEUR.total,
    }
    rendu = json.dumps(sortie, ensure_ascii=False, indent=2)
    print(rendu)
    if arguments.journal:
        Path(arguments.journal).write_text(rendu, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

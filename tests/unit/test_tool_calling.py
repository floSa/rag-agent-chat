"""Détection d'une demande de recherche supplémentaire par le modèle.

Deux canaux : l'appel d'outil natif d'Ollama — structuré, donc sans ambiguïté —
et, pour les modèles qui n'en font pas, le repérage de `search_vectors("…")`
dans la prose. Le second est fragile : le modèle doit produire la syntaxe
exacte, et ses tokens sont déjà partis à l'écran avant qu'on les retire.
"""

from src.agent.llm import extract_tool_query


def _call(name: str, arguments) -> dict:
    return {"tool_calls": [{"function": {"name": name, "arguments": arguments}}]}


def test_appel_natif_avec_arguments_objet() -> None:
    assert extract_tool_query(_call("search_vectors", {"query": "écart-type"})) == "écart-type"


def test_appel_natif_avec_arguments_en_chaine_json() -> None:
    """Ollama rend un objet ; certains modèles rendent une chaîne JSON."""
    assert extract_tool_query(_call("search_vectors", '{"query": "dispersion"}')) == "dispersion"


def test_json_invalide_ignore() -> None:
    assert extract_tool_query(_call("search_vectors", "{pas du json")) is None


def test_autre_outil_ignore() -> None:
    assert extract_tool_query(_call("delete_everything", {"query": "tout"})) is None


def test_requete_vide_ignoree() -> None:
    assert extract_tool_query(_call("search_vectors", {"query": "   "})) is None


def test_requete_absente_ignoree() -> None:
    assert extract_tool_query(_call("search_vectors", {})) is None


def test_message_sans_appel_d_outil() -> None:
    assert extract_tool_query({"content": "Voici la réponse."}) is None


def test_message_vide() -> None:
    assert extract_tool_query({}) is None


def test_requete_rognee() -> None:
    assert extract_tool_query(_call("search_vectors", {"query": "  sujet  "})) == "sujet"

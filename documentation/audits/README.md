# Audits — documents datés, versés après mesure

Chaque fichier de ce répertoire est le rapport d'un audit indépendant, rendu à
une date, sur un état du dépôt à cette date. Ils ne sont pas tenus à jour : leur
valeur est d'être **le compte rendu de ce qui a été mesuré ce jour-là**.

> ## CES DOCUMENTS DÉCRIVENT UN ÉTAT ANTÉRIEUR, ET ILS NE SONT PAS RÉÉCRITS
>
> **Le moteur LLM servi est vLLM depuis le 17 septembre 2026**, et le lot 28
> (18 septembre 2026) a retiré du code le support de l'autre moteur — pas
> seulement son nom.
>
> Les documents de ce répertoire le nomment encore, et **c'est délibéré**. Ce
> sont des documents datés, signés, versés après mesure : les réécrire pour
> qu'ils s'accordent avec l'état d'aujourd'hui **falsifierait un rapport**. Un
> rapport dit ce qui a été mesuré le jour où il a été mesuré, ou il ne dit rien.
>
> C'est aussi pourquoi ce répertoire est nommé, avec sa raison, dans le périmètre
> d'exclusion du garde `test_le_nom_de_l_ancien_moteur_ne_revient_pas` — qui
> mord, lui, partout où le nom décrirait le fonctionnement actuel.
>
> **Ce qui décrit le fonctionnement actuel** vit dans
> [`../moteur_llm.md`](../moteur_llm.md), et se relit par `GET /health`.

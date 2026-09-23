# Référence de la troncature du graphe, avant la bascule du stockage objet

`mesuré` le **23 septembre 2026 à 08:53–08:58 UTC**, contre le graphe et
ChromaDB en service, base `main` = `46be5a8`, code servi `ba6a8f0`.

POURQUOI CE FICHIER EXISTE. Le pipeline réingérera tout le corpus. Les comptes
ci-dessous ne valent que comme **point de départ** : si après la réingestion les
sept amputés deviennent zéro, le découpage a changé ; s'ils deviennent trente,
aussi. **Sans l'état d'avant, l'après ne se lit pas.** Même motif que
`2026-09-22-cles-medias.md`.

LA DÉFINITION DU COMPTE DE SOMMETS, ÉCRITE UNE FOIS POUR TOUTES. Deux chiffres
circulaient — **15 196** de notre voisin, **15 173** de nous — et l'écart de
**23** vaut exactement le nombre de `Document`. Réconcilié : `sommets_tous_tags`
compte **tous** les tags de `SHOW TAGS`, `sommets_sans_Document` en retire le tag
`Document`. **Citer l'un pour l'autre est une dispute à retardement.**

CE QUE CE FICHIER NE DIT PAS. Il ne dit **pas** où la matière est passée pour les
sept amputés : le texte que le **document source** produit réellement n'est
mesuré ni ici ni ailleurs, et tant qu'il ne l'est pas, « le texte entier » n'a
pas de référent. Le pipeline le mesure de son côté.

ET UNE LEÇON DE MÉTHODE, PAYÉE ICI. Le premier relevé énumérait une liste de tags
**écrite à la main**, qui inventait `Text` et `Title` — inexistants — et oubliait
`PageHeader`, `PageFooter` et `Document`. Il est tombé juste **par chance** : les
oubliés valaient zéro, sauf `Document`. Le relevé ci-dessous lit `SHOW TAGS`.
**Une liste en dur ne se trompe pas bruyamment, elle se trompe en silence.**

```json
{
  "tags_du_schema": [
    "Caption",
    "Code",
    "Document",
    "Footnote",
    "Formula",
    "ListItem",
    "PageFooter",
    "PageHeader",
    "Paragraph",
    "Picture",
    "SectionHeader",
    "Table"
  ],
  "sommets_par_tag": {
    "Caption": 201,
    "Code": 4963,
    "Document": 23,
    "Footnote": 0,
    "Formula": 0,
    "ListItem": 1748,
    "PageFooter": 0,
    "PageHeader": 0,
    "Paragraph": 7251,
    "Picture": 209,
    "SectionHeader": 746,
    "Table": 55
  },
  "sommets_tous_tags": 15196,
  "sommets_sans_Document": 15173,
  "plafond_de_troncature": 2000,
  "tronques_par_tag": {
    "Paragraph": 4,
    "Table": 14
  },
  "tronques_total": 18,
  "rallonges_par_les_vecteurs": 11,
  "restent_amputes": 7,
  "ids_restent_amputes": [
    "0d5e8808ae",
    "0e50891a03",
    "489b7da6ec",
    "a32675b5c6",
    "bf408a09bb",
    "e29c354d09",
    "f4c2943b70"
  ],
  "longueur_rendue_par_les_vecteurs": {
    "0d5e8808ae": 1776,
    "0e50891a03": 1150,
    "489b7da6ec": 1363,
    "a32675b5c6": 1875,
    "bf408a09bb": 1801,
    "e29c354d09": 1266,
    "f4c2943b70": 1540
  }
}
```

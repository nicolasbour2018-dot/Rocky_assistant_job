# Rapprochement TheirStack

TheirStack est utilisé uniquement lors d'une action volontaire sur une annonce
Rocky marquée `INCOMPLÈTE`. Il n'est pas enregistré comme source de collecte.

Rocky appelle l'endpoint officiel `POST /v1/jobs/search` avec le nom exact de
l'entreprise, l'intitulé et une limite de trois résultats afin de borner la
consommation de crédits. Le contrat est documenté dans la
[référence Job Search](https://theirstack.com/en/docs/api-reference/jobs/search_jobs_v1).

Un résultat doit dépasser les seuils de similarité du titre et de l'entreprise,
puis être corroboré par une URL identique, une date proche ou une localisation
compatible. La description n'est retenue que si elle est non tronquée et
nettement plus longue que l'aperçu Rocky. L'identifiant Rocky et la provenance
de collecte sont conservés ; seuls `description_enrichment_source=TheirStack`
et l'identifiant TheirStack du résultat décrivent l'enrichissement.

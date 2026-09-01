# 0013 – Ordre de migration et stratégie de tests

Date : 2026-09-01. Statut : acceptée.

## Contexte

Les phases 1 et 2 (CI verte, outillage) restent devant (0001). Alternatives
pesées : données d'abord sous Streamlit (les pages sont adaptées deux fois) ;
documents d'abord (petit lot, mais le gros reste).

Tests : 27 fichiers, hors ligne, 20 sur SQLite. L'UI est peu couverte
(6 fichiers importent Streamlit).

## Décision

1. Squelette complet mais vide : `src/rocky/` avec la configuration, la
   `Base` ORM et la migration Alembic initiale, l'app FastAPI avec l'auth et
   le layout Pico, la CLI, les plists.
2. Une fonctionnalité à la fois, en entier : domaine, cas d'usage,
   adaptateur, page. La page Streamlit correspondante est supprimée dans le
   même lot.

Le code n'est pas déplacé, il est réécrit dans les couches cibles. La suite
de tests existante sert de spécification et se porte avec la fonctionnalité.
Une fonctionnalité sans tests en reçoit avant sa réécriture.

Tests : pytest hors ligne, SQLite sous `tmp_path`, doublures pour Mistral,
Gmail et HTTP. Couverture cliquet en CI (`pytest-cov`), seuil posé au niveau
mesuré, qui bloque une régression sans rien exiger de l'existant.

Idées notées, non planifiées : `hypothesis` sur le matching et le parsing,
trois parcours Playwright de bout en bout, `respx`. Le projet s'industrialise
sans se compliquer ; ces étages viendront si un besoin réel les appelle.

## Conséquences

- Ordre suggéré des fonctionnalités : auth et cockpit (valide le squelette),
  offres et veille, profils et documents, candidatures et préremplissage,
  email, monitoring, ATS, assistant.
- Fin de transition = suppression de `dashboard/` et de `streamlit`.
- Questions ouvertes pour Nicolas : le banc ATS à quatre extracteurs PDF
  (isolé dans un adaptateur avec imports paresseux en attendant) ; le CV
  Canva, à reproduire ou à redessiner (0009).

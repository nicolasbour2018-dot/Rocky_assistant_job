"""Détection déterministe des compétences dans les annonces.

Ce module fournit le vocabulaire et les règles locales utilisés pendant
l'import, l'enrichissement et le matching. Il ne fait appel ni à un LLM ni à
une API : le résultat est explicable et réutilisable dans les analyses.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any
                            #################################################################################################
                                # Module de détection des compétences dans les annonces d'emploi.
                                # Intègre des dictionnaires de compétences déterminées.
                                # Extrait, normalise et classe les compétences déterminées détectées dans les annonces.
                            #################################################################################################



#################################################################################################
# Bloc de dictionnaires de compétences déterminées.
#################################################################################################

# Les clés correspondent au nom normalisé enregistré dans la base.
# Les valeurs correspondent aux différentes formulations possibles.

SKILL_ALIASES = {
    # Langages
    "Python": ["python"],
    "SQL": ["sql", "requêtes sql", "requete sql", "requêtage sql", "SQL", "requêtes SQL", "requete SQL", "requêtage SQL"],
    "R": ["langage r", "programmation r", "r studio", "rstudio"],
    "JavaScript": ["javascript", "java script"],
    "TypeScript": ["typescript", "type script"],
    "Java": ["java"],
    "Scala": ["scala"],
    "Bash": ["bash", "shell scripting", "shell script"],
    "Google Apps Script": ["google apps script", "google app script", "google appscript", "apps script", "appscript", "développement en google apps script", "developpement en google apps script", "développer en google apps script", "developper en google apps script"],
    "Google Workspace": ["google workspace", "suite google workspace", "google suite", "g suite"],
    "AppSheet": ["appsheet", "app sheet", "google appsheet"],
    "Low-code / No-code": ["low-code", "low code", "no-code", "no code", "solutions low-code", "solutions low code", "applications low-code", "applications low code", "développement low-code", "developpement low code", "développement no-code", "developpement no code", "solutions no-code", "solutions no code", "applications no-code", "applications no code"],
    "Matomo": ["matomo", "matomo analytics"],

    # Analyse et manipulation de données
    "Pandas": ["pandas"],
    "NumPy": ["numpy"],
    "Polars": ["polars"],
    "Excel": ["excel", "microsoft excel", "tableur excel"],
    "Power Query": ["power query"],
    "VBA": ["vba", "visual basic for applications"],

    # Visualisation et BI
    "Power BI": ["power bi", "powerbi"],
    "Tableau": ["tableau software", "tableau desktop", "tableau prep"],
    "Looker": ["looker", "looker studio", "google data studio"],
    "Matplotlib": ["matplotlib"],
    "Seaborn": ["seaborn"],
    "Plotly": ["plotly"],
    "Streamlit": ["streamlit"],
    "LangChain": ["langchain", "lang chain"],
    "n8n": ["n8n"],

    # Machine learning et IA
    "Machine Learning": ["machine learning", "apprentissage automatique"],
    "Deep Learning": ["deep learning", "apprentissage profond"],
    "Scikit-learn": ["scikit-learn", "scikit learn", "sklearn", "scikit"],
    "TensorFlow": ["tensorflow", "tensor flow", "tf"],
    "PyTorch": ["pytorch", "py torch"],
    "NLP": ["nlp", "traitement automatique du langage", "traitement du langage naturel", "traitement automatique du langage naturel"],
    "LLM": ["llm", "large language model", "large language models", "modèle de langage", "modeles de langage"],
    "RAG": ["rag", "RAG","retrieval augmented generation"],
    "Computer Vision": ["computer vision", "vision par ordinateur"],
    "Modélisation statistique": ["modélisation statistique", "modelisation statistique", "modèles statistiques", "modeles statistiques"],
    "Analyse prédictive": ["analyse prédictive", "analyse predictive", "modélisation prédictive", "modelisation predictive", "modèles prédictifs", "modeles predictifs"],

    # Bases de données
    "PostgreSQL": ["postgresql", "postgres", "postgre sql", "postgre"],
    "MySQL": ["mysql"],
    "SQLite": ["sqlite"],
    "MongoDB": ["mongodb", "mongo db"],
    "BigQuery": ["bigquery", "big query", "google bigquery", "google big query"],
    "Snowflake": ["snowflake"],
    "Redshift": ["redshift", "amazon redshift"],
    "SQL Server": ["sql server", "microsoft sql server"],
    "Gestion des données": ["gestion des données", "gestion de données", "data management", "administration des données", "administration de données"],
    "Structuration des données": ["structuration des données", "structuration de données", "organiser les données", "organisation des données", "organisation de données"],
    "Conception de bases de données": ["conception de bases de données", "conception de base de données", "concevoir une base de données", "concevoir des bases de données", "database design", "modélisation de bases de données", "modelisation de bases de donnees"],

    # Data engineering
    "ETL / ELT": ["etl", "elt", "pipeline de données", "pipelines de données", "pipeline data", "pipelines data"],
    "Airflow": ["airflow", "apache airflow"],
    "dbt": ["dbt", "data build tool"],
    "Spark": ["spark", "apache spark", "pyspark"],
    "Kafka": ["kafka", "apache kafka"],
    "Databricks": ["databricks"],
    "Automatisation": ["automatisation", "automatisations", "automatiser", "solution automatisée", "solution automatisee", "solutions automatisées", "solutions automatisees", "automatisation des processus", "automatisation de processus", "automatisation des tâches", "automatisation des taches"],
    "Cartographie des données": ["cartographie des données", "cartographie de données", "data mapping", "cartographier les données", "cartographier des données"],
    "Règles de gestion": ["règles de gestion", "regles de gestion", "définition des règles de gestion", "definition des regles de gestion", "formalisation des règles de gestion", "formalisation des regles de gestion", "business rules"],

    # Cloud et déploiement
    "AWS": ["aws", "AWS","amazon web services"],
    "Azure": ["microsoft azure", "azure"],
    "GCP": ["gcp", "GCP", "google cloud", "google cloud platform"],
    "Docker": ["docker", "Docker","conteneur docker", "conteneurs docker"],
    "Kubernetes": ["kubernetes", "K8s", "k8s"],
    "FastAPI": ["fastapi", "FastAPI", "fast api"],
    "Flask": ["flask", "Flask"],
    "API REST": ["api rest","API REST", "rest api", "api restful", "restful api", "api restfull", "API RESTFULL"],
    "MLOps": ["mlops", "ml ops", "mlo ps", "ml ops", "machine learning operations", "machine learning ops", "opérations de machine learning", "operations de machine learning"],
    "CI/CD": ["ci/cd", "ci cd", "intégration continue", "integration continue", "déploiement continu", "deploiement continu"],

    # Développement et organisation
    "Git": ["git"],
    "GitHub": ["github"],
    "GitLab": ["gitlab"],
    "Jupyter": ["jupyter", "jupyter notebook", "jupyterlab"],
    "VS Code": ["visual studio code", "vs code", "vscode", "vs code editor", "vscode editor", "VS code"],
    "Agile": ["méthode agile", "methodologie agile", "méthodologie agile", "scrum", "kanban", "agile", "AGILE"],
    "Documentation technique": ["documentation technique", "documentations techniques", "rédaction de documentation technique", "redaction de documentation technique", "rédiger une documentation technique", "rediger une documentation technique", "documenter les solutions", "documentation des solutions"],

    # Compétences data et métier
    "Data Visualisation": ["data visualisation", "data visualization", "visualisation de données", "visualisation des données", "visualisation de donnees", "visualisation des donnees"],
    "Data Cleaning": ["data cleaning", "nettoyage de données", "nettoyage des données", "préparation des données", "preparation des donnees", "nettoyer les données", "nettoyer des données", "nettoyage et préparation des données", "nettoyage et preparation des donnees", "nettoyage et préparation de données", "nettoyage et preparation de donnees"],
    "Data Quality": ["data quality", "qualité des données", "qualite des donnees"],
    "Data Governance": ["data governance", "gouvernance des données", "gouvernance de données"],
    "Data Warehousing": ["data warehouse", "data warehousing", "entrepôt de données", "entrepot de donnees"],
    "Reporting": ["reporting", "Reporting","création de rapports", "creation de rapports", "rapports"],
    "Dashboarding": ["dashboarding", "création de dashboards", "creation de dashboards", "création de tableaux de bord", "tableaux de bord", "tableaux de bord interactifs", "tableaux de bord interactifs", "dashboards interactifs", "dashboards interactifs", "dashboard dynamique", "tableau de bord dynamique", "tableaux de bords dynamiques","tableau de bord interactif", "dashboard interactif", "dashboards dynamiques"],
    "Analyse statistique": ["analyse statistique", "analyses statistiques", "statistiques descriptives", "statistiques inférentielles", "statistiques exploratoires", "statistiques multivariées"],
    "A/B Testing": ["a/b test", "a b test", "test a/b", "tests a/b", "test ab", "tests ab", "test a b", "tests a b", "expérimentation", "experimentation"],
    "KPI": ["kpi", "indicateurs clés de performance", "indicateurs cles de performance", "indicateurs de performance", "indicateurs de performance clés", "indicateurs de performance", "indicateurs de performance clés", "suivi des indicateurs clés de performance", "suivi des indicateurs", "indicateurs de suivi"],
    # L'abréviation isolée "BI" est volontairement exclue : elle faisait
    # compter "Power BI" une seconde fois comme "Business Intelligence".
    "Business Intelligence": [
        "business intelligence",
        "informatique décisionnelle",
        "informatique decisionnelle",
    ],

    # Compétences transversales
    "Communication": ["excellentes capacités de communication", "bonne communication", "aisance relationnelle", "communication écrite et orale", "communication ecrite et orale"],
    "Travail en équipe": ["travail en équipe", "travail en equipe", "travailler en équipe", "travailler en equipe", "esprit d'équipe", "esprit d equipe", "collaboration avec les équipes", "collaboration avec les equipes", "capacité à travailler en équipe", "capacite a travailler en equipe", "capacité à collaborer avec les équipes", "capacite a collaborer avec les equipes"],
    "Autonomie": ["autonomie", "autonome"],
    "Rigueur": ["rigueur", "rigoureux", "rigoureuse"],
    "Curiosité": ["curiosité", "curiosite", "curieux", "curieuse"],
    "Esprit analytique": ["esprit analytique", "capacité d'analyse", "capacite d analyse", "capacités d'analyse", "capacites d analyse"],
    "Résolution de problèmes": ["résolution de problèmes", "resolution de problemes", "problem solving"],
    "Pédagogie": ["pédagogie", "pedagogie", "pédagogue", "pedagogue", "vulgarisation", "vulgariser", "capacité à vulgariser", "capacite a vulgariser", "capacité à vulgariser des résultats complexes", "capacite a vulgariser des resultats complexes", "capacité à vulgariser des resultats complexes", "capacite a vulgariser des résultats complexes"],
    "Force de proposition": ["force de proposition", "être force de proposition", "etre force de proposition", "proactif", "proactive", "proactivité", "proactivite"],
    "Esprit logique": ["esprit logique", "logique", "raisonnement logique", "capacité de raisonnement", "capacite de raisonnement"],
    "Esprit analytique": ["esprit analytique", "capacité d'analyse", "capacite d analyse", "capacités d'analyse", "capacites d analyse", "capacité d’analyse", "capacités d’analyse", "analyse et synthèse", "analyse et synthese"],
}


TECHNICAL_SKILLS = {
    "Python",
    "SQL",
    "R",
    "JavaScript",
    "TypeScript",
    "Java",
    "Scala",
    "Bash",
    "Pandas",
    "NumPy",
    "Polars",
    "Excel",
    "Power Query",
    "VBA",
    "Power BI",
    "Tableau",
    "Looker",
    "Matplotlib",
    "Seaborn",
    "Plotly",
    "Streamlit",
    "LangChain",
    "n8n",
    "Machine Learning",
    "Deep Learning",
    "Scikit-learn",
    "TensorFlow",
    "PyTorch",
    "NLP",
    "LLM",
    "RAG",
    "Computer Vision",
    "PostgreSQL",
    "MySQL",
    "SQLite",
    "MongoDB",
    "BigQuery",
    "Snowflake",
    "Redshift",
    "SQL Server",
    "ETL / ELT",
    "Airflow",
    "dbt",
    "Spark",
    "Kafka",
    "Databricks",
    "AWS",
    "Azure",
    "GCP",
    "Docker",
    "Kubernetes",
    "FastAPI",
    "Flask",
    "API REST",
    "MLOps",
    "CI/CD",
    "Git",
    "GitHub",
    "GitLab",
    "Jupyter",
    "VS Code",
    "Google Apps Script",
    "Google Workspace",
    "AppSheet",
    "Low-code / No-code",
    "Matomo"
}


BUSINESS_SKILLS = {
    "Data Visualisation",
    "Data Cleaning",
    "Data Quality",
    "Data Governance",
    "Data Warehousing",
    "Reporting",
    "Dashboarding",
    "Analyse statistique",
    "Modélisation statistique",
    "Analyse prédictive",
    "A/B Testing",
    "KPI",
    "Business Intelligence",
    "Agile",
    "Automatisation",
    "Documentation technique",
    "Gestion des données",
    "Structuration des données",
    "Conception de bases de données",
    "Cartographie des données",
    "Règles de gestion"
}


SOFT_SKILLS = {
    "Communication",
    "Travail en équipe",
    "Autonomie",
    "Rigueur",
    "Curiosité",
    "Esprit analytique",
    "Résolution de problèmes",
    "Pédagogie",
    "Force de proposition",
    "Esprit logique",
    "Capacité d'analyse",
}

#################################################################################################
# Bloc de fonctions de normalisation et de recherche des compétences dans les annonces d'emploi.
#################################################################################################

def normalize_text(text: str | None) -> str:
    "Normalise le texte pour faciliter les recherches : minuscules, suppression des accents, espaces normalisés."
    if not text:
        return ""

    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(
        character
        for character in text
        if not unicodedata.combining(character)
    )

    text = text.lower()
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def contains_expression(text: str, expression: str) -> bool:
    """
    Recherche une expression complète dans le texte.

    Les limites évitent notamment de détecter :
    - R dans n'importe quel mot ;
    - Git dans digital ;
    - Java dans JavaScript.
    """
    normalized_expression = normalize_text(expression)

    pattern = (
        r"(?<![a-z0-9])"
        + re.escape(normalized_expression)
        + r"(?![a-z0-9])"
    )

    return re.search(pattern, text) is not None

#################################################################################################
# Bloc de fonction d'extraction et de classification des compétences détectées dans les annonces d'emploi.
#################################################################################################

def extract_skills(title: str | None, description: str | None) -> dict[str, list[str]]:
    """
    Extrait et classe les compétences détectées dans une annonce.
    """
    source_text = normalize_text(
        f"{title or ''} {description or ''}"
    )

    detected_skills: set[str] = set()

    for skill_name, aliases in SKILL_ALIASES.items():
        if any(contains_expression(source_text, alias) for alias in aliases):
            detected_skills.add(skill_name)

    return {
        "technical_skills": sorted(
            detected_skills.intersection(TECHNICAL_SKILLS)
        ),
        "business_skills": sorted(
            detected_skills.intersection(BUSINESS_SKILLS)
        ),
        "soft_skills": sorted(
            detected_skills.intersection(SOFT_SKILLS)
        ),
        "all_skills": sorted(detected_skills),
    }

#################################################################################################
# Bloc de la fonction d'activation de la recherche de compétences dans les annonces.
#################################################################################################

def analyze_job(title: str | None, description: str | None) -> dict[str, Any]:
    "Point d'entrée général de l'analyse d'une annonce."
    skills = extract_skills(
        title=title,
        description=description,
    )

    return {
        "technical_skills": skills["technical_skills"],
        "business_skills": skills["business_skills"],
        "soft_skills": skills["soft_skills"],
        "all_skills": skills["all_skills"],
        "skills_count": len(skills["all_skills"]),
    }

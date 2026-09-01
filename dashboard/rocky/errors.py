"""Exceptions métier affichables proprement dans le dashboard."""


class RockyError(Exception):
    """Erreur attendue et compréhensible par l'utilisateur."""


class ConfigurationError(RockyError):
    """Une configuration ou un credential obligatoire manque."""


class JobImportError(RockyError):
    """Une annonce n'a pas pu être importée."""


class SourceError(RockyError):
    """Une source de veille a retourné une erreur."""


class DocumentError(RockyError):
    """Un document de candidature n'a pas pu être produit."""

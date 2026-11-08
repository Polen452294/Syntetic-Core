class DomainError(Exception):
    status_code = 400


class NotFoundError(DomainError):
    status_code = 404


class ConflictError(DomainError):
    status_code = 409


class ScenarioValidationError(DomainError):
    status_code = 422


class NavigationError(Exception):
    pass


class NavigationTimeout(NavigationError):
    pass


class TemporaryNetworkError(NavigationError):
    pass


class TemporaryTargetUnavailable(NavigationError):
    pass


class ActionTimeoutError(Exception):
    pass


class VisitDurationExceeded(Exception):
    pass


class VisitActionWindowMissed(Exception):
    pass


class VisitLinkNotFound(Exception):
    pass


class SelectorNotFoundError(Exception):
    pass


class BrowserLaunchError(Exception):
    pass


class ProfileLockedError(ConflictError):
    pass


class ProfileValidationError(DomainError):
    pass


class ExternalRedirectError(ProfileValidationError):
    """An incubation page or background request left its verified scope."""


class ProxyIdentityChangedError(ProfileValidationError):
    """A persisted browser identity no longer has its established proxy exit IP."""


class ProxyUnavailableError(BrowserLaunchError):
    pass


class DiagnosticError(Exception):
    pass


class FingerprintDiagnosticError(DiagnosticError):
    pass


class MitmproxyError(DiagnosticError):
    pass


class ScenarioError(Exception):
    pass


class SearchEntryError(ScenarioError):
    pass


class SearchChallengeError(SearchEntryError):
    pass


class SearchTargetNotFound(SearchEntryError):
    pass


class SearchEntryTimeout(SearchEntryError):
    pass


class LeaseLost(Exception):
    pass


class UserCancelled(Exception):
    pass


class TransportUnavailable(Exception):
    pass


class WorkerLost(Exception):
    pass


class DiskSpaceLow(Exception):
    pass


class EgressGatewayDrop(TemporaryNetworkError):
    pass


class DOMElementNotFoundError(Exception):
    pass


class EmptyResponse(Exception):
    pass


class IncubationSitesUnavailable(Exception):
    pass

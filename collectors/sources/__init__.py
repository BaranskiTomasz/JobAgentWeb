from .arbeitnow import ArbeitnowSource, ArbeitnowUKSource
from .ashby import AshbySource
from .greenhouse import GreenhouseSource
from .hackernews import HackerNewsSource
from .himalayas import HimalayasSource
from .jobicy import JobicySource
from .jobscollider import JobsColliderSource
from .justjoin import JustJoinSource
from .lever import LeverSource
from .nofluffjobs import NoFluffJobsSource
from .remoteok import RemoteOKSource
from .remotive import RemotiveSource
from .solidjobs import SolidJobsSource
from .weworkremotely import WWRSource
from .workingnomads import WorkingNomadsSource

_REGISTRY = {
    "arbeitnow": ArbeitnowSource, "arbeitnow_uk": ArbeitnowUKSource,
    "ashby": AshbySource, "greenhouse": GreenhouseSource, "hackernews": HackerNewsSource,
    "himalayas": HimalayasSource, "jobicy": JobicySource, "jobscollider": JobsColliderSource,
    "justjoin": JustJoinSource, "lever": LeverSource, "nofluffjobs": NoFluffJobsSource,
    "remoteok": RemoteOKSource, "remotive": RemotiveSource, "solidjobs": SolidJobsSource,
    "weworkremotely": WWRSource, "workingnomads": WorkingNomadsSource,
}


def make(source_id: str, **kwargs):
    try:
        return _REGISTRY[source_id](**kwargs)
    except KeyError as error:
        raise ValueError(f"Unknown catalog source: {source_id!r}") from error


def available() -> list[str]:
    return list(_REGISTRY)

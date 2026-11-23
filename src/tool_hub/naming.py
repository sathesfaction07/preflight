"""Distribution names against module names, and why the mapping is circular.

`pillow` is what you `pip install`. `PIL` is what you `import`. These are two namespaces, not
two spellings, and a dependency check written against the wrong one does not merely fail
sometimes -- it is UNSATISFIABLE. Verified: Pillow 12.3.0 installed, and
`find_spec("pillow")` still returns None. Installing the package cannot make that check pass.

The obvious fix is to resolve the name from installed metadata, and it works:

    importlib.metadata.distribution("pillow").read_text("top_level.txt") -> "PIL\\n"

But only for a distribution that is ALREADY INSTALLED. For an absent one, `distribution()`
raises `PackageNotFoundError`, so you cannot learn which module name to look for. **The check
needs the answer in order to ask the question.** And `top_level.txt` is a setuptools legacy
file that modern wheels often omit -- absent for 17 of 28 distributions in one venv here,
including Pygments, click and matplotlib.

So the curated table below is not laziness. It is the only thing that works for a package that
is not installed, and it is a guess that goes stale. Both of those are said out loud rather
than implied.
"""

from __future__ import annotations

import importlib.metadata as md
import re

from .models import NameResolution, Namespace, Resolution

#: Distributions whose import name differs from their install name. A guess, curated by hand,
#: and the ONLY source available for a distribution that is not installed. `doctor` reports it
#: as a guess rather than as knowledge.
#:
#: Kept small on purpose: a long table would imply completeness it cannot have. There are tens
#: of thousands of distributions on PyPI and this covers eleven.
KNOWN_DIFFERENT: dict[str, str] = {
    "pillow": "PIL",
    "scikit-learn": "sklearn",
    "beautifulsoup4": "bs4",
    "pyyaml": "yaml",
    "python-dateutil": "dateutil",
    "python-docx": "docx",
    "msgpack-python": "msgpack",
    "opencv-python": "cv2",
    "attrs": "attr",
    "protobuf": "google.protobuf",
    "typing-extensions": "typing_extensions",
}

#: PEP 503 normalisation: runs of -_. collapse to a single -, and case folds.
_NORMALISE = re.compile(r"[-_.]+")


def normalise_distribution(name: str) -> str:
    """PEP 503 normalised form, which is how a distribution name is compared."""
    return _NORMALISE.sub("-", name).lower()


def looks_like_a_module(name: str) -> bool:
    """Could this string be passed to `import` at all?

    A hyphen makes it impossible -- `import python-dateutil` is a syntax error, not a missing
    module. So a hyphenated name in a `find_spec` check is a name that CANNOT resolve, which
    is the sharpest available signal that the wrong namespace was used.
    """
    return all(part.isidentifier() for part in name.split(".")) and bool(name)


def classify(name: str) -> Namespace:
    """Which namespace a written-down name must belong to.

    Only a definite answer is given. A hyphen proves DISTRIBUTION, because no module name can
    contain one. Everything else is UNKNOWN rather than MODULE, because `requests` is both a
    valid distribution name and a valid module name and nothing in the string decides it.
    """
    if not looks_like_a_module(name):
        return Namespace.DISTRIBUTION
    return Namespace.UNKNOWN


def from_metadata(distribution: str) -> str | None:
    """The authoritative module name, if the distribution is installed and says so.

    Two sources, tried in order:
      * `top_level.txt` -- a setuptools legacy file, so often absent
      * the RECORD file -- present for wheels, and read as a fallback

    Returns None when the distribution is absent, which is the circularity: the answer lives
    inside the thing whose presence is in question.
    """
    try:
        dist = md.distribution(distribution)
    except md.PackageNotFoundError:
        return None

    top = dist.read_text("top_level.txt")
    if top:
        for line in top.splitlines():
            candidate = line.strip()
            if candidate and looks_like_a_module(candidate):
                return candidate

    # No top_level.txt. Infer from the installed file list: the shallowest directory holding
    # an __init__.py, or a bare top-level .py module.
    for path in dist.files or ():
        parts = path.parts
        if len(parts) >= 2 and parts[-1] == "__init__.py" and looks_like_a_module(parts[0]):
            return parts[0]
    for path in dist.files or ():
        parts = path.parts
        if len(parts) == 1 and parts[0].endswith(".py"):
            stem = parts[0][:-3]
            if looks_like_a_module(stem):
                return stem
    return None


def resolve(distribution: str) -> NameResolution:
    """What module does this distribution provide, and how confident is that answer?

    The four sources are not equal and the result says which was used, because "we resolved
    it" covers an authoritative read and a hand-written guess and those deserve to be told
    apart.
    """
    from_meta = from_metadata(distribution)
    if from_meta is not None:
        return NameResolution(
            distribution=distribution,
            module=from_meta,
            resolution=Resolution.METADATA,
            detail=(
                "read from the installed distribution's own metadata. Authoritative -- and "
                "only available BECAUSE it is installed, which is the thing the check was "
                "trying to establish"
            ),
        )

    key = normalise_distribution(distribution)
    for candidate, module in KNOWN_DIFFERENT.items():
        if normalise_distribution(candidate) == key:
            return NameResolution(
                distribution=distribution,
                module=module,
                resolution=Resolution.TABLE,
                detail=(
                    f"not installed, so metadata cannot say. Taken from a hand-curated table "
                    f"of {len(KNOWN_DIFFERENT)} entries -- the only source that works for an "
                    f"absent package, and a guess that goes stale"
                ),
            )

    if looks_like_a_module(distribution):
        return NameResolution(
            distribution=distribution,
            module=distribution,
            resolution=Resolution.ASSUMED,
            detail=(
                "not installed and not in the table, so the name was assumed to be its own "
                "module name. Right most of the time, which is exactly why the exceptions "
                "are surprising"
            ),
        )

    underscored = distribution.replace("-", "_")
    if looks_like_a_module(underscored):
        return NameResolution(
            distribution=distribution,
            module=underscored,
            resolution=Resolution.ASSUMED,
            detail=(
                f"not installed and not in the table. Hyphens replaced with underscores to "
                f"give {underscored!r}, which is a convention and not a rule"
            ),
        )

    return NameResolution(
        distribution=distribution,
        module=None,
        resolution=Resolution.UNRESOLVED,
        detail=(
            f"{distribution!r} is not installed, is not in the table, and cannot be made into "
            f"a module name. Nothing can be checked about it"
        ),
    )


def circularity_note(distribution: str) -> str:
    """State plainly whether this particular name can be resolved, and why."""
    installed = from_metadata(distribution) is not None
    if installed:
        return (
            f"{distribution!r} is installed, so its metadata names the module -- and if it is "
            f"installed, the presence check had its answer already."
        )
    return (
        f"{distribution!r} is NOT installed, so there is no metadata to read and the module "
        f"name is unknowable from the system. Any answer now is a guess. The check needs the "
        f"answer in order to ask the question."
    )


def metadata_coverage() -> tuple[int, int, list[str]]:
    """How many installed distributions actually ship `top_level.txt`.

    Reported because the metadata route is the sound one, and it is not universal. Returns
    (with, without, a few examples without).
    """
    with_top = 0
    without: list[str] = []
    for dist in md.distributions():
        name = dist.metadata["Name"]
        if not name:
            continue
        try:
            top = dist.read_text("top_level.txt")
        except (OSError, KeyError):
            top = None
        if top:
            with_top += 1
        else:
            without.append(name)
    return with_top, len(without), sorted(without)[:6]


def unsatisfiable_names(names: list[str]) -> list[tuple[str, str]]:
    """Names that no installation can satisfy, with the reason.

    A hyphenated name in a `find_spec` check is the clearest case: `import python-dateutil` is
    a syntax error, so the check cannot pass whatever is installed. This is the one thing in
    the whole project that `check` gates on, because it is fixable at source by writing the
    other namespace's name.
    """
    found = []
    for name in names:
        if not looks_like_a_module(name):
            resolution = resolve(name)
            target = resolution.module or "nothing importable"
            found.append(
                (
                    name,
                    f"no module can be named {name!r}, so a presence check on it is "
                    f"UNSATISFIABLE -- installing the package cannot make it pass. The "
                    f"importable name is {target!r}",
                )
            )
    return found

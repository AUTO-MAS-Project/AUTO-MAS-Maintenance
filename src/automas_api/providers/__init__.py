"""Official mainland China announcement sources."""

from .arknights import fetch as fetch_arknights
from .endfield import fetch as fetch_endfield

PROVIDERS = {"arknights": fetch_arknights, "endfield": fetch_endfield}

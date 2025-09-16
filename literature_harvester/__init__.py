"""Literature Harvester Library
A modular library for harvesting academic literature from multiple sources.
"""

from .config import Config
from .harvester import LiteratureHarvester

__version__ = "1.0.0"
__all__ = ["Config", "LiteratureHarvester"]
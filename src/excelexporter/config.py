import logging
import toml
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class Configuration:
    ignore_sheet_mark: str = field(default="~")
    ignore_field_mark: str = field(default="*")
    custom_generator: str = field(default="GDS2.0")
    input: str = field(default="data")
    output: str = field(default="dist")
    project_root: str = field(default="../")

    @classmethod
    def load(cls, filename: str = "export.toml") -> 'Configuration':
        with open(filename) as f:
            data = toml.load(f)
            config = Configuration(**data)
            return config

    def save(self, filename: str = "export.toml"):
        with open(filename, "w") as f:
            data = asdict(self)
            toml.dump(data, f)

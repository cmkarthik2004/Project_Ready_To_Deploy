import json
import logging
import sys


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        d = {"ts": self.formatTime(record), "level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        if record.exc_info:
            d["exc"] = self.formatException(record.exc_info)
        return json.dumps(d)


def setup_logging(level: str = "INFO") -> None:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(level)
    for noisy in ("httpx", "sentence_transformers", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

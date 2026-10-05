from collector import utc_now, write_json
from .security import text
import threading

class Diagnostics:
    def __init__(self, path): self.path, self.state, self.lock = path, {}, threading.Lock()
    def update(self, **values):
        with self.lock:
            self.state.update(values, updated_at=utc_now())
            write_json(self.path, self.state)
    def error(self, error): self.update(last_error=text(error), connected=False)

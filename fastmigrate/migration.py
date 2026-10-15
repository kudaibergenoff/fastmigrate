from abc import ABC, abstractmethod

class Migration(ABC):
    @abstractmethod
    def up(self):
        """Apply migration."""

    @abstractmethod
    def down(self):
        """Reverse migration."""

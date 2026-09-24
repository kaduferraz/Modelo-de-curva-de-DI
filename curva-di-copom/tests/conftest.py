import sys
from pathlib import Path

# Permite rodar `pytest` sem instalar o pacote
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

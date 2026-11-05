"""Registro dos atendimentos encaminhados à equipe.

O banco de dados é somente leitura e reconstruído pelo ETL, então os encaminhamentos ficam em um
arquivo próprio, com um registro JSON por linha. Em produção, iriam para uma fila ou um CRM.
"""

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from contracts.schemas import EscalationReceipt

ESCALATIONS_PATH = Path(__file__).parent / "escalations.jsonl"

# Prazo definido no manual da loja, seção 7.3.
RESPONSE_DEADLINE = "24 horas úteis"


class EscalationLog:
    def __init__(self, path=ESCALATIONS_PATH):
        self.path = Path(path)
        self._lock = threading.Lock()

    def register(self, request):
        protocol = uuid.uuid4().hex[:8].upper()
        entry = {
            "protocol": protocol,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **request.model_dump(),
        }
        with self._lock, self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return EscalationReceipt(protocol=protocol, response_deadline=RESPONSE_DEADLINE)

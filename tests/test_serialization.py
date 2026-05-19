from __future__ import annotations

import json
import unittest
from decimal import Decimal
from uuid import uuid4

from sentinel_core.serialization import to_jsonable


class SerializationTests(unittest.TestCase):
    def test_decimal_uuid_are_jsonable(self):
        payload = {"value": Decimal("1.23"), "id": uuid4()}
        json.dumps(to_jsonable(payload))


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-

# (C) Copyright 2025-2026 IBM. All Rights Reserved.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.
# tests/test_versions_endpoint.py
import unittest
from fastapi.testclient import TestClient
from qsa_sim.api import app


class QSAVersionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        self._orig = getattr(app, "list_api_versions", None)

    def tearDown(self):
        setattr(app, "list_api_versions", self._orig)

    def test_versions(self):
        cases = [
            (None, {"versions": None}),
            (["2025-08-01", "2025-08-15"], {"versions": ["2025-08-01", "2025-08-15"]}),
        ]
        for given, expected in cases:
            with self.subTest(given=given):
                app.list_api_versions = given
                resp = self.client.get("/versions")
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json(), expected)

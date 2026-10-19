import os
import tempfile
import unittest

import seed


class DBTest(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.conn = seed.seed(self.path)

    def tearDown(self):
        self.conn.close()
        os.remove(self.path)

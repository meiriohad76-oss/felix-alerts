from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DeploymentAssetTests(unittest.TestCase):
    def test_raspberry_pi_service_declares_backend_pythonpath(self):
        service = (ROOT / "deploy" / "raspberry-pi" / "sentinel.service").read_text()
        env_example = (ROOT / "deploy" / "raspberry-pi" / "env.example").read_text()
        deployment_doc = (ROOT / "docs" / "DEPLOYMENT.md").read_text()

        self.assertIn("PYTHONPATH=/opt/sentinel/backend", service)
        self.assertIn("PYTHONPATH=/opt/sentinel/backend", env_example)
        self.assertIn("HOST=127.0.0.1", env_example)
        self.assertIn("HOST=127.0.0.1", deployment_doc)
        self.assertIn("Do not expose port 8765 directly on the LAN", deployment_doc)

    def test_raspberry_pi_backup_and_restore_scripts_are_present(self):
        backup = (ROOT / "deploy" / "raspberry-pi" / "backup_database.sh").read_text()
        restore = (ROOT / "deploy" / "raspberry-pi" / "restore_database.sh").read_text()
        deployment_doc = (ROOT / "docs" / "DEPLOYMENT.md").read_text()

        self.assertIn("set -euo pipefail", backup)
        self.assertIn("sqlite3 \"$DB_PATH\" \".backup '$BACKUP_PATH'\"", backup)
        self.assertIn("find \"$BACKUP_DIR\" -name 'sentinel-*.sqlite3' -type f -mtime +\"$RETENTION_DAYS\" -delete", backup)
        self.assertIn("systemctl stop sentinel", restore)
        self.assertIn("sqlite3 \"$RESTORE_PATH\" \"PRAGMA integrity_check;\"", restore)
        self.assertIn("PRE_RESTORE_BACKUP", restore)
        self.assertIn("cp \"$RESTORE_PATH\" \"$DB_PATH\"", restore)
        self.assertIn("systemctl start sentinel", restore)
        self.assertIn("sudo /opt/sentinel/deploy/raspberry-pi/backup_database.sh", deployment_doc)
        self.assertIn("sudo /opt/sentinel/deploy/raspberry-pi/restore_database.sh", deployment_doc)


if __name__ == "__main__":
    unittest.main()

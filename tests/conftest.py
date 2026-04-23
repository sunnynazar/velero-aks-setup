"""
Shared pytest fixtures and sys.path / module stubs.

The Azure SDK has a broken cffi/Rust backend in this environment, so we
inject lightweight sys.modules stubs for all azure.* imports before any
test file is collected. The actual SDK clients are always mocked in tests
anyway, so the stubs just need to be importable.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

# Make scripts/ importable without installing as a package
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

# ---------------------------------------------------------------------------
# Real exception classes that tests can raise / catch
# ---------------------------------------------------------------------------

class ResourceNotFoundError(Exception):
    pass

class ResourceExistsError(Exception):
    pass

# ---------------------------------------------------------------------------
# Build minimal azure.* stub modules
# ---------------------------------------------------------------------------

def _mock_module(*names: str) -> MagicMock:
    m = MagicMock()
    m.__name__ = names[-1]
    return m

# azure.core.exceptions needs real exception classes
_exceptions_mod = _mock_module("azure", "core", "exceptions")
_exceptions_mod.ResourceNotFoundError = ResourceNotFoundError
_exceptions_mod.ResourceExistsError   = ResourceExistsError

_azure_core = _mock_module("azure", "core")
_azure_core.exceptions = _exceptions_mod

_azure = _mock_module("azure")
_azure.core = _azure_core

_azure_mgmt_storage_models = _mock_module("azure", "mgmt", "storage", "models")

AZURE_STUBS: dict[str, MagicMock] = {
    "azure":                                        _azure,
    "azure.core":                                   _azure_core,
    "azure.core.exceptions":                        _exceptions_mod,
    "azure.identity":                               _mock_module("azure", "identity"),
    "azure.mgmt":                                   _mock_module("azure", "mgmt"),
    "azure.mgmt.authorization":                     _mock_module("azure", "mgmt", "authorization"),
    "azure.mgmt.authorization.models":              _mock_module("azure", "mgmt", "authorization", "models"),
    "azure.mgmt.containerservice":                  _mock_module("azure", "mgmt", "containerservice"),
    "azure.mgmt.containerservice.models":           _mock_module("azure", "mgmt", "containerservice", "models"),
    "azure.mgmt.msi":                               _mock_module("azure", "mgmt", "msi"),
    "azure.mgmt.msi.models":                        _mock_module("azure", "mgmt", "msi", "models"),
    "azure.mgmt.resource":                          _mock_module("azure", "mgmt", "resource"),
    "azure.mgmt.resource.resources":                _mock_module("azure", "mgmt", "resource", "resources"),
    "azure.mgmt.resource.resources.models":         _mock_module("azure", "mgmt", "resource", "resources", "models"),
    "azure.mgmt.storage":                           _mock_module("azure", "mgmt", "storage"),
    "azure.mgmt.storage.models":                    _azure_mgmt_storage_models,
}

for mod_name, stub in AZURE_STUBS.items():
    sys.modules.setdefault(mod_name, stub)

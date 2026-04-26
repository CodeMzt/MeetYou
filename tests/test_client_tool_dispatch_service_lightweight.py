from __future__ import annotations

import unittest
from types import SimpleNamespace

from core.services.client_tool_dispatch_service import ClientToolDispatchError, ClientToolDispatchService


class _ClientService:
    def __init__(self, clients, workspace_bindings):
        self.clients = clients
        self.workspace_bindings = workspace_bindings

    def get_by_client_id(self, client_id):
        return self.clients.get(client_id)

    def is_bound_to_workspace(self, *, client_id, workspace_id):
        return (client_id, workspace_id) in self.workspace_bindings

    def list_tool_clients_for_workspace(self, *, workspace_id, tool_key):
        return [
            (client, SimpleNamespace(workspace_id=workspace_id))
            for client in self.clients.values()
            if (client.client_id, workspace_id) in self.workspace_bindings
            and tool_key in set(client.executable_tools)
        ]


def _service(*, clients, workspace_bindings):
    return ClientToolDispatchService(
        client_service=_ClientService(clients, workspace_bindings),
        capability_service=SimpleNamespace(),
        session_service=SimpleNamespace(),
        thread_service=SimpleNamespace(),
        workspace_service=SimpleNamespace(),
        operation_service=SimpleNamespace(),
        operation_call_service=SimpleNamespace(),
    )


class ClientToolDispatchServiceLightweightTests(unittest.TestCase):
    def test_source_available_tools_are_enforced(self):
        service = _service(
            clients={
                "web": SimpleNamespace(client_id="web", available_tools=["memory.search"], executable_tools=[]),
            },
            workspace_bindings=set(),
        )

        with self.assertRaises(ClientToolDispatchError) as error_context:
            service._assert_source_can_start(source_client_id="web", tool_key="shell.exec")  # noqa: SLF001

        self.assertEqual(error_context.exception.tool_error_code, "tool_not_available_for_source_client")

    def test_target_unavailable_does_not_fallback(self):
        service = _service(clients={}, workspace_bindings=set())
        workspace = SimpleNamespace(id=1, workspace_id="desktop-main")

        with self.assertRaises(ClientToolDispatchError) as error_context:
            service._select_target_client(  # noqa: SLF001
                tool_key="file.read",
                workspace=workspace,
                target_client_id="missing-client",
            )

        self.assertEqual(error_context.exception.tool_error_code, "target_client_unavailable")

    def test_selects_source_client_when_it_can_execute_tool(self):
        client = SimpleNamespace(
            client_id="desktop-main",
            display_name="Desktop",
            client_type="desktop",
            status="ready",
            available_tools=["file.read"],
            executable_tools=["file.read"],
        )
        workspace = SimpleNamespace(id=1, workspace_id="desktop-main")
        service = _service(clients={"desktop-main": client}, workspace_bindings={("desktop-main", 1)})

        selected = service._select_target_client(  # noqa: SLF001
            tool_key="file.read",
            workspace=workspace,
            source_client_id="desktop-main",
        )

        self.assertIs(selected, client)


if __name__ == "__main__":
    unittest.main()

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "windows-agent"))
sys.path.insert(0, str(ROOT))

import main  # noqa: E402


class FakeWebSocket:
    def __init__(self, messages):
        self.client = SimpleNamespace(host="127.0.0.1")
        self.headers = {}
        self.messages = list(messages)
        self.sent = []
        self.closed = []

    async def accept(self):
        pass

    async def receive_text(self):
        if self.messages:
            return self.messages.pop(0)
        raise main.WebSocketDisconnect()

    async def send_json(self, payload):
        self.sent.append(payload)

    async def close(self, code=None, reason=None):
        self.closed.append((code, reason))


class MainRouteTests(unittest.TestCase):
    def test_root_has_an_ascii_service_identifier_for_legacy_powershell(self):
        response = main.root()

        self.assertEqual(response["service"], "pipa-windows-agent")
        self.assertEqual(response["status"], "online")

    def test_reload_route_requires_launcher_header_and_requests_current_server_shutdown(self):
        invalid_request = SimpleNamespace(headers={"x-pipa-reload": "0"})

        server = SimpleNamespace(should_exit=False)

        async def invoke_reload():
            with self.assertRaises(main.HTTPException) as error:
                await main.api_internal_reload(invalid_request)
            self.assertEqual(error.exception.status_code, 403)

            valid_request = SimpleNamespace(headers={"x-pipa-reload": "1"})
            with patch("main._uvicorn_server", server):
                response = await main.api_internal_reload(valid_request)
                self.assertTrue(response["success"])
                self.assertTrue(response["restarting"])
                self.assertFalse(server.should_exit)
                await asyncio.sleep(0.1)

        asyncio.run(invoke_reload())
        self.assertTrue(server.should_exit)

    @patch.dict("main.os.environ", {}, clear=True)
    @patch("main.get_capabilities", return_value={"success": True, "integrations": {}})
    def test_capabilities_route_is_read_only(self, get_capabilities):
        response = main.api_capabilities()

        self.assertTrue(response["success"])
        get_capabilities.assert_called_once_with(
            serial_gateway_configured=False,
            serial_gateway_running=False,
            serial_gateway_connected=False,
            mobile_gateway_configured=False,
            mobile_gateway_running=False,
            mobile_gateway_connected=False,
        )

    @patch.dict("main.os.environ", {"PIPA_SERIAL_PORT": "COM7"}, clear=False)
    @patch("main.get_capabilities", return_value={"success": True, "integrations": {}})
    def test_capabilities_distinguish_configured_gateway_from_running_worker(self, get_capabilities):
        main.api_capabilities()

        get_capabilities.assert_called_once_with(
            serial_gateway_configured=True,
            serial_gateway_running=False,
            serial_gateway_connected=False,
            mobile_gateway_configured=False,
            mobile_gateway_running=False,
            mobile_gateway_connected=False,
        )

    @patch.dict("main.os.environ", {"PIPA_SERIAL_SECURITY": "v2"}, clear=True)
    def test_protocol_reports_the_explicit_serial_security_mode(self):
        response = main.api_pipa_protocol()

        self.assertEqual(response["serial_gateway_security"], "v2")

    @patch("main.open_apple_music", return_value={"success": True, "target": "desktop_app"})
    @patch("main.open_whatsapp_web", return_value={"success": True, "url": "https://web.whatsapp.com/"})
    @patch("main.open_discord_app", return_value={"success": True, "call_started": False})
    def test_new_integration_routes_delegate_to_safe_adapters(self, open_discord, open_whatsapp, open_music):
        self.assertEqual(main.api_music_open()["target"], "desktop_app")
        self.assertEqual(main.api_whatsapp_open()["success"], True)
        self.assertEqual(main.api_discord_open()["call_started"], False)
        open_music.assert_called_once_with()
        open_whatsapp.assert_called_once_with()
        open_discord.assert_called_once_with()

    @patch("main.webbrowser.open", return_value=True)
    def test_music_search_reports_that_playback_was_not_started(self, open_browser):
        response = main.api_music_search(main.MusicRequest(term="Daft Punk"))

        self.assertFalse(response["playback_started"])
        self.assertTrue(response["requires_manual_selection"])
        open_browser.assert_called_once()

    @patch("main.webbrowser.open", return_value=True)
    def test_external_url_routes_never_return_the_destination(self, open_browser):
        responses = [
            main.api_open_url(main.UrlRequest(url="https://example.com")),
            main.api_web_search(main.QueryRequest(query="Pipa")),
            main.api_music_search(main.MusicRequest(term="Daft Punk")),
            main.api_whatsapp_compose(main.WhatsAppRequest(phone="+34600123456", message="Hola")),
            main.api_discord_channel_open(main.DiscordChannelRequest(channel_id="12345678901234567")),
        ]

        for response in responses:
            self.assertNotIn("url", response)
        self.assertEqual(open_browser.call_count, 5)

    @patch("main.resolve_whatsapp_contact", return_value=("mama", "34600123456"))
    @patch("main.resolve_discord_contact", return_value=("amigo", "12345678901234567", None))
    @patch("main.webbrowser.open", return_value=True)
    def test_contact_routes_resolve_locally_without_returning_destination_urls(
        self, open_browser, resolve_discord, resolve_whatsapp
    ):
        whatsapp = main.api_whatsapp_contact_compose(
            main.ContactMessageRequest(contact="mama", message="Hola")
        )
        discord = main.api_discord_contact_open(main.ContactRequest(contact="amigo"))

        self.assertFalse(whatsapp["sent"])
        self.assertTrue(whatsapp["requires_manual_send"])
        self.assertFalse(discord["call_started"])
        self.assertNotIn("url", whatsapp)
        self.assertNotIn("url", discord)
        resolve_whatsapp.assert_called_once_with("mama")
        resolve_discord.assert_called_once_with("amigo")
        self.assertEqual(open_browser.call_count, 2)

    @patch("main.resolve_discord_contact", return_value=("amigo", "12345678901234567", None))
    @patch(
        "main.open_discord_call",
        return_value={
            "success": True,
            "call_started": False,
            "requires_manual_call": True,
        },
    )
    def test_discord_call_route_never_starts_the_call(self, open_call, resolve_contact):
        response = main.api_discord_contact_call(main.ContactRequest(contact="amigo"))

        self.assertFalse(response["call_started"])
        self.assertTrue(response["requires_manual_call"])
        self.assertNotIn("contact", response)
        resolve_contact.assert_called_once_with("amigo")
        open_call.assert_called_once_with("12345678901234567", None)

    @patch(
        "main.open_discord_call",
        return_value={
            "success": True,
            "call_started": False,
            "requires_manual_call": True,
        },
    )
    def test_discord_channel_call_route_never_starts_the_call(self, open_call):
        response = main.api_discord_channel_call(
            main.DiscordChannelRequest(
                channel_id="12345678901234567",
                guild_id="98765432109876543",
            )
        )

        self.assertFalse(response["call_started"])
        self.assertTrue(response["requires_manual_call"])
        open_call.assert_called_once_with("12345678901234567", "98765432109876543")

    @patch("main.open_league", return_value={"success": True, "target": "allowlisted_app"})
    @patch("main.with_client_or_launch")
    def test_league_search_route_can_launch_the_allowlisted_client(self, with_client_or_launch, open_league):
        with_client_or_launch.return_value = {"started": True, "client_started": True}

        response = main.api_league_search(main.LeagueQueueRequest(queue="normal"))

        self.assertEqual(response, {"started": True, "client_started": True})
        callback, launcher = with_client_or_launch.call_args.args
        self.assertIs(launcher, open_league)
        self.assertEqual(callback(SimpleNamespace(start_search=lambda queue: queue)), "normal")

    @patch("main.with_client_or_launch", side_effect=main.LeagueClientError("private token detail"))
    def test_league_search_route_hides_client_error_details(self, with_client_or_launch):
        with self.assertRaises(main.HTTPException) as error:
            main.api_league_search(main.LeagueQueueRequest(queue="normal"))

        self.assertEqual(error.exception.status_code, 503)
        self.assertEqual(error.exception.detail, "League no está disponible ahora.")
        self.assertNotIn("token", error.exception.detail)
        with_client_or_launch.assert_called_once()

    @patch("main.with_client")
    def test_league_wait_route_only_observes_matchmaking(self, with_client):
        with_client.return_value = {
            "found": True,
            "searching": False,
            "match_found": True,
            "timed_out": False,
        }

        response = main.api_league_wait(main.LeagueWaitRequest(seconds=45))

        self.assertTrue(response["found"])
        callback = with_client.call_args.args[0]
        self.assertEqual(callback(SimpleNamespace(wait_for_match=lambda seconds: seconds)), 45)

    @patch("main.resolve_whatsapp_contact", return_value=("mama", "34600123456"))
    @patch("main.webbrowser.open", return_value=True)
    def test_whatsapp_contact_open_never_prepares_a_message(self, open_browser, resolve_contact):
        response = main.api_whatsapp_contact_open(main.ContactRequest(contact="mama"))

        self.assertTrue(response["success"])
        self.assertFalse(response["sent"])
        self.assertNotIn("contact", response)
        self.assertNotIn("url", response)
        resolve_contact.assert_called_once_with("mama")
        open_browser.assert_called_once_with("https://wa.me/34600123456")

    @patch("main.webbrowser.open", return_value=True)
    def test_whatsapp_phone_open_never_prepares_or_sends_a_message(self, open_browser):
        response = main.api_whatsapp_phone_open(main.WhatsAppPhoneRequest(phone="+34 600 123 456"))

        self.assertTrue(response["success"])
        self.assertFalse(response["sent"])
        self.assertNotIn("url", response)
        open_browser.assert_called_once_with("https://wa.me/34600123456")

    def test_new_routes_are_registered(self):
        paths = {route.path for route in main.app.routes}
        self.assertTrue(
            {
                "/commands",
                "/integrations/status",
                "/music/open",
                "/whatsapp/open",
                "/whatsapp/contact/compose",
                "/whatsapp/contact/open",
                "/whatsapp/phone/open",
                "/discord/open",
                "/discord/contact/open",
                "/discord/contact/call",
                "/self-test",
                "/readiness",
                "/league/search/wait",
            }.issubset(paths)
        )

    @patch("main.get_command_catalog", return_value=[{"id": "league_status"}])
    def test_commands_route_is_read_only_and_non_sensitive(self, get_command_catalog):
        response = main.api_commands()

        self.assertEqual(response, {"success": True, "commands": [{"id": "league_status"}]})
        get_command_catalog.assert_called_once_with()

    @patch("main.get_integration_capabilities", return_value={"league": {"client_ready": False}})
    def test_integration_status_route_is_read_only_and_minimal(self, get_integration_capabilities):
        response = main.api_integration_status()

        self.assertEqual(
            response,
            {"success": True, "integrations": {"league": {"client_ready": False}}},
        )
        get_integration_capabilities.assert_called_once_with()

    @patch(
        "main.inspect_readiness",
        return_value={
            "success": True,
            "apps": {"configured_count": 2, "unresolved_count": 0},
            "contacts": {"configured_count": 1, "whatsapp_destinations": 1, "discord_destinations": 0},
            "integrations": {"whatsapp": {"contact_aliases_configured": True}},
        },
    )
    def test_readiness_route_is_read_only_and_bounded(self, inspect_readiness):
        response = main.api_readiness()

        self.assertTrue(response["success"])
        self.assertNotIn("phone", str(response).lower())
        self.assertNotIn("path", str(response).lower())
        inspect_readiness.assert_called_once_with()

    @patch("main.get_self_test", return_value={"success": True, "checks": {}})
    def test_self_test_route_is_read_only(self, get_self_test):
        response = main.api_self_test()

        self.assertTrue(response["success"])
        get_self_test.assert_called_once_with(
            serial_gateway_configured=False,
            serial_gateway_running=False,
            serial_gateway_connected=False,
            mobile_gateway_configured=False,
            mobile_gateway_running=False,
            mobile_gateway_connected=False,
        )

    def test_external_routes_require_explicit_local_confirmation_header(self):
        request = SimpleNamespace(
            method="POST",
            headers={"x-pipa-local-request": "1"},
            url=SimpleNamespace(path="/music/open"),
        )

        response = asyncio.run(main.protect_local_http(request, lambda _request: None))

        self.assertEqual(response.status_code, 403)
        self.assertIn("confirmación local", response.body.decode("utf-8"))
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_every_external_route_is_registered_and_confirmation_gated(self):
        expected_paths = frozenset(
            {
                "/open-app",
                "/open-url",
                "/web/search",
                "/music/open",
                "/music/search",
                "/league/open",
                "/league/search",
                "/whatsapp/open",
                "/whatsapp/compose",
                "/whatsapp/contact/compose",
                "/whatsapp/contact/open",
                "/whatsapp/phone/open",
                "/discord/open",
                "/discord/channel/open",
                "/discord/channel/call",
                "/discord/contact/open",
                "/discord/contact/call",
                "/codex/open",
                "/system/lock",
            }
        )
        self.assertEqual(main.LOCAL_CONFIRMATION_PATHS, expected_paths)
        registered_paths = {route.path for route in main.app.routes}
        self.assertTrue(expected_paths.issubset(registered_paths))

        for path in expected_paths:
            with self.subTest(path=path):
                request = SimpleNamespace(
                    method="POST",
                    headers={"x-pipa-local-request": "1"},
                    url=SimpleNamespace(path=path),
                )
                response = asyncio.run(main.protect_local_http(request, lambda _request: None))
                self.assertEqual(response.status_code, 403)

    def test_external_routes_pass_after_both_local_headers(self):
        request = SimpleNamespace(
            method="POST",
            headers={
                "x-pipa-local-request": "1",
                "x-pipa-local-confirmation": "1",
            },
            url=SimpleNamespace(path="/music/open"),
        )

        async def call_next(_request):
            return main.JSONResponse({"success": True})

        response = asyncio.run(main.protect_local_http(request, call_next))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_validation_errors_do_not_echo_sensitive_input(self):
        error = main.RequestValidationError(
            [
                {
                    "type": "string_too_short",
                    "loc": ("body", "message"),
                    "msg": "String should have at least 1 character",
                    "input": "https://example.invalid/private-message",
                }
            ]
        )

        response = asyncio.run(main.handle_request_validation(None, error))

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.body.decode("utf-8"), '{"detail":"Solicitud no válida."}')
        self.assertNotIn(b"example.invalid", response.body)
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_controlled_route_errors_use_fixed_public_messages(self):
        with patch(
            "main.validate_external_url", side_effect=ValueError("private URL https://secret.invalid")
        ):
            with self.assertRaises(main.HTTPException) as url_error:
                main.api_open_url(main.UrlRequest(url="https://secret.invalid/private"))
        self.assertEqual(url_error.exception.detail, "La URL no es válida.")
        self.assertNotIn("secret.invalid", str(url_error.exception.detail))

        with patch("main.open_whatsapp_compose", side_effect=ValueError("private message and phone")):
            with self.assertRaises(main.HTTPException) as whatsapp_error:
                main.api_whatsapp_compose(
                    main.WhatsAppRequest(phone="+34600123456", message="private message")
                )
        self.assertEqual(whatsapp_error.exception.detail, "La solicitud de WhatsApp no es válida.")
        self.assertNotIn("private", str(whatsapp_error.exception.detail))

        with patch("main.with_client", side_effect=main.LeagueClientError("private token detail")):
            with self.assertRaises(main.HTTPException) as league_error:
                main.api_league_status()
        self.assertEqual(league_error.exception.detail, "League no está disponible ahora.")
        self.assertNotIn("token", str(league_error.exception.detail))

    def test_unexpected_errors_are_generic_and_do_not_echo_internal_details(self):
        error = RuntimeError("/private/apps.json: secret-token")

        response = asyncio.run(main.handle_unexpected_request(None, error))

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.body.decode("utf-8"), '{"detail":"Error interno del agente."}')
        self.assertNotIn(b"private", response.body)
        self.assertNotIn(b"secret-token", response.body)
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_chunked_or_unknown_length_requests_are_bounded(self):
        async def body():
            return b"x" * (main.MAX_REQUEST_BYTES + 1)

        request = SimpleNamespace(
            method="POST",
            headers={"x-pipa-local-request": "1"},
            url=SimpleNamespace(path="/timers"),
            body=body,
        )

        response = asyncio.run(main.protect_local_http(request, lambda _request: None))

        self.assertEqual(response.status_code, 413)

    def test_body_limit_check_replays_valid_body_to_fastapi(self):
        async def invoke():
            events = []
            delivered = False

            async def receive():
                nonlocal delivered
                if delivered:
                    return {"type": "http.disconnect"}
                delivered = True
                return {
                    "type": "http.request",
                    "body": b'{"seconds":1,"label":"middleware-test"}',
                    "more_body": False,
                }

            async def send(message):
                events.append(message)

            scope = {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/timers",
                "raw_path": b"/timers",
                "query_string": b"",
                "headers": [
                    (b"host", b"127.0.0.1:8765"),
                    (b"content-type", b"application/json"),
                    (b"x-pipa-local-request", b"1"),
                ],
                "server": ("127.0.0.1", 8765),
                "client": ("127.0.0.1", 50000),
            }
            await main.app(scope, receive, send)
            return events[0]["status"]

        self.assertEqual(asyncio.run(invoke()), 200)

    def test_websocket_rejects_repeated_invalid_messages_without_reflecting_input(self):
        websocket = FakeWebSocket(['{"type":"' + ("x" * 4000) + '"}'] * main.MAX_PROTOCOL_ERRORS)

        asyncio.run(main.api_pipa_websocket(websocket))

        self.assertEqual(len(websocket.sent), main.MAX_PROTOCOL_ERRORS)
        for response in websocket.sent:
            self.assertEqual(response["code"], "protocol_error")
            self.assertNotIn("x" * 100, str(response))
        self.assertEqual(websocket.closed[-1][0], 1008)

    def test_websocket_rejects_duplicate_json_fields(self):
        websocket = FakeWebSocket(
            ['{"protocol_version":1,"type":"challenge_request","type":"ping"}'] * main.MAX_PROTOCOL_ERRORS
        )

        asyncio.run(main.api_pipa_websocket(websocket))

        self.assertEqual(len(websocket.sent), main.MAX_PROTOCOL_ERRORS)
        self.assertTrue(all(response["code"] == "protocol_error" for response in websocket.sent))
        self.assertEqual(websocket.closed[-1][0], 1008)


if __name__ == "__main__":
    unittest.main()

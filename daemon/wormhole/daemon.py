"""Main Wormhole daemon."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from pathlib import Path
from typing import Any

import websockets.exceptions

from wormhole.control import (
    CloseSessionRequest,
    ControlRequest,
    ErrorResponse,
    GetStatusRequest,
    ListSessionsRequest,
    OpenSessionRequest,
    QuerySessionRequest,
    SessionInfoResponse,
    SessionListResponse,
    StatusResponse,
    SuccessResponse,
    get_socket_path,
    parse_control_request,
)
from wormhole.discovery import DiscoveryAdvertiser
from wormhole.protocol import (
    ClientMessage,
    ErrorMessage,
    EventMessage,
    PendingPermissionInfo,
    ServerMessage,
    SessionInfo,
    WelcomeMessage,
    parse_client_message,
)
from wormhole.persistence import (
    EventPersistence,
    PersistedSession,
    SessionPersistence,
)
from wormhole.session import WormholeSession

logger = logging.getLogger(__name__)


class WormholeDaemon:
    """Main daemon managing sessions and WebSocket connections."""

    def __init__(
        self,
        port: int = 7117,
        enable_discovery: bool = True,
        event_persistence: EventPersistence | None = None,
        session_persistence: SessionPersistence | None = None,
    ) -> None:
        self.port = port
        self.enable_discovery = enable_discovery
        self.sessions: dict[str, WormholeSession] = {}
        self.directory_to_session: dict[Path, str] = {}
        self._clients: set[Any] = set()  # WebSocket connections
        self._control_server: asyncio.Server | None = None
        self._discovery: DiscoveryAdvertiser | None = None
        self._persistence = session_persistence or SessionPersistence()
        self._event_persistence = event_persistence or EventPersistence()

    async def run(self) -> None:
        """Run the daemon."""
        import websockets

        logger.info(
            "Starting Wormhole daemon",
            extra={"port": self.port, "discovery": self.enable_discovery},
        )

        # Restore persisted sessions
        await self._restore_sessions()

        # Start control socket
        await self._start_control_socket()

        # Start mDNS advertisement
        if self.enable_discovery:
            await self._start_discovery()

        # Mobile clients may be slow to respond to pings (network transitions, etc.)
        # Increase timeouts to reduce spurious disconnections
        async with websockets.serve(
            self._handle_connection,
            "0.0.0.0",
            self.port,
            ping_interval=30,  # Send ping every 30 seconds
            ping_timeout=60,   # Wait 60 seconds for pong before closing
        ):
            logger.info(
                "Wormhole daemon ready",
                extra={"port": self.port, "control_socket": str(get_socket_path())},
            )
            print(f"Wormhole daemon listening on port {self.port}")
            print(f"Control socket: {get_socket_path()}")
            try:
                await asyncio.Future()  # Run forever
            finally:
                await self._cleanup()

    async def _start_discovery(self) -> None:
        """Start mDNS discovery advertisement."""
        try:
            self._discovery = DiscoveryAdvertiser(port=self.port)
            await self._discovery.start()
        except Exception as e:
            logger.warning("Failed to start mDNS discovery", exc_info=e)

    async def _restore_sessions(self) -> None:
        """Restore sessions from persistence."""
        persisted = self._persistence.load_sessions()
        if not persisted:
            return

        logger.info(f"Restoring {len(persisted)} persisted sessions")
        for p in persisted:
            try:
                directory = Path(p.directory)
                if not directory.exists():
                    logger.warning(f"Skipping session {p.name}: directory does not exist")
                    self._persistence.remove_session(p.name)
                    continue

                session = self.create_session(name=p.name, directory=directory)
                session.claude_session_id = p.claude_session_id
                session.cost_usd = p.cost_usd

                await session.start()
                logger.info(f"Restored session: {p.name}")
            except Exception as e:
                logger.warning(f"Failed to restore session {p.name}: {e}")
                self._persistence.remove_session(p.name)

    def _persist_session(self, session: WormholeSession) -> None:
        """Persist a session to disk."""
        self._persistence.add_session(PersistedSession(
            name=session.name,
            directory=str(session.directory),
            claude_session_id=session.claude_session_id,
            cost_usd=session.cost_usd,
        ))

    async def _start_control_socket(self) -> None:
        """Start the Unix control socket server."""
        socket_path = get_socket_path()

        # Remove existing socket if present
        if socket_path.exists():
            socket_path.unlink()

        self._control_server = await asyncio.start_unix_server(
            self._handle_control_connection,
            path=str(socket_path),
        )

        # Set permissions so only current user can access
        os.chmod(socket_path, 0o600)

    async def _cleanup(self) -> None:
        """Clean up resources."""
        logger.info("Shutting down daemon")

        # Persist all sessions before shutdown (for restoration on restart)
        for session in self.sessions.values():
            self._persist_session(session)
        logger.info(f"Persisted {len(self.sessions)} sessions for restart")

        # Stop discovery
        if self._discovery:
            await self._discovery.stop()

        # Close control socket
        if self._control_server:
            self._control_server.close()
            await self._control_server.wait_closed()

        # Remove socket file
        socket_path = get_socket_path()
        if socket_path.exists():
            socket_path.unlink()

        # Stop all sessions (but don't remove from persistence)
        for session in self.sessions.values():
            await session.stop()

        logger.info("Daemon shutdown complete")

    async def _handle_control_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a control socket connection."""
        try:
            data = await reader.readline()
            if not data:
                return

            request = parse_control_request(data.decode().strip())
            response = await self._handle_control_request(request)

            writer.write((response.model_dump_json() + "\n").encode())
            await writer.drain()
        except Exception as e:
            error = ErrorResponse(code="INTERNAL_ERROR", message=str(e))
            writer.write((error.model_dump_json() + "\n").encode())
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def _handle_control_request(self, request: ControlRequest) -> Any:
        """Handle a parsed control request."""
        match request:
            case OpenSessionRequest():
                return await self._handle_open_session(request)
            case CloseSessionRequest():
                return await self._handle_close_session(request)
            case ListSessionsRequest():
                return self._handle_list_sessions()
            case GetStatusRequest():
                return self._handle_get_status()
            case QuerySessionRequest():
                return await self._handle_query_session(request)

    async def _handle_open_session(
        self, request: OpenSessionRequest
    ) -> SuccessResponse | ErrorResponse:
        """Handle open session request."""
        try:
            directory = Path(request.directory).resolve()

            session = self.create_session(
                name=request.name,
                directory=directory,
                options=request.options,
            )

            # Start the session
            await session.start(request.options)

            return SuccessResponse(
                message=f"Session '{request.name}' created in {directory}",
                data={"name": request.name, "directory": str(directory)},
            )
        except ValueError as e:
            return ErrorResponse(code="SESSION_EXISTS", message=str(e))
        except Exception as e:
            return ErrorResponse(code="SDK_ERROR", message=str(e))

    async def _handle_close_session(
        self, request: CloseSessionRequest
    ) -> SuccessResponse | ErrorResponse:
        """Handle close session request."""
        if request.name not in self.sessions:
            return ErrorResponse(
                code="SESSION_NOT_FOUND",
                message=f"Session not found: {request.name}",
            )

        await self.close_session(request.name)
        return SuccessResponse(message=f"Session '{request.name}' closed")

    def _handle_list_sessions(self) -> SessionListResponse:
        """Handle list sessions request."""
        sessions = [
            SessionInfoResponse(
                name=s.name,
                directory=str(s.directory),
                state=s.state.value,
                claude_session_id=s.claude_session_id,
                cost_usd=s.cost_usd,
            )
            for s in self.sessions.values()
        ]
        return SessionListResponse(sessions=sessions)

    def _handle_get_status(self) -> StatusResponse:
        """Handle get status request."""
        return StatusResponse(
            running=True,
            port=self.port,
            machine_name=socket.gethostname(),
            session_count=len(self.sessions),
            connected_clients=len(self._clients),
        )

    async def _handle_query_session(
        self, request: QuerySessionRequest
    ) -> SuccessResponse | ErrorResponse:
        """Handle query session request."""
        session = self.sessions.get(request.name)
        if not session:
            return ErrorResponse(
                code="SESSION_NOT_FOUND",
                message=f"Session not found: {request.name}",
            )

        try:
            await session.query(request.text)
            return SuccessResponse(message="Query sent")
        except Exception as e:
            return ErrorResponse(code="SDK_ERROR", message=str(e))

    def create_session(
        self,
        name: str,
        directory: Path,
        options: dict[str, Any] | None = None,
    ) -> WormholeSession:
        """Create a new session."""
        directory = directory.resolve()

        # Check one-per-directory constraint
        if directory in self.directory_to_session:
            existing = self.directory_to_session[directory]
            raise ValueError(
                f"A session already exists in this directory: {existing}"
            )

        # Create session with shared event persistence
        session = WormholeSession(
            name=name,
            directory=directory,
            event_persistence=self._event_persistence,
        )
        session.set_broadcast_callback(self._broadcast)

        # Set up persistence callback for session updates
        session.set_persistence_callback(self._persist_session)

        self.sessions[name] = session
        self.directory_to_session[directory] = name

        # Persist immediately
        self._persist_session(session)

        return session

    async def close_session(self, name: str) -> None:
        """Close and remove a session (user-initiated)."""
        session = self.sessions.get(name)
        if session:
            await session.stop()
            self.directory_to_session.pop(session.directory, None)
            self.sessions.pop(name, None)
            # Remove from persistence (user explicitly closed)
            self._persistence.remove_session(name)
            # Clear event history (user explicitly closed)
            self._event_persistence.clear_events(name)

    async def _handle_connection(self, websocket: Any) -> None:
        """Handle a new WebSocket connection."""
        self._clients.add(websocket)
        subscribed_sessions: set[str] = set()
        remote = getattr(websocket, 'remote_address', None)
        client_info = f"{remote}" if remote else "unknown"
        logger.debug("Client connected", extra={"client": client_info})

        try:
            async for raw_message in websocket:
                try:
                    msg = parse_client_message(raw_message)
                    await self._handle_message(websocket, msg, subscribed_sessions)
                except Exception as e:
                    error = ErrorMessage(code="INVALID_MESSAGE", message=str(e))
                    await websocket.send(error.model_dump_json())
        except websockets.exceptions.ConnectionClosed as e:
            # Expected when clients disconnect (mobile going to background, network loss, etc.)
            logger.debug(
                "Client disconnected",
                extra={"client": client_info, "code": e.code, "reason": e.reason},
            )
        finally:
            self._clients.discard(websocket)

    async def _handle_message(
        self,
        websocket: Any,
        msg: ClientMessage,
        subscribed: set[str],
    ) -> None:
        """Handle a parsed client message."""
        from wormhole.protocol import (
            ControlMessage,
            HelloMessage,
            InputMessage,
            PermissionResponseMessage,
            SubscribeMessage,
            SyncMessage,
            SyncResponseMessage,
        )

        match msg:
            case HelloMessage():
                welcome = WelcomeMessage(
                    server_version="0.1.0",
                    machine_name=socket.gethostname(),
                    sessions=[
                        SessionInfo(
                            name=s.name,
                            directory=str(s.directory),
                            state=s.state.value,
                            claude_session_id=s.claude_session_id,
                            cost_usd=s.cost_usd,
                            last_activity=s.last_activity,
                            pending_permissions=[
                                PendingPermissionInfo(
                                    request_id=p.request_id,
                                    tool_name=p.tool_name,
                                    tool_input=p.tool_input,
                                    session_name=s.name,
                                    created_at=p.created_at,
                                )
                                for p in s.get_pending_permissions()
                            ],
                        )
                        for s in self.sessions.values()
                    ],
                )
                await websocket.send(welcome.model_dump_json())

            case SubscribeMessage():
                if msg.sessions == "*":
                    subscribed.update(self.sessions.keys())
                else:
                    subscribed.update(msg.sessions)

            case InputMessage():
                session = self.sessions.get(msg.session)
                if session:
                    await session.query(msg.text)

            case PermissionResponseMessage():
                for session in self.sessions.values():
                    if session.respond_to_permission(msg.request_id, msg.decision):
                        break

            case ControlMessage():
                session = self.sessions.get(msg.session)
                if session:
                    match msg.action:
                        case "interrupt":
                            await session.interrupt()
                        case "compact":
                            await session.query("/compact")
                        case "clear":
                            await session.query("/clear")
                        case "plan":
                            await session.query("/plan")

            case SyncMessage():
                session = self.sessions.get(msg.session)
                if session:
                    events = session.get_events_since(msg.last_seen_sequence)
                    response = SyncResponseMessage(
                        session=msg.session,
                        events=[
                            EventMessage(
                                session=msg.session,
                                sequence=e.sequence,
                                timestamp=e.timestamp,
                                message=e.message,
                            )
                            for e in events
                        ],
                        pending_permissions=[
                            PendingPermissionInfo(
                                request_id=p.request_id,
                                tool_name=p.tool_name,
                                tool_input=p.tool_input,
                                session_name=session.name,
                                created_at=p.created_at,
                            )
                            for p in session.get_pending_permissions()
                        ],
                        oldest_available_sequence=session.get_oldest_sequence(),
                    )
                    await websocket.send(response.model_dump_json())

    async def _broadcast(self, msg: ServerMessage) -> None:
        """Broadcast a message to all connected clients."""
        if not self._clients:
            return

        data = msg.model_dump_json()
        await asyncio.gather(
            *[client.send(data) for client in self._clients],
            return_exceptions=True,
        )

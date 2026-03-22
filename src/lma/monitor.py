"""Live packet monitoring TUI using Textual."""

from __future__ import annotations

import textwrap
import time
from datetime import datetime, timezone

from rich.markup import escape as markup_escape

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, Label, Static
from textual.worker import get_current_worker

from lma.api import DEFAULT_REGION, fetch_packets
from lma.db import load_db

MAX_PACKETS = 500


def resolve_name(origin_id: str, db: dict) -> str:
    """Resolve a key prefix to a display name.

    Returns the node name if unambiguous, 'name1/name2?' if multiple matches,
    or the raw 8-char prefix if no match found.
    """
    origin_id = origin_id.lower()
    names = [
        db["nodes"][key]["name"]
        for key in db.get("nodes", {})
        if key.startswith(origin_id) or origin_id.startswith(key[: len(origin_id)])
    ]
    if not names:
        return origin_id[:8]
    if len(names) == 1:
        return names[0]
    return "/".join(names) + "?"


def format_path(path_list: list, db: dict, resolve: bool = True) -> str:
    if not path_list:
        return "direct"
    if not resolve:
        return " → ".join(hop[:8] for hop in path_list)
    return " → ".join(resolve_name(hop, db) for hop in path_list)


def format_payload_type(pt: str) -> str:
    return (pt or "")[:10]


def fmt_key_prefix(key: str) -> str:
    """Format first 3 bytes of a hex key as 'xx xx xx'."""
    k = key.lower().ljust(6, "_")[:6]
    return f"{k[0:2]} {k[2:4]} {k[4:6]}"


def fmt_ts(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return iso


def _build_detail_text(packet: dict, db: dict) -> str:
    p = packet
    node_name = resolve_name(p.get("origin_id", ""), db)
    lines = [
        "[bold]Packet detail[/bold]",
        "",
        f"[dim]Node:[/dim]       {node_name}",
        f"[dim]Origin ID:[/dim]  {p.get('origin_id', '-')}",
        f"[dim]Heard at:[/dim]   {fmt_ts(p.get('heard_at', ''))}",
        f"[dim]Type:[/dim]       {p.get('payload_type', '-')}",
        f"[dim]Route:[/dim]      {p.get('route_type', '-')}",
        f"[dim]SNR:[/dim]        {p.get('snr', '-')}",
        f"[dim]RSSI:[/dim]       {p.get('rssi', '-')}",
        f"[dim]Score:[/dim]      {p.get('score', '-')}",
        "",
    ]

    path = p.get("path") or []
    if not path:
        lines.append("[dim]Path:[/dim]       direct")
    else:
        lines.append("[dim]Path:[/dim]")
        for hop in path:
            name = resolve_name(hop, db)
            lines.append(f"  [dim]{fmt_key_prefix(hop)}[/dim]  {name}")

    decoded = p.get("decoded_payload")
    if decoded:
        lines.append("")
        lines.append("[dim]Decoded payload:[/dim]")
        if isinstance(decoded, dict):
            for k, v in decoded.items():
                lines.append(f"  {k}: {v}")
        else:
            lines.append(f"  {decoded}")

    regions = p.get("regions") or []
    if regions:
        lines.append("")
        lines.append(f"[dim]Regions:[/dim]    {', '.join(regions)}")

    lines += [
        "",
        f"[dim]ID:[/dim]         {p.get('id', '-')}",
        f"[dim]Created:[/dim]    {fmt_ts(p.get('created_at', ''))}",
    ]
    return "\n".join(lines)


class FilterScreen(ModalScreen[dict]):
    """Modal dialog for filtering packets by multiple criteria."""

    DEFAULT_CSS = """
    FilterScreen {
        align: center middle;
    }
    FilterScreen > Static {
        width: 54;
        padding: 1 2 0 2;
        background: $surface;
    }
    FilterScreen > #title {
        padding: 1 2 0 2;
        background: $surface;
        text-style: bold;
    }
    FilterScreen > #hint {
        padding: 0 2 1 2;
        background: $surface;
        color: $text-muted;
        text-style: italic;
    }
    FilterScreen > Input {
        width: 54;
        border: solid $accent;
        background: $surface;
        padding: 0 1;
    }
    """

    BINDINGS = [Binding("escape", "clear_all", "Clear all")]

    def __init__(self, filters: dict):
        super().__init__()
        self._pkt_filters = filters

    def compose(self) -> ComposeResult:
        yield Static("Packet Filters  (name or hex address)", id="title", markup=False)
        yield Static("Observer:", markup=False)
        yield Input(value=self._pkt_filters.get("observer", ""), placeholder="e.g.  gw-home  or  ab cd ef", id="observer")
        yield Static("Any node (observer or in path):", markup=False)
        yield Input(value=self._pkt_filters.get("node", ""), placeholder="e.g.  relay  or  ab cd", id="node")
        yield Static("Node in path:", markup=False)
        yield Input(value=self._pkt_filters.get("path_node", ""), placeholder="e.g.  relay  or  ab cd", id="path_node")
        yield Static("↵ apply · Esc clear all · Tab next field", id="hint", markup=False)

    def on_mount(self) -> None:
        self.query_one("#observer", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._apply()

    def _apply(self) -> None:
        self.dismiss({
            "observer": self.query_one("#observer", Input).value.strip(),
            "node": self.query_one("#node", Input).value.strip(),
            "path_node": self.query_one("#path_node", Input).value.strip(),
        })

    def action_clear_all(self) -> None:
        self.dismiss({"observer": "", "node": "", "path_node": ""})


class PacketDetailScreen(ModalScreen):
    """Full-packet detail view with up/down navigation."""

    DEFAULT_CSS = """
    PacketDetailScreen {
        align: center middle;
    }
    PacketDetailScreen > Static {
        width: 72;
        height: auto;
        max-height: 40;
        border: solid $accent;
        background: $surface;
        padding: 1 2;
        overflow-y: auto;
    }
    """

    BINDINGS = [
        Binding("escape,q", "dismiss", "Close"),
        Binding("up,k", "prev", "Previous"),
        Binding("down,j", "next", "Next"),
    ]

    def __init__(self, packets: list[dict], index: int, db: dict):
        super().__init__()
        self._packets = packets
        self._index = index
        self._db = db

    def compose(self) -> ComposeResult:
        yield Static("", id="content", markup=True)

    def on_mount(self) -> None:
        self._refresh_content()

    def _refresh_content(self) -> None:
        p = self._packets[self._index]
        n = len(self._packets)
        header = f"[dim]({self._index + 1}/{n}  ↑↓ navigate)[/dim]\n"
        self.query_one("#content", Static).update(
            header + _build_detail_text(p, self._db)
        )
        # Keep the underlying table cursor in sync
        self.app.query_one("#packets", DataTable).move_cursor(row=self._index)

    def action_prev(self) -> None:
        if self._index > 0:
            self._index -= 1
            self._refresh_content()

    def action_next(self) -> None:
        if self._index < len(self._packets) - 1:
            self._index += 1
            self._refresh_content()


class PacketMonitorApp(App):
    """Live MeshCore packet monitor."""

    TITLE = "MeshCore Monitor"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("p", "pause", "Pause/Resume"),
        Binding("f", "filter", "Filter"),
        Binding("n", "toggle_names", "Names"),
        Binding("w", "toggle_wrap", "Wrap"),
    ]
    CSS = """
    DataTable {
        height: 1fr;
    }
    #status {
        height: 1;
        background: $panel;
        padding: 0 1;
        color: $text-muted;
    }
    """

    def __init__(self, region: str = DEFAULT_REGION, poll_interval: int = 5):
        super().__init__()
        self.region = region
        self.poll_interval = poll_interval
        self._db: dict = {"nodes": {}}
        self._seen_ids: set[str] = set()
        self._paused = False
        self._pkt_filters: dict = {"observer": "", "node": "", "path_node": ""}
        self._all_packets: list[dict] = []
        self._packets_by_id: dict[str, dict] = {}
        self._displayed: list[dict] = []
        self._resolve_path: bool = True
        self._wrap_path: bool = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield DataTable(id="packets")
        yield Label("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self._db = load_db()
        table = self.query_one("#packets", DataTable)
        table.add_columns("Time", "Observer", "Type", "SNR", "RSSI", "Path")
        table.cursor_type = "row"
        self.sub_title = f"region={self.region}  poll={self.poll_interval}s"
        self._set_status(None)
        self._poll_worker()

    @work(thread=True, exclusive=True)
    def _poll_worker(self) -> None:
        worker = get_current_worker()
        while not worker.is_cancelled:
            try:
                packets = fetch_packets(self.region, limit=500)
                self.call_from_thread(self._ingest_packets, packets)
            except Exception as e:
                self.call_from_thread(self._set_status, str(e))
            for _ in range(self.poll_interval * 10):
                if worker.is_cancelled:
                    return
                time.sleep(0.1)

    def _ingest_packets(self, packets: list[dict]) -> None:
        region = self.region.upper()
        new = [
            p for p in packets
            if p.get("id") not in self._seen_ids
            and region in [r.upper() for r in (p.get("regions") or [])]
        ]
        if not new:
            self._set_status(None)
            return
        for p in new:
            self._seen_ids.add(p["id"])
            self._packets_by_id[p["id"]] = p
        self._all_packets = (new + self._all_packets)[:MAX_PACKETS]
        visible_ids = {p["id"] for p in self._all_packets}
        self._packets_by_id = {k: v for k, v in self._packets_by_id.items() if k in visible_ids}
        if not self._paused:
            self._rebuild_table()
        self._set_status(None)

    def _node_matches(self, term: str, node_id: str) -> bool:
        """True if term matches the node by name substring or hex address prefix."""
        t = term.lower().replace(" ", "")
        return t in resolve_name(node_id, self._db).lower() or node_id.lower().startswith(t)

    def _packet_matches(self, p: dict) -> bool:
        f = self._pkt_filters
        obs_id = p.get("origin_id", "")
        path_ids = p.get("path") or []

        if f["observer"] and not self._node_matches(f["observer"], obs_id):
            return False

        if f["node"]:
            all_ids = [obs_id] + list(path_ids)
            if not any(self._node_matches(f["node"], nid) for nid in all_ids):
                return False

        if f["path_node"] and not any(self._node_matches(f["path_node"], nid) for nid in path_ids):
            return False

        return True

    def _rebuild_table(self) -> None:
        table = self.query_one("#packets", DataTable)
        table.clear()
        self._displayed = [p for p in self._all_packets if self._packet_matches(p)]
        for p in self._displayed:
            heard = p.get("heard_at", "")
            try:
                dt = datetime.fromisoformat(heard.replace("Z", "+00:00"))
                time_str = dt.astimezone().strftime("%H:%M:%S")
            except Exception:
                time_str = heard[:8]
            node = resolve_name(p.get("origin_id", ""), self._db)
            ptype = format_payload_type(p.get("payload_type", ""))
            snr = f"{p['snr']:.1f}" if p.get("snr") is not None else "-"
            rssi = str(p.get("rssi", "-"))
            path = format_path(p.get("path") or [], self._db, resolve=self._resolve_path)
            if self._wrap_path:
                wrap_width = max(20, self.size.width - 58)
                lines = textwrap.wrap(path, width=wrap_width) or [path]
                path_cell = "\n".join(lines)
                row_height = len(lines)
            else:
                path_cell = path
                row_height = 1
            table.add_row(time_str, node, ptype, snr, rssi, path_cell, height=row_height, key=p["id"])

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if not self._displayed:
            return
        self.push_screen(PacketDetailScreen(self._displayed, event.cursor_row, self._db))

    def action_toggle_names(self) -> None:
        self._resolve_path = not self._resolve_path
        self._rebuild_table()
        self._set_status(None)

    def action_toggle_wrap(self) -> None:
        self._wrap_path = not self._wrap_path
        self._rebuild_table()
        self._set_status(None)

    def _set_status(self, error: str | None) -> None:
        state = "[PAUSED]" if self._paused else "[LIVE]"
        parts = []
        if self._pkt_filters["observer"]: parts.append(f"obs={markup_escape(self._pkt_filters['observer'])}")
        if self._pkt_filters["node"]: parts.append(f"node={markup_escape(self._pkt_filters['node'])}")
        if self._pkt_filters["path_node"]: parts.append(f"path={markup_escape(self._pkt_filters['path_node'])}")
        filt = f"  ({', '.join(parts)})" if parts else ""
        names = "  path:names" if self._resolve_path else "  path:hops"
        wrap = "  wrap:on" if self._wrap_path else ""
        count = len(self._all_packets)
        now = datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S")
        err = f"  ERROR: {error}" if error else ""
        self.query_one("#status", Label).update(
            f"{state}{filt}{names}{wrap}  {count} packets  last: {now}{err}"
        )

    def action_refresh(self) -> None:
        self.workers.cancel_all()
        self._poll_worker()

    def action_pause(self) -> None:
        self._paused = not self._paused
        if not self._paused:
            self._rebuild_table()
        self._set_status(None)

    def action_filter(self) -> None:
        def apply_filter(value: dict | None) -> None:
            if value is not None:
                self._pkt_filters = value
            self._rebuild_table()
            self._set_status(None)

        self.push_screen(FilterScreen(self._pkt_filters), apply_filter)


def run_monitor(region: str = DEFAULT_REGION, poll_interval: int = 5) -> None:
    PacketMonitorApp(region=region, poll_interval=poll_interval).run()

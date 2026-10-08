"""Uplink probing: does the default route actually carry traffic?

`binnacle doctor` and the watchdog both need one question answered per
interface -- can packets get out through it. Every other health signal on
this host is blind to the failure that matters: on 2026-09-12 the USB
adapter held the default route for 48 minutes while 802.11 association,
carrier and the DHCP lease all stayed valid and no packet reached the
router. ChatGPT saw the connector as offline; every local check was green.

So the probes here run end to end, in layers, and report the deepest layer
that still worked:

1. gateway -- ICMP to the route's gateway, bound to the device.
2. dns     -- an A query for the upstream host, sent to the configured
               nameserver from the interface's own source address.
3. tcp     -- a TCP connect to the upstream host, from that same address.

Binding matters because both radios sit on the same /24 here, and binding
a *source address* is not enough: `ip route get 192.168.50.1 from <wlan0
addr>` still answers `dev wlan1` while wlan1 holds the lower metric, so a
probe "from wlan0" would measure wlan1's path. On 2026-09-12 20:31 that is
exactly what happened -- wlan1's air path degraded, the source-bound wlan0
probes failed with it, the watchdog saw "no healthy alternative" and did
not fail over. Every layer therefore binds the *device* (SO_BINDTODEVICE,
allowed unprivileged on this kernel; `ping -I <dev>` does the same).

The TCP layer connects to an address, not a name, so a dead resolver does
not masquerade as a dead path: the address comes from this cycle's DNS
answer, or from the last one that succeeded.

Nothing here changes system state; route changes live in the watchdog.
"""

import json
import secrets
import socket
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

Run = Callable[..., "subprocess.CompletedProcess[str]"]

RESOLV_CONF = Path("/etc/resolv.conf")
UPSTREAM_HOST = "api.openai.com"
UPSTREAM_PORT = 443
#: Layer names in probe order, shallowest first.
LAYERS = ("gateway", "dns", "tcp")


_SUDO_NOARG_FLAGS = frozenset({"-n", "-E", "-H", "-k", "-b", "-P", "-S"})


def sudo_timeout_argv(args: "Sequence[str]", timeout: float) -> list[str]:
    """Insert coreutils `timeout` into a sudo command line, so the timeout
    actually reaches the command being run.

    subprocess's own `timeout=` kills the process IT started. For `sudo ...`
    that process is sudo, not the command. This host's sudoers sets `use_pty`,
    so sudo allocates a pty and forks the real command as its own child:
    killing sudo leaves that child running, orphaned, and reparented to
    systemd --user. On 2026-09-17 a `sudo -n iw dev wlan1 scan` issued with
    timeout=60.0 was still running 5 h 52 min later at 97 % of one core, on a
    4-core machine that had already been killed once that week by resource
    exhaustion. The journal showed sudo's "session opened" with no matching
    "session closed": sudo had been killed, the command had not.

    `timeout` runs on sudo's far side, so it kills the command itself, and it
    exits 124 -- the code `_run` already documents for a timeout.

    Anything that is not a sudo invocation is returned unchanged, and so is a
    sudo line using a flag that takes a value, because inserting `timeout` at
    the wrong position would corrupt the command. Not wrapping is safe; it only
    means that call keeps the old behaviour.
    """
    argv = [str(a) for a in args]
    if not argv or argv[0] != "sudo":
        return argv
    i = 1
    while i < len(argv) and argv[i].startswith("-"):
        if argv[i] not in _SUDO_NOARG_FLAGS:
            return argv  # a flag we do not model; do not guess where to insert
        i += 1
    if i >= len(argv) or argv[i] == "timeout":
        return argv  # nothing to run, or already wrapped
    return argv[:i] + ["timeout", str(max(1, int(timeout)))] + argv[i:]


def _run(*args: str, timeout: float = 10.0) -> "subprocess.CompletedProcess[str]":
    argv = sudo_timeout_argv(args, timeout)
    # When wrapped, coreutils `timeout` must fire first; the outer one is only
    # a backstop for sudo itself hanging before it can exec.
    outer = timeout + 5 if argv != list(args) else timeout
    return subprocess.run(
        argv, capture_output=True, text=True, check=False, timeout=outer
    )


@dataclass(frozen=True, slots=True)
class Route:
    """One default route, as `ip route` reports it."""

    dev: str
    gateway: str
    src: str
    metric: int

    @property
    def label(self) -> str:
        return f"{self.dev} (src {self.src}, metric {self.metric})"


@dataclass(slots=True)
class ProbeResult:
    """Per-layer outcome for one interface."""

    dev: str
    layers: dict[str, bool] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    #: Classifications a layer could add: notes["dns"] is "resolver" when
    #: the system resolver failed but the fallback answered over the same
    #: device (a DNS server problem, not the link), "link" when both failed.
    notes: dict[str, str] = field(default_factory=dict)
    #: Milliseconds each layer took (a latency creeping up is the earliest
    #: sign of a link going bad; the journal keeps it).
    timings: dict[str, float] = field(default_factory=dict)

    @property
    def healthy(self) -> bool:
        """Every probed layer passed."""
        return bool(self.layers) and all(self.layers.values())

    @property
    def wedged(self) -> bool:
        """No layer passed: the interface is up but carries nothing."""
        return bool(self.layers) and not any(self.layers.values())

    @property
    def unavailable(self) -> bool:
        """The probe could not run at all (see ProbeUnavailable): unknown,
        never a verdict about the route."""
        return not self.layers and bool(self.errors.get("probe"))

    @property
    def dead_end(self) -> bool:
        """The TCP layer failed: whatever else answers, the tunnel cannot
        reach its upstream through this route. A wedge is a dead end; so
        is a route whose gateway pings while nothing beyond it connects."""
        return bool(self.layers) and self.layers.get("tcp") is False

    @property
    def deepest_ok(self) -> str | None:
        """Name of the deepest layer that passed, or None."""
        passed = [name for name in LAYERS if self.layers.get(name)]
        return passed[-1] if passed else None

    @property
    def first_failure(self) -> str | None:
        """Name of the shallowest layer that failed, or None."""
        for name in LAYERS:
            if name in self.layers and not self.layers[name]:
                return name
        return None

    def summary(self) -> str:
        parts = [
            f"{n}={'ok' if self.layers[n] else 'FAIL'}"
            for n in LAYERS
            if n in self.layers
        ]
        return " ".join(parts)

    def detail(self) -> str:
        """`summary()` with the layer timings: gateway=ok(12ms) dns=ok(4ms)."""
        parts = []
        for n in LAYERS:
            if n not in self.layers:
                continue
            verdict = "ok" if self.layers[n] else "FAIL"
            ms = self.timings.get(n)
            parts.append(
                f"{n}={verdict}({ms:.0f}ms)" if ms is not None else f"{n}={verdict}"
            )
        if not parts and self.errors.get("probe"):
            return "probe=unavailable"
        return " ".join(parts)


# -- inputs ------------------------------------------------------------------


def default_routes(run: Run = _run) -> list[Route]:
    """Default routes, lowest metric (most preferred) first.

    Routes without a gateway or a source address are skipped: the probes
    cannot attribute a result without both. `[]` is also what a failed
    `ip route` gives; `read_default_routes` tells the two apart.
    """
    routes, _ = read_default_routes(run)
    return routes


def read_default_routes(run: Run = _run) -> tuple[list[Route], bool]:
    """(default routes, whether `ip route` could be read). A loop that
    acts on "no route" must know the difference between an empty table
    and a failed read: on 2026-09-13 a failed read would have looked like
    every radio losing its route at once."""
    proc = run("ip", "-j", "route", "show", "default")
    if proc.returncode != 0:
        return [], False
    try:
        rows = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return [], False
    out = [
        Route(
            dev=r["dev"],
            gateway=r["gateway"],
            src=r["prefsrc"],
            metric=int(r.get("metric", 0)),
        )
        for r in rows
        if isinstance(r, dict)
        and r.get("dev")
        and r.get("gateway")
        and r.get("prefsrc")
    ]
    return sorted(out, key=lambda r: r.metric), True


def active_route(routes: list[Route]) -> Route | None:
    """The route traffic actually takes: the lowest metric."""
    return routes[0] if routes else None


def nameservers(resolv_conf: Path = RESOLV_CONF) -> list[str]:
    try:
        text = resolv_conf.read_text(encoding="utf-8")
    except OSError:
        return []
    return [
        parts[1]
        for line in text.splitlines()
        if (parts := line.split()) and parts[0] == "nameserver" and len(parts) > 1
    ]


# -- layers ------------------------------------------------------------------

#: Last address each upstream host resolved to, so the TCP layer can still
#: test the path while DNS is down.
_last_address: dict[str, str] = {}


class ProbeUnavailable(Exception):
    """The probe itself cannot run (not the link): e.g. the kernel refuses
    SO_BINDTODEVICE. Callers must treat this as "unknown", never as a
    failed route -- a probe bug must not trigger a reset storm."""


def _bind_device(sock: socket.socket, dev: str | None) -> None:
    if dev:
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, dev.encode())
        except PermissionError as e:
            raise ProbeUnavailable(f"cannot bind to {dev}: {e}") from e


def probe_gateway(
    route: Route, timeout: float = 2.0, run: Run = _run
) -> tuple[bool, str]:
    """ICMP echo to the gateway, bound to the device."""
    try:
        proc = run(
            "ping",
            "-I",
            route.dev,
            "-c",
            "1",
            "-W",
            str(int(max(1, timeout))),
            route.gateway,
            timeout=timeout + 3,
        )
    except subprocess.TimeoutExpired:
        return False, f"ping to {route.gateway} timed out"
    if proc.returncode == 0:
        return True, ""
    return False, f"ping to {route.gateway} via {route.dev} failed"


def _dns_query(name: str) -> tuple[bytes, bytes]:
    """A minimal DNS A query and its transaction id."""
    qid = secrets.token_bytes(2)
    header = qid + b"\x01\x00" + b"\x00\x01" + b"\x00\x00" * 3
    labels = b"".join(bytes([len(p)]) + p.encode("ascii") for p in name.split(".") if p)
    return header + labels + b"\x00" + b"\x00\x01\x00\x01", qid


def _skip_name(data: bytes, pos: int) -> int:
    """Index just past a (possibly compressed) DNS name starting at pos."""
    while pos < len(data):
        length = data[pos]
        if length == 0:
            return pos + 1
        if length & 0xC0 == 0xC0:  # compression pointer: two bytes, then done
            return pos + 2
        pos += 1 + length
    return pos


def _first_a_record(data: bytes) -> str | None:
    """Dotted address of the first A record in a DNS reply, if any."""
    if len(data) < 12:
        return None
    questions = int.from_bytes(data[4:6], "big")
    answers = int.from_bytes(data[6:8], "big")
    pos = 12
    for _ in range(questions):
        pos = _skip_name(data, pos) + 4
    for _ in range(answers):
        pos = _skip_name(data, pos)
        if pos + 10 > len(data):
            return None
        rtype = int.from_bytes(data[pos : pos + 2], "big")
        rdlen = int.from_bytes(data[pos + 8 : pos + 10], "big")
        rdata = data[pos + 10 : pos + 10 + rdlen]
        if rtype == 1 and rdlen == 4:
            return ".".join(str(b) for b in rdata)
        pos += 10 + rdlen
    return None


def probe_dns(
    src: str,
    server: str,
    host: str = UPSTREAM_HOST,
    timeout: float = 3.0,
    port: int = 53,
    dev: str | None = None,
) -> tuple[bool, str, str | None]:
    """Resolve `host` at `server` through `dev`. Returns (ok, error, address)."""
    query, qid = _dns_query(host)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout)
        _bind_device(sock, dev)
        sock.bind((src, 0))
        sock.sendto(query, (server, port))
        data, _ = sock.recvfrom(4096)
    except OSError as e:
        return False, f"DNS {host} at {server} via {dev or src}: {e}", None
    finally:
        sock.close()
    if len(data) < 6 or data[:2] != qid:
        return False, f"DNS {host} at {server}: malformed reply", None
    if int.from_bytes(data[6:8], "big") == 0:
        return False, f"DNS {host} at {server}: no answer records", None
    return True, "", _first_a_record(data)


def probe_tcp(
    src: str,
    host: str = UPSTREAM_HOST,
    port: int = UPSTREAM_PORT,
    timeout: float = 5.0,
    dev: str | None = None,
    address: str | None = None,
) -> tuple[bool, str]:
    """TCP connect to `address` (or `host`) through `dev`."""
    target = address or host
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        _bind_device(sock, dev)
        sock.bind((src, 0))
        sock.connect((target, port))
        return True, ""
    except OSError as e:
        where = f"{host} ({target})" if address else host
        return False, f"TCP {where}:{port} via {dev or src}: {e}"
    finally:
        sock.close()


def probe(
    route: Route,
    host: str = UPSTREAM_HOST,
    nameserver: str | None = None,
    timeout: float = 3.0,
    run: Run = _run,
    fallback_nameserver: str | None = None,
) -> ProbeResult:
    """Run the three layers in order and collect what passed.

    Layers run even after one fails: knowing that the gateway answers but
    DNS does not is what separates a dead radio from a dead resolver. The
    TCP layer uses the address DNS just returned, or the last one it ever
    returned, so it keeps measuring the path when the resolver is down.
    When the system resolver fails, `fallback_nameserver` (a public one)
    is asked over the same device to classify the failure: an answer
    means the resolver is the problem, silence means the link is.
    """
    result = ProbeResult(dev=route.dev)
    try:
        return _probe_layers(
            result, route, host, nameserver, timeout, run, fallback_nameserver
        )
    except ProbeUnavailable as e:
        result.layers.clear()
        result.errors["probe"] = str(e)
        return result


def _probe_layers(
    result: ProbeResult,
    route: Route,
    host: str,
    nameserver: str | None,
    timeout: float,
    run: Run,
    fallback_nameserver: str | None,
) -> ProbeResult:
    started = time.perf_counter()
    okay, err = probe_gateway(route, timeout=timeout, run=run)
    result.timings["gateway"] = (time.perf_counter() - started) * 1000
    result.layers["gateway"] = okay
    if err:
        result.errors["gateway"] = err

    server = nameserver or (nameservers() or [route.gateway])[0]
    started = time.perf_counter()
    okay, err, address = probe_dns(
        route.src, server, host, timeout=timeout, dev=route.dev
    )
    result.timings["dns"] = (time.perf_counter() - started) * 1000
    result.layers["dns"] = okay
    if err:
        result.errors["dns"] = err
    if not okay and fallback_nameserver and fallback_nameserver != server:
        fb_ok, _, fb_address = probe_dns(
            route.src, fallback_nameserver, host, timeout=timeout, dev=route.dev
        )
        if fb_ok:
            result.notes["dns"] = "resolver"
            result.errors["dns"] = (
                f"{err} -- {fallback_nameserver} answers over {route.dev}: "
                "the resolver, not the link"
            )
            address = fb_address
        else:
            result.notes["dns"] = "link"
            result.errors["dns"] = f"{err} -- {fallback_nameserver} too: the link"
    if address:
        _last_address[host] = address
    target = address or _last_address.get(host)

    if target is None:
        result.layers["tcp"] = False
        result.errors["tcp"] = (
            f"TCP {host}: no address (DNS failed and none cached yet)"
        )
    else:
        started = time.perf_counter()
        okay, err = probe_tcp(
            route.src, host, timeout=timeout + 2, dev=route.dev, address=target
        )
        result.timings["tcp"] = (time.perf_counter() - started) * 1000
        result.layers["tcp"] = okay
        if err:
            result.errors["tcp"] = err

    return result


def probe_all(
    routes: list[Route],
    host: str = UPSTREAM_HOST,
    timeout: float = 3.0,
    run: Run = _run,
    fallback_nameserver: str | None = None,
) -> dict[str, ProbeResult]:
    """Probe every default route, keyed by device."""
    found = nameservers()
    server = found[0] if found else None
    return {
        r.dev: probe(
            r,
            host=host,
            nameserver=server,
            timeout=timeout,
            run=run,
            fallback_nameserver=fallback_nameserver,
        )
        for r in routes
    }
